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
        "Devuelve sessions, transactions y revenue por canal. NOTA: desde "
        "DEC_048, Shopify es la fuente de verdad de revenue (no GA4) para "
        "clientes ecommerce. GA4 entra en la triangulación 3-way como "
        "atribución proxy por source-medium — NO como ground truth."
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


# ─── BUDGET PACER TOOL DEFINITIONS ──────────────────────────────────────────

GET_META_SPEND_MONTH = {
    "type": "custom",
    "name": "get_meta_spend_month",
    "description": (
        "Obtiene el gasto acumulado del mes en curso en Meta Ads para una cuenta. "
        "Devuelve spend_month_eur y date_preset='this_month'. "
        "Usado por budget-pacer para comparar el gasto mensual acumulado "
        "contra el objetivo mensual del cliente y detectar desviaciones."
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
        },
        "required": ["ad_account_id"],
    },
}


GET_GOOGLE_ADS_SPEND_MONTH = {
    "type": "custom",
    "name": "get_google_ads_spend_month",
    "description": (
        "Obtiene el gasto acumulado del mes en curso en Google Ads para una cuenta. "
        "Devuelve spend_month_eur y date_preset='this_month'. "
        "Usado por budget-pacer para comparar el gasto mensual acumulado "
        "contra el objetivo mensual del cliente y detectar desviaciones."
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
        },
        "required": ["customer_id"],
    },
}


# ─── NAMING & UTM AUDITOR TOOL DEFINITIONS ───────────────────────────────────

GET_META_ACTIVE_AD_URLS = {
    "type": "custom",
    "name": "get_meta_active_ad_urls",
    "description": (
        "Extrae las URLs de destino de todos los ads activos de Meta para auditar "
        "parámetros UTM y naming convention. "
        "Devuelve lista de ads con ad_id, ad_name, adset_name, campaign_name y "
        "destination_url. Usado por naming-utm-auditor para detectar UTMs "
        "incompletos o incumplimientos de naming."
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
        },
        "required": ["ad_account_id"],
    },
}


GET_META_ACTIVE_CAMPAIGNS = {
    "type": "custom",
    "name": "get_meta_active_campaigns",
    "description": (
        "Obtiene la lista de campañas activas en Meta Ads con nombre, objetivo "
        "y presupuesto. Usado por naming-utm-auditor para verificar el scope "
        "de campañas activas y cruzar con los naming patterns del cliente."
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
        },
        "required": ["ad_account_id"],
    },
}


GET_GOOGLE_ADS_ACTIVE_AD_URLS = {
    "type": "custom",
    "name": "get_google_ads_active_ad_urls",
    "description": (
        "Extrae las URLs finales de todos los ads activos de Google Ads (Search, "
        "Shopping, PMAX) para auditar parámetros UTM y naming convention. "
        "Devuelve lista de ads con ad_id, ad_name, ad_type, adgroup_name, "
        "campaign_name, channel_type y destination_url. "
        "Usado por naming-utm-auditor."
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
        },
        "required": ["customer_id"],
    },
}


GET_GOOGLE_ADS_ACTIVE_CAMPAIGNS = {
    "type": "custom",
    "name": "get_google_ads_active_campaigns",
    "description": (
        "Lista las campañas activas de Google Ads con nombre, tipo de canal "
        "y presupuesto diario. Usado por naming-utm-auditor para verificar el "
        "scope de campañas activas y cruzar con los naming patterns del cliente."
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
        },
        "required": ["customer_id"],
    },
}


# ─── WEEKLY DIGEST TOOL DEFINITIONS ──────────────────────────────────────────

GET_GA4_WEEKLY_COMPARISON = {
    "type": "custom",
    "name": "get_ga4_weekly_comparison",
    "description": (
        "Compara métricas de GA4 de la semana actual vs semana anterior vs mismo "
        "periodo del año anterior. Devuelve sessions, transactions, revenue_eur y "
        "new_users para los tres periodos, más los cambios WoW y YoY en porcentaje. "
        "Usado por weekly-digest para la sección de KPIs semanales."
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
        },
        "required": ["property_id"],
    },
}


# --- DV360 TOOL DEFINITIONS - Fase 2 (DEC_064) ------------------------------
 
