"""
create_line_item_sdf.py — Crea Line Items en DV360 vía SDF upload (v9.2).

Casos de uso principales:
  - Line Items de YouTube & Partners (no soportados por REST API v4)
  - Creación masiva de múltiples LIs en una sola operación

Flujo:
  1. Genera el CSV en formato SDF v9.2
  2. Sube el CSV via sdfdownloadtasks upload
  3. Hace polling hasta que la operación completa
  4. Devuelve los IDs de los LIs creados

Uso:
    python scripts/dv360/line_items/create_line_item_sdf.py \\
        --client test \\
        --io-id 1029063342 \\
        --name "ES_LI_YouTube_NonSkip_15s" \\
        --type YOUTUBE_NON_SKIP \\
        --budget-eur 38285 \\
        --start-date 2026-07-01 \\
        --end-date 2026-07-21 \\
        --geo-regions ES \\
        --language-codes es \\
        --frequency-cap 6 \\
        --frequency-cap-unit WEEKS \\
        --bid-strategy CPM \\
        --bid-eur 4.70

DEC_083 — DV360 API directa.
DEC_084 — SA llyc-ops-writer-sa para escritura.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import zipfile

from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

from scripts.dv360._common.auth import build_writer_service, get_advertiser_id
from scripts.dv360._common.audit import log_action, confirm_action

# ── Constantes ────────────────────────────────────────────────────────────────

PARTNER_ID = "5748134"
SDF_VERSION = "SDF_VERSION_9_2"

LINE_ITEM_TYPES = {
    "YOUTUBE_NON_SKIP":   ("YouTube & Partners", "Non-skippable"),
    "YOUTUBE_BUMPER":     ("YouTube & Partners", "Bumper"),
    "YOUTUBE_INSTREAM":   ("YouTube & Partners", "In-stream"),
    "YOUTUBE_INFEED":     ("YouTube & Partners", "In-feed"),
    "DISPLAY":            ("Display", "Simple"),
    "VIDEO":              ("Video", "Standard"),
}

GEO_IDS = {
    "ES": "2724", "PT": "2620", "FR": "2250", "DE": "2276",
    "IT": "2380", "GB": "2826", "US": "2840", "MX": "2484",
    "AR": "2032", "CO": "2170", "CL": "2152",
}

LANGUAGE_IDS = {
    "es": "1003", "en": "1000", "fr": "1002", "de": "1001",
    "it": "1004", "pt": "1014", "ca": "1038",
}

FREQUENCY_UNITS = {
    "DAYS": "Days", "WEEKS": "Weeks", "MONTHS": "Months",
}


# ── Builder SDF row ────────────────────────────────────────────────────────────

def build_sdf_row(
    io_id: str,
    name: str,
    li_type: str,
    budget_eur: float,
    start_date: str,
    end_date: str,
    bid_strategy: str,
    bid_eur: float,
    geo_regions: list | None = None,
    language_codes: list | None = None,
    frequency_cap: int | None = None,
    frequency_cap_unit: str | None = None,
    audience_inmarket: list | None = None,
    brand_safety_exclude: list | None = None,
    viewability_target: str | None = None,
    youtube_target_frequency: int | None = None,
) -> dict:
    """Construye una fila SDF v9.2 para un Line Item."""

    type_str, subtype_str = LINE_ITEM_TYPES.get(li_type.upper(), ("Display", "Simple"))
    is_youtube = "YouTube" in type_str

    # Geo
    geo_include = ""
    if geo_regions:
        ids = [GEO_IDS.get(r.upper(), "") for r in geo_regions if GEO_IDS.get(r.upper())]
        geo_include = "; ".join(ids) + ";" if ids else ""

    # Language
    lang_include = ""
    if language_codes:
        ids = [LANGUAGE_IDS.get(l.lower(), "") for l in language_codes if LANGUAGE_IDS.get(l.lower())]
        lang_include = "; ".join(ids) + ";" if ids else ""

    # Frequency
    freq_enabled = "True" if frequency_cap else "False"
    freq_exposures = str(frequency_cap) if frequency_cap else ""
    freq_period = FREQUENCY_UNITS.get(frequency_cap_unit.upper(), "Days") if frequency_cap_unit else ""
    freq_amount = "1"

    # TrueView frequency (YouTube)
    tv_freq_enabled = "False"
    tv_freq_exposures = ""
    tv_freq_period = ""
    if is_youtube and youtube_target_frequency:
        tv_freq_enabled = "True"
        tv_freq_exposures = str(youtube_target_frequency)
        tv_freq_period = "Weeks"

    # Brand safety
    bs_custom = ""
    if brand_safety_exclude:
        mapping = {
            "ADULT": "Sexual", "VIOLENCE": "Violence", "DRUGS": "Drugs",
            "HATE": "Hate Speech", "WEAPONS": "Weapons", "TRAGEDY": "Tragedy",
            "TOBACCO": "Tobacco",
        }
        bs_custom = "; ".join([mapping.get(c.upper(), c) for c in brand_safety_exclude]) + ";"

    # Audiences
    affinity_include = ""
    if audience_inmarket:
        affinity_include = "; ".join(audience_inmarket) + ";"

    # Viewability
    viewability = ""
    if viewability_target:
        mapping = {"50": "0.5", "60": "0.6", "70": "0.7", "80": "0.8"}
        viewability = mapping.get(str(viewability_target), "0.5")

    row = {
        "Line Item Id":                          "",  # vacío = CREATE
        "Io Id":                                 io_id,
        "Type":                                  type_str,
        "Subtype":                               subtype_str,
        "Name":                                  name,
        "Status":                                "Paused",
        "Start Date":                            start_date,
        "End Date":                              end_date,
        "Budget Type":                           "Amount",
        "Budget Amount":                         str(budget_eur),
        "Pacing":                                "Flight",
        "Pacing Rate":                           "Even",
        "Pacing Amount":                         "0",
        "Frequency Enabled":                     freq_enabled,
        "Frequency Exposures":                   freq_exposures,
        "Frequency Period":                      freq_period,
        "Frequency Amount":                      freq_amount,
        "TrueView View Frequency Enabled":       tv_freq_enabled,
        "TrueView View Frequency Exposures":     tv_freq_exposures,
        "TrueView View Frequency Period":        tv_freq_period,
        "Partner Revenue Model":                 "CPM",
        "Partner Revenue Amount":                "0",
        "Conversion Counting Type":              "Count post-click",
        "Conversion Counting Pct":               "0",
        "Primary Attribution Model Id":          "0",
        "Bid Strategy Type":                     "Fixed" if bid_strategy.upper() == "FIXED" else "Maximize",
        "Bid Strategy Value":                    str(bid_eur) if bid_eur else "0",
        "Bid Strategy Unit":                     "CPM" if is_youtube else "CPC",
        "Bid Strategy Do Not Exceed":            "0",
        "Apply Floor Price For Deals":           "False",
        "Algorithm Id":                          "0",
        "Contains EU Political Ads":             "No",
        "Geography Targeting - Include":         geo_include,
        "Language Targeting - Include":          lang_include,
        "Device Targeting - Include":            "30000; 30001; 30002; 30004;",
        "Digital Content Labels - Exclude":      "MA;" if not brand_safety_exclude else "",
        "Brand Safety Sensitivity Setting":      "Use custom" if bs_custom else "Standard",
        "Brand Safety Custom Settings":          bs_custom,
        "Third Party Verification Services":     "None",
        "Optimize Fixed Bidding":                "False",
        "Optimized Targeting":                   "False",
        "Affinity & In Market Targeting - Include": affinity_include,
        "Inventory Source Targeting - Authorized Seller Options": "Authorized Direct Sellers And Resellers",
        "Inventory Source Targeting - Target New Exchanges": "True",
        "Environment Targeting":                 "Web;" if not is_youtube else "",
        "Viewability Omid Targeting Enabled":    "True",
        "Viewability Targeting Active View":     viewability,
    }
    return row


# ── Upload SDF ─────────────────────────────────────────────────────────────────

def upload_sdf(svc, partner_id: str, rows: list[dict], headers: list[str]) -> dict:
    """Genera el CSV, lo sube y hace polling hasta completar."""

    # Generar CSV en memoria
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    csv_bytes = buf.getvalue().encode("utf-8")

    # Subir
    media = MediaIoBaseUpload(
        io.BytesIO(csv_bytes),
        mimetype="text/csv",
        resumable=False,
    )
    upload_resp = svc.media().upload(
        resourceName="sdf",
        media_body=media,
        body={
            "version": SDF_VERSION,
            "partnerId": partner_id,
            "advertiserId": None,  # se infiere del IO
        },
    ).execute()

    return upload_resp


def poll_operation(svc, op_name: str, max_wait: int = 120) -> dict:
    """Hace polling de una operación SDF hasta que completa."""
    for _ in range(max_wait // 5):
        r = svc.sdfdownloadtasks().operations().get(name=op_name).execute()
        if r.get("done"):
            return r
        time.sleep(5)
    raise TimeoutError(f"Operacion {op_name} no completó en {max_wait}s")


# ── Main ───────────────────────────────────────────────────────────────────────

def create_line_item_sdf(
    client_id: str,
    io_id: str,
    name: str,
    li_type: str,
    budget_eur: float,
    start_date: str,
    end_date: str,
    bid_strategy: str = "FIXED",
    bid_eur: float = 1.0,
    geo_regions: list | None = None,
    language_codes: list | None = None,
    frequency_cap: int | None = None,
    frequency_cap_unit: str | None = None,
    audience_inmarket: list | None = None,
    brand_safety_exclude: list | None = None,
    viewability_target: str | None = None,
    youtube_target_frequency: int | None = None,
    dry_run: bool = False,
) -> dict:

    advertiser_id = get_advertiser_id(client_id)

    row = build_sdf_row(
        io_id=io_id,
        name=name,
        li_type=li_type,
        budget_eur=budget_eur,
        start_date=start_date,
        end_date=end_date,
        bid_strategy=bid_strategy,
        bid_eur=bid_eur,
        geo_regions=geo_regions,
        language_codes=language_codes,
        frequency_cap=frequency_cap,
        frequency_cap_unit=frequency_cap_unit,
        audience_inmarket=audience_inmarket,
        brand_safety_exclude=brand_safety_exclude,
        viewability_target=viewability_target,
        youtube_target_frequency=youtube_target_frequency,
    )

    # Headers del SDF v9.2 — solo los que necesitamos
    headers = list(row.keys())

    action_msg = (
        f"Crear Line Item SDF [{li_type}] '{name}' "
        f"(IO {io_id}, budget {budget_eur} EUR) "
        f"en advertiser {advertiser_id} cliente {client_id}."
    )

    if not confirm_action(action_msg, dry_run=dry_run):
        return {"status": "cancelled", "data": {}}

    if dry_run:
        return {
            "status": "dry_run",
            "data": {
                "advertiser_id": advertiser_id,
                "li_type": li_type,
                "sdf_row": row,
                "note": f"LI [{li_type}] se crearia via SDF. Revisar antes de ejecutar.",
            },
        }

    svc = build_writer_service(client_id=client_id)

    # Generar CSV
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerow(row)
    csv_bytes = buf.getvalue().encode("utf-8")

    # Subir SDF
    media = MediaIoBaseUpload(
        io.BytesIO(csv_bytes),
        mimetype="application/octet-stream",
        resumable=False,
    )

    try:
        upload_resp = svc.media().upload(
            resourceName="sdf",
            media_body=media,
        ).execute()
        op_name = upload_resp.get("name", "")
        op_result = poll_operation(svc, op_name)

        outcome = {
            "status": "ok",
            "data": {
                "operation": op_name,
                "result": op_result,
            },
        }
    except Exception as e:
        outcome = {
            "status": "error",
            "error": str(e),
            "data": {},
        }

    log_action(
        script="create_line_item_sdf",
        action="create_line_item_sdf",
        client_id=client_id,
        args={
            "io_id": io_id,
            "name": name,
            "li_type": li_type,
            "budget_eur": budget_eur,
            "advertiser_id": advertiser_id,
        },
        result=outcome,
        dry_run=dry_run,
    )
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crea Line Items en DV360 vía SDF upload (soporta YouTube & Partners)."
    )
    parser.add_argument("--client", required=True)
    parser.add_argument("--io-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--li-type", required=True,
                        choices=list(LINE_ITEM_TYPES.keys()),
                        help="Tipo de LI")
    parser.add_argument("--budget-eur", required=True, type=float)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--bid-strategy", choices=["FIXED", "MAXIMIZE"], default="FIXED")
    parser.add_argument("--bid-eur", type=float, default=1.0)
    parser.add_argument("--geo-regions", nargs="+", default=None)
    parser.add_argument("--language-codes", nargs="+", default=None)
    parser.add_argument("--frequency-cap", type=int, default=None)
    parser.add_argument("--frequency-cap-unit",
                        choices=["DAYS", "WEEKS", "MONTHS"], default=None)
    parser.add_argument("--audience-inmarket", nargs="+", default=None)
    parser.add_argument("--brand-safety-exclude", nargs="+", default=None)
    parser.add_argument("--viewability-target",
                        choices=["50", "60", "70", "80"], default=None)
    parser.add_argument("--youtube-target-frequency", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    result = create_line_item_sdf(
        client_id=args.client,
        io_id=args.io_id,
        name=args.name,
        li_type=args.li_type,
        budget_eur=args.budget_eur,
        start_date=args.start_date,
        end_date=args.end_date,
        bid_strategy=args.bid_strategy,
        bid_eur=args.bid_eur,
        geo_regions=args.geo_regions,
        language_codes=args.language_codes,
        frequency_cap=args.frequency_cap,
        frequency_cap_unit=args.frequency_cap_unit,
        audience_inmarket=args.audience_inmarket,
        brand_safety_exclude=args.brand_safety_exclude,
        viewability_target=args.viewability_target,
        youtube_target_frequency=args.youtube_target_frequency,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("ok", "dry_run", "cancelled") else 1)


if __name__ == "__main__":
    main()