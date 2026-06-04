"""
main.py — Cloud Function agent-executor
Entry point genérico para todos los agentes del sistema LLYC AI-First.
Despacha por (client_id, agent_name) — cada par tiene su propio agent.

Trigger: HTTP (invocado por Cloud Scheduler de cada proyecto cliente).
Proyecto GCP: llyc-ai-first-core
Service Account: llyc-agents-sa@llyc-ai-first-core.iam.gserviceaccount.com
Memoria: 1024MB · Timeout: 300s

DEC_065 (26/05/2026): el sistema usa Anthropic Messages API + tool_use clásico,
no Managed Agents. El system prompt se construye client-side en cada invocación
desde system_prompts/{agent}.md + clients/{client_id}/config.json. El agent_id
persistido en config se mantiene por trazabilidad histórica pero no se usa en runtime.

Decisiones aplicadas:
  - DEC_026: secrets híbridos (core + proyecto cliente)
  - DEC_030: Cloud Scheduler en proyecto cliente, payload con client_id
  - DEC_033: un agent por (client_id, agent_name)
  - DEC_044: una API key de Anthropic por agente
  - DEC_056: 2 reintentos en tool execution antes de error 500
  - DEC_058 (act. 22/05): API key de Anthropic vive en proyecto cliente
  - DEC_059: filtrado de plataformas inyectadas por enabled + tools del agente
  - DEC_065 (26/05): Messages API + tool_use (no Managed Agents)
"""

# ─── IMPORTS ──────────────────────────────────────────────────────────────────
import os
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import functions_framework
from google.cloud import secretmanager
import google.cloud.logging

import anthropic

from tools.response import ok, error
from tools import meta, google_ads, ga4, drive, notifications, shopify
from tools.email import render_email_html
from tools.definitions import get_tool_definitions  # DEC_065
from prompt_builder import load_static_prompt, build_dynamic_context  # F-CloudLog (29/05)
from operational_inputs import (  # DEC_075
    load_operational_inputs, to_prompt_block, reference_used,
)

# ─── BOOTSTRAP ────────────────────────────────────────────────────────────────
# CRÍTICO: no usar logging.basicConfig en Cloud Functions Gen 2.
# No propaga correctamente. Usar google.cloud.logging siempre.
google.cloud.logging.Client().setup_logging()
log = logging.getLogger(__name__)

# DEC_065: ANTHROPIC_BETA se mantiene declarada como referencia histórica,
# pero NO se usa en runtime (messages.create no requiere beta header).
ANTHROPIC_BETA = "managed-agents-2026-04-01"

MODEL = "claude-sonnet-4-6"
CORE_PROJECT_ID = "llyc-ai-first-core"
MAX_TOOL_RETRIES = 2  # DEC_056: reintentos antes de devolver 500