DV360_GET_CAMPAIGN = {
    "type": "custom",
    "name": "dv360_get_campaign",
    "description": (
        "Obtiene los datos de una campana DV360 por ID. "
        "Devuelve nombre, estado, objetivo y presupuestos. "
        "Usar cuando se necesita el detalle de una campana concreta "
        "ya identificada via dv360_list_campaigns."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "campaign_id": {"type": "string", "description": "ID de la campana DV360."},
        },
        "required": ["campaign_id"],
    },
}
 
DV360_LIST_LINE_ITEMS = {
    "type": "custom",
    "name": "dv360_list_line_items",
    "description": (
        "Lista Line Items del advertiser DV360. "
        "Si se especifica campaign_id, filtra por campana. "
        "Devuelve id, nombre, estado, tipo, pacing, presupuesto y bid strategy. "
        "Util para analizar la estructura de activacion y ritmo de gasto granular."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "campaign_id": {"type": "string", "description": "ID de campana para filtrar. Si se omite devuelve todos los LIs."},
            "filter_str": {"type": "string", "description": "Filtro adicional en formato DV360 API."},
        },
        "required": [],
    },
}
 
DV360_GET_LINE_ITEM = {
    "type": "custom",
    "name": "dv360_get_line_item",
    "description": (
        "Obtiene el detalle completo de un Line Item DV360 por ID. "
        "Devuelve estado, tipo, pacing, presupuesto, bid strategy y targeting expansion. "
        "Usar tras dv360_list_line_items para inspeccionar un LI concreto."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "line_item_id": {"type": "string", "description": "ID del Line Item DV360."},
        },
        "required": ["line_item_id"],
    },
}
 
DV360_GET_TARGETING = {
    "type": "custom",
    "name": "dv360_get_targeting",
    "description": (
        "Obtiene el targeting asignado a un Line Item DV360. "
        "Por defecto consulta: GEO_REGION, DEVICE_TYPE, AUDIENCE_GROUP, AGE_RANGE, GENDER. "
        "Se puede especificar una lista de tipos concretos. "
        "Util para auditar coherencia entre targeting y KPIs del cliente."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "line_item_id": {"type": "string", "description": "ID del Line Item DV360."},
            "targeting_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lista de tipos de targeting a consultar. Si se omite consulta los 5 principales.",
            },
        },
        "required": ["line_item_id"],
    },
}
 
DV360_GET_INSERTION_ORDER = {
    "type": "custom",
    "name": "dv360_get_insertion_order",
    "description": (
        "Obtiene el detalle de un Insertion Order DV360 por ID. "
        "Devuelve estado, pacing, segmentos de presupuesto y frequency cap. "
        "Usar tras dv360_list_insertion_orders para inspeccionar un IO concreto."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "insertion_order_id": {"type": "string", "description": "ID del Insertion Order DV360."},
        },
        "required": ["insertion_order_id"],
    },
}
 
DV360_LIST_CREATIVES = {
    "type": "custom",
    "name": "dv360_list_creatives",
    "description": (
        "Lista creatividades del advertiser DV360. "
        "Devuelve id, nombre, estado, tipo, dimensiones y estado de revision. "
        "Base para el agente creative-fatigue-detector (Sprint 2+)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "filter_str": {"type": "string", "description": "Filtro opcional en formato DV360 API."},
        },
        "required": [],
    },
}
 
DV360_LIST_GOOGLE_AUDIENCES = {
    "type": "custom",
    "name": "dv360_list_google_audiences",
    "description": (
        "Lista audiencias de Google disponibles para targeting en DV360. "
        "Devuelve id, nombre y tipo de audiencia. "
        "Util para auditar audiencias activas y detectar solapamientos o gaps."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "filter_str": {"type": "string", "description": "Filtro opcional en formato DV360 API."},
        },
        "required": [],
    },
}
 
DV360_SEARCH_TARGETING_OPTIONS = {
    "type": "custom",
    "name": "dv360_search_targeting_options",
    "description": (
        "Busca opciones de targeting disponibles por tipo en DV360. "
        "Util para descubrir valores validos antes de asignarlos. "
        "targeting_type ejemplos: TARGETING_TYPE_GEO_REGION, TARGETING_TYPE_DEVICE_TYPE."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "targeting_type": {"type": "string", "description": "Tipo de targeting a consultar (TARGETING_TYPE_*)."},
            "search_terms": {"type": "string", "description": "Termino de busqueda opcional para filtrar resultados."},
        },
        "required": ["targeting_type"],
    },
}
 

