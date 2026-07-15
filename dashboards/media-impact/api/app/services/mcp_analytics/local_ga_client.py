"""Mock de BetaAnalyticsDataClient para manejar archivos locales (CSV/Excel) 
como si fueran una API de GA4, permitiendo que todos los servicios de análisis 
funcionen sin cambios significativos.
"""

import logging
from typing import List, Dict, Any, Optional
from types import SimpleNamespace
from .local_data_service import local_data_service

logger = logging.getLogger(__name__)

class LocalGAClient:
    """Mock del cliente de Google Analytics para datos locales."""
    
    def __init__(self, filename: Optional[str] = None):
        self.filename = filename

    def run_report(self, request) -> SimpleNamespace:
        """
        Interpreta un RunReportRequest de Google Cloud y lo ejecuta sobre el CSV local.
        """
        try:
            # Extraer dimensiones y métricas del objeto request (que puede ser dict o objeto)
            if hasattr(request, 'dimensions'):
                dimensions = [d.name for d in request.dimensions]
                metrics = [m.name for m in request.metrics]
                limit = getattr(request, 'limit', 100)
            else:
                dimensions = request.get('dimensions', [])
                metrics = request.get('metrics', [])
                limit = request.get('limit', 100)

            logger.info(f"LocalGAClient: Ejecutando reporte local sobre {self.filename or 'default'}")
            
            result = local_data_service.run_report(
                dimensions=dimensions,
                metrics=metrics,
                limit=limit,
                filename=self.filename
            )

            # Empaquetar en una estructura compatible con BetaAnalyticsDataClient response
            rows = []
            for r in result["rows"]:
                dim_vals = [SimpleNamespace(value=str(r.get(d, ""))) for d in dimensions]
                met_vals = [SimpleNamespace(value=str(r.get(m, "0"))) for m in metrics]
                rows.append(SimpleNamespace(dimension_values=dim_vals, metric_values=met_vals))

            dim_headers = [SimpleNamespace(name=d) for d in dimensions]
            met_headers = [SimpleNamespace(name=m) for m in metrics]

            return SimpleNamespace(
                rows=rows,
                row_count=result["row_count"],
                dimension_headers=dim_headers,
                metric_headers=met_headers,
                metadata=SimpleNamespace(
                    sampling_metadatas=[],
                    subject_to_thresholding=False
                )
            )

        except Exception as e:
            logger.error(f"Error en LocalGAClient: {str(e)}")
            raise e

    def get_metadata(self, request):
        """Mock de metadata para archivos locales."""
        return SimpleNamespace(
            name="properties/local/metadata",
            dimensions=[SimpleNamespace(api_name=d, ui_name=d) for d in local_data_service.dimensions],
            metrics=[SimpleNamespace(api_name=m, ui_name=m) for m in local_data_service.metrics]
        )
