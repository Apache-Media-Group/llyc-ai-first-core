"""Servicio de chat con Gemini."""
import os
import json
import re
import logging
from typing import Optional, Dict, Any, List
from app.models.mcp_analytics.core_models import ChatRequest, ChatResponse, RunReportRequest

logger = logging.getLogger(__name__)

class ChatService:
    def __init__(self, api_key=None, knowledge_base=None, ga_service=None, local_data_service=None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._model = None
        self.knowledge_base = knowledge_base
        self.ga_service = ga_service
        self.local_data_service = local_data_service

    @property
    def model(self):
        if self._model is None and self.api_key:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            
            # System Instruction para forzar rol técnico
            system_instruction = """
            Eres un Analista de Datos Digitales Senior (Data Scientist) especializado en Google Analytics 4 y Adobe Analytics.
            Trabajas para LLYC Adtech. Tu misión es interpretar datos numéricos crudos y convertirlos en insights de negocio.

            REGLAS CRÍTICAS DE COMPORTAMIENTO (PENALIZACIÓN MÁXIMA SI SE VIOLAN):
            1. **ESTRICTAMENTE TÉCNICO:** NO eres un agente de atención al cliente de la marca analizada.
               - Si la propiedad es "Empresa-A", "Empresa-B" o "Empresa-C", NUNCA respondas sobre sus productos o servicios generales.
               - SOLO responde sobre sus DATOS: Visitas, Conversiones, Tasas de Rebote, Fuentes de Tráfico.
               - Ejemplo MAL: "Puedo ayudarte a pedir cita médica".
               - Ejemplo BIEN: "Puedo analizar cuántos usuarios visitaron la página de citas médicas y dónde abandonaron el funnel".

            2. **DATA-DRIVEN:**
               - Todas tus afirmaciones deben basarse en el JSON proporcionado en el bloque [CONTEXTO].
               - Si el contexto está vacío o no tiene los datos pedidos, RESPONDE: "No tengo esos datos cargados. Por favor ejecuta un reporte primero (ej: 'Últimos 7 días')."
               - NO ALUCINES DATOS.

            3. **FORMATO:**
               - Usa tablas Markdown para presentar cifras.
               - Usa negritas para métricas clave.
               - Sé conciso y ejecutivo.

            4. **INTENCIÓN:**
               - Si el usuario pregunta "¿qué puedes hacer?", ofrece opciones analíticas: "Puedo analizar tendencias de tráfico, desglosar por dispositivo, auditar la calidad del dato o comparar períodos."
            """

            self._model = genai.GenerativeModel(
                "gemini-2.5-pro",
                system_instruction=system_instruction,
                generation_config={
                    "temperature": 0.2, # Baja temperatura para precisión
                    "top_p": 0.95,
                    "max_output_tokens": 8192,
                }
            )
            logger.info("ChatService initialized with gemini-2.5-pro and Strict System Instruction")
        return self._model

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if not self.model:
            return ChatResponse(message="Chat no configurado (falta API Key).", suggestions=[])
        
        try:
            # Construir prompt con historial limitado
            history_txt = ""
            if hasattr(request, 'chat_history') and request.chat_history:
                # Tomar últimos 3 pares para contexto inmediato
                recent = request.chat_history[-6:]
                for msg in recent:
                    role = getattr(msg, 'role', 'user') if not isinstance(msg, dict) else msg.get('role', 'user')
                    content = getattr(msg, 'content', '') if not isinstance(msg, dict) else msg.get('content', '')
                    history_txt += f"{role.upper()}: {content}\n"

            # Contexto de datos
            context_str = json.dumps(request.context, indent=2, ensure_ascii=False) if request.context else "NO DATA CONTEXT"

            prompt = f"""
            [CONTEXTO DE DATOS ACTUALES]
            {context_str}

            [HISTORIAL DE CHAT RECIENTE]
            {history_txt}

            [PREGUNTA DEL USUARIO]
            {request.message}
            
            Responde como Analista de Datos:
            """

            response = self.model.generate_content(prompt)
            return ChatResponse(message=response.text, suggestions=[])
        except Exception as e:
            logger.error(f"Gemini Error: {e}")
            return ChatResponse(message=f"Error analizando datos: {str(e)}", suggestions=[])

    async def _detect_and_execute_tool(self, t, c): return None
