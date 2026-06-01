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
from datetime import datetime, timezone


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
            "message": message,
        },
    }


# ─────────────────────────────────────────────
# TIMEOUT DECORATOR
# ─────────────────────────────────────────────

TIMEOUTS = {
    "meta": 30,
    "google_ads": 30,
    "ga4": 30,
    "dv360": 45,
    "tiktok": 30,
    "drive": 20,
    "gmail": 30,
    "shopify": 30,
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
