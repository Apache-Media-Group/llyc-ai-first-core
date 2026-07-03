# ================================================================
# CAMPAIGN INTELLIGENCE API — Cloud Functions Gen 2
# Proyecto core: llyc-ai-first-core
# Lectura cross-project hacia proyectos de cliente
# SA: dashboards-sa@llyc-ai-first-core.iam.gserviceaccount.com
# ================================================================
# Endpoints (HTTP trigger, path routing via query param ?action=):
#   GET  ?action=ping                → health check
#   GET  ?action=me                  → info del usuario autenticado + rol
#   GET  ?action=data                → todos los datos de campaña
#   GET  ?action=data&platform=Meta  → datos de una plataforma
#   POST ?action=chat                → proxy Anthropic chat
#   POST ?action=insights            → generación de insights con caché
# ================================================================

import os
import json
import hashlib
import functions_framework
from datetime import datetime, timezone, date
from google.cloud import bigquery, secretmanager
import google.cloud.logging
import logging
import firebase_admin
from firebase_admin import auth as firebase_auth

# Initialize Firebase Admin SDK (uses application default credentials)
if not firebase_admin._apps:
    firebase_admin.initialize_app()

# ── LOGGING ───────────────────────────────────────────────────────
google.cloud.logging.Client().setup_logging()
log = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────
CORE_PROJECT = "llyc-ai-first-core"

for _var in ["GCP_CLIENT_PROJECT", "TENANT_ID", "CLIENT_SECRET_PROJECT"]:
    if not os.getenv(_var):
        raise RuntimeError(f"Missing required env var: {_var}")

CLIENT_PROJECT        = os.getenv("GCP_CLIENT_PROJECT")
BQ_DATASET            = os.getenv("BQ_DATASET", "ODS")
TENANT_ID             = os.getenv("TENANT_ID")
CLIENT_SECRET_PROJECT = os.getenv("CLIENT_SECRET_PROJECT")

KNOWN_TENANTS = set(
    t.strip() for t in os.getenv("KNOWN_TENANTS", TENANT_ID).split(";") if t.strip()
)

TENANT_CONFIG = {
    t: {
        "client_project": os.getenv(f"CLIENT_PROJECT_{t.upper()}", os.getenv("GCP_CLIENT_PROJECT")),
        "bq_dataset": os.getenv("BQ_DATASET", "ODS"),
        "client_secret_project": os.getenv(f"SECRET_PROJECT_{t.upper()}", os.getenv("CLIENT_SECRET_PROJECT")),
    }
    for t in KNOWN_TENANTS
}

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

bq_client = bigquery.Client(project=CORE_PROJECT)
sm_client = secretmanager.SecretManagerServiceClient()

_insights_cache = {"hash": None, "insights": None}
_anthropic_client = None


# ── CLIENT CONFIG ─────────────────────────────────────────────────
def get_client_config(tenant_id=None) -> dict:
    effective_tenant = tenant_id or TENANT_ID
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "clients", effective_tenant, "config.json"
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log.warning(f"config.json not found for tenant {effective_tenant} — using defaults")
        return {}
    except Exception as e:
        log.error(f"Error reading config.json for {effective_tenant}: {e}")
        return {}


def get_dashboard_config(tenant_id=None) -> dict:
    cfg = get_client_config(tenant_id)
    return cfg.get("dashboard", {
        "enabled": True,
        "datasources": [p.lower() for p in PLATFORMS],
        "windows": {"default_days": 30, "comparison_days": 7}
    })


def get_active_platforms(tenant_id=None) -> list:
    dash_cfg = get_dashboard_config(tenant_id)
    datasources = [s.lower() for s in dash_cfg.get("datasources", PLATFORMS)]
    return [p for p in PLATFORMS if p.lower() in datasources]


# ── FIREBASE AUTH ─────────────────────────────────────────────────
def get_allowed_emails(tenant_id=None) -> list:
    """
    Lee la allowlist de emails autorizados.
    Soporta formato email:role y email simple en ALLOWED_EMAILS env var.
    Retorna lista de emails (solo la parte antes de :).
    """
    env_emails = os.getenv("ALLOWED_EMAILS", "")
    if env_emails:
        emails = []
        for entry in env_emails.split(";"):
            email = entry.strip().split(":")[0].strip().lower()
            if email:
                emails.append(email)
        return emails
    return []


def get_user_role(email: str, tenant_id=None) -> str:
    """
    Devuelve el rol del usuario desde ALLOWED_EMAILS env var.
    Formato esperado: email:role;email:role
    Ejemplo: sergio.alonso@llyc.global:editor;alberto.gonzalez@llyc.global:viewer
    """
    env_emails = os.getenv("ALLOWED_EMAILS", "")
    email_lower = email.strip().lower()
    for entry in env_emails.split(";"):
        parts = entry.strip().split(":")
        if len(parts) >= 2 and parts[0].strip().lower() == email_lower:
            return parts[1].strip()
    return "viewer"


