"""Base de Conocimiento - Persistencia de Reglas Aprendidas.

Sistema de almacenamiento para reglas que el sistema ha aprendido del feedback.
Utiliza JSON en local durante desarrollo y Google Cloud Storage en producción.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class LearnedRule:
    """Representa una regla aprendida por el sistema."""
    
    def __init__(
        self,
        rule_id: str,
        description: str,
        verdict: str,
        confidence: float,
        original_feedback: str,
        reasoning: str,
        created_at: str,
        status: str = "ACTIVE"
    ):
        """
        Args:
            rule_id: ID único de la regla (UUID o timestamp)
            description: Descripción clara de qué hace la regla
            verdict: ACCEPTED, REJECTED, PREFERENCE
            confidence: Confianza del Judge (0-1)
            original_feedback: El feedback que generó la regla
            reasoning: Explicación del Judge
            created_at: ISO timestamp de cuándo se creó
            status: ACTIVE, INACTIVE, ARCHIVED
        """
        self.rule_id = rule_id
        self.description = description
        self.verdict = verdict
        self.confidence = confidence
        self.original_feedback = original_feedback
        self.reasoning = reasoning
        self.created_at = created_at
        self.status = status
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para persistencia."""
        return {
            "rule_id": self.rule_id,
            "description": self.description,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "original_feedback": self.original_feedback,
            "reasoning": self.reasoning,
            "created_at": self.created_at,
            "status": self.status,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearnedRule":
        """Crea una instancia desde diccionario."""
        return cls(**data)


class KnowledgeBaseService:
    """
    Servicio de persistencia para reglas aprendidas.
    
    Durante desarrollo: Almacena en database/learned_rules.json
    En producción: Debería usar Google Cloud Storage (implementable)
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        Args:
            storage_path: Path a carpeta database/ (por defecto detecta)
        """
        if storage_path is None:
            # Detectar la carpeta database/ automáticamente
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent
            storage_path = str(project_root / "database")
        
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.rules_file = self.storage_path / "learned_rules.json"
        self.feedback_file = self.storage_path / "user_feedback.json"
        
        # Crear archivo de reglas si no existe
        if not self.rules_file.exists():
            self._initialize_storage()
        
        # Crear archivo de feedback si no existe
        if not self.feedback_file.exists():
            self._initialize_feedback_storage()
        
        logger.info(f"KnowledgeBaseService inicializado en {self.storage_path}")
    
    def _initialize_storage(self):
        """Crea el archivo de almacenamiento inicial."""
        initial_data = {
            "version": "1.0",
            "created_at": datetime.utcnow().isoformat(),
            "rules": []
        }
        with open(self.rules_file, 'w') as f:
            json.dump(initial_data, f, indent=2)
    
    def _initialize_feedback_storage(self):
        """Crea el archivo de feedback inicial."""
        with open(self.feedback_file, 'w') as f:
            json.dump([], f, indent=2)
    
    def load_rules(self) -> List[LearnedRule]:
        """Carga todas las reglas activas desde almacenamiento."""
        try:
            with open(self.rules_file, 'r') as f:
                data = json.load(f)
            
            rules = []
            for rule_data in data.get("rules", []):
                if rule_data.get("status") == "ACTIVE":
                    rules.append(LearnedRule.from_dict(rule_data))
            
            logger.debug(f"Cargadas {len(rules)} reglas activas")
            return rules
        
        except Exception as e:
            logger.error(f"Error cargando reglas: {e}")
            return []
    
    def save_feedback(self, feedback_data: Dict[str, Any]) -> bool:
        """
        Guarda feedback crudo del usuario sin evaluar (para análisis futuro).
        
        Args:
            feedback_data: Dict con feedback_id, rating, user_feedback, context, etc.
        
        Returns:
            True si fue exitoso
        """
        try:
            current_feedback = []
            if self.feedback_file.exists():
                with open(self.feedback_file, 'r', encoding='utf-8') as f:
                    current_feedback = json.load(f)
            
            current_feedback.append(feedback_data)
            
            with open(self.feedback_file, 'w', encoding='utf-8') as f:
                json.dump(current_feedback, f, indent=2, ensure_ascii=False)
            
            logger.info(f"✅ Feedback guardado: {feedback_data.get('feedback_id')}")
            return True
        except Exception as e:
            logger.error(f"❌ Error guardando feedback: {e}")
            return False
    
    def save_rule(self, rule: LearnedRule) -> bool:
        """
        Guarda una nueva regla aprendida.
        
        Args:
            rule: LearnedRule a guardar
        
        Returns:
            True si fue exitoso
        """
        try:
            with open(self.rules_file, 'r') as f:
                data = json.load(f)
            
            # Verificar si la regla ya existe
            existing_ids = [r["rule_id"] for r in data["rules"]]
            if rule.rule_id in existing_ids:
                logger.warning(f"Regla {rule.rule_id} ya existe, actualizando...")
                data["rules"] = [r for r in data["rules"] if r["rule_id"] != rule.rule_id]
            
            # Agregar nueva regla
            data["rules"].append(rule.to_dict())
            
            # Guardar
            with open(self.rules_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"Regla {rule.rule_id} guardada exitosamente")
            return True
        
        except Exception as e:
            logger.error(f"Error guardando regla: {e}")
            return False
    
    def get_rule_by_id(self, rule_id: str) -> Optional[LearnedRule]:
        """Obtiene una regla específica por ID."""
        try:
            with open(self.rules_file, 'r') as f:
                data = json.load(f)
            
            for rule_data in data.get("rules", []):
                if rule_data.get("rule_id") == rule_id:
                    return LearnedRule.from_dict(rule_data)
            
            return None
        
        except Exception as e:
            logger.error(f"Error obteniendo regla {rule_id}: {e}")
            return None
    
    def deactivate_rule(self, rule_id: str) -> bool:
        """Desactiva una regla (soft delete)."""
        try:
            with open(self.rules_file, 'r') as f:
                data = json.load(f)
            
            found = False
            for rule in data["rules"]:
                if rule.get("rule_id") == rule_id:
                    rule["status"] = "INACTIVE"
                    found = True
                    break
            
            if found:
                with open(self.rules_file, 'w') as f:
                    json.dump(data, f, indent=2)
                logger.info(f"Regla {rule_id} desactivada")
                return True
            
            return False
        
        except Exception as e:
            logger.error(f"Error desactivando regla: {e}")
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """Obtiene estadísticas de las reglas aprendidas."""
        try:
            with open(self.rules_file, 'r') as f:
                data = json.load(f)
            
            rules = data.get("rules", [])
            active_rules = [r for r in rules if r.get("status") == "ACTIVE"]
            
            verdicts = {}
            total_confidence = 0.0
            
            for rule in active_rules:
                verdict = rule.get("verdict", "UNKNOWN")
                verdicts[verdict] = verdicts.get(verdict, 0) + 1
                total_confidence += rule.get("confidence", 0.0)
            
            avg_confidence = total_confidence / len(active_rules) if active_rules else 0.0
            
            return {
                "total_rules": len(rules),
                "active_rules": len(active_rules),
                "by_verdict": verdicts,
                "average_confidence": round(avg_confidence, 2),
                "created_at": data.get("created_at"),
            }
        
        except Exception as e:
            logger.error(f"Error obteniendo estadísticas: {e}")
            return {
                "total_rules": 0,
                "active_rules": 0,
                "error": str(e)
            }
    
    def get_all_rules_for_prompt_injection(self) -> str:
        """
        Retorna las reglas activas como string para inyectar en prompts.
        
        Usado en chat_service para contextualizar el LLM con lo aprendido.
        """
        rules = self.load_rules()
        
        if not rules:
            return ""
        
        rules_text = "\n\n**=== REGLAS APRENDIDAS POR EL SISTEMA ===**\n"
        rules_text += "El sistema ha aprendido las siguientes reglas del feedback de usuarios:\n\n"
        
        for rule in rules:
            if rule.verdict == "ACCEPTED":
                rules_text += f"✅ **{rule.description}**\n"
                rules_text += f"   Razonamiento: {rule.reasoning}\n"
                rules_text += f"   Confianza: {rule.confidence:.1%}\n\n"
        
        return rules_text if len(rules) > 0 else ""
