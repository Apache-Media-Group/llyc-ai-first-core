"""
scripts/dv360/insertion_orders/create_io.py
Crea un Insertion Order en DV360 con configuracion completa.

Jerarquia: Campaign → Insertion Order → Line Item → Creatives

El IO gestiona: presupuesto, ritmo de gasto, puja, frecuencia e inventario.

Uso:
    # Dry-run primero (obligatorio)
    python scripts/dv360/insertion_orders/create_io.py \\
        --client vidal-vidal \\
        --campaign-id 123456 \\
        --name "IO_ES_Display_Prospecting_Intereses" \\
        --budget-eur 5000.0 \\
        --pacing EVEN \\
        --start-date 2026-07-01 \\
        --end-date 2026-09-30 \\
        --frequency-cap 3 \\
        --frequency-cap-unit DAYS \\
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

_EUR_TO_MICROS = 1_000_000

# ── Valores validos ────────────────────────────────────────────────────────────

PACING_TYPES = {
    "EVEN":  "PACING_TYPE_EVEN",
    "AHEAD": "PACING_TYPE_AHEAD",
    "ASAP":  "PACING_TYPE_ASAP",
}

PACING_PERIODS = {
    "DAILY":  "PACING_PERIOD_DAILY",
    "FLIGHT": "PACING_PERIOD_FLIGHT",
}

BIDDING_STRATEGIES = {
    "MAXIMIZE":       "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPA",
    "CONTROL_BUDGET": "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CUSTOM",
}

FREQUENCY_CAP_UNITS = {
    "MINUTES": "TIME_UNIT_MINUTES",
    "HOURS":   "TIME_UNIT_HOURS",
    "DAYS":    "TIME_UNIT_DAYS",
    "WEEKS":   "TIME_UNIT_WEEKS",
    "MONTHS":  "TIME_UNIT_MONTHS",
}

# Exchanges/SSPs disponibles para public inventory
PUBLIC_EXCHANGES = {
    "GAM":       "EXCHANGE_GOOGLE_AD_MANAGER",
    "MAGNITE":   "EXCHANGE_MAGNITE",
    "OPENX":     "EXCHANGE_OPENX",
    "PUBMATIC":  "EXCHANGE_PUBMATIC",
    "INDEX":     "EXCHANGE_INDEX_EXCHANGE",
    "APPNEXUS":  "EXCHANGE_APPNEXUS",
    "RUBICON":   "EXCHANGE_RUBICON",
    "TRIPLELIFT":"EXCHANGE_TRIPLE_LIFT",
}


def _eur_to_micros(eur: float) -> int:
    return int(eur * _EUR_TO_MICROS)


def _parse_date(date_str: str) -> dict:
    parts = date_str.split("-")
    return {"year": int(parts[0]), "month": int(parts[1]), "day": int(parts[2])}


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
    performance_goal_type: str,
    performance_goal_value_eur: float | None,
    frequency_cap: int | None,
    frequency_cap_unit: str | None,
    exchanges: list[str],
    deal_ids: list[str],
    budget_segments: list[dict] | None,
) -> dict:
    """
    Construye el body completo para insertionOrders.create.

    Args:
        advertiser_id: ID del advertiser
        campaign_id: ID de la campaña padre
        name: nombre del IO (nomenclatura: IO_{pais}_{tipo}_{estrategia})
        budget_eur: presupuesto total del IO en EUR
        budget_unit: AMOUNT (EUR) | IMPRESSIONS
        start_date: fecha inicio YYYY-MM-DD
        end_date: fecha fin YYYY-MM-DD
        pacing: EVEN | AHEAD | ASAP
        pacing_period: DAILY | FLIGHT
        performance_goal_type: MAXIMIZE | CONTROL_BUDGET
        performance_goal_value_eur: valor numerico del objetivo (ej. CPA 15 EUR)
        frequency_cap: max impresiones por usuario en el periodo
        frequency_cap_unit: DAYS | WEEKS | MONTHS
        exchanges: lista de SSPs — ["GAM", "MAGNITE", ...]
        deal_ids: lista de IDs de deals PG/PMP negociados
        budget_segments: lista de segmentos de presupuesto con fechas y montos
                         [{"start": "2026-07-01", "end": "2026-07-31", "eur": 2000}]
    """
    pacing_type = PACING_TYPES.get(pacing.upper())
    if not pacing_type:
        raise ValueError(f"pacing '{pacing}' no valido. Opciones: {list(PACING_TYPES)}")

    pacing_period_type = PACING_PERIODS.get(pacing_period.upper())
    if not pacing_period_type:
        raise ValueError(f"pacing_period '{pacing_period}' no valido. Opciones: {list(PACING_PERIODS)}")

    budget_unit_mapped = "BUDGET_UNIT_CURRENCY" if budget_unit.upper() == "AMOUNT" else "BUDGET_UNIT_IMPRESSIONS"

    body = {
        "advertiserId": advertiser_id,
        "campaignId": campaign_id,
        "displayName": name,
        "entityStatus": "ENTITY_STATUS_DRAFT",  # Siempre se crea en DRAFT para revision
        "pacing": {
            "pacingPeriod": pacing_period_type,
            "pacingType": pacing_type,
        },
        "budget": {
            "budgetUnit": budget_unit_mapped,
            "automationType": "INSERTION_ORDER_AUTOMATION_TYPE_NONE",
        },
    }

    # Budget: monto total o segmentos
    if budget_segments:
        segments = []
        for seg in budget_segments:
            segments.append({
                "budgetAmountMicros": str(_eur_to_micros(seg["eur"])),
                "dateRange": {
                    "startDate": _parse_date(seg["start"]),
                    "endDate": _parse_date(seg["end"]),
                },
                "campaignBudgetId": "",  # Se asigna al vincular con campaign budget
            })
        body["budget"]["budgetSegments"] = segments
    else:
        # Presupuesto unico para todo el flight
        body["budget"]["budgetSegments"] = [
            {
                "budgetAmountMicros": str(_eur_to_micros(budget_eur)),
                "dateRange": {
                    "startDate": _parse_date(start_date),
                    "endDate": _parse_date(end_date),
                },
            }
        ]

    # Performance goal (puja y optimizacion)
    if performance_goal_value_eur is not None:
        body["performanceGoal"] = {
            "performanceGoalType": "PERFORMANCE_GOAL_TYPE_CPA",
            "performanceGoalAmountMicros": str(_eur_to_micros(performance_goal_value_eur)),
        }
    else:
        body["performanceGoal"] = {
            "performanceGoalType": "PERFORMANCE_GOAL_TYPE_CUSTOM",
            "performanceGoalString": "Optimize for delivery",
        }

    body["bidStrategy"] = {
        "maximizeSpendAutoBid": {
            "performanceGoalType": "BIDDING_STRATEGY_PERFORMANCE_GOAL_TYPE_CPA",
        }
    }

    # Frequency cap a nivel IO
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

    # Inventory sources — public exchanges + deals privados
    inventory_source_settings = {}

    if exchanges:
        exchange_list = []
        for ex in exchanges:
            mapped = PUBLIC_EXCHANGES.get(ex.upper())
            if mapped:
                exchange_list.append(mapped)
            else:
                log.warning(f"Exchange '{ex}' no reconocido. Ignorado.")
        if exchange_list:
            inventory_source_settings["whitelistedInventorySourceIds"] = []
            # En v4 los exchanges se configuran a nivel IO via inventorySourceGroups
            # Se declara como Open Auction por defecto si no hay deals
            body["inventorySourceSettings"] = {
                "whitelistedInventorySourceGroups": exchange_list,
            }

    if deal_ids:
        # Deals PG/PMP — se referencian por su ID en DV360
        body["inventorySourceSettings"] = body.get("inventorySourceSettings", {})
        body["inventorySourceSettings"]["inventorySourceIds"] = deal_ids

    if not exchanges and not deal_ids:
        # Sin restriccion de inventario — Open Auction completo
        body["inventorySourceSettings"] = {}

    return body


def create_io(
    client_id: str,
    campaign_id: str,
    name: str,
    budget_eur: float,
    budget_unit: str = "AMOUNT",
    start_date: str = None,
    end_date: str = None,
    pacing: str = "EVEN",
    pacing_period: str = "DAILY",
    performance_goal_type: str = "MAXIMIZE",
    performance_goal_value_eur: float | None = None,
    frequency_cap: int | None = None,
    frequency_cap_unit: str | None = None,
    exchanges: list[str] = None,
    deal_ids: list[str] = None,
    budget_segments: list[dict] | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Crea un Insertion Order en DV360.

    El IO se crea siempre en estado DRAFT para revision antes de activar.
    Usar activate_io.py para activarlo tras revision.

    Args:
        client_id: ID del cliente
        campaign_id: ID de la campaña padre (obtenido de create_campaign.py)
        name: nombre del IO. Nomenclatura: IO_{pais}_{tipo}_{estrategia}
        budget_eur: presupuesto total en EUR
        budget_unit: AMOUNT (EUR por defecto) | IMPRESSIONS
        start_date: fecha inicio YYYY-MM-DD
        end_date: fecha fin YYYY-MM-DD
        pacing: EVEN (recomendado) | AHEAD | ASAP
        pacing_period: DAILY (recomendado) | FLIGHT
        performance_goal_type: MAXIMIZE | CONTROL_BUDGET
        performance_goal_value_eur: CPA objetivo en EUR (ej. 15.0)
        frequency_cap: max impresiones por usuario en el periodo (ej. 3)
        frequency_cap_unit: DAYS | WEEKS | MONTHS
        exchanges: SSPs de inventario publico ["GAM", "MAGNITE", "PUBMATIC", ...]
        deal_ids: IDs de deals PG/PMP negociados con medios
        budget_segments: segmentos de presupuesto por periodo
                         [{"start": "2026-07-01", "end": "2026-07-31", "eur": 2000}]
        dry_run: si True, muestra la accion sin ejecutarla
    """
    if exchanges is None:
        exchanges = ["GAM"]  # Google Ad Manager por defecto
    if deal_ids is None:
        deal_ids = []

    advertiser_id = get_advertiser_id(client_id)

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
        performance_goal_type=performance_goal_type,
        performance_goal_value_eur=performance_goal_value_eur,
        frequency_cap=frequency_cap,
        frequency_cap_unit=frequency_cap_unit,
        exchanges=exchanges,
        deal_ids=deal_ids,
        budget_segments=budget_segments,
    )

    action_msg = (
        f"Crear IO '{name}' "
        f"(campaña {campaign_id}, budget {budget_eur} EUR, pacing {pacing}/{pacing_period}) "
        f"en advertiser {advertiser_id} cliente {client_id}. "
        "Se crea en DRAFT — requiere revision y activacion manual."
    )

    if not confirm_action(action_msg, dry_run=dry_run):
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
                "frequency_cap": result.get("frequencyCap", {}),
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
            "exchanges": exchanges,
            "deal_ids": deal_ids,
            "advertiser_id": advertiser_id,
        },
        result=outcome,
        dry_run=dry_run,
    )

    if outcome["status"] == "ok":
        io_id = outcome["data"]["io_id"]
        print(f"\n✅ IO creado en DRAFT. io_id: {io_id}")
        print("Siguiente paso: crear Line Items con este io_id.")
        print(
            f"  python scripts/dv360/line_items/create_line_item.py "
            f"--client {client_id} "
            f"--campaign-id {campaign_id} "
            f"--io-id {io_id} ..."
        )
        print(f"\nCuando el LI este listo, activar el IO:")
        print(
            f"  python scripts/dv360/insertion_orders/activate_io.py "
            f"--client {client_id} --io-id {io_id}"
        )

    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crea un Insertion Order en DV360.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Pacing (--pacing):
  EVEN    Distribuye el presupuesto uniformemente (RECOMENDADO)
  AHEAD   Gasta mas rapido al inicio del periodo
  ASAP    Sin restriccion temporal (solo campanas flash 24h)

