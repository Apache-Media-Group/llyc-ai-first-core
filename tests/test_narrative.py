import datetime as dt
import narrative as N
import output_assembler as A


class FakeOI:
    client_id = "vidal-vidal"
    def kpi(self, m, p, platform=None, periodo=None):
        return {("roas", "tolerancia_desviacion_pct"): 15,
                ("cpa", "tolerancia_desviacion_pct"): 20}.get((m, p))
    def budget_for(self, platform=None):
        return {"roas_blended_floor": 3.0}


def _ok(**d):
    return {"status": "ok", "data": d}


def deterministic():
    results = {
        ("get_meta_performance", "yesterday"): _ok(spend_eur=100, revenue_eur=200, roas=2.0, conversions=10),
        ("get_meta_performance", "7d"): _ok(spend_eur=700, revenue_eur=2800, roas=4.0, conversions=70),
        ("get_meta_performance", "mtd"): _ok(spend_eur=2000),
        ("get_google_ads_performance", "yesterday"): _ok(spend_eur=50, revenue_eur=250, roas=5.0, conversions=5),
        ("get_google_ads_performance", "7d"): _ok(spend_eur=350, revenue_eur=1680, roas=4.8, conversions=35),
        ("get_google_ads_performance", "mtd"): _ok(spend_eur=1000),
        ("get_ga4_performance", "yesterday"): _ok(sessions=1000, transactions=11, revenue_eur=300),
        ("get_shopify_orders_period", "yesterday"): _ok(revenue_eur=480, orders_count=12),
        ("get_shopify_orders_period", "mtd"): _ok(revenue_eur=5000),
    }
    return A.assemble("performance-monitor", results, FakeOI(), dt.date(2026, 6, 16), ["meta", "google_ads"])


def test_merge_rellena_solo_prose():
    d = deterministic()
    prose = {
        "summary": "  Meta ROAS cae 50%.  ",
        "roas_blended_recommendation": "Blended por debajo del floor.",
        "revenue_triangulation": {"detail": "Deltas nominales."},
        "platforms": {"meta": {"alert_detail": "ROAS 2.0 vs 4.0 (-50%, umbral -15%)."}},
        "alerts": [{"platform": "meta", "metric": "roas", "description": "Caida pronunciada."}],
    }
    out = N.merge_prose(d, prose)
    assert out["summary"] == "Meta ROAS cae 50%."
    assert out["roas_blended_recommendation"] == "Blended por debajo del floor."
    assert out["revenue_triangulation"]["detail"] == "Deltas nominales."
    assert out["platforms"]["meta"]["alert_detail"].startswith("ROAS 2.0")
    assert out["alerts"][0]["description"] == "Caida pronunciada."


def test_llm_no_puede_pisar_numeros():
    d = deterministic()
    real_spend = d["platforms"]["meta"]["spend_eur"]
    real_roas = d["roas_blended_mtd"]
    prose = {
        "summary": "x",
        "platforms": {"meta": {"alert_detail": "y", "spend_eur": 99999, "revenue_eur": 0}},
        "roas_blended_mtd": 999, "alerts": [],
    }
    out = N.merge_prose(d, prose)
    assert out["platforms"]["meta"]["spend_eur"] == real_spend
    assert out["roas_blended_mtd"] == real_roas
    assert out["platforms"]["meta"]["alert_detail"] == "y"


def test_merge_no_toca_alert_detail_de_ga4_shopify():
    d = deterministic()
    out = N.merge_prose(d, {"summary": "s"})
    assert out["platforms"]["ga4"]["alert_detail"] == ""
    assert out["platforms"]["shopify"]["alert_detail"] == ""


def test_metrics_block_lleva_los_numeros_clave():
    d = deterministic()
    blk = N.build_metrics_block(d)
    assert "spend=100" in blk and "revenue=200" in blk
    assert "SHOPIFY (ground truth): revenue=480" in blk
    assert "blended=1.67" in blk and "floor=3.0" in blk
    assert "meta roas: valor=2.0 umbral=15 dev=-50.0%" in blk
