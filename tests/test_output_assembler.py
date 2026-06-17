import datetime as dt
import output_assembler as A


class FakeOI:
    client_id = "vidal-vidal"
    def __init__(self, kpis):
        self._k = kpis  # {(metrica,parametro): valor}
    def kpi(self, metrica, parametro, platform=None, periodo=None):
        return self._k.get((metrica, parametro))


KPIS = {("roas", "tolerancia_desviacion_pct"): 15,
        ("cpa", "tolerancia_desviacion_pct"): 20,
        ("roas", "dinamico_minimo"): 3.0}


def _ok(**data):
    return {"status": "ok", "data": data}


def base_results():
    return {
        ("get_meta_performance", "yesterday"): _ok(spend_eur=100, revenue_eur=200, roas=2.0, conversions=10),
        ("get_meta_performance", "7d"):        _ok(spend_eur=700, revenue_eur=2800, roas=4.0, conversions=70),
        ("get_meta_performance", "mtd"):       _ok(spend_eur=2000),
        ("get_google_ads_performance", "yesterday"): _ok(spend_eur=50, revenue_eur=250, roas=5.0, conversions=5),
        ("get_google_ads_performance", "7d"):        _ok(spend_eur=350, revenue_eur=1680, roas=4.8, conversions=35),
        ("get_google_ads_performance", "mtd"):       _ok(spend_eur=1000),
        ("get_ga4_performance", "yesterday"): _ok(sessions=1000, transactions=11, revenue_eur=300),
        ("get_shopify_orders_period", "yesterday"): _ok(revenue_eur=480, orders_count=12),
        ("get_shopify_orders_period", "mtd"):       _ok(revenue_eur=5000),
    }


DATE = dt.date(2026, 6, 16)
PAID = ["meta", "google_ads"]


def run(results=None, kpis=None):
    return A.assemble("performance-monitor", results or base_results(),
                      FakeOI(kpis or KPIS), DATE, PAID)


def test_resolve_window():
    assert A.resolve_window(DATE, "yesterday") == (DATE, DATE)
    assert A.resolve_window(DATE, "7d") == (dt.date(2026, 6, 9), dt.date(2026, 6, 15))
    assert A.resolve_window(DATE, "mtd") == (dt.date(2026, 6, 1), DATE)


def test_raw_y_ratios():
    o = run()
    assert o["platforms"]["meta"]["spend_eur"] == 100
    assert o["platforms"]["meta"]["roas_yesterday"] == 2.0
    assert o["platforms"]["shopify"]["aov_eur"] == 40.0
    assert o["platforms"]["meta"]["roas_deviation_pct"] == -50.0


def test_sum_y_deltas():
    o = run()
    assert o["revenue_triangulation"]["paid_sum_eur"] == 450
    assert o["revenue_triangulation"]["delta_paid_vs_shopify_pct"] == -6.25
    assert o["revenue_triangulation"]["delta_ga4_vs_shopify_pct"] == -37.5


def test_roas_blended_y_banda():
    o = run()
    assert o["roas_blended_mtd"] == 1.67
    assert o["roas_blended_floor"] == 3.0
    assert o["roas_blended_band"] == "por_debajo"


def test_banda_None_si_floor_ausente():
    k = {kk: vv for kk, vv in KPIS.items() if kk != ("roas", "dinamico_minimo")}
    o = run(kpis=k)
    assert o["roas_blended_floor"] is None
    assert o["roas_blended_band"] is None


def test_alerta_roas_caida_supera_tolerancia():
    o = run()
    alerts = o["alerts"]
    assert len(alerts) == 1
    a = alerts[0]
    assert a["platform"] == "meta" and a["metric"] == "roas"
    assert a["threshold"] == 15 and a["deviation_pct"] == -50.0
    assert a["value"] == 2.0
    assert o["platforms"]["meta"]["status"] == "ALERTA"
    assert o["platforms"]["google_ads"]["status"] == "NORMAL"
    assert o["analysis_status"] == "ALERTA"


def test_sin_alerta_dentro_de_tolerancia():
    r = base_results()
    r[("get_meta_performance", "yesterday")] = _ok(spend_eur=100, revenue_eur=380, roas=3.8, conversions=10)
    o = A.assemble("performance-monitor", r, FakeOI(KPIS), DATE, PAID)
    assert o["alerts"] == []
    assert o["analysis_status"] == "NORMAL"
    assert o["platforms"]["meta"]["status"] == "NORMAL"


def test_alerta_cpa_subida_supera_tolerancia():
    r = base_results()
    r[("get_meta_performance", "yesterday")] = _ok(spend_eur=100, revenue_eur=400, roas=4.0, conversions=2)
    o = A.assemble("performance-monitor", r, FakeOI(KPIS), DATE, PAID)
    cpa_alerts = [a for a in o["alerts"] if a["metric"] == "cpa"]
    assert len(cpa_alerts) == 1 and cpa_alerts[0]["platform"] == "meta"


def test_shopify_error_partial_y_triangulacion_na():
    r = base_results()
    r[("get_shopify_orders_period", "yesterday")] = {"status": "error", "platform": "shopify",
                                                      "error": {"code": "HTTP_503", "message": "Shopify 503"}}
    o = A.assemble("performance-monitor", r, FakeOI(KPIS), DATE, PAID)
    assert o["execution_status"] == "PARTIAL"
    assert "shopify" in o["execution_status_detail"]
    assert o["revenue_triangulation"]["status"] == "N/A"
    assert o["platforms"]["shopify"]["status"] == "ERROR"
    assert o["platforms"]["shopify"]["error_detail"] == "Shopify 503"


def test_todo_ok_execution_ok():
    o = run()
    assert o["execution_status"] == "OK"
    assert o["execution_status_detail"] == ""
    assert o["revenue_triangulation"]["status"] == "OK"


def test_ga4_shopify_alert_detail_vacio_y_prose_none():
    o = run()
    assert o["platforms"]["ga4"]["alert_detail"] == ""
    assert o["platforms"]["shopify"]["alert_detail"] == ""
    assert o["summary"] is None
    assert o["platforms"]["meta"]["alert_detail"] is None
    assert "description" not in (o["alerts"][0] if o["alerts"] else {})


def test_metadata():
    o = run()
    assert o["agent"] == "performance-monitor"
    assert o["date"] == "2026-06-16"
    assert o["generated_at"] is None
