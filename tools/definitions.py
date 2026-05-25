"""
tools/definitions.py — Tool definitions for Claude Managed Agents.

Decisions applied:
  - DEC_021: catálogo individual + asignación por agente vía
    TOOL_DEFINITIONS_BY_AGENT. Estructura forward-compatible: cuando llegue
    un agente nuevo (budget-pacer, naming-utm-auditor, weekly-digest,
    creative-fatigue-detector), se añade su entrada al dict sin tocar
    scripts/bootstrap_agent.py.

Cada tool definition se corresponde 1:1 con una función pública en
tools/[plataforma].py. El input_schema debe alinear exactamente con la
firma de la función — el dispatcher en main.py recibe los tool_use
blocks de Claude y los rutea a la función correspondiente sin
adaptación intermedia.

⚠️ Importante: write_output_to_drive NO es una tool del agente. La
persistencia del output en Drive la hace el wrapper agent_executor
(main.py línea ~650) tras la respuesta final del agente. El agente
devuelve el JSON estructurado, no escribe ficheros.

Cómo añadir una tool nueva:
  1. Implementar la función pública en tools/[plataforma].py con contrato
     ok/error (tools/response.py) y @with_timeout(plataforma).
  2. Añadir su definition aquí como constante a nivel módulo.
  3. Referenciarla desde la lista del agente que la consume en
     TOOL_DEFINITIONS_BY_AGENT.

Convención: las constantes individuales se nombran en MAYÚSCULAS siguiendo
el patrón GET_<PLATAFORMA>_<ACCIÓN>, y se referencian por nombre desde el
dict de asignación por agente.
"""


# ─── CATÁLOGO DE TOOL DEFINITIONS ────────────────────────────────────────────
#
# Notas sobre el campo "metrics" en las 3 tools de performance:
# La firma de las funciones de Meta, Google Ads y GA4 acepta `metrics: list`,
# pero los docstrings indican que el parámetro está actualmente ignorado —
# las funciones devuelven siempre el set estándar de métricas. Se mantiene en
# el schema por fidelidad al contrato Python actual; el agente puede pasar
# `[]` o la lista vacía sin consecuencias. Eliminar de aquí cuando se elimine
# de la firma de la función.

GET_META_PERFORMANCE = {
    "type": "custom",
    "name": "get_meta_performance",
    "description": (
        "Obtiene métricas de rendimiento de Meta Ads para una cuenta y rango "
        "de fechas. Devuelve siempre: spend, revenue, ROAS, CPA, impressions, "
        "clicks, CTR. Usado por performance-monitor para comparar yesterday "
        "contra la media de los últimos 7 días y detectar desviaciones."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ad_account_id": {
                "type": "string",
                "description": (
                    "ID de la cuenta publicitaria Meta SIN prefijo 'act_'. "
                    "Ejemplo: '2466105110293178' (no 'act_2466105110293178')."
                ),
            },
            "date_start": {
                "type": "string",
                "description": "Fecha inicio del rango en formato YYYY-MM-DD.",
            },
            "date_end": {
                "type": "string",
                "description": "Fecha fin del rango (inclusive) en formato YYYY-MM-DD.",
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Lista de métricas a obtener. Actualmente IGNORADA por la "
                    "función — siempre se devuelve el set estándar. Pasar `[]`."
                ),
            },
        },
        "required": ["ad_account_id", "date_start", "date_end", "metrics"],
    },
}


GET_GOOGLE_ADS_PERFORMANCE = {
    "type": "custom",
    "name": "get_google_ads_performance",
    "description": (
        "Obtiene métricas de rendimiento de Google Ads por campaña para una "
        "cuenta y rango de fechas. Devuelve siempre: spend, revenue, ROAS, "
        "conversions, impressions, clicks, CTR. Usado por performance-monitor "
        "para detectar desviaciones contra la media de los últimos 7 días."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": (
                    "ID de la cuenta Google Ads sin guiones. Ejemplo: "
                    "'2756616331' (no '275-661-6331')."
                ),
            },
            "date_start": {
                "type": "string",
                "description": "Fecha inicio en formato YYYY-MM-DD.",
            },
            "date_end": {
                "type": "string",
                "description": "Fecha fin (inclusive) en formato YYYY-MM-DD.",
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Opcional. Actualmente IGNORADA — siempre se devuelve el "
                    "set estándar. Si se pasa, usar `[]`."
                ),
            },
        },
        "required": ["customer_id", "date_start", "date_end"],
    },
}