# DEC_065: parámetros del loop Messages API + tool_use
MAX_TOKENS = 4096
MAX_AGENT_ITERATIONS = 20  # tope de seguridad para evitar bucles

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

    # Shopify (DEC_048 + DEC_050)
    "get_shopify_orders_period":        shopify.get_shopify_orders_period,
    "get_shopify_customer_segment":     shopify.get_shopify_customer_segment,
    "get_shopify_inventory_status":     shopify.get_shopify_inventory_status,
    "get_shopify_active_discounts":     shopify.get_shopify_active_discounts,

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

    DEC_065: el agent_id ya no se usa en runtime (Messages API no lo requiere),
    pero se sigue resolviendo aquí como check de coherencia con el bootstrap
    y para trazabilidad histórica en los logs.
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
    return response.payload.data.decode("utf-8").strip()


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

    # API key de Anthropic: nombre derivado de agent_name + client_id (DEC_058 Actualización 2026-05-22)
    # agent_name viene en kebab-case del payload HTTP → normalizamos a snake_case para el secret name
    anthropic_secret_name = f"anthropic-api-key-{agent_name.replace('-', '_')}-{client_id}"
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

    # GA4 credenciales OAuth admin-tech (DEC_067, 2026-05-27)
    #   - CLIENT_ID, CLIENT_SECRET → shared en llyc-ai-first-core (OAuth app de agencia)
    #   - REFRESH_TOKEN            → cliente en llyc-ai-{client_id} (admin-tech@llyc.global)
    # Migrado de SA → OAuth para unificar con Meta/Google Ads (la SA del JSON antiguo
    # no tenía Viewer en property GA4 del cliente; admin-tech sí lo tiene de forma estable).
    if config.get("platforms", {}).get("ga4", {}).get("enabled"):
        # Shared (en core)
        for key in ["ga4_client_id", "ga4_client_secret"]:
            secret_name = creds_map.get(key)
            if secret_name:
                secrets[secret_name] = _access_secret(
                    sm_client, CORE_PROJECT_ID, secret_name
                )
        # Client
        secret_name = creds_map.get("ga4_refresh_token")
        if secret_name:
            secrets[secret_name] = _access_secret(
                sm_client, client_project_id, secret_name
            )

    # Shopify credenciales (DEC_048 — 100% en proyecto cliente; excepción al patrón híbrido)
    #   - SHOPIFY_ADMIN_API_TOKEN → cliente en llyc-ai-{client_id}
    if config.get("platforms", {}).get("shopify", {}).get("enabled"):
        secret_name = creds_map.get("shopify_admin_token")
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

    Pre-inicialización de clients (fix 27/05/2026):
    Antes de definir el handler interno se inicializan los clients de cada
    plataforma activa (cached en cierre). Diferencia de firmas:
      - Meta:        FacebookAdsApi.init() configura una API global;
                     las funciones get_meta_* NO reciben client object.
      - Google Ads:  init_google_ads_client() -> GoogleAdsClient;
                     get_google_ads_* recibe client como primer arg posicional.
      - GA4:         init_ga4_client() -> BetaAnalyticsDataClient;
                     get_ga4_* recibe client como primer arg posicional.
    Si una plataforma falla al inicializar (credencial mal, secret faltante),
    se registra el error y todas las tools de esa plataforma devuelven un
    error estructurado claro al agente sin reintentar inútilmente.
    """
    # ─── INICIALIZACIÓN DE CLIENTS POR PLATAFORMA ────────────────────────────
    clients: dict[str, Any] = {}
    init_errors: dict[str, str] = {}
    platforms_cfg = config.get("platforms", {})
    creds_map = config.get("credentials", {})

    def _get_secret(key: str):
        """Devuelve el valor del secret asociado a la entrada `key` del creds_map."""
        secret_name = creds_map.get(key)
        if not secret_name:
            return None
        return secrets.get(secret_name)

    # ── Meta ─────────────────────────────────────────────────────────────────
    if platforms_cfg.get("meta", {}).get("enabled"):
        try:
            access_token = _get_secret("meta_access_token")
            app_id = _get_secret("meta_app_id")
            app_secret = _get_secret("meta_app_secret")
            missing = [k for k, v in {
                "meta_access_token": access_token,
                "meta_app_id": app_id,
                "meta_app_secret": app_secret,
            }.items() if not v]
            if missing:
                raise RuntimeError(f"Faltan secrets para Meta: {missing}")
            meta.init_meta_api(
                access_token=access_token,
                app_id=app_id,
                app_secret=app_secret,
            )
            clients["meta"] = True  # marker — la API es global, no hay objeto
            log.info(json.dumps({
                "event": "platform_client_initialized",
                "platform": "meta",
                "client_id": client_id,
            }))
        except Exception as e:
            init_errors["meta"] = str(e)
            log.error(json.dumps({
                "event": "platform_client_init_failed",
                "platform": "meta",
                "client_id": client_id,
                "error": str(e),
            }))

    # ── Google Ads ──────────────────────────────────────────────────────────
    if platforms_cfg.get("google_ads", {}).get("enabled"):
        try:
            developer_token = _get_secret("google_ads_developer_token")
            ga_client_id = _get_secret("google_ads_client_id")
            ga_client_secret = _get_secret("google_ads_client_secret")
            refresh_token = _get_secret("google_ads_refresh_token")
            login_customer_id = platforms_cfg["google_ads"].get("manager_id")
            missing = [k for k, v in {
                "google_ads_developer_token": developer_token,
                "google_ads_client_id": ga_client_id,
                "google_ads_client_secret": ga_client_secret,
                "google_ads_refresh_token": refresh_token,
                "platforms.google_ads.manager_id": login_customer_id,
            }.items() if not v]
            if missing:
                raise RuntimeError(f"Faltan credenciales para Google Ads: {missing}")
            clients["google_ads"] = google_ads.init_google_ads_client(
                developer_token=developer_token,
                client_id=ga_client_id,
                client_secret=ga_client_secret,
                refresh_token=refresh_token,
                login_customer_id=str(login_customer_id),
            )
            log.info(json.dumps({
                "event": "platform_client_initialized",
                "platform": "google_ads",
                "client_id": client_id,
            }))
        except Exception as e:
            init_errors["google_ads"] = str(e)
            log.error(json.dumps({
                "event": "platform_client_init_failed",
                "platform": "google_ads",
                "client_id": client_id,
                "error": str(e),
            }))

    # ── GA4 ──────────────────────────────────────────────────────────────────
    if platforms_cfg.get("ga4", {}).get("enabled"):
        try:
            cid = _get_secret("ga4_client_id")
            csec = _get_secret("ga4_client_secret")
            rtok = _get_secret("ga4_refresh_token")
            missing = [
                k for k, v in [
                    ("ga4_client_id", cid),
                    ("ga4_client_secret", csec),
                    ("ga4_refresh_token", rtok),
                ] if not v
            ]
            if missing:
                raise RuntimeError(f"Faltan credenciales OAuth de GA4: {', '.join(missing)}")
            clients["ga4"] = ga4.init_ga4_client(
                client_id=cid,
                client_secret=csec,
                refresh_token=rtok,
            )
            log.info(json.dumps({
                "event": "platform_client_initialized",
                "platform": "ga4",
                "client_id": client_id,
            }))
        except Exception as e:
            init_errors["ga4"] = str(e)
            log.error(json.dumps({
                "event": "platform_client_init_failed",
                "platform": "ga4",
                "client_id": client_id,
                "error": str(e),
            }))

    # ── Shopify ──────────────────────────────────────────────────────────────
    if platforms_cfg.get("shopify", {}).get("enabled"):
        try:
            access_token = _get_secret("shopify_admin_token")
            shop_domain = platforms_cfg["shopify"].get("shop_domain")
            api_version = platforms_cfg["shopify"].get("api_version")
            missing = [k for k, v in {
                "shopify_admin_token": access_token,
                "platforms.shopify.shop_domain": shop_domain,
                "platforms.shopify.api_version": api_version,
            }.items() if not v]
            if missing:
                raise RuntimeError(f"Faltan credenciales/config para Shopify: {missing}")
            shopify.init_shopify_api(
                shop_domain=shop_domain,
                access_token=access_token,
                api_version=api_version,
            )
            clients["shopify"] = True  # marker — API global vía state module, no client object
            log.info(json.dumps({
                "event": "platform_client_initialized",
                "platform": "shopify",
                "client_id": client_id,
            }))
        except Exception as e:
            init_errors["shopify"] = str(e)
            log.error(json.dumps({
                "event": "platform_client_init_failed",
                "platform": "shopify",
                "client_id": client_id,
                "error": str(e),
            }))

    # ─── MAPEO DE TOOL NAME → PLATAFORMA ─────────────────────────────────────
    # Cada prefijo determina qué client se inyecta. get_meta_* es especial:
    # la plataforma está inicializada (API global) pero NO se prepena client.
    PLATFORM_PREFIX_TO_KEY = (
        ("get_meta_", "meta"),
        ("get_google_ads_", "google_ads"),
        ("get_ga4_", "ga4"),
        ("get_shopify_", "shopify"),
    )

    def _resolve_platform(tool_name: str):
        for prefix, plat in PLATFORM_PREFIX_TO_KEY:
            if tool_name.startswith(prefix):
                return plat
        return None

    # ─── HANDLER INTERNO ──────────────────────────────────────────────────────
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

        # Resolver plataforma e inicialización
        platform = _resolve_platform(tool_name)

        # Si la plataforma falló al inicializar, devolver error claro sin reintentar
        if platform and platform in init_errors:
            log.warning(json.dumps({
                "event": "tool_skipped_platform_uninit",
                "client_id": client_id,
                "agent": agent_name,
                "tool_name": tool_name,
                "platform": platform,
            }))
            return error(
                platform,
                "CLIENT_INIT_FAILED",
                f"Cliente {platform} no se inicializó: {init_errors[platform]}",
            )

        # Determinar si la tool requiere client object como primer positional
        # Meta no lo requiere (API global vía init_meta_api). Google Ads y GA4 sí.
        client_obj = clients.get(platform) if platform else None
        prepend_client = platform in ("google_ads", "ga4") and client_obj is not None

        last_result = None
        for attempt in range(1, MAX_TOOL_RETRIES + 1):
            t0 = time.monotonic()
            try:
                if prepend_client:
                    result = executor(client_obj, **tool_input)
                else:
                    result = executor(**tool_input)
                duration_ms = int((time.monotonic() - t0) * 1000)

                event_payload = {
                    "event": "tool_executed",
                    "client_id": client_id,
                    "agent": agent_name,
                    "tool_name": tool_name,
                    "attempt": attempt,
                    "status": result.get("status"),
                    "duration_ms": duration_ms,
                }
                if result.get("status") == "error":
                    err = result.get("error") or {}
                    event_payload["error_code"] = err.get("code")
                    event_payload["error_message"] = err.get("message")
                log.info(json.dumps(event_payload))

                if result.get("status") == "ok":
                    return result

                last_result = result

            except Exception as e:
                duration_ms = int((time.monotonic() - t0) * 1000)
                last_result = error(
                    platform or "unknown",
                    "EXCEPTION",
                    str(e),
                )
                log.warning(json.dumps({
                    "event": "tool_error",
                    "client_id": client_id,
                    "agent": agent_name,
                    "tool_name": tool_name,
                    "attempt": attempt,
                    "error_message": str(e),
                    "exception_type": type(e).__name__,
                    "exception_module": type(e).__module__,
                    "status_code": getattr(e, "status_code", None) or getattr(e, "code", None),
                    "duration_ms": duration_ms,
                }))

            if attempt < MAX_TOOL_RETRIES:
                time.sleep(2 ** attempt)  # backoff exponencial

        last_err = (last_result or {}).get("error") or {}
        log.error(json.dumps({
            "event": "tool_exhausted",
            "client_id": client_id,
            "agent": agent_name,
            "tool_name": tool_name,
            "max_retries": MAX_TOOL_RETRIES,
            "last_error_code": last_err.get("code"),
            "last_error_message": last_err.get("message"),
        }))

        return last_result

    return handler


# ─── SYSTEM PROMPT BUILDERS (DEC_065) ─────────────────────────────────────────
# Construcción client-side del system prompt en cada invocación. Antes (Managed
# Agents) el system prompt vivía server-side en Anthropic asociado al agent_id.
# load_static_prompt y build_dynamic_context viven en prompt_builder.py
# (módulo dedicado sin side effects de CloudLoggingHandler — F-CloudLog, 29/05/2026).


# ─── INVOCACIÓN DEL AGENT ─────────────────────────────────────────────────────

def build_user_message(agent_name: str, config: dict, analysis_date: str) -> str:
    """
    Construye el mensaje inicial que se envía al modelo en cada invocación.
    DEC_065: el system prompt y las tools se inyectan en cada llamada via
    messages.create(). El user_message activa la ejecución con la fecha de análisis.

    analysis_date: YYYY-MM-DD, fecha del día a analizar (ayer respecto al
    momento de ejecución). Calculada en el entrypoint y propagada.
    """
    client_name = config["client"]["name"]

    messages = {
        "performance-monitor": (
            f"Ejecuta el análisis de rendimiento de paid media para {client_name}. "
            f"Fecha de análisis: {analysis_date}. "
            f"Esa es la fecha del día a analizar — compara sus KPIs con la media "
            f"de los 7 días naturales previos. Genera el output en el formato estructurado definido."
        ),
        "budget-pacer": (
            f"Ejecuta el análisis de presupuesto para {client_name} a fecha {analysis_date}. "
            f"Compara el gasto actual del mes con el objetivo mensual y detecta "
            f"desviaciones. Genera el output en el formato estructurado definido."
        ),
        "naming-utm-auditor": (
            f"Ejecuta la auditoría de naming y UTMs para {client_name} a fecha {analysis_date}. "
            f"Revisa todos los ads activos y detecta incumplimientos de naming convention "
            f"o parámetros UTM incompletos. Genera el output en el formato estructurado definido."
        ),
        "weekly-digest": (
            f"Genera el weekly digest para {client_name} correspondiente a la semana "
            f"que termina el {analysis_date}. Analiza el rendimiento cross-platform, detecta "
            f"patrones y propone 2-3 opciones de acción con datos. "
            f"Genera el output en el formato estructurado definido."
        ),
    }

    return messages.get(
        agent_name,
        f"Ejecuta el análisis para {client_name} a fecha {analysis_date}."
    )


def run_agent(
    anthropic_client: anthropic.Anthropic,
    system_prompt: str,
    tools: list[dict],
    user_message: str,
    tool_handler,
    client_id: str,
    agent_name: str,
) -> dict:
    """
    Invoca al modelo Claude vía Messages API + tool_use clásico.

    DEC_065 (26/05/2026): pivot desde Managed Agents a Messages API. El system
    prompt y las tools se pasan en cada invocación; no hay agent persistido
    server-side. Patrón estándar de Anthropic, perfectamente soportado por SDK
    0.103.x y 0.104.x (sin beta header).

    Loop:
      1. messages.create() con system + tools + history acumulado.
      2. Si stop_reason == 'end_turn' → extraer texto, parsear JSON, devolver.
      3. Si stop_reason == 'tool_use' → por cada bloque tool_use, ejecutar vía
         tool_handler. Appendear assistant message + tool_results al history. Loop.
      4. Si stop_reason inesperado o MAX_AGENT_ITERATIONS alcanzado → ERROR.
    """
    log.info(json.dumps({
        "event": "agent_invoked",
        "client_id": client_id,
        "agent": agent_name,
        "model": MODEL,
        "tools_count": len(tools),
    }))

    t0 = time.monotonic()
    messages = [{"role": "user", "content": user_message}]
    final_response = None
    iterations = 0
    total_input_tokens = 0
    total_output_tokens = 0

    while iterations < MAX_AGENT_ITERATIONS:
        iterations += 1
        response = anthropic_client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        log.info(json.dumps({
            "event": "agent_turn",
            "client_id": client_id,
            "agent": agent_name,
            "iteration": iterations,
            "stop_reason": response.stop_reason,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }))

        if response.stop_reason == "end_turn":
            final_response = response
            break

        if response.stop_reason == "tool_use":
            # Appendear assistant message completo (incluye los tool_use blocks)
            messages.append({"role": "assistant", "content": response.content})

            # Procesar cada tool_use y construir tool_results
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                log.info(json.dumps({
                    "event": "tool_call",
                    "client_id": client_id,
                    "agent": agent_name,
                    "tool": block.name,
                }))
                try:
                    result = tool_handler(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
                except Exception as e:
                    log.error(json.dumps({
                        "event": "tool_handler_exception",
                        "client_id": client_id,
                        "agent": agent_name,
                        "tool": block.name,
                        "error": str(e),
                    }))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({"status": "error", "message": str(e)}),
                        "is_error": True,
                    })

            messages.append({"role": "user", "content": tool_results})
            continue

        # stop_reason inesperado (max_tokens, stop_sequence...)
        log.error(json.dumps({
            "event": "unexpected_stop_reason",
            "client_id": client_id,
            "agent": agent_name,
            "stop_reason": response.stop_reason,
        }))
        final_response = response
        break

    duration_ms = int((time.monotonic() - t0) * 1000)

    if final_response is None:
        log.error(json.dumps({
            "event": "agent_max_iterations",
            "client_id": client_id,
            "agent": agent_name,
            "iterations": iterations,
        }))
        return {
            "agent": agent_name,
            "client": client_id,
            "status_global": "ERROR",
            "summary": f"Agente alcanzó MAX_AGENT_ITERATIONS={MAX_AGENT_ITERATIONS} sin cerrar turno.",
        }

    # Extraer texto del final_response
    output_text = "".join(
        block.text for block in final_response.content if hasattr(block, "text")
    )

    log.info(json.dumps({
        "event": "agent_completed",
        "client_id": client_id,
        "agent": agent_name,
        "duration_ms": duration_ms,
        "iterations": iterations,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "output_length": len(output_text),
    }))

    # Parsear el output como JSON estructurado
    try:
        return json.loads(output_text)
    except json.JSONDecodeError:
        # Fallback: extraer JSON de un bloque ```json ... ``` si Claude lo envolvió
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', output_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        log.error(json.dumps({
            "event": "json_decode_error",
            "client_id": client_id,
            "agent": agent_name,
            "raw_preview": output_text[:500],
        }))
        return {
            "agent": agent_name,
            "client": client_id,
            "status_global": "ERROR",
            "summary": "Output del agente no es JSON válido.",
            "raw_output": output_text,
        }


# ─── OUTPUT WRITING ──────────────────────────────────────────────────────────

def write_output_to_drive_for_agent(
    config: dict, agent_name: str, output: dict, client_id: str, analysis_date: str
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

    filename = f"{analysis_date}_PAID_{agent_name}-{client_id}.json"

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


def send_notification_for_agent(
    config: dict,
    agent_name: str,
    output: dict,
    drive_result: dict,
    status: str,
    analysis_date: str,
) -> dict:
    """
    Renderiza email HTML estructurado vía Jinja2 + email_templates/<agent_key>.html
    y delega el envío en notifications.send_alert_email.

    Refactor 2026-05-29 (DEC_050): plantilla externa con template inheritance
    (_base.html + macros) en lugar de HTML inline. Cross-agent: cada agente
    declara su propio template hijo bajo email_templates/.

    No propaga excepciones — siempre devuelve un dict con status. Si el envío
    falla, se loggea como ERROR; la Cloud Function NO aborta (el output sigue
    válido en Drive y Cloud Logging). Si el template falla (TemplateNotFound,
    UndefinedError por StrictUndefined), se loggea y se devuelve error con
    detalle — esto fuerza visibilidad del contrato roto.

    Construcción del subject:
      [{execution_status} · {analysis_status}] {agent_name} · {client_name} · {date}
      Si analysis_status es N/A se omite (caso ERROR sin análisis).
    """
    notifications_config = config.get("notifications", {})
    recipients = notifications_config.get("alert_recipients", [])
    client_id = config.get("client", {}).get("id")

    if not recipients:
        log.warning(json.dumps({
            "event": "notification_skipped_no_recipients",
            "client_id": client_id,
            "agent": agent_name,
        }))
        return {"status": "skipped", "reason": "no alert_recipients in config"}

    client_name = config.get("client", {}).get("name", "Cliente")
    summary = output.get("summary", "(sin resumen)")
    drive_url = (
        drive_result.get("data", {}).get("url")
        if drive_result.get("status") == "ok"
        else None
    )

    # Modelo dual de status (DEC_050): execution + analysis separados.
    # Backward compat: si el agente todavía devuelve status_global legacy,
    # lo mapeamos a execution=OK/PARTIAL/ERROR y analysis=ALERTA/NORMAL.
    execution_status = output.get("execution_status") or _derive_execution_status(status)
    analysis_status = output.get("analysis_status") or _derive_analysis_status(status)
    execution_status_detail = output.get("execution_status_detail", "")

    # Subject: prefijo dual cuando aplica
    subject_label = execution_status
    if analysis_status and analysis_status != "N/A" and execution_status == "OK":
        subject_label = analysis_status
    elif analysis_status and analysis_status != "N/A":
        subject_label = f"{execution_status} · {analysis_status}"
    subject = f"[{subject_label}] {agent_name} · {client_name} · {analysis_date}"

    # Contexto del template — debe contener TODO lo que performance_monitor.html
    # referencia. Si falta alguna key con StrictUndefined la render falla.
    context = {
        "client_name": client_name,
        "analysis_date": analysis_date,
        "execution_status": execution_status,
        "execution_status_detail": execution_status_detail,
        "analysis_status": analysis_status,
        "summary": summary,
        "revenue_triangulation": output.get("revenue_triangulation"),
        "platforms": output.get("platforms", {}),
        "alerts": output.get("alerts", []),
        "drive_url": drive_url,
    }

    template_name = f"{agent_name.replace('-', '_')}.html"

    try:
        body_html = render_email_html(template_name, context)
    except Exception as e:
        log.error(json.dumps({
            "event": "notification_template_render_failed",
            "client_id": client_id,
            "agent": agent_name,
            "template": template_name,
            "error_type": type(e).__name__,
            "error": str(e),
        }))
        return {
            "status": "error",
            "error": {"code": "TEMPLATE_RENDER", "message": f"{type(e).__name__}: {e}"},
        }

    # Fallback plain text — versión simple para clientes sin HTML
    body_text = (
        f"{subject}\n\n"
        f"{summary}\n\n"
        + (f"Ver output completo: {drive_url}\n" if drive_url else "")
    )

    try:
        return notifications.send_alert_email(
            recipients=recipients,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            drive_url=drive_url,
        )
    except Exception as e:
        log.error(json.dumps({
            "event": "notification_caught_exception",
            "client_id": client_id,
            "agent": agent_name,
            "error": str(e),
        }))
        return {
            "status": "error",
            "error": {"code": "UNEXPECTED", "message": str(e)},
        }


def _derive_execution_status(legacy_status: str) -> str:
    """Mapea status_global legacy → execution_status del modelo dual."""
    if legacy_status == "ERROR":
        return "ERROR"
    if legacy_status == "PARTIAL":
        return "PARTIAL"
    return "OK"


def _derive_analysis_status(legacy_status: str) -> str:
    """Mapea status_global legacy → analysis_status del modelo dual."""
    if legacy_status in ("ALERTA", "NORMAL"):
        return legacy_status
    return "N/A"


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

    # Fecha del día a analizar: ayer respecto al momento de ejecución.
    # Calculada una vez aquí y propagada a build_user_message, Drive (filename)
    # y email (subject) para que las tres referencias muestren exactamente la
    # misma fecha (la del dato analizado, no la de generación).
    # TODO: usar timezone del cliente cuando config.client.timezone esté disponible.
    analysis_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    log.info(json.dumps({
        "event": "execution_started",
        "client_id": client_id,
        "agent": agent_name,
        "analysis_date": analysis_date,
    }))

    try:
        # ── 1. Cargar config del cliente ──────────────────────────────────────
        config = load_client_config(client_id)

        # ── 2. Resolver agent_id (DEC_065: solo validación + traza, no se usa en runtime) ─
        agent_id = resolve_agent_id(config, agent_name)
        log.info(json.dumps({
            "event": "agent_id_resolved",
            "client_id": client_id,
            "agent": agent_name,
            "agent_id": agent_id,
            "note": "DEC_065: agent_id resuelto para traza, no usado en runtime",
        }))

        # ── 3. Cargar secrets ─────────────────────────────────────────────────
        secrets = load_secrets(client_id, agent_name, config)

        # ── 4. Inicializar cliente Anthropic (DEC_065: sin beta header) ───────
        # messages.create() no requiere managed-agents-2026-04-01.
        anthropic_client = anthropic.Anthropic(
            api_key=secrets["ANTHROPIC_API_KEY"],
        )

        # ── 5. Construir tool handler con secrets + config inyectados ─────────
        handler = tool_handler_factory(secrets, config, client_id, agent_name)

        # ── 6. Cargar system_prompt + tools client-side (DEC_065) ─────────────
        # Antes vivía server-side asociado al agent_id. Ahora se construye en
        # cada invocación: static prompt del repo + contexto dinámico del config.
        static_prompt = load_static_prompt(agent_name)
        dynamic_context = build_dynamic_context(config, agent_name)

        # DEC_075: capa de parámetros operativos. Lee el workbook operativo del
        # cliente (budget dinámico + tolerancias KPI) por Sheets API y lo inyecta
        # en el prompt. load_operational_inputs NUNCA lanza: degrada a fallback de
        # config y señala la fuente, de modo que un workbook caído no tumba la
        # ejecución (a lo sumo el agente reporta el fallback en su output).
        enabled_platforms = [
            k for k, v in config.get("platforms", {}).items()
            if isinstance(v, dict) and v.get("enabled")
        ]
        oi = load_operational_inputs(config, agent_name, platforms=enabled_platforms)
        log.info(json.dumps({
            "event": "operational_inputs_loaded",
            "client_id": client_id,
            "agent": agent_name,
            **reference_used(oi),
        }))

        system_prompt = f"{static_prompt}\n\n{dynamic_context}\n\n{to_prompt_block(oi)}"
        tools = get_tool_definitions(agent_name.replace("-", "_"))

        # ── 7. Construir user_message e invocar el agent ──────────────────────
        user_message = build_user_message(agent_name, config, analysis_date)
        output = run_agent(
            anthropic_client,
            system_prompt,
            tools,
            user_message,
            handler,
            client_id,
            agent_name,
        )

        # ── 8. Log del output final (DEC_050 — modelo dual) ──────────────────
        execution_status = output.get("execution_status") or output.get("status_global") or "UNKNOWN"
        analysis_status = output.get("analysis_status") or "N/A"
        log.info(json.dumps({
            "event": "execution_completed",
            "client_id": client_id,
            "agent": agent_name,
            "execution_status": execution_status,
            "analysis_status": analysis_status,
        }))

        # Determinar notify_level a comparar con alert_levels.
        # Regla: si execution falló (PARTIAL/ERROR), notificar ese estado técnico.
        # Si execution OK, notificar según analysis (ALERTA/NORMAL).
        if execution_status in ("ERROR", "PARTIAL"):
            notify_level = execution_status
        else:
            notify_level = analysis_status if analysis_status not in ("N/A", None) else execution_status

        # ── 9. Escribir output a Drive (arq §9 step 8) ────────────────────────
        drive_result = write_output_to_drive_for_agent(
            config, agent_name, output, client_id, analysis_date
        )

        # ── 10. Notificar si notify_level dispara alerta (arq §9 step 9) ──────
        notifications_config = config.get("notifications", {})
        if notify_level in notifications_config.get("alert_levels", []):
            notification_result = send_notification_for_agent(
                config, agent_name, output, drive_result, notify_level, analysis_date
            )
        else:
            notification_result = {
                "status": "skipped",
                "reason": f"notify_level not in alert_levels (was: {notify_level})",
            }

        return {
            "status": "ok",
            "client_id": client_id,
            "agent_name": agent_name,
            "execution_status": execution_status,
            "analysis_status": analysis_status,
            "notify_level": notify_level,
            "summary": output.get("summary", ""),
            "output": output,
            "drive": drive_result,
            "notifications": notification_result,
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
