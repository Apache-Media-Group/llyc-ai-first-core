"""
scripts/dv360/_common/auth.py
Lectura de credenciales para scripts de escritura DV360.

SA dedicada: llyc-ops-writer-sa (DEC_084).
NUNCA usar llyc-agents-sa desde scripts de escritura.

Uso:
    from scripts.dv360._common.auth import build_writer_service
    svc = build_writer_service(client_id="vidal-vidal")
"""

from __future__ import annotations
import json
import os

from google.cloud import secretmanager
from google.oauth2 import service_account
import googleapiclient.discovery as discovery

WRITER_SA = "llyc-ops-writer-sa"
CORE_PROJECT = "llyc-ai-first-core"
SECRET_NAME = "DV360_WRITER_SERVICE_ACCOUNT_KEY"

SCOPES = [
    "https://www.googleapis.com/auth/display-video",
    "https://www.googleapis.com/auth/display-video-mediaplanning",
]


def _read_secret(project_id: str, secret_name: str) -> str:
    """Lee un secret de GCP Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def build_writer_service(client_id: str | None = None) -> Any:
    """
    Construye el cliente DV360 API v4 con la SA de escritura (DEC_084).

    Lee DV360_WRITER_SERVICE_ACCOUNT_KEY desde Secret Manager de llyc-ai-first-core.
    Esta SA tiene permisos write sobre DV360 — nunca se monta en el runtime del agente.

    Args:
        client_id: ID del cliente (para trazabilidad en logs). No cambia las credenciales.
    """
    sa_json = _read_secret(CORE_PROJECT, SECRET_NAME)

    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=SCOPES
    )

    svc = discovery.build(
        "displayvideo", "v4",
        credentials=creds,
        cache_discovery=False,
    )
    return svc


def get_advertiser_id(client_id: str) -> str:
    """
    Lee el advertiser_id del config del cliente.
    Busca clients/{client_id}/config.json relativo al repo raiz.
    """
    import pathlib
    repo_root = pathlib.Path(__file__).parents[3]
    config_path = repo_root / "clients" / client_id / "config.json"

    if not config_path.exists():
        raise FileNotFoundError(f"Config no encontrado para cliente '{client_id}': {config_path}")

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    dv360 = config.get("platforms", {}).get("dv360", {})
    advertiser_id = dv360.get("advertiser_id")

    if not advertiser_id or advertiser_id == "PENDIENTE":
        raise ValueError(
            f"advertiser_id de DV360 no configurado para cliente '{client_id}'. "
            "Completar clients/{client_id}/config.json platforms.dv360.advertiser_id."
        )

    return advertiser_id
