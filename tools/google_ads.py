"""
tools/google_ads.py — Google Ads API tools
Proyecto: llyc-ai-first-core
Owner: Alberto González
Sprint: 1

Alimenta: performance-monitor · budget-pacer · naming-utm-auditor
Decisiones aplicadas: 022 (contrato ok/error + timeout), 026 (Secret Manager híbrido)

Credenciales leídas desde Secret Manager:
  - GOOGLE_ADS_DEVELOPER_TOKEN   → llyc-ai-first-core  (scope: shared)
  - GOOGLE_ADS_CLIENT_ID         → llyc-ai-first-core  (scope: shared)
  - GOOGLE_ADS_CLIENT_SECRET     → llyc-ai-first-core  (scope: shared)
  - GOOGLE_ADS_REFRESH_TOKEN     → llyc-ai-[cliente]   (scope: client)
"""

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from tools.response import ok, error, with_timeout


# ─────────────────────────────────────────────
# INICIALIZACIÓN
# ─────────────────────────────────────────────

def init_google_ads_client(
    developer_token: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    login_customer_id: str,
) -> GoogleAdsClient:
    """
    Inicializa el cliente de Google Ads con las credenciales del cliente.
    Llamar una vez por ejecución de Cloud Function antes de usar el resto de funciones.
    login_customer_id es el MCC (manager_customer_id en config).
    """
    credentials = {
        "developer_token": developer_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "login_customer_id": login_customer_id,
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(credentials)


# ─────────────────────────────────────────────
# PERFORMANCE MONITOR
# ─────────────────────────────────────────────

@with_timeout("google_ads")
def get_google_ads_performance(
    client: GoogleAdsClient,
    customer_id: str,
    date_start: str,
    date_end: str,
    metrics: list = None,
) -> dict:
    """
    Obtiene métricas de rendimiento por campaña para un rango de fechas.

    Usado por: performance-monitor (yesterday + last_7d para calcular desviación)

    Args:
        client: GoogleAdsClient inicializado
        customer_id: ID de la cuenta (sin guiones, ej: 2756616331)
        date_start: Fecha inicio YYYY-MM-DD
        date_end: Fecha fin YYYY-MM-DD
        metrics: ignorado — se devuelven siempre las métricas estándar

    Returns:
        ok("google_ads", {...}) con spend, revenue, ROAS, conversions, impressions, clicks, CTR
        error("google_ads", ...) si falla la llamada
    """
    try:
        ga_service = client.get_service("GoogleAdsService")

        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign.advertising_channel_type,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr
            FROM campaign
            WHERE campaign.status = 'ENABLED'
              AND segments.date BETWEEN '{date_start}' AND '{date_end}'
            ORDER BY metrics.cost_micros DESC
        """

        response = ga_service.search_stream(customer_id=str(customer_id), query=query)

        campaigns = []
        total_spend = 0.0
        total_revenue = 0.0
        total_conversions = 0.0
        total_impressions = 0
        total_clicks = 0

        for batch in response:
            for row in batch.results:
                spend = row.metrics.cost_micros / 1_000_000
                revenue = row.metrics.conversions_value
                conversions = row.metrics.conversions
                impressions = row.metrics.impressions
                clicks = row.metrics.clicks
                roas = revenue / spend if spend > 0 else 0.0

                campaigns.append({
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "channel_type": row.campaign.advertising_channel_type.name,
                    "spend_eur": round(spend, 2),
                    "revenue_eur": round(revenue, 2),
                    "roas": round(roas, 2),
                    "conversions": round(conversions, 1),
                    "impressions": impressions,
                    "clicks": clicks,
                    "ctr_pct": round(row.metrics.ctr, 4),
                })

                total_spend += spend
                total_revenue += revenue
                total_conversions += conversions
                total_impressions += impressions
                total_clicks += clicks

        total_roas = total_revenue / total_spend if total_spend > 0 else 0.0
        total_ctr = total_clicks / total_impressions if total_impressions > 0 else 0.0

        return ok("google_ads", {
            "spend_eur": round(total_spend, 2),
            "revenue_eur": round(total_revenue, 2),
            "roas": round(total_roas, 2),
            "conversions": round(total_conversions, 1),
            "impressions": total_impressions,
            "clicks": total_clicks,
            "ctr_pct": round(total_ctr, 4),
            "campaigns": campaigns,
            "date_start": date_start,
            "date_end": date_end,
        })

    except GoogleAdsException as e:
        return error(
            "google_ads",
            "API_ERROR",
            f"GoogleAdsException: {e.error.code().name} — {e.failure}",
        )
    except Exception as e:
        return error("google_ads", "UNEXPECTED_ERROR", str(e))


# ─────────────────────────────────────────────
# BUDGET PACER
# ─────────────────────────────────────────────

@with_timeout("google_ads")
def get_google_ads_spend_today(
    client: GoogleAdsClient,
    customer_id: str,
) -> dict:
    """
    Obtiene el gasto del día en curso.
    Usado por: budget-pacer (ejecución 12:00 y 18:00)
    """
    try:
        ga_service = client.get_service("GoogleAdsService")

        query = """
            SELECT metrics.cost_micros
            FROM campaign
            WHERE campaign.status = 'ENABLED'
              AND segments.date DURING TODAY
        """

        response = ga_service.search_stream(customer_id=str(customer_id), query=query)
        total_micros = sum(
            row.metrics.cost_micros
            for batch in response
            for row in batch.results
        )

        return ok("google_ads", {
            "spend_today_eur": round(total_micros / 1_000_000, 2),
            "date_preset": "today",
        })

    except GoogleAdsException as e:
        return error(
            "google_ads",
            "API_ERROR",
            f"GoogleAdsException: {e.error.code().name}",
        )
    except Exception as e:
        return error("google_ads", "UNEXPECTED_ERROR", str(e))


@with_timeout("google_ads")
def get_google_ads_spend_month(
    client: GoogleAdsClient,
    customer_id: str,
) -> dict:
    """
    Obtiene el gasto acumulado del mes en curso.
    Usado por: budget-pacer
    """
    try:
        ga_service = client.get_service("GoogleAdsService")

        query = """
            SELECT metrics.cost_micros
            FROM campaign
            WHERE campaign.status = 'ENABLED'
              AND segments.date DURING THIS_MONTH
        """

        response = ga_service.search_stream(customer_id=str(customer_id), query=query)
        total_micros = sum(
            row.metrics.cost_micros
            for batch in response
            for row in batch.results
        )

        return ok("google_ads", {
            "spend_month_eur": round(total_micros / 1_000_000, 2),
            "date_preset": "this_month",
        })

    except GoogleAdsException as e:
        return error(
            "google_ads",
            "API_ERROR",
            f"GoogleAdsException: {e.error.code().name}",
        )
    except Exception as e:
        return error("google_ads", "UNEXPECTED_ERROR", str(e))


# ─────────────────────────────────────────────
# NAMING & UTM AUDITOR
# ─────────────────────────────────────────────

@with_timeout("google_ads")
def get_google_ads_active_ad_urls(
    client: GoogleAdsClient,
    customer_id: str,
) -> dict:
    """
    Extrae URLs finales de todos los ads activos para auditar UTMs y naming.
    Cubre Search, Shopping y PMAX.
    Usado por: naming-utm-auditor (ejecución lunes 9:00)
    """
    try:
        ga_service = client.get_service("GoogleAdsService")

        query = """
            SELECT
                ad_group_ad.ad.id,
                ad_group_ad.ad.name,
                ad_group_ad.ad.final_urls,
                ad_group_ad.ad.type,
                ad_group.name,
                campaign.name,
                campaign.advertising_channel_type
            FROM ad_group_ad
            WHERE ad_group_ad.status = 'ENABLED'
              AND ad_group.status = 'ENABLED'
              AND campaign.status = 'ENABLED'
        """

        response = ga_service.search_stream(customer_id=str(customer_id), query=query)

        ad_list = []
        for batch in response:
            for row in batch.results:
                final_urls = list(row.ad_group_ad.ad.final_urls)
                ad_list.append({
                    "ad_id": str(row.ad_group_ad.ad.id),
                    "ad_name": row.ad_group_ad.ad.name,
                    "ad_type": row.ad_group_ad.ad.type_.name,
                    "adgroup_name": row.ad_group.name,
                    "campaign_name": row.campaign.name,
                    "channel_type": row.campaign.advertising_channel_type.name,
                    "destination_url": final_urls[0] if final_urls else None,
                })

        return ok("google_ads", {
            "ads": ad_list,
            "total_active_ads": len(ad_list),
        })

    except GoogleAdsException as e:
        return error(
            "google_ads",
            "API_ERROR",
            f"GoogleAdsException: {e.error.code().name}",
        )
    except Exception as e:
        return error("google_ads", "UNEXPECTED_ERROR", str(e))


# ─────────────────────────────────────────────
# CAMPAÑAS ACTIVAS (auxiliar)
# ─────────────────────────────────────────────

@with_timeout("google_ads")
def get_google_ads_active_campaigns(
    client: GoogleAdsClient,
    customer_id: str,
) -> dict:
    """
    Lista campañas activas con presupuesto y tipo.
    Auxiliar para verificar scope de campañas en config.
    """
    try:
        ga_service = client.get_service("GoogleAdsService")

        query = """
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type,
                campaign_budget.amount_micros
            FROM campaign
            WHERE campaign.status = 'ENABLED'
            ORDER BY campaign.name
        """

        response = ga_service.search_stream(customer_id=str(customer_id), query=query)

        campaign_list = []
        for batch in response:
            for row in batch.results:
                budget = row.campaign_budget.amount_micros / 1_000_000
                campaign_list.append({
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "channel_type": row.campaign.advertising_channel_type.name,
                    "daily_budget_eur": round(budget, 2),
                })

        return ok("google_ads", {
            "campaigns": campaign_list,
            "total_active_campaigns": len(campaign_list),
        })

    except GoogleAdsException as e:
        return error(
            "google_ads",
            "API_ERROR",
            f"GoogleAdsException: {e.error.code().name}",
        )
    except Exception as e:
        return error("google_ads", "UNEXPECTED_ERROR", str(e))