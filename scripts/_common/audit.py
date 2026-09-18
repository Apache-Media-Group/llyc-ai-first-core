"""
scripts/_common/audit.py
Logging estructurado y confirmacion humana para scripts de escritura,
compartido entre plataformas (DEC_143).

Cada accion queda registrada en Cloud Logging con:
  who    - usuario que ejecuta (variable de entorno LLYC_OPERATOR o whoami)
  when   - timestamp ISO 8601
  what   - plataforma + script + accion
  args   - parametros de la llamada
  result - success/error + payload resumido

SEGURIDAD: "args" y "result" se serializan a Cloud Logging. El llamador es
responsable de NUNCA pasar valores de secrets, tokens o credenciales en
esos parametros - esta funcion no los filtra ni los redacta.
"""

from __future__ import annotations
import json
import logging
import os
import subprocess
from datetime import datetime, timezone

log = logging.getLogger("scripts.audit")


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
    platform: str,
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
        platform: plataforma (ej. "dv360", "cm360", "meta").
        script: nombre del fichero de script (ej. "pause_line_item").
        action: accion ejecutada (ej. "pause_line_item").
        client_id: ID del cliente.
        args: parametros de la llamada - NUNCA incluir credenciales,
            tokens o valores de secrets, se serializan tal cual a
            Cloud Logging.
        result: resultado de la operacion (ok/error + payload).
        dry_run: True si fue una ejecucion simulada.
    """
    entry = {
        "event": f"{platform}_script_executed",
        "who": _get_operator(),
        "when": datetime.now(timezone.utc).isoformat(),
        "what": {
            "platform": platform,
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


def confirm_action(message: str, dry_run: bool = False, skip_confirm: bool = False) -> bool:
    """
    Solicita confirmacion interactiva antes de ejecutar una accion.

    En dry-run siempre devuelve True (simulacion, no hay accion real).
    En produccion requiere escribir "si" para confirmar.
    """
    if dry_run:
        print(f"\n[DRY-RUN] Se ejecutaria: {message}")
        return True
    if skip_confirm:
        return True

    print(f"\nACCION IRREVERSIBLE: {message}")
    print("Escribe \'si\' para confirmar, cualquier otra cosa para cancelar: ", end="")
    response = input().strip().lower()

    if response == "si":
        return True

    print("Cancelado.")
    return False


def confirm_destructive(message: str, client_id: str, dry_run: bool = False) -> bool:
    """
    Doble confirmacion para acciones destructivas (delete, archive masivo).
    """
    if dry_run:
        print(f"\n[DRY-RUN] Accion destructiva que se ejecutaria: {message}")
        return True
    print(f"\nACCION DESTRUCTIVA: {message}")
    print("Esta accion no se puede deshacer facilmente.")
    print("Primera confirmacion - escribe \'confirmo\': ", end="")
    r1 = input().strip().lower()
    if r1 != "confirmo":
        print("Cancelado.")
        return False
    print(f"Segunda confirmacion - escribe el client_id \'{client_id}\' para confirmar: ", end="")
    r2 = input().strip().lower()
    if r2 != client_id.lower():
        print("Client ID incorrecto. Cancelado.")
        return False
    return True
