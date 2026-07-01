"""
scripts/meta/campaigns/read_briefing_from_workbook.py
Lee el tab meta_briefing del workbook del cliente y genera un JSON de briefing.
 
El JSON generado se guarda en clients/<client_id>/briefings/ y sirve como
input para create_campaign_from_briefing.py. Es tambien el snapshot de
trazabilidad en Git de lo que se ejecuto.
 
Flujo completo:
    1. Consultor rellena tab "meta_briefing" en el workbook del cliente
    2. Este script lee el tab y genera el JSON
    3. create_campaign_from_briefing.py consume el JSON
 
Formato del tab meta_briefing (dos columnas: campo | valor):
    campaign_name         VV_PROS_META_ADV+_2026-07
    objective             OUTCOME_SALES
    special_ad_categories (vacio si no aplica)
    ad_set_name           VV_PROS_META_ADV+_2026-07_AS01
    optimization_goal     OFFSITE_CONVERSIONS
    billing_event         IMPRESSIONS
    bid_strategy          LOWEST_COST_WITHOUT_CAP
    daily_budget_eur      50
    start_date            2026-07-07
    geo_countries         ES
    age_min               25
    age_max               55
    ad_name               VV_PROS_META_ADV+_2026-07_AS01_AD01
    creative_name         VV_PROS_META_ADV+_2026-07_AS01_AD01_CR01
    page_id               123456789
    link_url              https://www.vidalyvidal.com
    ad_message            Descubre nuestra nueva coleccion
    call_to_action        SHOP_NOW
    image_hash            abc123...
 
Uso:
    python -m scripts.meta.campaigns.read_briefing_from_workbook \\
        --client vidal-vidal \\
        [--dry-run]  # muestra el JSON sin guardarlo
"""
from __future__ import annotations
 
import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone
 
from google.oauth2 import service_account
from googleapiclient.discovery import build
 
from scripts._common.secrets import read_secret
 
CORE_PROJECT = "llyc-ai-first-core"
WRITER_SA_SECRET = "DV360_OPS_WRITER_SA_KEY"
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
TAB_NAME = "meta_briefing"
 
# Campos obligatorios — el script falla si alguno esta vacio
REQUIRED_FIELDS = [
    "campaign_name",
    "objective",
    "ad_set_name",
    "optimization_goal",
    "daily_budget_eur",
    "start_date",
    "geo_countries",
    "ad_name",
    "creative_name",
    "page_id",
    "link_url",
    "ad_message",
    "call_to_action",
    "image_hash",
]
 
 
# --- AUTENTICACION SHEETS -----------------------------------------------------
 
def _build_sheets_service():
    """Construye cliente de Google Sheets con la SA de escritura (tiene acceso al workbook)."""
    sa_json = read_secret(WRITER_SA_SECRET, project_id=CORE_PROJECT)
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=SHEETS_SCOPES
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)
 
 
# --- LECTURA DEL WORKBOOK -----------------------------------------------------
 
def _get_workbook_file_id(client_id: str) -> str:
    """Lee el file_id del workbook desde config.json del cliente."""
    repo_root = pathlib.Path(__file__).parents[3]
    config_path = repo_root / "clients" / client_id / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config no encontrado para cliente '{client_id}': {config_path}")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    file_id = config.get("workbook", {}).get("file_id")
    if not file_id:
        raise ValueError(
            f"workbook.file_id no configurado en clients/{client_id}/config.json. "
            "Anadir: \"workbook\": {\"file_id\": \"<id>\"}."
        )
    return file_id
 
 
def read_tab(client_id: str) -> dict:
    """
    Lee el tab meta_briefing del workbook del cliente.
    Formato esperado: columna A = campo, columna B = valor.
    Lineas en blanco y filas sin valor se ignoran.
    Returns:
        dict con todos los campos clave:valor del tab.
    """
    file_id = _get_workbook_file_id(client_id)
    svc = _build_sheets_service()
 
    range_name = f"{TAB_NAME}!A:B"
    result = (
        svc.spreadsheets()
        .values()
        .get(spreadsheetId=file_id, range=range_name)
        .execute()
    )
    rows = result.get("values", [])
    if not rows:
        raise ValueError(
            f"El tab '{TAB_NAME}' esta vacio o no existe en el workbook de '{client_id}'. "
            "Asegurate de que el consultor ha rellenado el tab antes de ejecutar este script."
        )
 
    data = {}
    for row in rows:
        if len(row) < 2:
            continue  # fila sin valor, ignorar
        campo = str(row[0]).strip()
        valor = str(row[1]).strip()
        if not campo or campo.startswith("#"):
            continue  # linea en blanco o comentario
        data[campo] = valor
 
    return data
 
 
