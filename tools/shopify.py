"""
tools/shopify.py — Shopify Admin API tools
Proyecto: llyc-ai-first-core
Owner: Max (Massimiliano Turinetto) · Reviewer: Alberto González
Sprint: 1

Alimenta: performance-monitor (get_shopify_orders_period) · weekly-digest (las 4)
Decisiones aplicadas: 022 (contrato ok/error + timeout), 048 (Shopify fuente de
verdad de revenue), 049 (processed_at canónico + TZ Madrid), 050 (4 tools
específicas, no abstracción única).

Credenciales leídas desde Secret Manager vía config.json:
  - SHOPIFY_ADMIN_API_TOKEN → llyc-ai-{cliente}  (scope: client, DEC_048 §8)

Shopify es excepción al patrón híbrido (DEC_026/DEC_048): 100% en proyecto cliente.
No hay credenciales shared en llyc-ai-first-core.
"""

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from tools.response import ok, error, with_timeout


# ─────────────────────────────────────────────
# STATE GLOBAL (patrón Meta — init-once-per-execution)
# ─────────────────────────────────────────────

_SHOPIFY_CONFIG: dict[str, str | None] = {
    "shop_domain": None,
    "access_token": None,
    "api_version": None,
}

_MADRID_TZ = ZoneInfo("Europe/Madrid")
_DEFAULT_PAGE_SIZE = 250

# Sesión HTTP reutilizada (keep-alive) + retry sobre fallos transitorios.
# Causa raíz del SSL-EOF en CF (M8 30/06): requests.get suelto por página abría
# una conexión TLS nueva por cada página de paginación; bajo ráfaga, Shopify
# cortaba alguna a media (UNEXPECTED_EOF_WHILE_READING). La Session da keep-alive
# (elimina el re-handshake) y Retry cubre EOF/timeout/429/5xx residual por página.
# backoff_factor bajo para caber en el techo de 120s de with_timeout("shopify").
_SESSION: requests.Session | None = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        sess = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        sess.mount("https://", adapter)
        _SESSION = sess
    return _SESSION


# ─────────────────────────────────────────────
# INICIALIZACIÓN
# ─────────────────────────────────────────────


def init_shopify_api(shop_domain: str, access_token: str, api_version: str) -> None:
    """
    Configura el cliente Shopify para esta ejecución de Cloud Function.
    Llamar una vez antes de usar el resto de funciones (patrón init_meta_api).
    """
    _SHOPIFY_CONFIG["shop_domain"] = shop_domain
    _SHOPIFY_CONFIG["access_token"] = access_token
    _SHOPIFY_CONFIG["api_version"] = api_version


# ─────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────


def _ensure_initialized() -> None:
    if not _SHOPIFY_CONFIG["access_token"]:
        raise RuntimeError(
            "Shopify no inicializado. Llamar init_shopify_api() antes de las tools."
        )


def _base_url() -> str:
    return (
        f"https://{_SHOPIFY_CONFIG['shop_domain']}"
        f"/admin/api/{_SHOPIFY_CONFIG['api_version']}"
    )


def _headers() -> dict:
    return {
        "X-Shopify-Access-Token": _SHOPIFY_CONFIG["access_token"],
        "Content-Type": "application/json",
    }


