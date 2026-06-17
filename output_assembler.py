"""
output_assembler.py — Ensamblador determinista (brief §9 step 3, T3).

Dado OUTPUT_REGISTRY[agente] + resultados de tools indexados por (tool, window)
+ OperationalInputs (oi, DEC_075) + fecha de análisis + plataformas paid activas,
computa TODOS los campos raw/derived del contrato, dispara alerts[] contra los
umbrales del workbook y deriva los status (modelo dual DEC_072). Devuelve el dict
de campos deterministas; los 5 campos prose los rellena el LLM (T5) y se mergean
aparte.

READ-ONLY (DEC_022): solo lee y describe. No decide, no prescribe, no escribe.

Contrato de entrada `results`: dict {(tool_name, window): result_dict}, donde
result_dict es el dict nativo devuelto por la tool (capturado en T1 / producido
por el orquestador L3 en T4). result["status"] == "error" marca fallo de fuente.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from output_registry import OUTPUT_REGISTRY, Raw, Derived, Prose

# Parámetro del workbook que codifica la tolerancia de desviación (confirmado
# contra kpis de V&V, 2026-06-17). El doc de la capa dice "tolerancia_desv_pct"
# (typo); la fuente viva y el prompt v2.1 usan "tolerancia_desviacion_pct".
TOL_PARAM = "tolerancia_desviacion_pct"
FLOOR_PARAM = "dinamico_minimo"  # roas blended floor (nivel cuenta), DEC_062

PAID = ("meta", "google_ads")


# ----------------------------- ventanas -----------------------------


def resolve_window(analysis_date: _dt.date, window: str) -> tuple[_dt.date, _dt.date]:
    """analysis_date = día a analizar (ya es 'el día anterior' del run).
    yesterday = [analysis_date, analysis_date]; 7d = 7 días previos NO inclusivos;
    mtd = [primero de mes, analysis_date]. (prompt v2.1 §Contexto temporal)."""
    if window == "yesterday":
        return analysis_date, analysis_date
    if window == "7d":
        return analysis_date - _dt.timedelta(days=7), analysis_date - _dt.timedelta(days=1)
    if window == "mtd":
        return analysis_date.replace(day=1), analysis_date
    raise ValueError(f"ventana desconocida: {window}")


# ----------------------------- helpers de acceso -----------------------------


def _dig(d: Any, path: str) -> Optional[Any]:
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _is_error(result: Optional[dict]) -> bool:
    return not isinstance(result, dict) or result.get("status") == "error"


def _pct_change(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / b * 100, 2)


def _ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return round(a / b, 2)


# ----------------------------- ensamblador -----------------------------


class Assembler:
    def __init__(self, agent_key, results, oi, analysis_date, enabled_paid):
        self.spec = OUTPUT_REGISTRY[agent_key]
        self.results = results
        self.oi = oi
        self.date = analysis_date
        self.paid = [p for p in PAID if p in enabled_paid]
        self._memo: dict[str, Any] = {}
        self._stack: set[str] = set()

    def _expand(self, key: str, paid: Optional[str]) -> str:
        return key.replace("{paid}", paid) if paid and "{paid}" in key else key

    def _spec_for(self, key: str):
        # key concreta -> buscar su spec (plantilla {paid} o literal)
        if key in self.spec:
            return self.spec[key], None
        for p in self.paid:
            tmpl = key.replace(p, "{paid}", 1)
            if "{paid}" in tmpl and tmpl in self.spec:
                return self.spec[tmpl], p
        return None, None

    def value(self, key: str) -> Any:
        if key in self._memo:
            return self._memo[key]
        if key in self._stack:
            raise ValueError(f"ciclo en operandos: {key}")
        self._stack.add(key)
        spec, paid = self._spec_for(key)
        val = None if spec is None else self._eval(key, spec, paid)
        self._stack.discard(key)
        self._memo[key] = val
        return val

    def _eval(self, key, spec, paid):
        if isinstance(spec, Prose):
            return None  # lo rellena el LLM (T5)
        if isinstance(spec, Raw):
            return self._eval_raw(spec, paid)
        if isinstance(spec, Derived):
            return self._eval_derived(key, spec, paid)
        return None

    def _eval_raw(self, spec: Raw, paid):
        if spec.tool == "workbook":
            metrica, parametro = spec.path.split(".")
            level = None if spec.window in ("cuenta", "n/a", "") else spec.window
            return self.oi.kpi(metrica, parametro, platform=level)
        if spec.tool == "budget":
            # floor blended ponderado del tab budget (mes en curso), DEC_061/062.
            # oi.budget_for devuelve el bloque por nivel; None en fallback -> banda null.
            blk = self.oi.budget_for(spec.window)
            return (blk or {}).get(spec.path)
        tool = self._expand(spec.tool, paid)
        result = self.results.get((tool, spec.window))
        if _is_error(result):
            return None
        return _dig(result, spec.path)

    def _eval_derived(self, key, spec: Derived, paid):
        op, ops = spec.op, [self._expand(o, paid) for o in spec.operands]
        if op == "metadata":
            return {"agent": self.spec_agent(), "client": self.client(),
                    "date": self.date.isoformat(),
                    "generated_at": None}.get(ops[0])  # generated_at lo pone el executor
        if op == "alias":
            return self.value(ops[0])
        if op == "ratio":
            return _ratio(self.value(ops[0]), self.value(ops[1]))
        if op == "pct_change":
            return _pct_change(self.value(ops[0]), self.value(ops[1]))
        if op == "delta_pct_vs":
            return _pct_change(self.value(ops[0]), self.value(ops[1]))
        if op == "sum":
            glob = spec.operands[0]
            vals = [self.value(glob.replace("*paid*", p)) for p in self.paid]
            vals = [v for v in vals if isinstance(v, (int, float))]
            return round(sum(vals), 2) if vals else None
        if op == "const_empty":
            return ""
        if op == "tool_error_message":
            return self._tool_error(ops[0])
        if op == "source_status":
            r = self.results.get((self._tool_for_platform(ops[0]), "yesterday"))
            return "ERROR" if _is_error(r) else "NORMAL"
        if op == "band_vs_floor":
            return self._band(self.value(ops[0]), self.value(ops[1]))
        if op == "triangulation_status":
            sh = self.results.get(("get_shopify_orders_period", "yesterday"))
            return "N/A" if _is_error(sh) else "OK"
        if op == "alerts_from_thresholds":
            return self._alerts()
        if op == "platform_status":
            return self._platform_status(paid)
        if op == "execution_status":
            return self._execution_status()
        if op == "execution_status_detail":
            return self._execution_detail()
        if op == "analysis_status":
            return "ALERTA" if self.value("alerts") else "NORMAL"
        return None

    def spec_agent(self):
        return next(iter(OUTPUT_REGISTRY))  # único agente en el mapa por ahora

    def client(self):
        return getattr(self.oi, "client_id", None)

    def _tool_for_platform(self, plat):
        return {"meta": "get_meta_performance", "google_ads": "get_google_ads_performance",
                "ga4": "get_ga4_performance", "shopify": "get_shopify_orders_period"}[plat]

    def _tool_error(self, plat):
        r = self.results.get((self._tool_for_platform(plat), "yesterday"))
        if _is_error(r) and isinstance(r, dict):
            return (r.get("error") or {}).get("message", "")
        return ""

    def _tol(self, metrica, plat):
        return self.oi.kpi(metrica, TOL_PARAM, platform=plat)

    def _alerts(self):
        out = []
        for p in self.paid:
            if _is_error(self.results.get((self._tool_for_platform(p), "yesterday"))):
                continue
            roas_dev = self.value(f"platforms.{p}.roas_deviation_pct")
            tol_roas = self._tol("roas", p)
            # ROAS: desviación ADVERSA = caída; |dev| > tolerancia
            if roas_dev is not None and tol_roas is not None and roas_dev < 0 and abs(roas_dev) > tol_roas:
                out.append({"platform": p, "metric": "roas",
                            "value": self.value(f"platforms.{p}.roas_yesterday"),
                            "threshold": tol_roas, "deviation_pct": roas_dev})
            cpa_dev = self.value(f"platforms.{p}.cpa_deviation_pct")
            tol_cpa = self._tol("cpa", p)
            # CPA: desviación ADVERSA = subida; dev > tolerancia
            if cpa_dev is not None and tol_cpa is not None and cpa_dev > 0 and cpa_dev > tol_cpa:
                out.append({"platform": p, "metric": "cpa",
                            "value": self.value(f"platforms.{p}.cpa_yesterday_eur"),
                            "threshold": tol_cpa, "deviation_pct": cpa_dev})
        return out

    def _platform_status(self, plat):
        if _is_error(self.results.get((self._tool_for_platform(plat), "yesterday"))):
            return "ERROR"
        fired = any(a["platform"] == plat for a in self.value("alerts"))
        return "ALERTA" if fired else "NORMAL"

    def _band(self, v, floor):
        if v is None or floor is None:
            return None  # floor ausente (p.ej. fallback) -> banda N/A
        if v < floor:
            return "por_debajo"
        if v <= floor * 1.05:
            return "en_torno"
        return "por_encima"

    def _sources_status(self):
        # PARTIAL si alguna fuente falla; ERROR si todas; OK si ninguna.
        checks = {
            "shopify": ("get_shopify_orders_period", "yesterday"),
            "ga4": ("get_ga4_performance", "yesterday"),
            **{p: (self._tool_for_platform(p), "yesterday") for p in self.paid},
        }
        failed = [s for s, k in checks.items() if _is_error(self.results.get(k))]
        return failed, len(failed) == len(checks)

    def _execution_status(self):
        failed, all_failed = self._sources_status()
        if all_failed:
            return "ERROR"
        if failed:
            return "PARTIAL"
        return "OK"

    def _execution_detail(self):
        failed, _ = self._sources_status()
        return "" if not failed else "Fuente(s) sin datos: " + ", ".join(sorted(failed))


def assemble(agent_key, results, oi, analysis_date, enabled_paid) -> dict:
    """Devuelve los campos deterministas en estructura anidada del contrato.
    Los 5 campos prose quedan como None (los rellena el LLM en T5)."""
    a = Assembler(agent_key, results, oi, analysis_date, enabled_paid)
    out: dict = {}
    for key in a.spec:
        if "._" in key or key.startswith("_"):
            continue  # intermedios no emitidos
        if key == "alerts[].description":
            continue  # se rellena por-alerta en el merge prose (T5)
        if "{paid}" in key:
            concrete = [key.replace("{paid}", p) for p in a.paid]
        else:
            concrete = [key]
        for ck in concrete:
            _set_nested(out, ck, a.value(ck))
    return out


def _set_nested(out: dict, dotted: str, value: Any):
    parts = dotted.split(".")
    cur = out
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


# ─── T10: overwrite determinista de budget-pacer (NO L3; sigue en loop) ───────


def _index_captured_budget_pacer(captured: list) -> dict:
    """Lista [{tool, input, result}] -> {(tool, window): result} para budget-pacer.
    Ventana intrinseca por tool: *_spend_month -> mtd, *_spend_today -> today,
    get_shopify_orders_period -> mtd (budget-pacer monthly llama Shopify una vez).
    Tool set acotado (DEC_059) -> una llamada por tool/perfil, sin ambiguedad."""
    idx: dict = {}
    for c in captured:
        tool = c.get("tool", "")
        if tool.endswith("_spend_month"):
            win = "mtd"
        elif tool.endswith("_spend_today"):
            win = "today"
        elif tool == "get_shopify_orders_period":
            win = "mtd"
        else:
            continue
        idx[(tool, win)] = c.get("result")
    return idx


def _overwrite_existing(target: dict, source: dict) -> dict:
    """Sobreescribe en target los leaf que existen en source. Solo claves YA
    presentes en target (preserva contrato; NO anade claves nuevas). Recursivo en
    dicts. Un leaf None de source SI sobreescribe (fuente fallida -> el numero del
    LLM no debe quedarse). Perfil por presencia: campos ausentes en el output del
    LLM (p.ej. intraday en monthly) no se tocan."""
    if not isinstance(target, dict) or not isinstance(source, dict):
        return target
    for k, sv in source.items():
        if k not in target:
            continue
        tv = target[k]
        if isinstance(sv, dict) and isinstance(tv, dict):
            _overwrite_existing(tv, sv)
        else:
            target[k] = sv
    return target


def overwrite_budget_pacer(output, captured, oi, analysis_date, enabled_paid) -> dict:
    """T10: garantiza los numeros deterministas de budget-pacer sin sacarlo del loop.
    Indexa la lista capturada por (tool, ventana intrinseca), computa los campos del
    registry 'budget-pacer' con assemble(), y SOBREESCRIBE en el output del LLM solo
    las claves ya presentes. El juicio del LLM (pacing.status/deviation/detail,
    rentability.status/meets/detail, analysis_status, alerts, summary, period,
    projection) queda intacto. Perfil por presencia (monthly/intraday)."""
    idx = _index_captured_budget_pacer(captured)
    det = assemble("budget-pacer", idx, oi, analysis_date, enabled_paid)
    return _overwrite_existing(output, det)
