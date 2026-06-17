import datetime as dt
import orchestrator as O
from output_registry import OUTPUT_REGISTRY

SPEC = OUTPUT_REGISTRY["performance-monitor"]
DATE = dt.date(2026, 6, 16)
PAID = ["meta", "google_ads"]
CONFIG = {"platforms": {
    "meta": {"ad_account_id": "2466105110293178"},
    "google_ads": {"customer_id": "2756616331"},
    "ga4": {"property_id": "267182121"},
    "shopify": {"dtc_filter": {"source_name": "web", "excluded_source_names": ["X"]}},
}}


class FakeHandler:
    def __init__(self):
        self.calls = []
    def __call__(self, tool, tool_input):
        self.calls.append((tool, tool_input))
        return {"status": "ok", "data": {"_tool": tool}}


def test_plan_cubre_los_9_pares_esperados():
    h = FakeHandler()
    results = O.orchestrate_l3(SPEC, h, CONFIG, DATE, PAID)
    esperado = {
        ("get_meta_performance", "yesterday"), ("get_meta_performance", "7d"), ("get_meta_performance", "mtd"),
        ("get_google_ads_performance", "yesterday"), ("get_google_ads_performance", "7d"), ("get_google_ads_performance", "mtd"),
        ("get_ga4_performance", "yesterday"),
        ("get_shopify_orders_period", "yesterday"), ("get_shopify_orders_period", "mtd"),
    }
    assert set(results) == esperado


def test_tool_input_por_tool():
    h = FakeHandler()
    O.orchestrate_l3(SPEC, h, CONFIG, DATE, PAID)
    meta_y = next(i for t, i in h.calls if t == "get_meta_performance" and i["date_start"] == "2026-06-16")
    assert meta_y["ad_account_id"] == "2466105110293178" and meta_y["metrics"] == [] and meta_y["date_end"] == "2026-06-16"
    g_7d = next(i for t, i in h.calls if t == "get_google_ads_performance" and i["date_start"] == "2026-06-09")
    assert g_7d["customer_id"] == "2756616331" and g_7d["date_end"] == "2026-06-15"
    ga4 = [i for t, i in h.calls if t == "get_ga4_performance"]
    assert len(ga4) == 1 and ga4[0]["property_id"] == "267182121"
    sh_mtd = next(i for t, i in h.calls if t == "get_shopify_orders_period" and i["date_start"] == "2026-06-01")
    assert sh_mtd["dtc_filter"] == {"source_name": "web", "excluded_source_names": ["X"]}
    assert sh_mtd["date_end"] == "2026-06-16"
    assert all("access_token" not in i and "token" not in i for _, i in h.calls)


def test_results_alimentan_al_ensamblador():
    h = FakeHandler()
    results = O.orchestrate_l3(SPEC, h, CONFIG, DATE, PAID)
    assert all(isinstance(k, tuple) and len(k) == 2 for k in results)
    assert all(r["status"] == "ok" for r in results.values())


def test_no_importa_anthropic():
    # un `import anthropic` real bindearia el simbolo en el namespace del modulo
    assert "anthropic" not in dir(O)
