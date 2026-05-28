"""
tools/ga4.py — Google Analytics 4 Data API tools
Proyecto: llyc-ai-first-core
Owner: Alberto González
Sprint: 1

Alimenta: performance-monitor · weekly-digest
Decisiones aplicadas: 022 (contrato ok/error + timeout), 026 (Secret Manager híbrido),
                      035 (GA4 fuente de verdad de web behavior y funnel),
                      048 (Shopify fuente de verdad de revenue — GA4 secundaria para revenue),
                      067 (auth OAuth admin-tech, unifica con Meta/Google Ads — 2026-05-27)

Credenciales leídas desde Secret Manager (DEC_067, OAuth admin-tech):
  - GA4_CLIENT_ID         → llyc-ai-first-core   (scope: shared, OAuth app LLYC)
  - GA4_CLIENT_SECRET     → llyc-ai-first-core   (scope: shared, OAuth app LLYC)
  - GA4_REFRESH_TOKEN     → llyc-ai-[cliente]    (scope: client, admin-tech@llyc.global)

Nota sobre revenue (DEC_048):
  GA4 tiene >2x discrepancia documentada vs Shopify en V&V.
  GA4 es fuente de verdad para: sesiones, funnel, comportamiento web, canal breakdown.
  Shopify es fuente de verdad para: revenue, transactions.
  Las funciones de revenue de GA4 se devuelven con flag 'source: ga4' para
  que el agente pueda aplicar la jerarquía correcta.
"""

import json
import os
import tempfile

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    Metric,
    MetricAggregation,
    RunReportRequest,
)
from google.oauth2.credentials import Credentials

from tools.response import ok, error, with_timeout


# ─────────────────────────────────────────────
# INICIALIZACIÓN
# ─────────────────────────────────────────────

def init_ga4_client(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> BetaAnalyticsDataClient:
    """
    Inicializa el cliente GA4 Data API mediante OAuth de usuario
    (admin-tech@llyc.global, Viewer en la property GA4 del cliente).

    Patrón unificado con Meta y Google Ads — documentado en PAID_ga4-setup.md §5.
    Las 3 credenciales se leen desde Secret Manager: client_id y client_secret
    de llyc-ai-first-core (compartidos a nivel agencia), refresh_token del
    proyecto del cliente.

    Llamar una vez por ejecución de Cloud Function antes de usar el resto de funciones.
    """
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )
    return BetaAnalyticsDataClient(credentials=credentials)


# ─────────────────────────────────────────────
# PERFORMANCE MONITOR
# ─────────────────────────────────────────────

@with_timeout("ga4")
def get_ga4_performance(
    client: BetaAnalyticsDataClient,
    property_id: str,
    date_start: str,
    date_end: str,
    metrics: list = None,
) -> dict:
    """
    Obtiene métricas de rendimiento de GA4 por canal para un rango de fechas.

    Usado por: performance-monitor (yesterday + last_7d)
               weekly-digest (semana actual vs semana anterior)

    Args:
        client: BetaAnalyticsDataClient inicializado
        property_id: ID de la property GA4 (solo el número, ej: 267182121)
        date_start: Fecha inicio YYYY-MM-DD o 'yesterday', 'NdaysAgo'
        date_end: Fecha fin YYYY-MM-DD o 'today', 'yesterday'
        metrics: ignorado — se devuelven siempre las métricas estándar

    Returns:
        ok("ga4", {...}) con sessions, transactions, revenue por canal
        error("ga4", ...) si falla la llamada

    Nota: revenue marcado con source='ga4' — ver DEC_048.
    """
    try:
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[
                Dimension(name="sessionDefaultChannelGroup"),
                Dimension(name="sessionMedium"),
                Dimension(name="sessionSource"),
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="newUsers"),
                Metric(name="transactions"),
                Metric(name="purchaseRevenue"),
                Metric(name="conversions"),
                Metric(name="bounceRate"),
            ],
            date_ranges=[DateRange(start_date=date_start, end_date=date_end)],
            metric_aggregations=[MetricAggregation.TOTAL],
        )

        response = client.run_report(request)

        channels = []
        total_sessions = 0
        total_transactions = 0
        total_revenue = 0.0
        total_new_users = 0

        for row in response.rows:
            channel = row.dimension_values[0].value
            medium = row.dimension_values[1].value
            source = row.dimension_values[2].value
            sessions = int(row.metric_values[0].value)
            new_users = int(row.metric_values[1].value)
            transactions = int(row.metric_values[2].value)
            revenue = float(row.metric_values[3].value)
            bounce_rate = float(row.metric_values[5].value)

            channels.append({
                "channel": channel,
                "medium": medium,
                "source": source,
                "sessions": sessions,
                "new_users": new_users,
                "transactions": transactions,
                "revenue_eur": round(revenue, 2),
                "bounce_rate_pct": round(bounce_rate, 4),
            })

            total_sessions += sessions
            total_transactions += transactions
            total_revenue += revenue
            total_new_users += new_users

        return ok("ga4", {
            "sessions": total_sessions,
            "new_users": total_new_users,
            "transactions": total_transactions,
            "revenue_eur": round(total_revenue, 2),
            "revenue_source": "ga4",  # DEC_048: Shopify es ground truth — este valor es referencial
            "channels": channels,
            "date_start": date_start,
            "date_end": date_end,
        })

    except Exception as e:
        return error("ga4", "API_ERROR", str(e))


