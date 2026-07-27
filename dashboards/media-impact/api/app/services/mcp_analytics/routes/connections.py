# backend/app/services/mcp_analytics/routes/connections.py
import logging
from typing import List
import json
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional

from app.services.auth_utils import TokenManager
from app.services.mcp_analytics.secret_manager_service import SecretManagerService

logger = logging.getLogger(__name__)
router = APIRouter()

class GA4ConnectionResponse(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    client_email: Optional[str] = None
    created_at: Optional[str] = None
    authorization_url: Optional[str] = None

@router.post("/connections/ga4", response_model=GA4ConnectionResponse)
async def create_ga4_connection(
    request: Request,
    name: str = Form(...),
    type: str = Form("service_account"),
    file: Optional[UploadFile] = File(None)
):
    """
    Crea una nueva conexión global a GA4 subiendo un Service Account JSON.
    Guarda los metadatos en Firestore y el JSON real en Secret Manager.
    """
    try:
        if type == "service_account":
            if not file or not file.filename.endswith('.json'):
                raise HTTPException(status_code=400, detail="Debe subir un archivo JSON válido de Service Account.")
                
            content = await file.read()
            sa_data = json.loads(content)
            
            if sa_data.get("type") != "service_account" or not sa_data.get("client_email"):
                raise HTTPException(status_code=400, detail="El JSON no contiene un Service Account válido.")
                
            client_email = sa_data.get("client_email")
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            safe_email_prefix = client_email.split("@")[0].replace(".", "-").replace("_", "-")
            connection_id = f"{safe_email_prefix}-{timestamp}"
            
            # 1. Guardar el JSON en Secret Manager
            secret_service = SecretManagerService()
            # Usamos "global" como tenant_id y f"ga4-conn-{connection_id}" como secret_type
            # Para que el ID resultante sea llyc-mcp-global-ga4-conn-...
            secret_saved = secret_service.save_tenant_secret(
                tenant_id="global",
                secret_type=f"ga4-conn-{connection_id}",
                secret_value=content.decode('utf-8')
            )
            
            if not secret_saved:
                raise HTTPException(status_code=500, detail="Error al guardar el Service Account en GCP Secret Manager.")
                
            # 2. Guardar los metadatos en Firestore
            tm = TokenManager()
            if not tm.db:
                raise HTTPException(status_code=500, detail="No hay conexión a la base de datos Firestore.")
                
            doc_ref = tm.db.collection("ga4_connections").document(connection_id)
            connection_data = {
                "id": connection_id,
                "name": name,
                "client_email": client_email,
                "created_at": datetime.utcnow().isoformat()
            }
            doc_ref.set(connection_data)
            
            logger.info(f"✅ Conexión Global GA4 '{name}' ({connection_id}) creada con éxito.")
            return GA4ConnectionResponse(**connection_data)
    
        elif type == "oauth_json":
            if not file or not file.filename.endswith('.json'):
                raise HTTPException(status_code=400, detail="Debe subir un client_secret de GCP válido.")
                
            content = await file.read()
            client_config = json.loads(content)
            
            if "web" not in client_config and "installed" not in client_config:
                raise HTTPException(status_code=400, detail="El JSON no parece ser un client_secret de OAuth válido.")
                
            # Generar URL de autorización
            from google_auth_oauthlib.flow import Flow
            import uuid
            
            # Determinar url base para callback
            host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:8080"
            proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
            if host and (".a.run.app" in host or ".web.app" in host or "firebaseapp.com" in host or "llyc.global" in host):
                proto = "https"
                
            redirect_uri = f"{proto}://{host}/api/v1/mcp-analytics/connections/ga4/callback"
            
            flow = Flow.from_client_config(
                client_config,
                scopes=['https://www.googleapis.com/auth/analytics.readonly']
            )
            flow.redirect_uri = redirect_uri
            
            # Necesitamos state para evitar CSRF y para pasar 'name' al callback
            state = str(uuid.uuid4())
            
            auth_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent',
                state=state
            )
            
            # Guardar en Firestore temporalmente el estado y el client_config para usarlo en el callback
            tm = TokenManager()
            if tm.db:
                tm.db.collection("oauth_states").document(state).set({
                    "name": name,
                    "client_config": client_config,
                    "redirect_uri": redirect_uri,
                    "code_verifier": getattr(flow, 'code_verifier', None),
                    "created_at": datetime.utcnow().isoformat()
                })
                
            logger.info(f"🔗 Iniciando flujo OAuth 3-Legged para '{name}'. Redirect URI: {redirect_uri}")
            return GA4ConnectionResponse(authorization_url=auth_url)
            
        elif type == "admin_oauth":
            raise HTTPException(status_code=501, detail="El login automático de Admin aún no está implementado.")
            
        else:
            raise HTTPException(status_code=400, detail="Tipo de conexión no válido.")
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="El archivo no es un JSON válido.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error inesperado al crear conexión GA4: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

@router.get("/connections/ga4", response_model=List[GA4ConnectionResponse])
async def list_ga4_connections():
    """
    Devuelve la lista de metadatos de las conexiones globales de GA4 configuradas.
    """
    try:
        tm = TokenManager()
        if not tm.db:
            raise HTTPException(status_code=500, detail="No hay conexión a la base de datos Firestore.")
            
        connections_ref = tm.db.collection("ga4_connections")
        docs = connections_ref.stream()
        
        connections = []
        for doc in docs:
            data = doc.to_dict()
            if data:
                connections.append(data)
                
        return sorted(connections, key=lambda x: x.get("created_at", ""), reverse=True)
    except Exception as e:
        logger.error(f"Error al listar conexiones GA4: {e}")
        raise HTTPException(status_code=500, detail="Error interno al listar conexiones.")

