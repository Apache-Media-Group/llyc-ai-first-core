"""
Turespaña · Sentiment Intelligence API
Cloud Function HTTP — Python 3.11
Entry point: sentiment_api

Tabla BQ: llyc-prj-turespana-datamart.buffalo_bid_turespana_ods.buffalo_bid_report
Schema confirmado (49 campos):
  - partner_name (STRING), provider (STRING) están en filas 2-3
  - impressions, clicks, impressions_scored son FLOAT64 → se castean a INT64

Endpoints:
  GET ?action=ping       → health check
  GET ?action=me         → email + role del usuario
  GET ?action=filters    → valores disponibles para dropdowns
  GET ?action=data&...   → registros filtrados + benchmarks por plataforma
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Optional

import functions_framework
from flask import Request, jsonify, make_response
import firebase_admin
from firebase_admin import auth as firebase_auth
from google.cloud import bigquery

# ── INIT ──────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not firebase_admin._apps:
    firebase_admin.initialize_app()

bq_client = bigquery.Client()

# ── CONFIG ────────────────────────────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "clients", "turespana", "config.json")
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

BQ_TABLE        = CONFIG["bq_table"]
PARTNER_FILTER  = CONFIG["partner_filter"]
ALLOWED_ORIGINS = CONFIG.get("allowed_origins", ["https://dashboard.llyc.global"])

# Columnas expuestas al frontend
# impressions, clicks, impressions_scored son FLOAT64 en BQ → se castean a INT64
SELECT_COLS = """
    provider,
    market,
    campaign_objective,
    campaign_grouping,
    CAST(ad_id AS STRING)                                              AS ad_id,
    ad_name,
    ad_type,
    ad_audience,
    ad_format,
    ad_version,
    ad_language,
    CAST(ROUND(COALESCE(impressions, 0)) AS INT64)                     AS impressions,
    CAST(ROUND(COALESCE(impressions_scored, 0)) AS INT64)              AS impressions_scored,
    ROUND(COALESCE(emotional_score, 0), 4)                             AS emotional_score,
    ROUND(score_w_ad, 4)                                               AS score_w_ad,
    ROUND(COALESCE(threshold_avg, 0), 4)                               AS threshold_avg,
    ROUND(COALESCE(threshold_excellent, 0), 4)                         AS threshold_excellent,
    ROUND(gap_to_excellent, 4)                                         AS gap_to_excellent,
    COALESCE(benchmark_reliable, FALSE)                                AS benchmark_reliable,
    perf_level_sentiment,
    ROUND(COALESCE(spend, 0), 2)                                       AS spend,
    CAST(ROUND(COALESCE(clicks, 0)) AS INT64)                          AS clicks
