"""T10a / T6: guard estatico sobre los filtros de las queries de google_ads.

Las queries de GASTO (historico, MTD, hoy) NO deben filtrar por campaign.status:
el gasto ya incurrido es independiente del estado actual de la campana (1b).
Las queries de ENTIDAD ACTIVA (naming-utm-auditor) SI deben filtrar ENABLED.
No se puede E2E la GAQL en local; este guard previene la reintroduccion del filtro.
"""
import inspect

import tools.google_ads as g


def test_queries_de_gasto_sin_filtro_de_estado():
    for fn in (g.get_google_ads_performance,
               g.get_google_ads_spend_month,
               g.get_google_ads_spend_today):
        src = inspect.getsource(fn)
        assert "campaign.status = 'ENABLED'" not in src, \
            f"{fn.__name__} reintrodujo el filtro de estado (1b)"


def test_spend_today_usa_cost_micros_y_today():
    src = inspect.getsource(g.get_google_ads_spend_today)
    assert "DURING TODAY" in src
    assert "metrics.cost_micros > 0" in src


def test_queries_de_entidad_activa_mantienen_estado():
    for fn in (g.get_google_ads_active_ad_urls,
               g.get_google_ads_url_settings,
               g.get_google_ads_active_campaigns):
        src = inspect.getsource(fn)
        assert "ENABLED" in src, \
            f"{fn.__name__} deberia mantener el filtro de entidad activa"
