"""
scripts/dv360/insertion_orders/activate_io.py
Activa un Insertion Order en DV360.

Uso:
    python scripts/dv360/insertion_orders/activate_io.py \
        --client vidal-vidal \
        --io-id 123456789 \
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


def activate_io(
    client_id: str,
    io_id: str,
    dry_run: bool = False,
) -> dict:
    """
    Activa un Insertion Order en DV360 (ENTITY_STATUS_ACTIVE).

    Args:
        client_id: ID del cliente
        io_id: ID del Insertion Order a activar
        dry_run: si True, muestra la accion sin ejecutarla
    """
    advertiser_id = get_advertiser_id(client_id)

    action_msg = (
        f"Activar Insertion Order {io_id} "
        f"(advertiser {advertiser_id}, cliente {client_id})"
    )

    if not confirm_action(action_msg, dry_run=dry_run):
        return {"status": "cancelled", "data": {}}

    if dry_run:
        return {
            "status": "dry_run",
            "data": {
                "io_id": io_id,
                "advertiser_id": advertiser_id,
                "action": "activate",
                "new_status": "ENTITY_STATUS_ACTIVE",
            },
        }

    try:
        svc = build_writer_service(client_id=client_id)
        result = (
            svc.advertisers()
            .insertionOrders()
            .patch(
                advertiserId=advertiser_id,
                insertionOrderId=io_id,
                updateMask="entityStatus",
                body={"entityStatus": "ENTITY_STATUS_ACTIVE"},
            )
            .execute()
        )

        outcome = {
            "status": "ok",
            "data": {
                "io_id": result.get("insertionOrderId"),
                "name": result.get("displayName"),
                "entity_status": result.get("entityStatus"),
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
        script="activate_io",
        action="activate_io",
        client_id=client_id,
        args={"io_id": io_id, "advertiser_id": advertiser_id},
        result=outcome,
        dry_run=dry_run,
    )

    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description="Activa un Insertion Order en DV360.")
    parser.add_argument("--client", required=True, help="ID del cliente")
    parser.add_argument("--io-id", required=True, help="ID del Insertion Order a activar")
    parser.add_argument("--dry-run", action="store_true", help="Simula la accion sin ejecutarla")

    args = parser.parse_args()

    result = activate_io(
        client_id=args.client,
        io_id=args.io_id,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("ok", "dry_run", "cancelled") else 1)


if __name__ == "__main__":
    main()
