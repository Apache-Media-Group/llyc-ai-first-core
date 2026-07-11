import os
import logging
from typing import Optional
from fastapi import Security, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import firebase_admin
from firebase_admin import auth as firebase_auth, credentials

logger = logging.getLogger(__name__)

# Configuración del esquema de autenticación HTTP Bearer
security = HTTPBearer(auto_error=False)

# Inicializar Firebase Admin SDK de forma segura
# En GCP (Cloud Run), se autentica automáticamente con la Service Account por defecto del host.
try:
    if not firebase_admin._apps:
        # Intenta usar Application Default Credentials (ADC)
        try:
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK inicializado exitosamente usando Application Default Credentials.")
        except Exception as adc_err:
            # Fallback a inicialización sin argumentos (para inicializar de forma perezosa en desarrollo)
            firebase_admin.initialize_app()
            logger.info("Firebase Admin SDK inicializado de forma por defecto.")
except Exception as e:
    logger.warning(f"No se pudo inicializar Firebase Admin SDK de forma nativa: {e}. "
                   f"Se requerirá configuración de variables de entorno de GCP o un bypass de desarrollo.")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    """
    Inyección de dependencia de FastAPI que valida criptográficamente el token JWT 
    de Firebase Auth enviado en la cabecera 'Authorization: Bearer <JWT>'.
    
    Permite un bypass controlado UNICAMENTE en desarrollo local si está habilitado mediante variables de entorno.
    """
    is_production = os.getenv("K_SERVICE") is not None or os.getenv("ENVIRONMENT") == "production"
    bypass_local = os.getenv("BYPASS_AUTH_LOCAL", "false").lower() == "true"
    
    # 1. Si no hay credenciales Bearer
    if not credentials:
        if not is_production and bypass_local:
            dev_user = os.getenv("DEFAULT_USER_EMAIL", "developer@llyc.global")
            logger.info(f"[AUTH BYPASS] Desarrollo local: No JWT provisto. Usando usuario de pruebas: {dev_user}")
            return dev_user
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta la cabecera de autenticación 'Authorization: Bearer <JWT>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    token = credentials.credentials
    
    # 2. Validar el token contra los servidores de Firebase
    try:
        decoded_token = firebase_auth.verify_id_token(token)
        email = decoded_token.get("email")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="El token de autenticación de Firebase no contiene un correo electrónico de usuario válido.",
            )
        return email
        
    except Exception as e:
        # Si la validación falla pero es desarrollo local con bypass habilitado, permitir el fallback
        if not is_production and bypass_local:
            dev_user = os.getenv("DEFAULT_USER_EMAIL", "developer@llyc.global")
            logger.warning(f"[AUTH BYPASS] Error validando JWT ({e}). Usando usuario de pruebas local: {dev_user}")
            return dev_user
            
        logger.error(f"Error de autenticación de Firebase Auth: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token de Firebase inválido o expirado: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_tenant_access(tenant_id: Optional[str], user_email: str, enforce_2fa: bool = False) -> None:
    """
    Verifica si un usuario autenticado por Firebase Auth tiene permisos para visualizar
    o consultar datos de un Tenant específico.
    Si no tiene acceso (o si se requiere 2FA y no se ha completado), lanza HTTPException 403 Forbidden.
    """
    if not tenant_id:
        return  # Si no hay tenant_id, no restringimos por inquilino

    tenant_id_clean = tenant_id.lower().strip()
    user_email_clean = user_email.lower().strip()

    # 1. Bypass para Superadmins de LLYC
    if user_email_clean.endswith("@llyc.global") or user_email_clean.endswith("@llyc.ai"):
        return

    # 2. Si el tenant solicitado es 'llyc', solo permitimos LLYC (ya cubierto por el bypass anterior)
    if tenant_id_clean == "llyc":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: Se requiere una cuenta corporativa de LLYC para acceder a este inquilino.",
        )

    # 3. Consultar configuración del Tenant en Firestore
    try:
        from app.services.auth_utils import TokenManager
        tm = TokenManager()
        if tm.db:
            doc = tm.db.collection("tenants").document(tenant_id_clean).get()
            if doc.exists:
                tdata = doc.to_dict()
                authorized_emails = [e.lower().strip() for e in tdata.get("authorized_emails", [])]
                authorized_domains = [d.lower().strip() for d in tdata.get("authorized_domains", [])]

                # Comprobar email directo
                email_authorized = user_email_clean in authorized_emails

                # Comprobar dominio corporativo
                domain_authorized = False
                email_parts = user_email_clean.split("@")
                if len(email_parts) == 2:
                    domain = email_parts[1]
                    if domain in authorized_domains:
                        domain_authorized = True

                # Si no está autorizado
                if not email_authorized and not domain_authorized:
                    logger.warning(f"❌ [AUTH ERROR] El usuario '{user_email_clean}' intentó acceder al tenant '{tenant_id_clean}' pero no está autorizado.")
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Acceso denegado: Tu cuenta '{user_email}' no está autorizada para ver el dashboard de '{tenant_id_clean}'.",
                    )

                # Si está en whitelist, verificar 2FA si es exigido
                if enforce_2fa:
                    from app.services.otp_service import otp_service
                    if not otp_service.is_2fa_verified(tenant_id_clean, user_email_clean):
                        logger.warning(f"🔒 [2FA REQUIRED] El usuario '{user_email_clean}' está autorizado en whitelist pero aún no ha validado su 2FA para el tenant '{tenant_id_clean}'.")
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="2FA_REQUIRED"
                        )

                return
            else:
                # Si el tenant no existe en Firestore, no autorizar por defecto
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Cliente '{tenant_id_clean}' no registrado en la plataforma.",
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verificando acceso al tenant {tenant_id_clean}: {e}")
        # En caso de error técnico, ser restrictivos excepto si es dev local con bypass habilitado
        is_production = os.getenv("K_SERVICE") is not None or os.getenv("ENVIRONMENT") == "production"
        bypass_local = os.getenv("BYPASS_AUTH_LOCAL", "false").lower() == "true"
        if not is_production and bypass_local:
            logger.warning(f"[AUTH BYPASS] Error validando acceso en dev local. Permitiendo acceso por bypass.")
            return
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno al verificar permisos de acceso al cliente: {str(e)}"
        )


