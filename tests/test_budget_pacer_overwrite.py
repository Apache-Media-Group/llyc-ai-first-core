import datetime as dt

from output_assembler import (
    overwrite_budget_pacer,
    _index_captured_budget_pacer,
    _overwrite_existing,
)


class FakeOI:
    def kpi(self, *a, **k):
        return None

    def budget_for(self, nivel="cuenta"):
        return {"base_eur": 23500.0, "incremental_max_eur": 5000.0,
                "total_max_eur": 28500.0, "roas_floor_base": 5.0,
                "roas_floor_incremental": 3.0, "roas_blended_floor": 4.65}


def _ok(**d):
    return {"status": "ok", "data": d}


DATE = dt.date(2026, 6, 16)
PAID = ["meta", "google_ads"]


def test_index_captured_mapea_ventanas_intrinsecas():
    idx = _index_captured_budget_pacer([
        {"tool": "get_meta_spend_month", "input": {}, "result": _ok(spend_month_eur=1)},
        {"tool": "get_meta_spend_today", "input": {}, "result": _ok(spend_today_eur=2)},
        {"tool": "get_shopify_orders_period", "input": {}, "result": _ok(revenue_eur=3)},
        {"tool": "get_meta_active_campaigns", "input": {}, "result": _ok()},
    ])
    assert ("get_meta_spend_month", "mtd") in idx
    assert ("get_meta_spend_today", "today") in idx
    assert ("get_shopify_orders_period", "mtd") in idx
    assert len(idx) == 3


def test_overwrite_existing_no_anade_claves_y_None_sobreescribe():
    t = {"a": 1, "b": {"x": 1, "y": 2}, "c": 3}
    _overwrite_existing(t, {"a": 10, "b": {"x": 100, "z": 9}, "d": 4})
    assert t["a"] == 10 and t["b"]["x"] == 100 and t["b"]["y"] == 2
    assert "z" not in t["b"] and "d" not in t
    t2 = {"a": 5}
    _overwrite_existing(t2, {"a": None})
    assert t2["a"] is None


def test_overwrite_monthly_fija_numeros_y_respeta_juicio():
    captured = [
        {"tool": "get_meta_spend_month", "input": {}, "result": _ok(spend_month_eur=8000.0)},
        {"tool": "get_google_ads_spend_month", "input": {}, "result": _ok(spend_month_eur=4000.0)},
        {"tool": "get_shopify_orders_period", "input": {}, "result": _ok(revenue_eur=50000.0)},
    ]
    out = {
        "agent": "budget-pacer",
        "actuals_mtd": {"spend_eur": 999.0, "revenue_eur": 999.0, "roas_blended": 9.9,
                        "spend_by_platform": {"meta": 999.0, "google_ads": 999.0}},
        "budget_plan": {"base_eur": 1.0, "incremental_max_eur": 1.0, "total_max_eur": 1.0,
                        "roas_floor_base": 1.0, "roas_floor_incremental": 1.0,
                        "roas_blended_floor": 1.0, "source": "workbook"},
        "rentability": {"status": "OK", "roas_blended_mtd": 9.9, "roas_blended_floor": 1.0,
                        "meets_blended_floor": True, "detail": "juicio LLM"},
        "pacing": {"status": "WITHIN_BAND", "projected_month_spend_eur": 777.0,
                   "deviation_pct": 0.0, "detail": "juicio LLM"},
        "period": {"month": "2026-06", "days_elapsed": 16, "days_in_month": 30, "pace_fraction": 0.53},
        "summary": "s", "alerts": [],
    }
    overwrite_budget_pacer(out, captured, FakeOI(), DATE, PAID)
    assert out["actuals_mtd"]["spend_by_platform"]["meta"] == 8000.0
    assert out["actuals_mtd"]["spend_by_platform"]["google_ads"] == 4000.0
    assert out["actuals_mtd"]["spend_eur"] == 12000.0
    assert out["actuals_mtd"]["revenue_eur"] == 50000.0
    assert abs(out["actuals_mtd"]["roas_blended"] - 4.17) < 0.01
    assert out["budget_plan"]["base_eur"] == 23500.0
    assert out["budget_plan"]["total_max_eur"] == 28500.0
    assert out["budget_plan"]["roas_blended_floor"] == 4.65
    assert out["rentability"]["roas_blended_floor"] == 4.65
    assert abs(out["rentability"]["roas_blended_mtd"] - 4.17) < 0.01
    # juicio del LLM intacto
    assert out["rentability"]["status"] == "OK"
    assert out["rentability"]["meets_blended_floor"] is True
    assert out["rentability"]["detail"] == "juicio LLM"
    assert out["pacing"]["projected_month_spend_eur"] == 777.0
    assert out["pacing"]["detail"] == "juicio LLM"
    assert out["budget_plan"]["source"] == "workbook"
    assert "intraday" not in out


def test_overwrite_intraday_fija_spend_today():
    captured = [
        {"tool": "get_meta_spend_today", "input": {}, "result": _ok(spend_today_eur=300.0)},
        {"tool": "get_google_ads_spend_today", "input": {}, "result": _ok(spend_today_eur=150.0)},
    ]
    out = {
        "agent": "budget-pacer",
        "intraday": {"spend_today_eur": 99.0,
                     "spend_today_by_platform": {"meta": 99.0, "google_ads": 99.0},
                     "underspend_floor_eur": 100.0, "overspend_ceiling_eur": 200.0,
                     "status": "WITHIN", "platform_dark": [], "detail": "juicio LLM"},
        "summary": "s", "alerts": [],
    }
    overwrite_budget_pacer(out, captured, FakeOI(), DATE, PAID)
    assert out["intraday"]["spend_today_by_platform"]["meta"] == 300.0
    assert out["intraday"]["spend_today_by_platform"]["google_ads"] == 150.0
    assert out["intraday"]["spend_today_eur"] == 450.0
    assert out["intraday"]["underspend_floor_eur"] == 100.0
    assert out["intraday"]["status"] == "WITHIN"
    assert out["intraday"]["detail"] == "juicio LLM"
    assert "actuals_mtd" not in out
