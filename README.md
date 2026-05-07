# llyc-ai-first-core

Tool executor y agentes de Claude Managed Agents para el sistema LLYC AI-First.

## Estructura

- `main.py` — punto de entrada Cloud Function
- `tools/` — implementación de tools por plataforma (Meta, Google Ads, GA4, DV360, TikTok, Drive)
- `clients/` — configuración por cliente
- `requirements.txt` — dependencias Python

## Stack

- Python 3.11+
- SDK anthropic · facebook-business · google-ads · google-analytics-data · google-api-python-client
- GCP: Cloud Functions · Cloud Scheduler · Secret Manager · Cloud Logging

## Documentación

Knowledge base completo del proyecto en Drive DM-AI-FIRST. Documentos clave:
- `arquitectura-sistema.md` — arquitectura técnica
- `META_arquitectura-github.md` — gobernanza GitHub
- `META_setup-repo-github.md` — guía de setup de este repo

## Owner

Max (`admin-tech-llyc`) · Soporte técnico: Alberto González · DevOps: Sergio
