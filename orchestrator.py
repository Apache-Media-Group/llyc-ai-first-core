"""
orchestrator.py — Orquestador L3 para perf-monitor (brief §9 step 4, T4).

Deriva el plan de llamadas del propio OUTPUT_REGISTRY (cada spec `raw` con tool
real -> un par (tool, window)), resuelve cada ventana a fechas, construye el
tool_input completo (IDs de config + fechas + metrics/dtc_filter) y llama los
tools DIRECTAMENTE via el handler existente (tool_handler_factory: reusa init
de clients, secrets y retry). NO hay loop tool_use, NO hay messages.create: este
modulo no llama al LLM.

Devuelve results = {(tool_name, window): result_dict} -- exactamente el contrato
de entrada que consume output_assembler.assemble().

READ-ONLY (DEC_022): solo lecturas de plataforma.
"""
from __future__ import annotations

import datetime as _dt
from typing import Callable

from output_registry import Raw
from output_assembler import resolve_window


def _plan(spec: dict, enabled_paid: list[str]) -> set[tuple[str, str]]:
    """Pares (tool, window) distintos que el registry necesita leer.
    Expande {paid} sobre las paid activas; ignora el pseudo-tool 'workbook'."""
    pairs: set[tuple[str, str]] = set()
    for s in spec.values():
        if isinstance(s, Raw) and s.tool != "workbook":
            if "{paid}" in s.tool:
                for p in enabled_paid:
                    pairs.add((s.tool.replace("{paid}", p), s.window))
            else:
                pairs.add((s.tool, s.window))
    return pairs


def _tool_input(tool: str, config: dict, start: _dt.date, end: _dt.date) -> dict:
    """tool_input no-secreto por tool: IDs de config + fechas (+ metrics/dtc_filter).
    Alinea con `required` del input_schema (tools/definitions.py)."""
    p = config.get("platforms", {})
    ds, de = start.isoformat(), end.isoformat()
    if tool == "get_meta_performance":
        return {"ad_account_id": p["meta"]["ad_account_id"],
                "date_start": ds, "date_end": de, "metrics": []}
    if tool == "get_google_ads_performance":
        return {"customer_id": p["google_ads"]["customer_id"],
                "date_start": ds, "date_end": de, "metrics": []}
    if tool == "get_ga4_performance":
        return {"property_id": p["ga4"]["property_id"],
                "date_start": ds, "date_end": de, "metrics": []}
    if tool == "get_shopify_orders_period":
        # dtc_filter obligatorio de facto: sin el, revenue ground-truth sin aislar
        # DTC (incluiria wholesale/ECI) -> triangulacion incorrecta (DEC_048/049).
        return {"date_start": ds, "date_end": de,
                "dtc_filter": p.get("shopify", {}).get("dtc_filter")}
    raise ValueError(f"sin builder de tool_input para {tool}")


def orchestrate_l3(
    spec: dict,
    handler: Callable[[str, dict], dict],
    config: dict,
    analysis_date: _dt.date,
    enabled_paid: list[str],
) -> dict:
    """Llama los tools directamente y devuelve results{(tool,window)}.
    Sin loop tool_use, sin LLM. Orden determinista (sorted) para trazas estables."""
    results: dict[tuple[str, str], dict] = {}
    for tool, window in sorted(_plan(spec, enabled_paid)):
        start, end = resolve_window(analysis_date, window)
        results[(tool, window)] = handler(tool, _tool_input(tool, config, start, end))
    return results
