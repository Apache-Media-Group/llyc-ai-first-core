"""
scripts/dv360/campaigns/create_campaign.py
Crea una Campaña en DV360 con configuración completa.

Jerarquia DV360: Campaign → Insertion Order → Line Item → Creatives

Uso:
    # Dry-run primero (obligatorio antes de ejecutar en produccion)
    python scripts/dv360/campaigns/create_campaign.py \
        --client vidal-vidal \
        --name "ES_PROD_Display_Conversion_Q2_2026" \
        --goal CAMPAIGN_GOAL_TYPE_DRIVE_ACTION \
        --kpi CPA \
        --kpi-value 15.0 \
        --start-date 2026-07-01 \
        --end-date 2026-09-30 \
        --frequency-cap 5 \
        --frequency-cap-unit MONTHS \
        --dry-run

    # Ejecucion real tras confirmar dry-run
    python scripts/dv360/campaigns/create_campaign.py \
        --client vidal-vidal \
        --name "ES_PROD_Display_Conversion_Q2_2026" \
        --goal CAMPAIGN_GOAL_TYPE_DRIVE_ACTION \
        --kpi CPA \
        --kpi-value 15.0 \
        --start-date 2026-07-01 \
        --end-date 2026-09-30 \
        --frequency-cap 5 \
        --frequency-cap-unit MONTHS

SA: llyc-ops-writer-sa (DEC_084). NUNCA llyc-agents-sa.

Referencia API:
    https://developers.google.com/display-video/api/reference/rest/v4/advertisers.campaigns/create
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


# ── Valores validos ────────────────────────────────────────────────────────────

CAMPAIGN_GOAL_TYPES = {
    "AWARENESS":     "CAMPAIGN_GOAL_TYPE_RAISE_AWARENESS",
    "CONSIDERATION": "CAMPAIGN_GOAL_TYPE_DRIVE_CONSIDERATION",
    "ACTION":        "CAMPAIGN_GOAL_TYPE_DRIVE_ACTION",
}

KPI_TYPES = {
    "CPA":    "KPI_TYPE_CPA",
    "CPC":    "KPI_TYPE_CPC",
    "CTR":    "KPI_TYPE_CTR",
    "VCPM":   "KPI_TYPE_VCPM",
    "VIEWABILITY": "KPI_TYPE_VIEWABILITY",
}

FREQUENCY_CAP_UNITS = {
    "MINUTES": "TIME_UNIT_MINUTES",
    "HOURS":   "TIME_UNIT_HOURS",
    "DAYS":    "TIME_UNIT_DAYS",
    "WEEKS":   "TIME_UNIT_WEEKS",
    "MONTHS":  "TIME_UNIT_MONTHS",
}

CREATIVE_TYPES = {
    "DISPLAY": "CREATIVE_TYPE_STANDARD",
    "VIDEO":   "CREATIVE_TYPE_VIDEO",
    "AUDIO":   "CREATIVE_TYPE_AUDIO",
}


def _parse_date(date_str: str) -> dict:
    """Convierte YYYY-MM-DD al formato de fecha de la API DV360."""
    parts = date_str.split("-")
    if len(parts) != 3:
        raise ValueError(f"Fecha invalida: {date_str}. Formato esperado: YYYY-MM-DD")
    return {
        "year": int(parts[0]),
        "month": int(parts[1]),
        "day": int(parts[2]),
    }


def build_campaign_body(
    advertiser_id: str,
    name: str,
    goal: str,
    kpi: str,
    kpi_value: float | None,
    creative_types: list[str],
    start_date: str,
    end_date: str,
    frequency_cap: int | None,
    frequency_cap_unit: str | None,
    frequency_cap_max_impressions: int | None,
    budget_optimization: bool,
) -> dict:
    """
    Construye el body de la request para campaigns.create.

    Args:
        advertiser_id: ID del advertiser DV360
        name: nombre de la campaña (usar nomenclatura estandarizada)
        goal: tipo de objetivo — AWARENESS | CONSIDERATION | ACTION
        kpi: KPI principal — CPA | CPC | CTR | VCPM | VIEWABILITY
        kpi_value: valor numerico del KPI (ej. 15.0 para CPA 15 EUR). None si no aplica.
        creative_types: lista de tipos de creatividad — ["DISPLAY"] | ["DISPLAY", "VIDEO"]
        start_date: fecha inicio YYYY-MM-DD
        end_date: fecha fin YYYY-MM-DD
        frequency_cap: numero maximo de impresiones por usuario en el periodo
        frequency_cap_unit: unidad de tiempo — MINUTES | HOURS | DAYS | WEEKS | MONTHS
        frequency_cap_max_impressions: alias de frequency_cap (API usa maxImpressions)
        budget_optimization: True = el algoritmo distribuye budget entre IOs automaticamente
    """
    goal_type = CAMPAIGN_GOAL_TYPES.get(goal.upper())
    if not goal_type:
        raise ValueError(f"goal '{goal}' no valido. Opciones: {list(CAMPAIGN_GOAL_TYPES)}")

    kpi_type = KPI_TYPES.get(kpi.upper())
    if not kpi_type:
        raise ValueError(f"kpi '{kpi}' no valido. Opciones: {list(KPI_TYPES)}")

    creative_type_list = []
    for ct in creative_types:
        mapped = CREATIVE_TYPES.get(ct.upper())
        if not mapped:
            raise ValueError(f"creative_type '{ct}' no valido. Opciones: {list(CREATIVE_TYPES)}")
        creative_type_list.append(mapped)

    body = {
        "advertiserId": advertiser_id,
        "displayName": name,
        "campaignGoal": {
            "campaignGoalType": goal_type,
            "performanceGoal": {
                "performanceGoalType": kpi_type,
            },
        },
        "campaignFlight": {
            "plannedSpendAmountMicros": None,  # Opcional — presupuesto total planificado
            "plannedDates": {
                "startDate": _parse_date(start_date),
                "endDate": _parse_date(end_date),
            },
        },
        "creativeTypes": creative_type_list,
    }

    # KPI value — algunos KPIs (CTR, VIEWABILITY) no tienen valor numerico
    if kpi_value is not None:
        if kpi.upper() in ("CPA", "CPC"):
            # CPA y CPC se expresan en micros (EUR * 1_000_000)
            body["campaignGoal"]["performanceGoal"]["performanceGoalAmountMicros"] = str(
                int(kpi_value * 1_000_000)
            )
        elif kpi.upper() == "VCPM":
            body["campaignGoal"]["performanceGoal"]["performanceGoalAmountMicros"] = str(
                int(kpi_value * 1_000_000)
            )
        elif kpi.upper() in ("CTR", "VIEWABILITY"):
            # CTR y Viewability son porcentajes (0-100)
            body["campaignGoal"]["performanceGoal"]["performanceGoalPercentageMicros"] = str(
                int(kpi_value * 10_000)  # % * 10_000 = micros de porcentaje
            )

    # Frequency cap a nivel campaña
    if frequency_cap and frequency_cap_unit:
        unit_mapped = FREQUENCY_CAP_UNITS.get(frequency_cap_unit.upper())
        if not unit_mapped:
            raise ValueError(
                f"frequency_cap_unit '{frequency_cap_unit}' no valido. "
                f"Opciones: {list(FREQUENCY_CAP_UNITS)}"
            )
        body["frequencyCap"] = {
            "maxImpressions": frequency_cap,
            "timeUnit": unit_mapped,
            "timeUnitCount": 1,  # "cada 1 semana", "cada 1 mes"
        }
    else:
        # Sin frequency cap a nivel campaña (se gestiona a nivel IO/LI)
        body["frequencyCap"] = {"unlimited": True}

    # Budget optimization (distribucion automatica entre IOs)
    body["campaignBudgets"] = []  # Se añaden presupuestos al crear/actualizar IOs
    # La optimizacion de budget se controla desde la IO, no desde la campaña en v4

    return body


def create_campaign(
    client_id: str,
    name: str,
    goal: str,
    kpi: str,
    kpi_value: float | None = None,
    creative_types: list[str] = None,
    start_date: str = None,
    end_date: str = None,
    frequency_cap: int | None = None,
    frequency_cap_unit: str | None = None,
    budget_optimization: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Crea una Campaña en DV360.

    Args:
        client_id: ID del cliente (ej. 'vidal-vidal')
        name: nombre de la campaña. Usar nomenclatura: ES_PROD_{tipo}_{objetivo}_{periodo}
        goal: objetivo — AWARENESS | CONSIDERATION | ACTION
        kpi: KPI principal — CPA | CPC | CTR | VCPM | VIEWABILITY
        kpi_value: valor numerico del KPI (EUR para CPA/CPC, % para CTR/VIEWABILITY)
        creative_types: tipos de creatividad — ["DISPLAY"] por defecto
        start_date: fecha inicio YYYY-MM-DD
        end_date: fecha fin YYYY-MM-DD
        frequency_cap: max impresiones por usuario en el periodo (ej. 5)
        frequency_cap_unit: MINUTES | HOURS | DAYS | WEEKS | MONTHS
        budget_optimization: distribucion automatica de budget entre IOs
        dry_run: si True, muestra la accion sin ejecutarla
    """
    if creative_types is None:
        creative_types = ["DISPLAY"]

    advertiser_id = get_advertiser_id(client_id)

    body = build_campaign_body(
        advertiser_id=advertiser_id,
        name=name,
        goal=goal,
        kpi=kpi,
        kpi_value=kpi_value,
        creative_types=creative_types,
        start_date=start_date,
        end_date=end_date,
        frequency_cap=frequency_cap,
        frequency_cap_unit=frequency_cap_unit,
        frequency_cap_max_impressions=frequency_cap,
        budget_optimization=budget_optimization,
    )

    action_msg = (
        f"Crear Campaña '{name}' "
        f"(goal={goal}, kpi={kpi}, {start_date} → {end_date}) "
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
            "creative_types": creative_types,
            "start_date": start_date,
            "end_date": end_date,
            "frequency_cap": frequency_cap,
            "frequency_cap_unit": frequency_cap_unit,
            "advertiser_id": advertiser_id,
        },
        result=outcome,
        dry_run=dry_run,
    )

    if outcome["status"] == "ok":
        print(f"\n✅ Campaña creada. campaign_id: {outcome['data']['campaign_id']}")
        print("Siguiente paso: crear Insertion Order con este campaign_id.")
        print(
            f"  python scripts/dv360/insertion_orders/create_io.py "
            f"--client {client_id} "
            f"--campaign-id {outcome['data']['campaign_id']} ..."
        )

    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crea una Campaña en DV360.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Objetivos (--goal):
  AWARENESS       Reconocimiento de marca
  CONSIDERATION   Consideracion
  ACTION          Conversion / ventas