@router.get("/connections/ga4/{connection_id}/properties")
async def list_ga4_properties(connection_id: str):
    """
    Recupera el Service Account de Secret Manager y utiliza la API de GA4 Admin
    para listar las cuentas y propiedades accesibles.
    """
    try:
        # 1. Obtener el JSON desde Secret Manager
        secret_service = SecretManagerService()
        secret_value = secret_service.get_tenant_secret(
            tenant_id="global",
            secret_type=f"ga4-conn-{connection_id}"
        )
        
        if not secret_value:
            raise HTTPException(status_code=404, detail="No se encontró el Service Account para esta conexión.")
            
        sa_info = json.loads(secret_value)
        
        # 2. Autenticar con google-analytics-admin
        from google.oauth2 import service_account, credentials as oauth_credentials
        from google.analytics.admin import AnalyticsAdminServiceClient
        
        if sa_info.get("type") == "oauth_user":
            credentials = oauth_credentials.Credentials(
                token=None,
                refresh_token=sa_info.get("refresh_token"),
                token_uri=sa_info.get("token_uri"),
                client_id=sa_info.get("client_id"),
                client_secret=sa_info.get("client_secret")
            )
        else:
            credentials = service_account.Credentials.from_service_account_info(sa_info)
            
        client = AnalyticsAdminServiceClient(credentials=credentials)
        
        # 3. Listar cuentas y propiedades
        result = []
        account_summaries = client.list_account_summaries()
        for summary in account_summaries:
            account_data = {
                "account_id": summary.account, # ej: accounts/12345
                "account_name": summary.display_name,
                "properties": []
            }
            
            for prop_summary in summary.property_summaries:
                account_data["properties"].append({
                    "property_id": prop_summary.property, # ej: properties/12345
                    "property_name": prop_summary.display_name,
                    "industry_category": None # Prop summaries don't have industry category directly, but this is fine
                })
                
            if account_data["properties"]:
                result.append(account_data)
                
        return {"accounts": result}
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="El secreto almacenado no es un JSON válido.")
    except Exception as e:
        logger.error(f"Error al listar propiedades de GA4 para {connection_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error al consultar la API de Google Analytics: {str(e)}")

@router.get("/connections/ga4/callback")
async def oauth_callback(
    request: Request,
    state: str,
    code: str = None,
    error: str = None
):
    """
    Callback para el flujo de OAuth 2.0 (3-Legged).
    """
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:3000"
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    if host and (".a.run.app" in host or ".web.app" in host or "firebaseapp.com" in host or "llyc.global" in host):
        proto = "https"
        
    base_url = f"{proto}://{host}/media-impact" if "localhost:3000" not in host and "localhost:8080" not in host else f"http://localhost:3000/media-impact"
        
    if error:
        logger.error(f"Error en OAuth callback: {error}")
        return RedirectResponse(f"{base_url}/#admin")

    if not code:
        return RedirectResponse(f"{base_url}/#admin")
        
    try:
        tm = TokenManager()
        if not tm.db:
            raise Exception("No DB connection")
            
        doc_ref = tm.db.collection("oauth_states").document(state)
        doc = doc_ref.get()
        if not doc.exists:
            return RedirectResponse(f"{base_url}/#admin")
            
        state_data = doc.to_dict()
        client_config = state_data["client_config"]
        name = state_data["name"]
        redirect_uri = state_data["redirect_uri"]
        
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_config(
            client_config,
            scopes=['https://www.googleapis.com/auth/analytics.readonly']
        )
        flow.redirect_uri = redirect_uri
        
        # Restore the code verifier
        if "code_verifier" in state_data and state_data["code_verifier"]:
            flow.code_verifier = state_data["code_verifier"]
        
        # Build the full authorization response URL
        auth_response = str(request.url)
        if request.headers.get("x-forwarded-proto") == "https":
            auth_response = auth_response.replace("http://", "https://")
            
        import os
        if "localhost" in auth_response or "127.0.0.1" in auth_response:
            os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
        os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
            
        flow.fetch_token(authorization_response=auth_response)
        credentials = flow.credentials
        
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        connection_id = f"oauth-{timestamp}"
        
        final_creds = {
            "type": "oauth_user",
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri
        }
        
        secret_service = SecretManagerService()
        secret_saved = secret_service.save_tenant_secret(
            tenant_id="global",
            secret_type=f"ga4-conn-{connection_id}",
            secret_value=json.dumps(final_creds)
        )
        
        if not secret_saved:
            raise Exception("Error saving secret")
            
        connection_data = {
            "id": connection_id,
            "name": name,
            "client_email": "Usuario OAuth (3-Legged)",
            "created_at": datetime.utcnow().isoformat(),
            "type": "oauth_json"
        }
        tm.db.collection("ga4_connections").document(connection_id).set(connection_data)
        doc_ref.delete()
        
        return RedirectResponse(f"{base_url}/#admin")
        
    except Exception as e:
        logger.error(f"Error completando OAuth: {e}")
        return RedirectResponse(f"{base_url}/#admin")
