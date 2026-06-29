"""
scripts/dv360/create_campaign_from_briefing.py
Orquestador de creación de campaña DV360 desde un briefing JSON.

Ejecuta la secuencia completa con UNA SOLA confirmación:
  1. create_campaign
  2. Por cada IO: create_io
  3. Por cada LI del IO: create_line_item
  4. activate_line_item (opcional, --activate)
  5. activate_io (opcional, --activate)

Uso:
    python scripts/dv360/create_campaign_from_briefing.py \\
        --client vaillant \\
        --briefing scripts/dv360/briefings/vaillant_2026q3.json \\
        [--dry-run] \\
        [--activate]

El briefing JSON sigue el schema de briefing_template.json.

DEC_022: el sistema es read-only en runtime. Este script es operativa humana.
DEC_069: escritura solo vía scripts manuales con guardrails+dry-run+confirmación+audit.
DEC_086: SA llyc-ops-writer-sa. NUNCA llyc-agents-sa.
DEC_092: guardrails de presupuesto y bid hardcoded, override con --reason.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.dv360._common.audit import log_action, confirm_action
from scripts.dv360.campaigns.create_campaign import create_campaign
from scripts.dv360.insertion_orders.create_io import create_io
from scripts.dv360.insertion_orders.activate_io import activate_io
from scripts.dv360.line_items.create_line_item import create_line_item
from scripts.dv360.line_items.activate_line_item import activate_line_item

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


def _require(d: dict, key: str, context: str = "") -> object:
    """Extrae un campo obligatorio del dict o lanza ValueError."""
    if key not in d or d[key] is None:
        raise ValueError(f"Campo obligatorio '{key}' faltante en {context}")
    return d[key]


def run_orchestrator(briefing: dict, dry_run: bool = False, activate: bool = False, existing_campaign_id: str = None) -> dict:
    """
    Ejecuta la secuencia completa de creación de campaña DV360.
    Devuelve un dict con el resultado de cada paso.
    """
    client_id = _require(briefing, "client", "briefing raiz")
    reason = briefing.get("reason")
    camp_cfg = _require(briefing, "campaign", "briefing raiz")
    ios_cfg = _require(briefing, "insertion_orders", "briefing raiz")

    results = {
        "client": client_id,
        "dry_run": dry_run,
        "campaign": None,
        "insertion_orders": [],
        "errors": [],
    }
    # ── 1. Campaign ────────────────────────────────────────────────────────────────────────────
    if existing_campaign_id:
        log.info(f"[1/N] Usando Campaign existente: {existing_campaign_id}")
        campaign_id = existing_campaign_id
        results["campaign"] = {"status": "skipped", "data": {"campaign_id": existing_campaign_id}}
    else:
        log.info(f"[1/N] Creando Campaign...")
        camp_result = create_campaign(
            client_id=client_id,
            name=_require(camp_cfg, "name", "campaign"),
            goal=_require(camp_cfg, "goal", "campaign"),
            kpi=_require(camp_cfg, "kpi", "campaign"),
            kpi_value=camp_cfg.get("kpi_value"),
            start_date=_require(camp_cfg, "start_date", "campaign"),
            end_date=_require(camp_cfg, "end_date", "campaign"),
            frequency_cap=camp_cfg.get("frequency_cap"),
            frequency_cap_unit=camp_cfg.get("frequency_cap_unit"),
            dry_run=dry_run,
            skip_confirm=True,
        )
        results["campaign"] = camp_result
        if camp_result["status"] not in ("ok", "dry_run"):
            results["errors"].append(f"Campaign fallo: {camp_result.get('error')}")
            return results
        campaign_id = camp_result["data"].get("campaign_id", "DRY_RUN_CAMPAIGN_ID")
        log.info(f"  Campaign: {campaign_id}")
    campaign_id = existing_campaign_id or camp_result["data"].get("campaign_id", "DRY_RUN_CAMPAIGN_ID")
    log.info(f"  ✅ Campaign: {campaign_id}")

    # ── 2. Insertion Orders + Line Items ───────────────────────────────────────
    for io_idx, io_cfg in enumerate(ios_cfg):
        io_name = _require(io_cfg, "name", f"IO[{io_idx}]")
        log.info(f"[IO {io_idx+1}/{len(ios_cfg)}] Creando IO '{io_name}'...")

        io_result = create_io(
            client_id=client_id,
            campaign_id=campaign_id,
            name=io_name,
            budget_eur=_require(io_cfg, "budget_eur", f"IO '{io_name}'"),
            budget_unit=io_cfg.get("budget_unit", "AMOUNT"),
            max_budget_eur=io_cfg.get("max_budget_eur") or 30000.0,
            start_date=io_cfg.get("start_date", camp_cfg["start_date"]),
            end_date=io_cfg.get("end_date", camp_cfg["end_date"]),
            pacing=io_cfg.get("pacing", "EVEN"),
            pacing_period=io_cfg.get("pacing_period", "DAILY"),
            kpi_type=_require(io_cfg, "kpi_type", f"IO '{io_name}'"),
            kpi_value=str(_require(io_cfg, "kpi_value", f"IO '{io_name}'")),
            optimization_objective=io_cfg.get("optimization_objective", "CONVERSIONS"),
            automation_type=io_cfg.get("automation_type", "NONE"),
            performance_goal_value_eur=io_cfg.get("performance_goal_value_eur"),
            frequency_cap=io_cfg.get("frequency_cap"),
            frequency_cap_unit=io_cfg.get("frequency_cap_unit"),
            reason=reason,
            dry_run=dry_run,
            skip_confirm=True,
        )

        io_entry = {"io": io_result, "line_items": []}
        results["insertion_orders"].append(io_entry)

        if io_result["status"] not in ("ok", "dry_run"):
            results["errors"].append(f"IO '{io_name}' falló: {io_result.get('error')}")
            log.error(f"  ❌ IO '{io_name}' falló — saltando sus LIs")
            continue

        io_id = io_result["data"].get("io_id", "DRY_RUN_IO_ID")
        log.info(f"  ✅ IO: {io_id}")

        # ── 3. Line Items del IO ───────────────────────────────────────────────
        lis_cfg = io_cfg.get("line_items", [])
        for li_idx, li_cfg in enumerate(lis_cfg):
            li_name = _require(li_cfg, "name", f"IO '{io_name}' LI[{li_idx}]")
            log.info(f"  [LI {li_idx+1}/{len(lis_cfg)}] Creando LI '{li_name}'...")

            li_result = create_line_item(
                client_id=client_id,
                campaign_id=campaign_id,
                io_id=io_id,
                name=li_name,
                li_type=li_cfg.get("li_type", "DISPLAY"),
                budget_eur=_require(li_cfg, "budget_eur", f"LI '{li_name}'"),
                max_budget_eur=li_cfg.get("max_budget_eur") or 5000.0,
                start_date=li_cfg.get("start_date", io_cfg.get("start_date", camp_cfg["start_date"])),
                end_date=li_cfg.get("end_date", io_cfg.get("end_date", camp_cfg["end_date"])),
                bid_strategy=li_cfg.get("bid_strategy", "FIXED"),
                bid_eur=li_cfg.get("bid_eur"),
                bid_max_eur=li_cfg.get("bid_max_eur"),
                max_bid_eur_guardrail=li_cfg.get("max_bid_guardrail") or 50.0,                
                target_cpa_eur=li_cfg.get("target_cpa_eur"),
                target_cpv_eur=li_cfg.get("target_cpv_eur"),
                frequency_cap=li_cfg.get("frequency_cap"),
                frequency_cap_unit=li_cfg.get("frequency_cap_unit"),
                creative_ids=li_cfg.get("creative_ids", []),
                audience_expansion=li_cfg.get("audience_expansion", False),
                youtube_target_frequency=li_cfg.get("youtube_target_frequency"),
                content_labels_exclude=li_cfg.get("content_labels_exclude"),
                brand_safety_exclude=li_cfg.get("brand_safety_exclude"),
                sensitive_categories_exclude=li_cfg.get("sensitive_categories_exclude"),
                keyword_includes=li_cfg.get("keyword_includes"),
                keyword_excludes=li_cfg.get("keyword_excludes"),
                url_includes=li_cfg.get("url_includes"),
                url_excludes=li_cfg.get("url_excludes"),
                iab_categories=li_cfg.get("iab_categories"),
                environment=li_cfg.get("environment"),
                viewability_target=li_cfg.get("viewability_target"),
                positions=li_cfg.get("positions"),
                audience_list_ids=li_cfg.get("audience_list_ids"),
                audience_inmarket=li_cfg.get("audience_inmarket"),
                audience_affinity=li_cfg.get("audience_affinity"),
                genders=li_cfg.get("genders"),
                age_ranges=li_cfg.get("age_ranges"),
                parental_status=li_cfg.get("parental_status"),
                geo_regions=li_cfg.get("geo_regions"),
                geo_cities=li_cfg.get("geo_cities"),
                geo_zip_codes=li_cfg.get("geo_zip_codes"),
                geo_exclude=li_cfg.get("geo_exclude"),
                language_codes=li_cfg.get("language_codes"),
                daypart_matrix=json.loads(li_cfg["daypart_matrix"]) if li_cfg.get("daypart_matrix") else None,
                device_types=li_cfg.get("device_types"),
                operating_systems=li_cfg.get("operating_systems"),
                browsers=li_cfg.get("browsers"),
                connection_speeds=li_cfg.get("connection_speeds"),
                youtube_content_categories=li_cfg.get("youtube_content_categories"),
                youtube_channel_ids=li_cfg.get("youtube_channel_ids"),
                youtube_video_ids=li_cfg.get("youtube_video_ids"),
                reason=reason,
                dry_run=dry_run,
                skip_confirm=True,
            )
            io_entry["line_items"].append(li_result)

            if li_result["status"] not in ("ok", "partial", "dry_run"):
                results["errors"].append(f"LI '{li_name}' falló: {li_result.get('error')}")
                log.error(f"    ❌ LI '{li_name}' falló")
                continue

            li_id = li_result["data"].get("line_item_id", "DRY_RUN_LI_ID")
            log.info(f"    ✅ LI: {li_id}")

            # ── 4. Activar LI (opcional) ───────────────────────────────────────
            if activate and li_result["status"] == "ok":
                log.info(f"    Activando LI {li_id}...")
                act_result = activate_line_item(
                    client_id=client_id,
                    line_item_id=li_id,
                    dry_run=dry_run,
                    skip_confirm=True,
                )
                io_entry["line_items"][-1]["activate"] = act_result
                log.info(f"    ✅ LI activado")

        # ── 5. Activar IO (opcional) ───────────────────────────────────────────
        if activate and io_result["status"] == "ok":
            log.info(f"  Activando IO {io_id}...")
            act_io_result = activate_io(
                client_id=client_id,
                io_id=io_id,
                dry_run=dry_run,
                skip_confirm=True,
            )
            io_entry["activate_io"] = act_io_result
            log.info(f"  ✅ IO activado")

    results["status"] = "ok" if not results["errors"] else "partial"
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Orquestador DV360 — crea Campaign+IOs+LIs desde un briefing JSON con una sola confirmación.",
        epilog="Ejemplo: python scripts/dv360/create_campaign_from_briefing.py --client vaillant --briefing briefing.json --dry-run"
    )
    parser.add_argument("--client", required=True, help="ID del cliente")
    parser.add_argument("--briefing", required=True, help="Path al fichero JSON del briefing")
    parser.add_argument("--dry-run", action="store_true", help="Simula sin ejecutar")
    parser.add_argument("--activate", action="store_true", help="Activa LIs e IOs tras crearlos")
    parser.add_argument("--campaign-id", default=None, help="ID de campaña existente — salta la creacion")
    args = parser.parse_args()

    # Cargar briefing
    briefing_path = Path(args.briefing)
    if not briefing_path.exists():
        print(f"ERROR: fichero de briefing no encontrado: {briefing_path}")
        sys.exit(1)

    briefing = json.loads(briefing_path.read_text(encoding="utf-8"))
    briefing["client"] = args.client  # --client tiene precedencia sobre el JSON

    # Resumen antes de confirmar
    camp = briefing.get("campaign", {})
    ios = briefing.get("insertion_orders", [])
    total_lis = sum(len(io.get("line_items", [])) for io in ios)
    total_budget = sum(io.get("budget_eur", 0) for io in ios)

    print(f"\n{'='*60}")
    print(f"BRIEFING: {briefing_path.name}")
    print(f"Cliente:  {args.client}")
    print(f"Campaña:  {camp.get('name')} ({camp.get('start_date')} → {camp.get('end_date')})")
    print(f"IOs:      {len(ios)}")
    print(f"LIs:      {total_lis}")
    print(f"Budget:   {total_budget:.2f} EUR")
    print(f"Dry-run:  {args.dry_run}")
    print(f"Activar:  {args.activate}")
    print(f"{'='*60}\n")

    if not confirm_action(
        f"Ejecutar secuencia completa: 1 Campaign + {len(ios)} IOs + {total_lis} LIs",
        dry_run=args.dry_run
    ):
        print("Cancelado.")
        sys.exit(0)

    result = run_orchestrator(briefing, dry_run=args.dry_run, activate=args.activate, existing_campaign_id=args.campaign_id)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result.get("errors"):
        print(f"\n⚠️  {len(result['errors'])} errores:")
        for e in result["errors"]:
            print(f"  - {e}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()