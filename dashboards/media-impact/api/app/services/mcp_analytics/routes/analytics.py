# backend/app/services/mcp_analytics/routes/analytics.py
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Query, File, UploadFile

from app.core.config import settings
from app.services.auth_middleware import get_current_user, verify_tenant_access
from app.services.auth_utils import TokenManager, RBACManager
from app.services.mcp_analytics.adobe_service import AdobeAnalyticsService
from app.services.mcp_analytics.ga_advanced_service import GA4AdvancedService
from app.services.mcp_analytics.ga_risk_service import GA4RiskService
from app.services.mcp_analytics.ga_traffic_ia_service import GATrafficIAService
from app.services.mcp_analytics.session_service import session_service

from app.services.mcp_analytics.routes.dependencies import (
    get_credentials,
    get_analytics_service,
    get_inspector_service
)

from app.models.mcp_analytics.core_models import (
    RunReportRequest, RunReportResponse, DeepDiveRequest,
    RiskAnalysisRequest, TrafficIARequest, TrafficIAResponse,
    TrafficIAURLAnalysisRequest, TrafficIAURLAnalysisResponse,
    GAAccount, GAProperty,
    AdvancedReportRequest, FunnelAnalysisRequest
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/session/check")
async def check_session(session_id: Optional[str] = None):
    """Verifica si la sesión es válida."""
    if not session_id:
        return {"authenticated": False, "message": "No session_id provided"}
    
    session = session_service.get_session(session_id)
    if not session:
        return {"authenticated": False, "message": "Invalid session"}
    
    provider = session.get("provider", "google")
    if provider == "adobe":
        if not session.get("adobe_credentials"):
            return {"authenticated": False, "message": "Adobe credentials not found", "action": "show_adobe_modal", "provider": provider}
    else:
        if not session.get("credentials"):
            return {"authenticated": False, "message": "Credentials not found", "action": "redirect_to_login", "provider": provider}
    return {"authenticated": True, "session_id": session_id, "message": "Session is valid", "user_email": session.get("user_email"), "provider": provider}

@router.get("/user-connections")
async def list_user_connections(user_email: str = Depends(get_current_user)):
    """Lista las conexiones de GA4 y Adobe Analytics disponibles para el usuario en la plataforma."""
    try:
        target_email = user_email.lower().strip()
        tm = TokenManager()
        all_connections = tm.list_user_connections(target_email)
        
        # Filtrar solo GA4 y Adobe
        filtered = []
        for conn in all_connections:
            platform = conn.get("platform", "").upper()
            if platform in ["GA4", "ADOBE_ANALYTICS", "GOOGLE_ANALYTICS", "ADOBE", "BRANDLIGHT", "PEEC"]:
                filtered.append({
                    "connection_id": conn["id"],
                    "platform": platform,
                    "display_name": conn.get("metadata", {}).get("account_name", conn["id"]),
                    "account_id": conn.get("metadata", {}).get("account_id")
                })
        return {"connections": filtered}
    except Exception as e:
        logger.error(f"Error listing user connections: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/test-connection")
async def test_connection(
    connection_id: str,
    session_id: Optional[str] = None,
    user_email: str = Depends(get_current_user)
):
    """Prueba si una conexión es válida y devuelve detalles en caso de error."""
    try:
        service = get_analytics_service(session_id, connection_id, user_email, force_refresh=True)
        try:
            accounts = await service.list_accounts()
            
            if not accounts and getattr(service, "provider", None) == "adobe":
                # Si es Adobe y devolvió 0, devolvemos el RAW para inspección
                return {
                    "status": "warning", 
                    "accounts_found": 0, 
                    "message": "Adobe Discovery returned 0 accounts",
                    "raw_adobe_response": service._last_raw_discovery
                }
                
            return {"status": "ok", "accounts_found": len(accounts)}
        except Exception as inner_e:
            res = {"status": "error", "message": str(inner_e)}
            if getattr(service, "provider", None) == "adobe" and service._last_raw_discovery:
                res["raw_adobe_response"] = service._last_raw_discovery
            return res
            
    except Exception as e:
        logger.error(f"Connection test failed for {connection_id}: {e}")
        return {"status": "error", "message": str(e)}

@router.get("/accounts")
async def list_accounts(
    session_id: Optional[str] = None, 
    connection_id: Optional[str] = None, 
    tenant_id: Optional[str] = Query(None),
    user_email: str = Depends(get_current_user)
):
    """Lista las cuentas del proveedor configurado con reintento de refresh."""
    try:
        service = get_analytics_service(session_id, connection_id, user_email, tenant_id=tenant_id)
        try:
            accounts = await service.list_accounts()
            return {"accounts": [acc.model_dump() for acc in accounts]}
        except Exception as e:
            if "401" in str(e) or "authentication" in str(e).lower() or "unauthenticated" in str(e).lower():
                logger.info("401 detected in list_accounts, attempting forced token refresh...")
                service = get_analytics_service(session_id, connection_id, user_email, force_refresh=True, tenant_id=tenant_id)
                accounts = await service.list_accounts()
                return {"accounts": [acc.model_dump() for acc in accounts]}
            raise e
    except Exception as e:
        logger.error(f"Error in list_accounts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/properties")
async def list_properties(
    account_id: Optional[str] = None, 
    session_id: Optional[str] = None, 
    connection_id: Optional[str] = None, 
    tenant_id: Optional[str] = Query(None),
    user_email: str = Depends(get_current_user)
):
    """Lista las propiedades del proveedor configurado con reintento de refresh."""
    try:
        clean_account_id = None
        if account_id:
            clean_account_id = account_id.split("/")[-1]
            
        service = get_analytics_service(session_id, connection_id, user_email, tenant_id=tenant_id)
        try:
            properties = await service.list_properties(clean_account_id)
            return {"properties": [prop.model_dump() for prop in properties]}
        except Exception as e:
            if "401" in str(e) or "authentication" in str(e).lower() or "unauthenticated" in str(e).lower():
                logger.info("401 detected in list_properties, attempting forced token refresh...")
                service = get_analytics_service(session_id, connection_id, user_email, force_refresh=True, tenant_id=tenant_id)
                properties = await service.list_properties(clean_account_id)
                return {"properties": [prop.model_dump() for prop in properties]}
            raise e
    except Exception as e:
        logger.error(f"Error in list_properties: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/adobe/segments/{property_id}")
async def list_adobe_segments(
    property_id: str,
    connection_id: str,
    tenant_id: Optional[str] = Query(None),
    user_email: str = Depends(get_current_user)
):
    """Lista los segmentos disponibles para un Report Suite de Adobe Analytics."""
    try:
        # We must use the analytics service factory to get an authenticated Adobe service
        service = get_analytics_service(connection_id=connection_id, user_email=user_email, tenant_id=tenant_id)
        
        # Check if the service is indeed an AdobeAnalyticsService
        if not isinstance(service, AdobeAnalyticsService):
            raise HTTPException(status_code=400, detail="This endpoint is only for Adobe Analytics connections.")
            
        segments = await service.list_segments(property_id)
        return {"segments": segments}
    except HTTPException as e:
        # Re-raise HTTP exceptions to let FastAPI handle them
        raise e
    except Exception as e:
        logger.error(f"Error in list_adobe_segments for property {property_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/run-report", response_model=RunReportResponse)
async def run_report(
    request: RunReportRequest, 
    session_id: Optional[str] = None, 
    connection_id: Optional[str] = None, 
    user_email: str = Depends(get_current_user)
):
    """Ejecuta un reporte en el proveedor configurado, prefiriendo BigQuery si hay datos del tenant."""
    s_id = request.session_id or session_id
    c_id = request.connection_id or connection_id
    t_id = request.tenant_id
    
    # Validar acceso al tenant si se provee uno
    if t_id:
        await verify_tenant_access(t_id, user_email, enforce_2fa=True)
    
    # Si se pasa un tenant_id y no estamos en modo live_api, intentar recuperar datos reales desde BigQuery
    if t_id and not request.live_api:
        try:
            from app.services.mcp_analytics.bigquery_service import BigQueryService
            bq = BigQueryService()
            
            # Formatear fechas de consulta
            start_date = request.date_ranges[0]["start_date"] if request.date_ranges else "30daysAgo"
            end_date = request.date_ranges[0]["end_date"] if request.date_ranges else "today"
            
            if "daysago" in start_date.lower():
                import re
                match = re.match(r"(\d+)daysago", start_date.lower())
                if match:
                    days = int(match.group(1))
                    start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
                else:
                    start_date = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
            if end_date.lower() == "today":
                end_date = datetime.utcnow().strftime("%Y-%m-%d")
                
            metrics = bq.query_dashboard_metrics(t_id, start_date, end_date, segment_id=request.segment_id)
            if metrics and metrics.get("has_data", False):
                logger.info(f"Consumiendo datos reales desde Google BigQuery para el tenant '{t_id}'.")
                
                # Mapear las filas diarias directamente para que el frontend pueda pintar los gráficos reales de evolución!
                report_rows = []
                for r in metrics.get("daily_rows", []):
                    report_rows.append({
                        "date": r["date"],
                        "sessions": str(r["sessions"]),
                        "ai_referred": str(r["ai_referred"]),
                        "ai_inferred": str(r["ai_inferred"]),
                        "chatgpt_sessions": str(r.get("chatgpt_sessions", 0)),
                        "chatgpt_duration": str(r.get("chatgpt_duration", 0.0)),
                        "chatgpt_conversions": str(r.get("chatgpt_conversions", 0.0)),
                        "gemini_sessions": str(r.get("gemini_sessions", 0)),
                        "gemini_duration": str(r.get("gemini_duration", 0.0)),
                        "gemini_conversions": str(r.get("gemini_conversions", 0.0)),
                        "perplexity_sessions": str(r.get("perplexity_sessions", 0)),
                        "perplexity_duration": str(r.get("perplexity_duration", 0.0)),
                        "perplexity_conversions": str(r.get("perplexity_conversions", 0.0)),
                        "claude_sessions": str(r.get("claude_sessions", 0)),
                        "claude_duration": str(r.get("claude_duration", 0.0)),
                        "claude_conversions": str(r.get("claude_conversions", 0.0)),
                        "copilot_sessions": str(r.get("copilot_sessions", 0)),
                        "copilot_duration": str(r.get("copilot_duration", 0.0)),
                        "copilot_conversions": str(r.get("copilot_conversions", 0.0)),
                        "other_ai_sessions": str(r.get("other_ai_sessions", 0)),
                        "other_ai_duration": str(r.get("other_ai_duration", 0.0)),
                        "other_ai_conversions": str(r.get("other_ai_conversions", 0.0)),
                        "conversions": str(r.get("engagement_score", 0)),
                        "visibility_score": str(metrics.get("visibility_score", 0)),
                        "sentiment_score": str(metrics.get("sentiment_score", 0))
                    })
                
                # Si no hay filas de tráfico diario pero sí de visibilidad, insertamos una agregada para el periodo
                if not report_rows:
                    report_rows.append({
                        "date": datetime.utcnow().strftime("%Y-%m-%d"),
                        "sessions": "0",
                        "ai_referred": "0",
                        "ai_inferred": "0",
                        "chatgpt_sessions": "0",
                        "chatgpt_duration": "0",
                        "chatgpt_conversions": "0",
                        "gemini_sessions": "0",
                        "gemini_duration": "0",
                        "gemini_conversions": "0",
                        "perplexity_sessions": "0",
                        "perplexity_duration": "0",
                        "perplexity_conversions": "0",
                        "claude_sessions": "0",
                        "claude_duration": "0",
                        "claude_conversions": "0",
                        "copilot_sessions": "0",
                        "copilot_duration": "0",
                        "copilot_conversions": "0",
                        "other_ai_sessions": "0",
                        "other_ai_duration": "0",
                        "other_ai_conversions": "0",
                        "conversions": "0",
                        "visibility_score": str(metrics.get("visibility_score", 0)),
                        "sentiment_score": str(metrics.get("sentiment_score", 0))
                    })
                    
                return RunReportResponse(
                    property_id=request.property_id or "bigquery-fact",
                    dimension_headers=["date"],
                    metric_headers=["sessions", "ai_referred", "ai_inferred", "chatgpt_sessions", "chatgpt_duration", "chatgpt_conversions", "gemini_sessions", "gemini_duration", "gemini_conversions", "perplexity_sessions", "perplexity_duration", "perplexity_conversions", "claude_sessions", "claude_duration", "claude_conversions", "copilot_sessions", "copilot_duration", "copilot_conversions", "other_ai_sessions", "other_ai_duration", "other_ai_conversions", "engagement_score", "visibility_score", "sentiment_score"],
                    rows=report_rows,
                    row_count=len(report_rows),
                    metadata={
                        "total_monitored_domains": metrics.get("total_monitored_domains", 0),
                        "competitors": metrics.get("competitors", []),
                        "topics_pr": metrics.get("topics_pr", []),
                        "topics_digital": metrics.get("topics_digital", []),
                        "domains": metrics.get("domains", []),
                        "behavioral_clusters": metrics.get("behavioral_clusters", {}),
                        "visibility_by_engine": metrics.get("visibility_by_engine", [])
                    }
                )
        except Exception as bqe:
            logger.warning(f"No se pudo consultar BigQuery para {t_id}, devolviendo reporte en ceros en lugar de fallback: {bqe}")

        # Si BigQuery no tiene datos o falló, devolvemos un reporte en ceros para evitar el mock de la Live API
        report_rows = [{
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "sessions": "0", "ai_referred": "0", "ai_inferred": "0",
            "chatgpt_sessions": "0", "chatgpt_duration": "0", "chatgpt_conversions": "0",
            "gemini_sessions": "0", "gemini_duration": "0", "gemini_conversions": "0",
            "perplexity_sessions": "0", "perplexity_duration": "0", "perplexity_conversions": "0",
            "claude_sessions": "0", "claude_duration": "0", "claude_conversions": "0",
            "copilot_sessions": "0", "copilot_duration": "0", "copilot_conversions": "0",
            "other_ai_sessions": "0", "other_ai_duration": "0", "other_ai_conversions": "0",
            "conversions": "0", "visibility_score": "0", "sentiment_score": "0"
        }]
        return RunReportResponse(
            property_id=request.property_id or "bigquery-fact",
            dimension_headers=["date"],
            metric_headers=["sessions", "ai_referred", "ai_inferred", "chatgpt_sessions", "chatgpt_duration", "chatgpt_conversions", "gemini_sessions", "gemini_duration", "gemini_conversions", "perplexity_sessions", "perplexity_duration", "perplexity_conversions", "claude_sessions", "claude_duration", "claude_conversions", "copilot_sessions", "copilot_duration", "copilot_conversions", "other_ai_sessions", "other_ai_duration", "other_ai_conversions", "engagement_score", "visibility_score", "sentiment_score"],
            rows=report_rows,
            row_count=len(report_rows),
            metadata={
                "total_monitored_domains": 0, "competitors": [], "topics_pr": [],
                "topics_digital": [], "domains": [], "behavioral_clusters": {}, "visibility_by_engine": []
            }
        )

    # Si NO hay tenant_id o es explícitamente live_api=True, sí usamos Live API
    try:
        service = get_analytics_service(s_id, c_id, user_email)
        result = await service.run_report(request)
        return result
    except Exception as e:
        logger.error(f"Error fetching live API report for tenant {t_id}: {e}", exc_info=True)
        if request.live_api:
            # Si estamos explícitamente en modo Live API y falla, devolver un error claro
            raise HTTPException(status_code=500, detail=f"Error en Live API: {str(e)}")
        raise e

@router.post("/advanced-report")
async def execute_advanced_report(
    request: AdvancedReportRequest,
    session_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    user_email: str = Depends(get_current_user)
):
    """Ejecuta reporte avanzado con validación de alcances y calidad."""
    s_id = request.session_id or session_id
    c_id = request.connection_id or connection_id
    
    try:
        service = get_analytics_service(s_id, c_id, user_email)
        if getattr(service, "provider", None) == "adobe":
            return await service.execute_advanced_report(
                request.property_id, 
                request.report_type,
                request.start_date, 
                request.end_date,
                request.custom_config
            )
    except Exception as e:
        logger.error(f"Adobe Advanced Report routing failed: {e}")
        return {"error": str(e)}
    
    # Fallback to GA4 Advanced
    credentials = get_credentials(s_id, c_id, user_email)
    if not credentials:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    advanced_service = GA4AdvancedService(credentials=credentials)
    return await advanced_service.execute_advanced_report(
        property_id=request.property_id,
        report_type=request.report_type,
        start_date=request.start_date,
        end_date=request.end_date,
        custom_config=request.custom_config
    )

@router.post("/funnel-analysis")
async def execute_funnel_analysis(
    request: FunnelAnalysisRequest,
    session_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    user_email: str = Depends(get_current_user)
):
    """Ejecuta análisis de funnel (embudo) con eventos secuenciales."""
    s_id = request.session_id or session_id
    c_id = request.connection_id or connection_id
    
    try:
        service = get_analytics_service(s_id, c_id, user_email)
        if getattr(service, "provider", None) == "adobe":
            return await service.execute_funnel_analysis(
                request.property_id, 
                request.steps,
                request.start_date, 
                request.end_date
            )
    except Exception as e:
        logger.error(f"Adobe Funnel routing failed: {e}")
        return {"error": str(e)}
    
    credentials = get_credentials(s_id, c_id, user_email)
    if not credentials:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    advanced_service = GA4AdvancedService(credentials=credentials)
    return await advanced_service.execute_funnel_analysis(
        property_id=request.property_id,
        steps=request.steps,
        start_date=request.start_date,
        end_date=request.end_date
    )

@router.post("/deep-dive")
async def execute_deep_dive(
    request: DeepDiveRequest,
    session_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    user_email: str = Depends(get_current_user)
):
    """Ejecuta análisis profundo (Deep Dive) multisección."""
    s_id = request.session_id or session_id
    c_id = request.connection_id or connection_id
    
    try:
        service = get_analytics_service(s_id, c_id, user_email)
        if getattr(service, "provider", None) == "adobe":
            return await service.execute_deep_dive(request.property_id, request.start_date, request.end_date)
    except Exception as e:
        logger.error(f"Adobe Deep Dive routing failed: {e}")
        return {"error": str(e)}
    
    credentials = get_credentials(s_id, c_id, user_email)
    if not credentials:
        raise HTTPException(status_code=401, detail="No autenticado")
    advanced_service = GA4AdvancedService(credentials=credentials)
    return await advanced_service.execute_deep_dive(request.property_id, request.start_date, request.end_date)

@router.post("/risk-analysis")
async def execute_risk_analysis(
    request: RiskAnalysisRequest,
    user_email: str = Depends(get_current_user)
):
    s_id = request.session_id
    c_id = request.connection_id
    
    try:
        service = get_analytics_service(s_id, c_id, user_email)
        if getattr(service, "provider", None) == "adobe":
            return await service.analyze_risk(
                request.property_id, 
                request.start_date, 
                request.end_date,
                request.break_even_roas
            )
    except Exception as e:
        logger.error(f"Adobe Risk routing failed: {e}")
        return {"error": str(e)}
    
    credentials = get_credentials(s_id, c_id, user_email)
    if not credentials:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    risk_service = GA4RiskService(credentials)
    return await risk_service.analyze_risk(request.property_id, {"start_date": request.start_date, "end_date": request.end_date}, request.break_even_roas)

@router.post("/traffic-ia", response_model=TrafficIAResponse)
async def analyze_traffic_ia(
    request: TrafficIARequest,
    user_email: str = Depends(get_current_user)
):
    s_id = request.session_id
    c_id = request.connection_id
    
    try:
        service = get_analytics_service(s_id, c_id, user_email)
        if getattr(service, "provider", None) == "adobe":
            return await service.analyze_traffic_ia(
                request.property_id, 
                request.start_date, 
                request.end_date,
                language=getattr(request, 'language', 'es'),
                segment_id=getattr(request, 'segment_id', None)
            )
    except Exception as e:
        logger.error(f"Adobe Traffic-IA routing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    credentials = get_credentials(s_id, c_id, user_email)
    if not credentials:
        raise HTTPException(status_code=401, detail="No autenticado")
    ia_service = GATrafficIAService(credentials)
    return await ia_service.analyze_traffic_ia(request.property_id, {"start_date": request.start_date, "end_date": request.end_date}, language=getattr(request, 'language', 'es'))

@router.post("/traffic-ia/url-analysis", response_model=TrafficIAURLAnalysisResponse)
async def execute_traffic_ia_url_analysis(
    request: TrafficIAURLAnalysisRequest, 
    session_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    user_email: str = Depends(get_current_user)
):
    s_id = request.session_id or session_id
    c_id = request.connection_id or connection_id
    
    try:
        service = get_analytics_service(s_id, c_id, user_email)
        if getattr(service, "provider", None) == "adobe":
            return await service.analyze_url_performance(request.property_id, {"start_date": request.start_date, "end_date": request.end_date}, request.urls)
    except Exception as e:
        logger.error(f"Adobe URL Analysis routing failed: {e}")
        return {"url_performance": [], "summary": {"total_sessions": 0, "urls_analyzed": request.urls}, "daily_trend": [], "traffic_sources_analysis": []}

    credentials = get_credentials(s_id, c_id, user_email)
    if not credentials:
        raise HTTPException(status_code=401, detail="No autenticado")
    traffic_service = GATrafficIAService(credentials=credentials)
    return await traffic_service.analyze_url_performance(request.property_id, {"start_date": request.start_date, "end_date": request.end_date}, request.urls)

@router.get("/property-audit")
async def audit_property(
    property_id: str, 
    session_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    user_email: str = Depends(get_current_user)
):
    """Audita la configuración de una propiedad."""
    service = get_analytics_service(session_id, connection_id, user_email)
    return await service.audit_configuration(property_id)

@router.post("/upload-data")
async def upload_data(file: UploadFile = File(...), user_email: str = Depends(get_current_user)):
    """Sube un archivo local para análisis (CSV/Excel)."""
    try:
        from app.services.mcp_analytics.local_data_service import LocalDataService
        service = LocalDataService()
        result = await service.save_file(file, user_email)
        return result
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail=str(e))
