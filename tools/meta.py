"""
tools/meta.py — Meta Marketing API tools
Proyecto: llyc-ai-first-core
Owner: Alberto González
Sprint: 1

Alimenta: performance-monitor · budget-pacer · naming-utm-auditor
Decisiones aplicadas: 022 (contrato ok/error + timeout), 026 (Secret Manager híbrido)

Credenciales leídas desde Secret Manager vía config.json:
  - META_ACCESS_TOKEN     → llyc-ai-[cliente]   (scope: client)
  - META_APP_ID           → llyc-ai-first-core  (scope: shared)
  - META_APP_SECRET       → llyc-ai-first-core  (scope: shared)
"""

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adsinsights import AdsInsights
from facebook_business.adobjects.campaign import Campaign
from facebook_business.exceptions import FacebookRequestError

from tools.response import ok, error, with_timeout


# ─────────────────────────────────────────────
# INICIALIZACIÓN
# ─────────────────────────────────────────────


def init_meta_api(access_token: str, app_id: str, app_secret: str) -> None:
    """
    Inicializa el SDK de Meta con las credenciales del cliente.
    Llamar una vez por ejecución de Cloud Function antes de usar el resto de funciones.
    """
    FacebookAdsApi.init(app_id=app_id, app_secret=app_secret, access_token=access_token)


# ─────────────────────────────────────────────
# PERFORMANCE MONITOR
# ─────────────────────────────────────────────


@with_timeout("meta")
def get_meta_performance(
    ad_account_id: str, date_start: str, date_end: str, metrics: list
) -> dict:
    """
    Obtiene métricas de rendimiento de Meta Ads para un rango de fechas.

    Usado por: performance-monitor (yesterday + last_7d para calcular desviación)

    Args:
        ad_account_id: ID de la cuenta publicitaria (sin prefijo 'act_')
        date_start: Fecha inicio en formato YYYY-MM-DD
        date_end: Fecha fin en formato YYYY-MM-DD
        metrics: Lista de métricas a obtener (ignorado — se devuelven siempre las estándar)

    Returns:
        ok("meta", {...}) con spend, revenue, ROAS, CPA, impressions, clicks, CTR
        error("meta", ...) si falla la llamada
    """
    try:
        account = AdAccount(f"act_{ad_account_id}")

        insights = account.get_insights(
            fields=[
                AdsInsights.Field.spend,
                AdsInsights.Field.impressions,
                AdsInsights.Field.clicks,
                AdsInsights.Field.ctr,
                AdsInsights.Field.actions,
                AdsInsights.Field.action_values,
                AdsInsights.Field.cost_per_action_type,
            ],
            params={
                "time_range": {"since": date_start, "until": date_end},
                "level": "account",
            },
        )

        results = list(insights)

        if not results:
            return ok(
                "meta",
                {
                    "spend_eur": 0.0,
                    "revenue_eur": 0.0,
                    "roas": 0.0,
                    "cpa_eur": 0.0,
                    "impressions": 0,
                    "clicks": 0,
                    "ctr_pct": 0.0,
                    "conversions": 0,
                    "date_start": date_start,
                    "date_end": date_end,
                },
            )

        insight = results[0]
        spend = float(insight.get("spend", 0))

        # Revenue: omni_purchase es el evento canonico deduplicado de Meta
        # (web/app/offline). NO sumar "purchase": esta contenido en
        # omni_purchase y duplica el valor (x2 en cuentas web-only).
        action_values = insight.get("action_values", [])
        revenue = sum(
            float(av["value"])
            for av in action_values
            if av["action_type"] == "omni_purchase"
        )

        # Conversiones: suma de purchase actions
        actions = insight.get("actions", [])
        conversions = sum(
            int(float(a["value"]))
            for a in actions
            if a["action_type"] == "omni_purchase"
        )

        roas = revenue / spend if spend > 0 else 0.0
        cpa = spend / conversions if conversions > 0 else 0.0

        return ok(
            "meta",
            {
                "spend_eur": round(spend, 2),
                "revenue_eur": round(revenue, 2),
                "roas": round(roas, 2),
                "cpa_eur": round(cpa, 2),
                "impressions": int(insight.get("impressions", 0)),
                "clicks": int(insight.get("clicks", 0)),
                "ctr_pct": round(float(insight.get("ctr", 0)), 4),
                "conversions": conversions,
                "date_start": date_start,
                "date_end": date_end,
            },
        )

    except FacebookRequestError as e:
        return error(
            "meta", "API_ERROR", f"FacebookRequestError: {e.api_error_message()}"
        )
    except Exception as e:
        return error("meta", "UNEXPECTED_ERROR", str(e))


