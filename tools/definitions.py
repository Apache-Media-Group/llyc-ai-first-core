"""
tools/definitions.py — Catálogo de tool definitions para Managed Agents
Proyecto: llyc-ai-first-core
Decisión 021: tool definitions centralizadas en este fichero.

Estructura:
  TOOL_DEFINITIONS_BY_AGENT — dict indexado por agent_name con las tools
  que ese agente puede invocar. scripts/bootstrap_agent.py lo importa
  para crear el Managed Agent con el subset correcto.

POC Sprint 1 — DV360 (Decisión 064):
  Se añaden las 3 tools del POC. El catálogo completo de Meta, Google Ads
  y GA4 ya existe en sus respectivos tools/*.py — sus definitions se añaden
  aquí en el mismo patrón cuando se formalice definitions.py completo.
"""

from __future__ import annotations

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  DV360 TOOL DEFINITIONS — POC Sprint 1                                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝

DV360_TOOLS: list[dict] = [
    {
        "name": "dv360_list_campaigns",
        "description": (
            "Lista todas las campañas del advertiser DV360. "
            "Devuelve id, nombre, estado, objetivo y presupuestos. "
            "Úsala para obtener una visión global del portfolio de campañas "
            "antes de analizar una campaña específica."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_str": {
                    "type": "string",
                    "description": (
                        "Filtro opcional en formato DV360 API. "
                        "Ejemplo: 'entityStatus=\"ENTITY_STATUS_ACTIVE\"' "
                        "para listar solo campañas activas."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "dv360_list_insertion_orders",
        "description": (
            "Lista los Insertion Orders del advertiser DV360. "
            "Si se especifica campaign_id, filtra por campaña. "
            "Devuelve id, nombre, estado, pacing y segmentos de presupuesto. "
            "Úsala para analizar el ritmo de gasto a nivel de IO."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "ID de campaña DV360 para filtrar sus IOs. "
                        "Si se omite, devuelve todos los IOs del advertiser."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "dv360_get_campaign_metrics",
        "description": (
            "Obtiene el estado y datos de presupuesto de una campaña DV360. "
            "Devuelve entityStatus, presupuestos, y recuento de line items "
            "activos vs totales. "
            "NOTA: métricas de rendimiento (impresiones, clicks, CPA, gasto) "
            "no disponibles en esta versión — pendiente de fuente de datos "
            "(Decisión 064). Útil para budget-pacer; limitado para "
            "performance-monitor."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "string",
                    "description": "ID de la campaña DV360.",
                },
            },
            "required": ["campaign_id"],
        },
    },
]


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CATÁLOGO POR AGENTE                                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝
# Cada agente recibe solo las tools que necesita.
# scripts/bootstrap_agent.py importa TOOL_DEFINITIONS_BY_AGENT[agent_name].
# DV360 excluido de performance-monitor hasta resolver métricas (DEC_064).

TOOL_DEFINITIONS_BY_AGENT: dict[str, list[dict]] = {
    "performance-monitor": [
        # Meta, Google Ads, GA4 — sus definitions se añaden aquí
        # cuando se formalice el catálogo completo.
        # DV360 excluido — ver Decisión 064 y META_dv360-rescue-inventory §4.
    ],
    "budget-pacer": [
        # Meta, Google Ads, GA4 — pendiente formalización.
        # DV360: solo get_campaign_metrics (estado + presupuesto, sin métricas reales)
        DV360_TOOLS[2],  # dv360_get_campaign_metrics
    ],
    "naming-utm-auditor": [
        # No necesita DV360 en S1.
    ],
    "weekly-digest": [
        # Meta, Google Ads, GA4 — pendiente formalización.
        # DV360: campaigns + IOs para sección de estado semanal
        DV360_TOOLS[0],  # dv360_list_campaigns
        DV360_TOOLS[1],  # dv360_list_insertion_orders
    ],
}
