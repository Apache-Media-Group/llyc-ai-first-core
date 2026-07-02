"""
scripts/meta/campaigns/create_campaign_from_briefing.py
Fase 1: Crea Campaign + Ad Sets en Meta desde el JSON de briefing.
 
El Ad y el Creative son Fase 2 (create_ad_from_briefing.py, pendiente).
Sin Ad no hay entrega posible — zero riesgo de gasto aunque el Ad Set
quede en ACTIVE. Se mantiene PAUSED por seguridad.
 
El JSON lo genera read_briefing_from_workbook.py.
Contrato DEC_100: una confirmacion al inicio + dry-run previo obligatorio.
Owner: Alberto Gonzalez | Reviewer: Max | E2E: Jesus Lopez
 
Uso:
    # Paso 1: dry-run (obligatorio antes del real)
    python -m scripts.meta.campaigns.create_campaign_from_briefing \\
        --client vidal-vidal \\
        --briefing clients/vidal-vidal/briefings/meta_2026-07-01_1430.json \\
        --dry-run
 
    # Paso 2: ejecucion real (tras validar dry-run)
    python -m scripts.meta.campaigns.create_campaign_from_briefing \\
        --client vidal-vidal \\
        --briefing clients/vidal-vidal/briefings/meta_2026-07-01_1430.json
"""
from __future__ import annotations
 
import argparse
import json
import pathlib
import sys
 
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.exceptions import FacebookRequestError
 
from scripts.meta._common.auth import build_meta_client
from scripts._common.audit import log_action, confirm_action
 
PLATFORM = "meta"
SCRIPT = "create_campaign_from_briefing"
 
 
# --- CARGA DEL BRIEFING -------------------------------------------------------
 
