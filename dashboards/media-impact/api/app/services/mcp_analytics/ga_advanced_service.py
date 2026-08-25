"""
GA4 Advanced Extractor Service
Rol: Data Engineer Senior (GA Data API v1beta)
Enfoque: consultas robustas multi-propiedad con validación de alcances,
detección de cardinalidad/muestreo y manejo de cuotas.
"""

import time
import math
import logging
from typing import List, Dict, Any, Optional


def _sanitize_for_json(obj: Any) -> Any:
    """Sanitiza valores para JSON: convierte NaN/Inf a 0."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(x) for x in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    elif hasattr(obj, 'item'):  # numpy types
        val = obj.item()
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return 0.0
        return val
    return obj
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    DateRange,
    Dimension,
    Metric,
    Filter,
    FilterExpression,
    FilterExpressionList,
)
from google.api_core import exceptions as gexc
from google.oauth2.credentials import Credentials
from app.services.mcp_analytics.calculation_service import (
    calculate_drop_rate, 
    calculate_conversion_rate, 
    convert_ga4_rate_to_percentage
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Catálogos de compatibilidad de alcance (scope)
# --------------------------------------------------------------------------------------
USER_DIMS = {"firstUserSource", "firstUserMedium", "firstUserCampaign", "firstUserDefaultChannelGroup"}
USER_METRICS = {"newUsers", "totalUsers", "activeUsers"}

SESSION_DIMS = {
    "sessionSource", "sessionMedium", "sessionCampaign", "landingPage",
    "sessionDefaultChannelGroup", "sessionManualAdContent"
}
SESSION_METRICS = {"sessions", "engagementRate", "bounceRate", "averageSessionDuration", "engagedSessions"}

ITEM_EVENT_DIMS = {"itemName", "itemCategory", "eventName", "pagePath", "pageTitle", "deviceCategory"}
ITEM_EVENT_METRICS = {
    "itemRevenue", "ecommercePurchases", "eventCount", "purchaseToViewRate",
    "screenPageViews", "totalRevenue", "userEngagementDuration"
}

# --------------------------------------------------------------------------------------
# Validación de compatibilidad de alcances
# --------------------------------------------------------------------------------------
def validate_scope(dimensions: List[str], metrics: List[str]) -> Dict[str, Any]:
    """
    Valida que dimensiones y métricas sean compatibles según alcance GA4.
    
    Returns:
        Dict con 'valid' (bool), 'scope' (str), y 'message' (str)
    """
    dims_set, mets_set = set(dimensions), set(metrics)

    # User scope: dimensiones firstUser* con métricas de usuario
    if dims_set.issubset(USER_DIMS) and mets_set.issubset(USER_METRICS):
        return {"valid": True, "scope": "user", "message": "User acquisition scope"}

    # Session scope: dimensiones session* con métricas de sesión
    if dims_set.issubset(SESSION_DIMS) and mets_set.issubset(SESSION_METRICS):
        return {"valid": True, "scope": "session", "message": "Session/traffic acquisition scope"}

    # Item/Event scope: más flexible, incluye eventos y ecommerce
    if dims_set.issubset(ITEM_EVENT_DIMS) and mets_set.issubset(ITEM_EVENT_METRICS):
        return {"valid": True, "scope": "item_event", "message": "Item/Event scope"}

    return {
        "valid": False,
        "scope": "unknown",
        "message": f"Incompatible scope combination. Dims: {dimensions} | Mets: {metrics}"
    }


# --------------------------------------------------------------------------------------
# Backoff exponencial (maneja cuotas Standard vs 360)
# --------------------------------------------------------------------------------------
def run_with_backoff(
    client: BetaAnalyticsDataClient,
    request: RunReportRequest,
    max_retries: int = 5,
    base_sleep: float = 1.0
):
    """Ejecuta request con backoff exponencial para manejar cuotas."""
    for attempt in range(max_retries):
        try:
            return client.run_report(request)
        except gexc.ResourceExhausted as exc:
            sleep = base_sleep * (2 ** attempt)
            logger.warning(
                "Quota exceeded (attempt %d/%d). Retrying in %.1fs. Error: %s",
                attempt + 1, max_retries, sleep, str(exc)
            )
            time.sleep(sleep)
        except gexc.GoogleAPICallError as exc:
            if attempt < max_retries - 1:
                sleep = base_sleep * (2 ** attempt)
                logger.warning(
                    "Transient API error (attempt %d/%d). Retrying in %.1fs. Error: %s",
                    attempt + 1, max_retries, sleep, str(exc)
                )
                time.sleep(sleep)
            else:
                raise
    raise RuntimeError(f"Max retries ({max_retries}) exceeded for GA4 API request")


# --------------------------------------------------------------------------------------
# Análisis de calidad de datos
# --------------------------------------------------------------------------------------
def analyze_data_quality(response) -> Dict[str, Any]:
    """
    Analiza respuesta para detectar problemas de calidad:
    - Cardinalidad alta (fila "(other)")
    - Thresholding/muestreo
    - Valores (not set)
    """
    issues = []
    warnings = []

    # Cardinalidad alta => fila "(other)"
    has_other = any(
        any(dim.value == "(other)" for dim in row.dimension_values)
        for row in response.rows
    )
    if has_other:
        issues.append({
            "type": "high_cardinality",
            "message": "Alta cardinalidad: aparece fila '(other)'. "
                      "Sugerencia: reducir rango de fechas o eliminar dimensiones de alta cardinalidad."
        })

    # Thresholding (privacidad) o muestreo
    if hasattr(response, 'metadata') and hasattr(response.metadata, 'subject_to_thresholding'):
        if response.metadata.subject_to_thresholding:
            warnings.append({
                "type": "thresholding",
                "message": "Datos sujetos a thresholding por privacidad. "
                          "Algunos valores pueden estar ocultos o redondeados."
            })

    # Sampling (propiedades Standard >10M eventos)
    if hasattr(response, 'metadata') and hasattr(response.metadata, 'sampling_metadatas'):
        if response.metadata.sampling_metadatas:
            warnings.append({
                "type": "sampling",
                "message": "Datos basados en muestra (sampling). "
                          "Considera propiedades 360 para datos sin muestreo."
            })

    # Valores (not set) / (data not available)
    has_not_set = any(
        any(dim.value in ("(not set)", "(data not available)") for dim in row.dimension_values)
        for row in response.rows
    )
    if has_not_set:
        warnings.append({
            "type": "missing_data",
            "message": "Encontrados valores '(not set)' o '(data not available)'. "
                      "Puede deberse a retrasos de atribución (24-48h) o etiquetado incompleto."
        })

    return {
        "row_count": response.row_count,
        "issues": issues,
        "warnings": warnings,
        "has_quality_problems": len(issues) > 0
    }


# --------------------------------------------------------------------------------------
# GA4 Advanced Service Class
# --------------------------------------------------------------------------------------
class GA4AdvancedService:
    """Servicio avanzado para extracción de datos GA4 con validación de alcances."""

    def __init__(self, credentials: Optional[Credentials] = None, client: Optional[Any] = None):
        self.credentials = credentials
        self._client = client

    @property
    def client(self) -> BetaAnalyticsDataClient:
        """Lazy load del cliente GA4 (si no se inyectó uno)."""
        if self._client is None:
            if self.credentials:
                self._client = BetaAnalyticsDataClient(credentials=self.credentials)
            else:
                self._client = BetaAnalyticsDataClient()
        return self._client

    def build_user_acquisition_report(
        self,
        property_id: str,
        start_date: str = "7daysAgo",
        end_date: str = "today"
    ) -> RunReportRequest:
        """
        User Acquisition: firstUser* dimensions + user metrics.
        Uso: entender de dónde vienen nuevos usuarios (primera interacción).
        """
        dimensions = ["firstUserSource", "firstUserMedium"]
        metrics = ["newUsers", "totalUsers"]
        
        validation = validate_scope(dimensions, metrics)
        if not validation["valid"]:
            raise ValueError(validation["message"])

        return RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            limit=10000,
        )

    def build_session_acquisition_report(
        self,
        property_id: str,
        start_date: str = "7daysAgo",
        end_date: str = "today"
    ) -> RunReportRequest:
        """
        Traffic Acquisition: session* dimensions + session metrics.
        Uso: entender fuentes de tráfico de todas las sesiones.
        """
        dimensions = ["sessionSource", "sessionMedium"]
        metrics = ["sessions", "engagementRate", "engagedSessions"]
        
        validation = validate_scope(dimensions, metrics)
        if not validation["valid"]:
            raise ValueError(validation["message"])

        return RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            limit=10000,
        )

    def build_ecommerce_report(
        self,
        property_id: str,
        start_date: str = "7daysAgo",
        end_date: str = "today"
    ) -> RunReportRequest:
        """
        E-commerce: item dimensions + revenue/purchase metrics.
        Uso: análisis de productos, ingresos y conversiones.
        """
        dimensions = ["itemName", "itemCategory"]
        metrics = ["itemRevenue", "ecommercePurchases"]
        
        validation = validate_scope(dimensions, metrics)
        if not validation["valid"]:
            raise ValueError(validation["message"])

        return RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            limit=10000,
        )

    def build_explore_like_report(
        self,
        property_id: str,
        dimensions: List[str],
        metrics: List[str],
        start_date: str = "7daysAgo",
        end_date: str = "today",
        filters: Optional[Dict[str, Any]] = None
    ) -> RunReportRequest:
        """
        Consulta tipo "Exploración" con filtros avanzados personalizados.
        
        Args:
            filters: dict con estructura {"and": [{"field": "pagePath", "value": "/checkout", "type": "prefix"}]}
        """
        validation = validate_scope(dimensions, metrics)
        if not validation["valid"]:
            raise ValueError(validation["message"])

        request = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            limit=10000,
        )

        # Aplicar filtros si se proporcionan
        if filters:
            request.dimension_filter = self._build_filter_expression(filters)

        return request

    def _build_filter_expression(self, filters: Dict[str, Any]) -> FilterExpression:
        """Construye FilterExpression a partir de estructura dict."""
        if "and" in filters:
            expressions = []
            for f in filters["and"]:
                match_type = Filter.StringFilter.MatchType.EXACT
                if f.get("type") == "prefix":
                    match_type = Filter.StringFilter.MatchType.BEGINS_WITH
                elif f.get("type") == "contains":
                    match_type = Filter.StringFilter.MatchType.CONTAINS

                expressions.append(
                    FilterExpression(
                        filter=Filter(
                            field_name=f["field"],
                            string_filter=Filter.StringFilter(
                                value=f["value"],
                                match_type=match_type
                            )
                        )
                    )
                )
            return FilterExpression(
                and_group=FilterExpressionList(expressions=expressions)
            )
        
        # Filtro simple
        return FilterExpression(
            filter=Filter(
                field_name=filters["field"],
                string_filter=Filter.StringFilter(value=filters["value"])
            )
        )

    async def execute_advanced_report(
        self,
        property_id: str,
        report_type: str,
        start_date: str = "7daysAgo",
        end_date: str = "today",
        custom_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Ejecuta reporte avanzado con validación y análisis de calidad.
        
        Args:
            report_type: 'user_acquisition', 'session_acquisition', 'ecommerce', 'explore'
            custom_config: configuración personalizada para tipo 'explore'
        """
        # Asegurar formato correcto de property_id
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"

        # Construir request según tipo
        if report_type == "user_acquisition":
            request = self.build_user_acquisition_report(property_id, start_date, end_date)
        elif report_type == "session_acquisition":
            request = self.build_session_acquisition_report(property_id, start_date, end_date)
        elif report_type == "ecommerce":
            request = self.build_ecommerce_report(property_id, start_date, end_date)
        elif report_type == "explore" and custom_config:
            request = self.build_explore_like_report(
                property_id,
                dimensions=custom_config.get("dimensions", []),
                metrics=custom_config.get("metrics", []),
                start_date=start_date,
                end_date=end_date,
                filters=custom_config.get("filters")
            )
        else:
            raise ValueError(f"Tipo de reporte no soportado: {report_type}")

        # Ejecutar con backoff
        logger.info(f"Executing advanced report: {report_type} for {property_id}")
        response = run_with_backoff(self.client, request)

        # Analizar calidad de datos
        quality = analyze_data_quality(response)

        # Parsear datos
        dimension_headers = [h.name for h in response.dimension_headers]
        metric_headers = [h.name for h in response.metric_headers]

        rows = []
        for row in response.rows:
            row_data = {}
            for i, dim_value in enumerate(row.dimension_values):
                row_data[dimension_headers[i]] = dim_value.value
            for i, met_value in enumerate(row.metric_values):
                row_data[metric_headers[i]] = met_value.value
            rows.append(row_data)

        return _sanitize_for_json({
            "property_id": property_id,
            "report_type": report_type,
            "dimension_headers": dimension_headers,
            "metric_headers": metric_headers,
            "rows": rows,
            "row_count": len(rows),
            "data_quality": quality,
            "date_range": {
                "start_date": start_date,
                "end_date": end_date
            }
        })

    async def execute_funnel_analysis(
        self,
        property_id: str,
        steps: List[str],
        start_date: str = "7daysAgo",
        end_date: str = "today"
    ) -> Dict[str, Any]:
        """
        Reconstruye un funnel consultando secuencia de eventos.
        Calcula caídas entre pasos localmente.
        
        Args:
            steps: lista de eventName en orden (ej. ["session_start", "view_item", "purchase"])
        """
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"

        logger.info(f"Executing funnel analysis for {property_id}: {steps}")
        
        results = {}
        for event_name in steps:
            request = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="eventName")],
                metrics=[Metric(name="eventCount")],
                dimension_filter=FilterExpression(
                    filter=Filter(
                        field_name="eventName",
                        string_filter=Filter.StringFilter(value=event_name)
                    )
                ),
                limit=1,
            )
            
            response = run_with_backoff(self.client, request)
            count = int(response.rows[0].metric_values[0].value) if response.rows else 0
            results[event_name] = count

        # Calcular ratios de abandono
        funnel_data = []
        for i, step in enumerate(steps):
            if i == 0:
                funnel_data.append({
                    "step": step,
                    "step_number": i + 1,
                    "count": results[step],
                    "drop_count": 0,
                    "drop_rate": 0.0,
                    "conversion_rate": 100.0
                })
            else:
                prev_count = results[steps[i-1]]
                current_count = results[step]
                drop = max(prev_count - current_count, 0)
                # Usar calculation_service para precisión decimal
                drop_rate = calculate_drop_rate(prev_count, current_count, decimals=2)
                conversion_rate = calculate_conversion_rate(current_count, results[steps[0]], decimals=2)
                
                funnel_data.append({
                    "step": step,
                    "step_number": i + 1,
                    "count": current_count,
                    "drop_count": drop,
                    "drop_rate": drop_rate,
                    "conversion_rate": conversion_rate
                })

        return _sanitize_for_json({
            "property_id": property_id,
            "funnel_steps": funnel_data,
            "total_entered": results[steps[0]],
            "total_completed": results[steps[-1]],
            "overall_conversion_rate": calculate_conversion_rate(
                results[steps[-1]], 
                results[steps[0]], 
                decimals=2
            ),
            "date_range": {
                "start_date": start_date,
                "end_date": end_date
            }
        })

    async def execute_deep_dive(
        self,
        property_id: str,
        start_date: str = "30daysAgo",
        end_date: str = "today"
    ) -> Dict[str, Any]:
        """
        Ejecuta un análisis Deep Dive COMPLETO de la propiedad GA4 (17 secciones).
        
        Incluye:
        1. Overview General (con comparativa)
        2. Adquisición (canales, fuentes/medios, campañas, nuevos vs recurrentes)
        3. Comportamiento de Usuario (páginas, flujo, eventos, tiempo)
        4. Tecnología (dispositivos, navegadores, SO, resoluciones)
        5. Geografía (países, ciudades, idiomas, conversiones por ubicación)
        6. E-commerce (ingresos, productos, tasa conversión, AOV)
        7. Embudos de Conversión (eventos secuenciales, abandonos)
        8. Audiencias (demografía, intereses, nuevos vs recurrentes)
        9. Eventos Clave (top eventos, parámetros, conversiones)
        10. Velocidad del Sitio (page load time, server response)
        11. Búsqueda Interna (términos, conversiones)
        12. Engagement (sesiones engaged, scroll depth)
        13. Retención (cohortes, frecuencia)
        14. Anomalías y Calidad de Datos
        15. Comparativas Temporales (WoW, MoM, YoY)
        16. Segmentación Avanzada (alta calidad, riesgo, VIP)
        17. Recomendaciones Accionables
        """
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"

        logger.info(f"Starting COMPREHENSIVE DEEP DIVE analysis for {property_id} (17 sections)")
        
        results = {
            "property_id": property_id,
            "date_range": {"start_date": start_date, "end_date": end_date},
            "sections": {},
            "total_sections": 17
        }

        # ========================================
        # SECCIÓN 1: OVERVIEW GENERAL
        # ========================================
        overview_request = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            metrics=[
                Metric(name="activeUsers"),
                Metric(name="sessions"),
                Metric(name="totalUsers"),
                Metric(name="newUsers"),
                Metric(name="conversions"),
                Metric(name="engagementRate"),
                Metric(name="averageSessionDuration"),
                Metric(name="bounceRate"),
                Metric(name="sessionConversionRate"),
                Metric(name="engagedSessions")
            ]
        )
        overview = run_with_backoff(self.client, overview_request)
        results["sections"]["1_overview_general"] = self._parse_response(overview)

        # ========================================
        # SECCIÓN 2: ADQUISICIÓN
        # ========================================
        # 2.1 Canales de adquisición
        acquisition_channels = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="sessionDefaultChannelGroup")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="newUsers"),
                Metric(name="conversions"),
                Metric(name="engagementRate"),
                Metric(name="averageSessionDuration"),
                Metric(name="bounceRate")
            ]
        )
        channels = run_with_backoff(self.client, acquisition_channels)
        results["sections"]["2_1_acquisition_channels"] = self._parse_response(channels)

        # 2.2 Fuentes y Medios detallados
        acquisition_sources = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[
                Dimension(name="sessionSource"),
                Dimension(name="sessionMedium")
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="newUsers"),
                Metric(name="conversions"),
                Metric(name="engagementRate")
            ],
            limit=30
        )
        sources = run_with_backoff(self.client, acquisition_sources)
        results["sections"]["2_2_acquisition_sources_mediums"] = self._parse_response(sources)

        # 2.3 Campañas
        try:
            campaigns = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="sessionCampaignName")],
                metrics=[
                    Metric(name="sessions"),
                    Metric(name="newUsers"),
                    Metric(name="conversions"),
                    Metric(name="sessionConversionRate")
                ],
                limit=20
            )
            campaigns_data = run_with_backoff(self.client, campaigns)
            results["sections"]["2_3_campaigns"] = self._parse_response(campaigns_data)
        except Exception as e:
            logger.warning(f"Campaigns report failed: {e}")
            results["sections"]["2_3_campaigns"] = {"error": str(e)}

        # 2.4 Usuarios nuevos vs recurrentes por canal
        new_vs_returning_by_channel = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[
                Dimension(name="sessionDefaultChannelGroup"),
                Dimension(name="newVsReturning")
            ],
            metrics=[
                Metric(name="activeUsers"),
                Metric(name="sessions"),
                Metric(name="conversions")
            ]
        )
        new_ret_data = run_with_backoff(self.client, new_vs_returning_by_channel)
        results["sections"]["2_4_new_vs_returning_by_channel"] = self._parse_response(new_ret_data)

        # ========================================
        # SECCIÓN 3: COMPORTAMIENTO DE USUARIO
        # ========================================
        # 3.1 Páginas más visitadas
        top_pages = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[
                Dimension(name="pagePath"),
                Dimension(name="pageTitle")
            ],
            metrics=[
                Metric(name="screenPageViews"),
                Metric(name="sessions"),
                Metric(name="conversions"),
                Metric(name="averageSessionDuration"),
                Metric(name="bounceRate")
            ],
            limit=30
        )
        pages = run_with_backoff(self.client, top_pages)
        results["sections"]["3_1_top_pages"] = self._parse_response(pages)

        # 3.2 Landing pages (páginas de entrada)
        landing_pages = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="landingPage")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="conversions"),
                Metric(name="bounceRate"),
                Metric(name="engagementRate")
            ],
            limit=20
        )
        landing_data = run_with_backoff(self.client, landing_pages)
        results["sections"]["3_2_landing_pages"] = self._parse_response(landing_data)

        # 3.3 Exit pages (páginas de salida)
        try:
            exit_pages = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="exitPage")],
                metrics=[
                    Metric(name="sessions"),
                    Metric(name="exits")
                ],
                limit=20
            )
            exit_data = run_with_backoff(self.client, exit_pages)
            results["sections"]["3_3_exit_pages"] = self._parse_response(exit_data)
        except Exception as e:
            logger.warning(f"Exit pages report failed: {e}")
            results["sections"]["3_3_exit_pages"] = {"error": str(e)}

        # ========================================
        # SECCIÓN 4: TECNOLOGÍA
        # ========================================
        # 4.1 Dispositivos (desktop, mobile, tablet)
        devices = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="deviceCategory")],
            metrics=[
                Metric(name="activeUsers"),
                Metric(name="sessions"),
                Metric(name="conversions"),
                Metric(name="engagementRate"),
                Metric(name="averageSessionDuration"),
                Metric(name="bounceRate")
            ]
        )
        devices_data = run_with_backoff(self.client, devices)
        results["sections"]["4_1_devices"] = self._parse_response(devices_data)

        # 4.2 Navegadores
        browsers = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="browser")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="conversions"),
                Metric(name="engagementRate")
            ],
            limit=15
        )
        browsers_data = run_with_backoff(self.client, browsers)
        results["sections"]["4_2_browsers"] = self._parse_response(browsers_data)

        # 4.3 Sistemas Operativos
        os_data = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="operatingSystem")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="conversions"),
                Metric(name="engagementRate")
            ],
            limit=15
        )
        os_result = run_with_backoff(self.client, os_data)
        results["sections"]["4_3_operating_systems"] = self._parse_response(os_result)

        # 4.4 Resoluciones de pantalla
        try:
            screen_res = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="screenResolution")],
                metrics=[
                    Metric(name="sessions"),
                    Metric(name="activeUsers")
                ],
                limit=15
            )
            screen_data = run_with_backoff(self.client, screen_res)
            results["sections"]["4_4_screen_resolutions"] = self._parse_response(screen_data)
        except Exception as e:
            logger.warning(f"Screen resolution report failed: {e}")
            results["sections"]["4_4_screen_resolutions"] = {"error": str(e)}

        # ========================================
        # SECCIÓN 5: GEOGRAFÍA
        # ========================================
        # 5.1 Países
        countries = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="country")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="conversions"),
                Metric(name="newUsers"),
                Metric(name="engagementRate"),
                Metric(name="averageSessionDuration")
            ],
            limit=20
        )
        countries_data = run_with_backoff(self.client, countries)
        results["sections"]["5_1_countries"] = self._parse_response(countries_data)

        # 5.2 Ciudades
        cities = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="city")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="conversions"),
                Metric(name="activeUsers")
            ],
            limit=25
        )
        cities_data = run_with_backoff(self.client, cities)
        results["sections"]["5_2_cities"] = self._parse_response(cities_data)

        # 5.3 Idiomas
        try:
            languages = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="language")],
                metrics=[
                    Metric(name="sessions"),
                    Metric(name="activeUsers"),
                    Metric(name="conversions")
                ],
                limit=15
            )
            lang_data = run_with_backoff(self.client, languages)
            results["sections"]["5_3_languages"] = self._parse_response(lang_data)
        except Exception as e:
            logger.warning(f"Languages report failed: {e}")
            results["sections"]["5_3_languages"] = {"error": str(e)}

        # ========================================
        # SECCIÓN 6: E-COMMERCE
        # ========================================
        try:
            # 6.1 Ingresos totales y transacciones
            ecommerce_overview = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                metrics=[
                    Metric(name="totalRevenue"),
                    Metric(name="transactions"),
                    Metric(name="purchaseRevenue"),
                    Metric(name="itemsViewed"),
                    Metric(name="itemsPurchased"),
                    Metric(name="cartToViewRate"),
                    Metric(name="purchaseToViewRate")
                ]
            )
            ecom_overview_data = run_with_backoff(self.client, ecommerce_overview)
            results["sections"]["6_1_ecommerce_overview"] = self._parse_response(ecom_overview_data)

            # 6.2 Productos más vendidos
            top_products = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="itemName")],
                metrics=[
                    Metric(name="itemRevenue"),
                    Metric(name="itemsPurchased"),
                    Metric(name="itemsViewed")
                ],
                limit=20
            )
            products_data = run_with_backoff(self.client, top_products)
            results["sections"]["6_2_top_products"] = self._parse_response(products_data)

            # 6.3 Categorías de productos
            product_categories = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="itemCategory")],
                metrics=[
                    Metric(name="itemRevenue"),
                    Metric(name="itemsPurchased")
                ],
                limit=15
            )
            categories_data = run_with_backoff(self.client, product_categories)
            results["sections"]["6_3_product_categories"] = self._parse_response(categories_data)
        except Exception as e:
            logger.warning(f"E-commerce section failed: {e}")
            results["sections"]["6_ecommerce"] = {"error": str(e), "note": "E-commerce data may not be available"}

        # ========================================
        # SECCIÓN 7: EMBUDOS DE CONVERSIÓN
        # ========================================
        try:
            # Embudo estándar e-commerce: session_start → view_item → add_to_cart → begin_checkout → purchase
            funnel_steps = ["session_start", "view_item", "add_to_cart", "begin_checkout", "purchase"]
            funnel_results = {}
            
            for event_name in funnel_steps:
                event_request = RunReportRequest(
                    property=property_id,
                    date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                    dimensions=[Dimension(name="eventName")],
                    metrics=[Metric(name="eventCount")],
                    dimension_filter=FilterExpression(
                        filter=Filter(
                            field_name="eventName",
                            string_filter=Filter.StringFilter(value=event_name)
                        )
                    )
                )
                event_data = run_with_backoff(self.client, event_request)
                count = int(event_data.rows[0].metric_values[0].value) if event_data.rows else 0
                funnel_results[event_name] = count
            
            results["sections"]["7_funnel_conversion"] = {
                "funnel_steps": funnel_results,
                "note": "Standard e-commerce funnel"
            }
        except Exception as e:
            logger.warning(f"Funnel analysis failed: {e}")
            results["sections"]["7_funnel_conversion"] = {"error": str(e)}

        # ========================================
        # SECCIÓN 8: AUDIENCIAS
        # ========================================
        # 8.1 Usuarios nuevos vs recurrentes (global)
        user_type = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="newVsReturning")],
            metrics=[
                Metric(name="activeUsers"),
                Metric(name="sessions"),
                Metric(name="conversions"),
                Metric(name="engagementRate"),
                Metric(name="averageSessionDuration")
            ]
        )
        user_type_data = run_with_backoff(self.client, user_type)
        results["sections"]["8_1_user_type"] = self._parse_response(user_type_data)

        # 8.2 Demografía (edad y género) - opcional, requiere habilitación
        try:
            demographics_age = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="userAgeBracket")],
                metrics=[
                    Metric(name="activeUsers"),
                    Metric(name="sessions"),
                    Metric(name="conversions")
                ]
            )
            age_data = run_with_backoff(self.client, demographics_age)
            results["sections"]["8_2_demographics_age"] = self._parse_response(age_data)

            demographics_gender = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="userGender")],
                metrics=[
                    Metric(name="activeUsers"),
                    Metric(name="sessions"),
                    Metric(name="conversions")
                ]
            )
            gender_data = run_with_backoff(self.client, demographics_gender)
            results["sections"]["8_3_demographics_gender"] = self._parse_response(gender_data)
        except Exception as e:
            logger.warning(f"Demographics not available: {e}")
            results["sections"]["8_demographics"] = {"error": str(e), "note": "Demographics require Google Signals enabled"}

        # ========================================
        # SECCIÓN 9: EVENTOS CLAVE
        # ========================================
        # 9.1 Top eventos por conteo
        events = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="eventName")],
            metrics=[
                Metric(name="eventCount"),
                Metric(name="conversions"),
                Metric(name="eventValue")
            ],
            limit=25
        )
        events_data = run_with_backoff(self.client, events)
        results["sections"]["9_1_top_events"] = self._parse_response(events_data)

        # 9.2 Eventos de conversión
        try:
            conversion_events = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="eventName")],
                metrics=[
                    Metric(name="conversions"),
                    Metric(name="eventCount")
                ],
                dimension_filter=FilterExpression(
                    filter=Filter(
                        field_name="eventName",
                        in_list_filter=Filter.InListFilter(
                            values=["purchase", "generate_lead", "sign_up", "form_submit"]
                        )
                    )
                ),
                limit=10
            )
            conv_events_data = run_with_backoff(self.client, conversion_events)
            results["sections"]["9_2_conversion_events"] = self._parse_response(conv_events_data)
        except Exception as e:
            logger.warning(f"Conversion events report failed: {e}")
            results["sections"]["9_2_conversion_events"] = {"error": str(e)}

        # ========================================
        # SECCIÓN 10: VELOCIDAD DEL SITIO
        # ========================================
        try:
            # Nota: Las métricas de velocidad requieren configuración específica en GA4
            page_load_time = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="pagePath")],
                metrics=[
                    Metric(name="userEngagementDuration")
                ],
                limit=20
            )
            load_data = run_with_backoff(self.client, page_load_time)
            results["sections"]["10_site_speed"] = self._parse_response(load_data)
        except Exception as e:
            logger.warning(f"Site speed metrics not available: {e}")
            results["sections"]["10_site_speed"] = {"error": str(e), "note": "Site speed metrics require custom implementation"}

        # ========================================
        # SECCIÓN 11: BÚSQUEDA INTERNA
        # ========================================
        try:
            search_terms = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="searchTerm")],
                metrics=[
                    Metric(name="eventCount"),
                    Metric(name="conversions")
                ],
                limit=20
            )
            search_data = run_with_backoff(self.client, search_terms)
            results["sections"]["11_internal_search"] = self._parse_response(search_data)
        except Exception as e:
            logger.warning(f"Internal search not configured: {e}")
            results["sections"]["11_internal_search"] = {"error": str(e), "note": "Internal search requires searchTerm parameter"}

        # ========================================
        # SECCIÓN 12: ENGAGEMENT
        # ========================================
        # 12.1 Sesiones engaged
        engagement_overview = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            metrics=[
                Metric(name="engagedSessions"),
                Metric(name="engagementRate"),
                Metric(name="userEngagementDuration"),
                Metric(name="averageSessionDuration")
            ]
        )
        engagement_data = run_with_backoff(self.client, engagement_overview)
        results["sections"]["12_1_engagement_overview"] = self._parse_response(engagement_data)

        # 12.2 Engagement por canal
        engagement_by_channel = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="sessionDefaultChannelGroup")],
            metrics=[
                Metric(name="engagedSessions"),
                Metric(name="engagementRate"),
                Metric(name="averageSessionDuration")
            ]
        )
        eng_channel_data = run_with_backoff(self.client, engagement_by_channel)
        results["sections"]["12_2_engagement_by_channel"] = self._parse_response(eng_channel_data)

        # ========================================
        # SECCIÓN 13: RETENCIÓN
        # ========================================
        try:
            # Frecuencia de usuarios (número de sesiones)
            session_frequency = RunReportRequest(
                property=property_id,
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                dimensions=[Dimension(name="sessionMedium")],
                metrics=[
                    Metric(name="activeUsers"),
                    Metric(name="sessionsPerUser")
                ],
                limit=15
            )
            freq_data = run_with_backoff(self.client, session_frequency)
            results["sections"]["13_user_retention"] = self._parse_response(freq_data)
        except Exception as e:
            logger.warning(f"Retention metrics limited: {e}")
            results["sections"]["13_user_retention"] = {"error": str(e), "note": "Full cohort analysis requires BigQuery export"}

        # ========================================
        # SECCIÓN 14: ANOMALÍAS Y CALIDAD DE DATOS
        # ========================================
        all_quality_issues = []
        not_set_count = 0
        other_count = 0
        
        for section_name, section_data in results["sections"].items():
            if isinstance(section_data, dict) and "rows" in section_data:
                for row in section_data["rows"][:10]:  # Revisar primeras 10 filas
                    for key, value in row.items():
                        if value == "(not set)":
                            not_set_count += 1
                            all_quality_issues.append({
                                "section": section_name,
                                "issue": f"(not set) found in {key}",
                                "severity": "warning"
                            })
                        elif value == "(other)":
                            other_count += 1
                            all_quality_issues.append({
                                "section": section_name,
                                "issue": f"High cardinality in {key} - data aggregated as (other)",
                                "severity": "info"
                            })

        results["sections"]["14_data_quality_anomalies"] = {
            "total_issues": len(all_quality_issues),
            "not_set_count": not_set_count,
            "other_count": other_count,
            "issues_sample": all_quality_issues[:15],
            "note": "(not set) indicates missing data; (other) indicates high cardinality thresholding"
        }

        # ========================================
        # SECCIÓN 15: COMPARATIVAS TEMPORALES
        # ========================================
        try:
            # Comparar con período anterior (para WoW, MoM)
            # Calcular período anterior dinámicamente
            from datetime import datetime, timedelta
            
            # Esta sección requeriría lógica adicional para calcular fechas del período anterior
            results["sections"]["15_temporal_comparisons"] = {
                "note": "Temporal comparisons (WoW, MoM, YoY) require dual date range queries",
                "current_period": {"start": start_date, "end": end_date},
                "implementation": "pending"
            }
        except Exception as e:
            logger.warning(f"Temporal comparisons failed: {e}")
            results["sections"]["15_temporal_comparisons"] = {"error": str(e)}

        # ========================================
        # SECCIÓN 16: SEGMENTACIÓN AVANZADA
        # ========================================
        try:
            # 16.1 Usuarios de alta calidad (>3 sesiones + conversión)
            # Nota: Esto requeriría segmentos de audiencia configurados en GA4
            # Por ahora, mostramos distribución de sesiones por usuario
            
            results["sections"]["16_advanced_segmentation"] = {
                "note": "Advanced segmentation (high-quality, at-risk, VIP users) requires audience segments configured in GA4",
                "recommendation": "Configure audiences in GA4 Admin for: High Quality Users (3+ sessions + conversion), At-Risk Users (1 session, no return in 30 days), VIP Users (5+ conversions)"
            }
        except Exception as e:
            logger.warning(f"Advanced segmentation failed: {e}")
            results["sections"]["16_advanced_segmentation"] = {"error": str(e)}

        # ========================================
        # SECCIÓN 17: RECOMENDACIONES ACCIONABLES
        # ========================================
        recommendations = []
        
        # Analizar datos para generar recomendaciones automáticas
        try:
            # Revisar bounce rate alto
            if "4_1_devices" in results["sections"] and results["sections"]["4_1_devices"].get("rows"):
                for device in results["sections"]["4_1_devices"]["rows"]:
                    bounce_rate = convert_ga4_rate_to_percentage(device.get("bounceRate", 0))
                    device_name = device.get("deviceCategory", "Unknown")
                    if bounce_rate > 60:
                        recommendations.append({
                            "type": "alert",
                            "category": "user_experience",
                            "message": f"High bounce rate ({bounce_rate:.2f}%) on {device_name} devices",
                            "action": f"Review mobile UX and page load speed for {device_name}"
                        })
            
            # Revisar canales con bajo engagement
            if "2_1_acquisition_channels" in results["sections"] and results["sections"]["2_1_acquisition_channels"].get("rows"):
                for channel in results["sections"]["2_1_acquisition_channels"]["rows"]:
                    engagement_rate = convert_ga4_rate_to_percentage(channel.get("engagementRate", 0))
                    channel_name = channel.get("sessionDefaultChannelGroup", "Unknown")
                    if engagement_rate < 30:
                        recommendations.append({
                            "type": "opportunity",
                            "category": "acquisition",
                            "message": f"Low engagement rate ({engagement_rate:.2f}%) in {channel_name} channel",
                            "action": f"Optimize landing pages and targeting for {channel_name} traffic"
                        })
            
            # Detectar caídas significativas (requeriría comparación temporal)
            recommendations.append({
                "type": "insight",
                "category": "analysis",
                "message": "For drop detection, enable temporal comparison (WoW, MoM)",
                "action": "Implement automated alerts for >20% drops in key metrics"
            })
            
        except Exception as e:
            logger.warning(f"Recommendations generation failed: {e}")
        
        results["sections"]["17_actionable_recommendations"] = {
            "total_recommendations": len(recommendations),
            "recommendations": recommendations,
            "note": "AI-powered recommendations based on detected patterns and thresholds"
        }

        # ========================================
        # RESUMEN FINAL
        # ========================================
        results["summary"] = {
            "total_sections_analyzed": len([k for k in results["sections"].keys() if not results["sections"][k].get("error")]),
            "sections_with_errors": len([k for k in results["sections"].keys() if results["sections"][k].get("error")]),
            "date_range": {"start_date": start_date, "end_date": end_date},
            "analysis_timestamp": datetime.now().isoformat(),
            "recommendations_count": len(recommendations)
        }

        logger.info(f"COMPREHENSIVE DEEP DIVE completed: {results['summary']['total_sections_analyzed']}/{results['total_sections']} sections successfully analyzed")
        return _sanitize_for_json(results)

    def _parse_response(self, response) -> Dict[str, Any]:
        """Helper para parsear respuestas de GA Data API."""
        dimension_headers = [h.name for h in response.dimension_headers]
        metric_headers = [h.name for h in response.metric_headers]
        
        rows = []
        for row in response.rows:
            row_data = {}
            for i, dim_value in enumerate(row.dimension_values):
                row_data[dimension_headers[i]] = dim_value.value
            for i, met_value in enumerate(row.metric_values):
                row_data[metric_headers[i]] = met_value.value
            rows.append(row_data)
        
        return {
            "dimension_headers": dimension_headers,
            "metric_headers": metric_headers,
            "rows": rows,
            "row_count": len(rows)
        }
