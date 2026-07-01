"""
scripts/meta/campaigns/read_briefing_from_workbook.py
Lee el tab meta_briefing del workbook del cliente y genera un JSON de briefing.
 
El nombre del tab se configura en clients/<client_id>/config.json:
    "workbook": {
        "file_id": "<id>",
        "tabs": {
            "meta_briefing": "briefing_meta_vidal"
        }
    }
 
Estructura del tab (secciones con cabecera #):
    # CAMPAIGN        — campos de campaña
    # AD_SET_1        — primer ad set
    # AD_1 (de AD_SET_1) — primer ad del ad set 1
    # AD_SET_2        — segundo ad set (opcional)
    # AD_1 (de AD_SET_2) — primer ad del ad set 2
 
Columna A = campo, Columna B = valor. Filas con # en col A = cabecera de sección.
 
Uso:
    python -m scripts.meta.campaigns.read_briefing_from_workbook \\
        --client vidal-vidal \\
        [--dry-run]
"""
from __future__ import annotations
 
import argparse
import json
import pathlib
import re
import sys
from datetime import datetime, timezone
 
from google.oauth2 import service_account
from googleapiclient.discovery import build
 
from scripts._common.secrets import read_secret
 
CORE_PROJECT = "llyc-ai-first-core"
WRITER_SA_SECRET = "DV360_OPS_WRITER_SA_KEY"
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
 
# Campos obligatorios por sección
REQUIRED_CAMPAIGN = ["campaign_name", "objective"]
REQUIRED_AD_SET = [
    "ad_set_name", "optimization_goal", "billing_event",
    "bid_strategy", "daily_budget_eur", "start_date", "geo_countries",
]
REQUIRED_AD = [
    "ad_name", "creative_type", "page_id",
    "link_url", "ad_message", "call_to_action",
]
# Opcionales en dry-run (requieren datos de Jesús)
DRY_RUN_OPTIONAL = ["page_id", "pixel_id", "image_hash", "video_id"]
 
# Valores válidos (validación básica antes de llamar a la API)
VALID_OBJECTIVES = {
    "OUTCOME_SALES", "OUTCOME_LEADS", "OUTCOME_AWARENESS",
    "OUTCOME_ENGAGEMENT", "OUTCOME_TRAFFIC", "OUTCOME_APP_PROMOTION",
}
VALID_OPTIMIZATION_GOALS = {
    "OFFSITE_CONVERSIONS", "LINK_CLICKS", "LANDING_PAGE_VIEWS",
    "REACH", "IMPRESSIONS", "VALUE", "LEAD_GENERATION", "THRUPLAY",
}
VALID_BID_STRATEGIES = {
    "LOWEST_COST_WITHOUT_CAP", "LOWEST_COST_WITH_BID_CAP",
    "COST_CAP", "LOWEST_COST_WITH_MIN_ROAS",
}
VALID_BILLING_EVENTS = {"IMPRESSIONS", "LINK_CLICKS", "THRUPLAY"}
VALID_CREATIVE_TYPES = {"SINGLE_IMAGE", "VIDEO", "CAROUSEL"}
VALID_PLACEMENTS = {"AUTOMATIC", "MANUAL"}
 
 
# --- AUTH ---------------------------------------------------------------------
 
def _build_sheets_service():
    sa_json = read_secret(WRITER_SA_SECRET, project_id=CORE_PROJECT)
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=SHEETS_SCOPES
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)
 
 
def _get_workbook_config(client_id: str) -> tuple[str, str]:
    repo_root = pathlib.Path(__file__).parents[3]
    config_path = repo_root / "clients" / client_id / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config no encontrado: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    wb = cfg.get("workbook", {})
    file_id = wb.get("file_id")
    if not file_id:
        raise ValueError(f"workbook.file_id no configurado en clients/{client_id}/config.json")
    tab_name = wb.get("tabs", {}).get("meta_briefing", "meta_briefing")
    return file_id, tab_name
 
 
# --- LECTURA Y PARSEO DEL TAB -------------------------------------------------
 
def _read_raw_rows(client_id: str) -> tuple[list[list[str]], str]:
    """Lee todas las filas del tab. Devuelve (rows, tab_name)."""
    file_id, tab_name = _get_workbook_config(client_id)
    svc = _build_sheets_service()
    result = (
        svc.spreadsheets().values()
        .get(spreadsheetId=file_id, range=f"{tab_name}!A:B")
        .execute()
    )
    rows = result.get("values", [])
    if not rows:
        raise ValueError(
            f"El tab '{tab_name}' esta vacio o no existe en el workbook de '{client_id}'."
        )
    return rows, tab_name
 
 
