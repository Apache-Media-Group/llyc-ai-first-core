"""
scripts/dv360/campaigns/create_campaign.py
Crea una Campana en DV360 con configuracion completa.
API v4 — valores validados contra la API real.

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

# Valores validados contra DV360 API v4
CAMPAIGN_GOAL_TYPES = {
    "AWARENESS":     "CAMPAIGN_GOAL_TYPE_BRAND_AWARENESS",
    "CONSIDERATION": "CAMPAIGN_GOAL_TYPE_ONLINE_ACTION",
    "ACTION":        "CAMPAIGN_GOAL_TYPE_ONLINE_ACTION",
    "REACH":         "CAMPAIGN_GOAL_TYPE_BRAND_AWARENESS",
}

KPI_TYPES = {
    "CPA":         "PERFORMANCE_GOAL_TYPE_CPA",
    "CPC":         "PERFORMANCE_GOAL_TYPE_CPC",
    "CTR":         "PERFORMANCE_GOAL_TYPE_CTR",
    "VCPM":        "PERFORMANCE_GOAL_TYPE_VCPM",
    "VIEWABILITY": "PERFORMANCE_GOAL_TYPE_VIEWABLE_CPM",
    "CPM":         "PERFORMANCE_GOAL_TYPE_CPM",
}

FREQUENCY_CAP_UNITS = {
    "MINUTES": "TIME_UNIT_MINUTES",
    "HOURS":   "TIME_UNIT_HOURS",
    "DAYS":    "TIME_UNIT_DAYS",
    "WEEKS":   "TIME_UNIT_WEEKS",
    "MONTHS":  "TIME_UNIT_MONTHS",
}


def _parse_date(date_str: str) -> dict:
    parts = date_str.split("-")
    return {"year": int(parts[0]), "month": int(parts[1]), "day": int(parts[2])}


def build_campaign_body(
    advertiser_id: str,
    name: str,
    goal: str,
    kpi: str,
    kpi_value: float | None,
    start_date: str,
    end_date: str,
    frequency_cap: int | None,
    frequency_cap_unit: str | None,
) -> dict:
    goal_type = CAMPAIGN_GOAL_TYPES.get(goal.upper())
    if not goal_type:
        raise ValueError(f"goal '{goal}' no valido. Opciones: {list(CAMPAIGN_GOAL_TYPES)}")

    kpi_type = KPI_TYPES.get(kpi.upper())
    if not kpi_type:
        raise ValueError(f"kpi '{kpi}' no valido. Opciones: {list(KPI_TYPES)}")

    body = {
        "advertiserId": advertiser_id,
        "displayName": name,
        "entityStatus": "ENTITY_STATUS_PAUSED",
        "campaignGoal": {
            "campaignGoalType": goal_type,
            "performanceGoal": {
                "performanceGoalType": kpi_type,
            },
        },
        "campaignFlight": {
            "plannedDates": {
                "startDate": _parse_date(start_date),
                "endDate": _parse_date(end_date),
            },
        },
    }

    # KPI value en micros
    if kpi_value is not None:
        if kpi.upper() in ("CPA", "CPC", "VCPM", "CPM"):
            body["campaignGoal"]["performanceGoal"]["performanceGoalAmountMicros"] = str(
                int(kpi_value * 1_000_000)
            )
        elif kpi.upper() in ("CTR", "VIEWABILITY"):
            body["campaignGoal"]["performanceGoal"]["performanceGoalPercentageMicros"] = str(
                int(kpi_value * 10_000)
            )

    # Frequency cap
    if frequency_cap and frequency_cap_unit:
        unit_mapped = FREQUENCY_CAP_UNITS.get(frequency_cap_unit.upper())
        if not unit_mapped:
            raise ValueError(f"frequency_cap_unit '{frequency_cap_unit}' no valido.")
        body["frequencyCap"] = {
            "maxImpressions": frequency_cap,
            "timeUnit": unit_mapped,
            "timeUnitCount": 1,
        }
    else:
        body["frequencyCap"] = {"unlimited": True}

    return body


def create_campaign(
    client_id: str,
    name: str,
    goal: str,
    kpi: str,
    kpi_value: float | None = None,
    start_date: str = None,
    end_date: str = None,
    frequency_cap: int | None = None,
    frequency_cap_unit: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Crea una Campana en DV360."""
    advertiser_id = get_advertiser_id(client_id)

    body = build_campaign_body(
        advertiser_id=advertiser_id,
        name=name,
        goal=goal,
        kpi=kpi,
        kpi_value=kpi_value,
        start_date=start_date,
        end_date=end_date,
        frequency_cap=frequency_cap,
        frequency_cap_unit=frequency_cap_unit,
    )

    action_msg = (
        f"Crear Campana '{name}' "
        f"(goal={goal}, kpi={kpi}, {start_date} -> {end_date}) "
        f"en advertiser {advertiser_id} cliente {client_id}"
    )

    if not confirm_action(action_msg, dry_run=dry_run):
        return {"status": "cancelled", "data": {}}

    if dry_run:
        return {
            "status": "dry_run",
            "data": {
                "advertiser_id": advertiser_id,
                "body": body,
                "note": "Dry-run completado. Revisa el body antes de ejecutar.",
            },
        }

    try:
        svc = build_writer_service(client_id=client_id)
        result = (
            svc.advertisers()
            .campaigns()
            .create(advertiserId=advertiser_id, body=body)
            .execute()
        )

        outcome = {
            "status": "ok",
            "data": {
                "campaign_id": result.get("campaignId"),
                "name": result.get("displayName"),
                "status": result.get("entityStatus"),
                "goal": result.get("campaignGoal", {}),
                "flight": result.get("campaignFlight", {}),
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
        script="create_campaign",
        action="create_campaign",
        client_id=client_id,
        args={
            "name": name,
            "goal": goal,
            "kpi": kpi,
            "kpi_value": kpi_value,
            "start_date": start_date,
            "end_date": end_date,
            "advertiser_id": advertiser_id,
        },
        result=outcome,
        dry_run=dry_run,
    )

    if outcome["status"] == "ok":
        campaign_id = outcome["data"]["campaign_id"]
        print(f"\n✅ Campana creada. campaign_id: {campaign_id}")
        print(f"Siguiente paso:")
        print(
            f"  python scripts/dv360/insertion_orders/create_io.py "
            f"--client {client_id} --campaign-id {campaign_id} ..."
        )

    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crea una Campana en DV360.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Objetivos (--goal):
  AWARENESS     Reconocimiento de marca
  CONSIDERATION Consideracion
  ACTION        Conversion / ventas
  REACH         Alcance

KPIs (--kpi):
  CPA    Coste por Adquisicion (--kpi-value en EUR)
  CPC    Coste por Clic (--kpi-value en EUR)
  CTR    Ratio de Clics (--kpi-value en %)
  VCPM   CPM visible (--kpi-value en EUR)
  CPM    CPM objetivo (--kpi-value en EUR)
  VIEWABILITY Visibilidad (--kpi-value en %)

Ejemplos:
  python scripts/dv360/campaigns/create_campaign.py \\
    --client test \\
    --name "TEST_Display_Q3_2026" \\
    --goal ACTION --kpi CPA --kpi-value 15.0 \\
    --start-date 2026-07-01 --end-date 2026-09-30 \\
    --dry-run
        """,
    )
    parser.add_argument("--client", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--goal", required=True, choices=list(CAMPAIGN_GOAL_TYPES))
    parser.add_argument("--kpi", required=True, choices=list(KPI_TYPES))
    parser.add_argument("--kpi-value", type=float, default=None)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--frequency-cap", type=int, default=None)
    parser.add_argument("--frequency-cap-unit", choices=list(FREQUENCY_CAP_UNITS), default=None)
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    result = create_campaign(
        client_id=args.client,
        name=args.name,
        goal=args.goal,
        kpi=args.kpi,
        kpi_value=args.kpi_value,
        start_date=args.start_date,
        end_date=args.end_date,
        frequency_cap=args.frequency_cap,
        frequency_cap_unit=args.frequency_cap_unit,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("ok", "dry_run", "cancelled") else 1)


if __name__ == "__main__":
    main()
