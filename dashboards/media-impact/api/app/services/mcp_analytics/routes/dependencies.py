# backend/app/services/mcp_analytics/routes/dependencies.py
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Any

from fastapi import Depends, HTTPException

from app.core.config import settings
from app.services.auth_middleware import get_current_user
from app.services.auth_utils import TokenManager, RBACManager
from app.services.mcp_analytics.ga_service import GAService
from app.services.mcp_analytics.adobe_service import AdobeAnalyticsService
from app.services.mcp_analytics.peec_service import PeecService
from app.services.mcp_analytics.data_inspector import DataInspectorService
from app.services.mcp_analytics.session_service import session_service

logger = logging.getLogger(__name__)

def get_inspector_service():
    return DataInspectorService()

def get_credentials(
    session_id: Optional[str] = None, 
    connection_id: Optional[str] = None, 
    user_email: Optional[str] = None, 
    force_refresh: bool = False
) -> Optional[Any]:
    """Retrieves credentials from the session or platform connection."""
    # Try platform connection first
    if connection_id and user_email:
        try:
            target_user = user_email.lower().strip()
            logger.info(f"Getting credentials for connection_id: {connection_id}, user: {target_user}, force_refresh={force_refresh}")
            tm = TokenManager()
            connection = tm.get_connection(connection_id)
            if connection and RBACManager.can_view(connection.get("permissions", {}), target_user):
                tokens = connection.get("tokens", {})
                logger.info(f"Building Credentials for connection {connection_id} (Platform: {connection.get('platform')}). Available keys: {list(tokens.keys())}")
                
                # Support multiple key variations
                access_token = tokens.get("access_token") or tokens.get("accessToken")
                refresh_token = tokens.get("refresh_token") or tokens.get("refreshToken")
                
                from google.oauth2.credentials import Credentials
                creds = Credentials(
                    token=access_token,
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=settings.GOOGLE_CLIENT_ID,
                    client_secret=settings.GOOGLE_CLIENT_SECRET,
                    scopes=tokens.get("scopes", ["https://www.googleapis.com/auth/analytics.readonly"])
                )
                
                # Check and refresh if needed
                # If expiry is missing, force_refresh might be needed if token is invalid
                should_refresh = force_refresh or (creds.refresh_token and (not creds.token or creds.expired))
                
                if should_refresh and creds.refresh_token:
                    logger.info(f"Triggering token refresh for {connection_id}...")
                    from google.auth.transport.requests import Request as AuthRequest
                    try:
                        creds.refresh(AuthRequest())
                        logger.info("Token refreshed successfully. Saving back to connection.")
                        
                        # Update the connection with the new token
                        try:
                            new_tokens = tokens.copy()
                            new_tokens["access_token"] = creds.token
                            if creds.refresh_token:
                                new_tokens["refresh_token"] = creds.refresh_token
                            
                            doc_ref = tm.db.collection(tm.collection).document(connection_id)
                            encrypted_tokens = tm._encrypt_tokens(new_tokens)
                            doc_ref.update({"tokens": encrypted_tokens, "updated_at": datetime.utcnow()})
                            logger.info(f"Connection {connection_id} tokens updated in Firestore.")
                        except Exception as save_ex:
                            logger.error(f"Failed to save refreshed tokens: {save_ex}")
                    except Exception as refresh_err:
                        logger.error(f"Refresh failed for {connection_id}: {refresh_err}")
                
                return creds
            else:
                if not connection:
                    logger.warning(f"Connection {connection_id} not found in Firestore.")
                else:
                    logger.warning(f"RBAC rejected for {target_user} on connection {connection_id}.")
        except Exception as e:
            logger.error(f"Error fetching credentials from connection {connection_id}: {e}", exc_info=True)

    # Fallback to legacy session
    if not session_id:
        return None
    session = session_service.get_session(session_id)
    if not session:
        return None
    
    provider = session.get("provider", "google")
    if provider == "google":
        creds_data = session.get("credentials")
        if not creds_data: return None
        from google.oauth2.credentials import Credentials
        return Credentials.from_authorized_user_info(creds_data)
    
    return None

