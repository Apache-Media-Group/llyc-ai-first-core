import output_registry as r

REG = r.OUTPUT_REGISTRY["budget-pacer"]

EXPECTED = {
    "actuals_mtd.spend_by_platform.{paid}", "actuals_mtd.spend_eur",
    "actuals_mtd.revenue_eur", "actuals_mtd.roas_blended",
    "rentability.roas_blended_mtd", "rentability.roas_blended_floor",
    "budget_plan.base_eur", "budget_plan.incremental_max_eur", "budget_plan.total_max_eur",
    "budget_plan.roas_floor_base", "budget_plan.roas_floor_incremental", "budget_plan.roas_blended_floor",
    "intraday.spend_today_by_platform.{paid}", "intraday.spend_today_eur",
}


def test_cubre_los_campos_deterministas():
    faltan = EXPECTED - set(REG)
    assert not faltan, f"campos deterministas sin declarar: {faltan}"


def test_sin_prose_el_juicio_lo_deja_el_LLM():
    assert not any(isinstance(v, r.Prose) for v in REG.values())


def test_todo_spec_es_de_uno_de_los_tres_tipos():
    assert all(isinstance(v, (r.Raw, r.Derived, r.Prose)) for v in REG.values())


def test_fuentes_criticas():
    assert REG["actuals_mtd.spend_by_platform.{paid}"].tool == "get_{paid}_spend_month"
    assert REG["intraday.spend_today_by_platform.{paid}"].tool == "get_{paid}_spend_today"
    assert REG["budget_plan.base_eur"].tool == "budget"
    assert REG["actuals_mtd.roas_blended"].op == "ratio"


def test_operandos_derived_resuelven():
    keys = set(REG)

    def known(o):
        if not isinstance(o, str):
            return True
        if "*paid*" in o:
            return o.replace("*paid*", "{paid}") in keys
        return o in keys

    no_res = [(k, o) for k, v in REG.items() if isinstance(v, r.Derived)
              for o in v.operands if not known(o)]
    assert not no_res, f"operandos no resueltos: {no_res}"