def _parse_sections(rows: list[list[str]]) -> dict[str, dict[str, str]]:
    """
    Parsea las filas en secciones identificadas por cabeceras (#).
    Devuelve dict: {seccion_key: {campo: valor}}.
 
    Cabeceras reconocidas:
      # CAMPAIGN
      # AD_SET_1, # AD_SET_2, ...
      # AD_1 (de AD_SET_1), # AD_2 (de AD_SET_1), ...
    """
    sections: dict[str, dict[str, str]] = {}
    current_section: str | None = None
 
    for row in rows:
        col_a = str(row[0]).strip() if len(row) > 0 else ""
        col_b = str(row[1]).strip() if len(row) > 1 else ""
 
        if not col_a:
            continue
 
        # Detectar cabecera de sección
        if col_a.startswith("#"):
            header = col_a.lstrip("#").strip().upper()
            # Normalizar: "AD_1 (DE AD_SET_1)" → "AD_SET_1.AD_1"
            m_ad = re.match(r"AD[_\s](\d+)\s*\(.*AD[_\s]SET[_\s](\d+)\)", header)
            m_adset = re.match(r"AD[_\s]SET[_\s](\d+)", header)
            m_campaign = re.match(r"CAMPAIGN", header)
 
            if m_ad:
                ad_n, adset_n = m_ad.group(1), m_ad.group(2)
                current_section = f"AD_SET_{adset_n}.AD_{ad_n}"
            elif m_adset:
                current_section = f"AD_SET_{m_adset.group(1)}"
            elif m_campaign:
                current_section = "CAMPAIGN"
            else:
                current_section = header  # sección desconocida, ignorar
            sections.setdefault(current_section, {})
            continue
 
        # Campo de datos
        if current_section and col_a and not col_a.startswith("#"):
            sections[current_section][col_a.lower()] = col_b
 
    return sections
 
 
# --- VALIDACION ---------------------------------------------------------------
 
def _validate(sections: dict, dry_run: bool) -> list[str]:
    errors = []
 
    # CAMPAIGN
    camp = sections.get("CAMPAIGN", {})
    for f in REQUIRED_CAMPAIGN:
        if not camp.get(f):
            errors.append(f"[CAMPAIGN] Campo obligatorio vacio: '{f}'")
    if camp.get("objective") and camp["objective"].upper() not in VALID_OBJECTIVES:
        errors.append(
            f"[CAMPAIGN] objective '{camp['objective']}' no valido. "
            f"Opciones: {sorted(VALID_OBJECTIVES)}"
        )
 
    # AD_SETs
    adset_keys = sorted([k for k in sections if re.match(r"AD_SET_\d+$", k)])
    if not adset_keys:
        errors.append("No se encontro ninguna seccion # AD_SET_N en el tab.")
 
    for adset_key in adset_keys:
        adset = sections.get(adset_key, {})
        for f in REQUIRED_AD_SET:
            if not adset.get(f) and not (dry_run and f in DRY_RUN_OPTIONAL):
                errors.append(f"[{adset_key}] Campo obligatorio vacio: '{f}'")
        if adset.get("bid_strategy") and adset["bid_strategy"].upper() not in VALID_BID_STRATEGIES:
            errors.append(
                f"[{adset_key}] bid_strategy '{adset['bid_strategy']}' no valido. "
                f"Opciones: {sorted(VALID_BID_STRATEGIES)}"
            )
        if adset.get("optimization_goal") and adset["optimization_goal"].upper() not in VALID_OPTIMIZATION_GOALS:
            errors.append(
                f"[{adset_key}] optimization_goal '{adset['optimization_goal']}' no valido."
            )
 
        # ADs del ad set
        n = adset_key.split("_")[-1]
        ad_keys = sorted([k for k in sections if re.match(rf"AD_SET_{n}\.AD_\d+", k)])
        if not ad_keys:
            errors.append(f"[{adset_key}] No se encontro ninguna seccion # AD_N (de AD_SET_{n}).")
        for ad_key in ad_keys:
            ad = sections.get(ad_key, {})
            for f in REQUIRED_AD:
                if not ad.get(f) and not (dry_run and f in DRY_RUN_OPTIONAL):
                    errors.append(f"[{ad_key}] Campo obligatorio vacio: '{f}'")
 
    return errors
 
 
