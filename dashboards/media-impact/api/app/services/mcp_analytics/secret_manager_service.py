# backend/app/services/mcp_analytics/secret_manager_service.py

import os
import logging
from typing import Optional
from google.cloud import secretmanager
from app.core.config import settings

logger = logging.getLogger(__name__)

class SecretManagerService:
    """
    Servicio empresarial para la gestión segura de llaves y credenciales de inquilinos
    utilizando GCP Secret Manager como almacén criptográfico.
    """
    
    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID") or settings.GCP_PROJECT_ID
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                self._client = secretmanager.SecretManagerServiceClient()
                logger.info("GCP Secret Manager Service Client inicializado correctamente.")
            except Exception as e:
                logger.warning(f"No se pudo inicializar GCP Secret Manager Service Client (posible entorno local): {e}")
        return self._client

    def save_tenant_secret(self, tenant_id: str, secret_type: str, secret_value: str) -> bool:
        """
        Crea o actualiza un secreto encriptado para un tenant específico en GCP Secret Manager.
        """
        if not self.client:
            logger.error("Secret Manager Client no está disponible. No se puede guardar el secreto.")
            return False
            
        try:
            secret_id = f"llyc-mcp-{tenant_id}-{secret_type}".lower().strip()
            parent = f"projects/{self.project_id}"
            secret_path = f"{parent}/secrets/{secret_id}"
            
            # Verificar si el secreto ya existe
            try:
                self.client.get_secret(request={"name": secret_path})
                logger.info(f"El secreto {secret_id} ya existe. Procediendo a crear nueva versión.")
            except Exception:
                # Si lanza excepción, asumimos que no existe y lo creamos de raíz
                logger.info(f"Creando nuevo secreto de marca: {secret_id}...")
                self.client.create_secret(
                    request={
                        "parent": parent,
                        "secret_id": secret_id,
                        "secret": {
                            "replication": {
                                "automatic": {}
                            }
                        }
                    }
                )
            
            # Añadir la nueva versión con la clave
            payload = secret_value.encode("utf-8")
            self.client.add_secret_version(
                request={
                    "parent": secret_path,
                    "payload": {
                        "data": payload
                    }
                }
            )
            logger.info(f"✅ Secreto {secret_id} guardado con éxito en Secret Manager.")
            return True
            
        except Exception as e:
            logger.error(f"Error al guardar secreto en Secret Manager: {e}")
            return False

    def get_tenant_secret(self, tenant_id: str, secret_type: str) -> Optional[str]:
        """
        Recupera la versión más reciente de un secreto encriptado de un tenant desde GCP Secret Manager.
        """
        if not self.client:
            logger.warning("Secret Manager Client no está disponible. No se puede recuperar el secreto.")
            return None
            
        try:
            secret_id = f"llyc-mcp-{tenant_id}-{secret_type}".lower().strip()
            # Accedemos a la versión más reciente ('latest')
            name = f"projects/{self.project_id}/secrets/{secret_id}/versions/latest"
            
            response = self.client.access_secret_version(request={"name": name})
            secret_value = response.payload.data.decode("UTF-8")
            return secret_value
            
        except Exception as e:
            logger.debug(f"No se pudo recuperar el secreto {secret_id} desde Secret Manager: {e}")
            return None

    def delete_tenant_secret(self, tenant_id: str, secret_type: str) -> bool:
        """
        Elimina completamente un secreto y todas sus versiones de GCP Secret Manager.
        """
        if not self.client:
            logger.warning("Secret Manager Client no está disponible. No se puede eliminar el secreto.")
            return False
            
        try:
            secret_id = f"llyc-mcp-{tenant_id}-{secret_type}".lower().strip()
            secret_path = f"projects/{self.project_id}/secrets/{secret_id}"
            
            self.client.delete_secret(request={"name": secret_path})
            logger.info(f"✅ Secreto {secret_id} eliminado con éxito de Secret Manager.")
            return True
            
        except Exception as e:
            logger.error(f"Error al eliminar el secreto {secret_id} de Secret Manager: {e}")
            return False
