# backend/app/services/mcp_analytics/routes/chat_ai.py
import os
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends

from app.services.auth_middleware import get_current_user
from app.services.mcp_analytics.chat_service import ChatService
from app.services.mcp_analytics.routes.dependencies import get_analytics_service

from app.models.mcp_analytics.core_models import (
    ChatRequest, ChatResponse,
    PDFInsightsRequest, PDFInsightsResponse,
    EngagementScoreExplanationRequest, EngagementScoreExplanationResponse
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat_with_data(
    request: ChatRequest,
    session_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    user_email: str = Depends(get_current_user)
):
    """Chat interactivo con los datos de GA4/Adobe."""
    s_id = request.session_id or session_id
    c_id = request.connection_id or connection_id
    
    service = get_analytics_service(s_id, c_id, user_email)
    chat_service = ChatService(service)
    
    result = await chat_service.process_message(
        message=request.message,
        context=request.context,
        chat_history=[{"role": m.role, "content": m.content} for m in (request.chat_history or [])]
    )
    
    return ChatResponse(
        message=result.get("message", ""),
        suggestions=result.get("suggestions"),
        data=result.get("data")
    )

@router.post("/generate-pdf-insights", response_model=PDFInsightsResponse)
async def generate_pdf_insights(
    request: PDFInsightsRequest,
    user_email: str = Depends(get_current_user)
):
    """
    Genera un análisis narrativo profundo para el reporte PDF usando Gemini.
    """
    try:
        from google import genai
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="Gemini API Key not configured")
            
        client = genai.Client(api_key=api_key)
        
        # Enriquecer el resumen de datos para el prompt
        data_summary = json.dumps(request.data, indent=2)
        lang_inst = "Responde en Español" if request.language == "es" else "Respond in English"
        
        prompt = f"""
        ERES: Un Consultor Senior de Growth Marketing y Estrategia Digital en LLYC, experto en IA Generativa y Analítica Avanzada.
        OBJETIVO: Analizar los datos de un reporte de '{request.report_type}' de la propiedad '{request.property_name}' y redactar un informe ejecutivo de altísimo valor para el C-Level del cliente.
        
        CONTEXTO DE LOS DATOS (JSON):
        {data_summary}
        
        REGLAS DE ORO DE REDACCIÓN:
        1. {lang_inst}.
        2. TONO: Extremadamente profesional, estratégico, directo y accionable. Evita introducciones genéricas como "Aquí tienes el análisis".
        3. FORMATO: Usa negritas (**KPI**) para resaltar números y hallazgos críticos.
        4. IDENTIDAD: Habla como un consultor humano experto. No menciones que eres una IA.
        5. ENFOQUE: No te limites a leer los datos; interpreta qué significan para el negocio. Si el Sniper Score es bajo, explica por qué y cómo mejorarlo. Si hay tráfico inferido de IA, destaca el potencial de 'Dark Social'.
        
        ESTRUCTURA TÉCNICA REQUERIDA (JSON ESTRICTO):
        Devuelve ÚNICAMENTE un objeto JSON con estas llaves:
        - executive_summary: Un párrafo potente (5-6 líneas) con el hallazgo más disruptivo del período.
        - sections: Una lista de 4 objetos con:
            * 'title': Título estratégico (ej: "Optimización del Funnel de IA", "AEO: El nuevo SEO").
            * 'content': 2-3 párrafos de análisis profundo, citando métricas específicas de los datos adjuntos.
            * 'key_takeaway': Una "bala de plata" o acción táctica inmediata de impacto.
        - footer_disclaimer: Cláusula de confidencialidad y rigor estadístico de LLYC.
        
        INDICACIONES ESPECÍFICAS PARA '{request.report_type}':
        - Analiza la "Batalla de IAs": ¿Qué motor (ChatGPT, Claude, Perplexity) es más eficiente?
        - Comenta sobre los Behavioral Clusters: ¿Por qué tenemos más 'Researchers' o 'Quick Answers'?
        - Sugiere estrategias de AEO (AI Engine Optimization) para las Landing Pages con mayor afinidad.
        """
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config={
                'response_mime_type': 'application/json'
            }
        )
        
        if response and response.text:
            # Clean possible markdown formatting if Gemini returns it despite the config
            clean_text = response.text.strip()
            if clean_text.startswith("```"):
                # Remove first line (e.g. ```json) and last line (```)
                lines = clean_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].strip() == "```":
                    lines = lines[:-1]
                clean_text = "\n".join(lines).strip()
                
            return json.loads(clean_text)
        else:
            raise Exception("Empty response from Gemini")
            
    except Exception as e:
        logger.error(f"Failed to generate PDF insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/explain-engagement-score", response_model=EngagementScoreExplanationResponse)
async def explain_engagement_score(
    request: EngagementScoreExplanationRequest,
    user_email: str = Depends(get_current_user)
):
    """
    Explica el Engagement Score (Sniper Score) usando IA basada en la metodología oficial.
    """
    try:
        from google import genai
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="Gemini API Key not configured")
            
        client = genai.Client(api_key=api_key)
        
        lang_inst = "Responde en Español" if request.language == "es" else "Respond in English"
        
        prompt = f"""
        ERES: Un Analista de Datos Senior experto en la metodología "Sniper Score" de LLYC.
        OBJETIVO: Explicar de forma clara y técnica por qué un segmento de tráfico tiene un Engagement Score de {request.engagement_score}.
        
        DATOS ACTUALES:
        - Engagement Score: {request.engagement_score} / 100
        - Conversiones: {request.conversions}
        - Duración Media: {request.avg_duration}s
        - Páginas por Sesión: {request.pages_per_session}
        
        METODOLOGÍA (Sniper Score v3):
        La fórmula es S(c, d, p) = B(c) + [30 / log10((d * p) + 10)]
        Donde:
        - B(c) es un Bono Base: Si hay conversiones (>0), B(c) = 70. Si no, B(c) = 0.
        - d * p es la "Fricción" (Duración x Profundidad).
        - La IA premia la EFICIENCIA: Menos fricción con el mismo resultado sube el score. Una fricción excesiva (dar vueltas sin convertir) baja el score.
        
        REQUERIMIENTOS DE RESPUESTA:
        1. {lang_inst}.
        2. ESTRUCTURA (JSON):
           - explanation: Un párrafo narrativo que interprete el score según la eficiencia observada.
           - methodology_summary: Un resumen de qué es el Sniper Score (máximo 2 líneas).
           - calculation_detail: Una explicación de cómo los datos ({request.conversions} conv, {request.avg_duration}s, {request.pages_per_session} pág) influyeron en el {request.engagement_score} final.
        
        Devuelve ÚNICAMENTE el JSON.
        """
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config={
                'response_mime_type': 'application/json'
            }
        )
        
        if response and response.text:
            clean_text = response.text.strip()
            if clean_text.startswith("```"):
                lines = clean_text.splitlines()
                if lines[0].startswith("```"): lines = lines[1:]
                if lines[-1].strip() == "```": lines = lines[:-1]
                clean_text = "\n".join(lines).strip()
                
            return json.loads(clean_text)
        else:
            raise Exception("Empty response from Gemini")
            
    except Exception as e:
        logger.error(f"Failed to explain engagement score: {e}")
        raise HTTPException(status_code=500, detail=str(e))
