# MCP Analytics Services

This directory contains the core analytical logic for the Marketing Control Panel (MCP) in AIMA 2.0.

## Connectors

### 1. Adobe Analytics (`adobe_service.py`)
Provides advanced parity with GA4 features.
- **Dual-Query Engine**: To ensure exact SEO/Organic parity with Adobe Workspace, the service executes parallel requests for Referrers (AI identification) and Marketing Channels (SEO validation).
- **Time Formatting**: Standardized MM:SS durations.

### 2. GA4 Traffic IA (`ga_traffic_ia_service.py`)
- **Behavioral Clustering**: Classifies users into Researchers, Quick Answers, and Transactional.
- **Inference Model**: Estimates hidden AI traffic in organic channels.

## AI Insights Integration
Both services utilize the **Gemini 2.0 API** via the `google-genai` SDK.
- **Prompt Logic**: Localized (ES/EN) strategic analysis based on report KPIs.
- **Dependencies**: Requires `GEMINI_API_KEY` in environment variables.

---

# Servicios de MCP Analytics

Este directorio contiene la lógica analítica central del Marketing Control Panel (MCP) en AIMA 2.0.

## Conectores

### 1. Adobe Analytics (`adobe_service.py`)
Proporciona paridad avanzada con las funciones de GA4.
- **Motor de Consulta Dual**: Para garantizar la paridad exacta de SEO/Orgánico con Adobe Workspace, el servicio ejecuta peticiones paralelas para Referrers (identificación de IA) y Marketing Channels (validación de SEO).
- **Formateo de Tiempo**: Duraciones estandarizadas en MM:SS.

### 2. GA4 Traffic IA (`ga_traffic_ia_service.py`)
- **Clustering Conductual**: Clasifica a los usuarios en Investigadores, Respuestas Rápidas y Transaccionales.
- **Modelo de Inferencia**: Estima el tráfico de IA oculto en canales orgánicos.

## Integración de AI Insights
Ambos servicios utilizan la **API de Gemini 2.0** a través del SDK `google-genai`.
- **Lógica de Prompt**: Análisis estratégico localizado (ES/EN) basado en los KPIs del reporte.
- **Dependencias**: Requiere `GEMINI_API_KEY` en las variables de entorno.
