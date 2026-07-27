"""Ejecutor de cambios de configuración basados en feedback.

Este módulo se encarga de aplicar cambios técnicos sencillos (mapeos, alias,
umbrales) que han sido validados por el FeedbackEvaluador como SIMPLE_EXECUTION.
"""

import json
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ConfigExecutor:
    def __init__(self, schema_path: str = "resources/ga4_schema.json"):
        self.schema_path = schema_path
        # Asegurar que el archivo de override existe en database si no queremos tocar resources
        self.db_schema_path = "database/ga4_schema_overrides.json"
        os.makedirs("database", exist_ok=True)

    def execute_action(self, action_str: str) -> bool:
        """
        Interpreta y ejecuta una acción técnica.
        Ejemplo: 'alias metric activeUsers to users'
        """
        if not action_str:
            return False
            
        action_str = action_str.lower()
        logger.info(f"⚙️ Intentando ejecutar acción técnica: {action_str}")
        logger.info("Auto-applying internal override (does not touch client platforms)...")
        
        try:
            # Caso 1: Alias de métricas/dimensiones
            # 'alias metric old_name to new_name'
            if action_str.startswith("alias"):
                parts = action_str.split(" ")
                if len(parts) >= 5 and parts[3] == "to":
                    target_type = parts[1] # metric/dimension
                    old_name = parts[2]
                    new_name = parts[4]
                    return self._apply_alias(target_type, old_name, new_name)
            
            # Caso 2: Cambiar umbrales (ej: 'set threshold risk to 0.8')
            if action_str.startswith("set threshold"):
                parts = action_str.split(" ")
                if len(parts) >= 5:
                    key = parts[2]
                    value = float(parts[4])
                    return self._apply_threshold(key, value)
                    
            logger.warning(f"Acción técnica no reconocida: {action_str}")
            return False
        except Exception as e:
            logger.error(f"Error ejecutando acción técnica: {e}")
            return False

    def _apply_alias(self, target_type: str, old_name: str, new_name: str) -> bool:
        """Guarda un alias en el archivo de overrides."""
        overrides = self._load_overrides()
        
        if "aliases" not in overrides:
            overrides["aliases"] = {}
        
        overrides["aliases"][new_name] = old_name
        
        self._save_overrides(overrides)
        logger.info(f"✅ Alias creado: {new_name} -> {old_name} ({target_type})")
        return True

    def _apply_threshold(self, key: str, value: float) -> bool:
        """Guarda un umbral en el archivo de overrides."""
        overrides = self._load_overrides()
        
        if "thresholds" not in overrides:
            overrides["thresholds"] = {}
        
        overrides["thresholds"][key] = value
        
        self._save_overrides(overrides)
        logger.info(f"✅ Umbral actualizado: {key} = {value}")
        return True

    def _load_overrides(self) -> Dict[str, Any]:
        if os.path.exists(self.db_schema_path):
            with open(self.db_schema_path, "r") as f:
                return json.load(f)
        return {}

    def _save_overrides(self, data: Dict[str, Any]):
        with open(self.db_schema_path, "w") as f:
            json.dump(data, f, indent=2)

# Singleton
config_executor = ConfigExecutor()