KPIs (--kpi):
  CPA             Coste por Adquisicion (requiere --kpi-value en EUR)
  CPC             Coste por Clic (requiere --kpi-value en EUR)
  CTR             Ratio de Clics (requiere --kpi-value en %)
  VCPM            CPM visible (requiere --kpi-value en EUR)
  VIEWABILITY     % de visibilidad (requiere --kpi-value en %)

Tipos de creatividad (--creative-types):
  DISPLAY         Display estandar (por defecto)
  VIDEO           Video
  AUDIO           Audio

Frecuencia (--frequency-cap-unit):
  MINUTES HOURS DAYS WEEKS MONTHS

Ejemplos:
  # Campaña de conversion con CPA objetivo 15 EUR, max 5 impactos/mes
  python scripts/dv360/campaigns/create_campaign.py \\
    --client vidal-vidal \\
    --name "ES_PROD_Display_Conversion_Q3_2026" \\
    --goal ACTION \\
    --kpi CPA \\
    --kpi-value 15.0 \\
    --start-date 2026-07-01 \\
    --end-date 2026-09-30 \\
    --frequency-cap 5 \\
    --frequency-cap-unit MONTHS \\
    --dry-run
        """,
    )
    parser.add_argument("--client", required=True, help="ID del cliente (ej. vidal-vidal)")
    parser.add_argument("--name", required=True, help="Nombre de la campaña. Nomenclatura: ES_PROD_{tipo}_{objetivo}_{periodo}")
    parser.add_argument("--goal", required=True, choices=["AWARENESS", "CONSIDERATION", "ACTION"], help="Objetivo de campaña")
    parser.add_argument("--kpi", required=True, choices=["CPA", "CPC", "CTR", "VCPM", "VIEWABILITY"], help="KPI principal")
    parser.add_argument("--kpi-value", type=float, default=None, help="Valor numerico del KPI (EUR para CPA/CPC, %% para CTR/VIEWABILITY)")
    parser.add_argument("--creative-types", nargs="+", default=["DISPLAY"], choices=["DISPLAY", "VIDEO", "AUDIO"], help="Tipos de creatividad (defecto: DISPLAY)")
    parser.add_argument("--start-date", required=True, help="Fecha inicio YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="Fecha fin YYYY-MM-DD")
    parser.add_argument("--frequency-cap", type=int, default=None, help="Max impresiones por usuario en el periodo")
    parser.add_argument("--frequency-cap-unit", choices=["MINUTES", "HOURS", "DAYS", "WEEKS", "MONTHS"], default=None, help="Unidad de tiempo del frequency cap")
    parser.add_argument("--budget-optimization", action="store_true", help="Activar optimizacion automatica de budget entre IOs")
    parser.add_argument("--dry-run", action="store_true", help="Simula la accion sin ejecutarla")

    args = parser.parse_args()

    result = create_campaign(
        client_id=args.client,
        name=args.name,
        goal=args.goal,
        kpi=args.kpi,
        kpi_value=args.kpi_value,
        creative_types=args.creative_types,
        start_date=args.start_date,
        end_date=args.end_date,
        frequency_cap=args.frequency_cap,
        frequency_cap_unit=args.frequency_cap_unit,
        budget_optimization=args.budget_optimization,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("ok", "dry_run", "cancelled") else 1)


if __name__ == "__main__":
    main()