# --- CONSTRUCCION DEL JSON ----------------------------------------------------
 
def _parse_attribution(window_str: str) -> list[dict]:
    """
    Parsea '7d_click,1d_view' en lista attribution_spec de Meta.
    Formatos validos: Nd_click, Nd_view (N = 1|7|28).
    """
    specs = []
    for part in window_str.split(","):
        part = part.strip().lower()
        m = re.match(r"(\d+)d_(click|view)(?:_through)?", part)
        if m:
            days, event = int(m.group(1)), m.group(2)
            event_type = "CLICK_THROUGH" if event == "click" else "VIEW_THROUGH"
            specs.append({"event_type": event_type, "window_days": days})
    return specs or [{"event_type": "CLICK_THROUGH", "window_days": 7}]
 
 
def _build_ad(ad_data: dict) -> dict:
    creative_type = ad_data.get("creative_type", "SINGLE_IMAGE").upper()
 
    ad = {
        "name": ad_data["ad_name"],
        "creative_type": creative_type,
        "page_id": ad_data.get("page_id", "PENDIENTE"),
        "instagram_account_id": ad_data.get("instagram_account_id") or None,
        "link_url": ad_data.get("link_url", ""),
        "ad_message": ad_data.get("ad_message", ""),
        "ad_title": ad_data.get("ad_title") or None,
        "ad_description": ad_data.get("ad_description") or None,
        "call_to_action": ad_data.get("call_to_action", "LEARN_MORE").upper(),
        "tracking_url": ad_data.get("tracking_url") or None,
    }
 
    if creative_type == "SINGLE_IMAGE":
        ad["image_hash"] = ad_data.get("image_hash", "PENDIENTE")
    elif creative_type == "VIDEO":
        ad["video_id"] = ad_data.get("video_id", "PENDIENTE")
    elif creative_type == "CAROUSEL":
        # Carousel requiere cards — se expande en el orquestador
        ad["carousel_cards"] = []  # placeholder
 
    return ad
 
 
def _build_ad_set(adset_data: dict, ads: list[dict], adset_n: str) -> dict:
    geo_countries = [c.strip() for c in adset_data.get("geo_countries", "ES").split(",") if c.strip()]
 
    # Genders: ALL -> [] (Meta omite el campo para todos), MALE -> [1], FEMALE -> [2]
    gender_raw = adset_data.get("genders", "ALL").upper()
    genders = [] if gender_raw == "ALL" else ([1] if gender_raw == "MALE" else [2])
 
    # Custom audiences
    ca_raw = adset_data.get("custom_audiences", "").strip()
    custom_audiences = [{"id": a.strip()} for a in ca_raw.split(",") if a.strip()]
 
    # Attribution
    attr_raw = adset_data.get("attribution_window", "7d_click,1d_view")
    attribution_spec = _parse_attribution(attr_raw)
 
    # Budget en centimos (Meta usa centimos de la moneda local)
    daily_budget_eur = float(adset_data.get("daily_budget_eur", 0))
    daily_budget_cents = int(daily_budget_eur * 100)
 
    # Bid amount en micros (solo para BID_CAP y COST_CAP)
    bid_amount_raw = adset_data.get("bid_amount_eur", "").strip()
    bid_amount_micros = int(float(bid_amount_raw) * 1_000_000) if bid_amount_raw else None
 
    # Dates
    start_date = adset_data.get("start_date", "")
    start_time = f"{start_date}T00:00:00+0000" if start_date else None
    end_date = adset_data.get("end_date", "").strip()
    end_time = f"{end_date}T23:59:59+0000" if end_date else None
 
    return {
        "name": adset_data["ad_set_name"],
        "optimization_goal": adset_data.get("optimization_goal", "OFFSITE_CONVERSIONS").upper(),
        "billing_event": adset_data.get("billing_event", "IMPRESSIONS").upper(),
        "bid_strategy": adset_data.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP").upper(),
        "bid_amount_micros": bid_amount_micros,
        "daily_budget_cents": daily_budget_cents,
        "start_time": start_time,
        "end_time": end_time,
        "placements": adset_data.get("placements", "AUTOMATIC").upper(),
        "pixel_id": adset_data.get("pixel_id", "PENDIENTE") or "PENDIENTE",
        "targeting": {
            "geo_locations": {"countries": geo_countries},
            "geo_cities": [c.strip() for c in adset_data.get("geo_cities", "").split(",") if c.strip()],
            "age_min": int(adset_data.get("age_min", 18)),
            "age_max": int(adset_data.get("age_max", 65)),
            "genders": genders,
            "custom_audiences": custom_audiences,
            "attribution_spec": attribution_spec,
        },
        "ads": ads,
    }
 
 