"""

# Dimensiones filtrables — provider es el filtro de plataforma (META, TIKTOK...)
FILTER_DIMS = [
    "provider",
    "market",
    "campaign_objective",
    "campaign_grouping",
    "ad_format",
    "ad_type",
    "ad_audience",
    "ad_language",
    "ad_version",
]

FILTER_LABELS = {
    "provider":           "Plataforma",
    "market":             "Mercado",
    "campaign_objective": "Objetivo",
    "campaign_grouping":  "Agrupación",
    "ad_format":          "Formato",
    "ad_type":            "Tipo de Ad",
    "ad_audience":        "Audiencia",
    "ad_language":        "Idioma",
    "ad_version":         "Versión",
}


# ── CORS ──────────────────────────────────────────────────────────────────────
def _cors_headers(request: Request) -> dict:
    origin = request.headers.get("Origin", "")
    allowed = origin if origin in ALLOWED_ORIGINS else ALLOWED_ORIGINS[0]
    return {
        "Access-Control-Allow-Origin":  allowed,
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
        "Access-Control-Max-Age":       "3600",
    }


# ── AUTH ──────────────────────────────────────────────────────────────────────
def _verify_token(request: Request) -> tuple[Optional[dict], Optional[str]]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Authorization header missing or malformed"
    token = auth_header[7:]
    try:
        decoded = firebase_auth.verify_id_token(token)
        return decoded, None
    except firebase_auth.ExpiredIdTokenError:
        return None, "Token expired"
    except firebase_auth.InvalidIdTokenError:
        return None, "Invalid token"
    except Exception as e:
        return None, str(e)


def _get_user_role(email: str) -> Optional[str]:
    """
    Soporta:
      - string "user@llyc.global"            → viewer
      - dict {"email": "...", "role": "..."}  → role definido
      - allowed_domains ["llyc.global"]       → viewer para todo el dominio
    """
    for entry in CONFIG.get("allowed_emails", []):
        if isinstance(entry, str):
            if entry == email:
                return "viewer"
        elif isinstance(entry, dict):
            if entry.get("email") == email:
                return entry.get("role", "viewer")

    domain = email.split("@")[1] if "@" in email else ""
    for allowed_domain in CONFIG.get("allowed_domains", []):
        if allowed_domain == domain:
            return "viewer"

    return None


# ── BIGQUERY ──────────────────────────────────────────────────────────────────
def _build_where(params: dict) -> tuple[str, list]:
    """
    WHERE base:
      - partner_name = 'Turespaña'  (siempre — aísla el cliente)
      - emotional_score > 0          (siempre — excluye ads sin score real)
    Filtros opcionales: cualquier dimensión de FILTER_DIMS.
    Usa parámetros nombrados para evitar SQL injection.
    """
    conditions = [
        "partner_name = @partner_name",
        "emotional_score > 0",
    ]
    bq_params = [
        bigquery.ScalarQueryParameter("partner_name", "STRING", PARTNER_FILTER),
    ]

    for dim in FILTER_DIMS:
        val = params.get(dim)
        if val:
            conditions.append(f"{dim} = @{dim}")
            bq_params.append(bigquery.ScalarQueryParameter(dim, "STRING", val))

    return " AND ".join(conditions), bq_params


def _row_to_dict(row) -> dict:
    return {
        "provider":             row.provider,
        "market":               row.market,
        "campaign_objective":   row.campaign_objective,
        "campaign_grouping":    row.campaign_grouping,
        "ad_id":                row.ad_id,
        "ad_name":              row.ad_name,
        "ad_type":              row.ad_type,
        "ad_audience":          row.ad_audience,
        "ad_format":            row.ad_format,
        "ad_version":           row.ad_version,
        "ad_language":          row.ad_language,
        "impressions":          int(row.impressions or 0),
        "impressions_scored":   int(row.impressions_scored or 0),
        "emotional_score":      float(row.emotional_score or 0),
        "score_w_ad":           float(row.score_w_ad) if row.score_w_ad is not None else None,
        "threshold_avg":        float(row.threshold_avg or 0),
        "threshold_excellent":  float(row.threshold_excellent or 0),
        "gap_to_excellent":     float(row.gap_to_excellent) if row.gap_to_excellent is not None else None,
        "benchmark_reliable":   bool(row.benchmark_reliable),
        "perf_level_sentiment": row.perf_level_sentiment,
        "spend":                float(row.spend or 0),
        "clicks":               int(row.clicks or 0),
    }


# ── HANDLERS ──────────────────────────────────────────────────────────────────
def _handle_ping(headers: dict):
    return make_response(
        jsonify({"ok": True, "ts": datetime.now(timezone.utc).isoformat()}),
        200, headers
    )


def _handle_me(email: str, role: str, headers: dict):
    return make_response(jsonify({"email": email, "role": role}), 200, headers)


def _handle_filters(headers: dict):
    """Valores disponibles para cada dimensión — query ligera sin traer registros."""
    dims_sql = ", ".join(FILTER_DIMS)
    query = f"""
        SELECT DISTINCT {dims_sql}
        FROM `{BQ_TABLE}`
        WHERE partner_name = @partner_name
          AND emotional_score > 0
        ORDER BY provider, market
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("partner_name", "STRING", PARTNER_FILTER)
    ])
    try:
        rows = list(bq_client.query(query, job_config=job_config).result())
    except Exception as e:
        logger.error("BQ filters error: %s", e)
        return make_response(jsonify({"error": f"BigQuery error: {e}"}), 500, headers)

    filters_available = {dim: set() for dim in FILTER_DIMS}
    for row in rows:
        for dim in FILTER_DIMS:
            val = getattr(row, dim, None)
            if val:
                filters_available[dim].add(val)

    return make_response(jsonify({
        "filters_available": {k: sorted(v) for k, v in filters_available.items()},
        "filter_labels":     FILTER_LABELS,
    }), 200, headers)


