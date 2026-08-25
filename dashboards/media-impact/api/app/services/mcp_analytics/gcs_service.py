# backend/app/services/mcp_analytics/gcs_service.py

import os
import logging
from typing import Optional
from google.cloud import storage
from app.core.config import settings

logger = logging.getLogger(__name__)

class GCSService:
    """
    Servicio empresarial para gestionar la subida y almacenamiento de recursos públicos
    (como logotipos SVGs/PNGs corporativos de clientes) en Google Cloud Storage (GCS).
    """
    
    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID") or settings.GCP_PROJECT_ID
        # Bucket público configurable por entorno, por defecto 'llyc-mcp-public-assets'
        self.bucket_name = os.getenv("GCP_PUBLIC_BUCKET", "llyc-mcp-public-assets")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                self._client = storage.Client(project=self.project_id)
                logger.info(f"GCP Storage Client inicializado correctamente para el proyecto: {self.project_id}")
            except Exception as e:
                logger.warning(f"No se pudo inicializar GCP Storage Client (posible entorno local): {e}")
        return self._client

    def upload_logo(self, tenant_id: str, file_content: bytes, content_type: str = "image/svg+xml") -> Optional[str]:
        """
        Sube un archivo de logotipo (SVG o PNG) a GCS y devuelve su URL CDN pública.
        """
        if not self.client:
            logger.error("GCS Client no está disponible. No se puede subir el archivo.")
            return None
            
        try:
            bucket = self.client.bucket(self.bucket_name)
            
            # El nombre de archivo se normaliza según el tenant y tipo (ej: logos/test.svg)
            ext = "png" if "png" in content_type else "svg"
            blob_name = f"logos/{tenant_id}.{ext}".lower().strip()
            blob = bucket.blob(blob_name)
            
            # Subir contenido con el content_type correcto
            blob.upload_from_string(file_content, content_type=content_type)
            
            # Hacer público el archivo para que se pueda visualizar en la interfaz web (<img> tag)
            try:
                blob.make_public()
            except Exception as e:
                logger.warning(f"No se pudo hacer público el logo (posible Uniform Bucket-Level Access): {e}")
                
            # Generar URL pública CDN estándar de Google Cloud Storage
            public_url = f"https://storage.googleapis.com/{self.bucket_name}/{blob_name}"
            logger.info(f"✅ Logotipo de tenant '{tenant_id}' subido con éxito a GCS: {public_url}")
            return public_url
            
        except Exception as e:
            logger.error(f"Error al subir logotipo de tenant '{tenant_id}' a GCS: {e}")
            return None
