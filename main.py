"""
main.py — Cloud Function agent-executor
Entry point genérico para todos los agentes del sistema LLYC AI-First.
Despacha por (client_id, agent_name) — cada par tiene su propio agent Managed.

Trigger: HTTP (invocado por Cloud Scheduler de cada proyecto cliente).
Proyecto GCP: llyc-ai-first-core
Service Account: llyc-agents-sa@llyc-ai-first-core.iam.gserviceaccount.com
Memoria: 1024MB · Timeout: 300s

El agent_id vive en clients/{client_id}/config.json bajo agents[agent_name].
main.py NO crea agents — eso lo hace scripts/bootstrap_agent.py.

Decisiones aplicadas:
  - DEC_026: secrets híbridos (core + proyecto cliente)
  - DEC_030: Cloud Scheduler en proyecto cliente, payload con client_id
  - DEC_033: un agent Managed por (client_id, agent_name)
  - DEC_044: una API key de Anthropic por agente
  - DEC_056: 2 reintentos en tool execution antes de error 500
"""

# ─── IMPORTS ──────────────────────────────────────────────────────────────────
import os
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import functions_framework
from google.cloud import secretmanager
import google.cloud.logging

import anthropic

from tools.response import ok, error
from tools import meta, google_ads, ga4, drive

# ─── BOOTSTRAP ────────────────────────────────────────────────────────────────
# CRÍTICO: no usar logging.basicConfig en Cloud Functions Gen 2.
# No propaga correctamente. Usar google.cloud.logging siempre.
google.cloud.logging.Client().setup_logging()
log = logging.getLogger(__name__)

ANTHROPIC_BETA = "managed-agents-2026-04-01"
MODEL = "claude-sonnet-4-6"
CORE_PROJECT_ID = "llyc-ai-first-core"
MAX_TOOL_RETRIES = 2  # DEC_056: reintentos antes de devolver 500

# ─── AGENTES Y TOOLS SOPORTADOS ───────────────────────────────────────────────
SUPPORTED_AGENTS = {
    "performance-monitor",
    "budget-pacer",
    "naming-utm-auditor",
    "weekly-digest",
    # "creative-fatigue-detector" → Sprint 2
}


# Mapa de despacho: nombre de tool que pide el agente → función ejecutora.
# DV360 NO está aquí — vive en su propio MCP server en Cloud Run (DEC_037).
TOOL_DISPATCHER = {
    # Meta
    "get_meta_performance":             meta.get_meta_performance,
    "get_meta_spend_today":             meta.get_meta_spend_today,
    "get_meta_spend_month":             meta.get_meta_spend_month,
    "get_meta_active_ad_urls":          meta.get_meta_active_ad_urls,
    "get_meta_active_campaigns":        meta.get_meta_active_campaigns,

    # Google Ads
    "get_google_ads_performance":       google_ads.get_google_ads_performance,
    "get_google_ads_spend_today":       google_ads.get_google_ads_spend_today,
    "get_google_ads_spend_month":       google_ads.get_google_ads_spend_month,
    "get_google_ads_active_ad_urls":    google_ads.get_google_ads_active_ad_urls,
    "get_google_ads_active_campaigns":  google_ads.get_google_ads_active_campaigns,

    # GA4
    "get_ga4_performance":              ga4.get_ga4_performance,
    "get_ga4_paid_channel_performance": ga4.get_ga4_paid_channel_performance,
    "get_ga4_funnel":                   ga4.get_ga4_funnel,
    "get_ga4_weekly_comparison":        ga4.get_ga4_weekly_comparison,

    # tiktok → Sprint 1.5 (Jesús pendiente de validar access token)
}

# ─── CARGA DE CONFIGURACIÓN ───────────────────────────────────────────────────
INVALID_VALUES = {"PENDIENTE", "", None, 0, "null", "undefined"}

def load_client_config(client_id: str) -> dict:
    """
    Lee clients/{client_id}/config.json desde el bundle de la Cloud Function.
    Falla ruidosamente si el fichero no existe o si hay campos con PENDIENTE.
    """
    config_path = Path(__file__).parent / "clients" / client_id / "config.json"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Config no encontrado para cliente '{client_id}': {config_path}"
        )

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    log.info(json.dumps({
        "event": "config_loaded",
        "client_id": client_id,
    }))

    return config