# ─────────────────────────────────────────────
# PAID CHANNEL BREAKDOWN
# ─────────────────────────────────────────────

@with_timeout("ga4")
def get_ga4_paid_channel_performance(
    client: BetaAnalyticsDataClient,
    property_id: str,
    date_start: str,
    date_end: str,
) -> dict:
    """
    Obtiene transacciones, revenue y sesiones filtrando solo canales paid (utm_medium = paid_*).
    Permite cruzar con datos de Meta y Google Ads para calcular ROAS real desde GA4.

    Usado por: weekly-digest (correlación de atribución plataforma ↔ GA4, sección 7)
    """
    try:
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[
                Dimension(name="sessionMedium"),
                Dimension(name="sessionCampaignName"),
                Dimension(name="sessionSource"),
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="transactions"),
                Metric(name="purchaseRevenue"),
                Metric(name="bounceRate"),
            ],
            date_ranges=[DateRange(start_date=date_start, end_date=date_end)],
            dimension_filter=FilterExpression(
                filter=Filter(
                    field_name="sessionMedium",
                    string_filter=Filter.StringFilter(
                        match_type=Filter.StringFilter.MatchType.BEGINS_WITH,
                        value="paid_",
                    ),
                )
            ),
        )

        response = client.run_report(request)

        by_medium = {}
        for row in response.rows:
            medium = row.dimension_values[0].value
            campaign = row.dimension_values[1].value
            source = row.dimension_values[2].value
            sessions = int(row.metric_values[0].value)
            transactions = int(row.metric_values[1].value)
            revenue = float(row.metric_values[2].value)

            if medium not in by_medium:
                by_medium[medium] = {
                    "medium": medium,
                    "sessions": 0,
                    "transactions": 0,
                    "revenue_eur": 0.0,
                    "campaigns": [],
                }

            by_medium[medium]["sessions"] += sessions
            by_medium[medium]["transactions"] += transactions
            by_medium[medium]["revenue_eur"] += revenue
            by_medium[medium]["campaigns"].append({
                "campaign": campaign,
                "source": source,
                "sessions": sessions,
                "transactions": transactions,
                "revenue_eur": round(revenue, 2),
            })

        # Redondear revenue totales
        for m in by_medium.values():
            m["revenue_eur"] = round(m["revenue_eur"], 2)

        return ok("ga4", {
            "paid_channels": list(by_medium.values()),
            "revenue_source": "ga4",  # DEC_048
            "date_start": date_start,
            "date_end": date_end,
        })

    except Exception as e:
        return error("ga4", "API_ERROR", str(e))


# ─────────────────────────────────────────────
# FUNNEL DE CONVERSIÓN
# ─────────────────────────────────────────────

