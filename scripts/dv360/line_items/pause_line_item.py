"""
scripts/dv360/line_items/pause_line_item.py
Pausa un Line Item en DV360.

Uso:
    python scripts/dv360/line_items/pause_line_item.py \
        --client vidal-vidal \
        --line-item-id 123456789 \
        --dry-run

    python scripts/dv360/line_items/pause_line_item.py \
        --client vidal-vidal \
        --line-item-id 123456789

SA: llyc-ops-writer-sa (DEC_084). NUNCA llyc-agents-sa.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Permite importar _common desde cualquier directorio de trabajo
sys.path.insert(0, str(Path(__file__).parents[3]))

from googleapiclient.errors import HttpError

from scripts.dv360._common.auth import build_writer_service, get_advertiser_id
from scripts.dv360._common.audit import log_action, confirm_action

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def pause_line_item(
    client_id: str,
    line_item_id: str,
    dry_run: bool = False,
) -> dict:
    """
    Pausa un Line Item en DV360.

    Args:
        client_id: ID del cliente (ej. 'vidal-vidal')
        line_item_id: ID del Line Item a pausar
        dry_run: si True, muestra la accion sin ejecutarla

    Returns:
        dict con status y datos del LI actualizado
    """
    advertiser_id = get_advertiser_id(client_id)

    action_msg = (
        f"Pausar Line Item {line_item_id} "
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
                "action": "pause",
                "new_status": "ENTITY_STATUS_PAUSED",
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
                updateMask="entityStatus",
                body={"entityStatus": "ENTITY_STATUS_PAUSED"},
            )
            .execute()
        )

        outcome = {
            "status": "ok",
            "data": {
                "line_item_id": result.get("lineItemId"),
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
        script="pause_line_item",
        action="pause_line_item",
        client_id=client_id,
        args={"line_item_id": line_item_id, "advertiser_id": advertiser_id},
        result=outcome,
        dry_run=dry_run,
    )

    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pausa un Line Item en DV360.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Dry-run (ver que haria sin ejecutar)
  python scripts/dv360/line_items/pause_line_item.py --client vidal-vidal --line-item-id 123456789 --dry-run

  # Ejecucion real
  python scripts/dv360/line_items/pause_line_item.py --client vidal-vidal --line-item-id 123456789
        """,
    )
    parser.add_argument("--client", required=True, help="ID del cliente (ej. vidal-vidal)")
    parser.add_argument("--line-item-id", required=True, help="ID del Line Item a pausar")
    parser.add_argument("--dry-run", action="store_true", help="Simula la accion sin ejecutarla")

    args = parser.parse_args()

    result = pause_line_item(
        client_id=args.client,
        line_item_id=args.line_item_id,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("ok", "dry_run", "cancelled") else 1)


if __name__ == "__main__":
    main()