def resolve_agent_id(config: dict, agent_name: str) -> str:
    """
    Devuelve config.agents[agent_name].agent_id.
    Falla con error explícito si el agente no está bootstrapped o está disabled.
    main.py nunca crea agents — eso lo hace scripts/bootstrap_agent.py.
    """
    client_id = config["client"]["id"]
    agents = config.get("agents", {})

    # El config actual usa snake_case (performance_monitor) — normalizamos
    agent_key = agent_name.replace("-", "_")

    if agent_key not in agents:
        raise RuntimeError(
            f"Agent '{agent_name}' no bootstrapped para cliente '{client_id}'. "
            f"Ejecutar: python scripts/bootstrap_agent.py "
            f"--client {client_id} --agent {agent_name}"
        )

    agent_config = agents[agent_key]

    if not agent_config.get("enabled", False):
        raise RuntimeError(
            f"Agent '{agent_name}' deshabilitado en config de '{client_id}'."
        )

    agent_id = agent_config.get("agent_id")
    if not agent_id or agent_id in INVALID_VALUES:
        raise RuntimeError(
            f"agent_id vacío o PENDIENTE para '{agent_name}' en '{client_id}'. "
            f"Ejecutar bootstrap primero."
        )

    return agent_id


# ─── CARGA DE SECRETS ─────────────────────────────────────────────────────────

def _access_secret(sm_client, project_id: str, secret_name: str) -> str:
    """Lee la última versión de un secret de Secret Manager."""
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = sm_client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def load_secrets(client_id: str, agent_name: str, config: dict) -> dict[str, str]:
    """
    Lee secrets desde GCP Secret Manager.
    DEC_026 (híbrido): secrets compartidos de agencia en llyc-ai-first-core,
    secrets específicos del cliente en llyc-ai-{client_id}.

    El config.credentials contiene solo nombres de secrets — nunca valores.
    La SA llyc-agents-sa tiene secretAccessor en ambos proyectos.
    NUNCA loggear los valores devueltos.
    """
    sm_client = secretmanager.SecretManagerServiceClient()
    client_project_id = f"llyc-ai-{client_id}"
    secrets = {}

    creds_map = config.get("credentials", {})

    # API key de Anthropic: nombre derivado del agent_name (DEC_044)
    anthropic_secret_name = f"anthropic-api-key-{agent_name}"
    secrets["ANTHROPIC_API_KEY"] = _access_secret(
        sm_client, client_project_id, anthropic_secret_name
    )

    # Meta credenciales (DEC_026 híbrido)
    #   - APP_ID, APP_SECRET → shared en llyc-ai-first-core (credenciales de la app de agencia)
    #   - ACCESS_TOKEN       → cliente en llyc-ai-{client_id} (token del Business Manager)
    if config.get("platforms", {}).get("meta", {}).get("enabled"):
        # Shared (en core)
        for key in ["meta_app_id", "meta_app_secret"]:
            secret_name = creds_map.get(key)
            if secret_name:
                secrets[secret_name] = _access_secret(
                    sm_client, CORE_PROJECT_ID, secret_name
                )
        # Client
        secret_name = creds_map.get("meta_access_token")
        if secret_name:
            secrets[secret_name] = _access_secret(
                sm_client, client_project_id, secret_name
            )

    # Google Ads credenciales (DEC_026 híbrido)
    #   - DEVELOPER_TOKEN, CLIENT_ID, CLIENT_SECRET → shared en llyc-ai-first-core (OAuth app de agencia)
    #   - REFRESH_TOKEN                             → cliente en llyc-ai-{client_id}
    if config.get("platforms", {}).get("google_ads", {}).get("enabled"):
        # Shared (en core)
        for key in [
            "google_ads_developer_token",
            "google_ads_client_id",
            "google_ads_client_secret",
        ]:
            secret_name = creds_map.get(key)
            if secret_name:
                secrets[secret_name] = _access_secret(
                    sm_client, CORE_PROJECT_ID, secret_name
                )
        # Client
        secret_name = creds_map.get("google_ads_refresh_token")
        if secret_name:
            secrets[secret_name] = _access_secret(
                sm_client, client_project_id, secret_name
            )

    # GA4 service account (scope: client)
    if config.get("platforms", {}).get("ga4", {}).get("enabled"):
        secret_name = creds_map.get("google_service_account_key")
        if secret_name:
            secrets[secret_name] = _access_secret(
                sm_client, client_project_id, secret_name
            )

    log.info(json.dumps({
        "event": "secrets_loaded",
        "client_id": client_id,
        "agent": agent_name,
        "secret_count": len(secrets),
    }))

    return secrets


