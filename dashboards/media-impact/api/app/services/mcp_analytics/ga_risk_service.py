"""
GA4 Risk Auditor Service
Rol: Quantitative Marketing Analyst
Enfoque: Auditoría de volatilidad, riesgo y varianza en campañas.
"""

import logging
import math
import numpy as np
import pandas as pd
from scipy import stats
from typing import List, Dict, Any, Optional
from datetime import datetime
from google.oauth2.credentials import Credentials
from .calculation_service import CalculationService
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
    FilterExpression,
    Filter
)

logger = logging.getLogger(__name__)

def _sanitize_for_json(obj: Any) -> Any:
    """Sanitiza valores para JSON: convierte NaN/Inf a 0."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(x) for x in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    elif isinstance(obj, (np.float64, np.float32, np.floating)):
        if np.isnan(obj) or np.isinf(obj):
            return 0.0
        return float(obj)
    elif isinstance(obj, (np.int64, np.int32, np.integer)):
        return int(obj)
    return obj

class GA4RiskService:
    def __init__(self, credentials: Optional[Credentials] = None, client: Optional[Any] = None):
        if client:
            self.client = client
        elif credentials:
            self.client = BetaAnalyticsDataClient(credentials=credentials)
        else:
            self.client = BetaAnalyticsDataClient()

    async def analyze_risk(self, property_id: str, date_range: Dict[str, str], break_even_roas: float) -> Dict[str, Any]:
        """Wrapper to match the unified interface."""
        return await self.run_risk_analysis(
            property_id,
            start_date=date_range.get("start_date", "30daysAgo"),
            end_date=date_range.get("end_date", "today"),
            break_even_roas=break_even_roas
        )

    async def run_risk_analysis(
        self,
        property_id: str,
        start_date: str = "30daysAgo",
        end_date: str = "today",
        break_even_roas: float = 3.0
    ) -> Dict[str, Any]:
        """
        Ejecuta un análisis de riesgo y varianza para las campañas.
        """
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"

        # 1. Obtener datos diarios por campaña
        # Usamos sessionSource/sessionMedium como proxy de "Campaña" si el nombre no está claro
        request = RunReportRequest(
            property=property_id,
            dimensions=[
                Dimension(name="date"),
                Dimension(name="sessionSource"),
                Dimension(name="sessionMedium"),
                Dimension(name="sessionCampaignName")
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="conversions"),
                Metric(name="totalRevenue"),
                # Metric(name="advertiserAdCost") # Solo si hay Google Ads vinculado
            ],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            limit=10000
        )

        try:
            response = self.client.run_report(request)
            data = self._parse_to_dataframe(response)
        except Exception as e:
            # Reintentar sin advertiserAdCost si falla (por si no está disponible)
            logger.warning(f"Risk analysis data fetch failed: {e}. Retrying without AdCost.")
            response = self.client.run_report(request)
            data = self._parse_to_dataframe(response)

        if data.empty:
            return {"error": "No data found for risk analysis"}

        # 2. Ingeniería de Características
        # Combinar Source/Medium/Campaign en una etiqueta única
        data['CampaignLabel'] = data['sessionSource'] + " / " + data['sessionMedium'] + " (" + data['sessionCampaignName'] + ")"
        
        # Calcular KPI de rendimiento (ROAS proxy o CVR) usando precisión Decimal
        if 'advertiserAdCost' in data.columns and data['advertiserAdCost'].sum() > 0:
            data['Performance'] = data.apply(lambda row: CalculationService.calculate_ratio(row['totalRevenue'], row['advertiserAdCost']), axis=1)
            kpi_name = "ROAS"
        else:
            data['Performance'] = data.apply(lambda row: CalculationService.calculate_percentage(row['conversions'], row['sessions']), axis=1)
            kpi_name = "CVR (Conv/100 Sessions)"
            # Ajustar break_even si es CVR (ej: 2% suele ser bueno)
            if break_even_roas == 3.0: 
                break_even_roas = 2.0 

        # 3. Análisis Estadístico por Campaña
        campaign_stats = []
        unique_campaigns = data['CampaignLabel'].unique()
        
        # Filtrar solo campañas con suficiente volumen (ej: > 5 días de datos)
        min_days = 5
        
        visualization_data = {
            "campaigns": [],
            "distributions": {}, # Para Violin Plots
            "boxplot_data": []
        }

        for campaign in unique_campaigns:
            c_data = data[data['CampaignLabel'] == campaign].copy()
            c_data = c_data.dropna(subset=['Performance'])
            
            if len(c_data) < min_days:
                continue

            perf_series = c_data['Performance']
            
            stats_dict = {
                "name": campaign,
                "mean": float(perf_series.mean()),
                "median": float(perf_series.median()),
                "std_dev": float(perf_series.std()),
                "variance": float(perf_series.var()),
                "skewness": float(stats.skew(perf_series)),
                "kurtosis": float(stats.kurtosis(perf_series)),
                "prob_success": CalculationService.calculate_percentage((perf_series > break_even_roas).sum(), len(perf_series)),
                "var_5": float(perf_series.quantile(0.05)),
                "sample_size": len(perf_series)
            }
            
            # Diagnóstico
            if stats_dict['std_dev'] < (stats_dict['mean'] * 0.2):
                stats_dict['diagnosis'] = "ESTABLE (Escalar)"
                stats_dict['status'] = "success"
            elif stats_dict['prob_success'] < 40:
                stats_dict['diagnosis'] = "RIESGO ALTO (Optimizar)"
                stats_dict['status'] = "warning"
            elif stats_dict['mean'] < break_even_roas and stats_dict['prob_success'] > 10:
                stats_dict['diagnosis'] = "CORTAR / AUDITAR"
                stats_dict['status'] = "error"
            else:
                stats_dict['diagnosis'] = "VOLÁTIL"
                stats_dict['status'] = "info"

            campaign_stats.append(stats_dict)
            
            # Datos para visualización
            visualization_data["campaigns"].append(campaign)
            visualization_data["distributions"][campaign] = perf_series.tolist()
            visualization_data["boxplot_data"].append({
                "x": campaign,
                "y": [
                    float(perf_series.min()),
                    float(perf_series.quantile(0.25)),
                    float(perf_series.median()),
                    float(perf_series.quantile(0.75)),
                    float(perf_series.max())
                ]
            })

        return _sanitize_for_json({
            "property_id": property_id,
            "date_range": {"start_date": start_date, "end_date": end_date},
            "kpi_analyzed": kpi_name,
            "break_even_threshold": break_even_roas,
            "campaign_audit": sorted(campaign_stats, key=lambda x: x['mean'], reverse=True),
            "visualization": visualization_data
        })

    def _parse_to_dataframe(self, response) -> pd.DataFrame:
        """Parsea RunReportResponse a Pandas DataFrame."""
        dimension_headers = [h.name for h in response.dimension_headers]
        metric_headers = [h.name for h in response.metric_headers]
        
        rows = []
        for row in response.rows:
            row_data = {}
            for i, dim_value in enumerate(row.dimension_values):
                row_data[dimension_headers[i]] = dim_value.value
            for i, met_value in enumerate(row.metric_values):
                row_data[metric_headers[i]] = float(met_value.value)
            rows.append(row_data)
        
        return pd.DataFrame(rows)