# --- VALIDACION ---------------------------------------------------------------
 
def validate(data: dict) -> list[str]:
    """Devuelve lista de errores. Vacia = ok."""
    errors = []
    for field in REQUIRED_FIELDS:
        if not data.get(field):
            errors.append(f"Campo obligatorio vacio o ausente: '{field}'")
    return errors
 
 
# --- CONSTRUCCION DEL BRIEFING JSON ------------------------------------------
 
def build_briefing(data: dict) -> dict:
    """Construye el dict de briefing en el formato que consume create_campaign_from_briefing.py."""
 
    # geo_countries: "ES" o "ES,FR,PT" -> lista
    geo_countries = [c.strip() for c in data.get("geo_countries", "ES").split(",") if c.strip()]
 
    # special_ad_categories: vacio -> []
    special_raw = data.get("special_ad_categories", "").strip()
    special_ad_categories = [s.strip() for s in special_raw.split(",") if s.strip()] if special_raw else []
 
    briefing = {
        "campaign_name": data["campaign_name"],
        "objective": data["objective"],
        "special_ad_categories": special_ad_categories,
        "ad_set": {
            "name": data["ad_set_name"],
            "optimization_goal": data["optimization_goal"],
            "billing_event": data.get("billing_event", "IMPRESSIONS"),
            "bid_strategy": data.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP"),
            "daily_budget_eur": float(data["daily_budget_eur"]),
            "start_time": f"{data['start_date']}T00:00:00+0000",
            "targeting": {
                "geo_locations": {
                    "countries": geo_countries
                },
                "age_min": int(data.get("age_min", 18)),
                "age_max": int(data.get("age_max", 65)),
            },
        },
        "ad": {
            "name": data["ad_name"],
            "creative_name": data["creative_name"],
            "object_story_spec": {
                "page_id": data["page_id"],
                "link_data": {
                    "link": data["link_url"],
                    "message": data["ad_message"],
                    "name": data.get("ad_title", data["campaign_name"]),
                    "call_to_action": {
                        "type": data["call_to_action"]
                    },
                    "image_hash": data["image_hash"],
                },
            },
        },
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": f"workbook tab '{TAB_NAME}'",
            "client_id": None,  # se rellena en run()
        },
    }
    return briefing
 
 
# --- GUARDADO -----------------------------------------------------------------
 
def save_briefing(briefing: dict, client_id: str) -> pathlib.Path:
    """Guarda el JSON en clients/<client_id>/briefings/ con timestamp."""
    repo_root = pathlib.Path(__file__).parents[3]
    out_dir = repo_root / "clients" / client_id / "briefings"
    out_dir.mkdir(parents=True, exist_ok=True)
 
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    out_path = out_dir / f"meta_{ts}.json"
    out_path.write_text(json.dumps(briefing, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
 
 
# --- ORQUESTADOR --------------------------------------------------------------
 
def run(client_id: str, dry_run: bool) -> None:
    print(f"\nLeyendo tab '{TAB_NAME}' del workbook de '{client_id}'...")
 
    data = read_tab(client_id)
 
    errors = validate(data)
    if errors:
        print("\nERROR — Campos obligatorios incompletos en el workbook:")
        for e in errors:
            print(f"  - {e}")
        print(f"\nRellena el tab '{TAB_NAME}' y vuelve a ejecutar.")
        sys.exit(1)
 
    briefing = build_briefing(data)
    briefing["_meta"]["client_id"] = client_id
 
    print("\nBriefing generado:")
    print(json.dumps(briefing, indent=2, ensure_ascii=False))
 
    if dry_run:
        print(f"\n[DRY-RUN] JSON no guardado. Revisa los campos y ejecuta sin --dry-run para guardar.")
        return
 
    out_path = save_briefing(briefing, client_id)
    print(f"\nGuardado en: {out_path}")
    print(f"\nSiguiente paso:")
    print(f"  python -m scripts.meta.campaigns.create_campaign_from_briefing \\")
    print(f"      --client {client_id} \\")
    print(f"      --briefing {out_path} \\")
    print(f"      --dry-run")
 
 
# --- ENTRY POINT --------------------------------------------------------------
 
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Lee tab meta_briefing del workbook y genera JSON de briefing."
    )
    parser.add_argument("--client", required=True, help="ID del cliente (ej. vidal-vidal)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra el JSON generado sin guardarlo",
    )
    args = parser.parse_args()
 
    run(client_id=args.client, dry_run=args.dry_run)