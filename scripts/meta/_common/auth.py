"""
scripts/meta/_common/auth.py
Autenticacion Meta Marketing API para scripts de escritura.

Lee META_ACCESS_TOKEN desde Secret Manager del proyecto cliente (DEC_026).
SA de escritura: llyc-ops-writer-sa (DEC_086).
NUNCA usar llyc-agents-sa desde scripts de escritura.

Uso:
    from scripts.meta._common.auth import build_meta_client, get_ad_account_id
    api = build_meta_client(client_id="vidal-vidal")
    ad_account_id = get_ad_account_id(client_id="vidal-vidal")
"""
from __future__ import annotations

import json
import pathlib

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount

from scripts._common.secrets import read_secret


def _get_client_project(client_id: str) -> str:
    """
    Resuelve el proyecto GCP del cliente desde config.json.
    El secret META_ACCESS_TOKEN vive en el proyecto cliente (DEC_058).
    """
    repo_root = pathlib.Path(__file__).parents[3]
    config_path = repo_root / "clients" / client_id / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(
        )
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    project_id = config.get("gcp", {}).get("project_id")
    if not project_id:
        raise ValueError(
            f"Completar clients/{client_id}/config.json gcp.project_id — "
            f"sin este campo no se puede resolver el proyecto GCP del secret Meta."
        )
    return project_id


def get_ad_account_id(client_id: str) -> str:
    """
    Lee el ad_account_id del config del cliente.
    Formato esperado en config.json: platforms.meta.ad_account_id (sin prefijo act_).
    Devuelve el ID con prefijo act_ requerido por la API.
    """
    repo_root = pathlib.Path(__file__).parents[3]
    config_path = repo_root / "clients" / client_id / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(
        )
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    meta = config.get("platforms", {}).get("meta", {})
    ad_account_id = meta.get("ad_account_id")
    if not ad_account_id or ad_account_id == "PENDIENTE":
        raise ValueError(
            "Completar clients/{client_id}/config.json platforms.meta.ad_account_id."
        )

    # Normalizar: la API requiere prefijo act_
    if not str(ad_account_id).startswith("act_"):
        ad_account_id = f"act_{ad_account_id}"

    return str(ad_account_id)


def build_meta_client(client_id: str) -> AdAccount:
    """
    Inicializa la Meta Marketing API para el path de escritura (ops) y devuelve
    el AdAccount del cliente.
    Lee el secreto write-scoped meta-access-token-ops desde Secret Manager del
    proyecto cliente, accesible únicamente por llyc-ops-writer-sa (DEC_114).
    Esta función NUNCA debe invocarse desde el runtime de agentes
    (llyc-agents-sa) ni desde el dispatcher del loop tool_use (DEC_115).
    Args:
        client_id: ID del cliente (ej. vidal-vidal).
    Returns:
        AdAccount inicializado y listo para operar.
    Raises:
        FileNotFoundError: si config.json del cliente no existe.
        ValueError: si ad_account_id no esta configurado.
        google.api_core.exceptions.NotFound: si el secret no existe en SM.
    """
    project_id = _get_client_project(client_id)
    access_token = read_secret("meta-access-token-ops", project_id=project_id)

    FacebookAdsApi.init(access_token=access_token)

    ad_account_id = get_ad_account_id(client_id)
    return AdAccount(ad_account_id)