def verify_firebase_token(request, tenant_id=None) -> tuple:
    """
    Verifica token Firebase y comprueba allowlist.
    Retorna (autorizado, email, role).
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False, "", "viewer"
    id_token = auth_header.split("Bearer ")[1]
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        email = decoded.get("email", "").strip().lower()
        effective_tenant = tenant_id or TENANT_ID
        allowed_emails = get_allowed_emails(effective_tenant)
        if email in allowed_emails:
            role = get_user_role(email, effective_tenant)
            log.info(f"Auth OK: {email} role={role} tenant={effective_tenant}")
            return True, email, role
        log.warning(f"Access denied for email: {email} on tenant: {effective_tenant}")
        return False, email, "viewer"
    except Exception as e:
        log.error(f"Firebase token verification failed: {e}")
        return False, "", "viewer"


def resolve_tenant(request):
    """Resuelve y valida tenant_id desde la URL."""
    url_tenant = request.args.get("tenant_id", "").strip()
    if not url_tenant:
        return TENANT_ID, TENANT_CONFIG.get(TENANT_ID, {})
    if url_tenant not in KNOWN_TENANTS:
        raise ValueError(f"Unknown tenant_id: {url_tenant}")
    return url_tenant, TENANT_CONFIG.get(url_tenant, {})


# ── ANTHROPIC ─────────────────────────────────────────────────────
def get_anthropic_client():
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
def query_platform(platform: str, client_project: str = None, bq_dataset: str = None) -> dict:
    table = TABLE_MAP.get(platform)
    if not table:
        return {"error": f"Platform '{platform}' not found"}
    cp = client_project or CLIENT_PROJECT
    ds = bq_dataset or BQ_DATASET
    sql = f"SELECT * FROM `{cp}.{ds}.{table}` LIMIT 5000"
    try:
        rows = list(bq_client.query(sql).result())
        if not rows:
            return {"headers": [], "rows": [], "lastUpdated": datetime.now(timezone.utc).isoformat()}
        headers = list(rows[0].keys())
        data_rows = [
            [v.isoformat() if isinstance(v, (datetime, date)) else v for v in row.values()]
            for row in rows
        ]
        return {"headers": headers, "rows": data_rows, "lastUpdated": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        log.error(f"BQ query error for {platform}: {e}")
        return {"error": str(e)}


def get_system_prompt(extra: str = "") -> str:
    cfg = get_client_config()
    client = cfg.get("client", {})
    client_name = client.get("name", TENANT_ID)
    sector      = client.get("sector", "").replace("_", " ")
    currency    = client.get("currency", "EUR")
    dash_cfg    = cfg.get("dashboard", {})
    datasources = dash_cfg.get("datasources", [])
    client_block = "\n".join(filter(None, [
        f"Cliente: {client_name}" if client_name else "",
        f"Sector: {sector}"       if sector      else "",
        f"Moneda: {currency}",
        f"Plataformas activas: {', '.join(datasources)}" if datasources else "",
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
    import flask
    response = flask.make_response(json.dumps(data, ensure_ascii=False), status)
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


# ── CLOUD FUNCTION ENTRYPOINT ─────────────────────────────────────
@functions_framework.http
def dashboard_api(request):
    if request.method == "OPTIONS":
        return json_response({}, 204)

    action = request.args.get("action", "ping")

    try:
        req_tenant, tenant_cfg = resolve_tenant(request)
    except ValueError as e:
        return json_response({"error": str(e)}, 403)

    req_client_project = tenant_cfg.get("client_project", CLIENT_PROJECT)
    req_bq_dataset     = tenant_cfg.get("bq_dataset", BQ_DATASET)

    log.info(f"dashboard_api called: action={action} tenant={req_tenant}")

    # Ping no requiere auth
    if action == "ping":
        return json_response({
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "tenant": req_tenant,
            "client_project": req_client_project
        })

    # Todos los demás endpoints requieren auth
    authorized, email, user_role = verify_firebase_token(request, req_tenant)
    if not authorized:
        return json_response({"error": "Unauthorized"}, 401)

    # ── ME ────────────────────────────────────────────────────────
    if action == "me":
        return json_response({
            "email": email,
            "role": user_role,
            "tenant": req_tenant
        })

    # ── DATA ──────────────────────────────────────────────────────
    if action == "data":
        active_platforms = get_active_platforms(req_tenant)
        platform = request.args.get("platform")
        if platform:
            if platform not in active_platforms:
                return json_response({"error": f"Platform '{platform}' not supported"}, 404)
            return json_response(query_platform(platform, req_client_project, req_bq_dataset))
        result = {}
        for p in active_platforms:
            result[p] = query_platform(p, req_client_project, req_bq_dataset)
        return json_response({
            "data": result,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "tenant": req_tenant,
            "userRole": user_role
        })

    # ── CHAT ──────────────────────────────────────────────────────
    if action == "chat" and request.method == "POST":
        body = request.get_json(silent=True) or {}
        messages     = body.get("messages", [])
        data_summary = body.get("dataSummary", "")
        if not messages:
            return json_response({"error": "No messages provided"}, 400)
        system = get_system_prompt(f"\nDATOS ACTUALES DE CAMPAÑA:\n{data_summary}" if data_summary else "")
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
        cache_key  = hashlib.md5(fetched_at.encode()).hexdigest() if fetched_at else None
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