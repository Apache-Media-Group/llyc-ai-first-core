"""T9 (eval local): determinismo de los numeros del output de perf-monitor.

Cierra el gate de evals del brief s9/s12 a nivel unitario:
  - regresion del Bug 2 (06-10): el spend de Google != el de Meta (cada uno de su tool_result)
  - campo canonico del output == tool_result.data (sin transcripcion del LLM)
  - prosa adversaria no sobreescribe numeros tras merge_prose

El E2E contra prod (06-09/10) es la pieza gated por el deploy manual Gen2 y va aparte.
"""
import datetime as dt

import pytest

from output_assembler import assemble
from narrative import merge_prose


class FakeOI:
    client_id = "vidal-vidal"
    trace = {"fallback_used": False}

    def kpi(self, m, p, platform=None, periodo=None):
        return {("roas", "tolerancia_desviacion_pct"): 15,
                ("cpa", "tolerancia_desviacion_pct"): 20}.get((m, p))

    def budget_for(self, nivel="cuenta"):
        return {"roas_blended_floor": 4.65}


def _ok(**d):
    return {"status": "ok", "data": d}


DATE = dt.date(2026, 6, 16)
PAID = ["meta", "google_ads"]


def _results(meta_spend, google_spend):
    return {
        ("get_meta_performance", "yesterday"): _ok(spend_eur=meta_spend, revenue_eur=200, roas=2.0, conversions=10),
        ("get_meta_performance", "7d"): _ok(spend_eur=700, revenue_eur=2800, roas=4.0, conversions=70),
        ("get_meta_performance", "mtd"): _ok(spend_eur=2000),
        ("get_google_ads_performance", "yesterday"): _ok(spend_eur=google_spend, revenue_eur=250, roas=5.0, conversions=5),
        ("get_google_ads_performance", "7d"): _ok(spend_eur=350, revenue_eur=1680, roas=4.8, conversions=35),
        ("get_google_ads_performance", "mtd"): _ok(spend_eur=1000),
        ("get_ga4_performance", "yesterday"): _ok(sessions=1000, transactions=11, revenue_eur=300),
        ("get_shopify_orders_period", "yesterday"): _ok(revenue_eur=480, orders_count=12),
        ("get_shopify_orders_period", "mtd"): _ok(revenue_eur=5000),
    }


def test_regresion_0610_google_spend_no_es_meta_spend():
    # Bug 2: el LLM transcribia el spend de Meta tambien en Google. Con L3 cada
    # numero sale de su tool_result -> deben quedar distintos.
    out = assemble("performance-monitor", _results(100.0, 50.0), FakeOI(), DATE, PAID)
    assert out["platforms"]["meta"]["spend_eur"] == 100.0
    assert out["platforms"]["google_ads"]["spend_eur"] == 50.0
    assert out["platforms"]["google_ads"]["spend_eur"] != out["platforms"]["meta"]["spend_eur"]


@pytest.mark.parametrize("plat,tool,field", [
    ("meta", "get_meta_performance", "spend_eur"),
    ("meta", "get_meta_performance", "revenue_eur"),
    ("google_ads", "get_google_ads_performance", "spend_eur"),
    ("google_ads", "get_google_ads_performance", "revenue_eur"),
    ("ga4", "get_ga4_performance", "revenue_eur"),
    ("shopify", "get_shopify_orders_period", "revenue_eur"),
])
def test_campo_canonico_igual_tool_result(plat, tool, field):
    res = _results(123.45, 67.89)
    out = assemble("performance-monitor", res, FakeOI(), DATE, PAID)
    assert out["platforms"][plat][field] == res[(tool, "yesterday")]["data"][field]


def test_prosa_adversaria_no_sobreescribe_numeros():
    det = assemble("performance-monitor", _results(100.0, 50.0), FakeOI(), DATE, PAID)
    adversarial = {
        "platforms": {"meta": {"spend_eur": 999.0, "alert_detail": "x"},
                      "google_ads": {"spend_eur": 999.0}},
        "summary": "x",
    }
    out = merge_prose(det, adversarial)
    assert out["platforms"]["meta"]["spend_eur"] == 100.0
    assert out["platforms"]["google_ads"]["spend_eur"] == 50.0
