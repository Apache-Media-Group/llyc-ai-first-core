"""
scripts/dv360/read_briefing_from_drive.py
Lee el briefing DV360 desde un Google Sheet en Drive y genera el JSON
para el orquestador create_campaign_from_briefing.py.

Uso:
    python scripts/dv360/read_briefing_from_drive.py \
        --spreadsheet-id <ID> \
        --client <client_id> \
        --output clients/<client_id>/PAID_briefing-dv360-<client_id>.json

DEC_083: DV360 API directa.
DEC_084: SA llyc-ops-writer-sa para lectura del Sheet.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sys
from datetime import datetime

from google.oauth2 import service_account as sa
from googleapiclient import discovery

from scripts.dv360._common.auth import _read_secret

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SECRET_NAME = "DV360_OPS_WRITER_SA_KEY"
GCP_PROJECT = "llyc-ai-first-core"

SECTION_HEADERS = {
    "PLANTILLA BRIEFING DV360", "CAMPAÑA", "INSERTION ORDER",
    "LINE ITEM", "TARGETING", "BRAND SAFETY", "CALIDAD Y FRECUENCIA",
    "OVERRIDE DE GUARDRAILS"
}


def _is_section(key: str) -> bool:
    return any(key.upper().startswith(h) for h in SECTION_HEADERS)


def _parse_date(d: str | None) -> str | None:
    if not d or d.strip().lower() == "heredar":
        return None
    try:
        return datetime.strptime(d.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return d.strip()


def _parse_list(v: str | None) -> list | None:
    if not v or not v.strip():
        return None
    return [x.strip() for x in v.split(",") if x.strip()]


def _parse_float(v: str | None) -> float | None:
    if not v or not v.strip():
        return None
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return None


def _parse_int(v: str | None) -> int | None:
    if not v or not v.strip():
        return None
    try:
        return int(v)
    except ValueError:
        return None


def read_sheet(spreadsheet_id: str) -> dict:
    sa_json = _read_secret(GCP_PROJECT, SECRET_NAME)
    creds = sa.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=SCOPES
    )
    svc = discovery.build("sheets", "v4", credentials=creds, cache_discovery=False)
    result = svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="A1:B100"
    ).execute()
    data = {}
    for row in result.get("values", []):
        if len(row) == 2 and row[0] and not _is_section(row[0]):
            data[row[0].strip()] = row[1].strip() if row[1] else ""
        elif len(row) == 1 and row[0] in ("CLIENTE", "ADVERTISER_ID"):
            data[row[0]] = ""
    return data


def build_briefing(data: dict, client_override: str | None = None) -> dict:
    client = client_override or data.get("CLIENTE") or data.get("client", "")
    camp_start = _parse_date(data.get("campaign_start_date"))
    camp_end = _parse_date(data.get("campaign_end_date"))
    io_start = _parse_date(data.get("io_start_date")) or camp_start
    io_end = _parse_date(data.get("io_end_date")) or camp_end

    return {
        "client": client,
        "dry_run": False,
        "reason": data.get("reason") or None,
        "campaign": {
            "name": data.get("campaign_name"),
            "goal": data.get("campaign_goal"),
            "kpi": data.get("campaign_kpi"),
            "kpi_value": _parse_float(data.get("campaign_kpi_value")),
            "start_date": camp_start,
            "end_date": camp_end,
            "frequency_cap": _parse_int(data.get("campaign_frequency_cap")),
            "frequency_cap_unit": data.get("campaign_frequency_cap_unit") or None,
        },
        "insertion_orders": [{
            "name": data.get("io_name"),
            "budget_eur": _parse_float(data.get("io_budget_eur")) or 0,
            "pacing": data.get("io_pacing", "EVEN"),
            "pacing_period": data.get("io_pacing_period", "DAILY"),
            "kpi_type": data.get("io_kpi_type"),
            "kpi_value": data.get("io_kpi_value", "700000"),
            "optimization_objective": data.get("io_optimization_objective", "CONVERSIONS"),
            "frequency_cap": _parse_int(data.get("io_frequency_cap")),
            "frequency_cap_unit": data.get("io_frequency_cap_unit") or None,
            "start_date": io_start,
            "end_date": io_end,
            "line_items": [{
                "name": data.get("li_name"),
                "li_type": data.get("li_type", "DISPLAY"),
                "budget_eur": _parse_float(data.get("li_budget_eur")) or 0,
                "bid_strategy": data.get("li_bid_strategy", "FIXED"),
                "bid_eur": _parse_float(data.get("li_bid_eur")),
                "target_cpa_eur": _parse_float(data.get("li_target_cpa_eur")),
                "start_date": _parse_date(data.get("li_start_date")) or io_start,
                "end_date": _parse_date(data.get("li_end_date")) or io_end,
                "geo_regions": _parse_list(data.get("li_geo_regions")),
                "geo_exclude": _parse_list(data.get("li_geo_exclude")),
                "language_codes": _parse_list(data.get("li_language_codes")),
                "device_types": _parse_list(data.get("li_device_types")),
                "environment": data.get("li_environment") or None,
                "positions": _parse_list(data.get("li_positions")),
                "audience_inmarket": _parse_list(data.get("li_audience_inmarket")),
                "audience_affinity": _parse_list(data.get("li_audience_affinity")),
                "audience_list_ids": _parse_list(data.get("li_audience_list_ids")),
                "keyword_includes": _parse_list(data.get("li_keyword_includes")),
                "keyword_excludes": _parse_list(data.get("li_keyword_excludes")),
                "iab_categories": _parse_list(data.get("li_iab_categories")),
                "url_includes": _parse_list(data.get("li_url_includes")),
                "url_excludes": _parse_list(data.get("li_url_excludes")),
                "brand_safety_exclude": _parse_list(data.get("li_brand_safety_exclude")),
                "content_labels_exclude": _parse_list(data.get("li_content_labels_exclude")),
                "frequency_cap": _parse_int(data.get("li_frequency_cap")),
                "frequency_cap_unit": data.get("li_frequency_cap_unit") or None,
                "viewability_target": data.get("li_viewability_target") or None,
                "audience_expansion": (data.get("li_audience_expansion", "NO").upper() == "SI"),
            }]
        }]
    }


def main():
    parser = argparse.ArgumentParser(
        description="Lee briefing DV360 desde Google Sheet y genera JSON para el orquestador."
    )
    parser.add_argument("--spreadsheet-id", required=True, help="ID del Google Sheet del briefing")
    parser.add_argument("--client", default=None, help="Override del client_id (opcional)")
    parser.add_argument("--output", default=None, help="Path de salida del JSON (opcional)")
    parser.add_argument("--dry-run", action="store_true", help="Marca el briefing como dry_run=True")
    args = parser.parse_args()

    data = read_sheet(args.spreadsheet_id)
    briefing = build_briefing(data, client_override=args.client)

    if args.dry_run:
        briefing["dry_run"] = True

    output_json = json.dumps(briefing, indent=2, ensure_ascii=False)

    if args.output:
        out = pathlib.Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(output_json, encoding="utf-8")
        print(f"Briefing guardado en: {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
