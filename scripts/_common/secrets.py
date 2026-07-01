"""
scripts/_common/secrets.py
Lectura genérica de GCP Secret Manager.

Compartido por todos los adapters de plataforma (DV360, Meta, ...).
No contiene lógica de plataforma — solo el contrato de lectura de secrets.

Regla DEC_067: .strip() defensivo obligatorio en toda lectura de secret.
Regla DEC_026: valores reales solo en Secret Manager, nunca en repo ni Drive.
"""
from __future__ import annotations

from google.cloud import secretmanager

CORE_PROJECT = "llyc-ai-first-core"


def read_secret(secret_name: str, project_id: str = CORE_PROJECT) -> str:
    """
    Lee la versión latest de un secret desde GCP Secret Manager.

    Args:
        secret_name: nombre del secret en MAYUSCULAS_SNAKE_CASE (DEC_033).
        project_id: proyecto GCP donde vive el secret.
                    Por defecto llyc-ai-first-core (secrets compartidos).
                    Pasar el proyecto cliente para secrets por cliente.

    Returns:
        Valor del secret como string, con .strip() aplicado (DEC_067).

    Raises:
        google.api_core.exceptions.NotFound: si el secret no existe.
        google.api_core.exceptions.PermissionDenied: si la SA no tiene acceso.
    """
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8").strip()  # DEC_067