def _handle_data(request: Request, headers: dict):
    """Registros filtrados + benchmarks por plataforma + valores de filtro disponibles."""
    params = request.args
    where, bq_params = _build_where(params)

    # ── Query principal ────────────────────────────────────────────
    data_query = f"""
        SELECT {SELECT_COLS}
        FROM `{BQ_TABLE}`
        WHERE {where}
        ORDER BY score_w_ad DESC NULLS LAST
        LIMIT 10000
    """
    job_config = bigquery.QueryJobConfig(query_parameters=bq_params)

    try:
        rows = list(bq_client.query(data_query, job_config=job_config).result())
    except Exception as e:
        logger.error("BQ data error: %s", e)
        return make_response(jsonify({"error": f"BigQuery error: {e}"}), 500, headers)

    # ── Benchmarks por plataforma ──────────────────────────────────
    # threshold_avg y threshold_excellent son constantes por partner+provider.
    # Se devuelven agrupados para que el frontend muestre el umbral correcto
    # según la plataforma activa en el filtro.
    benchmarks_by_provider: dict = {}
    for row in rows:
        p = row.provider
        if p and p not in benchmarks_by_provider:
            benchmarks_by_provider[p] = {
                "threshold_avg":       float(row.threshold_avg or 0),
                "threshold_excellent": float(row.threshold_excellent or 0),
            }

    # ── Filtros disponibles (universo completo, sin los filtros activos) ──
    dims_sql = ", ".join(FILTER_DIMS)
    filters_query = f"""
        SELECT DISTINCT {dims_sql}
        FROM `{BQ_TABLE}`
        WHERE partner_name = @partner_name
          AND emotional_score > 0
        ORDER BY provider, market
    """
    filters_job = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("partner_name", "STRING", PARTNER_FILTER)
    ])
    try:
        filter_rows = list(bq_client.query(filters_query, job_config=filters_job).result())
    except Exception as e:
        logger.warning("BQ filters error (non-fatal): %s", e)
        filter_rows = []

    filters_available = {dim: set() for dim in FILTER_DIMS}
    for row in filter_rows:
        for dim in FILTER_DIMS:
            val = getattr(row, dim, None)
            if val:
                filters_available[dim].add(val)

    records = [_row_to_dict(row) for row in rows]

    return make_response(jsonify({
        "records":           records,
        "total":             len(records),
        "benchmarks":        benchmarks_by_provider,
        "filters_available": {k: sorted(v) for k, v in filters_available.items()},
        "filter_labels":     FILTER_LABELS,
        "fetched_at":        datetime.now(timezone.utc).isoformat(),
    }), 200, headers)


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
@functions_framework.http
def sentiment_api(request: Request):
    headers = _cors_headers(request)

    if request.method == "OPTIONS":
        return make_response("", 204, headers)

    if request.method != "GET":
        return make_response(jsonify({"error": "Method not allowed"}), 405, headers)

    decoded_token, token_error = _verify_token(request)
    if token_error:
        logger.warning("Auth error: %s", token_error)
        return make_response(jsonify({"error": f"Unauthorized: {token_error}"}), 401, headers)

    email = decoded_token.get("email", "")
    role  = _get_user_role(email)
    if not role:
        logger.warning("Access denied for: %s", email)
        return make_response(jsonify({"error": "Access denied"}), 403, headers)

    action = request.args.get("action", "data")
    logger.info("user=%s action=%s", email, action)

    if action == "ping":    return _handle_ping(headers)
    if action == "me":      return _handle_me(email, role, headers)
    if action == "filters": return _handle_filters(headers)
    if action == "data":    return _handle_data(request, headers)

    return make_response(jsonify({"error": f"Unknown action: {action}"}), 400, headers)
