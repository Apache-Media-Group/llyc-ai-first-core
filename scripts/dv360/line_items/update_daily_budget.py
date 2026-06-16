"""
scripts/dv360/line_items/update_daily_budget.py
Actualiza el presupuesto diario de un Line Item en DV360.

Guardrail: maximo 20% de variacion respecto al presupuesto actual.
Se puede sobreescribir con --skip-guardrail para casos justificados.

Uso:
    python scripts/dv360/line_items/update_daily_budget.py \
        --client vidal-vidal \
        --line-item-id 123456789 \
        --budget-eur 150.00 \
        --dry-run

SA: llyc-ops-writer-sa (DEC_084). NUNCA llyc-agents-sa.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from googleapiclient.errors import HttpError

from scripts.dv360._common.auth import build_writer_service, get_advertiser_id
from scripts.dv360._common.audit import log_action, confirm_action

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

_MAX_VARIATION_PCT = 20.0
_EUR_TO_MICROS = 1_000_000


def _eur_to_micros(eur: float) -> int:
    return int(eur * _EUR_TO_MICROS)


def _micros_to_eur(micros: int) -> float:
    return micros / _EUR_TO_MICROS


def update_daily_budget(
    client_id: str,
    line_item_id: str,
    budget_eur: float,
    skip_guardrail: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Actualiza el presupuesto diario de un Line Item.

    Lee el presupuesto actual antes de escribir para aplicar el guardrail de variacion.

    Args:
        client_id: ID del cliente
        line_item_id: ID del Line Item
        budget_eur: nuevo presupuesto diario en EUR
        skip_guardrail: si True, omite el guardrail de variacion
        dry_run: si True, muestra la accion sin ejecutarla
    """
    if budget_eur <= 0:
        return {
            "status": "error",
            "error": f"budget_eur debe ser positivo. Recibido: {budget_eur}",
            "data": {},
        }

    advertiser_id = get_advertiser_id(client_id)

    # Leer presupuesto actual para validar guardrail
    current_budget_eur = None
    if not skip_guardrail:
        try:
            svc = build_writer_service(client_id=client_id)
            li = (
                svc.advertisers()
                .lineItems()
                .get(advertiserId=advertiser_id, lineItemId=line_item_id)
                .execute()
            )
            budget_info = li.get("budget", {})
            current_micros = budget_info.get("maxAmount")
            if current_micros:
                current_budget_eur = _micros_to_eur(int(current_micros))
                variation_pct = abs(budget_eur - current_budget_eur) / current_budget_eur * 100
                if variation_pct > _MAX_VARIATION_PCT:
                    return {
                        "status": "error",
                        "error": (
                            f"Variacion {variation_pct:.1f}% supera el guardrail de {_MAX_VARIATION_PCT}%. "
                            f"Presupuesto actual: {current_budget_eur} EUR. "
                            f"Nuevo: {budget_eur} EUR. "
                            "Usa --skip-guardrail para sobreescribir con justificacion."
                        ),
                        "data": {
                            "current_budget_eur": current_budget_eur,
                            "new_budget_eur": budget_eur,
                            "variation_pct": round(variation_pct, 1),
                        },
                    }
        except Exception as e:
            log.warning(f"No se pudo leer presupuesto actual para guardrail: {e}. Continuando sin validacion.")

    budget_micros = _eur_to_micros(budget_eur)

    action_msg = (
        f"Actualizar presupuesto diario Line Item {line_item_id} "
        f"de {current_budget_eur or '?'} EUR a {budget_eur} EUR ({budget_micros} micros) "
        f"(advertiser {advertiser_id}, cliente {client_id})"
    )

    if not confirm_action(action_msg, dry_run=dry_run):
        return {"status": "cancelled", "data": {}}

    if dry_run:
        return {
            "status": "dry_run",
            "data": {
                "line_item_id": line_item_id,
                "advertiser_id": advertiser_id,
                "current_budget_eur": current_budget_eur,
                "new_budget_eur": budget_eur,
                "new_budget_micros": budget_micros,
            },
        }

    try:
        svc = build_writer_service(client_id=client_id)
        result = (
            svc.advertisers()
            .lineItems()
            .patch(
                advertiserId=advertiser_id,
                lineItemId=line_item_id,
                updateMask="budget.maxAmount",
                body={
                    "budget": {
                        "maxAmount": str(budget_micros),
                    }
                },
            )
            .execute()
        )

        outcome = {
            "status": "ok",
            "data": {
                "line_item_id": result.get("lineItemId"),
                "name": result.get("displayName"),
                "budget": result.get("budget", {}),
            },
        }

    except HttpError as e:
        outcome = {
            "status": "error",
            "error": f"DV360 API {e.resp.status}: {e.reason}",
            "data": {},
        }
    except Exception as e:
        outcome = {
            "status": "error",
            "error": str(e),
            "data": {},
        }

    log_action(
        script="update_daily_budget",
        action="update_daily_budget",
        client_id=client_id,
        args={
            "line_item_id": line_item_id,
            "advertiser_id": advertiser_id,
            "budget_eur": budget_eur,
            "budget_micros": budget_micros,
            "previous_budget_eur": current_budget_eur,
            "skip_guardrail": skip_guardrail,
        },
        result=outcome,
        dry_run=dry_run,
    )

    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Actualiza el presupuesto diario de un Line Item en DV360.",
        epilog=f"Guardrail: maximo {_MAX_VARIATION_PCT}% de variacion respecto al presupuesto actual.",
    )
    parser.add_argument("--client", required=True, help="ID del cliente")
    parser.add_argument("--line-item-id", required=True, help="ID del Line Item")
    parser.add_argument("--budget-eur", required=True, type=float, help="Nuevo presupuesto diario en EUR")
    parser.add_argument(
        "--skip-guardrail", action="store_true",
        help=f"Omite el guardrail de variacion maxima ({_MAX_VARIATION_PCT}%)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Simula la accion sin ejecutarla")

    args = parser.parse_args()

    result = update_daily_budget(
        client_id=args.client,
        line_item_id=args.line_item_id,
        budget_eur=args.budget_eur,
        skip_guardrail=args.skip_guardrail,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("ok", "dry_run", "cancelled") else 1)


if __name__ == "__main__":
    main()
