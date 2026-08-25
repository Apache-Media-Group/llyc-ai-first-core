"""Servicio para inspeccionar datos raw de la API de GA4.

Captura las peticiones y respuestas enviadas a Google Analytics para permitir
la visualización y auditoría técnica de los datos.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from collections import deque

logger = logging.getLogger(__name__)

class DataInspectorService:
    def __init__(self, max_entries: int = 10):
        """
        Inicializa el inspector.
        
        Args:
            max_entries: Número máximo de peticiones recientes a mantener en memoria.
        """
        self.history = deque(maxlen=max_entries)

    def log_api_call(
        self, 
        endpoint: str, 
        request_body: Dict[str, Any], 
        response_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Registra una llamada a la API."""
        entry = {
            "endpoint": endpoint,
            "request": request_body,
            "response": response_data,
            "quality_metrics": self._extract_quality_metrics(response_data),
            "metadata": metadata or {}
        }
        self.history.appendleft(entry)
        logger.debug(f"API call logged in DataInspector: {endpoint}")

    def get_latest_calls(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retorna las llamadas más recientes."""
        return list(self.history)[:limit]

    def _extract_quality_metrics(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Extrae métricas de calidad de la respuesta (sampling, thresholding, etc)."""
        metrics = {
            "is_sampled": False,
            "is_subject_to_thresholding": False,
            "row_count": 0,
            "has_other_row": False,
            "sampling_percentage": 100.0
        }

        if not response:
            return metrics

        # GA4 Data API Metadata
        meta = response.get("metadata", {})
        
        # Check sampling
        sampling_metadatas = meta.get("samplingMetadatas", [])
        if sampling_metadatas:
            metrics["is_sampled"] = True
            # Intentar calcular porcentaje si está disponible
            try:
                samples = int(sampling_metadatas[0].get("samplesReadCount", 0))
                total = int(sampling_metadatas[0].get("samplingSpaceSize", 1))
                metrics["sampling_percentage"] = round((samples / total) * 100, 2)
            except:
                pass

        # Check thresholding
        metrics["is_subject_to_thresholding"] = meta.get("subjectToThresholding", False)

        # Row count
        metrics["row_count"] = response.get("rowCount", 0)

        # Check for (other) row in dimension values
        rows = response.get("rows", [])
        for row in rows:
            dim_values = row.get("dimensionValues", [])
            if any(dv.get("value") == "(other)" for dv in dim_values):
                metrics["has_other_row"] = True
                break

        return metrics

    def get_last_call(self) -> Optional[Dict[str, Any]]:
        """Retorna la última llamada realizada."""
        if self.history:
            return self.history[0]
        return None
