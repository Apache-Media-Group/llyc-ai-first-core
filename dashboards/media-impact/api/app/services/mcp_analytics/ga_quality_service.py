"""
GA4 Quality Service
Rol: Data Quality Engineer

Responsabilidades:
- Auditar respuestas de la API de Datos
- Detectar muestreo (sampling)
- Identificar alta cardinalidad ((other))
- Detectar datos faltantes ((not set))
- Identificar retrasos de atribución ((data not available))
- Generar reportes de calidad con puntuaciones
"""

import logging
from typing import Dict, Any, List, Optional
from .calculation_service import CalculationService
from google.analytics.data_v1beta.types import RunReportResponse

logger = logging.getLogger(__name__)

class GA4QualityService:
    """Servicio de auditoría de calidad de datos GA4."""
    
    def __init__(self):
        """Inicializa el servicio de calidad."""
        pass
    
    def audit_response(self, response: RunReportResponse) -> Dict[str, Any]:
        """
        Audita una respuesta de la API de Datos GA4.
        
        Args:
            response: Respuesta de RunReportRequest
            
        Returns:
            Dict con issues, warnings y quality_score
        """
        issues = []
        warnings = []
        
        # 1. Check Sampling
        sampling_check = self._check_sampling(response)
        if sampling_check:
            issues.append(sampling_check)
        
        # 2. Check High Cardinality (other row)
        cardinality_check = self._check_high_cardinality(response)
        if cardinality_check:
            warnings.append(cardinality_check)
        
        # 3. Check Missing Data (not set)
        missing_data_check = self._check_missing_data(response)
        if missing_data_check:
            warnings.append(missing_data_check)
        
        # 4. Check Attribution Delays (data not available)
        attribution_check = self._check_attribution_delays(response)
        if attribution_check:
            warnings.append(attribution_check)
        
        # 5. Check Row Count
        row_count_check = self._check_row_count(response)
        if row_count_check:
            warnings.append(row_count_check)
        
        # Calcular quality score
        quality_score = self._calculate_quality_score(issues, warnings)
        
        return {
            "issues": issues,
            "warnings": warnings,
            "quality_score": quality_score,
            "has_critical_issues": len(issues) > 0,
            "total_rows": response.row_count if hasattr(response, 'row_count') else len(response.rows)
        }
    
    def _check_sampling(self, response: RunReportResponse) -> Optional[Dict[str, Any]]:
        """
        Verifica si los datos están muestreados.
        
        Returns:
            Dict con el issue o None si no hay muestreo
        """
        try:
            if hasattr(response, 'metadata') and hasattr(response.metadata, 'sampling_metadata'):
                sampling_meta = response.metadata.sampling_metadata
                if sampling_meta and sampling_meta.samples_read_count and sampling_meta.sampling_space_size:
                    sample_percentage = CalculationService.calculate_percentage(
                        sampling_meta.samples_read_count, 
                        sampling_meta.sampling_space_size,
                        decimals=1
                    )
                    
                    if sample_percentage < 100:
                        return {
                            "type": "sampling",
                            "severity": "critical" if sample_percentage < 80 else "warning",
                            "message": f"⚠️ DATOS MUESTREADOS: Este reporte está basado en {sample_percentage}% de los datos",
                            "details": {
                                "samples_read": sampling_meta.samples_read_count,
                                "total_samples": sampling_meta.sampling_space_size,
                                "percentage": sample_percentage
                            },
                            "recommendation": "Para datos 100% precisos, reduce el rango de fechas o usa la exportación a BigQuery"
                        }
        except Exception as e:
            logger.debug(f"Error checking sampling: {e}")
        
        return None
    
    def _check_high_cardinality(self, response: RunReportResponse) -> Optional[Dict[str, Any]]:
        """
        Detecta la presencia de la fila (other) que indica alta cardinalidad.
        
        Returns:
            Dict con el warning o None
        """
        try:
            for row in response.rows:
                for dim_value in row.dimension_values:
                    if dim_value.value == "(other)":
                        return {
                            "type": "high_cardinality",
                            "severity": "warning",
                            "message": "⚠️ ALTA CARDINALIDAD: Muchos valores agregados en la fila '(other)'",
                            "recommendation": "Los datos están agregados. Para ver todos los valores individuales, usa BigQuery o aplica filtros más específicos"
                        }
        except Exception as e:
            logger.debug(f"Error checking cardinality: {e}")
        
        return None
    
    def _check_missing_data(self, response: RunReportResponse) -> Optional[Dict[str, Any]]:
        """
        Detecta valores (not set) que indican datos faltantes.
        
        Returns:
            Dict con el warning o None
        """
        not_set_count = 0
        
        try:
            for row in response.rows:
                for dim_value in row.dimension_values:
                    if dim_value.value in ["(not set)", "(none)", ""]:
                        not_set_count += 1
            
            if not_set_count > 0:
                total_rows = len(response.rows)
                percentage = (not_set_count / total_rows) * 100 if total_rows > 0 else 0
                
                severity = "critical" if percentage > 20 else "warning"
                
                return {
                    "type": "missing_data",
                    "severity": severity,
                    "message": f"⚠️ DATOS FALTANTES: {not_set_count} filas con valores '(not set)' ({percentage:.1f}%)",
                    "details": {
                        "not_set_rows": not_set_count,
                        "total_rows": total_rows,
                        "percentage": percentage
                    },
                    "recommendation": "Verifica la configuración de etiquetas/GTM. Los datos faltantes pueden indicar problemas de tracking o configuraciones de privacidad"
                }
        except Exception as e:
            logger.debug(f"Error checking missing data: {e}")
        
        return None
    
    def _check_attribution_delays(self, response: RunReportResponse) -> Optional[Dict[str, Any]]:
        """
        Detecta (data not available) que indica atribución en proceso.
        
        Returns:
            Dict con el warning o None
        """
        try:
            for row in response.rows:
                for dim_value in row.dimension_values:
                    if "(data not available)" in dim_value.value.lower():
                        return {
                            "type": "attribution_delay",
                            "severity": "info",
                            "message": "ℹ️ ATRIBUCIÓN EN PROCESO: Algunos datos muestran '(data not available)'",
                            "recommendation": "La atribución completa puede tardar hasta 12 días. Los datos recientes pueden estar incompletos"
                        }
        except Exception as e:
            logger.debug(f"Error checking attribution delays: {e}")
        
        return None
    
    def _check_row_count(self, response: RunReportResponse) -> Optional[Dict[str, Any]]:
        """
        Verifica si se alcanzó el límite de filas (100,000).
        
        Returns:
            Dict con el warning o None
        """
        try:
            row_count = len(response.rows)
            
            # GA4 Data API tiene un límite de 100,000 filas por request
            if row_count >= 100000:
                return {
                    "type": "row_limit",
                    "severity": "warning",
                    "message": "⚠️ LÍMITE DE FILAS: Se alcanzó el máximo de 100,000 filas",
                    "details": {
                        "rows_returned": row_count,
                        "limit": 100000
                    },
                    "recommendation": "Pueden existir más datos. Usa paginación (offset) o BigQuery para datasets grandes"
                }
        except Exception as e:
            logger.debug(f"Error checking row count: {e}")
        
        return None
    
    def _calculate_quality_score(self, issues: List[Dict], warnings: List[Dict]) -> int:
        """
        Calcula un score de calidad de 0-100.
        
        Score base: 100
        - Critical issue: -30 puntos
        - Warning: -10 puntos
        - Info: -5 puntos
        
        Returns:
            Score de 0 a 100
        """
        score = 100
        
        for issue in issues:
            severity = issue.get("severity", "warning")
            if severity == "critical":
                score -= 30
            elif severity == "warning":
                score -= 15
        
        for warning in warnings:
            severity = warning.get("severity", "info")
            if severity == "critical":
                score -= 20
            elif severity == "warning":
                score -= 10
            elif severity == "info":
                score -= 5
        
        return max(0, min(100, score))
    
    def audit_multiple_responses(
        self,
        responses: Dict[str, RunReportResponse]
    ) -> Dict[str, Any]:
        """
        Audita múltiples respuestas (para Deep Dive).
        
        Args:
            responses: Dict con nombre_seccion: response
            
        Returns:
            Dict con auditoría agregada
        """
        all_issues = []
        all_warnings = []
        section_scores = {}
        
        for section_name, response in responses.items():
            if response and hasattr(response, 'rows'):
                audit = self.audit_response(response)
                section_scores[section_name] = audit["quality_score"]
                
                # Agregar issues con contexto de sección
                for issue in audit["issues"]:
                    all_issues.append({
                        **issue,
                        "section": section_name
                    })
                
                for warning in audit["warnings"]:
                    all_warnings.append({
                        **warning,
                        "section": section_name
                    })
        
        # Calcular score promedio
        average_score = sum(section_scores.values()) / len(section_scores) if section_scores else 100
        
        # Agrupar por tipo
        issues_by_type = {}
        for issue in all_issues + all_warnings:
            issue_type = issue.get("type", "unknown")
            if issue_type not in issues_by_type:
                issues_by_type[issue_type] = []
            issues_by_type[issue_type].append(issue)
        
        return {
            "overall_quality_score": round(average_score, 1),
            "section_scores": section_scores,
            "total_issues": len(all_issues),
            "total_warnings": len(all_warnings),
            "issues_by_type": issues_by_type,
            "recommendations": self._generate_global_recommendations(issues_by_type),
            "quality_grade": self._get_quality_grade(average_score)
        }
    
    def _generate_global_recommendations(self, issues_by_type: Dict) -> List[str]:
        """Genera recomendaciones globales basadas en los issues detectados."""
        recommendations = []
        
        if "sampling" in issues_by_type:
            recommendations.append(
                "📊 Múltiples reportes con muestreo detectados. "
                "Considera exportar a BigQuery para análisis sin muestreo"
            )
        
        if "high_cardinality" in issues_by_type:
            recommendations.append(
                "🔍 Alta cardinalidad detectada en varios reportes. "
                "BigQuery te dará acceso a todos los datos sin límite de filas"
            )
        
        if "missing_data" in issues_by_type:
            affected_sections = len(issues_by_type["missing_data"])
            recommendations.append(
                f"⚠️ Datos faltantes detectados en {affected_sections} secciones. "
                "Revisa la configuración de GTM y etiquetas"
            )
        
        if "attribution_delay" in issues_by_type:
            recommendations.append(
                "⏱️ Algunos datos aún están en proceso de atribución. "
                "Espera 7-12 días para datos completos de conversiones"
            )
        
        return recommendations
    
    def _get_quality_grade(self, score: float) -> str:
        """Convierte el score numérico en una calificación."""
        if score >= 90:
            return "Excelente ✅"
        elif score >= 75:
            return "Bueno ✔️"
        elif score >= 60:
            return "Aceptable ⚠️"
        elif score >= 40:
            return "Deficiente ⚠️⚠️"
        else:
            return "Crítico ❌"