def get_analytics_service(
    session_id: Optional[str] = None, 
    connection_id: Optional[str] = None, 
    user_email: Optional[str] = None, 
    force_refresh: bool = False,
    tenant_id: Optional[str] = None
) -> Any:
    """Factory to get the correct analytics service based on the session or connection."""
    
    # Try platform connection first
    if connection_id and user_email:
        target_user = user_email.lower().strip()
        
        if connection_id == "peec-temp":
            return PeecService({"api_key": "peec-temp"})
        elif connection_id == "brandlight-temp":
            from app.services.mcp_analytics.brandlight_service import BrandlightService
            return BrandlightService({"api_key": "brandlight-temp", "tenant_id": tenant_id})
        elif connection_id == "adobe-temp":
            return AdobeAnalyticsService({
                "client_id": "adobe-temp",
                "client_secret": "adobe-temp",
                "org_id": "adobe-temp",
                "company_id": "adobe-temp",
                "tenant_id": tenant_id
            })
        elif connection_id == "local":
            from app.services.mcp_analytics.ga_service import GAService
            return GAService(credentials=None, is_local=True)

        tm = TokenManager()
        connection = tm.get_connection(connection_id)
        if not connection:
             raise HTTPException(status_code=404, detail=f"Connection {connection_id} not found")
        
        if not RBACManager.can_view(connection.get("permissions", {}), target_user):
             raise HTTPException(status_code=403, detail="Unauthorized to access this connection")
             
        platform = connection.get("platform", "").upper()
        tokens = connection.get("tokens", {})
        metadata = connection.get("metadata", {})
        
        # Merge tokens and metadata for service initialization
        # This is critical for Adobe as IDs might be in metadata
        service_creds = {**tokens, **metadata}
        
        if platform in ["GA4", "GOOGLE_ANALYTICS"]:
            credentials = get_credentials(connection_id=connection_id, user_email=target_user, force_refresh=force_refresh)
            if not credentials:
                raise HTTPException(status_code=401, detail="Could not retrieve valid credentials for GA4")
            return GAService(credentials, inspector=get_inspector_service())
        elif platform == "ADOBE_ANALYTICS" or platform == "ADOBE":
            return AdobeAnalyticsService(service_creds)
        elif platform == "PEEC":
            return PeecService(service_creds)
        else:
             raise HTTPException(status_code=400, detail=f"Unsupported platform for MCP: {platform}")

    # Fallback to legacy session
    if not session_id:
        raise HTTPException(status_code=401, detail="No session_id or connection_id provided")
    
    session = session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
        
    provider = session.get("provider", "google")
    if provider == "google":
        credentials = get_credentials(session_id=session_id)
        if not credentials:
            raise HTTPException(status_code=401, detail="Google credentials not found in session")
        return GAService(credentials, inspector=get_inspector_service())
    elif provider == "adobe":
        adobe_creds = session.get("adobe_credentials")
        if not adobe_creds:
            raise HTTPException(status_code=401, detail="Adobe credentials not found in session")
        return AdobeAnalyticsService(adobe_creds)
    elif provider == "peec":
        peec_creds = session.get("peec_credentials") or session.get("credentials")
        if not peec_creds:
            raise HTTPException(status_code=401, detail="Peec credentials not found in session")
        return PeecService(peec_creds)
    
    raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

def get_current_admin(user_email: str = Depends(get_current_user)):
    """
    Filtro de seguridad estricto para garantizar que sólo cuentas de dominio @llyc.global
    puedan acceder a las operaciones de administración.
    """
    if not user_email.lower().strip().endswith("@llyc.global"):
        raise HTTPException(
            status_code=403,
            detail="Acceso denegado: Se requiere una cuenta corporativa de LLYC"
        )
    return user_email
