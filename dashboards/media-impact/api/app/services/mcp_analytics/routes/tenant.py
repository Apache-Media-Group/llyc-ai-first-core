# backend/app/services/mcp_analytics/routes/tenant.py
import logging
from typing import Optional

from fastapi import APIRouter, Request, Query, HTTPException, Depends
from pydantic import BaseModel

from app.services.auth_utils import TokenManager
from app.services.auth_middleware import get_current_user, verify_tenant_access

logger = logging.getLogger(__name__)
router = APIRouter()


class TenantConfigResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    logo_url: str
    primary_color: str
    secondary_color: str
    font_family: str
    support_email: str
    configured_secrets: Optional[dict] = None

@router.get("/tenant/config", response_model=TenantConfigResponse)
async def get_tenant_config(request: Request, tenant: Optional[str] = Query(None)):
    """
    Obtiene la configuración visual y de branding de forma dinámica según el subdominio
    o parámetro de consulta (estrategia híbrida), consultando en Firestore con fallback a local.
    """
    # 1. Intentar obtener el tenant desde el host (ej: cliente.dashboard.llyc.global)
    host = request.headers.get("host", "")
    detected_tenant = None
    
    # Si contiene subdominios y no es localhost, extraer el primer segmento
    if host and "localhost" not in host and "127.0.0.1" not in host:
        parts = host.split(".")
        if len(parts) > 2:  # Ej: cliente.dashboard.llyc.global -> ['cliente', 'dashboard', 'llyc', 'global']
            detected_tenant = parts[0].lower().strip()
            
    # 2. Si no se detectó o se pasa como Query (híbrido para demos), usar el parámetro query
    if tenant:
        detected_tenant = tenant.lower().strip()
        
    # 3. Si sigue sin detectarse o es un valor vacío, usar el de LLYC por defecto
    if not detected_tenant or detected_tenant in ["www", "dashboard", "analytics", "media-impact-llyc"]:
        detected_tenant = "llyc"
        
    # 4. Intentar consultar la configuración en vivo en Firestore
    try:
        tm = TokenManager()
        if tm.db:
            doc = tm.db.collection("tenants").document(detected_tenant).get()
            if doc.exists:
                logger.info(f"Configuración de tenant '{detected_tenant}' recuperada con éxito desde Firestore.")
                return doc.to_dict()
    except Exception as e:
        logger.warning(f"No se pudo consultar el tenant '{detected_tenant}' en Firestore (usando fallback local): {e}")

    # 5. Mapeo de bases de datos de inquilinos local (Solo LLYC como fallback del sistema base)
    tenant_database = {
        "llyc": {
            "tenant_id": "llyc",
            "tenant_name": "LLYC Intelligence",
            "logo_url": "/logo_llyc.svg",
            "primary_color": "#E51D24", # Rojo LLYC
            "secondary_color": "#1C2541", # Azul LLYC
            "font_family": "Montserrat, sans-serif",
            "support_email": "intelligence.mcp@llyc.global"
        }
    }
    
    # 6. Obtener configuración o lanzar 404 si es un cliente inexistente (Safeguard de seguridad)
    config = tenant_database.get(detected_tenant)
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"Organización '{detected_tenant}' no registrada en la plataforma analítica de LLYC."
        )
        
    return config


class OTPSendRequest(BaseModel):
    tenant: str

class OTPVerifyRequest(BaseModel):
    tenant: str
    code: str


@router.get("/tenant/verify")
async def verify_tenant_access_endpoint(
    tenant: str = Query(..., description="ID del tenant a verificar"),
    user_email: str = Depends(get_current_user)
):
    """
    Verifica de forma segura si el usuario autenticado por Firebase Auth
    tiene acceso al tenant especificado, comprobando si el 2FA ya está validado.
    Retorna si se requiere 2FA y si ya fue verificado.
    """
    # 1. Validar acceso a Whitelist (sin forzar 2FA aquí para permitir la respuesta descriptiva)
    await verify_tenant_access(tenant, user_email, enforce_2fa=False)
    
    # 2. Comprobar si tiene la sesión 2FA validada
    from app.services.otp_service import otp_service
    is_verified = otp_service.is_2fa_verified(tenant, user_email)
    
    # 3. Determinar si requiere 2FA (superadmins de LLYC no requieren 2FA)
    email_clean = user_email.lower().strip()
    is_superadmin = email_clean.endswith("@llyc.global") or email_clean.endswith("@llyc.ai")
    requires_2fa = not is_superadmin
    
    if requires_2fa and not is_verified:
        return {
            "status": "ok",
            "authorized": False,
            "user_email": user_email,
            "2fa_required": True,
            "2fa_verified": False
        }
        
    return {
        "status": "ok",
        "authorized": True,
        "user_email": user_email,
        "2fa_required": requires_2fa,
        "2fa_verified": is_verified or is_superadmin
    }


@router.post("/auth/otp/send")
async def send_otp_endpoint(
    request: OTPSendRequest,
    user_email: str = Depends(get_current_user)
):
    """
    Genera y envía un código de verificación OTP al email del usuario.
    Primero valida que el usuario esté en la Whitelist del tenant.
    """
    tenant = request.tenant.lower().strip()
    
    # Validar que el usuario tenga acceso whitelist antes de enviarle un OTP
    await verify_tenant_access(tenant, user_email, enforce_2fa=False)
    
    from app.services.otp_service import otp_service
    success = await otp_service.generate_and_send_otp(tenant, user_email)
    if not success:
        raise HTTPException(
            status_code=500,
            detail="No se pudo enviar el código OTP. Por favor, reintente en unos momentos."
        )
        
    return {"status": "ok", "message": "Código de verificación OTP enviado con éxito."}


@router.post("/auth/otp/verify")
async def verify_otp_endpoint(
    request: OTPVerifyRequest,
    user_email: str = Depends(get_current_user)
):
    """
    Valida el código de verificación OTP ingresado por el usuario.
    Si es correcto, crea un registro de sesión 2FA válida por 24 horas.
    """
    tenant = request.tenant.lower().strip()
    code = request.code.strip()
    
    # Validar acceso general a whitelist
    await verify_tenant_access(tenant, user_email, enforce_2fa=False)
    
    from app.services.otp_service import otp_service
    verified = otp_service.verify_otp(tenant, user_email, code)
    if not verified:
        raise HTTPException(
            status_code=400,
            detail="El código de verificación ingresado es incorrecto, ya ha sido utilizado o ha expirado."
        )
        
    return {"status": "ok", "verified": True, "message": "Autenticación de Dos Factores (2FA) completada con éxito."}