# ─── TOOL HANDLER ─────────────────────────────────────────────────────────────

def tool_handler_factory(secrets: dict, config: dict, client_id: str, agent_name: str):
    """
    Devuelve un handler que recibe (tool_name, tool_input) del callback
    del agente y lo despacha a la función real en TOOL_DISPATCHER.

    Política de errores (DEC_056):
    - Hasta MAX_TOOL_RETRIES reintentos por tool call.
    - Si persiste el error, devuelve tool_result con error estructurado
      para que el agente pueda razonar sobre el fallo.
    - NUNCA propaga excepción raw — el agente debe recibir siempre un resultado.
    """
    def handler(tool_name: str, tool_input: dict) -> Any:
        executor = TOOL_DISPATCHER.get(tool_name)

        if not executor:
            log.error(json.dumps({
                "event": "tool_not_found",
                "client_id": client_id,
                "agent": agent_name,
                "tool_name": tool_name,
            }))
            return error("unknown", "TOOL_NOT_FOUND", f"Tool '{tool_name}' no registrada en TOOL_DISPATCHER.")

        last_result = None
        for attempt in range(1, MAX_TOOL_RETRIES + 1):
            t0 = time.monotonic()
            try:
                result = executor(**tool_input)
                duration_ms = int((time.monotonic() - t0) * 1000)

                log.info(json.dumps({
                    "event": "tool_executed",
                    "client_id": client_id,
                    "agent": agent_name,
                    "tool_name": tool_name,
                    "attempt": attempt,
                    "status": result.get("status"),
                    "duration_ms": duration_ms,
                }))

                if result.get("status") == "ok":
                    return result

                last_result = result

            except Exception as e:
                duration_ms = int((time.monotonic() - t0) * 1000)
                last_result = error(
                    tool_name.split("_")[1] if "_" in tool_name else "unknown",
                    "EXCEPTION",
                    str(e),
                )
                log.warning(json.dumps({
                    "event": "tool_error",
                    "client_id": client_id,
                    "agent": agent_name,
                    "tool_name": tool_name,
                    "attempt": attempt,
                    "error": str(e),
                    "duration_ms": duration_ms,
                }))

            if attempt < MAX_TOOL_RETRIES:
                time.sleep(2 ** attempt)  # backoff exponencial

        log.error(json.dumps({
            "event": "tool_exhausted",
            "client_id": client_id,
            "agent": agent_name,
            "tool_name": tool_name,
            "max_retries": MAX_TOOL_RETRIES,
        }))

        return last_result

    return handler


# ─── INVOCACIÓN DEL AGENT ─────────────────────────────────────────────────────

