# ================================================================
# CAMPAIGN INTELLIGENCE API — Cloud Functions Gen 2
# Proyecto core: llyc-ai-first-core
# Lectura cross-project hacia proyectos de cliente
# SA: dashboards-sa@llyc-ai-first-core.iam.gserviceaccount.com
# ================================================================
# Endpoints (HTTP trigger, path routing via query param ?action=):
#   GET  ?action=ping                → health check
#   GET  ?action=data                → todos los datos de campaña
#   GET  ?action=data&platform=Meta  → datos de una plataforma
#   POST ?action=chat                → proxy Anthropic chat
#   POST ?action=insights            → generación de insights con caché
# ================================================================

import os
import json
import re
import hashlib
import functions_framework
from datetime import datetime, timezone, date
from google.cloud import bigquery, secretmanager
import google.cloud.logging
import logging

# ── LOGGING ───────────────────────────────────────────────────────
# Cloud Functions Gen 2 corre como Cloud Run — usar Cloud Logging
google.cloud.logging.Client().setup_logging()
log = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────
# Proyecto core — infraestructura compartida. Los jobs de BQ se facturan aquí.
CORE_PROJECT = "llyc-ai-first-core"

# Fail-loud si faltan env vars obligatorias — mejor error claro que default roto
for _var in ["GCP_CLIENT_PROJECT", "TENANT_ID", "CLIENT_SECRET_PROJECT"]:
    if not os.getenv(_var):
        raise RuntimeError(f"Missing required env var: {_var}")

# Proyecto del cliente — lectura cross-project desde el core
CLIENT_PROJECT        = os.getenv("GCP_CLIENT_PROJECT")
BQ_DATASET            = os.getenv("BQ_DATASET", "ODS")
TENANT_ID             = os.getenv("TENANT_ID")
CLIENT_SECRET_PROJECT = os.getenv("CLIENT_SECRET_PROJECT")

# Plataformas disponibles — pueden filtrarse vía config.json del cliente
PLATFORMS = ["Spotify", "TikTok", "YouTube", "Meta", "Amazon", "DOOH", "WeMass"]

TABLE_MAP = {
    "Spotify": "Spotify_native",
    "TikTok":  "TikTok_native",
    "YouTube": "Youtube_native",
    "Meta":    "Meta_native",
    "Amazon":  "Amazon_native",
    "DOOH":    "DOOH_native",
    "WeMass":  "WeMass_native",
}

# ── CLIENTS ───────────────────────────────────────────────────────
# BQ client corre en CORE_PROJECT usando dashboards-sa (--service-account del deploy)
# Los jobs se facturan en core; la lectura cross-project va al datamart del cliente
bq_client = bigquery.Client(project=CORE_PROJECT)
sm_client = secretmanager.SecretManagerServiceClient()

# Caché en memoria de insights (por instancia)
_insights_cache = {"hash": None, "insights": None}
# Caché de Anthropic client (inicializado lazy para no fallar en cold start)
_anthropic_client = None


# ── CLIENT CONFIG ─────────────────────────────────────────────────
def get_client_config() -> dict:
    """
    Lee clients/{TENANT_ID}/config.json en runtime.
    El bloque dashboard define datasources, windows y drive_folder_id.
    """
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "clients", TENANT_ID, "config.json"
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log.warning(f"config.json not found for tenant {TENANT_ID} — using defaults")
        return {}
    except Exception as e:
        log.error(f"Error reading config.json for {TENANT_ID}: {e}")
        return {}


def get_dashboard_config() -> dict:
    """Devuelve el bloque dashboard del config del cliente."""
    cfg = get_client_config()
    return cfg.get("dashboard", {
        "enabled": True,
        "datasources": [p.lower() for p in PLATFORMS],
        "windows": {"default_days": 30, "comparison_days": 7}
    })


