"""
tools/cm360.py - Herramientas Campaign Manager 360 para el tool executor
Proyecto: llyc-ai-first-core
DEC_142: agente CM360 read-only (DEC_022); adapter de escritura vive
fuera de este modulo, en scripts/_common/ (DEC_069/086/092/100/110/114/115).

Fase 1 - 4 herramientas de lectura, alcance minimo para asociar
creatividades ya aprobadas a placements existentes (piloto IFEMA):
  - list_campaigns
  - list_placements
  - list_creatives
  - list_floodlight_activities

Refactor aplicado sobre el patron ya validado en tools/dv360.py:
  1. Credenciales via Secret Manager (DEC_026)
  2. advertiser_id / profile_id desde config.json del cliente
  3. @with_timeout("cm360") - 45s (DEC_022, response.py)
  4. Contrato ok() / error() en todos los returns (DEC_022)

NOTA DE SEGURIDAD (pendiente de verificar, ver hilo de review):
Los scopes OAuth de dfareporting/dfatrafficking no distinguen lectura de
escritura a nivel de API - el aislamiento de DEC_114 para llyc-agents-sa
debe reforzarse asignando un rol de solo-lectura al Profile/User de CM360
usado por esta SA dentro de la cuenta de IFEMA, no solo por scope.
"""

from __future__ import annotations
import json
import logging
from typing import Any

from google.oauth2 import service_account
import googleapiclient.discovery as discovery
from googleapiclient.errors import HttpError

from tools.response import ok, error, with_timeout

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/dfareporting",
    "https://www.googleapis.com/auth/dfatrafficking",
]


# --- Autenticacion -----------------------------------------------------------

def _build_service(secrets: dict) -> Any:
    """
    Construye el cliente de Campaign Manager 360 API v4 desde el JSON de
    Service Account almacenado en Secret Manager (DEC_026).
    secrets["CM360_SERVICE_ACCOUNT_KEY"] -> JSON string de la SA.
    """
    sa_json = secrets.get("CM360_SERVICE_ACCOUNT_KEY")
    if not sa_json:
        raise ValueError("Secret CM360_SERVICE_ACCOUNT_KEY no encontrado")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=SCOPES
    )
    return discovery.build(
        "dfareporting", "v4",
        credentials=creds,
        cache_discovery=False,
    )


def _get_profile_id(config: dict) -> str:
    """
    CM360 requiere profileId (User Profile) en toda llamada, distinto del
    advertiser_id. Campo nuevo de config.json - DEC_142 D.
    """
    profile_id = config.get("platforms", {}).get("cm360", {}).get("profile_id")
    if not profile_id:
        raise ValueError(
            "config.platforms.cm360.profile_id no encontrado - "
            "requerido por la API de Campaign Manager 360, distinto de advertiser_id."
        )
    return profile_id


# --- TOOL 1: list_campaigns ---------------------------------------------------

