"""
tools/dv360.py — Herramientas DV360 para el tool executor
Proyecto: llyc-ai-first-core
Decisión 064: DV360 integrado como el resto de plataformas vía Tool Use.
Fase 2 del plan de rescate (META_arquitectura-github §10.2).

POC Sprint 1 — 3 herramientas prioritarias:
  - get_campaign_metrics   (stub hasta resolver fuente de métricas con Jesús)
  - list_campaigns
  - list_insertion_orders

Refactor aplicado sobre dv360_client.py (Apache-Media-Group/dv360-mcp-server):
  1. Credenciales vía Secret Manager (DEC_026)
  2. advertiser_id / partner_id desde config.json del cliente
  3. @with_timeout("dv360") — 45s (DEC_022, response.py)
  4. Contrato ok() / error() en todos los returns (DEC_022)
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
    "https://www.googleapis.com/auth/display-video",
    "https://www.googleapis.com/auth/display-video-mediaplanning",
]


# ── Autenticación ─────────────────────────────────────────────────────────────

def _build_service(secrets: dict) -> Any:
    """
    Construye el cliente de DV360 API v4 desde el JSON de Service Account
    almacenado en Secret Manager (DEC_026).
    secrets["DV360_SERVICE_ACCOUNT_KEY"] → JSON string de la SA.
    """
    sa_json = secrets.get("DV360_SERVICE_ACCOUNT_KEY")
    if not sa_json:
        raise ValueError("Secret DV360_SERVICE_ACCOUNT_KEY no encontrado")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=SCOPES
    )
    return discovery.build(
        "displayvideo", "v4",
        credentials=creds,
        cache_discovery=False,
    )


# ── TOOL 1: list_campaigns ────────────────────────────────────────────────────

@with_timeout("dv360")
def list_campaigns(secrets: dict, config: dict, filter_str: str = "") -> dict:
    """
    Lista todas las campañas del advertiser.
    advertiser_id inyectado desde config["platforms"]["dv360"]["advertiser_id"].
    """
    advertiser_id = config["platforms"]["dv360"]["advertiser_id"]
    try:
        svc = _build_service(secrets)
        results, page_token = [], None
        while True:
            resp = (
                svc.advertisers()
                .campaigns()
                .list(
                    advertiserId=advertiser_id,
                    filter=filter_str or None,
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
                "campaign_id": c.get("campaignId"),
                "name": c.get("displayName"),
                "status": c.get("entityStatus"),
                "goal_type": c.get("campaignGoal", {}).get("campaignGoalType"),
                "budgets": c.get("campaignBudgets", []),
            }
            for c in results
        ]
        log.info(
            "dv360.list_campaigns ok advertiser=%s total=%d",
            advertiser_id, len(campaigns),
        )
        return ok("dv360", {"campaigns": campaigns, "total": len(campaigns)})

    except HttpError as e:
        log.error("dv360.list_campaigns HttpError status=%s", e.resp.status)
        return error("dv360", "HTTP_ERROR", f"DV360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("dv360.list_campaigns error: %s", e)
        return error("dv360", "UNEXPECTED_ERROR", str(e))


# ── TOOL 2: list_insertion_orders ─────────────────────────────────────────────

@with_timeout("dv360")
def list_insertion_orders(
    secrets: dict, config: dict, campaign_id: str = ""
) -> dict:
    """
    Lista Insertion Orders del advertiser, filtrados por campaña si se especifica.
    """
    advertiser_id = config["platforms"]["dv360"]["advertiser_id"]
    try:
        svc = _build_service(secrets)
        results, page_token = [], None
        f = f"campaignId={campaign_id}" if campaign_id else None
        while True:
            resp = (
                svc.advertisers()
                .insertionOrders()
                .list(
                    advertiserId=advertiser_id,
                    filter=f,
                    pageToken=page_token,
                )
                .execute()
            )
            results.extend(resp.get("insertionOrders", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        insertion_orders = [
            {
                "insertion_order_id": io.get("insertionOrderId"),
                "campaign_id": io.get("campaignId"),
                "name": io.get("displayName"),
                "status": io.get("entityStatus"),
                "pacing": io.get("pacing", {}),
                "budget_segments": io.get("budget", {}).get("budgetSegments", []),
            }
            for io in results
        ]
        log.info(
            "dv360.list_insertion_orders ok advertiser=%s campaign=%s total=%d",
            advertiser_id, campaign_id or "all", len(insertion_orders),
        )
        return ok("dv360", {
            "insertion_orders": insertion_orders,
            "total": len(insertion_orders),
        })

    except HttpError as e:
        log.error("dv360.list_insertion_orders HttpError status=%s", e.resp.status)
        return error("dv360", "HTTP_ERROR", f"DV360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("dv360.list_insertion_orders error: %s", e)
        return error("dv360", "UNEXPECTED_ERROR", str(e))


# -- TOOL 3 (reimplementacion): get_campaign_metrics con Query API -------------
# Sustituye el stub anterior. Fuente: DV360 Query API asincrona (DEC_068).
# Flujo: queries.create() -> queries.run() -> poll queries.get() -> download CSV -> parse.
# Timeout interno: 60s. Si polling no resuelve -> error degradado (DEC_022).

import csv
import io
import time
import urllib.request


@with_timeout("dv360")
def get_campaign_metrics(
    secrets: dict, config: dict, campaign_id: str,
    date_range: str = "LAST_7_DAYS"
) -> dict:
    """
    Devuelve metricas de rendimiento de la campana via DV360 Query API asincrona.
    date_range: LAST_7_DAYS | LAST_30_DAYS | LAST_90_DAYS | CURRENT_MONTH | PREVIOUS_MONTH
    Timeout interno de polling: 60s. Si no resuelve devuelve error degradado.
    Ver DEC_068 - Query API como fuente unica de metricas DV360.
    """
    advertiser_id = config["platforms"]["dv360"]["advertiser_id"]
    POLL_INTERVAL = 5
    POLL_TIMEOUT = 60

    try:
        svc = _build_service(secrets)

        query_body = {
            "metadata": {
                "title": f"llyc_agent_campaign_{campaign_id}",
                "dataRange": {"range": date_range},
                "format": "CSV",
            },
            "params": {
                "type": "TYPE_GENERAL",
                "groupBys": ["FILTER_DATE", "FILTER_ADVERTISER_CAMPAIGN"],
                "filters": [
                    {"type": "FILTER_ADVERTISER", "value": advertiser_id},
                    {"type": "FILTER_ADVERTISER_CAMPAIGN", "value": campaign_id},
                ],
                "metrics": [
                    "METRIC_IMPRESSIONS",
                    "METRIC_CLICKS",
                    "METRIC_CTR",
                    "METRIC_REVENUE_ADVERTISER",
                    "METRIC_MEDIA_COST_ADVERTISER",
                    "METRIC_TOTAL_CONVERSIONS",
                    "METRIC_LAST_CLICKS_COUNT",
                ],
            },
            "schedule": {"frequency": "ONE_TIME"},
        }
        query = svc.queries().create(body=query_body).execute()
        query_id = query["queryId"]
        log.info("dv360.get_campaign_metrics query_created query_id=%s", query_id)

        svc.queries().run(queryId=query_id, body={}).execute()

        elapsed = 0
        report_url = None
        while elapsed < POLL_TIMEOUT:
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            q = svc.queries().get(queryId=query_id).execute()
            running = q.get("metadata", {}).get("running")
            gcs_path = q.get("metadata", {}).get("googleCloudStoragePath")
            if not running and gcs_path:
                report_url = gcs_path
                break
            log.info("dv360.get_campaign_metrics polling elapsed=%ds", elapsed)

        if not report_url:
            return error(
                "dv360", "TIMEOUT",
                f"Report no listo en {POLL_TIMEOUT}s (query_id={query_id}). "
                "El agente opera sin metricas DV360 en esta ejecucion."
            )

        with urllib.request.urlopen(report_url) as resp:
            raw = resp.read().decode("utf-8")

        reader = csv.DictReader(io.StringIO(raw))
        rows = list(reader)

        total_impressions = sum(int(r.get("Impressions", 0) or 0) for r in rows)
        total_clicks = sum(int(r.get("Clicks", 0) or 0) for r in rows)
        total_spend = sum(float(r.get("Revenue (Adv Currency)", 0) or 0) for r in rows)
        total_conversions = sum(float(r.get("Total Conversions", 0) or 0) for r in rows)
        ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0.0
        cpa = (total_spend / total_conversions) if total_conversions > 0 else None

        log.info(
            "dv360.get_campaign_metrics ok query_id=%s rows=%d impressions=%d spend=%.2f",
            query_id, len(rows), total_impressions, total_spend,
        )
        return ok("dv360", {
            "campaign_id": campaign_id,
            "date_range": date_range,
            "query_id": query_id,
            "metrics": {
                "impressions": total_impressions,
                "clicks": total_clicks,
                "ctr_pct": round(ctr, 2),
                "spend_advertiser_currency": round(total_spend, 2),
                "total_conversions": round(total_conversions, 2),
                "cpa": round(cpa, 2) if cpa is not None else None,
            },
            "daily_breakdown": rows,
        })

    except HttpError as e:
        log.error("dv360.get_campaign_metrics HttpError status=%s", e.resp.status)
        return error("dv360", "HTTP_ERROR", f"DV360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("dv360.get_campaign_metrics error: %s", e)
        return error("dv360", "UNEXPECTED_ERROR", str(e))


# -- TOOL 4: get_campaign -----------------------------------------------------

@with_timeout("dv360")
def get_campaign(secrets: dict, config: dict, campaign_id: str) -> dict:
    """Devuelve los datos de una campana por ID."""
    advertiser_id = config["platforms"]["dv360"]["advertiser_id"]
    try:
        svc = _build_service(secrets)
        c = (
            svc.advertisers()
            .campaigns()
            .get(advertiserId=advertiser_id, campaignId=campaign_id)
            .execute()
        )
        log.info("dv360.get_campaign ok advertiser=%s campaign=%s", advertiser_id, campaign_id)
        return ok("dv360", {
            "campaign_id": c.get("campaignId"),
            "name": c.get("displayName"),
            "status": c.get("entityStatus"),
            "goal_type": c.get("campaignGoal", {}).get("campaignGoalType"),
            "budgets": c.get("campaignBudgets", []),
        })
    except HttpError as e:
        return error("dv360", "HTTP_ERROR", f"DV360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("dv360.get_campaign error: %s", e)
        return error("dv360", "UNEXPECTED_ERROR", str(e))


# -- TOOL 5: list_line_items --------------------------------------------------

@with_timeout("dv360")
def list_line_items(
    secrets: dict, config: dict, campaign_id: str = "", filter_str: str = ""
) -> dict:
    """Lista Line Items del advertiser, filtrados por campana si se especifica."""
    advertiser_id = config["platforms"]["dv360"]["advertiser_id"]
    try:
        svc = _build_service(secrets)
        results, page_token = [], None
        f = f"campaignId={campaign_id}" if campaign_id else filter_str or None
        while True:
            resp = (
                svc.advertisers()
                .lineItems()
                .list(
                    advertiserId=advertiser_id,
                    filter=f,
                    pageToken=page_token,
                )
                .execute()
            )
            results.extend(resp.get("lineItems", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        line_items = [
            {
                "line_item_id": li.get("lineItemId"),
                "campaign_id": li.get("campaignId"),
                "insertion_order_id": li.get("insertionOrderId"),
                "name": li.get("displayName"),
                "status": li.get("entityStatus"),
                "line_item_type": li.get("lineItemType"),
                "pacing": li.get("pacing", {}),
                "budget": li.get("budget", {}),
                "bid_strategy": li.get("bidStrategy", {}),
            }
            for li in results
        ]
        log.info(
            "dv360.list_line_items ok advertiser=%s campaign=%s total=%d",
            advertiser_id, campaign_id or "all", len(line_items),
        )
        return ok("dv360", {"line_items": line_items, "total": len(line_items)})
    except HttpError as e:
        return error("dv360", "HTTP_ERROR", f"DV360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("dv360.list_line_items error: %s", e)
        return error("dv360", "UNEXPECTED_ERROR", str(e))


# -- TOOL 6: get_line_item ----------------------------------------------------

@with_timeout("dv360")
def get_line_item(secrets: dict, config: dict, line_item_id: str) -> dict:
    """Devuelve los datos de un Line Item por ID."""
    advertiser_id = config["platforms"]["dv360"]["advertiser_id"]
    try:
        svc = _build_service(secrets)
        li = (
            svc.advertisers()
            .lineItems()
            .get(advertiserId=advertiser_id, lineItemId=line_item_id)
            .execute()
        )
        log.info("dv360.get_line_item ok advertiser=%s li=%s", advertiser_id, line_item_id)
        return ok("dv360", {
            "line_item_id": li.get("lineItemId"),
            "campaign_id": li.get("campaignId"),
            "insertion_order_id": li.get("insertionOrderId"),
            "name": li.get("displayName"),
            "status": li.get("entityStatus"),
            "line_item_type": li.get("lineItemType"),
            "pacing": li.get("pacing", {}),
            "budget": li.get("budget", {}),
            "bid_strategy": li.get("bidStrategy", {}),
            "targeting_expansion": li.get("targetingExpansion", {}),
        })
    except HttpError as e:
        return error("dv360", "HTTP_ERROR", f"DV360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("dv360.get_line_item error: %s", e)
        return error("dv360", "UNEXPECTED_ERROR", str(e))


# -- HELPER: _get_targeting_by_type -------------------------------------------

def _get_targeting_by_type(
    svc: Any, advertiser_id: str, line_item_id: str, targeting_type: str
) -> list:
    """Helper privado: lectura de targeting de un LI por tipo."""
    results, page_token = [], None
    while True:
        resp = (
            svc.advertisers()
            .lineItems()
            .targetingOptions()
            .list(
                advertiserId=advertiser_id,
                lineItemId=line_item_id,
                targetingType=targeting_type,
                pageToken=page_token,
            )
            .execute()
        )
        results.extend(resp.get("assignedTargetingOptions", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


# -- TOOL 7: get_targeting ----------------------------------------------------

@with_timeout("dv360")
def get_targeting(
    secrets: dict, config: dict, line_item_id: str, targeting_types: list = None
) -> dict:
    """Devuelve el targeting asignado a un Line Item."""
    advertiser_id = config["platforms"]["dv360"]["advertiser_id"]
    DEFAULT_TYPES = [
        "TARGETING_TYPE_GEO_REGION",
        "TARGETING_TYPE_DEVICE_TYPE",
        "TARGETING_TYPE_AUDIENCE_GROUP",
        "TARGETING_TYPE_AGE_RANGE",
        "TARGETING_TYPE_GENDER",
    ]
    types_to_fetch = targeting_types or DEFAULT_TYPES
    try:
        svc = _build_service(secrets)
        targeting = {}
        for t_type in types_to_fetch:
            options = _get_targeting_by_type(svc, advertiser_id, line_item_id, t_type)
            if options:
                targeting[t_type] = options
        log.info(
            "dv360.get_targeting ok advertiser=%s li=%s types=%d",
            advertiser_id, line_item_id, len(targeting),
        )
        return ok("dv360", {"line_item_id": line_item_id, "targeting": targeting})
    except HttpError as e:
        return error("dv360", "HTTP_ERROR", f"DV360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("dv360.get_targeting error: %s", e)
        return error("dv360", "UNEXPECTED_ERROR", str(e))


# -- TOOL 8: get_insertion_order ----------------------------------------------

@with_timeout("dv360")
def get_insertion_order(secrets: dict, config: dict, insertion_order_id: str) -> dict:
    """Devuelve los datos de un Insertion Order por ID."""
    advertiser_id = config["platforms"]["dv360"]["advertiser_id"]
    try:
        svc = _build_service(secrets)
        io = (
            svc.advertisers()
            .insertionOrders()
            .get(advertiserId=advertiser_id, insertionOrderId=insertion_order_id)
            .execute()
        )
        log.info(
            "dv360.get_insertion_order ok advertiser=%s io=%s",
            advertiser_id, insertion_order_id,
        )
        return ok("dv360", {
            "insertion_order_id": io.get("insertionOrderId"),
            "campaign_id": io.get("campaignId"),
            "name": io.get("displayName"),
            "status": io.get("entityStatus"),
            "pacing": io.get("pacing", {}),
            "budget_segments": io.get("budget", {}).get("budgetSegments", []),
            "frequency_cap": io.get("frequencyCap", {}),
        })
    except HttpError as e:
        return error("dv360", "HTTP_ERROR", f"DV360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("dv360.get_insertion_order error: %s", e)
        return error("dv360", "UNEXPECTED_ERROR", str(e))


# -- TOOL 9: list_creatives ---------------------------------------------------

@with_timeout("dv360")
def list_creatives(secrets: dict, config: dict, filter_str: str = "") -> dict:
    """Lista creatividades del advertiser. Util para creative-fatigue-detector (Sprint 2)."""
    advertiser_id = config["platforms"]["dv360"]["advertiser_id"]
    try:
        svc = _build_service(secrets)
        results, page_token = [], None
        while True:
            resp = (
                svc.advertisers()
                .creatives()
                .list(
                    advertiserId=advertiser_id,
                    filter=filter_str or None,
                    pageToken=page_token,
                )
                .execute()
            )
            results.extend(resp.get("creatives", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        creatives = [
            {
                "creative_id": c.get("creativeId"),
                "name": c.get("displayName"),
                "status": c.get("entityStatus"),
                "creative_type": c.get("creativeType"),
                "dimensions": c.get("dimensions", {}),
                "review_status": c.get("reviewStatus", {}),
            }
            for c in results
        ]
        log.info("dv360.list_creatives ok advertiser=%s total=%d", advertiser_id, len(creatives))
        return ok("dv360", {"creatives": creatives, "total": len(creatives)})
    except HttpError as e:
        return error("dv360", "HTTP_ERROR", f"DV360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("dv360.list_creatives error: %s", e)
        return error("dv360", "UNEXPECTED_ERROR", str(e))


# -- TOOL 10: list_google_audiences -------------------------------------------

@with_timeout("dv360")
def list_google_audiences(secrets: dict, config: dict, filter_str: str = "") -> dict:
    """Lista audiencias de Google disponibles para targeting."""
    try:
        svc = _build_service(secrets)
        results, page_token = [], None
        while True:
            resp = (
                svc.googleAudiences()
                .list(
                    filter=filter_str or None,
                    pageToken=page_token,
                )
                .execute()
            )
            results.extend(resp.get("googleAudiences", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        audiences = [
            {
                "audience_id": a.get("googleAudienceId"),
                "name": a.get("displayName"),
                "audience_type": a.get("googleAudienceType"),
            }
            for a in results
        ]
        log.info("dv360.list_google_audiences ok total=%d", len(audiences))
        return ok("dv360", {"audiences": audiences, "total": len(audiences)})
    except HttpError as e:
        return error("dv360", "HTTP_ERROR", f"DV360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("dv360.list_google_audiences error: %s", e)
        return error("dv360", "UNEXPECTED_ERROR", str(e))


# -- TOOL 11: search_targeting_options ----------------------------------------

@with_timeout("dv360")
def search_targeting_options(
    secrets: dict, config: dict, targeting_type: str, search_terms: str = ""
) -> dict:
    """Busca opciones de targeting por tipo y termino de busqueda."""
    advertiser_id = config["platforms"]["dv360"]["advertiser_id"]
    try:
        svc = _build_service(secrets)
        body = {"advertiserId": advertiser_id}
        if search_terms:
            body["searchTerms"] = search_terms
        resp = (
            svc.targetingTypes()
            .targetingOptions()
            .search(targetingType=targeting_type, body=body)
            .execute()
        )
        options = resp.get("targetingOptions", [])
        log.info(
            "dv360.search_targeting_options ok type=%s total=%d",
            targeting_type, len(options),
        )
        return ok("dv360", {
            "targeting_type": targeting_type,
            "options": options,
            "total": len(options),
        })
    except HttpError as e:
        return error("dv360", "HTTP_ERROR", f"DV360 API {e.resp.status}: {e.reason}")
    except Exception as e:
        log.exception("dv360.search_targeting_options error: %s", e)
        return error("dv360", "UNEXPECTED_ERROR", str(e))
