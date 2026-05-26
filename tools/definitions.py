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


# ─── ASIGNACIÓN POR AGENTE ───────────────────────────────────────────────────
#
# Cada entrada del dict es la lista exacta de tools que se envía a Anthropic
# al crear el Managed Agent correspondiente. Subset selection se hace aquí,
# no en runtime.
#
# Sprint 1 — agentes operativos:
#   - performance_monitor   (este PR)
#   - budget_pacer          (próximo PR — Alberto)
#   - naming_utm_auditor    (próximo PR — Alberto)
#   - weekly_digest         (próximo PR — Alberto, incluye Shopify tools DEC_050)
#
# Sprint 2:
#   - creative_fatigue_detector

TOOL_DEFINITIONS_BY_AGENT = {
    "performance_monitor": [
        GET_META_PERFORMANCE,
        GET_GOOGLE_ADS_PERFORMANCE,
        GET_GA4_PERFORMANCE,
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
