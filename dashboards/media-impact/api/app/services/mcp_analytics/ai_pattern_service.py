"""Servicio para el análisis de patrones de IA (Lookalike Analysis).

Este servicio realiza un análisis en dos fases:
1. Benchmark: Calcula los KPIs del tráfico que viene confirmado de fuentes de IA.
2. Matching: Identifica segmentos de tráfico en otros canales (Directo, Orgánico) 
   que muestran patrones de comportamiento similares al benchmark de IA.
"""

import logging
from typing import Dict, Any, List, Optional
import pandas as pd
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    DateRange,
    Dimension,
    Metric,
    FilterExpression,
    Filter,
    FilterExpressionList,
)
from app.services.mcp_analytics.calculation_service import (
    calculate_percentage, 
    calculate_conversion_rate, 
    calculate_aov,
    convert_ga4_rate_to_percentage
)

logger = logging.getLogger(__name__)

class AIPatternService:
    def __init__(self, ga_service):
        """
        Inicializa el servicio.
        
        Args:
            ga_service: Instancia de GAService para realizar consultas a la API.
        """
        self.ga_service = ga_service
        # Nota: "bing" ha sido eliminado para contar SOLO tráfico de Copilot (IA)
        self.ai_sources = [
            "chatgpt", "openai", "bard", "perplexity", 
            "claude", "copilot", "gemini", "anthropic"
        ]

    async def analyze_ai_patterns(
        self, 
        property_id: str, 
        start_date: str = "30daysAgo", 
        end_date: str = "today"
    ) -> Dict[str, Any]:
        """
        Ejecuta el análisis completo de patrones de IA.
        """
        logger.info(f"Iniciando análisis de patrones IA para {property_id}")
        
        # 1. Obtener Benchmark de IA
        benchmark = await self._get_ai_benchmark(property_id, start_date, end_date)
        
        # 2. Obtener datos de comparación (Directo, Orgánico, Referido)
        comparison_data = await self._get_comparison_traffic(property_id, start_date, end_date)
        
        # 3. Realizar Matching
        matches = self._find_pattern_matches(benchmark, comparison_data)
        
        return {
            "benchmark": benchmark,
            "comparison_channels": comparison_data,
            "matches": matches,
            "metadata": {
                "property_id": property_id,
                "date_range": {"start": start_date, "end": end_date}
            }
        }

    async def _get_ai_benchmark(self, property_id: str, start_date: str, end_date: str) -> Dict[str, Any]:
        """Extrae KPIs de tráfico confirmado de fuentes de IA."""
        
        # Filtro para fuentes de IA
        ai_filter = FilterExpression(
            or_group=FilterExpressionList(
                expressions=[
                    FilterExpression(
                        filter=Filter(
                            field_name="sessionSource",
                            string_filter=Filter.StringFilter(
                                value=source,
                                match_type=Filter.StringFilter.MatchType.CONTAINS
                            )
                        )
                    ) for source in self.ai_sources
                ]
            )
        )

        metrics = [
            "sessions",
            "totalUsers",
            "conversions",
            "sessionConversionRate",
            "bounceRate",
            "screenPageViewsPerSession",
            "averagePurchaseRevenue",
            "activeUsers"
        ]

        # Intentar obtener datos
        try:
            # Usamos el GAService directamente o a través del cliente
            request = RunReportRequest(
                property=f"properties/{property_id.split('/')[-1]}",
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                metrics=[Metric(name=m) for m in metrics],
                dimension_filter=ai_filter
            )
            
            response = self.ga_service.client.run_report(request)
            
            if not response.rows:
                return self._get_empty_metrics()

            row = response.rows[0]
            data = {m: float(row.metric_values[i].value) for i, m in enumerate(metrics)}
            
            # Formatear KPIs según la imagen
            kpis = {
                "volumen": {
                    "sesiones": int(data["sessions"]),
                    "usuarios": int(data["totalUsers"])
                },
                "conversion": {
                    "cr": convert_ga4_rate_to_percentage(data["sessionConversionRate"]),
                    "conversions": int(data["conversions"])
                },
                "calidad": {
                    "bounce_rate": convert_ga4_rate_to_percentage(data["bounceRate"])
                },
                "engagement": {
                    "paginas_sesion": round(data["screenPageViewsPerSession"], 2)
                },
                "valor": {
                    "aov": round(data["averagePurchaseRevenue"], 2)
                }
            }
            
            # Nota: CPA, ROAS y Conversiones Asistidas a menudo requieren 
            # dimensiones/métricas adicionales o vinculaciones que pueden no estar presentes.
            # Se implementarán como N/A o estimaciones si es posible en fase 2.
            
            return kpis

        except Exception as e:
            logger.error(f"Error obteniendo benchmark IA: {e}")
            return self._get_empty_metrics()

    async def _get_comparison_traffic(self, property_id: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Obtiene KPIs de canales Directo, Orgánico y Referido para comparación."""
        
        channels = ["Direct", "Organic Search", "Referral"]
        results = []
        
        for channel in channels:
            channel_filter = FilterExpression(
                filter=Filter(
                    field_name="sessionDefaultChannelGroup",
                    string_filter=Filter.StringFilter(value=channel)
                )
            )
            
            metrics = [
                "sessions", "totalUsers", "conversions", 
                "sessionConversionRate", "bounceRate", 
                "screenPageViewsPerSession", "averagePurchaseRevenue"
            ]

            try:
                request = RunReportRequest(
                    property=f"properties/{property_id.split('/')[-1]}",
                    date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                    dimensions=[Dimension(name="landingPage")],
                    metrics=[Metric(name=m) for m in metrics],
                    dimension_filter=channel_filter,
                    limit=50 # Top 50 landing pages per channel
                )
                
                response = self.ga_service.client.run_report(request)
                
                for row in response.rows:
                    lp = row.dimension_values[0].value
                    data = {m: float(row.metric_values[i].value) for i, m in enumerate(metrics)}
                    
                    results.append({
                        "channel": channel,
                        "landing_page": lp,
                        "kpis": {
                            "volumen": {"sesiones": int(data["sessions"])},
                            "conversion": {"cr": convert_ga4_rate_to_percentage(data["sessionConversionRate"])},
                            "calidad": {"bounce_rate": convert_ga4_rate_to_percentage(data["bounceRate"])},
                            "engagement": {"paginas_sesion": round(data["screenPageViewsPerSession"], 2)},
                            "valor": {"aov": round(data["averagePurchaseRevenue"], 2)}
                        }
                    })
            except Exception as e:
                logger.error(f"Error comparando canal {channel}: {e}")
                
        return results

    def _find_pattern_matches(self, benchmark: Dict[str, Any], comparison_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Identifica segmentos que coinciden con el patrón del benchmark IA."""
        
        if benchmark["volumen"]["sesiones"] == 0:
            return []

        matches = []
        # Umbrales de similitud (flexibilidad de coincidencia)
        # Un match es exitoso si las métricas clave están dentro de un rango del benchmark
        
        for segment in comparison_data:
            score = 0
            # Solo comparamos si hay un volumen mínimo para que sea estadísticamente relevante
            if segment["kpis"]["volumen"]["sesiones"] < 5:
                continue
                
            # Pesos de los KPIs para el score de similitud
            # CR es muy importante (40%), Rebote (30%), Pags/Sesion (30%)
            
            # 1. Similitud de CR
            cr_diff = abs(segment["kpis"]["conversion"]["cr"] - benchmark["conversion"]["cr"])
            if cr_diff < 1.0: # Muy cerca (<1%)
                score += 40
            elif cr_diff < 5.0:
                score += 20
                
            # 2. Similitud de Bounce Rate
            br_diff = abs(segment["kpis"]["calidad"]["bounce_rate"] - benchmark["calidad"]["bounce_rate"])
            if br_diff < 5.0:
                score += 30
            elif br_diff < 15.0:
                score += 15
                
            # 3. Similitud de Engagament (Pags/Sesion)
            ps_diff = abs(segment["kpis"]["engagement"]["paginas_sesion"] - benchmark["engagement"]["paginas_sesion"])
            if ps_diff < 0.5:
                score += 30
            elif ps_diff < 1.5:
                score += 15
                
            if score >= 60: # Threshold de 60% para considerar "Lookalike"
                matches.append({
                    "channel": segment["channel"],
                    "landing_page": segment["landing_page"],
                    "similarity_score": score,
                    "kpis": segment["kpis"]
                })
                
        # Ordenar por score de similitud
        return sorted(matches, key=lambda x: x["similarity_score"], reverse=True)

    def _get_empty_metrics(self) -> Dict[str, Any]:
        """Retorna estructura de métricas vacía."""
        return {
            "volumen": {"sesiones": 0, "usuarios": 0},
            "conversion": {"cr": 0.0, "conversions": 0},
            "calidad": {"bounce_rate": 0.0},
            "engagement": {"paginas_sesion": 0.0},
            "valor": {"aov": 0.0}
        }
