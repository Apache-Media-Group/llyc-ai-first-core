"""
scripts/dv360/_common/audit.py
Logging estructurado de cada ejecucion de script DV360.

Cada accion queda registrada en Cloud Logging con:
  who   — usuario que ejecuta (variable de entorno LLYC_OPERATOR o whoami)
  when  — timestamp ISO 8601
  what  — nombre del script + accion
  args  — parametros de la llamada
  result — success/error + payload resumido
"""

from __future__ import annotations
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("dv360.scripts")


def _get_operator() -> str:
    """Identifica quien ejecuta el script."""
    operator = os.environ.get("LLYC_OPERATOR")
    if operator:
        return operator
    try:
        return subprocess.check_output(["whoami"], text=True).strip()
    except Exception:
        return "unknown"


def log_action(
    script: str,
    action: str,
    client_id: str,
    args: dict,
    result: dict,
    dry_run: bool = False,
) -> None:
    """
    Registra una ejecucion de script en Cloud Logging.

    Args:
        script: nombre del fichero de script (ej. 'pause_line_item')
        action: accion ejecutada (ej. 'pause_line_item')
        client_id: ID del cliente
        args: parametros de la llamada (sin credenciales)
        result: resultado de la operacion (ok/error + payload)
        dry_run: True si fue una ejecucion simulada
    """
    entry = {
        "event": "dv360_script_executed",
        "who": _get_operator(),
        "when": datetime.now(timezone.utc).isoformat(),
        "what": {
            "script": script,
            "action": action,
            "client_id": client_id,
            "dry_run": dry_run,
        },
        "args": args,
        "result": {
            "status": result.get("status", "unknown"),
            "data": result.get("data", {}),
            "error": result.get("error"),
        },
    }
    log.info(json.dumps(entry, ensure_ascii=False))


def confirm_action(message: str, dry_run: bool = False) -> bool:
    """
    Solicita confirmacion interactiva antes de ejecutar una accion.

    En dry-run siempre devuelve True (simulacion, no hay accion real).
    En produccion requiere escribir 'si' para confirmar.

    Args:
        message: descripcion de la accion a confirmar
        dry_run: si True, muestra el mensaje pero no pide confirmacion

    Returns:
        True si el usuario confirma, False si cancela
    """
    if dry_run:
        print(f"\n[DRY-RUN] Se ejecutaria: {message}")
        return True

    print(f"\n⚠️  ACCION IRREVERSIBLE: {message}")
    print("Escribe 'si' para confirmar, cualquier otra cosa para cancelar: ", end="")
    response = input().strip().lower()

    if response == "si":
        return True

    print("Cancelado.")
    return False


def confirm_destructive(message: str, dry_run: bool = False) -> bool:
    """
    Doble confirmacion para acciones destructivas (delete, archive masivo).

    Args:
        message: descripcion de la accion destructiva
        dry_run: si True, muestra el mensaje pero no pide confirmacion
    """
    if dry_run:
        print(f"\n[DRY-RUN] Accion destructiva que se ejecutaria: {message}")
        return True

    print(f"\n🔴 ACCION DESTRUCTIVA: {message}")
    print("Esta accion no se puede deshacer facilmente.")
    print("Primera confirmacion — escribe 'confirmo': ", end="")
    r1 = input().strip().lower()
    if r1 != "confirmo":
        print("Cancelado.")
        return False

    print("Segunda confirmacion — escribe el client_id para confirmar: ", end="")
    r2 = input().strip().lower()
    # La segunda confirmacion la valida el script llamante
    return r2
