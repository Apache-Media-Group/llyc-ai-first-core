"""
tools/response.py — Contratos OK/ERROR + decorator with_timeout para tools.

Cualquier tool del sistema debe:
  1. Devolver ok(platform, data) en caso de éxito
  2. Devolver error(platform, code, message) en caso de fallo
  3. Estar decorada con @with_timeout(platform) para acotar latencia

DEC_065 fix (27/05/2026): with_timeout reimplementado con
concurrent.futures.ThreadPoolExecutor en lugar de signal.alarm para
compatibilidad con Cloud Functions Gen 2 — los workers de gunicorn no son
el thread principal del intérprete y signal.alarm solo funciona ahí.
"""

import concurrent.futures
import functools
import re
from datetime import datetime, timezone


# ─────────────────────────────────────────────
# SANITIZACIÓN DE MENSAJES DE EXCEPCIÓN
# ─────────────────────────────────────────────

# Las excepciones de red (requests/urllib3: SSLError, ConnectionError, ...)
# incluyen la URL completa de la request en str(e), query string incluido.
# En Graph API eso significa access_token y appsecret_proof en claro.
# urllib3 además omite el esquema ("Max retries exceeded with url: /v23.0/...?access_token=..."),
# así que no basta con detectar URLs https:// — se redacta cualquier query
# string y cualquier par clave=valor sensible, esté donde esté.

_SENSITIVE_PARAMS = (
    "access_token",
    "appsecret_proof",
    "app_secret",
    "client_secret",
    "refresh_token",
    "api_key",
    "apikey",
    "key",
    "token",
    "signature",
    "sig",
    "password",
)

_SENSITIVE_KV_RE = re.compile(
    r"(?i)\b(" + "|".join(_SENSITIVE_PARAMS) + r")=[^&\s'\"<>]+"
)

# Query string completo tras '?'. Se exige al menos un '=' para no tocar
# signos de interrogación en prosa.
_QUERY_STRING_RE = re.compile(r"\?[^\s'\"<>]*=[^\s'\"<>]*")


def sanitize_error_message(message: str) -> str:
    """
    Redacta credenciales embebidas en mensajes de excepción antes de que
    lleguen al output del agente o a Cloud Logging (regla "NUNCA loggear
    los valores" de load_secrets, main.py).
    """
    if not message:
        return message
    message = str(message)
    message = _QUERY_STRING_RE.sub("?[REDACTED]", message)
    message = _SENSITIVE_KV_RE.sub(r"\1=[REDACTED]", message)
    return message


# ─────────────────────────────────────────────
# CONTRATO OK / ERROR
# ─────────────────────────────────────────────


def ok(platform: str, data: dict) -> dict:
    return {
        "status": "ok",
        "platform": platform,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


def error(platform: str, code: str, message: str) -> dict:
    return {
        "status": "error",
        "platform": platform,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": {
            "code": code,
            "message": sanitize_error_message(message),
        },
    }


# ─────────────────────────────────────────────
# TIMEOUT DECORATOR
# ─────────────────────────────────────────────

TIMEOUTS = {
    "meta": 60,
    "google_ads": 60,
    "ga4": 60,
    "dv360": 60,
    "tiktok": 60,
    "drive": 30,
    "gmail": 45,
    "shopify": 120,
}


def with_timeout(platform: str):
    """
    Decorator que aplica timeout por plataforma usando ThreadPoolExecutor.

    Funciona en cualquier thread (a diferencia de signal.alarm que solo
    funciona en el thread principal del intérprete Python). Necesario para
    Cloud Functions Gen 2, que ejecuta requests en worker threads de gunicorn.

    Si la llamada supera el límite devuelve error() estructurado en lugar
    de colgar o lanzar excepción. La firma pública del decorator no cambia
    respecto a la versión con signal.alarm — todos los callers funcionan
    sin modificación.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            timeout_seconds = TIMEOUTS.get(platform, 30)
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(func, *args, **kwargs)
                    return future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                return error(platform, "TIMEOUT", f"Timeout tras {timeout_seconds}s")

        return wrapper

    return decorator