def load_briefing(briefing_path: str) -> dict:
    p = pathlib.Path(briefing_path)
    if not p.exists():
        raise FileNotFoundError(f"Briefing no encontrado: {briefing_path}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)
 
 
# --- CREACION: CAMPAIGN -------------------------------------------------------
 
def create_campaign(ad_account, camp: dict, dry_run: bool) -> dict:
    """Crea la Campaign en PAUSED."""
    params = {
        Campaign.Field.name: camp["name"],
        Campaign.Field.objective: camp["objective"],
        Campaign.Field.status: Campaign.Status.paused,
        Campaign.Field.special_ad_categories: camp.get("special_ad_categories", []),
        Campaign.Field.buying_type: camp.get("buying_type", "AUCTION"),
    }
 
    if camp.get("cbo_enabled") and camp.get("campaign_budget_cents"):
        params[Campaign.Field.daily_budget] = camp["campaign_budget_cents"]
 
    if dry_run:
        return {"status": "dry_run", "data": {"params": params}}
 
    try:
        result = ad_account.create_campaign(params=params)
        return {"status": "ok", "data": {"campaign_id": result[Campaign.Field.id]}}
    except FacebookRequestError as e:
        return {"status": "error", "error": f"Meta API {e.api_error_code()}: {e.api_error_message()}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
 
 
# --- CREACION: AD SET ---------------------------------------------------------
 
def create_ad_set(ad_account, campaign_id: str, adset: dict, dry_run: bool) -> dict:
    """Crea el Ad Set vinculado a la Campaign, en PAUSED."""
    targeting = {
        "geo_locations": adset["targeting"]["geo_locations"],
        "age_min": adset["targeting"].get("age_min", 18),
        "age_max": adset["targeting"].get("age_max", 65),
    }
    if adset["targeting"].get("genders"):
        targeting["genders"] = adset["targeting"]["genders"]
    if adset["targeting"].get("custom_audiences"):
        targeting["custom_audiences"] = adset["targeting"]["custom_audiences"]
 
    params = {
        AdSet.Field.name: adset["name"],
        AdSet.Field.campaign_id: campaign_id,
        AdSet.Field.status: AdSet.Status.paused,
        AdSet.Field.optimization_goal: adset["optimization_goal"],
        AdSet.Field.billing_event: adset["billing_event"],
        AdSet.Field.bid_strategy: adset["bid_strategy"],
        AdSet.Field.daily_budget: adset["daily_budget_cents"],
        AdSet.Field.targeting: targeting,
        AdSet.Field.attribution_spec: adset["targeting"].get("attribution_spec", [
            {"event_type": "CLICK_THROUGH", "window_days": 7},
            {"event_type": "VIEW_THROUGH", "window_days": 1},
        ]),
    }
 
    if adset.get("start_time"):
        params[AdSet.Field.start_time] = adset["start_time"]
    if adset.get("end_time"):
        params[AdSet.Field.end_time] = adset["end_time"]
    if adset.get("bid_amount_micros"):
        params[AdSet.Field.bid_amount] = adset["bid_amount_micros"]
    if adset.get("pixel_id") and adset["pixel_id"] != "PENDIENTE":
        params[AdSet.Field.promoted_object] = {
            "pixel_id": adset["pixel_id"],
            "custom_event_type": "PURCHASE",
        }
 
    if dry_run:
        return {"status": "dry_run", "data": {"params": params}}
 
    try:
        result = ad_account.create_ad_set(params=params)
        return {"status": "ok", "data": {"ad_set_id": result[AdSet.Field.id]}}
    except FacebookRequestError as e:
        return {"status": "error", "error": f"Meta API {e.api_error_code()}: {e.api_error_message()}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
 
 
# --- ORQUESTADOR --------------------------------------------------------------
 
def run(client_id: str, briefing_path: str, dry_run: bool) -> None:
    briefing = load_briefing(briefing_path)
    camp = briefing["campaign"]
    ad_sets = briefing["ad_sets"]
 
    print("\n" + "=" * 60)
    print(f"CREAR CAMPANA META (Fase 1) — {client_id}")
    print(f"Briefing : {briefing_path}")
    print(f"Modo     : {'DRY-RUN' if dry_run else 'PRODUCCION'}")
    print("=" * 60)
    print(f"  Campaign : {camp['name']}")
    print(f"  Objetivo : {camp['objective']}")
    print(f"  Ad Sets  : {len(ad_sets)}")
    print("  Status   : PAUSED")
    print("  Fase 2   : Ads + Creatividades — pendiente (create_ad_from_briefing.py)")
    print("=" * 60 + "\n")
 
    if not dry_run:
        msg = (
            f"Crear Campaign '{camp['name']}' + {len(ad_sets)} Ad Set(s) "
            f"en Meta Ad Account de {client_id} (PAUSED, sin Ad, sin gasto)"
        )
        if not confirm_action(msg, dry_run=False):
            sys.exit(0)
 
    ad_account = build_meta_client(client_id)
    created = {"campaign_id": None, "ad_sets": []}
 
    # --- Campaign
    print("[1] Campaign...")
    camp_result = create_campaign(ad_account, camp, dry_run)
    log_action(PLATFORM, SCRIPT, "create_campaign", client_id,
               args={"campaign_name": camp["name"]}, result=camp_result, dry_run=dry_run)
 
    if camp_result["status"] not in ("ok", "dry_run"):
        print(f"  ERROR: {camp_result.get('error')}")
        sys.exit(1)
 
    campaign_id = camp_result["data"].get("campaign_id", "DRY_RUN_CAMPAIGN_ID")
    created["campaign_id"] = campaign_id
    print(f"  OK — campaign_id: {campaign_id}")
 
    # --- Ad Sets
    for i, adset in enumerate(ad_sets, 1):
        print(f"\n[2.{i}] Ad Set '{adset['name']}'...")
        adset_result = create_ad_set(ad_account, campaign_id, adset, dry_run)
        log_action(PLATFORM, SCRIPT, "create_ad_set", client_id,
                   args={"ad_set_name": adset["name"], "campaign_id": campaign_id},
                   result=adset_result, dry_run=dry_run)
 
        if adset_result["status"] not in ("ok", "dry_run"):
            print(f"  ERROR: {adset_result.get('error')}")
            sys.exit(1)
 
        ad_set_id = adset_result["data"].get("ad_set_id", f"DRY_RUN_ADSET_{i}_ID")
        print(f"  OK — ad_set_id: {ad_set_id}")
        created["ad_sets"].append({"ad_set_id": ad_set_id})
 
    # --- Resumen
    print("\n" + "=" * 60)
    print(f"{'[DRY-RUN] ' if dry_run else ''}FASE 1 COMPLETADA")
    print(f"  campaign_id : {created['campaign_id']}")
    for i, ar in enumerate(created["ad_sets"], 1):
        print(f"  ad_set_{i}_id : {ar['ad_set_id']}")
    print("  status      : PAUSED — sin Ad, sin entrega, sin gasto")
    print("  Siguiente   : Fase 2 — subir creatividades y crear Ads")
    print("=" * 60 + "\n")
 
 
# --- ENTRY POINT --------------------------------------------------------------
 
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fase 1: Crea Campaign + Ad Sets en Meta (sin Ad ni Creative)."
    )
    parser.add_argument("--client", required=True, help="ID del cliente (ej. vidal-vidal)")
    parser.add_argument("--briefing", required=True, help="Ruta al JSON generado por read_briefing_from_workbook.py")
    parser.add_argument("--dry-run", action="store_true", help="Simula sin ejecutar")
    args = parser.parse_args()
 
    run(client_id=args.client, briefing_path=args.briefing, dry_run=args.dry_run)