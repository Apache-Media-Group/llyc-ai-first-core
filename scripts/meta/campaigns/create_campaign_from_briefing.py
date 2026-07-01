"""
scripts/meta/campaigns/create_campaign_from_briefing.py
Crea Campaign + Ad Sets + Ads en Meta desde el JSON de briefing.
 
El JSON lo genera read_briefing_from_workbook.py.
Todo se crea en status=PAUSED — sin entrega, sin gasto.
Limpieza manual posterior por Jesus Lopez.
 
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
from datetime import datetime, timezone
 
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.exceptions import FacebookRequestError
 
from scripts.meta._common.auth import build_meta_client, get_ad_account_id
from scripts._common.audit import log_action, confirm_action
 
PLATFORM = "meta"
SCRIPT = "create_campaign_from_briefing"
 
 
# --- CARGA DEL BRIEFING -------------------------------------------------------
 
def load_briefing(briefing_path: str) -> dict:
    p = pathlib.Path(briefing_path)
    if not p.exists():
        raise FileNotFoundError(f"Briefing no encontrado: {briefing_path}")
    with open(p, encoding="utf-8") as f:
        briefing = json.load(f)
    # Marcar como ejecucion real al cargar
    briefing["dry_run"] = False
    return briefing
 
 
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
 
    # CBO: budget a nivel de campana
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
 
 
# --- CREACION: AD CREATIVE ----------------------------------------------------
 
def create_creative(ad_account, ad_account_id: str, ad: dict, page_id: str, dry_run: bool) -> dict:
    """Crea el AdCreative. Devuelve creative_id o placeholder en dry-run."""
    creative_type = ad.get("creative_type", "SINGLE_IMAGE")
 
    if creative_type == "SINGLE_IMAGE":
        object_story_spec = {
            "page_id": page_id,
            "link_data": {
                "link": ad["link_url"],
                "message": ad["ad_message"],
                "call_to_action": {"type": ad["call_to_action"]},
                "image_hash": ad.get("image_hash", "PENDIENTE"),
            },
        }
        if ad.get("ad_title"):
            object_story_spec["link_data"]["name"] = ad["ad_title"]
        if ad.get("ad_description"):
            object_story_spec["link_data"]["description"] = ad["ad_description"]
        if ad.get("tracking_url"):
            object_story_spec["link_data"]["link"] = ad["tracking_url"]
 
    elif creative_type == "VIDEO":
        object_story_spec = {
            "page_id": page_id,
            "video_data": {
                "video_id": ad.get("video_id", "PENDIENTE"),
                "message": ad["ad_message"],
                "call_to_action": {
                    "type": ad["call_to_action"],
                    "value": {"link": ad["link_url"]},
                },
            },
        }
 
    else:
        return {"status": "error", "error": f"creative_type '{creative_type}' no soportado aun. Usar SINGLE_IMAGE o VIDEO."}
 
    creative_params = {
        AdCreative.Field.name: f"{ad['ad_name']}_CR",
        AdCreative.Field.object_story_spec: object_story_spec,
    }
 
    if dry_run:
        return {"status": "dry_run", "data": {"creative_params": creative_params}}
 
    try:
        creative = ad_account.create_ad_creative(params=creative_params)
        return {"status": "ok", "data": {"creative_id": creative[AdCreative.Field.id]}}
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
 
    # Genders: solo incluir si no es ALL
    if adset["targeting"].get("genders"):
        targeting["genders"] = adset["targeting"]["genders"]
 
    # Custom audiences
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
 
    # start/end time
    if adset.get("start_time"):
        params[AdSet.Field.start_time] = adset["start_time"]
    if adset.get("end_time"):
        params[AdSet.Field.end_time] = adset["end_time"]
 
    # Bid amount (solo para BID_CAP y COST_CAP)
    if adset.get("bid_amount_micros"):
        params[AdSet.Field.bid_amount] = adset["bid_amount_micros"]
 
    # Pixel para conversiones
    if adset.get("pixel_id") and adset["pixel_id"] != "PENDIENTE":
        params[AdSet.Field.promoted_object] = {
            "pixel_id": adset["pixel_id"],
            "custom_event_type": "PURCHASE",
        }
 
    # Placements: AUTOMATIC no requiere parametros extra (Advantage+ Placements por defecto)
    # MANUAL requiere publisher_platforms — diferir a fase siguiente
 
    if dry_run:
        return {"status": "dry_run", "data": {"params": params}}
 
    try:
        result = ad_account.create_ad_set(params=params)
        return {"status": "ok", "data": {"ad_set_id": result[AdSet.Field.id]}}
    except FacebookRequestError as e:
        return {"status": "error", "error": f"Meta API {e.api_error_code()}: {e.api_error_message()}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
 
 
# --- CREACION: AD -------------------------------------------------------------
 
def create_ad(ad_account, ad_set_id: str, creative_id: str, ad: dict, dry_run: bool) -> dict:
    """Crea el Ad vinculado al Ad Set, en PAUSED."""
    params = {
        Ad.Field.name: ad["ad_name"],
        Ad.Field.adset_id: ad_set_id,
        Ad.Field.status: Ad.Status.paused,
        Ad.Field.creative: {"creative_id": creative_id},
    }
 
    if dry_run:
        return {"status": "dry_run", "data": {"params": params}}
 
    try:
        result = ad_account.create_ad(params=params)
        return {"status": "ok", "data": {"ad_id": result[Ad.Field.id]}}
    except FacebookRequestError as e:
        return {"status": "error", "error": f"Meta API {e.api_error_code()}: {e.api_error_message()}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
 
 
# --- ORQUESTADOR --------------------------------------------------------------
 
def run(client_id: str, briefing_path: str, dry_run: bool) -> None:
    briefing = load_briefing(briefing_path)
    camp = briefing["campaign"]
    ad_sets = briefing["ad_sets"]
 
    n_ads_total = sum(len(a["ads"]) for a in ad_sets)
 
    print("\n" + "=" * 60)
    print(f"CREAR CAMPANA META — {client_id}")
    print(f"Briefing : {briefing_path}")
    print(f"Modo     : {'DRY-RUN' if dry_run else 'PRODUCCION'}")
    print("=" * 60)
    print(f"  Campaign  : {camp['name']}")
    print(f"  Objetivo  : {camp['objective']}")
    print(f"  Ad Sets   : {len(ad_sets)}")
    print(f"  Ads total : {n_ads_total}")
    print("  Status    : PAUSED (sin entrega, sin gasto)")
    print("=" * 60 + "\n")
 
    if not dry_run:
        msg = (
            f"Crear Campaign '{camp['name']}' + {len(ad_sets)} Ad Set(s) "
            f"+ {n_ads_total} Ad(s) en Meta Ad Account de {client_id} (todo PAUSED)"
        )
        if not confirm_action(msg, dry_run=False):
            sys.exit(0)
 
    ad_account = build_meta_client(client_id)
    ad_account_id = get_ad_account_id(client_id)
    page_id_default = ad_sets[0]["ads"][0].get("page_id", "PENDIENTE") if ad_sets else "PENDIENTE"
 
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
 
    # --- Ad Sets y Ads
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
 
        adset_record = {"ad_set_id": ad_set_id, "ads": []}
 
        for j, ad in enumerate(adset["ads"], 1):
            page_id = ad.get("page_id", page_id_default)
 
            print(f"\n  [3.{i}.{j}] Creative '{ad['ad_name']}'...")
            creative_result = create_creative(ad_account, ad_account_id, ad, page_id, dry_run)
            log_action(PLATFORM, SCRIPT, "create_creative", client_id,
                       args={"ad_name": ad["ad_name"]}, result=creative_result, dry_run=dry_run)
 
            if creative_result["status"] not in ("ok", "dry_run"):
                print(f"    ERROR: {creative_result.get('error')}")
                sys.exit(1)
 
            creative_id = creative_result["data"].get("creative_id", f"DRY_RUN_CREATIVE_{i}_{j}_ID")
            print(f"    OK — creative_id: {creative_id}")
 
            print(f"  [3.{i}.{j}] Ad '{ad['ad_name']}'...")
            ad_result = create_ad(ad_account, ad_set_id, creative_id, ad, dry_run)
            log_action(PLATFORM, SCRIPT, "create_ad", client_id,
                       args={"ad_name": ad["ad_name"], "ad_set_id": ad_set_id},
                       result=ad_result, dry_run=dry_run)
 
            if ad_result["status"] not in ("ok", "dry_run"):
                print(f"    ERROR: {ad_result.get('error')}")
                sys.exit(1)
 
            ad_id = ad_result["data"].get("ad_id", f"DRY_RUN_AD_{i}_{j}_ID")
            print(f"    OK — ad_id: {ad_id}")
            adset_record["ads"].append({"ad_id": ad_id, "creative_id": creative_id})
 
        created["ad_sets"].append(adset_record)
 
    # --- Resumen final
    print("\n" + "=" * 60)
    print(f"{'[DRY-RUN] ' if dry_run else ''}COMPLETADO")
    print(f"  campaign_id : {created['campaign_id']}")
    for i, ar in enumerate(created["ad_sets"], 1):
        print(f"  ad_set_{i}_id : {ar['ad_set_id']}")
        for j, adr in enumerate(ar["ads"], 1):
            print(f"    ad_{i}_{j}_id  : {adr['ad_id']}")
    if not dry_run:
        print("  status      : PAUSED — sin entrega ni gasto")
        print("  Limpieza    : manual por Jesus Lopez")
    print("=" * 60 + "\n")
 
 
# --- ENTRY POINT --------------------------------------------------------------
 
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crea campana Meta desde JSON de briefing.")
    parser.add_argument("--client", required=True, help="ID del cliente (ej. vidal-vidal)")
    parser.add_argument("--briefing", required=True, help="Ruta al JSON generado por read_briefing_from_workbook.py")
    parser.add_argument("--dry-run", action="store_true", help="Simula sin ejecutar")
    args = parser.parse_args()
 
    run(client_id=args.client, briefing_path=args.briefing, dry_run=args.dry_run)