def build_briefing(sections: dict, client_id: str, tab_name: str) -> dict:
    camp_data = sections.get("CAMPAIGN", {})
 
    special_raw = camp_data.get("special_ad_categories", "").strip()
    special_ad_categories = [s.strip().upper() for s in special_raw.split(",") if s.strip()] if special_raw else []
 
    campaign = {
        "name": camp_data["campaign_name"],
        "objective": camp_data.get("objective", "").upper(),
        "special_ad_categories": special_ad_categories,
        "buying_type": camp_data.get("buying_type", "AUCTION").upper(),
        "cbo_enabled": camp_data.get("cbo_enabled", "false").lower() == "true",
    }
 
    # Ad Sets ordenados
    adset_keys = sorted([k for k in sections if re.match(r"AD_SET_\d+$", k)],
                        key=lambda k: int(k.split("_")[-1]))
 
    ad_sets = []
    for adset_key in adset_keys:
        n = adset_key.split("_")[-1]
        ad_keys = sorted(
            [k for k in sections if re.match(rf"AD_SET_{n}\.AD_\d+", k)],
            key=lambda k: int(k.split("_")[-1])
        )
        ads = [_build_ad(sections[ak]) for ak in ad_keys]
        ad_sets.append(_build_ad_set(sections[adset_key], ads, n))
 
    return {
        "client": client_id,
        "dry_run": False,
        "campaign": campaign,
        "ad_sets": ad_sets,
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": f"workbook tab '{tab_name}'",
            "sdk_version": "facebook-business==25.0.2",
        },
    }
 
 
# --- GUARDADO -----------------------------------------------------------------
 
def save_briefing(briefing: dict, client_id: str) -> pathlib.Path:
    repo_root = pathlib.Path(__file__).parents[3]
    out_dir = repo_root / "clients" / client_id / "briefings"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    out_path = out_dir / f"meta_{ts}.json"
    out_path.write_text(json.dumps(briefing, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
 
 
# --- ORQUESTADOR --------------------------------------------------------------
 
def run(client_id: str, dry_run: bool) -> None:
    _, tab_name = _get_workbook_config(client_id)
    print(f"\nLeyendo tab '{tab_name}' del workbook de '{client_id}'...")
 
    rows, tab_name = _read_raw_rows(client_id)
    sections = _parse_sections(rows)
 
    errors = _validate(sections, dry_run=dry_run)
    if errors:
        print("\nERROR — Campos incompletos o invalidos en el workbook:")
        for e in errors:
            print(f"  - {e}")
        print(f"\nCorrige el tab '{tab_name}' y vuelve a ejecutar.")
        sys.exit(1)
 
    briefing = build_briefing(sections, client_id, tab_name)
 
    n_adsets = len(briefing["ad_sets"])
    n_ads = sum(len(a["ads"]) for a in briefing["ad_sets"])
    print(f"  Campaign : {briefing['campaign']['name']}")
    print(f"  Objetivo : {briefing['campaign']['objective']}")
    print(f"  Ad Sets  : {n_adsets}")
    print(f"  Ads      : {n_ads}")
    print("\nBriefing completo:")
    print(json.dumps(briefing, indent=2, ensure_ascii=False))
 
    if dry_run:
        print(f"\n[DRY-RUN] JSON no guardado. Ejecuta sin --dry-run para guardar.")
        return
 
    out_path = save_briefing(briefing, client_id)
    print(f"\nGuardado en: {out_path}")
    print(f"\nSiguiente paso:")
    print(f"  python -m scripts.meta.campaigns.create_campaign_from_briefing \\")
    print(f"      --client {client_id} --briefing {out_path} --dry-run")
 
 
# --- ENTRY POINT --------------------------------------------------------------
 
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Lee tab meta_briefing del workbook y genera JSON de briefing."
    )
    parser.add_argument("--client", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="Muestra JSON sin guardar. page_id/pixel_id/image_hash opcionales.")
    args = parser.parse_args()
    run(client_id=args.client, dry_run=args.dry_run)