"""
scripts/dv360/insertion_orders/create_io.py
Crea un Insertion Order en DV360.
API v4 — campos validados contra la API real.

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

_EUR_TO_MICROS = 1_000_000

PACING_TYPES = {
    "EVEN":  "PACING_TYPE_EVEN",
    "AHEAD": "PACING_TYPE_EVEN",  # AHEAD no existe en IO v4, se mapea a EVEN
    "ASAP":  "PACING_TYPE_ASAP",
}

PACING_PERIODS = {
    "DAILY":  "PACING_PERIOD_DAILY",
    "FLIGHT": "PACING_PERIOD_FLIGHT",
}

FREQUENCY_CAP_UNITS = {
    "MINUTES": "TIME_UNIT_MINUTES",
    "HOURS":   "TIME_UNIT_HOURS",
    "DAYS":    "TIME_UNIT_DAYS",
    "WEEKS":   "TIME_UNIT_WEEKS",
    "MONTHS":  "TIME_UNIT_MONTHS",
}


_MAX_BUDGET_IO_EUR = 30000.0

OPTIMIZATION_OBJECTIVES = {
    "CONVERSIONS":     "CONVERSION",
    "CLICKS":          "CLICK",
    "BRAND_AWARENESS": "BRAND_AWARENESS",
    "VIEWABILITY":     "VIEWABILITY",
    "CUSTOM":          "CUSTOM",
    "NONE":            "NONE",
}

AUTOMATION_TYPES = {
    "NONE":   "INSERTION_ORDER_AUTOMATION_TYPE_NONE",
    "BUDGET": "INSERTION_ORDER_AUTOMATION_TYPE_BUDGET",
    "BID":    "INSERTION_ORDER_AUTOMATION_TYPE_BID",
}

def _eur_to_micros(eur: float) -> int:
    return int(eur * _EUR_TO_MICROS)


def _parse_date(date_str: str) -> dict:
    parts = date_str.split("-")
    return {"year": int(parts[0]), "month": int(parts[1]), "day": int(parts[2])}

KPI_TYPES_PERCENTAGE = {"VIEWABILITY", "CTR", "BRAND_LIFT"}

def _build_kpi(kpi_type: str, kpi_value: str) -> dict:
    kpi_type_mapped = f"KPI_TYPE_{kpi_type.upper()}"
    if kpi_type.upper() in KPI_TYPES_PERCENTAGE:
        return {"kpiType": kpi_type_mapped, "kpiPercentageMicros": kpi_value}
    else:
        return {"kpiType": kpi_type_mapped, "kpiAmountMicros": kpi_value}

def build_io_body(
    advertiser_id: str,
    campaign_id: str,
    name: str,
    budget_eur: float,
    budget_unit: str,
    start_date: str,
    end_date: str,
    pacing: str,
    pacing_period: str,
    performance_goal_value_eur: float | None,
    frequency_cap: int | None,
    frequency_cap_unit: str | None,
    budget_segments: list | None,
    optimization_objective: str = "CONVERSIONS",
    automation_type: str = "NONE",
    kpi_type: str = None,
    kpi_value: str = None,
) -> dict:
    pacing_type = PACING_TYPES.get(pacing.upper())
    if not pacing_type:
        raise ValueError(f"pacing '{pacing}' no valido. Opciones: {list(PACING_TYPES)}")

    pacing_period_type = PACING_PERIODS.get(pacing_period.upper())
    if not pacing_period_type:
        raise ValueError(f"pacing_period '{pacing_period}' no valido.")

    budget_unit_mapped = "BUDGET_UNIT_CURRENCY" if budget_unit.upper() == "AMOUNT" else "BUDGET_UNIT_IMPRESSIONS"

    opt_obj_mapped = OPTIMIZATION_OBJECTIVES.get(optimization_objective.upper(), "CONVERSION")
    body = {
        "campaignId": campaign_id,
        "displayName": name,
        "entityStatus": "ENTITY_STATUS_DRAFT",
        "optimizationObjective": opt_obj_mapped,
        "kpi": _build_kpi(kpi_type, kpi_value),
        "pacing": {
            "pacingPeriod": pacing_period_type,
            "pacingType": pacing_type,
            "dailyMaxMicros": str(int(budget_eur / 90 * 1_000_000)),
        },
        "budget": {
            "budgetUnit": budget_unit_mapped,
            "automationType": AUTOMATION_TYPES.get(automation_type.upper(), "INSERTION_ORDER_AUTOMATION_TYPE_NONE"),
        },
    }

    # Budget segments
    if budget_segments:
        segments = []
        for seg in budget_segments:
            segments.append({
                "budgetAmountMicros": str(_eur_to_micros(seg["eur"])),
                "dateRange": {
                    "startDate": _parse_date(seg["start"]),
                    "endDate": _parse_date(seg["end"]),
                },
            })
        body["budget"]["budgetSegments"] = segments
    else:
        body["budget"]["budgetSegments"] = [
            {
                "budgetAmountMicros": str(_eur_to_micros(budget_eur)),
                "dateRange": {
                    "startDate": _parse_date(start_date),
                    "endDate": _parse_date(end_date),
                },
            }
        ]

    # Bid strategy — mapeo KPI → performanceGoalType
    KPI_TO_BID_STRATEGY = {
        # Performance
        "CPC":         "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPC",
        "CPA":         "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPA",
        "CTR":         "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPC",   # CTR→CPC es la puja equivalente
        # Brand awareness / viewability
        "CPM":         "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_AV_VIEWED",
        "VCPM":        "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_AV_VIEWED",
        "VIEWABILITY": "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_AV_VIEWED",
        # Video completion
        "CPCV":        "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPCV",
        "CPIAVC":      "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPIAVC",
        # YouTube
        "VTR":         "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_AV_VIEWED",  # mejor aproximación disponible
        # Custom
        "BRAND_LIFT":  "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CUSTOM",
        "CUSTOM":      "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CUSTOM",
    }
    bid_goal_type = KPI_TO_BID_STRATEGY.get(
        kpi_type.upper() if kpi_type else "CPA",
        "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPA"
    )
    if performance_goal_value_eur:
        body["bidStrategy"] = {
            "maximizeSpendAutoBid": {
                "performanceGoalType": bid_goal_type,
                "maxAverageCpmBidAmountMicros": str(_eur_to_micros(performance_goal_value_eur)),
            }
        }
    else:
        body["bidStrategy"] = {
            "maximizeSpendAutoBid": {
                "performanceGoalType": bid_goal_type,
            }
        }

    # Frequency cap
    if frequency_cap and frequency_cap_unit:
        unit_mapped = FREQUENCY_CAP_UNITS.get(frequency_cap_unit.upper())
        if unit_mapped:
            body["frequencyCap"] = {
                "maxImpressions": frequency_cap,
                "timeUnit": unit_mapped,
                "timeUnitCount": 1,
            }
    else:
        body["frequencyCap"] = {"unlimited": True}

    return body


def create_io(
    client_id: str,
    campaign_id: str,
    name: str,
    budget_eur: float,
    max_budget_eur: float = _MAX_BUDGET_IO_EUR,
    reason: str | None = None,
    budget_unit: str = "AMOUNT",
    start_date: str = None,
    end_date: str = None,
    pacing: str = "EVEN",
    pacing_period: str = "DAILY",
    performance_goal_value_eur: float | None = None,
    frequency_cap: int | None = None,
    frequency_cap_unit: str | None = None,
    budget_segments: list | None = None,
    optimization_objective: str = "CONVERSIONS",
    automation_type: str = "NONE",
    kpi_type: str = None,
    kpi_value: str = None,
    dry_run: bool = False,
    skip_confirm: bool = False,
) -> dict:
    """Crea un Insertion Order en DV360. Se crea siempre en DRAFT."""
    advertiser_id = get_advertiser_id(client_id)
    if pacing.upper() == "ASAP":
        return {"status": "error", "error": "ASAP no permitido en IOs (guardrail operativo). Usa EVEN o AHEAD.", "data": {}}
    if budget_eur > max_budget_eur:
        return {
            "status": "error",
            "error": (
                f"budget_eur {budget_eur} EUR supera el guardrail de {max_budget_eur} EUR. "
                "Usa --max-budget con --reason para sobreescribir."
            ),
            "data": {"budget_eur": budget_eur, "guardrail_max_eur": max_budget_eur},
        }

    body = build_io_body(
        advertiser_id=advertiser_id,
        campaign_id=campaign_id,
        name=name,
        budget_eur=budget_eur,
        budget_unit=budget_unit,
        start_date=start_date,
        end_date=end_date,
        pacing=pacing,
        pacing_period=pacing_period,
        performance_goal_value_eur=performance_goal_value_eur,
        frequency_cap=frequency_cap,
        frequency_cap_unit=frequency_cap_unit,
        budget_segments=budget_segments,
        optimization_objective=optimization_objective,
        automation_type=automation_type,
        kpi_type=kpi_type,
        kpi_value=kpi_value,
    )

    action_msg = (
        f"Crear IO '{name}' "
        f"(campana {campaign_id}, budget {budget_eur} EUR, pacing {pacing}/{pacing_period}) "
        f"en advertiser {advertiser_id} cliente {client_id}. "
        "Se crea en DRAFT."
    )

    if not confirm_action(action_msg, dry_run=dry_run,
        skip_confirm=skip_confirm):
        return {"status": "cancelled", "data": {}}

    if dry_run:
        return {
            "status": "dry_run",
            "data": {
                "advertiser_id": advertiser_id,
                "campaign_id": campaign_id,
                "body": body,
                "note": "IO se crearia en DRAFT. Revisar body antes de ejecutar.",
            },
        }

    try:
        svc = build_writer_service(client_id=client_id)
        result = (
            svc.advertisers()
            .insertionOrders()
            .create(advertiserId=advertiser_id, body=body)
            .execute()
        )

        outcome = {
            "status": "ok",
            "data": {
                "io_id": result.get("insertionOrderId"),
                "campaign_id": result.get("campaignId"),
                "name": result.get("displayName"),
                "entity_status": result.get("entityStatus"),
                "pacing": result.get("pacing", {}),
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
        script="create_io",
        action="create_io",
        client_id=client_id,
        args={
            "campaign_id": campaign_id,
            "name": name,
            "budget_eur": budget_eur,
            "pacing": pacing,
            "advertiser_id": advertiser_id, "guardrail_max_eur": max_budget_eur,
            "reason": reason,
        },
        result=outcome,
        dry_run=dry_run,
    )

    if outcome["status"] == "ok":
        io_id = outcome["data"]["io_id"]
        print(f"\n IO creado en DRAFT. io_id: {io_id}")
        print(f"Siguiente paso:")
        print(
            f"  python scripts/dv360/line_items/create_line_item.py "
            f"--client {client_id} --campaign-id {campaign_id} --io-id {io_id} ..."
        )

    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea un Insertion Order en DV360.")
    parser.add_argument("--client", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--budget-eur", required=True, type=float)
    parser.add_argument("--max-budget", type=float, default=_MAX_BUDGET_IO_EUR,
                        help=f"Guardrail maximo de presupuesto IO en EUR (defecto {_MAX_BUDGET_IO_EUR})")
    parser.add_argument("--reason", type=str, default=None,
                        help="Justificacion obligatoria si se sobreescribe el guardrail con --max-budget")
    parser.add_argument("--budget-unit", choices=["AMOUNT", "IMPRESSIONS"], default="AMOUNT")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--pacing", choices=["EVEN", "AHEAD", "ASAP"], default="EVEN")
    parser.add_argument("--pacing-period", choices=["DAILY", "FLIGHT"], default="DAILY")
    parser.add_argument("--performance-goal-value", type=float, default=None)
    parser.add_argument("--frequency-cap", type=int, default=None)
    parser.add_argument("--frequency-cap-unit", choices=list(FREQUENCY_CAP_UNITS), default=None)
    parser.add_argument("--budget-segments", type=str, default=None)
    parser.add_argument("--optimization-objective", choices=list(OPTIMIZATION_OBJECTIVES), default="CONVERSIONS", help="Objetivo de optimizacion del IO (defecto: CONVERSIONS)")
    parser.add_argument("--automation-type", choices=list(AUTOMATION_TYPES), default="NONE", help="Tipo de automatizacion: NONE | BUDGET (automate bid+budget) | BID")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--kpi-type", required=True, choices=["VIEWABILITY", "CTR", "CPC", "CPA", "CPM", "CPIAVC", "BRAND_LIFT"], help="Tipo de KPI del IO")
    parser.add_argument("--kpi-value", required=True, help="Valor del KPI en micros (ej: 500000=0.50EUR para CPC)")
    args = parser.parse_args()
    if args.max_budget != _MAX_BUDGET_IO_EUR and not args.reason:
        print("ERROR: --reason es obligatorio cuando se sobreescribe el guardrail con --max-budget.")
        sys.exit(1)

    budget_segments = None
    if args.budget_segments:
        try:
            budget_segments = json.loads(args.budget_segments)
        except json.JSONDecodeError as e:
            print(f"Error parseando --budget-segments: {e}")
            sys.exit(1)

    result = create_io(
        client_id=args.client,
        campaign_id=args.campaign_id,
        name=args.name,
        budget_eur=args.budget_eur,
        budget_unit=args.budget_unit,
        start_date=args.start_date,
        end_date=args.end_date,
        pacing=args.pacing,
        pacing_period=args.pacing_period,
        performance_goal_value_eur=args.performance_goal_value,
        frequency_cap=args.frequency_cap,
        frequency_cap_unit=args.frequency_cap_unit,
        budget_segments=budget_segments,
        optimization_objective=getattr(args, "optimization_objective", "CONVERSIONS"),
        automation_type=getattr(args, "automation_type", "NONE"),
        kpi_type=getattr(args, "kpi_type", "VIEWABILITY"),
        kpi_value=getattr(args, "kpi_value", "700000"),
        dry_run=args.dry_run,
        max_budget_eur=args.max_budget,
        reason=getattr(args, "reason", None),
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("ok", "dry_run", "cancelled") else 1)


if __name__ == "__main__":
    main()
