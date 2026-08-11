# ================================================================
# CAMPAIGN INTELLIGENCE API — Cloud Functions Gen 2
# Proyecto core: llyc-ai-first-core
# Multi-tenant: tenant_id resuelto por request, proyecto/secret desde config
# SA: dashboards-sa@llyc-ai-first-core.iam.gserviceaccount.com
# ================================================================
# Endpoints (HTTP trigger, path routing via query param ?action=):
#   GET  ?action=ping                → health check (no auth)
#   GET  ?action=me                  → info del usuario autenticado + rol
#   GET  ?action=data                → todos los datos de campaña
#   GET  ?action=data&platform=Meta  → datos de una plataforma
#   POST ?action=chat                → proxy Anthropic chat
#   POST ?action=insights            → generación de insights con caché
#   GET  ?action=getConfig           → config visual + lista de accesos (Firestore)
#   POST ?action=saveConfig          → guarda config visual + accesos (solo editor)
# ================================================================

import os
import json
import hashlib
import functions_framework
from datetime import datetime, timezone, date
from google.cloud import bigquery, secretmanager, firestore
import google.cloud.logging
import logging
import firebase_admin
from firebase_admin import auth as firebase_auth

from platform_config import (
    get_active_platforms as _derive_active_platforms,
    resolve_table,
)

# ── FIREBASE ADMIN ────────────────────────────────────────────────
if not firebase_admin._apps:
    firebase_admin.initialize_app()

# ── LOGGING ───────────────────────────────────────────────────────
# Cloud Functions Gen 2 corre como Cloud Run — usar Cloud Logging
google.cloud.logging.Client().setup_logging()
log = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────
# Proyecto core — infraestructura compartida. Los jobs de BQ se facturan aquí.
CORE_PROJECT = "llyc-ai-first-core"

# Fallback de tenant si la request no pasa tenant_id (conveniencia local/debug,
# NO sustituye a resolve_tenant en producción — ahí el tenant_id llega por query).
DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID", "")

# ── CLIENTS (compartidos, sin estado de tenant) ───────────────────
# BQ client corre en CORE_PROJECT usando dashboards-sa (--service-account del deploy)
# Los jobs se facturan en core; la lectura cross-project va al proyecto del tenant.
bq_client = bigquery.Client(project=CORE_PROJECT)
sm_client = secretmanager.SecretManagerServiceClient()
fs_client = firestore.Client(project=CORE_PROJECT)

# Caché en memoria de insights — por instancia, sin distinguir tenant todavía
# (aceptable: cada instancia de CF ya suele servir ráfagas del mismo tenant).
_insights_cache = {"hash": None, "insights": None}

# Caché de clientes Anthropic — SÍ por tenant, cada uno tiene su propia key.
_anthropic_clients = {}


# ── TENANT RESOLUTION ─────────────────────────────────────────────
def resolve_tenant_id(request) -> str:
    """
    Resuelve el tenant_id desde el query param. Sin fallback oculto a un
    tenant fijo: si no llega y no hay DEFAULT_TENANT_ID, es error explícito.
    """
    tenant_id = request.args.get("tenant_id", "").strip()
    if not tenant_id:
        tenant_id = DEFAULT_TENANT_ID
    if not tenant_id:
        raise ValueError("tenant_id no provisto y no hay DEFAULT_TENANT_ID configurado")
    return tenant_id


