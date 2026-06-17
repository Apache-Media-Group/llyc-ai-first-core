"""
narrative.py — capa prosa de perf-monitor L3 (brief §9 steps 4-5, T5).

build_metrics_block: serializa el output determinista a un bloque legible que se
le pasa al LLM para que escriba prosa fundamentada en numeros ya computados (no
los inventa, los interpreta).

merge_prose: superpone SOLO los 5 huecos prose sobre el dict determinista. El
determinista MANDA: merge solo escribe en las rutas prose declaradas; cualquier
numero que el LLM emita se ignora de raiz (garantia del §1 — el valor final lo
fija el ejecutor, nunca la transcripcion del LLM).

Huecos prose (5): summary · platforms.{paid}.alert_detail · revenue_triangulation.detail
· alerts[].description · roas_blended_recommendation.
"""
from __future__ import annotations

PROSE_TOP = ("summary", "roas_blended_recommendation")
PAID = ("meta", "google_ads")


def _clean(x) -> str:
    return "" if x is None else str(x).strip()


def merge_prose(deterministic: dict, prose: dict) -> dict:
    """deterministic es la base autoritativa; se rellenan SOLO los huecos prose."""
    out = deterministic
    for k in PROSE_TOP:
        if k in out:
            out[k] = _clean(prose.get(k))
    if isinstance(out.get("revenue_triangulation"), dict):
        out["revenue_triangulation"]["detail"] = _clean(
            (prose.get("revenue_triangulation") or {}).get("detail")
        )
    plats = out.get("platforms", {})
    for p in PAID:
        if p in plats:
            pr = (prose.get("platforms") or {}).get(p) or {}
            plats[p]["alert_detail"] = _clean(pr.get("alert_detail"))
    prose_alerts = {
        (a.get("platform"), a.get("metric")): a.get("description")
        for a in (prose.get("alerts") or [])
    }
    for a in out.get("alerts", []):
        a["description"] = _clean(prose_alerts.get((a.get("platform"), a.get("metric"))))
    return out


def build_metrics_block(d: dict) -> str:
    plats = d.get("platforms", {})
    lines = [
        f"FECHA: {d.get('date')}  CLIENTE: {d.get('client')}",
        f"EXECUTION: {d.get('execution_status')} ({d.get('execution_status_detail') or 'sin incidencias'})",
        f"ANALYSIS: {d.get('analysis_status')}",
        "",
        "PLATAFORMAS PAID:",
    ]
    for p in PAID:
        b = plats.get(p)
        if not b:
            continue
        if b.get("status") == "ERROR":
            lines.append(f"  {p}: ERROR -- {b.get('error_detail')}")
            continue
        lines.append(
            f"  {p}: status={b.get('status')} | spend={b.get('spend_eur')} EUR "
            f"revenue={b.get('revenue_eur')} EUR | ROAS ayer={b.get('roas_yesterday')} "
            f"vs 7d={b.get('roas_7d_avg')} (dev {b.get('roas_deviation_pct')}%) | "
            f"CPA ayer={b.get('cpa_yesterday_eur')} vs 7d={b.get('cpa_7d_avg_eur')} "
            f"(dev {b.get('cpa_deviation_pct')}%)"
        )
    ga4 = plats.get("ga4")
    if ga4 and ga4.get("status") != "ERROR":
        lines.append(f"GA4 (proxy): sessions={ga4.get('sessions')} transactions={ga4.get('transactions')} revenue={ga4.get('revenue_eur')} EUR")
    sh = plats.get("shopify")
    if sh:
        if sh.get("status") == "ERROR":
            lines.append(f"SHOPIFY (ground truth): ERROR -- {sh.get('error_detail')}")
        else:
            lines.append(f"SHOPIFY (ground truth): revenue={sh.get('revenue_eur')} EUR orders={sh.get('orders_count')} AOV={sh.get('aov_eur')} EUR")
    tri = d.get("revenue_triangulation", {})
    if tri.get("status") == "OK":
        lines += ["", "TRIANGULACION (Shopify=ref):",
                  f"  Shopify={tri.get('shopify_eur')} | Sum_paid={tri.get('paid_sum_eur')} (delta {tri.get('delta_paid_vs_shopify_pct')}%) "
                  f"| GA4={tri.get('ga4_eur')} (delta {tri.get('delta_ga4_vs_shopify_pct')}%)"]
    else:
        lines += ["", "TRIANGULACION: N/A (Shopify no disponible)"]
    lines += ["", f"ROAS BLENDED MTD: blended={d.get('roas_blended_mtd')} floor={d.get('roas_blended_floor')} banda={d.get('roas_blended_band')}"]
    alerts = d.get("alerts", [])
    lines += ["", f"ALERTAS DISPARADAS ({len(alerts)}):"]
    for a in alerts:
        lines.append(f"  {a['platform']} {a['metric']}: valor={a['value']} umbral={a['threshold']} dev={a['deviation_pct']}%")
    if not alerts:
        lines.append("  (ninguna)")
    return "\n".join(lines)