# ─── SHOPIFY TOOL DEFINITIONS ────────────────────────────────────────────────
#
# Shopify es fuente de verdad de revenue (DEC_048). Las 4 tools alimentan
# weekly-digest; get_shopify_orders_period también alimenta performance-monitor.
# Patrón de inicialización: API global vía init_shopify_api() (igual que Meta).
# Las funciones NO reciben client object — el dispatcher NO prepend client.

GET_SHOPIFY_ORDERS_PERIOD = {
    "type": "custom",
    "name": "get_shopify_orders_period",
    "description": (
        "Obtiene revenue ground truth (DEC_048), orders, AOV y unidades de Shopify "
        "para un período. Filtra por processed_at en TZ Madrid (DEC_049). "
        "Aplica dtc_filter (source_name + exclusiones) para aislar pedidos DTC. "
        "Usado por weekly-digest (KPIs semanales) y performance-monitor "
        "(triangulación 3-way revenue)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "date_start": {
                "type": "string",
                "description": "Fecha inicio del período en formato YYYY-MM-DD (inclusivo).",
            },
            "date_end": {
                "type": "string",
                "description": "Fecha fin del período en formato YYYY-MM-DD (inclusivo).",
            },
            "dtc_filter": {
                "type": "object",
                "description": (
                    "Filtro DTC para aislar pedidos del canal directo. "
                    "Leer de platforms.shopify.dtc_filter del CONTEXTO DEL CLIENTE. "
                    "Campos: source_name (filtro server-side) y excluded_source_names "
                    "(exclusiones client-side). Pasar null si no aplica."
                ),
                "properties": {
                    "source_name": {
                        "type": "string",
                        "description": "Source name a incluir (ej. 'web').",
                    },
                    "excluded_source_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista de source_names a excluir (ej. ['pos', 'shopify_draft_order']).",
                    },
                },
            },
        },
        "required": ["date_start", "date_end"],
    },
}


GET_SHOPIFY_CUSTOMER_SEGMENT = {
    "type": "custom",
    "name": "get_shopify_customer_segment",
    "description": (
        "Obtiene la distribución de clientes nuevos vs recurrentes y la tasa de "
        "recompra dentro del período. Devuelve new_customers, returning_customers, "
        "new_customer_rate_pct y repeat_purchase_rate_pct. "
        "Usado por weekly-digest para analizar la calidad de la adquisición."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "date_start": {
                "type": "string",
                "description": "Fecha inicio del período en formato YYYY-MM-DD (inclusivo).",
            },
            "date_end": {
                "type": "string",
                "description": "Fecha fin del período en formato YYYY-MM-DD (inclusivo).",
            },
            "dtc_filter": {
                "type": "object",
                "description": (
                    "Mismo filtro DTC que en get_shopify_orders_period. "
                    "Leer de platforms.shopify.dtc_filter del CONTEXTO DEL CLIENTE."
                ),
                "properties": {
                    "source_name": {
                        "type": "string",
                        "description": "Source name a incluir (ej. 'web').",
                    },
                    "excluded_source_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista de source_names a excluir.",
                    },
                },
            },
        },
        "required": ["date_start", "date_end"],
    },
}


GET_SHOPIFY_INVENTORY_STATUS = {
    "type": "custom",
    "name": "get_shopify_inventory_status",
    "description": (
        "Obtiene el estado de inventario del catálogo activo de Shopify: SKUs en "
        "stock-out (≤0) y en stock crítico (≤ threshold_critical). "
        "Si sku_list es null, evalúa todo el catálogo activo. "
        "Usado por weekly-digest para detectar limitaciones de inventario que "
        "pueden estar afectando al rendimiento de campañas."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sku_list": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Lista de SKUs a evaluar. Si se omite o es null, "
                    "se evalúa todo el catálogo activo."
                ),
            },
            "threshold_critical": {
                "type": "integer",
                "description": (
                    "Umbral de unidades para considerar stock crítico. "
                    "Por defecto 10. SKUs con stock ≤ este valor se incluyen "
                    "en critical_stock."
                ),
            },
        },
        "required": [],
    },
}