# ─────────────────────────────────────────────
# BUDGET PACER
# ─────────────────────────────────────────────


@with_timeout("meta")
def get_meta_spend_today(ad_account_id: str) -> dict:
    """
    Obtiene el gasto del día en curso.
    Usado por: budget-pacer (ejecución 12:00 y 18:00)
    """
    try:
        account = AdAccount(f"act_{ad_account_id}")

        insights = account.get_insights(
            fields=[AdsInsights.Field.spend],
            params={
                "date_preset": "today",
                "level": "account",
            },
        )

        results = list(insights)
        spend = float(results[0]["spend"]) if results else 0.0

        return ok(
            "meta",
            {
                "spend_today_eur": round(spend, 2),
                "date_preset": "today",
            },
        )

    except FacebookRequestError as e:
        return error(
            "meta", "API_ERROR", f"FacebookRequestError: {e.api_error_message()}"
        )
    except Exception as e:
        return error("meta", "UNEXPECTED_ERROR", str(e))


@with_timeout("meta")
def get_meta_spend_month(ad_account_id: str) -> dict:
    """
    Obtiene el gasto acumulado del mes en curso.
    Usado por: budget-pacer
    """
    try:
        account = AdAccount(f"act_{ad_account_id}")

        insights = account.get_insights(
            fields=[AdsInsights.Field.spend],
            params={
                "date_preset": "this_month",
                "level": "account",
            },
        )

        results = list(insights)
        spend = float(results[0]["spend"]) if results else 0.0

        return ok(
            "meta",
            {
                "spend_month_eur": round(spend, 2),
                "date_preset": "this_month",
            },
        )

    except FacebookRequestError as e:
        return error(
            "meta", "API_ERROR", f"FacebookRequestError: {e.api_error_message()}"
        )
    except Exception as e:
        return error("meta", "UNEXPECTED_ERROR", str(e))


# ─────────────────────────────────────────────
# NAMING & UTM AUDITOR
# ─────────────────────────────────────────────


@with_timeout("meta")
def get_meta_active_ad_urls(ad_account_id: str) -> dict:
    """
    Extrae las URLs de destino de todos los ads activos para auditar UTMs y naming.
    Usado por: naming-utm-auditor (ejecución lunes 9:00)

    En Meta los UTMs viven normalmente en url_tags del creative (template que la
    plataforma anexa al link en delivery), no en el link en sí. Auditar solo
    destination_url produce falsos UTM_MISSING — el auditor debe leer effective_url.

    Returns:
        Lista de ads con ad_id, ad_name, adset_name, campaign_name,
        destination_url (link crudo del creative), url_tags (template UTM crudo)
        y effective_url (link + url_tags con macros {{campaign.name}} etc. resueltos)
    """
    try:
        account = AdAccount(f"act_{ad_account_id}")

        # Obtener ads activos con sus creatividades
        ads = account.get_ads(
            fields=[
                "id",
                "name",
                "adset_id",
                "adset{name}",
                "campaign_id",
                "campaign{name}",
                "creative{id,object_story_spec,asset_feed_spec,url_tags}",
                "status",
                "effective_status",
            ],
            params={
                "effective_status": ["ACTIVE"],
            },
        )

        ad_list = []
        for ad in ads:
            adset_name = ad.get("adset", {}).get("name") if ad.get("adset") else None
            campaign_name = (
                ad.get("campaign", {}).get("name") if ad.get("campaign") else None
            )
            creative = ad.get("creative", {})
            link = _extract_url_from_creative(creative)
            url_tags = creative.get("url_tags") if creative else None
            ad_data = {
                "ad_id": ad.get("id"),
                "ad_name": ad.get("name"),
                "adset_name": adset_name,
                "campaign_name": campaign_name,
                "destination_url": link,
                "url_tags": url_tags,
                "effective_url": _compose_effective_url(
                    link,
                    url_tags,
                    {
                        "campaign.name": campaign_name,
                        "adset.name": adset_name,
                        "ad.name": ad.get("name"),
                        "campaign.id": ad.get("campaign_id"),
                        "adset.id": ad.get("adset_id"),
                        "ad.id": ad.get("id"),
                    },
                ),
            }
            ad_list.append(ad_data)

        return ok(
            "meta",
            {
                "ads": ad_list,
                "total_active_ads": len(ad_list),
            },
        )

    except FacebookRequestError as e:
        return error(
            "meta", "API_ERROR", f"FacebookRequestError: {e.api_error_message()}"
        )
    except Exception as e:
        return error("meta", "UNEXPECTED_ERROR", str(e))