def _to_madrid_iso(date_str: str, end_of_day: bool = False) -> str:
    """
    Convierte 'YYYY-MM-DD' a ISO 8601 con TZ Europe/Madrid.
    DEC_049: agregación temporal en TZ Madrid.
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.replace(tzinfo=_MADRID_TZ).isoformat()


def _parse_next_page_info(link_header: str | None) -> str | None:
    """
    Extrae page_info del header Link de Shopify (cursor-based pagination).
    Formato: '<https://...?page_info=XXX&limit=250>; rel="next", <...>; rel="previous"'
    """
    if not link_header:
        return None
    match = re.search(r'<([^>]*)>;\s*rel="next"', link_header)
    if not match:
        return None
    page_info_match = re.search(r"[?&]page_info=([^&]+)", match.group(1))
    return page_info_match.group(1) if page_info_match else None


def _get_paginated(path: str, params: dict) -> list[dict]:
    """
    GET path + paginación cursor-based hasta agotar resultados.
    La clave del array en la response se infiere del path
    ('/orders.json' → 'orders', '/products.json' → 'products', etc.).
    """
    _ensure_initialized()
    resource_key = path.lstrip("/").split(".")[0].split("/")[-1]

    items: list[dict] = []
    url = f"{_base_url()}{path}"
    current_params = dict(params)
    current_params.setdefault("limit", _DEFAULT_PAGE_SIZE)

    while True:
        response = _get_session().get(
            url, headers=_headers(), params=current_params, timeout=25
        )
        response.raise_for_status()
        payload = response.json()
        items.extend(payload.get(resource_key, []))

        page_info = _parse_next_page_info(response.headers.get("Link"))
        if not page_info:
            break

        # Cursor pagination: Shopify exige SOLO page_info + limit en siguientes calls.
        current_params = {"page_info": page_info, "limit": _DEFAULT_PAGE_SIZE}

    return items


def _apply_dtc_filter(orders: list[dict], dtc_filter: dict | None) -> list[dict]:
    """
    Exclusiones client-side por source_name. Shopify API no soporta
    'excluded source_names' como filtro server-side múltiple.
    """
    if not dtc_filter:
        return orders
    excluded = set(dtc_filter.get("excluded_source_names", []))
    if not excluded:
        return orders
    return [o for o in orders if o.get("source_name") not in excluded]


# ─────────────────────────────────────────────
# TOOL 1 — ORDERS PERIOD (performance-monitor + weekly-digest)
# ─────────────────────────────────────────────


@with_timeout("shopify")
def get_shopify_orders_period(
    date_start: str,
    date_end: str,
    dtc_filter: dict | None = None,
) -> dict:
    """
    Revenue ground truth (DEC_048) + orders, AOV, units para un periodo.
    Filtra por processed_at (DEC_049, no created_at). TZ Madrid.

    Usado por:
      - performance-monitor: revenue ayer + media 7d (triangulación 3-way).
      - weekly-digest: KPIs principales Shopify DTC.

    Args:
        date_start: YYYY-MM-DD (inclusivo).
        date_end:   YYYY-MM-DD (inclusivo).
        dtc_filter: {"source_name": "web", "excluded_source_names": [...]}.
                    Si None, no filtra.

    Returns:
        ok("shopify", {revenue_eur, orders_count, units_count, aov_eur,
                       new_customer_orders, returning_customer_orders,
                       discounted_orders_count, date_start, date_end,
                       dtc_filter_applied})
    """
    try:
        _ensure_initialized()

        params: dict[str, Any] = {
            "status": "any",
            "processed_at_min": _to_madrid_iso(date_start, end_of_day=False),
            "processed_at_max": _to_madrid_iso(date_end, end_of_day=True),
        }
        if dtc_filter and dtc_filter.get("source_name"):
            params["source_name"] = dtc_filter["source_name"]

        orders = _get_paginated("/orders.json", params)
        orders = _apply_dtc_filter(orders, dtc_filter)

        revenue = 0.0
        units = 0
        new_customer_orders = 0
        returning_customer_orders = 0
        discounted_orders_count = 0

        for o in orders:
            try:
                revenue += float(o.get("total_price", 0) or 0)
            except (TypeError, ValueError):
                pass

            for line_item in o.get("line_items", []) or []:
                try:
                    units += int(line_item.get("quantity", 0) or 0)
                except (TypeError, ValueError):
                    pass

            # customer.orders_count incluye el order actual → 1 = primera compra
            customer = o.get("customer") or {}
            oc = customer.get("orders_count", 0) or 0
            if oc <= 1:
                new_customer_orders += 1
            else:
                returning_customer_orders += 1

            if o.get("discount_codes") or float(o.get("total_discounts", 0) or 0) > 0:
                discounted_orders_count += 1

        orders_count = len(orders)
        aov = (revenue / orders_count) if orders_count > 0 else 0.0

        return ok(
            "shopify",
            {
                "revenue_eur": round(revenue, 2),
                "orders_count": orders_count,
                "units_count": units,
                "aov_eur": round(aov, 2),
                "new_customer_orders": new_customer_orders,
                "returning_customer_orders": returning_customer_orders,
                "discounted_orders_count": discounted_orders_count,
                "date_start": date_start,
                "date_end": date_end,
                "dtc_filter_applied": dtc_filter if dtc_filter else None,
            },
        )

    except requests.HTTPError as e:
        body = e.response.text[:200] if e.response is not None else ""
        return error("shopify", "HTTP_ERROR", f"{e.response.status_code}: {body}")
    except requests.RequestException as e:
        return error("shopify", "API_ERROR", str(e))
    except Exception as e:
        return error("shopify", "UNEXPECTED_ERROR", str(e))


# ─────────────────────────────────────────────
# TOOL 2 — CUSTOMER SEGMENT (weekly-digest)
# ─────────────────────────────────────────────


@with_timeout("shopify")
def get_shopify_customer_segment(
    date_start: str,
    date_end: str,
    dtc_filter: dict | None = None,
) -> dict:
    """
    new vs returning + repeat purchase rate del periodo. Para weekly-digest.
    """
    try:
        _ensure_initialized()

        params: dict[str, Any] = {
            "status": "any",
            "processed_at_min": _to_madrid_iso(date_start, end_of_day=False),
            "processed_at_max": _to_madrid_iso(date_end, end_of_day=True),
            "fields": "id,customer,processed_at",
        }
        if dtc_filter and dtc_filter.get("source_name"):
            params["source_name"] = dtc_filter["source_name"]

        orders = _get_paginated("/orders.json", params)
        orders = _apply_dtc_filter(orders, dtc_filter)

        new_ids: set = set()
        returning_ids: set = set()
        count_in_window: dict = {}

        for o in orders:
            customer = o.get("customer") or {}
            cid = customer.get("id")
            if not cid:
                continue
            count_in_window[cid] = count_in_window.get(cid, 0) + 1

            oc = customer.get("orders_count", 0) or 0
            if oc <= 1:
                new_ids.add(cid)
            else:
                returning_ids.add(cid)

        repeat_ids = {cid for cid, n in count_in_window.items() if n >= 2}
        unique = len(new_ids | returning_ids)
        new_rate = (len(new_ids) / unique * 100) if unique > 0 else 0.0
        repeat_rate = (len(repeat_ids) / unique * 100) if unique > 0 else 0.0

        return ok(
            "shopify",
            {
                "new_customers": len(new_ids),
                "returning_customers": len(returning_ids),
                "new_customer_rate_pct": round(new_rate, 2),
                "repeat_purchase_rate_pct": round(repeat_rate, 2),
                "unique_customers": unique,
                "date_start": date_start,
                "date_end": date_end,
            },
        )

    except requests.HTTPError as e:
        body = e.response.text[:200] if e.response is not None else ""
        return error("shopify", "HTTP_ERROR", f"{e.response.status_code}: {body}")
    except requests.RequestException as e:
        return error("shopify", "API_ERROR", str(e))
    except Exception as e:
        return error("shopify", "UNEXPECTED_ERROR", str(e))


# ─────────────────────────────────────────────
# TOOL 3 — INVENTORY STATUS (patrón inventory_paid_mismatch DEC_050)
# ─────────────────────────────────────────────


@with_timeout("shopify")
def get_shopify_inventory_status(
    sku_list: list[str] | None = None,
    threshold_critical: int = 10,
) -> dict:
    """
    SKUs en stock-out (≤0) y stock crítico (≤ threshold).
    Si sku_list es None, evalúa todo el catálogo activo.
    """
    try:
        _ensure_initialized()

        params: dict[str, Any] = {"status": "active", "fields": "id,title,variants"}
        products = _get_paginated("/products.json", params)

        out_of_stock: list[dict] = []
        critical: list[dict] = []
        healthy = 0
        total = 0

        target_skus = set(sku_list) if sku_list else None

        for product in products:
            for variant in product.get("variants", []) or []:
                sku = variant.get("sku")
                if target_skus is not None and sku not in target_skus:
                    continue
                qty = variant.get("inventory_quantity")
                if qty is None:
                    continue
                total += 1
                entry = {
                    "sku": sku,
                    "product_title": product.get("title"),
                    "variant_title": variant.get("title"),
                    "available": qty,
                }
                if qty <= 0:
                    out_of_stock.append(entry)
                elif qty <= threshold_critical:
                    critical.append(entry)
                else:
                    healthy += 1

        return ok(
            "shopify",
            {
                "out_of_stock": out_of_stock,
                "critical_stock": critical,
                "healthy_count": healthy,
                "total_variants_checked": total,
                "threshold_critical_applied": threshold_critical,
            },
        )

    except requests.HTTPError as e:
        body = e.response.text[:200] if e.response is not None else ""
        return error("shopify", "HTTP_ERROR", f"{e.response.status_code}: {body}")
    except requests.RequestException as e:
        return error("shopify", "API_ERROR", str(e))
    except Exception as e:
        return error("shopify", "UNEXPECTED_ERROR", str(e))


# ─────────────────────────────────────────────
# TOOL 4 — ACTIVE DISCOUNTS (weekly-digest % pedidos con cupón)
# ─────────────────────────────────────────────


@with_timeout("shopify")
def get_shopify_active_discounts(
    date_start: str | None = None,
    date_end: str | None = None,
) -> dict:
    """
    Price rules activos. Si se proporcionan fechas, overlap con la ventana.
    Sin fechas: activos "ahora" (Europe/Madrid).
    """
    try:
        _ensure_initialized()

        rules = _get_paginated("/price_rules.json", {})

        now = datetime.now(_MADRID_TZ)
        window_start = (
            datetime.fromisoformat(_to_madrid_iso(date_start)) if date_start else None
        )
        window_end = (
            datetime.fromisoformat(_to_madrid_iso(date_end, end_of_day=True))
            if date_end
            else None
        )

        def _is_active(rule: dict) -> bool:
            starts = rule.get("starts_at")
            ends = rule.get("ends_at")
            starts_dt = datetime.fromisoformat(starts) if starts else None
            ends_dt = datetime.fromisoformat(ends) if ends else None

            if window_start and window_end:
                if ends_dt and ends_dt < window_start:
                    return False
                if starts_dt and starts_dt > window_end:
                    return False
                return True

            if starts_dt and starts_dt > now:
                return False
            if ends_dt and ends_dt < now:
                return False
            return True

        active = [r for r in rules if _is_active(r)]

        return ok(
            "shopify",
            {
                "active_price_rules": [
                    {
                        "id": r.get("id"),
                        "title": r.get("title"),
                        "value_type": r.get("value_type"),
                        "value": r.get("value"),
                        "starts_at": r.get("starts_at"),
                        "ends_at": r.get("ends_at"),
                        "target_type": r.get("target_type"),
                        "customer_selection": r.get("customer_selection"),
                    }
                    for r in active
                ],
                "total_active_count": len(active),
                "date_start": date_start,
                "date_end": date_end,
            },
        )

    except requests.HTTPError as e:
        body = e.response.text[:200] if e.response is not None else ""
        return error("shopify", "HTTP_ERROR", f"{e.response.status_code}: {body}")
    except requests.RequestException as e:
        return error("shopify", "API_ERROR", str(e))
    except Exception as e:
        return error("shopify", "UNEXPECTED_ERROR", str(e))
