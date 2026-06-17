"""
OUTPUT_REGISTRY — mapa declarativo raw/derived/prose por agente (brief §5/§6, T2).

Dato puro: ninguna lógica vive aquí. El ensamblador determinista (T3) recorre
este registry + los tool_result capturados (T1) + el objeto OperationalInputs
(workbook, DEC_075) y computa cada campo. Forward-compatible: un agente N+1 se
añade declarando su mapa, sin lógica nueva mientras reutilice el vocabulario de ops.

Claves y shape ALINEADOS al contrato de output real (system_prompts/
performance_monitor.md v2.1 + email_templates/performance_monitor.html):
invariante #1 — el render Jinja (StrictUndefined) consume estas claves tal cual.

Tres tipos de spec (brief §6):
  raw(tool, window, path)   lectura directa de un tool_result
  derived(op, *operands)    cómputo determinista; operandos referencian otros
                            campos ya computados (orden topológico) o literales
  prose()                   único territorio del LLM

Convenciones de clave:
  {paid}                placeholder expandido por T3 a cada plataforma paid activa
  platforms.*paid*.X    glob sobre las plataformas paid (para sum/agg)
  prefijo _             campo intermedio: se computa pero NO se emite al output
                        (conversiones, spend 7d/mtd usados solo como operandos)

Ventanas: "yesterday" | "7d" | "mtd" — T3 las resuelve a fechas desde la fecha
de análisis.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Raw:
    tool: str
    window: str
    path: str
    category: str = "raw"


@dataclass(frozen=True)
class Derived:
    op: str
    operands: tuple
    category: str = "derived"


@dataclass(frozen=True)
class Prose:
    category: str = "prose"


def raw(tool: str, window: str, path: str) -> Raw:
    return Raw(tool=tool, window=window, path=path)


def derived(op: str, *operands) -> Derived:
    return Derived(op=op, operands=tuple(operands))


def prose() -> Prose:
    return Prose()


# Vocabulario de ops derived que T3 debe implementar (cerrado; ampliar = decisión):
#   metadata(key)            metadata del ejecutor
#   alias(field)             copia de otro campo ya computado
#   ratio(a, b)              a / b
#   pct_change(a, b)         (a - b) / b * 100
#   sum(glob)                Σ sobre el glob de campos paid
#   delta_pct_vs(x, base)    (x - base) / base * 100
#   band_vs_floor(v, floor)  por_encima / en_torno / por_debajo
#   execution_status         helper DEC_072 (data completeness)
#   execution_status_detail  qué fuente(s) faltan
#   analysis_status          >=1 alerta disparada -> ALERTA
#   platform_status(dev...)  desviación vs umbral del workbook (oi.kpi)
#   source_status(plat)      NORMAL / ERROR (fuente no-paid: ga4, shopify)
#   triangulation_status     OK / N/A (N/A si Shopify falla)
#   tool_error_message(plat) mensaje del tool_result en error
#   const_empty              constante "" (clave presente exigida por contrato, sin contenido)
#   alerts_from_thresholds   construye alerts[] (platform/metric/value/threshold/deviation_pct)

OUTPUT_REGISTRY: dict[str, dict[str, object]] = {
    "performance-monitor": {
        # ── metadata ────────────────────────────────────────────────────────
        "agent":                 derived("metadata", "agent"),
        "client":                derived("metadata", "client"),
        "date":                  derived("metadata", "date"),
        "generated_at":          derived("metadata", "generated_at"),
        # ── statuses (modelo dual DEC_072) ───────────────────────────────────
        "execution_status":          derived("execution_status"),
        "execution_status_detail":   derived("execution_status_detail"),
        "analysis_status":           derived("analysis_status"),
        "summary":                   prose(),
        # ── plataformas paid (expandir {paid} -> meta, google_ads) ───────────
        "platforms.{paid}.status":             derived("platform_status", "platforms.{paid}.roas_deviation_pct", "platforms.{paid}.cpa_deviation_pct"),
        "platforms.{paid}.spend_eur":          raw("get_{paid}_performance", "yesterday", "data.spend_eur"),
        "platforms.{paid}.revenue_eur":        raw("get_{paid}_performance", "yesterday", "data.revenue_eur"),
        "platforms.{paid}._conversions_yday":  raw("get_{paid}_performance", "yesterday", "data.conversions"),
        "platforms.{paid}._spend_7d":          raw("get_{paid}_performance", "7d", "data.spend_eur"),
        "platforms.{paid}._conversions_7d":    raw("get_{paid}_performance", "7d", "data.conversions"),
        "platforms.{paid}.roas_yesterday":     derived("ratio", "platforms.{paid}.revenue_eur", "platforms.{paid}.spend_eur"),
        "platforms.{paid}.roas_7d_avg":        raw("get_{paid}_performance", "7d", "data.roas"),
        "platforms.{paid}.roas_deviation_pct": derived("pct_change", "platforms.{paid}.roas_yesterday", "platforms.{paid}.roas_7d_avg"),
        "platforms.{paid}.cpa_yesterday_eur":  derived("ratio", "platforms.{paid}.spend_eur", "platforms.{paid}._conversions_yday"),
        "platforms.{paid}.cpa_7d_avg_eur":     derived("ratio", "platforms.{paid}._spend_7d", "platforms.{paid}._conversions_7d"),
        "platforms.{paid}.cpa_deviation_pct":  derived("pct_change", "platforms.{paid}.cpa_yesterday_eur", "platforms.{paid}.cpa_7d_avg_eur"),
        "platforms.{paid}.alert_detail":       prose(),
        "platforms.{paid}.error_detail":       derived("tool_error_message", "{paid}"),
        # ── GA4 (proxy de atribución; no dispara alerta) ─────────────────────
        "platforms.ga4.sessions":      raw("get_ga4_performance", "yesterday", "data.sessions"),
        "platforms.ga4.transactions":  raw("get_ga4_performance", "yesterday", "data.transactions"),
        "platforms.ga4.revenue_eur":   raw("get_ga4_performance", "yesterday", "data.revenue_eur"),
        "platforms.ga4.status":        derived("source_status", "ga4"),
        "platforms.ga4.alert_detail":  derived("const_empty"),
        "platforms.ga4.error_detail":  derived("tool_error_message", "ga4"),
        # ── Shopify (ground truth DEC_048; no dispara alerta) ────────────────
        "platforms.shopify.status":        derived("source_status", "shopify"),
        "platforms.shopify.revenue_eur":   raw("get_shopify_orders_period", "yesterday", "data.revenue_eur"),
        "platforms.shopify.orders_count":  raw("get_shopify_orders_period", "yesterday", "data.orders"),
        "platforms.shopify.aov_eur":       derived("ratio", "platforms.shopify.revenue_eur", "platforms.shopify.orders_count"),
        "platforms.shopify.alert_detail":  derived("const_empty"),
        "platforms.shopify.error_detail":  derived("tool_error_message", "shopify"),
        # ── triangulación 3-way (DEC_050) — claves exactas del template ──────
        "revenue_triangulation.status":                    derived("triangulation_status"),
        "revenue_triangulation.shopify_eur":               derived("alias", "platforms.shopify.revenue_eur"),
        "revenue_triangulation.paid_sum_eur":              derived("sum", "platforms.*paid*.revenue_eur"),
        "revenue_triangulation.ga4_eur":                   derived("alias", "platforms.ga4.revenue_eur"),
        "revenue_triangulation.delta_paid_vs_shopify_pct": derived("delta_pct_vs", "revenue_triangulation.paid_sum_eur", "revenue_triangulation.shopify_eur"),
        "revenue_triangulation.delta_ga4_vs_shopify_pct":  derived("delta_pct_vs", "revenue_triangulation.ga4_eur", "revenue_triangulation.shopify_eur"),
        "revenue_triangulation.detail":                    prose(),
        # ── alerts (disparo determinista + descripción prose) ────────────────
        "alerts":               derived("alerts_from_thresholds"),
        "alerts[].description": prose(),
        # ── ROAS blended MTD (nuevo; cierra petición de Sara) ────────────────
        "_shopify_revenue_mtd":         raw("get_shopify_orders_period", "mtd", "data.revenue_eur"),
        "platforms.{paid}._spend_mtd":  raw("get_{paid}_performance", "mtd", "data.spend_eur"),
        "_paid_spend_mtd_total":        derived("sum", "platforms.*paid*._spend_mtd"),
        "roas_blended_mtd":             derived("ratio", "_shopify_revenue_mtd", "_paid_spend_mtd_total"),
        "roas_blended_floor":           raw("workbook", "cuenta", "roas.dinamico_minimo"),
        "roas_blended_band":            derived("band_vs_floor", "roas_blended_mtd", "roas_blended_floor"),
        "roas_blended_recommendation":  prose(),
    },
}