# ── CLIENT CONFIG ─────────────────────────────────────────────────
def get_client_config(tenant_id: str) -> dict:
    """
    Lee clients/{tenant_id}/config.json en runtime.
    Onboarding de tenant nuevo = añadir este fichero, nada más — no hay
    KNOWN_TENANTS ni env vars por cliente que mantener (DEC_024/089).
    """
    config_path = os.path.join(
        os.path.dirname(__file__), "clients", tenant_id, "config.json"
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log.warning(f"config.json not found for tenant {tenant_id}")
        return {}
    except Exception as e:
        log.error(f"Error reading config.json for {tenant_id}: {e}")
        return {}


def get_dashboard_config(cfg: dict) -> dict:
    """Bloque dashboard del config ya cargado (vacío si no existe)."""
    return cfg.get("dashboard", {})


def get_gcp_config(cfg: dict) -> dict:
    """
    Bloque gcp del config del tenant — de aquí sale a qué proyecto/dataset
    leer y en qué proyecto vive el secret de Anthropic. Fail-loud si falta
    algo imprescindible: mejor error claro que leer del proyecto equivocado.
    """
    gcp_cfg = cfg.get("gcp", {})
    required = ["project_id", "secret_manager_project"]
    missing = [k for k in required if not gcp_cfg.get(k)]
    if missing:
        raise ValueError(f"config.gcp incompleto, faltan: {missing}")
    return gcp_cfg


def get_active_platforms(dashboard_cfg: dict) -> list:
    """Plataformas activas del tenant. Delega en platform_config (lógica pura)."""
    return _derive_active_platforms(dashboard_cfg)


# ── FIREBASE AUTH + ACCESOS (Firestore) ───────────────────────────
def get_access_list(tenant_id: str) -> list:
    """
    Lista de accesos del tenant desde Firestore (colección dashboard_configs,
    un doc por tenant). Formato: [{"email": "...", "role": "editor|viewer"}].
    Fuente única de verdad de accesos — NO env vars (evita split-brain con
    el panel de gestión de accesos, que escribe aquí mismo vía saveConfig).
    """
    try:
        doc = fs_client.collection("dashboard_configs").document(tenant_id).get()
        if not doc.exists:
            return []
        return doc.to_dict().get("accessList", [])
    except Exception as e:
        log.error(f"Error leyendo access_list de Firestore para {tenant_id}: {e}")
        return []


def get_user_role(email: str, access_list: list) -> str | None:
    """
    Rol del usuario dentro de la access_list ya cargada. None si el email
    no está en la lista — distinto de "viewer": None es "sin acceso".
    """
    email_lower = email.strip().lower()
    for entry in access_list:
        if entry.get("email", "").strip().lower() == email_lower:
            return entry.get("role", "viewer")
    return None


def verify_firebase_token(request, tenant_id: str) -> tuple:
    """
    Verifica el ID token de Firebase y comprueba la access_list del tenant.
    Retorna (autorizado, email, role). role es None si no autorizado.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False, "", None
    id_token = auth_header.split("Bearer ")[1]
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        email = decoded.get("email", "").strip().lower()
    except Exception as e:
        log.error(f"Firebase token verification failed: {e}")
        return False, "", None

    access_list = get_access_list(tenant_id)
    role = get_user_role(email, access_list)
    if role is None:
        log.warning(f"Access denied for {email} on tenant {tenant_id} (no en access_list)")
        return False, email, None

    log.info(f"Auth OK: {email} role={role} tenant={tenant_id}")
    return True, email, role


# ── ANTHROPIC ─────────────────────────────────────────────────────
def get_anthropic_client(tenant_id: str, secret_manager_project: str):
    """
    Cliente de Anthropic por tenant (cada uno tiene su propia key, DEC_058).
    Secret naming: anthropic-api-key-campaign_intelligence-{tenant_id}
    Secret vive en secret_manager_project (proyecto del cliente).
    """
    if tenant_id in _anthropic_clients:
        return _anthropic_clients[tenant_id]

    import anthropic

    secret_name = (
        f"projects/{secret_manager_project}/secrets/"
        f"anthropic-api-key-campaign_intelligence-{tenant_id}/versions/latest"
    )
    try:
        response = sm_client.access_secret_version(name=secret_name)
        api_key = response.payload.data.decode("utf-8").strip()
    except Exception as e:
        log.error(f"Error reading Anthropic key from Secret Manager ({tenant_id}): {e}")
        raise

    client = anthropic.Anthropic(api_key=api_key)
    _anthropic_clients[tenant_id] = client
    return client


# ── HELPERS ───────────────────────────────────────────────────────
def query_platform(platform: str, dashboard_cfg: dict, client_project: str, bq_dataset: str) -> dict:
    """
    Lee una tabla nativa de BQ del proyecto del tenant.
    Job de BQ corre en CORE_PROJECT (dashboards-sa).
    Lectura cross-project hacia client_project.
    """
    table_map = dashboard_cfg.get("table_map", {})
    table = resolve_table(platform, table_map)
    if not table:
        return {"error": f"Platform '{platform}' not found"}

    sql = f"""
        SELECT *
        FROM `{client_project}.{bq_dataset}.{table}`
        LIMIT 5000
    """
    try:
        rows = list(bq_client.query(sql).result())
        if not rows:
            return {
                "headers": [],
                "rows": [],
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
            }

        headers = list(rows[0].keys())
        data_rows = [
            [
                v.isoformat() if isinstance(v, (datetime, date)) else v
                for v in row.values()
            ]
            for row in rows
        ]

        return {
            "headers": headers,
            "rows": data_rows,
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        log.error(f"BQ query error for {platform}: {e}")
        return {"error": str(e)}


def get_system_prompt(cfg: dict, tenant_id: str, extra: str = "") -> str:
    """System prompt con guardarraíles. Contexto del cliente desde el config ya cargado."""
    client = cfg.get("client", {})

    client_name = client.get("name", tenant_id)
    sector = client.get("sector", "").replace("_", " ")
    currency = client.get("currency", "EUR")

    dash_cfg = cfg.get("dashboard", {})
    datasources = dash_cfg.get("datasources", [])

    client_block = "\n".join(
        filter(
            None,
            [
                f"Cliente: {client_name}" if client_name else "",
                f"Sector: {sector}" if sector else "",
                f"Moneda: {currency}",
                f"Plataformas activas: {', '.join(datasources)}" if datasources else "",
            ],
        )
    )

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
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


# ── CLOUD FUNCTION ENTRYPOINT ─────────────────────────────────────
@functions_framework.http
def dashboard_api(request):
    """
    HTTP trigger único para todas las acciones del dashboard, multi-tenant.
    Routing via query param ?action= ; tenant vía query param ?tenant_id=
    """
    if request.method == "OPTIONS":
        return json_response({}, 204)

    action = request.args.get("action", "ping")

    try:
        tenant_id = resolve_tenant_id(request)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)

    log.info(f"dashboard_api called: action={action} tenant={tenant_id}")

    # ── PING ─────────────────────────────────────────────────────
    # No requiere auth — health check y confirmación de que el tenant existe.
    if action == "ping":
        cfg = get_client_config(tenant_id)
        return json_response(
            {
                "ok": True,
                "ts": datetime.now(timezone.utc).isoformat(),
                "tenant": tenant_id,
                "tenant_known": bool(cfg),
            }
        )

    # Todo lo demás requiere auth real contra la access_list de Firestore.
    authorized, email, user_role = verify_firebase_token(request, tenant_id)
    if not authorized:
        return json_response({"error": "Unauthorized"}, 401)

    # Config del tenant, cargado una vez por request.
    cfg = get_client_config(tenant_id)
    if not cfg:
        return json_response({"error": f"Unknown tenant: {tenant_id}"}, 404)

    dashboard_cfg = get_dashboard_config(cfg)

    try:
        gcp_cfg = get_gcp_config(cfg)
    except ValueError as e:
        log.error(f"Config GCP inválida para {tenant_id}: {e}")
        return json_response({"error": str(e)}, 500)

    client_project = gcp_cfg["project_id"]
    bq_dataset = gcp_cfg.get("bq_dataset", "ODS")
    secret_manager_project = gcp_cfg["secret_manager_project"]

    # ── ME ───────────────────────────────────────────────────────
    if action == "me":
        return json_response({"email": email, "role": user_role, "tenant": tenant_id})

    # ── DATA ─────────────────────────────────────────────────────
    if action == "data":
        try:
            active_platforms = get_active_platforms(dashboard_cfg)
        except ValueError as e:
            log.error(f"Config de plataformas inválida para {tenant_id}: {e}")
            return json_response({"error": str(e)}, 500)

        platform = request.args.get("platform")
        if platform:
            if platform not in active_platforms:
                return json_response({"error": f"Platform '{platform}' not supported"}, 404)
            return json_response(query_platform(platform, dashboard_cfg, client_project, bq_dataset))

        result = {}
        for p in active_platforms:
            result[p] = query_platform(p, dashboard_cfg, client_project, bq_dataset)

        return json_response(
            {
                "data": result,
                "fetchedAt": datetime.now(timezone.utc).isoformat(),
                "tenant": tenant_id,
                "userRole": user_role,
            }
        )

    # ── CHAT ─────────────────────────────────────────────────────
    if action == "chat" and request.method == "POST":
        body = request.get_json(silent=True) or {}
        messages = body.get("messages", [])
        data_summary = body.get("dataSummary", "")

        if not messages:
            return json_response({"error": "No messages provided"}, 400)

        system = get_system_prompt(
            cfg, tenant_id,
            f"\nDATOS ACTUALES DE CAMPAÑA:\n{data_summary}" if data_summary else "",
        )
        try:
            ai = get_anthropic_client(tenant_id, secret_manager_project)
            response = ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=system,
                messages=messages,
            )
            return json_response({"reply": response.content[0].text})
        except Exception as e:
            log.error(f"Anthropic chat error: {e}")
            return json_response({"error": str(e)}, 500)

    # ── INSIGHTS ─────────────────────────────────────────────────
    if action == "insights" and request.method == "POST":
        body = request.get_json(silent=True) or {}
        summary = body.get("summary", "")
        fetched_at = body.get("fetchedAt", "")

        cache_key = (
            hashlib.md5(f"{tenant_id}:{fetched_at}".encode()).hexdigest()
            if fetched_at else None
        )
        if (
            cache_key
            and _insights_cache["hash"] == cache_key
            and _insights_cache["insights"]
        ):
            return json_response({"insights": _insights_cache["insights"], "fromCache": True})

        system = get_system_prompt(cfg, tenant_id, """
TAREA: Analiza los datos y genera 5-6 insights en JSON.
Responde SOLO con JSON válido sin markdown:
{"insights":[{"type":"positive|opportunity|info","tag":"etiqueta corta","text":"insight en español, 1-2 frases accionables"}]}
- "positive": resultados destacables
- "opportunity": mejoras encuadradas constructivamente
- "info": contexto relevante""")

        try:
            ai = get_anthropic_client(tenant_id, secret_manager_project)
            response = ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                system=system,
                messages=[{"role": "user", "content": f"Datos de campaña:\n{summary}"}],
            )
            text = response.content[0].text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]
            parsed = json.loads(text)

            if cache_key:
                _insights_cache["hash"] = cache_key
                _insights_cache["insights"] = parsed.get("insights", [])

            return json_response({**parsed, "fromCache": False})
        except Exception as e:
            log.error(f"Anthropic insights error: {e}")
            return json_response({"error": str(e)}, 500)

    # ── GET CONFIG (panel visual + accesos) ─────────────────────
    if action == "getConfig":
        try:
            doc = fs_client.collection("dashboard_configs").document(tenant_id).get()
            saved_cfg = doc.to_dict() if doc.exists else {}
            return json_response({"config": saved_cfg})
        except Exception as e:
            log.error(f"Firestore getConfig error ({tenant_id}): {e}")
            return json_response({"config": {}})

    # ── SAVE CONFIG (panel visual + accesos, solo editor) ───────
    if action == "saveConfig" and request.method == "POST":
        if user_role != "editor":
            return json_response({"error": "Forbidden: editor role required"}, 403)

        body = request.get_json(silent=True) or {}
        new_cfg = body.get("config", {})

        # Salvaguarda: el editor que guarda siempre queda en la lista como
        # editor — nadie puede quitarse el acceso de edición por error.
        access_list = new_cfg.get("accessList", [])
        access_list = [a for a in access_list if a.get("email", "").strip().lower() != email]
        access_list.append({"email": email, "role": "editor"})
        new_cfg["accessList"] = access_list

        try:
            fs_client.collection("dashboard_configs").document(tenant_id).set(new_cfg)
            log.info(f"Config saved for tenant {tenant_id} by {email}")
            return json_response({"ok": True})
        except Exception as e:
            log.error(f"Firestore saveConfig error ({tenant_id}): {e}")
            return json_response({"error": str(e)}, 500)

    return json_response({"error": f"Unknown action: {action}"}, 400)