Periodo de pacing (--pacing-period):
  DAILY   Por dia (RECOMENDADO)
  FLIGHT  Por todo el vuelo

Exchanges (--exchanges):
  GAM MAGNITE OPENX PUBMATIC INDEX APPNEXUS RUBICON TRIPLELIFT

Budget segments (--budget-segments):
  JSON con lista de segmentos:
  '[{"start":"2026-07-01","end":"2026-07-31","eur":2000},{"start":"2026-08-01","end":"2026-08-31","eur":3000}]'

Ejemplos:
  # IO simple con presupuesto unico
  python scripts/dv360/insertion_orders/create_io.py \\
    --client vidal-vidal \\
    --campaign-id 123456 \\
    --name "IO_ES_Display_Prospecting_InMarket" \\
    --budget-eur 5000 \\
    --pacing EVEN \\
    --pacing-period DAILY \\
    --start-date 2026-07-01 \\
    --end-date 2026-09-30 \\
    --frequency-cap 3 \\
    --frequency-cap-unit DAYS \\
    --exchanges GAM PUBMATIC \\
    --dry-run

  # IO con deal privado PMP
  python scripts/dv360/insertion_orders/create_io.py \\
    --client vidal-vidal \\
    --campaign-id 123456 \\
    --name "IO_ES_Display_PMP_Premium" \\
    --budget-eur 2000 \\
    --pacing EVEN \\
    --start-date 2026-07-01 \\
    --end-date 2026-07-31 \\
    --deal-ids "deal_abc123" "deal_xyz456" \\
    --dry-run
        """,
    )
    parser.add_argument("--client", required=True, help="ID del cliente")
    parser.add_argument("--campaign-id", required=True, help="ID de la campana padre")
    parser.add_argument("--name", required=True, help="Nombre del IO. Nomenclatura: IO_{pais}_{tipo}_{estrategia}")
    parser.add_argument("--budget-eur", required=True, type=float, help="Presupuesto total en EUR")
    parser.add_argument("--budget-unit", choices=["AMOUNT", "IMPRESSIONS"], default="AMOUNT", help="Unidad de presupuesto (defecto: AMOUNT=EUR)")
    parser.add_argument("--start-date", required=True, help="Fecha inicio YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="Fecha fin YYYY-MM-DD")
    parser.add_argument("--pacing", choices=["EVEN", "AHEAD", "ASAP"], default="EVEN", help="Ritmo de gasto (defecto: EVEN)")
    parser.add_argument("--pacing-period", choices=["DAILY", "FLIGHT"], default="DAILY", help="Periodo de pacing (defecto: DAILY)")
    parser.add_argument("--performance-goal-value", type=float, default=None, help="CPA objetivo en EUR")
    parser.add_argument("--frequency-cap", type=int, default=None, help="Max impresiones por usuario en el periodo")
    parser.add_argument("--frequency-cap-unit", choices=["MINUTES", "HOURS", "DAYS", "WEEKS", "MONTHS"], default=None)
    parser.add_argument("--exchanges", nargs="+", default=["GAM"], help="SSPs de inventario publico (defecto: GAM)")
    parser.add_argument("--deal-ids", nargs="+", default=[], help="IDs de deals PG/PMP negociados")
    parser.add_argument("--budget-segments", type=str, default=None, help="JSON con segmentos de presupuesto por periodo")
    parser.add_argument("--dry-run", action="store_true", help="Simula la accion sin ejecutarla")

    args = parser.parse_args()

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
        exchanges=args.exchanges,
        deal_ids=args.deal_ids,
        budget_segments=budget_segments,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("ok", "dry_run", "cancelled") else 1)


if __name__ == "__main__":
    main()
