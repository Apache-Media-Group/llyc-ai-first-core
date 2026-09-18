"""
scripts/_common/secrets.py
Lectura generica de secrets desde GCP Secret Manager (DEC_143).

Plumbing puro, sin logica de negocio de ninguna plataforma.
"""

from __future__ import annotations

from google.cloud import secretmanager


def read_secret(project_id: str, secret_name: str) -> str:
    """
    Lee la version "latest" de un secret de GCP Secret Manager.

    Args:
        project_id: proyecto GCP donde vive el secret.
        secret_name: nombre del secret (sin project/version).

    Returns:
        El valor del secret como string.

    SEGURIDAD: el valor devuelto es sensible. El llamador nunca debe
    loguearlo, imprimirlo, ni incluirlo en payloads de auditoria (ver
    scripts/_common/audit.py: log_action audita "args"/"result", nunca
    credenciales).
    """
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")
