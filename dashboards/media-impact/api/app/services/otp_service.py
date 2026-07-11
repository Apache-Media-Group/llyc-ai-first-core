import os
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from google.cloud.firestore import SERVER_TIMESTAMP
from app.services.auth_utils import TokenManager
from app.services.mcp_analytics.learning.notification_mgr import NotificationManager

logger = logging.getLogger(__name__)

class OTPService:
    def __init__(self):
        self.tm = TokenManager()
        self.collection_otps = "otps"
        self.collection_sessions = "user_2fa_states"

    @property
    def db(self):
        return self.tm.db

    async def generate_and_send_otp(self, tenant_id: str, email: str) -> bool:
        """
        Genera un código OTP de 6 dígitos, lo guarda en Firestore con una validez de 5 minutos,
        y lo envía por correo electrónico usando NotificationManager.
        """
        if not self.db:
            logger.error("No se pudo iniciar el cliente de Firestore para el servicio de OTP.")
            return False

        tenant_id_clean = tenant_id.lower().strip()
        email_clean = email.lower().strip()

        # 1. Generar código seguro de 6 dígitos
        otp_code = "".join(secrets.choice("0123456789") for _ in range(6))
        
        # 2. Recuperar el nombre del inquilino para personalizar el correo
        tenant_name = "LLYC Intelligence"
        try:
            doc = self.db.collection("tenants").document(tenant_id_clean).get()
            if doc.exists:
                tenant_name = doc.to_dict().get("tenant_name", tenant_name)
        except Exception as e:
            logger.warning(f"Error recuperando nombre del tenant {tenant_id_clean}: {e}")

        # 3. Guardar el código OTP en Firestore (Document ID unico por email_tenant_id)
        # Esto sobreescribe cualquier código previo para el mismo usuario-tenant.
        doc_id = f"{email_clean}_{tenant_id_clean}"
        expires_at = datetime.utcnow() + timedelta(minutes=5)
        
        otp_data = {
            "email": email_clean,
            "tenant_id": tenant_id_clean,
            "code": otp_code,
            "expires_at": expires_at,
            "verified": False,
            "created_at": SERVER_TIMESTAMP
        }

        try:
            self.db.collection(self.collection_otps).document(doc_id).set(otp_data)
            logger.info(f"Código OTP generado y guardado para {email_clean} en tenant {tenant_id_clean}.")
        except Exception as e:
            logger.error(f"Error guardando código OTP en Firestore: {e}")
            return False

        # 4. Enviar el correo electrónico
        # Permitimos un bypass en desarrollo local si SMTP/Sendgrid no están configurados.
        is_production = os.getenv("K_SERVICE") is not None or os.getenv("ENVIRONMENT") == "production"
        bypass_local = os.getenv("BYPASS_AUTH_LOCAL", "false").lower() == "true"

        nm = NotificationManager()
        if not nm.use_sendgrid and not nm.use_smtp and not is_production and bypass_local:
            logger.warning(f"[OTP BYPASS] Desarrollo local: No hay credenciales de email. El código OTP es: {otp_code}")
            return True

        try:
            success = await nm.send_otp_email(email_clean, otp_code, tenant_name)
            if success:
                logger.info(f"Email con OTP enviado exitosamente a {email_clean}")
                return True
            else:
                logger.error(f"Fallo al enviar correo con OTP a {email_clean}")
                # En desarrollo local con bypass, permitimos que pase
                if not is_production and bypass_local:
                    logger.warning(f"[OTP BYPASS] Fallo de envío en local. Permitido por bypass. Código: {otp_code}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Excepción enviando correo con OTP: {e}")
            if not is_production and bypass_local:
                logger.warning(f"[OTP BYPASS] Excepción en local. Permitido por bypass. Código: {otp_code}")
                return True
            return False

    def verify_otp(self, tenant_id: str, email: str, code: str) -> bool:
        """
        Verifica si el código ingresado coincide con el OTP guardado en Firestore y no ha expirado.
        Si es correcto, crea un registro de sesión verificada de 2FA en 'user_2fa_states' válida por 24 horas.
        """
        if not self.db:
            return False

        tenant_id_clean = tenant_id.lower().strip()
        email_clean = email.lower().strip()
        code_clean = code.strip()

        doc_id = f"{email_clean}_{tenant_id_clean}"

        try:
            doc_ref = self.db.collection(self.collection_otps).document(doc_id)
            doc = doc_ref.get()
            if not doc.exists:
                logger.warning(f"No se encontró código OTP para {email_clean} en tenant {tenant_id_clean}.")
                return False

            data = doc.to_dict()
            
            # Verificar si ya está verificado
            if data.get("verified", False):
                logger.warning(f"Código OTP para {email_clean} ya fue utilizado/verificado.")
                return False

            # Verificar expiración
            expires_at = data.get("expires_at")
            if expires_at:
                # Firestore puede retornar datetime consciente de zona horaria o naive
                # Aseguramos naive utc datetime para comparación
                if expires_at.tzinfo is not None:
                    # En entornos Firestore reales, se obtiene en formato datetime con zona UTC
                    expires_at = expires_at.replace(tzinfo=None)
                if expires_at < datetime.utcnow():
                    logger.warning(f"Código OTP para {email_clean} ha expirado.")
                    return False

            # Comparar el código
            if data.get("code") != code_clean:
                logger.warning(f"Código OTP incorrecto provisto por {email_clean}.")
                return False

            # Marcar el OTP como verificado para que no se use de nuevo
            doc_ref.update({"verified": True})

            # Crear sesión verificada por 24 horas
            session_id = f"{email_clean}_{tenant_id_clean}"
            session_expires = datetime.utcnow() + timedelta(hours=24)
            
            session_data = {
                "email": email_clean,
                "tenant_id": tenant_id_clean,
                "verified_at": SERVER_TIMESTAMP,
                "expires_at": session_expires
            }

            self.db.collection(self.collection_sessions).document(session_id).set(session_data)
            logger.info(f"Sesión 2FA de 24 horas creada y verificada para {email_clean} en tenant {tenant_id_clean}.")
            return True

        except Exception as e:
            logger.error(f"Error verificando OTP para {email_clean}: {e}")
            return False

    def is_2fa_verified(self, tenant_id: str, email: str) -> bool:
        """
        Comprueba si el usuario tiene un estado de 2FA activo en Firestore para el inquilino solicitado.
        Permite bypass automático a Superadmins de LLYC.
        """
        email_clean = email.lower().strip()
        tenant_id_clean = tenant_id.lower().strip()

        # 1. Bypass para Superadmins de LLYC
        if email_clean.endswith("@llyc.global") or email_clean.endswith("@llyc.ai"):
            return True

        if not self.db:
            # En local con bypass, retornar True para no trabar desarrollo local
            is_production = os.getenv("K_SERVICE") is not None or os.getenv("ENVIRONMENT") == "production"
            bypass_local = os.getenv("BYPASS_AUTH_LOCAL", "false").lower() == "true"
            if not is_production and bypass_local:
                return True
            return False

        session_id = f"{email_clean}_{tenant_id_clean}"

        try:
            doc = self.db.collection(self.collection_sessions).document(session_id).get()
            if not doc.exists:
                return False

            data = doc.to_dict()
            expires_at = data.get("expires_at")
            if expires_at:
                if expires_at.tzinfo is not None:
                    expires_at = expires_at.replace(tzinfo=None)
                if expires_at > datetime.utcnow():
                    return True

            # Si ya expiró, podemos borrarlo proactivamente para mantener limpio
            self.db.collection(self.collection_sessions).document(session_id).delete()
            return False
        except Exception as e:
            logger.error(f"Error validando estado de 2FA para {email_clean}: {e}")
            return False

otp_service = OTPService()
