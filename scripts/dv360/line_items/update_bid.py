"""
scripts/dv360/line_items/update_bid.py
Actualiza la puja fija (fixed bid) de un Line Item en DV360.

Guardrail: maximo 50 EUR por defecto (_CHECK_BUDGET_GUARD).
Se puede sobreescribir con --max-bid para casos justificados.

Uso:
    python scripts/dv360/line_items/update_bid.py \
        --client vidal-vidal \
        --line-item-id 123456789 \
        --bid-eur 12.50 \
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

# Guardrail heredado del codigo legacy (dv360-mcp-server _check_budget_guard)
_CHECK_BUDGET_GUARD_EUR = 50.0
_EUR_TO_MICROS = 1_000_000


def _eur_to_micros(eur: float) -> int:
    return int(eur * _EUR_TO_MICROS)


def update_bid(
    client_id: str,
    line_item_id: str,
    bid_eur: float,
    max_bid_eur: float = _CHECK_BUDGET_GUARD_EUR,
    dry_run: bool = False,
    reason: str | None = None,
) -> dict:
    """
    Actualiza la puja fija de un Line Item.

    Args:
        client_id: ID del cliente
        line_item_id: ID del Line Item
        bid_eur: nueva puja en EUR
        max_bid_eur: guardrail maximo (defecto 50 EUR)
        dry_run: si True, muestra la accion sin ejecutarla
        reason: justificacion del override del guardrail (obligatorio si max_bid_eur > defecto)
    """
    if bid_eur <= 0:
        return {
            "status": "error",
            "error": f"bid_eur debe ser positivo. Recibido: {bid_eur}",
            "data": {},
        }

    if bid_eur > max_bid_eur:
        return {
            "status": "error",
            "error": (
                f"bid_eur {bid_eur} EUR supera el guardrail de {max_bid_eur} EUR. "
                "Usa --max-bid para sobreescribir el limite con justificacion."
            ),
            "data": {},
        }

    advertiser_id = get_advertiser_id(client_id)
    bid_micros = _eur_to_micros(bid_eur)

    action_msg = (
        f"Actualizar puja Line Item {line_item_id} a {bid_eur} EUR ({bid_micros} micros) "
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
                "bid_eur": bid_eur,
                "bid_micros": bid_micros,
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
                updateMask="bidStrategy",
                body={
                    "bidStrategy": {
                        "fixedBid": {
                            "bidAmountMicros": str(bid_micros),
                        }
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
                "bid_strategy": result.get("bidStrategy", {}),
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
        script="update_bid",
        action="update_bid",
        client_id=client_id,
        args={
            "line_item_id": line_item_id,
            "advertiser_id": advertiser_id,
            "bid_eur": bid_eur,
            "bid_micros": bid_micros,
            "guardrail_max_eur": max_bid_eur,
            "reason": reason,
        },
        result=outcome,
        dry_run=dry_run,
    )

    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Actualiza la puja fija de un Line Item en DV360.",
        epilog=f"Guardrail por defecto: {_CHECK_BUDGET_GUARD_EUR} EUR maximo.",
    )
    parser.add_argument("--client", required=True, help="ID del cliente")
    parser.add_argument("--line-item-id", required=True, help="ID del Line Item")
    parser.add_argument("--bid-eur", required=True, type=float, help="Nueva puja en EUR")
    parser.add_argument(
        "--max-bid", type=float, default=_CHECK_BUDGET_GUARD_EUR,
        help=f"Guardrail maximo en EUR (defecto {_CHECK_BUDGET_GUARD_EUR})"
    )
    parser.add_argument("--dry-run", action="store_true", help="Simula la accion sin ejecutarla")
    parser.add_argument("--reason", type=str, default=None, help="Justificacion obligatoria si se sobreescribe el guardrail con --max-bid")

    args = parser.parse_args()
    if args.max_bid != _CHECK_BUDGET_GUARD_EUR and not args.reason:
        print("ERROR: --reason es obligatorio cuando se sobreescribe el guardrail con --max-bid.")
        sys.exit(1)

    result = update_bid(
        client_id=args.client,
        line_item_id=args.line_item_id,
        bid_eur=args.bid_eur,
        max_bid_eur=args.max_bid,
        dry_run=args.dry_run,
        reason=getattr(args, "reason", None),
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("ok", "dry_run", "cancelled") else 1)


if __name__ == "__main__":
    main()
