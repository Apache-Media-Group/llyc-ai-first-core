"""
scripts/_common/audit.py
Logging estructurado y confirmacion interactiva para scripts de escritura.

Compartido por todos los adapters de plataforma (DV360, Meta, ...).
Cada accion queda registrada en Cloud Logging con:
  who    — usuario que ejecuta (LLYC_OPERATOR o whoami)
  when   — timestamp ISO 8601
  what   — plataforma + script + accion + client_id + dry_run
  args   — parametros de la llamada (sin credenciales)
  result — status + payload resumido

Contrato de confirmacion: DEC_100.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone

log = logging.getLogger("llyc.scripts")


def _get_operator() -> str:
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
    Registra una ejecucion de script en Cloud Logging (JSON estructurado).

    Args:
        platform:  plataforma afectada (meta, dv360, google_ads, ...).
        script:    nombre del fichero de script.
        action:    accion ejecutada.
        client_id: ID del cliente.
        args:      parametros de la llamada — NUNCA incluir credenciales.
        result:    {status: ok|error, data: {...}, error: str|None}.
        dry_run:   True si fue ejecucion simulada.
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


def confirm_action(message: str, dry_run: bool = False) -> bool:
    """
    Confirmacion interactiva antes de ejecutar una accion.
    En dry-run devuelve True sin pedir input.
    """
    if dry_run:
        print(f"
[DRY-RUN] Se ejecutaria: {message}")
        return True

    print(f"
⚠️  ACCION REQUERIDA: {message}")
    print("Escribe si para confirmar, cualquier otra cosa para cancelar: ", end="", flush=True)
    response = input().strip().lower()

    if response == "si":
        return True

    print("Cancelado.")
    return False


def confirm_destructive(message: str, client_id: str, dry_run: bool = False) -> bool:
    """
    Doble confirmacion para acciones destructivas (delete, archive masivo).
    El usuario debe escribir confirmo y luego el client_id exacto.
    """
    if dry_run:
        print(f"
[DRY-RUN] Accion destructiva que se ejecutaria: {message}")
        return True

    print(f"
🔴 ACCION DESTRUCTIVA: {message}")
    print("Esta accion no se puede deshacer facilmente.")
    print("Primera confirmacion — escribe confirmo: ", end="", flush=True)
    r1 = input().strip().lower()
    if r1 != "confirmo":
        print("Cancelado.")
        return False

    print(f"Segunda confirmacion — escribe el client_id {client_id} para confirmar: ", end="", flush=True)
    r2 = input().strip().lower()
    if r2 != client_id.lower():
        print("Client ID incorrecto. Cancelado.")
        return False

    return True
