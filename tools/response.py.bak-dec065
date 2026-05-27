"""
tools/response.py — Contrato de respuesta estándar
Proyecto: llyc-ai-first-core
Decisión 022: todos los tools devuelven ok() o error(), nunca excepciones raw.
"""

import functools
import signal
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
}


def with_timeout(platform: str):
    """
    Decorator que aplica timeout por plataforma.
    Si la llamada supera el límite devuelve error() en lugar de colgar.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            timeout_seconds = TIMEOUTS.get(platform, 30)

            def _handler(signum, frame):
                raise TimeoutError(f"Timeout tras {timeout_seconds}s")

            signal.signal(signal.SIGALRM, _handler)
            signal.alarm(timeout_seconds)
            try:
                result = func(*args, **kwargs)
            except TimeoutError as e:
                result = error(platform, "TIMEOUT", str(e))
            finally:
                signal.alarm(0)
            return result
        return wrapper
    return decorator