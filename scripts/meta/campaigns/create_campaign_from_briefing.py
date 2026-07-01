"""
scripts/meta/campaigns/create_campaign_from_briefing.py
Crea una campana completa en Meta desde un briefing estructurado.

Flujo: 1 Campaign + 1 Ad Set + 1 Ad, todo en status=PAUSED.
Estado PAUSED en Meta = sin entrega, sin gasto. Limpieza manual posterior.

Contrato DEC_100: una confirmacion al inicio con dry-run completo previo.
Owner: Alberto Gonzalez | Reviewer: Max | E2E: Jesus Lopez

Uso:
    python -m scripts.meta.campaigns.create_campaign_from_briefing \
        --client vidal-vidal \
        --briefing clients/vidal-vidal/briefings/prospecting_adv_plus.json \
        [--dry-run]
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

from scripts.meta._common.auth import build_meta_client, get_ad_account_id
from scripts._common.audit import log_action, confirm_action

PLATFORM = "meta"
SCRIPT = "create_campaign_from_briefing"


# --- LECTURA DE BRIEFING ------------------------------------------------------

def load_briefing(briefing_path: str) -> dict:
    p = pathlib.Path(briefing_path)
    if not p.exists():
        raise FileNotFoundError(f"Briefing no encontrado: {briefing_path}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# --- CREACION DE ENTIDADES ----------------------------------------------------

def create_campaign(ad_account, briefing: dict, dry_run: bool) -> dict:
    """Crea la Campaign en status PAUSED."""
    params = {
        Campaign.Field.name: briefing["campaign_name"],
        Campaign.Field.objective: briefing["objective"],
        Campaign.Field.status: Campaign.Status.paused,
        Campaign.Field.special_ad_categories: briefing.get("special_ad_categories", []),
    }
    if dry_run:
        return {"status": "ok", "data": {"dry_run": True, "params": params}}

    campaign = ad_account.create_campaign(params=params)
    return {"status": "ok", "data": {"campaign_id": campaign[Campaign.Field.id]}}


def create_ad_set(ad_account, campaign_id: str, briefing: dict, dry_run: bool) -> dict:
    """Crea el Ad Set vinculado a la Campaign, en status PAUSED."""
    ad_set_briefing = briefing["ad_set"]
    params = {
        AdSet.Field.name: ad_set_briefing["name"],
        AdSet.Field.campaign_id: campaign_id,
        AdSet.Field.status: AdSet.Status.paused,
        AdSet.Field.billing_event: ad_set_briefing.get("billing_event", "IMPRESSIONS"),
        AdSet.Field.optimization_goal: ad_set_briefing["optimization_goal"],
        AdSet.Field.bid_strategy: ad_set_briefing.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP"),
        AdSet.Field.daily_budget: int(ad_set_briefing["daily_budget_eur"] * 100),  # en centimos
        AdSet.Field.targeting: ad_set_briefing["targeting"],
        AdSet.Field.start_time: ad_set_briefing.get("start_time"),
    }
    if dry_run:
        return {"status": "ok", "data": {"dry_run": True, "params": params}}

    ad_set = ad_account.create_ad_set(params=params)
    return {"status": "ok", "data": {"ad_set_id": ad_set[AdSet.Field.id]}}


def create_ad(ad_account, ad_set_id: str, briefing: dict, dry_run: bool) -> dict:
    """Crea el Ad vinculado al Ad Set, en status PAUSED."""
    ad_briefing = briefing["ad"]

    creative_params = {
        AdCreative.Field.name: ad_briefing["creative_name"],
        AdCreative.Field.object_story_spec: ad_briefing["object_story_spec"],
    }
    if dry_run:
        ad_params = {
            Ad.Field.name: ad_briefing["name"],
            Ad.Field.adset_id: ad_set_id,
            Ad.Field.status: Ad.Status.paused,
            Ad.Field.creative: "(dry-run, no creative_id)",
        }
        return {"status": "ok", "data": {"dry_run": True, "creative_params": creative_params, "ad_params": ad_params}}

    creative = ad_account.create_ad_creative(params=creative_params)
    creative_id = creative[AdCreative.Field.id]

    ad_params = {
        Ad.Field.name: ad_briefing["name"],
        Ad.Field.adset_id: ad_set_id,
        Ad.Field.status: Ad.Status.paused,
        Ad.Field.creative: {"creative_id": creative_id},
    }
    ad = ad_account.create_ad(params=ad_params)
    return {"status": "ok", "data": {"ad_id": ad[Ad.Field.id], "creative_id": creative_id}}


# --- ORQUESTADOR --------------------------------------------------------------

def run(client_id: str, briefing_path: str, dry_run: bool) -> None:
    briefing = load_briefing(briefing_path)

    print("\n" + "=" * 60)
    print(f"CREAR CAMPANA META — {client_id}")
    print(f"Briefing: {briefing_path}")
    print(f"Modo: {'DRY-RUN' if dry_run else 'PRODUCCION'}")
    print("=" * 60)
    print(f"  Campaign : {briefing['campaign_name']}")
    print(f"  Objetivo : {briefing['objective']}")
    print(f"  Ad Set   : {briefing['ad_set']['name']}")
    print(f"  Budget   : {briefing['ad_set']['daily_budget_eur']} EUR/dia")
    print(f"  Ad       : {briefing['ad']['name']}")
    print("  Status   : PAUSED (sin entrega, sin gasto)")
    print("=" * 60 + "\n")

    # DEC_100: una sola confirmacion al inicio con dry-run previo obligatorio
    if not dry_run:
        msg = f"Crear Campaign + Ad Set + Ad en Meta Ad Account de {client_id} (todo PAUSED)"
        if not confirm_action(msg, dry_run=False):
            sys.exit(0)

    ad_account = build_meta_client(client_id)

    # --- Campaign
    print("[1/3] Campaign...")
    campaign_result = create_campaign(ad_account, briefing, dry_run)
    log_action(PLATFORM, SCRIPT, "create_campaign", client_id,
               args={"campaign_name": briefing["campaign_name"]},
               result=campaign_result, dry_run=dry_run)

    if campaign_result["status"] != "ok":
        print(f"ERROR en Campaign: {campaign_result}")
        sys.exit(1)

    campaign_id = campaign_result["data"].get("campaign_id", "DRY_RUN_ID")
    print(f"    OK — campaign_id: {campaign_id}")

    # --- Ad Set
    print("[2/3] Ad Set...")
    ad_set_result = create_ad_set(ad_account, campaign_id, briefing, dry_run)
    log_action(PLATFORM, SCRIPT, "create_ad_set", client_id,
               args={"ad_set_name": briefing["ad_set"]["name"], "campaign_id": campaign_id},
               result=ad_set_result, dry_run=dry_run)

    if ad_set_result["status"] != "ok":
        print(f"ERROR en Ad Set: {ad_set_result}")
        sys.exit(1)

    ad_set_id = ad_set_result["data"].get("ad_set_id", "DRY_RUN_ID")
    print(f"    OK — ad_set_id: {ad_set_id}")

    # --- Ad
    print("[3/3] Ad...")
    ad_result = create_ad(ad_account, ad_set_id, briefing, dry_run)
    log_action(PLATFORM, SCRIPT, "create_ad", client_id,
               args={"ad_name": briefing["ad"]["name"], "ad_set_id": ad_set_id},
               result=ad_result, dry_run=dry_run)

    if ad_result["status"] != "ok":
        print(f"ERROR en Ad: {ad_result}")
        sys.exit(1)

    ad_id = ad_result["data"].get("ad_id", "DRY_RUN_ID")
    print(f"    OK — ad_id: {ad_id}")

    print("\n" + "=" * 60)
    print(f"{'[DRY-RUN] ' if dry_run else ''}COMPLETADO")
    if not dry_run:
        print(f"  campaign_id : {campaign_id}")
        print(f"  ad_set_id   : {ad_set_id}")
        print(f"  ad_id       : {ad_id}")
        print("  status      : PAUSED — sin entrega ni gasto")
        print("  Limpieza    : manual por Jesus Lopez")
    print("=" * 60 + "\n")


# --- ENTRY POINT --------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crea campana Meta desde briefing")
    parser.add_argument("--client", required=True, help="ID del cliente (ej. vidal-vidal)")
    parser.add_argument("--briefing", required=True, help="Ruta al briefing JSON")
    parser.add_argument("--dry-run", action="store_true", help="Simula sin ejecutar")
    args = parser.parse_args()

    run(
        client_id=args.client,
        briefing_path=args.briefing,
        dry_run=args.dry_run,
    )
