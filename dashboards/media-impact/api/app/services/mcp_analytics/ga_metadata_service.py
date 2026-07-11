"""
GA4 Metadata Service
Rol: Data Architect Senior

Responsabilidades:
- Validar compatibilidad de scopes entre dimensiones y métricas
- Detectar riesgo de alta cardinalidad
- Sugerir combinaciones óptimas
- Cargar y gestionar esquema GA4
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

logger = logging.getLogger(__name__)

class GA4MetadataService:
    """Servicio de metadatos y validación de esquemas GA4."""
    
    def __init__(self):
        """Inicializa el servicio cargando el esquema GA4."""
        self.schema = self._load_schema()
        self.scopes = self.schema.get("scopes", {})
        self.cardinality_warnings = self.schema.get("cardinality_warnings", {})
        self.common_patterns = self.schema.get("common_patterns", {})
        
    def _load_schema(self) -> Dict[str, Any]:
        """Carga el esquema GA4 desde el archivo JSON."""
        schema_path = Path(__file__).parent.parent / "resources" / "ga4_schema.json"
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading GA4 schema: {e}")
            return {}
    
    def get_dimension_scope(self, dimension: str) -> Optional[str]:
        """
        Determina el scope de una dimensión.
        
        Args:
            dimension: Nombre de la dimensión
            
        Returns:
            Scope ('user', 'session', 'event', 'item') o None si no se encuentra
        """
        for scope_name, scope_data in self.scopes.items():
            if dimension in scope_data.get("dimensions", []):
                return scope_name
        return None
    
    def get_metric_scope(self, metric: str) -> Optional[str]:
        """
        Determina el scope de una métrica.
        
        Args:
            metric: Nombre de la métrica
            
        Returns:
            Scope ('user', 'session', 'event', 'item') o None si no se encuentra
        """
        for scope_name, scope_data in self.scopes.items():
            if metric in scope_data.get("metrics", []):
                return scope_name
        return None
    
    def validate_dimensions_metrics(
        self,
        dimensions: List[str],
        metrics: List[str]
    ) -> Dict[str, Any]:
        """
        Valida compatibilidad de scopes entre dimensiones y métricas.
        
        Args:
            dimensions: Lista de dimensiones
            metrics: Lista de métricas
            
        Returns:
            Dict con:
            - valid: bool
            - scope: str (scope detectado)
            - issues: List[str] (problemas encontrados)
            - suggestions: List[str] (sugerencias de corrección)
        """
        issues = []
        suggestions = []
        
        # Detectar scopes de dimensiones
        dim_scopes = set()
        for dim in dimensions:
            scope = self.get_dimension_scope(dim)
            if scope:
                dim_scopes.add(scope)
            else:
                issues.append(f"Dimensión desconocida: {dim}")
        
        # Detectar scopes de métricas
        metric_scopes = set()
        for metric in metrics:
            scope = self.get_metric_scope(metric)
            if scope:
                metric_scopes.add(scope)
            else:
                issues.append(f"Métrica desconocida: {metric}")
        
        # Validar compatibilidad
        all_scopes = dim_scopes | metric_scopes
        
        # Regla 1: No mezclar user y session scopes
        if "user" in all_scopes and "session" in all_scopes:
            issues.append("⚠️ INCOMPATIBILIDAD: No puedes mezclar scopes 'user' y 'session'")
            
            # Sugerir corrección
            if "user" in dim_scopes and "session" in metric_scopes:
                suggestions.append(
                    "Si quieres analizar adquisición de usuarios, usa dimensiones firstUser* con métricas de usuario (newUsers, totalUsers)"
                )
            elif "session" in dim_scopes and "user" in metric_scopes:
                suggestions.append(
                    "Si quieres analizar sesiones, usa dimensiones session* con métricas de sesión (sessions, engagementRate)"
                )
        
        # Regla 2: Item scope debe ir con event scope o solo
        if "item" in all_scopes and len(all_scopes) > 2:
            issues.append("⚠️ El scope 'item' solo debe combinarse con 'event' o usarse solo")
        
        # Determinar scope principal
        primary_scope = None
        if len(all_scopes) == 1:
            primary_scope = list(all_scopes)[0]
        elif len(all_scopes) == 2 and "event" in all_scopes:
            # Event puede combinarse con otros
            primary_scope = list(all_scopes - {"event"})[0]
        
        is_valid = len(issues) == 0
        
        return {
            "valid": is_valid,
            "scope": primary_scope or "mixed",
            "detected_scopes": list(all_scopes),
            "issues": issues,
            "suggestions": suggestions,
            "message": "✅ Combinación válida" if is_valid else "❌ Combinación inválida"
        }
    
    def check_cardinality_risk(self, dimensions: List[str]) -> Dict[str, Any]:
        """
        Analiza el riesgo de alta cardinalidad en las dimensiones.
        
        Args:
            dimensions: Lista de dimensiones
            
        Returns:
            Dict con nivel de riesgo y recomendaciones
        """
        risk_levels = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": []
        }
        
        for dim in dimensions:
            for level, level_data in self.cardinality_warnings.items():
                if dim in level_data.get("dimensions", []):
                    risk_levels[level].append({
                        "dimension": dim,
                        "description": level_data.get("description", "")
                    })
        
        # Calcular riesgo general
        overall_risk = "low"
        if risk_levels["critical"]:
            overall_risk = "critical"
        elif risk_levels["high"]:
            overall_risk = "high"
        elif risk_levels["medium"]:
            overall_risk = "medium"
        
        recommendations = []
        
        if overall_risk in ["critical", "high"]:
            recommendations.append(
                "⚠️ ALTA CARDINALIDAD: Esta consulta probablemente generará una fila (other) que agrupa muchos valores"
            )
            recommendations.append(
                "💡 RECOMENDACIÓN: Considera usar la exportación a BigQuery para análisis granular sin límites de filas"
            )
            recommendations.append(
                "💡 ALTERNATIVA: Reduce el rango de fechas o usa filtros más específicos"
            )
        
        return {
            "overall_risk": overall_risk,
            "risk_details": risk_levels,
            "recommendations": recommendations,
            "has_critical_risk": len(risk_levels["critical"]) > 0
        }
    
    def get_compatible_metrics(self, dimensions: List[str]) -> List[str]:
        """
        Sugiere métricas compatibles basadas en las dimensiones.
        
        Args:
            dimensions: Lista de dimensiones
            
        Returns:
            Lista de métricas compatibles
        """
        if not dimensions:
            return []
        
        # Detectar scope predominante
        dim_scopes = set()
        for dim in dimensions:
            scope = self.get_dimension_scope(dim)
            if scope:
                dim_scopes.add(scope)
        
        # Si hay conflicto user/session, retornar vacío
        if "user" in dim_scopes and "session" in dim_scopes:
            return []
        
        # Determinar scope principal
        primary_scope = None
        if "user" in dim_scopes:
            primary_scope = "user"
        elif "session" in dim_scopes:
            primary_scope = "session"
        elif "item" in dim_scopes:
            primary_scope = "item"
        else:
            primary_scope = "event"
        
        # Retornar métricas del scope principal + event (siempre compatible)
        compatible = []
        if primary_scope in self.scopes:
            compatible.extend(self.scopes[primary_scope].get("metrics", []))
        
        # Agregar métricas de event si no es el scope principal
        if primary_scope != "event" and "event" in self.scopes:
            compatible.extend(self.scopes["event"].get("metrics", []))
        
        return list(set(compatible))
    
    def get_common_pattern(self, pattern_name: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene un patrón común predefinido.
        
        Args:
            pattern_name: Nombre del patrón (ej: 'user_acquisition', 'ecommerce_overview')
            
        Returns:
            Dict con dimensiones y métricas del patrón o None
        """
        return self.common_patterns.get(pattern_name)
    
    def list_common_patterns(self) -> List[str]:
        """Lista todos los patrones comunes disponibles."""
        return list(self.common_patterns.keys())
    
    def suggest_optimization(
        self,
        dimensions: List[str],
        metrics: List[str]
    ) -> Dict[str, Any]:
        """
        Analiza la consulta y sugiere optimizaciones.
        
        Args:
            dimensions: Lista de dimensiones
            metrics: Lista de métricas
            
        Returns:
            Dict con validación, cardinalidad y sugerencias
        """
        validation = self.validate_dimensions_metrics(dimensions, metrics)
        cardinality = self.check_cardinality_risk(dimensions)
        
        all_suggestions = []
        
        # Agregar sugerencias de validación
        all_suggestions.extend(validation.get("suggestions", []))
        
        # Agregar sugerencias de cardinalidad
        all_suggestions.extend(cardinality.get("recommendations", []))
        
        # Sugerir patrón común si aplica
        for pattern_name, pattern_data in self.common_patterns.items():
            pattern_dims = set(pattern_data.get("dimensions", []))
            pattern_mets = set(pattern_data.get("metrics", []))
            query_dims = set(dimensions)
            query_mets = set(metrics)
            
            # Si coincide en más del 60%, sugerir el patrón completo
            dim_overlap = len(pattern_dims & query_dims) / len(pattern_dims) if pattern_dims else 0
            met_overlap = len(pattern_mets & query_mets) / len(pattern_mets) if pattern_mets else 0
            
            if dim_overlap > 0.6 or met_overlap > 0.6:
                all_suggestions.append(
                    f"💡 Patrón sugerido: '{pattern_name}' - {pattern_data.get('description', '')}"
                )
        
        return {
            "validation": validation,
            "cardinality": cardinality,
            "suggestions": all_suggestions,
            "is_optimal": validation["valid"] and cardinality["overall_risk"] in ["low", "medium"]
        }
