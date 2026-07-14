# backend/app/services/mcp_analytics/routes/oauth.py
import logging
from typing import Dict
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/oauth/login")
async def oauth_login(request: Request, provider: str = "google"):
    """
    Inicia el flujo de autenticación OAuth.
    Detecta de forma dinámica la dirección IP/Host de origen para redirigir
    correctamente al frontend en desarrollo o producción.
    """
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:3000"
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    
    # Forzar HTTPS en dominios de Google Cloud o Firebase Hosting
    if host and (".a.run.app" in host or ".web.app" in host or "firebaseapp.com" in host or "llyc.global" in host):
        proto = "https"
        
    logger.info(f"🔑 [OAuth Login] Request host: {host} | Proto: {proto}")
    
    # Determinar base de URL del Frontend
    if "localhost:80" in host or "127.0.0.1:80" in host:
        # Backend local redirige al puerto del frontend local de Vite
        base_url = "http://localhost:3000"
    elif "localhost:3000" in host:
        base_url = "http://localhost:3000"
    else:
        # En producción, Firebase sirve el frontend en la raíz de /media-impact
        base_url = f"{proto}://{host}/media-impact"
        
    redirect_uri = f"{base_url}?connection_id=mock-ga4&session_id=presentacion-llyc"
    logger.info(f"🔄 [OAuth Redirect] Redirigiendo cliente de vuelta a: {redirect_uri}")
    
    return RedirectResponse(redirect_uri)

@router.post("/oauth/callback")
async def oauth_callback(request: Request, data: Dict[str, str]):
    """Callback de OAuth (MOCKED FOR PRESENTATION)."""
    return {
        "status": "success",
        "session_id": "presentacion-llyc",
        "connection_id": "mock-ga4"
    }