def build_user_message(agent_name: str, config: dict) -> str:
    """
    Construye el mensaje inicial que se envía al agent en cada invocación.
    El system prompt ya está registrado en Anthropic para ese agent_id.
    El mensaje activa la ejecución con la fecha actual.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    client_name = config["client"]["name"]

    messages = {
        "performance-monitor": (
            f"Ejecuta el análisis de rendimiento de paid media para {client_name} "
            f"correspondiente al día {today}. "
            f"Compara el día anterior con la media de los últimos 7 días en todas "
            f"las plataformas activas. Genera el output en el formato estructurado definido."
        ),
        "budget-pacer": (
            f"Ejecuta el análisis de presupuesto para {client_name} a fecha {today}. "
            f"Compara el gasto actual del mes con el objetivo mensual y detecta "
            f"desviaciones. Genera el output en el formato estructurado definido."
        ),
        "naming-utm-auditor": (
            f"Ejecuta la auditoría de naming y UTMs para {client_name} a fecha {today}. "
            f"Revisa todos los ads activos y detecta incumplimientos de naming convention "
            f"o parámetros UTM incompletos. Genera el output en el formato estructurado definido."
        ),
        "weekly-digest": (
            f"Genera el weekly digest para {client_name} correspondiente a la semana "
            f"que termina el {today}. Analiza el rendimiento cross-platform, detecta "
            f"patrones y propone 2-3 opciones de acción con datos. "
            f"Genera el output en el formato estructurado definido."
        ),
    }

    return messages.get(
        agent_name,
        f"Ejecuta el análisis para {client_name} a fecha {today}."
    )


def run_agent(
    anthropic_client: anthropic.Anthropic,
    agent_id: str,
    user_message: str,
    tool_handler,
    client_id: str,
    agent_name: str,
) -> dict:
    """
    Invoca el agent identificado por agent_id vía Managed Agents beta.
    El system prompt y las tools ya están registrados en Anthropic para ese agent_id.

    El SDK gestiona el loop. Nosotros:
      1. Lanzamos la invocación con el user_message.
      2. Por cada tool_use callback, ejecutamos vía tool_handler.
      3. Devolvemos el output final cuando el agente cierra turno.
    """
    log.info(json.dumps({
        "event": "agent_invoked",
        "client_id": client_id,
        "agent": agent_name,
        "agent_id": agent_id,
    }))

    t0 = time.monotonic()

    # Invocación vía Managed Agents — el SDK gestiona el loop interno
    # Referencia: managed-agents-2026-04-01 quickstart
    with anthropic_client.beta.agents.sessions.stream(
        agent_id=agent_id,
        input=user_message,
        betas=[ANTHROPIC_BETA],
    ) as stream:
        for event in stream:
            # Callback de tool execution
            if hasattr(event, "type") and event.type == "tool_use":
                tool_result = tool_handler(event.name, event.input)
                stream.submit_tool_result(
                    tool_use_id=event.id,
                    content=json.dumps(tool_result),
                )

        final_output = stream.get_final_message()

    duration_ms = int((time.monotonic() - t0) * 1000)

    # Extraer el texto del output final
    output_text = ""
    for block in final_output.content:
        if hasattr(block, "text"):
            output_text += block.text

    log.info(json.dumps({
        "event": "agent_completed",
        "client_id": client_id,
        "agent": agent_name,
        "duration_ms": duration_ms,
        "output_length": len(output_text),
    }))

    # Intentar parsear el output como JSON estructurado
    try:
        return json.loads(output_text)
    except json.JSONDecodeError:
        return {
            "agent": agent_name,
            "client": client_id,
            "status_global": "ERROR",
            "summary": "Output del agente no es JSON válido.",
            "raw_output": output_text,
        }
# ─── OUTPUT WRITING ──────────────────────────────────────────────────────────

def write_output_to_drive_for_agent(
    config: dict, agent_name: str, output: dict, client_id: str
) -> dict:
    """
    Wrapper que construye filename siguiendo la convención del proyecto
    (YYYY-MM-DD_PAID_{agent_name}-{client_id}.json) y escribe el output
    a Drive en config.drive.outputs_folder_id.

    No propaga excepciones — siempre devuelve un dict con status.
    Si Drive falla, se loggea como ERROR y se devuelve el error en el dict
    para que el caller decida. La Cloud Function NO aborta — el output
    sigue siendo válido en Cloud Logging aunque Drive falle.

    El área 'PAID' es válida para los 4 agentes Sprint 1 (todos paid media).
    Si en futuro hay agentes DATA o CREATIVIDAD, parametrizar por agente.
    """
    drive_config = config.get("drive", {})
    folder_id = drive_config.get("outputs_folder_id")

    if not folder_id:
        log.error(json.dumps({
            "event": "drive_write_skipped_no_folder_id",
            "client_id": client_id,
            "agent": agent_name,
        }))
        return {"status": "skipped", "reason": "no outputs_folder_id in config"}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"{today}_PAID_{agent_name}-{client_id}.json"

    try:
        return drive.write_output_to_drive(
            folder_id=folder_id,
            filename=filename,
            payload=output,
        )
    except Exception as e:
        log.error(json.dumps({
            "event": "drive_write_caught_exception",
            "client_id": client_id,
            "agent": agent_name,
            "filename": filename,
            "error": str(e),
        }))
        return {
            "status": "error",
            "error": {"code": "UNEXPECTED", "message": str(e)},
        }


# ─── ENTRY POINT HTTP ─────────────────────────────────────────────────────────

@functions_framework.http
def agent_executor(request):
    """
    Entry point HTTP de la Cloud Function. Dispatcher genérico.

    Payload esperado (POST JSON desde Cloud Scheduler):
        {
            "client_id": "vidal-vidal",
            "agent_name": "performance-monitor"
        }

    Respuestas:
        200 — ejecución completada (con o sin alerta)
        400 — payload inválido, cliente o agente no soportado, agent no bootstrapped
        500 — error no controlado
    """
    # ── Validar payload ───────────────────────────────────────────────────────
    try:
        payload = request.get_json(force=True)
    except Exception:
        return {"error": "Payload no es JSON válido."}, 400

    client_id = payload.get("client_id", "").strip()
    agent_name = payload.get("agent_name", "").strip()

    if not client_id or not agent_name:
        return {"error": "client_id y agent_name son obligatorios."}, 400

    if agent_name not in SUPPORTED_AGENTS:
        return {
            "error": f"agent_name '{agent_name}' no soportado.",
            "supported": list(SUPPORTED_AGENTS),
        }, 400

    log.info(json.dumps({
        "event": "execution_started",
        "client_id": client_id,
        "agent": agent_name,
    }))

    try:
        # ── 1. Cargar config del cliente ──────────────────────────────────────
        config = load_client_config(client_id)

        # ── 2. Resolver agent_id ──────────────────────────────────────────────
        agent_id = resolve_agent_id(config, agent_name)

        # ── 3. Cargar secrets ─────────────────────────────────────────────────
        secrets = load_secrets(client_id, agent_name, config)

        # ── 4. Inicializar cliente Anthropic con header beta ──────────────────
        anthropic_client = anthropic.Anthropic(
            api_key=secrets["ANTHROPIC_API_KEY"],
            default_headers={"anthropic-beta": ANTHROPIC_BETA},
        )

        # ── 5. Construir tool handler con secrets + config inyectados ─────────
        handler = tool_handler_factory(secrets, config, client_id, agent_name)

        # ── 6. Construir mensaje inicial y invocar el agent ───────────────────
        user_message = build_user_message(agent_name, config)
        output = run_agent(
            anthropic_client, agent_id, user_message, handler, client_id, agent_name
        )

        # ── 7. Log del output final ───────────────────────────────────────────
        status = output.get("status_global", "UNKNOWN")
        log.info(json.dumps({
            "event": "execution_completed",
            "client_id": client_id,
            "agent": agent_name,
            "status": status,
        }))

        # ── 8. Escribir output a Drive (arq §9 step 8) ────────────────────────
        drive_result = write_output_to_drive_for_agent(
            config, agent_name, output, client_id
        )
        return {
            "status": "ok",
            "client_id": client_id,
            "agent_name": agent_name,
            "agent_status": status,
            "summary": output.get("summary", ""),
            "drive": drive_result,
        }, 200

    except (FileNotFoundError, RuntimeError) as e:
        log.error(json.dumps({
            "event": "execution_error_400",
            "client_id": client_id,
            "agent": agent_name,
            "error": str(e),
        }))
        return {"error": str(e)}, 400

    except Exception as e:
        log.error(json.dumps({
            "event": "execution_error_500",
            "client_id": client_id,
            "agent": agent_name,
            "error": str(e),
        }), exc_info=True)
        return {"error": "Error interno. Ver Cloud Logging para detalles."}, 500