# ─────────────────────────────────────────────
# CAMPAÑAS ACTIVAS (auxiliar)
# ─────────────────────────────────────────────


@with_timeout("meta")
def get_meta_active_campaigns(ad_account_id: str) -> dict:
    """
    Obtiene la lista de campañas activas con presupuesto.
    Auxiliar para verificar scope de campañas en config.
    """
    try:
        account = AdAccount(f"act_{ad_account_id}")

        campaigns = account.get_campaigns(
            fields=[
                Campaign.Field.id,
                Campaign.Field.name,
                Campaign.Field.status,
                Campaign.Field.objective,
                Campaign.Field.daily_budget,
                Campaign.Field.lifetime_budget,
            ],
            params={
                "effective_status": ["ACTIVE"],
            },
        )

        campaign_list = [
            {
                "campaign_id": c.get("id"),
                "campaign_name": c.get("name"),
                "objective": c.get("objective"),
                "daily_budget_eur": round(float(c["daily_budget"]) / 100, 2)
                if c.get("daily_budget")
                else None,
                "lifetime_budget_eur": round(float(c["lifetime_budget"]) / 100, 2)
                if c.get("lifetime_budget")
                else None,
            }
            for c in list(campaigns)
        ]

        return ok(
            "meta",
            {
                "campaigns": campaign_list,
                "total_active_campaigns": len(campaign_list),
            },
        )

    except FacebookRequestError as e:
        return error(
            "meta", "API_ERROR", f"FacebookRequestError: {e.api_error_message()}"
        )
    except Exception as e:
        return error("meta", "UNEXPECTED_ERROR", str(e))


# ─────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────


def _extract_url_from_creative(creative: dict) -> str | None:
    """
    Extrae la URL de destino de una creatividad de Meta.
    Intenta object_story_spec primero, luego asset_feed_spec.
    """
    if not creative:
        return None

    try:
        # Caso 1: link_data (ads de imagen/carrusel)
        story_spec = creative.get("object_story_spec", {})
        link_data = story_spec.get("link_data", {})
        if link_data.get("link"):
            return link_data["link"]

        # Caso 2: video_data
        video_data = story_spec.get("video_data", {})
        cta = video_data.get("call_to_action", {})
        if cta.get("value", {}).get("link"):
            return cta["value"]["link"]

        # Caso 3: asset_feed_spec (dynamic ads)
        asset_feed = creative.get("asset_feed_spec", {})
        link_urls = asset_feed.get("link_urls", [])
        if link_urls:
            return link_urls[0].get("website_url")

    except (KeyError, TypeError):
        pass

    return None


def _compose_effective_url(
    link: str | None, url_tags: str | None, macros: dict
) -> str | None:
    """
    Compone la URL efectiva de delivery: link del creative + url_tags anexado
    como query string, resolviendo los macros dinámicos de Meta conocidos
    ({{campaign.name}}, {{adset.name}}, {{ad.name}} y sus .id). Macros sin
    valor conocido (ej. {{placement}}) se dejan literales — siguen contando
    como parámetro presente y no vacío para la auditoría UTM.
    """
    if not link:
        return None
    if not url_tags:
        return link

    tags = url_tags.lstrip("?&")
    for key, value in macros.items():
        if value:
            tags = tags.replace("{{" + key + "}}", str(value))

    separator = "&" if "?" in link else "?"
    return f"{link}{separator}{tags}"