def get_active_platforms() -> list:
    """Devuelve las plataformas activas según config.json del cliente."""
    dash_cfg = get_dashboard_config()
    datasources = [s.lower() for s in dash_cfg.get("datasources", PLATFORMS)]
    return [p for p in PLATFORMS if p.lower() in datasources]


# ── ANTHROPIC ─────────────────────────────────────────────────────
def get_anthropic_client():
    """Inicializa el cliente de Anthropic leyendo la key de Secret Manager.
    Secret naming: anthropic-api-key-campaign_intelligence-{TENANT_ID}
    Secret vive en CLIENT_SECRET_PROJECT (proyecto del cliente) — DEC_058.
    """
    global _anthropic_client
    if _anthropic_client:
        return _anthropic_client

    import anthropic
    secret_name = (
        f"projects/{CLIENT_SECRET_PROJECT}/secrets/"
        f"anthropic-api-key-campaign_intelligence-{TENANT_ID}/versions/latest"
    )
    try:
        response = sm_client.access_secret_version(name=secret_name)
        api_key = response.payload.data.decode("utf-8").strip()
    except Exception as e:
        log.error(f"Error reading Anthropic key from Secret Manager: {e}")
        raise

    _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


# ── HELPERS ───────────────────────────────────────────────────────
def query_platform(platform: str) -> dict:
    """
    Lee una tabla nativa de BQ del proyecto del cliente.
    Job de BQ corre en CORE_PROJECT (dashboards-sa).
    Lectura cross-project hacia CLIENT_PROJECT.
    """
    table = TABLE_MAP.get(platform)
    if not table:
        return {"error": f"Platform '{platform}' not found"}

    sql = f"""
        SELECT *
        FROM `{CLIENT_PROJECT}.{BQ_DATASET}.{table}`
        LIMIT 5000
    """
    try:
        rows = list(bq_client.query(sql).result())
        if not rows:
            return {
                "headers": [],
                "rows": [],
                "lastUpdated": datetime.now(timezone.utc).isoformat()
            }

        headers = list(rows[0].keys())
        data_rows = [
            [v.isoformat() if isinstance(v, (datetime, date)) else v for v in row.values()]
            for row in rows
        ]

        return {
            "headers": headers,
            "rows": data_rows,
            "lastUpdated": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        log.error(f"BQ query error for {platform}: {e}")
        return {"error": str(e)}


def get_system_prompt(extra: str = "") -> str:
    """
    System prompt con guardarraíles.
    Contexto del cliente desde config.json vía get_client_config().
    """
    cfg = get_client_config()
    client = cfg.get("client", {})

    client_name = client.get("name", TENANT_ID)
    sector      = client.get("sector", "").replace("_", " ")
    currency    = client.get("currency", "EUR")

    dash_cfg    = cfg.get("dashboard", {})
    datasources = dash_cfg.get("datasources", [])

    client_block = "\n".join(filter(None, [
        f"Cliente: {client_name}"                           if client_name  else "",
        f"Sector: {sector}"                                 if sector       else "",
        f"Moneda: {currency}",
        f"Plataformas activas: {', '.join(datasources)}"   if datasources  else "",
    ]))

    return f"""Eres un analista experto en campañas de medios pagados que trabaja para LLYC.
Tu interlocutor puede ser el cliente o el equipo interno de Paid Media.

CONTEXTO DEL CLIENTE:
{client_block or "Sin contexto específico configurado."}

ROL Y TONO:
- Respondes con datos reales, análisis concreto y recomendaciones accionables
- Tono profesional, constructivo y orientado a resultados de negocio
- Menciona métricas técnicas (CTR, CPM, CPC, CPL, VTR) cuando aporten valor
- Respuestas concisas — máximo 3-4 párrafos en el chat
- Números en formato legible (1,2M en lugar de 1.234.567)

GUARDARRAÍLES:
- Si una métrica tiene margen de mejora, preséntala como oportunidad de optimización, no como un fallo
- Nunca uses lenguaje alarmista ni señales al equipo como responsable de bajo rendimiento
- Si una plataforma rinde por debajo, encúadralo como diversificación de mix o aprendizaje
- Comparativas entre plataformas: información para decidir, no ranking de ganadores/perdedores
- Si preguntan por algo negativo, reconócelo con honestidad + contexto + paso siguiente concreto

FORMATO: Responde en español.
{extra}"""


def json_response(data: dict, status: int = 200):
    """Helper para devolver JSON con CORS headers."""
    import flask
    response = flask.make_response(json.dumps(data, ensure_ascii=False), status)
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


# ── CLOUD FUNCTION ENTRYPOINT ─────────────────────────────────────
@functions_framework.http
def dashboard_api(request):
    """
    HTTP trigger único para todas las acciones del dashboard.
    Routing via query param ?action=
    """
    # CORS preflight
    if request.method == "OPTIONS":
        return json_response({}, 204)

    action = request.args.get("action", "ping")
    log.info(f"dashboard_api called: action={action} tenant={TENANT_ID}")

    # ── PING ──────────────────────────────────────────────────────
    if action == "ping":
        return json_response({
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "tenant": TENANT_ID,
            "client_project": CLIENT_PROJECT
        })

    # ── DATA ──────────────────────────────────────────────────────
    if action == "data":
        active_platforms = get_active_platforms()

        platform = request.args.get("platform")
        if platform:
            if platform not in active_platforms:
                return json_response({"error": f"Platform '{platform}' not supported"}, 404)
            return json_response(query_platform(platform))

        result = {}
        for p in active_platforms:
            result[p] = query_platform(p)

        return json_response({
            "data": result,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "tenant": TENANT_ID
        })

    # ── CHAT ──────────────────────────────────────────────────────
    if action == "chat" and request.method == "POST":
        body = request.get_json(silent=True) or {}
        messages     = body.get("messages", [])
        data_summary = body.get("dataSummary", "")

        if not messages:
            return json_response({"error": "No messages provided"}, 400)

        system = get_system_prompt(
            f"\nDATOS ACTUALES DE CAMPAÑA:\n{data_summary}" if data_summary else ""
        )
        try:
            ai = get_anthropic_client()
            response = ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=system,
                messages=messages
            )
            return json_response({"reply": response.content[0].text})
        except Exception as e:
            log.error(f"Anthropic chat error: {e}")
            return json_response({"error": str(e)}, 500)

    # ── INSIGHTS ──────────────────────────────────────────────────
    if action == "insights" and request.method == "POST":
        body       = request.get_json(silent=True) or {}
        summary    = body.get("summary", "")
        fetched_at = body.get("fetchedAt", "")

        cache_key = hashlib.md5(fetched_at.encode()).hexdigest() if fetched_at else None
        if cache_key and _insights_cache["hash"] == cache_key and _insights_cache["insights"]:
            return json_response({"insights": _insights_cache["insights"], "fromCache": True})

        system = get_system_prompt("""
TAREA: Analiza los datos y genera 5-6 insights en JSON.
Responde SOLO con JSON válido sin markdown:
{"insights":[{"type":"positive|opportunity|info","tag":"etiqueta corta","text":"insight en español, 1-2 frases accionables"}]}
- "positive": resultados destacables
- "opportunity": mejoras encuadradas constructivamente
- "info": contexto relevante""")

        try:
            ai = get_anthropic_client()
            response = ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                system=system,
                messages=[{"role": "user", "content": f"Datos de campaña:\n{summary}"}]
            )
            text = response.content[0].text
            # Extraer solo el bloque JSON — busca el primer { y el último }
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                text = text[start:end]
            parsed = json.loads(text)

            if cache_key:
                _insights_cache["hash"]     = cache_key
                _insights_cache["insights"] = parsed.get("insights", [])

            return json_response({**parsed, "fromCache": False})
        except Exception as e:
            log.error(f"Anthropic insights error: {e}")
            return json_response({"error": str(e)}, 500)

    return json_response({"error": f"Unknown action: {action}"}, 400)