@with_timeout("ga4")
def get_ga4_funnel(
    client: BetaAnalyticsDataClient,
    property_id: str,
    date_start: str,
    date_end: str,
) -> dict:
    """
    Obtiene métricas de funnel de conversión para el weekly-digest.
    Etapas: sesiones → usuarios activos → add_to_cart → checkout → purchase

    Usado por: weekly-digest (sección 4 — Funnel de conversión)
    """
    try:
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[
                Dimension(name="deviceCategory"),
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="activeUsers"),
                Metric(name="addToCarts"),
                Metric(name="checkouts"),
                Metric(name="transactions"),
                Metric(name="purchaseRevenue"),
            ],
            date_ranges=[DateRange(start_date=date_start, end_date=date_end)],
            metric_aggregations=[MetricAggregation.TOTAL],
        )

        response = client.run_report(request)

        by_device = []
        totals = {
            "sessions": 0,
            "active_users": 0,
            "add_to_carts": 0,
            "checkouts": 0,
            "transactions": 0,
            "revenue_eur": 0.0,
        }

        for row in response.rows:
            device = row.dimension_values[0].value
            sessions = int(row.metric_values[0].value)
            active_users = int(row.metric_values[1].value)
            add_to_carts = int(row.metric_values[2].value)
            checkouts = int(row.metric_values[3].value)
            transactions = int(row.metric_values[4].value)
            revenue = float(row.metric_values[5].value)

            by_device.append({
                "device": device,
                "sessions": sessions,
                "active_users": active_users,
                "add_to_carts": add_to_carts,
                "checkouts": checkouts,
                "transactions": transactions,
                "revenue_eur": round(revenue, 2),
                "cart_rate_pct": round(add_to_carts / sessions, 4) if sessions > 0 else 0.0,
                "checkout_rate_pct": round(checkouts / add_to_carts, 4) if add_to_carts > 0 else 0.0,
                "conversion_rate_pct": round(transactions / sessions, 4) if sessions > 0 else 0.0,
            })

            totals["sessions"] += sessions
            totals["active_users"] += active_users
            totals["add_to_carts"] += add_to_carts
            totals["checkouts"] += checkouts
            totals["transactions"] += transactions
            totals["revenue_eur"] += revenue

        totals["revenue_eur"] = round(totals["revenue_eur"], 2)
        totals["cart_rate_pct"] = round(totals["add_to_carts"] / totals["sessions"], 4) if totals["sessions"] > 0 else 0.0
        totals["checkout_rate_pct"] = round(totals["checkouts"] / totals["add_to_carts"], 4) if totals["add_to_carts"] > 0 else 0.0
        totals["conversion_rate_pct"] = round(totals["transactions"] / totals["sessions"], 4) if totals["sessions"] > 0 else 0.0

        return ok("ga4", {
            "funnel_totals": totals,
            "funnel_by_device": by_device,
            "revenue_source": "ga4",  # DEC_048
            "date_start": date_start,
            "date_end": date_end,
        })

    except Exception as e:
        return error("ga4", "API_ERROR", str(e))


# ─────────────────────────────────────────────
# WEEKLY COMPARISON (auxiliar weekly-digest)
# ─────────────────────────────────────────────

@with_timeout("ga4")
def get_ga4_weekly_comparison(
    client: BetaAnalyticsDataClient,
    property_id: str,
) -> dict:
    """
    Compara semana actual vs semana anterior vs mismo periodo año anterior.
    Usado por: weekly-digest (sección 2 — KPIs de la semana)
    """
    try:
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[
                Dimension(name="sessionDefaultChannelGroup"),
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="transactions"),
                Metric(name="purchaseRevenue"),
                Metric(name="newUsers"),
                Metric(name="activeUsers"),
            ],
            date_ranges=[
                DateRange(start_date="7daysAgo", end_date="yesterday", name="this_week"),
                DateRange(start_date="14daysAgo", end_date="8daysAgo", name="last_week"),
                DateRange(start_date="371daysAgo", end_date="365daysAgo", name="same_week_last_year"),
            ],
            metric_aggregations=[MetricAggregation.TOTAL],
        )

        response = client.run_report(request)

        def parse_period(rows, period_index):
            totals = {
                "sessions": 0,
                "transactions": 0,
                "revenue_eur": 0.0,
                "new_users": 0,
                "active_users": 0,
            }
            for row in rows:
                totals["sessions"] += int(row.metric_values[period_index * 5 + 0].value)
                totals["transactions"] += int(row.metric_values[period_index * 5 + 1].value)
                totals["revenue_eur"] += float(row.metric_values[period_index * 5 + 2].value)
                totals["new_users"] += int(row.metric_values[period_index * 5 + 3].value)
                totals["active_users"] += int(row.metric_values[period_index * 5 + 4].value)
            totals["revenue_eur"] = round(totals["revenue_eur"], 2)
            return totals

        this_week = parse_period(response.rows, 0)
        last_week = parse_period(response.rows, 1)
        same_week_ly = parse_period(response.rows, 2)

        def pct_change(current, previous):
            if previous == 0:
                return None
            return round((current - previous) / previous * 100, 1)

        return ok("ga4", {
            "this_week": this_week,
            "last_week": last_week,
            "same_week_last_year": same_week_ly,
            "wow_change_pct": {
                "sessions": pct_change(this_week["sessions"], last_week["sessions"]),
                "transactions": pct_change(this_week["transactions"], last_week["transactions"]),
                "revenue": pct_change(this_week["revenue_eur"], last_week["revenue_eur"]),
            },
            "yoy_change_pct": {
                "sessions": pct_change(this_week["sessions"], same_week_ly["sessions"]),
                "transactions": pct_change(this_week["transactions"], same_week_ly["transactions"]),
                "revenue": pct_change(this_week["revenue_eur"], same_week_ly["revenue_eur"]),
            },
            "revenue_source": "ga4",  # DEC_048
        })

    except Exception as e:
        return error("ga4", "API_ERROR", str(e))