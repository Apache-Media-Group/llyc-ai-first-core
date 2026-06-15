"""
scripts/dv360/verify_advertiser.py
Verifica el estado del advertiser DV360 antes de crear campanas.

Este script es de solo lectura — usa llyc-agents-sa, no llyc-ops-writer-sa.
No requiere confirmacion interactiva.

Uso:
    python scripts/dv360/verify_advertiser.py --client vidal-vidal
    python scripts/dv360/verify_advertiser.py --client vaillant

Salida:
    - Estado del advertiser (activo/pausado)
    - Nombre, moneda, zona horaria
    - Campanas activas (resumen)
    - Confirmacion de que el advertiser_id del config es correcto

Prerequisito antes de:
    create_campaign.py -> create_io.py -> create_line_item.py
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from googleapiclient.errors import HttpError
from google.cloud import secretmanager
from google.oauth2 import service_account
import googleapiclient.discovery as discovery

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/display-video",
    "https://www.googleapis.com/auth/display-video-mediaplanning",
]

CORE_PROJECT = "llyc-ai-first-core"
SECRET_NAME_READ = "DV360_SERVICE_ACCOUNT_KEY"


def _build_read_service() -> any:
    """Construye cliente DV360 con SA de lectura (llyc-agents-sa)."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{CORE_PROJECT}/secrets/{SECRET_NAME_READ}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    sa_json = response.payload.data.decode("utf-8")

    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=SCOPES
    )
    return discovery.build(
        "displayvideo", "v4",
        credentials=creds,
        cache_discovery=False,
    )


def get_advertiser_id_from_config(client_id: str) -> str:
    """Lee advertiser_id del config del cliente."""
    repo_root = Path(__file__).parents[2]
    config_path = repo_root / "clients" / client_id / "config.json"

    if not config_path.exists():
        raise FileNotFoundError(f"Config no encontrado: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    dv360 = config.get("platforms", {}).get("dv360", {})

    if not dv360.get("enabled", False):
        print(f"⚠️  DV360 esta deshabilitado en el config de '{client_id}' (enabled=false).")
        print("   Cambiar a enabled=true antes de operar.")

    advertiser_id = dv360.get("advertiser_id")
    if not advertiser_id or advertiser_id == "PENDIENTE":
        raise ValueError(
            f"advertiser_id no configurado para '{client_id}'. "
            "Completar platforms.dv360.advertiser_id en config.json."
        )

    return advertiser_id, config


def verify_advertiser(client_id: str) -> dict:
    """
    Verifica el estado del advertiser DV360 del cliente.

    Comprueba:
    - Que el advertiser_id del config existe y es accesible
    - Estado (activo/pausado/borrador)
    - Nombre, moneda, zona horaria
    - Numero de campanas activas

    Returns:
        dict con status y datos del advertiser
    """
    advertiser_id, config = get_advertiser_id_from_config(client_id)

    print(f"\n🔍 Verificando advertiser DV360 para cliente '{client_id}'...")
    print(f"   advertiser_id en config: {advertiser_id}")

    try:
        svc = _build_read_service()

        # 1. Datos del advertiser
        advertiser = (
            svc.advertisers()
            .get(advertiserId=advertiser_id)
            .execute()
        )

        # 2. Campanas activas (resumen)
        campaigns_resp = (
            svc.advertisers()
            .campaigns()
            .list(
                advertiserId=advertiser_id,
                filter='entityStatus="ENTITY_STATUS_ACTIVE"',
            )
            .execute()
        )
        active_campaigns = campaigns_resp.get("campaigns", [])

        # 3. Campanas en borrador
        draft_resp = (
            svc.advertisers()
            .campaigns()
            .list(
                advertiserId=advertiser_id,
                filter='entityStatus="ENTITY_STATUS_DRAFT"',
            )
            .execute()
        )
        draft_campaigns = draft_resp.get("campaigns", [])

        status = advertiser.get("entityStatus", "")
        is_active = status == "ENTITY_STATUS_ACTIVE"

        result = {
            "status": "ok",
            "data": {
                "client_id": client_id,
                "advertiser_id": advertiser_id,
                "name": advertiser.get("displayName"),
                "entity_status": status,
                "is_active": is_active,
                "currency": advertiser.get("generalConfig", {}).get("currencyCode"),
                "timezone": advertiser.get("generalConfig", {}).get("timeZone"),
                "domain": advertiser.get("generalConfig", {}).get("domainUrl"),
                "campaigns_active": len(active_campaigns),
                "campaigns_draft": len(draft_campaigns),
                "active_campaigns_summary": [
                    {
                        "campaign_id": c.get("campaignId"),
                        "name": c.get("displayName"),
                        "status": c.get("entityStatus"),
                    }
                    for c in active_campaigns[:5]  # Max 5 en resumen
                ],
            },
        }

        # Output legible
        print(f"\n{'='*60}")
        print(f"  Advertiser: {result['data']['name']}")
        print(f"  ID:         {advertiser_id}")
        print(f"  Estado:     {status} {'✅' if is_active else '⚠️'}")
        print(f"  Moneda:     {result['data']['currency']}")
        print(f"  Zona hora:  {result['data']['timezone']}")
        print(f"  Dominio:    {result['data']['domain']}")
        print(f"  Campanas activas: {result['data']['campaigns_active']}")
        print(f"  Campanas draft:   {result['data']['campaigns_draft']}")

        if active_campaigns:
            print(f"\n  Campanas activas (primeras 5):")
            for c in active_campaigns[:5]:
                print(f"    - [{c.get('campaignId')}] {c.get('displayName')}")

        if not is_active:
            print(f"\n⚠️  ADVERTISER NO ACTIVO. Estado: {status}")
            print("   Activar el advertiser en DV360 antes de crear campanas.")
        else:
            print(f"\n✅ Advertiser verificado. Listo para crear campanas.")
            print(f"\nSiguiente paso:")
            print(
                f"  python scripts/dv360/campaigns/create_campaign.py "
                f"--client {client_id} --name '...' --goal ACTION --kpi CPA ..."
            )

        print(f"{'='*60}\n")

        return result

    except HttpError as e:
        if e.resp.status == 404:
            outcome = {
                "status": "error",
                "error": (
                    f"Advertiser {advertiser_id} no encontrado en DV360. "
                    "Verificar que el advertiser_id en config.json es correcto "
                    "y que la SA tiene acceso al partner."
                ),
                "data": {"advertiser_id": advertiser_id, "client_id": client_id},
            }
        else:
            outcome = {
                "status": "error",
                "error": f"DV360 API {e.resp.status}: {e.reason}",
                "data": {},
            }
        print(f"\n❌ Error: {outcome['error']}")
        return outcome

    except Exception as e:
        outcome = {
            "status": "error",
            "error": str(e),
            "data": {},
        }
        print(f"\n❌ Error inesperado: {e}")
        return outcome


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verifica el estado del advertiser DV360 antes de crear campanas.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scripts/dv360/verify_advertiser.py --client vidal-vidal
  python scripts/dv360/verify_advertiser.py --client vaillant

Flujo completo de creacion de campana:
  1. verify_advertiser.py        <- estas aqui
  2. create_campaign.py
  3. create_io.py
  4. create_line_item.py
  5. activate_line_item.py
  6. activate_io.py
        """,
    )
    parser.add_argument("--client", required=True, help="ID del cliente (ej. vidal-vidal)")
    parser.add_argument("--json", action="store_true", help="Output en JSON puro (para scripting)")

    args = parser.parse_args()

    result = verify_advertiser(client_id=args.client)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))

    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