@with_timeout("cm360")
def list_campaigns(secrets: dict, config: dict, archived: bool = False) -> dict:
    """
    Lista las campanas del advertiser en CM360.
    advertiser_id inyectado desde config["platforms"]["cm360"]["advertiser_id"].
    """
    advertiser_id = config.get("platforms", {}).get("cm360", {}).get("advertiser_id")
    if not advertiser_id:
        return error("cm360", "CONFIG_ERROR", "config.platforms.cm360.advertiser_id no encontrado")
    profile_id = _get_profile_id(config)
    try:
        svc = _build_service(secrets)
        results, page_token = [], None
        while True:
            resp = (
                svc.campaigns()
                .list(
                    profileId=profile_id,
                    advertiserIds=[advertiser_id],
                    archived=archived,
                    pageToken=page_token,
                )
                .execute()
            )
            results.extend(resp.get("campaigns", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        campaigns = [
            {
                "campaign_id": c.get("id"),
                "name": c.get("name"),
                "advertiser_id": c.get("advertiserId"),
                "archived": c.get("archived"),
                "start_date": c.get("startDate"),
                "end_date": c.get("endDate"),
            }
            for c in results
        ]
        log.info(
            "cm360.list_campaigns ok advertiser=%s total=%d",
            advertiser_id, len(campaigns),
        )
        return ok("cm360", {"campaigns": campaigns, "total": len(campaigns)})

    except HttpError as e:
        log.error("cm360.list_campaigns HttpError status=%s", e.resp.status)
        return error("cm360", "HTTP_ERROR", f"CM360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("cm360.list_campaigns error: %s", e)
        return error("cm360", "UNEXPECTED_ERROR", str(e))


# --- TOOL 2: list_placements ---------------------------------------------------

@with_timeout("cm360")
def list_placements(secrets: dict, config: dict, campaign_id: str = "") -> dict:
    """
    Lista placements del advertiser, filtrados por campana si se especifica.
    Es la entidad sobre la que Fase 1 asocia creatividades.
    """
    advertiser_id = config.get("platforms", {}).get("cm360", {}).get("advertiser_id")
    if not advertiser_id:
        return error("cm360", "CONFIG_ERROR", "config.platforms.cm360.advertiser_id no encontrado")
    profile_id = _get_profile_id(config)
    try:
        svc = _build_service(secrets)
        results, page_token = [], None
        while True:
            kwargs = {
                "profileId": profile_id,
                "advertiserIds": [advertiser_id],
                "pageToken": page_token,
            }
            if campaign_id:
                kwargs["campaignIds"] = [campaign_id]
            resp = svc.placements().list(**kwargs).execute()
            results.extend(resp.get("placements", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        placements = [
            {
                "placement_id": p.get("id"),
                "name": p.get("name"),
                "campaign_id": p.get("campaignId"),
                "site_id": p.get("siteId"),
                "status": p.get("status"),
                "compatibility": p.get("compatibility"),
                "size": p.get("size", {}),
            }
            for p in results
        ]
        log.info(
            "cm360.list_placements ok advertiser=%s campaign=%s total=%d",
            advertiser_id, campaign_id or "all", len(placements),
        )
        return ok("cm360", {"placements": placements, "total": len(placements)})

    except HttpError as e:
        log.error("cm360.list_placements HttpError status=%s", e.resp.status)
        return error("cm360", "HTTP_ERROR", f"CM360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("cm360.list_placements error: %s", e)
        return error("cm360", "UNEXPECTED_ERROR", str(e))


# --- TOOL 3: list_creatives ---------------------------------------------------

@with_timeout("cm360")
def list_creatives(secrets: dict, config: dict, campaign_id: str = "") -> dict:
    """
    Lista creatividades del advertiser (ya aprobadas), filtradas por campana
    si se especifica. Fuente de las creatividades a asociar en Fase 1.
    """
    advertiser_id = config.get("platforms", {}).get("cm360", {}).get("advertiser_id")
    if not advertiser_id:
        return error("cm360", "CONFIG_ERROR", "config.platforms.cm360.advertiser_id no encontrado")
    profile_id = _get_profile_id(config)
    try:
        svc = _build_service(secrets)
        results, page_token = [], None
        while True:
            kwargs = {
                "profileId": profile_id,
                "advertiserId": advertiser_id,
                "pageToken": page_token,
            }
            if campaign_id:
                kwargs["campaignId"] = campaign_id
            resp = svc.creatives().list(**kwargs).execute()
            results.extend(resp.get("creatives", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        creatives = [
            {
                "creative_id": c.get("id"),
                "name": c.get("name"),
                "type": c.get("type"),
                "active": c.get("active"),
                "size": c.get("size", {}),
            }
            for c in results
        ]
        log.info(
            "cm360.list_creatives ok advertiser=%s campaign=%s total=%d",
            advertiser_id, campaign_id or "all", len(creatives),
        )
        return ok("cm360", {"creatives": creatives, "total": len(creatives)})

    except HttpError as e:
        log.error("cm360.list_creatives HttpError status=%s", e.resp.status)
        return error("cm360", "HTTP_ERROR", f"CM360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("cm360.list_creatives error: %s", e)
        return error("cm360", "UNEXPECTED_ERROR", str(e))


# --- TOOL 4: list_floodlight_activities ---------------------------------------

@with_timeout("cm360")
def list_floodlight_activities(secrets: dict, config: dict) -> dict:
    """
    Lista Floodlight Activities ya configuradas para el advertiser.
    Contexto para no contradecir configuracion existente al asociar
    creatividades (verificacion en vivo, DEC_142 - sin BigQuery).
    """
    advertiser_id = config.get("platforms", {}).get("cm360", {}).get("advertiser_id")
    if not advertiser_id:
        return error("cm360", "CONFIG_ERROR", "config.platforms.cm360.advertiser_id no encontrado")
    profile_id = _get_profile_id(config)
    try:
        svc = _build_service(secrets)
        results, page_token = [], None
        while True:
            resp = (
                svc.floodlightActivities()
                .list(
                    profileId=profile_id,
                    advertiserId=advertiser_id,
                    pageToken=page_token,
                )
                .execute()
            )
            results.extend(resp.get("floodlightActivities", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        activities = [
            {
                "activity_id": a.get("id"),
                "name": a.get("name"),
                "floodlight_activity_group_id": a.get("floodlightActivityGroupId"),
                "counting_method": a.get("countingMethod"),
            }
            for a in results
        ]
        log.info(
            "cm360.list_floodlight_activities ok advertiser=%s total=%d",
            advertiser_id, len(activities),
        )
        return ok("cm360", {"activities": activities, "total": len(activities)})

    except HttpError as e:

        log.error("cm360.list_floodlight_activities HttpError status=%s", e.resp.status)
        return error("cm360", "HTTP_ERROR", f"CM360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("cm360.list_floodlight_activities error: %s", e)
        return error("cm360", "UNEXPECTED_ERROR", str(e))