GET_GA4_PERFORMANCE = {
    "type": "custom",
    "name": "get_ga4_performance",
    "description": (
        "Obtiene métricas de GA4 desagregadas por canal "
        "(sessionDefaultChannelGroup) para una property y rango de fechas. "
        "Devuelve sessions, transactions y revenue por canal. GA4 es la "
        "fuente de verdad de revenue en V&V (DEC_042) — los revenues "
        "reportados por Meta y Google Ads deben contrastarse contra esto."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "property_id": {
                "type": "string",
                "description": (
                    "ID de la property GA4. Solo el número, sin prefijo "
                    "'properties/'. Ejemplo: '267182121'."
                ),
            },
            "date_start": {
                "type": "string",
                "description": (
                    "Fecha inicio. Formato YYYY-MM-DD o expresión relativa "
                    "soportada por GA4: 'yesterday', '7daysAgo', '30daysAgo'."
                ),
            },
            "date_end": {
                "type": "string",
                "description": (
                    "Fecha fin (inclusive). Formato YYYY-MM-DD o expresión "
                    "relativa: 'today', 'yesterday'."
                ),
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Opcional. Actualmente IGNORADA — siempre se devuelve "
                    "sessions, transactions y revenue. Si se pasa, usar `[]`."
                ),
            },
        },
        "required": ["property_id", "date_start", "date_end"],
    },
}


# ─── DV360 TOOL DEFINITIONS — POC Sprint 1 (DEC_064) ────────────────────────

DV360_LIST_CAMPAIGNS = {
    "type": "custom",
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
}

DV360_LIST_INSERTION_ORDERS = {
    "type": "custom",
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
}

DV360_GET_CAMPAIGN_METRICS = {
    "type": "custom",
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
}


# ─── ASIGNACIÓN POR AGENTE ───────────────────────────────────────────────────
#
# Cada entrada del dict es la lista exacta de tools que se envía a Anthropic
# al crear el Managed Agent correspondiente. Subset selection se hace aquí,
# no en runtime.
#
# Claves en snake_case — main.py convierte agent_id kebab-case con
# agent_name.replace("-", "_") antes de llamar a get_tool_definitions().
#
# Sprint 1 — agentes operativos:
#   - performance_monitor   (Meta + Google Ads + GA4)
#   - budget_pacer          (DV360 get_campaign_metrics — métricas reales pendientes DEC_064)
#   - naming_utm_auditor    (sin tools de plataforma en S1)
#   - weekly_digest         (DV360 list_campaigns + list_insertion_orders)
#
# Sprint 2:
#   - creative_fatigue_detector

TOOL_DEFINITIONS_BY_AGENT = {
    "performance_monitor": [
        GET_META_PERFORMANCE,
        GET_GOOGLE_ADS_PERFORMANCE,
        GET_GA4_PERFORMANCE,
        # DV360 excluido — ver Decisión 064 y META_dv360-rescue-inventory §4.
    ],
    "budget_pacer": [
        # Meta, Google Ads, GA4 — pendiente formalización.
        # DV360: solo get_campaign_metrics (estado + presupuesto, sin métricas reales)
        DV360_GET_CAMPAIGN_METRICS,
    ],
    "naming_utm_auditor": [
        # No necesita tools de plataforma en S1.
    ],
    "weekly_digest": [
        # Meta, Google Ads, GA4 — pendiente formalización.
        # DV360: campaigns + IOs para sección de estado semanal
        DV360_LIST_CAMPAIGNS,
        DV360_LIST_INSERTION_ORDERS,
    ],
    # Otros agentes — añadir entrada cuando se desarrollen siguiendo el patrón
    # de DEC_021. Las tools del catálogo se reutilizan; las nuevas se definen
    # como constante a nivel módulo arriba antes de referenciarlas aquí.
}


def get_tool_definitions(agent_name: str) -> list:
    """
    Devuelve la lista de tool definitions para el agente solicitado.

    Args:
        agent_name: Nombre del agente (snake_case). Debe existir en
            TOOL_DEFINITIONS_BY_AGENT.

    Returns:
        Lista de dicts con tool definitions listos para enviar a Anthropic
        en el campo `tools` al crear el Managed Agent.

    Raises:
        KeyError: Si el agente no tiene tools registradas en el dict.
            Indica que el agente no está bootstrappeado o que se está
            invocando antes de haber registrado sus tools en este fichero.
    """
    if agent_name not in TOOL_DEFINITIONS_BY_AGENT:
        registered = sorted(TOOL_DEFINITIONS_BY_AGENT.keys())
        raise KeyError(
            f"Agente '{agent_name}' no tiene tool definitions registradas. "
            f"Agentes disponibles: {registered}. "
            f"Si '{agent_name}' es nuevo, añadir su entrada en "
            f"tools/definitions.py:TOOL_DEFINITIONS_BY_AGENT."
        )
    return TOOL_DEFINITIONS_BY_AGENT[agent_name]
