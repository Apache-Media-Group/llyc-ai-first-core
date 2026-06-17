import output_registry as r

REG = r.OUTPUT_REGISTRY["performance-monitor"]

# Claves EMITIDAS del contrato real (performance_monitor.md v2.1 + template).
EXPECTED_EMITTED = {
    "agent", "client", "date", "generated_at",
    "execution_status", "execution_status_detail", "analysis_status", "summary",
    "platforms.{paid}.status", "platforms.{paid}.spend_eur", "platforms.{paid}.revenue_eur",
    "platforms.{paid}.roas_yesterday", "platforms.{paid}.roas_7d_avg",
    "platforms.{paid}.roas_deviation_pct", "platforms.{paid}.cpa_yesterday_eur",
    "platforms.{paid}.cpa_7d_avg_eur", "platforms.{paid}.cpa_deviation_pct",
    "platforms.{paid}.alert_detail", "platforms.{paid}.error_detail",
    "platforms.ga4.sessions", "platforms.ga4.transactions", "platforms.ga4.revenue_eur",
    "platforms.ga4.status", "platforms.ga4.alert_detail", "platforms.ga4.error_detail",
    "platforms.shopify.status",
    "platforms.shopify.revenue_eur", "platforms.shopify.orders_count", "platforms.shopify.aov_eur",
    "platforms.shopify.alert_detail", "platforms.shopify.error_detail",
    "revenue_triangulation.status",
    "revenue_triangulation.shopify_eur", "revenue_triangulation.paid_sum_eur",
    "revenue_triangulation.ga4_eur", "revenue_triangulation.delta_paid_vs_shopify_pct",
    "revenue_triangulation.delta_ga4_vs_shopify_pct", "revenue_triangulation.detail",
    "alerts", "alerts[].description",
    "roas_blended_mtd", "roas_blended_floor", "roas_blended_band", "roas_blended_recommendation",
}

EXPECTED_PROSE = {
    "summary", "platforms.{paid}.alert_detail", "revenue_triangulation.detail",
    "alerts[].description", "roas_blended_recommendation",
}


def test_cubre_el_contrato_de_output_real():
    faltan = EXPECTED_EMITTED - set(REG)
    assert not faltan, f"claves del contrato sin declarar: {faltan}"


def test_todo_spec_es_de_uno_de_los_tres_tipos():
    assert all(isinstance(v, (r.Raw, r.Derived, r.Prose)) for v in REG.values())


def test_categorias_criticas():
    assert isinstance(REG["platforms.shopify.revenue_eur"], r.Raw)
    assert isinstance(REG["roas_blended_mtd"], r.Derived)
    assert REG["roas_blended_mtd"].op == "ratio"
    assert isinstance(REG["summary"], r.Prose)


def test_ga4_shopify_alert_detail_no_es_prose():
    assert isinstance(REG["platforms.ga4.alert_detail"], r.Derived)
    assert isinstance(REG["platforms.shopify.alert_detail"], r.Derived)


def test_prose_es_exactamente_el_conjunto_esperado():
    prose = {k for k, v in REG.items() if isinstance(v, r.Prose)}
    assert prose == EXPECTED_PROSE, f"prose divergente: {prose ^ EXPECTED_PROSE}"


def test_operandos_derived_resuelven():
    keys = set(REG)

    def known(o):
        if not isinstance(o, str):
            return True
        if o.startswith("workbook:"):
            return True
        if o in ("agent", "client", "date", "generated_at"):
            return True
        if o in ("{paid}", "meta", "google_ads", "ga4", "shopify"):
            return True
        if "*paid*" in o:
            return o.replace("*paid*", "{paid}") in keys
        return o in keys

    no_resueltos = [
        (k, o)
        for k, v in REG.items()
        if isinstance(v, r.Derived)
        for o in v.operands
        if not known(o)
    ]
    assert not no_resueltos, f"operandos no resueltos: {no_resueltos}"
