"""Evaluador de Feedback con IA - Judge del Sistema de Aprendizaje.

Módulo que valida feedback del usuario contra documentación de GA4.
Utiliza LLM con prompts estrictos para decidir si una sugerencia debe ser aceptada.
"""

import os
import json
import re
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class VerdictType(str, Enum):
    """Tipos de veredicto que puede retornar el evaluador."""
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PREFERENCE = "PREFERENCE"  # Válido pero es preferencia, no regla dura
    SIMPLE_EXECUTION = "SIMPLE_EXECUTION" # Requiere cambio técnico sencillo


class EvaluationResult:
    """Resultado de la evaluación de un feedback."""
    
    def __init__(
        self,
        verdict: VerdictType,
        confidence: float,
        reasoning: str,
        rule_description: Optional[str] = None,
        technical_action: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Args:
            verdict: ACCEPTED, REJECTED, PREFERENCE o SIMPLE_EXECUTION
            confidence: Score 0-1 de confianza en el veredicto
            reasoning: Explicación detallada del veredicto
            rule_description: Descripción clara de la regla (si aplica)
            technical_action: Acción técnica a ejecutar (si aplica)
            metadata: Información adicional para trazabilidad
        """
        self.verdict = verdict
        self.confidence = confidence
        self.reasoning = reasoning
        self.rule_description = rule_description
        self.technical_action = technical_action
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte el resultado a diccionario para persistencia."""
        return {
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "rule_description": self.rule_description,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class FeedbackEvaluator:
    """
    Evaluador de feedback que actúa como Judge del sistema.
    
    Recibe feedback del usuario y lo evalúa contra:
    1. Documentación oficial de GA4
    2. Mejores prácticas de medición digital
    3. Consistencia con el modelo de datos existente
    4. Impacto en la precisión de análisis
    
    Retorna veredictos con confianza, nunca ciega aplicación de reglas.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Inicializa el evaluador.
        
        Args:
            api_key: API key de Gemini (si no se proporciona, usa env var)
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._model = None
    
    @property
    def model(self):
        """Lazy load del modelo Gemini."""
        if self._model is None and self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                # Use gemini-2.5-pro: most advanced stable Gemini 2.5 model for critical evaluation
                self._model = genai.GenerativeModel(
                    'gemini-2.5-pro',
                    generation_config={
                        "temperature": 0.0,  # Deterministic, not creative
                        "top_p": 0.95,
                        "top_k": 40,
                        "max_output_tokens": 2048,
                    }
                )
                logger.info("FeedbackEvaluator initialized with gemini-2.5-pro")
            except Exception as e:
                logger.error(f"❌ Error inicializando FeedbackEvaluator: {e}")
                self._model = None
        return self._model
    
    async def evaluate_feedback(
        self,
        user_feedback: str,
        context: Optional[Dict[str, Any]] = None,
        data_context: Optional[str] = None,
    ) -> EvaluationResult:
        """
        Evalúa un feedback del usuario.
        
        Args:
            user_feedback: El feedback o sugerencia del usuario
            context: Contexto adicional (ej: qué se estaba analizando)
            data_context: Datos o métricas relevantes en contexto
        
        Returns:
            EvaluationResult con verdict, confidence y reasoning
        """
        if not self.model:
            logger.warning("Gemini no configurado, retornando PREFERENCE")
            return EvaluationResult(
                verdict=VerdictType.PREFERENCE,
                confidence=0.3,
                reasoning="Evaluador no disponible (GEMINI_API_KEY no configurada)",
                metadata={"error": "model_unavailable"}
            )
        
        # Construir el prompt para el Judge
        prompt = self._build_judge_prompt(user_feedback, context, data_context)
        
        try:
            # Llamar al LLM con el sistema de evaluación estricto
            response = self.model.generate_content(prompt)
            
            # Parsear la respuesta JSON del modelo
            result = self._parse_judge_response(response.text, user_feedback)
            return result
            
        except Exception as e:
            logger.error(f"Error evaluando feedback: {e}")
            return EvaluationResult(
                verdict=VerdictType.REJECTED,
                confidence=0.0,
                reasoning=f"Error al evaluar: {str(e)}",
                metadata={"error": str(e)}
            )
    
    def _build_judge_prompt(
        self,
        user_feedback: str,
        context: Optional[Dict[str, Any]],
        data_context: Optional[str]
    ) -> str:
        """Construye el prompt para el Judge AI."""
        
        context_info = ""
        if context:
            if context.get("property_id"):
                context_info += f"\n- Propiedad GA4: {context['property_id']}"
            if context.get("issue_type"):
                context_info += f"\n- Tipo de issue: {context['issue_type']}"
            if context.get("affected_metric"):
                context_info += f"\n- Métrica afectada: {context['affected_metric']}"
        
        data_info = ""
        if data_context:
            data_info = f"\n\n**DATOS EN CONTEXTO**:\n{data_context[:500]}..."  # Limitar a 500 chars
        
        judge_prompt = f"""Eres un JUEZ TÉCNICO ESPECIALIZADO en Google Analytics 4 (GA4) y medición digital.

Tu rol es evaluar si una sugerencia de mejora (feedback) del usuario tiene VALIDEZ TÉCNICA, no es ser amable.

**REGLAS ESTRICTAS DE EVALUACIÓN**:
1. **NO ACEPTES CIEGAMENTE**: El usuario podría estar equivocado. Valida contra documentación de GA4.
2. **SOSPECHA DE SESGO**: Los usuarios tienden a sugerir cambios que "confirmen" sus hipótesis previas.
3. **PRECISIÓN ES CRÍTICA**: Un cambio que "parece correcto" pero es incorrecto, corrompe análisis futuros.
4. **DATOS PRIMERO**: Si hay datos que contradicen la sugerencia, recházala.

**DOCUMENTACIÓN GA4 DE REFERENCIA**:
- Sessions: Agrupa eventos de usuario en una sesión. Una sesión expira tras 30 min sin actividad.
- Source: Origen del tráfico (google, direct, bing, etc). Almacenado en 'source' parameter.
- Medium: Tipo de tráfico (organic, cpc, referral, direct, etc). Almacenado en 'medium' parameter.
- User IDs: Identificadores persistentes de usuarios. Requeridos ANTES de recopilarlos.
- Custom dimensions/metrics: Debe estar implementadas en GA4, no "inventadas" en informes.
- Events: GA4 mide TODO como eventos. No hay "pageviews" nativos, se simulan con "page_view" events.
- Conversions: Deben estar marcadas como "conversión" en GA4, no ser un evento cualquiera.

**TIPOS DE VEREDICTO**:
1. **ACCEPTED**: La sugerencia es técnicamente válida y debe convertirse en regla. Base sólida en GA4 docs.
2. **REJECTED**: La sugerencia es incorrecta, vaga o contradice GA4 specs. NO debe aplicarse nunca.
3. **PREFERENCE**: Es válida pero es preferencia/opción, no una regla fundamental. Aplicar con cuidado.
4. **SIMPLE_EXECUTION**: La sugerencia implica un cambio de CONFIGURACIÓN directo (ej: mapeo de métricas, alias, umbrales).

**CONTEXTO DEL USUARIO**:{context_info}{data_info}

**FEEDBACK DEL USUARIO**:
"{user_feedback}"

**TAREA**:
Evalúa el feedback. Retorna un JSON con:
{{
  "verdict": "ACCEPTED" | "REJECTED" | "PREFERENCE" | "SIMPLE_EXECUTION",
  "confidence": 0.0-1.0,
  "reasoning": "Explicación clara de por qué aceptas/rechazas. Cita documentación si aplica.",
  "rule_description": "Si es ACCEPTED o SIMPLE_EXECUTION: descripción clara de la regla a aplicar. Si es REJECTED o PREFERENCE: null",
  "technical_action": "Si es SIMPLE_EXECUTION, indica qué JSON o parámetro técnico cambiar (ej: 'alias metric activeUsers to users'). Si no, null"
}}

**INSTRUCCIONES CRÍTICAS**:
- Tu respuesta DEBE ser JSON válido y NADA MÁS.
- confidence > 0.8 = muy seguro; 0.5-0.8 = moderado; < 0.5 = bajo.
- Si no entiendes el feedback, retorna REJECTED con confidence baja.
- Si el feedback es vago ("arregla eso"), retorna REJECTED.
- Si es una preferencia pero no una regla dura (ej "me gustaría ver X de otra forma"), retorna PREFERENCE.
"""
        
        return judge_prompt
    
    def _parse_judge_response(self, response_text: str, original_feedback: str) -> EvaluationResult:
        """Parsea la respuesta JSON del Judge con parsing robusto."""
        
        try:
            text = response_text.strip()
            
            # Estrategia 1: Limpiar markdown code blocks
            if text.startswith("```json"):
                text = text[7:].strip()
            elif text.startswith("```"):
                text = text[3:].strip()
            
            if text.endswith("```"):
                text = text[:-3].strip()
            
            # Estrategia 2: Intentar parsear directamente
            try:
                data = json.loads(text)
                return self._create_evaluation_result(data, original_feedback)
            except json.JSONDecodeError:
                pass
            
            # Estrategia 3: Buscar JSON en el texto usando regex
            json_pattern = r'(\{.*?"verdict"\s*:\s*"(?:ACCEPTED|REJECTED|PREFERENCE|SIMPLE_EXECUTION)".*?\})'
            match = re.search(json_pattern, response_text, re.DOTALL)
            
            if match:
                try:
                    data = json.loads(match.group(1))
                    return self._create_evaluation_result(data, original_feedback)
                except json.JSONDecodeError as e:
                    logger.debug(f"Error parseando JSON extraído con regex: {e}")
            
            # Estrategia 4: Si todo falla, retornar PREFERENCE
            logger.warning(f"No se pudo parsear respuesta del Judge. Texto: {response_text[:200]}")
            return EvaluationResult(
                verdict=VerdictType.PREFERENCE,
                confidence=0.3,
                reasoning=f"No se pudo parsear la respuesta del evaluador. Feedback original: '{original_feedback}'",
                metadata={"error": "json_parse_failed", "raw_text": response_text[:300]}
            )
            
        except Exception as e:
            logger.error(f"Error inesperado parseando respuesta: {e}")
            return EvaluationResult(
                verdict=VerdictType.REJECTED,
                confidence=0.0,
                reasoning=f"Error inesperado: {str(e)}",
                metadata={"error": "unexpected_error"}
            )
    
    def _create_evaluation_result(self, data: Dict[str, Any], original_feedback: str) -> EvaluationResult:
        """Convierte un dict parseado a EvaluationResult."""
        try:
            verdict_str = data.get("verdict", "REJECTED").upper()
            valid_verdicts = [v.value for v in VerdictType]
            if verdict_str not in valid_verdicts:
                verdict_str = "REJECTED"
            
            verdict = VerdictType(verdict_str)
            confidence = float(data.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))  # Clamp 0-1
            
            reasoning = data.get("reasoning", "No hay explicación disponible")
            rule_desc = data.get("rule_description")
            tech_action = data.get("technical_action")
            
            return EvaluationResult(
                verdict=verdict,
                confidence=confidence,
                reasoning=reasoning,
                rule_description=rule_desc,
                technical_action=tech_action,
                metadata={
                    "original_feedback": original_feedback,
                }
            )
        except Exception as e:
            logger.error(f"Error creando EvaluationResult: {e}")
            return EvaluationResult(
                verdict=VerdictType.REJECTED,
                confidence=0.0,
                reasoning=f"Error procesando evaluación: {str(e)}",
                metadata={"error": str(e)}
            )