GET_SHOPIFY_ACTIVE_DISCOUNTS = {
    "type": "custom",
    "name": "get_shopify_active_discounts",
    "description": (
        "Obtiene los price rules de Shopify activos durante el período indicado. "
        "Si no se pasan fechas, devuelve los activos en el momento de ejecución. "
        "Devuelve id, title, value_type, value, starts_at, ends_at y customer_selection "
        "de cada regla activa. Usado por weekly-digest para contextualizar variaciones "
        "de revenue o AOV causadas por descuentos."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "date_start": {
                "type": "string",
                "description": (
                    "Inicio de la ventana temporal en formato YYYY-MM-DD. "
                    "Se incluyen price rules que se solapan con este período. "
                    "Opcional — si se omite, filtra por activos 'ahora'."
                ),
            },
            "date_end": {
                "type": "string",
                "description": (
                    "Fin de la ventana temporal en formato YYYY-MM-DD (inclusivo). "
                    "Opcional — usar junto con date_start."
                ),
            },
        },
        "required": [],
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


# ─── SHOPIFY TOOL DEFINITIONS (DEC_048 + DEC_050) ───────────────────────────

GET_SHOPIFY_ORDERS_PERIOD = {
    "type": "custom",
    "name": "get_shopify_orders_period",
    "description": (
        "Obtiene revenue, orders count, units y AOV desde Shopify para un "
        "rango de fechas. Filtra por processed_at (DEC_049, campo canónico) "
        "y aplica dtc_filter del config del cliente. Shopify es la fuente "
        "de verdad de revenue en clientes ecommerce (DEC_048) — usar este "
        "valor como ground truth para la triangulación con plataformas paid "
        "y GA4. TZ Madrid."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "date_start": {
                "type": "string",
                "description": "Fecha inicio (inclusiva) en formato YYYY-MM-DD.",
            },
            "date_end": {
                "type": "string",
                "description": "Fecha fin (inclusiva) en formato YYYY-MM-DD.",
            },
            "dtc_filter": {
                "type": "object",
                "description": (
                    "Filtro DTC del config del cliente. Estructura: "
                    "{source_name: str, excluded_source_names: list[str]}. "
                    "Opcional; si se omite no se filtra."
                ),
                "properties": {
                    "source_name": {"type": "string"},
                    "excluded_source_names": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "required": ["date_start", "date_end"],
    },
}


GET_SHOPIFY_CUSTOMER_SEGMENT = {
    "type": "custom",
    "name": "get_shopify_customer_segment",
    "description": (
        "Distribución new vs returning customers + repeat purchase rate "
        "para el periodo solicitado. Usado por weekly-digest. Aplica "
        "dtc_filter igual que get_shopify_orders_period."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "date_start": {"type": "string", "description": "YYYY-MM-DD."},
            "date_end": {"type": "string", "description": "YYYY-MM-DD."},
            "dtc_filter": {
                "type": "object",
                "properties": {
                    "source_name": {"type": "string"},
                    "excluded_source_names": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "required": ["date_start", "date_end"],
    },
}


GET_SHOPIFY_INVENTORY_STATUS = {
    "type": "custom",
    "name": "get_shopify_inventory_status",
    "description": (
        "Estado de inventario: SKUs en stock-out (<=0) y stock crítico "
        "(<= threshold). Si sku_list es None evalúa todo el catálogo "
        "activo. Usado por weekly-digest para el patrón "
        "inventory_paid_mismatch (DEC_050) — detección de paid activo "
        "sobre productos sin stock."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sku_list": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Lista de SKUs a evaluar. Si se omite, se evalúa todo "
                    "el catálogo activo."
                ),
            },
            "threshold_critical": {
                "type": "integer",
                "description": "Umbral de stock crítico. Default 10.",
            },
        },
        "required": [],
    },
}


GET_SHOPIFY_ACTIVE_DISCOUNTS = {
    "type": "custom",
    "name": "get_shopify_active_discounts",
    "description": (
        "Lista price rules activos en un periodo (overlap con la ventana) "
        "o activos 'ahora' (Europe/Madrid) si no se pasan fechas. Usado "
        "por weekly-digest para análisis de % pedidos con descuento."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "date_start": {
                "type": "string",
                "description": (
                    "YYYY-MM-DD. Opcional. Si se omite, devuelve los rules "
                    "activos en este momento."
                ),
            },
            "date_end": {"type": "string", "description": "YYYY-MM-DD. Opcional."},
        },
        "required": [],
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
        GET_SHOPIFY_ORDERS_PERIOD,      # DEC_048 -- ground truth revenue + triangulacion 3-way
        DV360_GET_CAMPAIGN_METRICS,     # DEC_068 -- Query API; inerte si dv360.enabled=false
        DV360_LIST_CAMPAIGNS,
        DV360_LIST_INSERTION_ORDERS,
    ],
    "budget_pacer": [
        GET_META_SPEND_MONTH,
        GET_GOOGLE_ADS_SPEND_MONTH,
        GET_SHOPIFY_ORDERS_PERIOD,      # DEC_048 -- revenue ground truth ROAS blended
        DV360_GET_CAMPAIGN_METRICS,     # DEC_068 -- inerte si dv360.enabled=false
        DV360_LIST_INSERTION_ORDERS,
    ],
    "naming_utm_auditor": [
        GET_META_ACTIVE_AD_URLS,
        GET_META_ACTIVE_CAMPAIGNS,
        GET_GOOGLE_ADS_ACTIVE_AD_URLS,
        GET_GOOGLE_ADS_ACTIVE_CAMPAIGNS,
        # DV360 naming/UTM fuera de scope Sprint 2
    ],
    "weekly_digest": [
        GET_META_PERFORMANCE,
        GET_GOOGLE_ADS_PERFORMANCE,
        GET_GA4_PERFORMANCE,
        GET_GA4_WEEKLY_COMPARISON,
        GET_SHOPIFY_ORDERS_PERIOD,
        GET_SHOPIFY_CUSTOMER_SEGMENT,
        GET_SHOPIFY_INVENTORY_STATUS,
        GET_SHOPIFY_ACTIVE_DISCOUNTS,
        DV360_GET_CAMPAIGN_METRICS,     # DEC_068 -- inerte si dv360.enabled=false
        DV360_LIST_CAMPAIGNS,
        DV360_LIST_INSERTION_ORDERS,
        DV360_LIST_CREATIVES,           # Base creative-fatigue-detector Sprint 2+
    ],
}
 



def get_tool_definitions(agent_name: str, config: dict = None) -> list:
    """
    Devuelve la lista de tool definitions para el agente solicitado.
    Filtra tools de plataformas con enabled=false en el config del cliente.
 
    Args:
        agent_name: Nombre del agente (snake_case).
        config: Config del cliente. Si None devuelve catalogo completo (retrocompatible).
 
    Returns:
        Lista de dicts con tool definitions listos para enviar a Anthropic.
 
    Raises:
        KeyError: Si el agente no tiene tools registradas.
    """
    if agent_name not in TOOL_DEFINITIONS_BY_AGENT:
        registered = sorted(TOOL_DEFINITIONS_BY_AGENT.keys())
        raise KeyError(
            f"Agente '{agent_name}' no tiene tool definitions registradas. "
            f"Agentes disponibles: {registered}. "
            f"Si '{agent_name}' es nuevo, anadir su entrada en "
            f"tools/definitions.py:TOOL_DEFINITIONS_BY_AGENT."
        )
 
    tools = list(TOOL_DEFINITIONS_BY_AGENT[agent_name])
 
    if config is None:
        return tools
 
    platforms = config.get("platforms", {})
    disabled = {
        name for name, cfg in platforms.items()
        if isinstance(cfg, dict) and not cfg.get("enabled", True)
    }
 
    PLATFORM_TOOL_PREFIX = {
        "dv360": "dv360_",
        "tiktok": "tiktok_",
        "shopify": "shopify_",
    }
 
    prefixes_to_exclude = {
        PLATFORM_TOOL_PREFIX[p] for p in disabled if p in PLATFORM_TOOL_PREFIX
    }
 
    if not prefixes_to_exclude:
        return tools
 
    return [
        t for t in tools
        if not any(t["name"].startswith(prefix) for prefix in prefixes_to_exclude)
    ]
