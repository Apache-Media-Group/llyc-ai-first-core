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
  GET ?action=summary&.. → resumen ejecutivo IA del dataset filtrado
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
from google.cloud import bigquery, secretmanager
import anthropic

# ── INIT ──────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not firebase_admin._apps:
    firebase_admin.initialize_app()

bq_client = bigquery.Client()
sm_client = secretmanager.SecretManagerServiceClient()

# Nombre del secret de Anthropic (DEC_058 / DEC_089)
# Proyecto cliente separado — no core (guardrail DEC_058)
ANTHROPIC_SECRET = (
    "projects/llyc-ai-turespana/secrets/"
    "anthropic-api-key-sentiment_intelligence-turespana/versions/latest"
)
_anthropic_client: Optional[anthropic.Anthropic] = None   # lazy init

# ── CONFIG ────────────────────────────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "clients", "turespana", "config.json")
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

BQ_TABLE        = CONFIG["bq_table"]
PARTNER_FILTER  = CONFIG["partner_filter"]
ALLOWED_ORIGINS = CONFIG.get("allowed_origins", ["https://dashboard.llyc.global"])

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

FILTER_DIMS = [
    "provider", "market", "campaign_objective", "campaign_grouping",
    "ad_format", "ad_type", "ad_audience", "ad_language", "ad_version",
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
    params = request.args
    where, bq_params = _build_where(params)

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

    benchmarks_by_provider: dict = {}
    for row in rows:
        p = row.provider
        if p and p not in benchmarks_by_provider:
            benchmarks_by_provider[p] = {
                "threshold_avg":       float(row.threshold_avg or 0),
                "threshold_excellent": float(row.threshold_excellent or 0),
            }

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


# ── ANTHROPIC ─────────────────────────────────────────────────────────────────
def _get_anthropic_client() -> anthropic.Anthropic:
    """Lazy init — carga la key desde Secret Manager una sola vez por instancia."""
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    try:
        response = sm_client.access_secret_version(name=ANTHROPIC_SECRET)
        api_key  = response.payload.data.decode("utf-8").strip()
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
        return _anthropic_client
    except Exception as e:
        raise RuntimeError(f"No se pudo cargar la API key de Anthropic: {e}")


def _build_summary_payload(rows: list[dict]) -> str:
    """Construye estadísticas agregadas para el LLM. Nunca envía el dataset completo."""
    if not rows:
        return "No hay datos para analizar con los filtros seleccionados."

    levels: dict = {}
    by_format:   dict = {}
    by_market:   dict = {}
    by_audience: dict = {}
    total_spend = 0.0
    total_imp   = 0

    for r in rows:
        lvl = r.get("perf_level_sentiment", "Sin Score")
        if lvl not in levels:
            levels[lvl] = {"count": 0, "spend": 0.0, "score_sum": 0.0, "imp": 0}
        levels[lvl]["count"]     += 1
        levels[lvl]["spend"]     += r.get("spend", 0) or 0
        levels[lvl]["score_sum"] += r.get("score_w_ad") or 0
        levels[lvl]["imp"]       += r.get("impressions", 0) or 0
        total_spend += r.get("spend", 0) or 0
        total_imp   += r.get("impressions", 0) or 0

        for dim, store in [("ad_format", by_format),
                           ("market",    by_market),
                           ("ad_audience", by_audience)]:
            key = r.get(dim) or "—"
            if key not in store:
                store[key] = {"count": 0, "score_sum": 0.0, "imp": 0, "spend": 0.0}
            store[key]["count"]     += 1
            store[key]["score_sum"] += r.get("score_w_ad") or 0
            store[key]["imp"]       += r.get("impressions", 0) or 0
            store[key]["spend"]     += r.get("spend", 0) or 0

    def top_by_score(store: dict, n: int = 5) -> list:
        ranked = [(k, v["score_sum"] / max(v["count"], 1), v["spend"], v["count"])
                  for k, v in store.items() if k != "—"]
        return sorted(ranked, key=lambda x: -x[1])[:n]

    scored = [r for r in rows if r.get("score_w_ad") is not None]
    top5   = sorted(scored, key=lambda r: -(r["score_w_ad"] or 0))[:5]
    bot5   = sorted(
        [r for r in scored if (r.get("spend") or 0) > 50],
        key=lambda r: (r["score_w_ad"] or 0)
    )[:5]

    thr_exc = next((r["threshold_excellent"] for r in rows if r.get("threshold_excellent")), 0)
    thr_avg = next((r["threshold_avg"] for r in rows if r.get("threshold_avg")), 0)

    def fmt_level(lvl):
        d = levels.get(lvl, {})
        n = d.get("count", 0)
        s = d.get("spend", 0)
        avg_sc = d["score_sum"] / n if n else 0
        return f"{n} ads | €{s:,.0f} inversión | score medio {avg_sc:.2f}"

    lines = [
        f"TOTAL: {len(rows)} ads analizados | €{total_spend:,.0f} inversión | {total_imp:,} impresiones",
        f"Umbral Excelente: {thr_exc:.2f} | Umbral Alto: {thr_avg:.2f}",
        "",
        "DISTRIBUCIÓN POR NIVEL:",
        f"  1.Excelente (Top): {fmt_level('1.Excelente (Top)')}",
        f"  2.Alto:            {fmt_level('2.Alto')}",
        f"  3.Bajo:            {fmt_level('3.Bajo')}",
        f"  0.Sin Score:       {fmt_level('0.Sin Score')}",
        "",
        "TOP 5 FORMATOS por score medio:",
    ] + [f"  {k}: score={sc:.2f} | €{sp:,.0f} | {n} ads"
         for k, sc, sp, n in top_by_score(by_format)] + [
        "",
        "TOP 5 MERCADOS por score medio:",
    ] + [f"  {k}: score={sc:.2f} | €{sp:,.0f} | {n} ads"
         for k, sc, sp, n in top_by_score(by_market)] + [
        "",
        "TOP 5 AUDIENCIAS por score medio:",
    ] + [f"  {k}: score={sc:.2f} | €{sp:,.0f} | {n} ads"
         for k, sc, sp, n in top_by_score(by_audience)] + [
        "",
        "TOP 5 ADS INDIVIDUALES (mayor score):",
    ] + [f"  [{r.get('provider','')} | {r.get('ad_format','')} | {r.get('market','')}] "
         f"score={r['score_w_ad']:.2f} | €{r.get('spend',0):,.0f} | {r.get('ad_name','')[:60]}"
         for r in top5] + [
        "",
        "5 ADS CON MAYOR INVERSIÓN Y BAJO RENDIMIENTO:",
    ] + [f"  [{r.get('provider','')} | {r.get('ad_format','')} | {r.get('market','')}] "
         f"score={r['score_w_ad']:.2f} | €{r.get('spend',0):,.0f} | {r.get('ad_name','')[:60]}"
         for r in bot5]

    return "\n".join(lines)


def _handle_summary(request: Request, headers: dict):
    """Genera un resumen ejecutivo IA del dataset filtrado actual."""
    params = request.args
    where, bq_params = _build_where(params)
    data_query = f"""
        SELECT {SELECT_COLS}
        FROM `{BQ_TABLE}`
        WHERE {where}
        ORDER BY score_w_ad DESC NULLS LAST
        LIMIT 10000
    """
    job_config = bigquery.QueryJobConfig(query_parameters=bq_params)
    try:
        rows = [_row_to_dict(r) for r in
                bq_client.query(data_query, job_config=job_config).result()]
    except Exception as e:
        logger.error("BQ summary error: %s", e)
        return make_response(jsonify({"error": f"BigQuery error: {e}"}), 500, headers)

    active_filters = {k: v for k, v in params.items() if k in FILTER_DIMS and v}
    filter_ctx = ", ".join(f"{k}={v}" for k, v in active_filters.items()) or "sin filtros"

    payload = _build_summary_payload(rows)
    prompt  = f"""Eres el analista creativo senior de LLYC, especializado en campañas de paid media para clientes de turismo y marca país.

Cliente: {PARTNER_FILTER}
Filtros activos: {filter_ctx}

Datos agregados del análisis de scoring emocional:

{payload}

Redacta un informe ejecutivo en español con estas cuatro secciones. Usa un tono estratégico y constructivo — el objetivo es identificar oportunidades y priorizar acciones, no señalar problemas. Evita lenguaje alarmista. Apóyate en los datos pero habla en términos de negocio, no de métricas técnicas:

**1. Situación del portfolio creativo**
Describe el estado general de las campañas de forma equilibrada. Menciona el volumen total, la distribución de niveles y el dato más relevante para el equipo. Máximo 4 líneas.

**2. Señales creativas positivas**
Identifica los formatos, mercados o audiencias que destacan por su conexión emocional. Explica qué tienen en común las piezas que mejor funcionan y por qué son relevantes para la estrategia. Máximo 5 líneas.

**3. Oportunidades de optimización**
Señala dónde hay margen de mejora, con foco en redistribución de presupuesto o ajuste creativo. Sé específico pero constructivo — no es un juicio, es una oportunidad. Máximo 4 líneas.

**4. Próximos pasos recomendados**
3 acciones concretas y priorizadas que el equipo puede ejecutar en los próximos días. Cada una en una línea, con formato: acción → impacto esperado."""

    try:
        client = _get_anthropic_client()
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        summary_text = message.content[0].text
    except RuntimeError as e:
        logger.warning("Anthropic key unavailable: %s", e)
        return make_response(jsonify({
            "error": "API key de Anthropic pendiente de configurar. Contacta con el equipo técnico."
        }), 503, headers)
    except Exception as e:
        logger.error("Anthropic API error: %s", e)
        return make_response(jsonify({"error": f"Error generando resumen: {e}"}), 500, headers)

    return make_response(jsonify({
        "summary":      summary_text,
        "ads_count":    len(rows),
        "filters":      active_filters,
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
    if action == "summary": return _handle_summary(request, headers)

    return make_response(jsonify({"error": f"Unknown action: {action}"}), 400, headers)