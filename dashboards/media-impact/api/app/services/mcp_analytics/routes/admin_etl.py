# backend/app/services/mcp_analytics/routes/admin_etl.py
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, BackgroundTasks
from pydantic import BaseModel, Field

from app.services.auth_utils import TokenManager
from app.services.mcp_analytics.secret_manager_service import SecretManagerService
from app.services.mcp_analytics.etl_service import MCPETLService
from app.services.mcp_analytics.ga_service import GAService
from app.services.mcp_analytics.adobe_service import AdobeAnalyticsService
from app.services.mcp_analytics.gcs_service import GCSService
from app.services.mcp_analytics.bigquery_service import BigQueryService

from app.services.mcp_analytics.routes.dependencies import get_current_admin

logger = logging.getLogger(__name__)
router = APIRouter()

# --- Pydantic Request Models ---

class TenantAdminRequest(BaseModel):
    tenant_id: str = Field(..., description="ID del tenant en minúsculas y sin espacios (ej: 'test')")
    tenant_name: str = Field(..., description="Nombre comercial visible (ej: 'LLYC España')")
    logo_url: str = Field(..., description="URL del logo en SVG/PNG")
    primary_color: str = Field(..., description="Color primario hexadecimal (ej: '#0070B0')")
    secondary_color: str = Field(..., description="Color secundario hexadecimal (ej: '#00A2E2')")
    font_family: str = Field(default="Open Sans, sans-serif", description="Familia tipográfica")
    support_email: str = Field(..., description="Email de soporte del cliente")
    authorized_emails: List[str] = Field(default=[], description="Lista de correos autorizados para este tenant")
    authorized_domains: List[str] = Field(default=[], description="Lista de dominios de correo corporativos autorizados")


class TenantSecretRequest(BaseModel):
    secret_type: str = Field(..., description="Tipo de secreto (ej: 'brandlight-key', 'peec-key')")
    secret_value: str = Field(..., description="Valor sensible de la API key")

class AdobeValidationRequest(BaseModel):
    client_id: str
    client_secret: str
    org_id: str

class GA4ValidationRequest(BaseModel):
    credentials_json: str

class ETLTriggerRequest(BaseModel):
    tenant_id: str = Field(..., description="ID del tenant a sincronizar (ej: 'test')")
    historical_backfill: bool = Field(default=False, description="Si es True, realiza un backfill histórico (ej. últimos 90 días). Si es False, es un incremento de 2 días.")

class PatchGapsRequest(BaseModel):
    gaps: List[Dict[str, str]] = Field(..., description="Lista de rangos de fechas a rellenar, ej: [{'start': '2026-06-01', 'end': '2026-06-05'}]")


# --- Helpers ---

def update_deployment_status(tenant_id: str, status: str, step: str, message: str):
    """
    Actualiza de forma atómica el estado del despliegue en curso de un cliente en Firestore,
    permitiendo al frontend auditar y pintar el estado de construcción en vivo.
    """
    try:
        tm = TokenManager()
        if tm.db:
            tm.db.collection("tenants").document(tenant_id).update({
                "deployment_status": {
                    "status": status,
                    "step": step,
                    "message": message,
                    "updated_at": datetime.utcnow().isoformat()
                }
            })
            logger.info(f"🔄 [DEPLOYMENT STATUS] Tenant '{tenant_id}' -> Status: {status} | Step: {step} | Msg: {message}")
    except Exception as e:
        logger.warning(f"No se pudo actualizar el estado de despliegue para '{tenant_id}': {e}")

def create_or_update_tenant_scheduler(tenant_id: str):
    """
    Crea o actualiza de forma programática un Job en Cloud Scheduler para el tenant
    a fin de ejecutar la ETL diaria a las 03:00 UTC.
    """
    try:
        from google.cloud import scheduler_v1
        client = scheduler_v1.CloudSchedulerClient()
        
        project_id = os.getenv("GCP_PROJECT_ID") or "llyc-ai-first-core"
        location_id = "us-central1"
        parent = f"projects/{project_id}/locations/{location_id}"
        
        job_id = f"mcp-analytics-{tenant_id}-etl-daily"
        job_name = f"{parent}/jobs/{job_id}"
        
        # URI de nuestro Cloud Run
        uri = f"https://llyc-intelligence-api-mz6ut5biaa-uc.a.run.app/api/v1/mcp-analytics/admin/etl/trigger"
        
        # Construir el job
        job = scheduler_v1.Job(
            name=job_name,
            description=f"Iniciador automático de la ETL diaria para el cliente MCP: {tenant_id}",
            http_target=scheduler_v1.HttpTarget(
                uri=uri,
                http_method=scheduler_v1.HttpMethod.POST,
                headers={"Content-Type": "application/json"},
                body=f'{{"tenant_id": "{tenant_id}"}}'.encode("utf-8")
            ),
            schedule="0 3 * * *",
            time_zone="UTC"
        )
        
        try:
            client.update_job(job=job)
            logger.info(f"✅ Job de Cloud Scheduler '{job_id}' actualizado con éxito.")
            update_deployment_status(tenant_id, "deploying", "Cloud Scheduler Configurado", f"Job '{job_id}' actualizado con éxito en Google Cloud.")
        except Exception:
            client.create_job(parent=parent, job=job)
            logger.info(f"✅ Job de Cloud Scheduler '{job_id}' creado con éxito.")
            update_deployment_status(tenant_id, "deploying", "Cloud Scheduler Configurado", f"Job '{job_id}' creado con éxito en Google Cloud.")
            
    except Exception as e:
        logger.warning(f"No se pudo automatizar Cloud Scheduler para '{tenant_id}': {e}")
        update_deployment_status(tenant_id, "deploying", "Cloud Scheduler Omitido", f"No se pudo configurar Cloud Scheduler: {e}. Continuando...")

async def run_historical_backfill_task(tenant_id: str):
    """
    Ejecuta un backfill histórico (últimos 90 días) para el tenant de forma asíncrona
    en segundo plano a fin de poblar las tablas analíticas en BigQuery.
    """
    try:
        update_deployment_status(tenant_id, "deploying", "Ejecutando Ingesta de Datos (90 días)", "Conectando en vivo con las APIs configuradas y poblando BigQuery de forma secuencial...")
        logger.info(f"🚀 Iniciando Backfill Histórico asíncrono (90 días) para '{tenant_id}'...")
        
        sms = SecretManagerService()
        credentials = {}
        secret_types = ["brandlight-key", "peec-key", "ga4-creds", "adobe-creds"]
        for st in secret_types:
            val = sms.get_tenant_secret(tenant_id, st)
            if val:
                credentials[st] = val
                
        date_from = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
        date_to = datetime.utcnow().strftime("%Y-%m-%d")
        
        # Callback para barra de progreso en tiempo real tipo tqdm
        def on_progress_callback(step: str, message: str):
            update_deployment_status(tenant_id, "deploying", step, message)
            
        etl = MCPETLService(tenant_id=tenant_id)
        await etl.run_full_sync(
            credentials=credentials,
            date_from=date_from,
            date_to=date_to,
            on_progress=on_progress_callback
        )
        logger.info(f"🏁 Backfill Histórico completado con éxito para '{tenant_id}'.")
        update_deployment_status(tenant_id, "success", "Despliegue Completado con Éxito", "La infraestructura y el histórico de 90 días de Adobe/GA4 se cargaron perfectamente en BigQuery.")
    except Exception as e:
        logger.error(f"Error en el Backfill Histórico asíncrono de '{tenant_id}': {e}")
        update_deployment_status(tenant_id, "failed", "Error en Despliegue", f"Falló la ingesta de datos del histórico: {e}")


# --- Endpoints ---

@router.get("/admin/tenants", response_model=List[Dict[str, Any]])
async def list_tenants_admin(user_email: str = Depends(get_current_admin)):
    """
    Lista todos los tenants creados en Firestore (Solo Superadmin LLYC).
    Soporta backfill automático y cacheado de configuración de secretos de GCP Secret Manager.
    """
    try:
        tm = TokenManager()
        if not tm.db:
            return []
            
        tenants_ref = tm.db.collection("tenants")
        docs = tenants_ref.stream()
        tenants = []
        sms = SecretManagerService()
        
        for doc in docs:
            tdata = doc.to_dict()
            tenant_id = tdata.get("tenant_id")
            
            # Inicializar o recuperar cacheado de configured_secrets
            if "configured_secrets" not in tdata or not isinstance(tdata["configured_secrets"], dict):
                tdata["configured_secrets"] = {
                    "brandlight-key": False,
                    "peec-key": False,
                    "ga4-creds": False,
                    "adobe-creds": False
                }
                
                # Intentar escanear en GCP Secret Manager de forma progresiva si está disponible
                if sms.client:
                    for st in ["brandlight-key", "peec-key", "ga4-creds", "adobe-creds"]:
                        try:
                            secret_id = f"llyc-mcp-{tenant_id}-{st}".lower().strip()
                            secret_path = f"projects/{sms.project_id}/secrets/{secret_id}"
                            sms.client.get_secret(request={"name": secret_path})
                            tdata["configured_secrets"][st] = True
                        except Exception:
                            pass
                    
                    # Guardar el caché en Firestore para acelerar consultas futuras
                    try:
                        tm.db.collection("tenants").document(tenant_id).update({
                            "configured_secrets": tdata["configured_secrets"]
                        })
                    except Exception as fe:
                        logger.warning(f"No se pudo cachear configured_secrets para {tenant_id} en Firestore: {fe}")
            else:
                # Asegurar de que tenga todas las llaves esperadas para evitar errores en frontend
                current_secrets = tdata["configured_secrets"]
                for st in ["brandlight-key", "peec-key", "ga4-creds", "adobe-creds"]:
                    if st not in current_secrets:
                        current_secrets[st] = False
                tdata["configured_secrets"] = current_secrets
                
            # Inicializar de forma segura listas ACL si no existen
            if "authorized_emails" not in tdata or not isinstance(tdata["authorized_emails"], list):
                tdata["authorized_emails"] = []
            if "authorized_domains" not in tdata or not isinstance(tdata["authorized_domains"], list):
                tdata["authorized_domains"] = []
                
            tenants.append(tdata)

            
        return tenants
    except Exception as e:
        logger.error(f"Error al listar tenants en admin: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/tenants", response_model=Dict[str, Any])
async def create_or_update_tenant_admin(
    tenant_req: TenantAdminRequest,
    user_email: str = Depends(get_current_admin)
):
    """
    Crea o actualiza la configuración de marca de un tenant en Firestore (Solo Superadmin LLYC).
    """
    try:
        tm = TokenManager()
        tenant_id = tenant_req.tenant_id.lower().strip()
        
        tenant_data = {
            "tenant_id": tenant_id,
            "tenant_name": tenant_req.tenant_name,
            "logo_url": tenant_req.logo_url,
            "primary_color": tenant_req.primary_color,
            "secondary_color": tenant_req.secondary_color,
            "font_family": tenant_req.font_family,
            "support_email": tenant_req.support_email,
            "authorized_emails": [e.lower().strip() for e in tenant_req.authorized_emails if e.strip()],
            "authorized_domains": [d.lower().strip() for d in tenant_req.authorized_domains if d.strip()],
            "updated_by": user_email,
            "updated_at": datetime.utcnow().isoformat()
        }

        
        # Mantener secrets configurados si ya existen o inicializar de forma limpia
        if tm.db:
            existing = tm.db.collection("tenants").document(tenant_id).get()
            if existing.exists:
                existing_data = existing.to_dict()
                tenant_data["configured_secrets"] = existing_data.get("configured_secrets", {
                    "brandlight-key": False,
                    "peec-key": False,
                    "ga4-creds": False,
                    "adobe-creds": False
                })
            else:
                tenant_data["configured_secrets"] = {
                    "brandlight-key": False,
                    "peec-key": False,
                    "ga4-creds": False,
                    "adobe-creds": False
                }
            
            tm.db.collection("tenants").document(tenant_id).set(tenant_data, merge=True)
            logger.info(f"Tenant '{tenant_id}' guardado con éxito en Firestore por {user_email}")
        else:
            logger.warning("Firestore no disponible, simulando guardado de Tenant local.")
            tenant_data["configured_secrets"] = {
                "brandlight-key": False,
                "peec-key": False,
                "ga4-creds": False,
                "adobe-creds": False
            }
            
        return {"status": "success", "message": f"Tenant '{tenant_id}' guardado con éxito.", "data": tenant_data}
        
    except Exception as e:
        logger.error(f"Error al guardar tenant: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/tenants/{tenant_id}/secrets", response_model=Dict[str, Any])
async def save_tenant_secret_admin(
    tenant_id: str,
    secret_req: TenantSecretRequest,
    background_tasks: BackgroundTasks,
    user_email: str = Depends(get_current_admin)
):
    """
    Guarda y encripta una clave sensible de un cliente (ej: Brandlight API Key)
    directamente en GCP Secret Manager (Solo Superadmin LLYC) y actualiza la metadata en Firestore.
    Desencadena de forma automatizada el Cloud Scheduler del cliente y un Backfill histórico de 90 días en segundo plano.
    """
    try:
        sms = SecretManagerService()

        tenant_id_clean = tenant_id.lower().strip()
        secret_type_clean = secret_req.secret_type.lower().strip()

        # Inicializar estado de despliegue en Firestore
        update_deployment_status(tenant_id_clean, "deploying", "Iniciando Despliegue", f"Guardando clave '{secret_type_clean}' en GCP Secret Manager...")

        # 1. Guardar secreto en GCP Secret Manager
        success = sms.save_tenant_secret(
            tenant_id=tenant_id_clean,
            secret_type=secret_type_clean,
            secret_value=secret_req.secret_value
        )

        if not success:
            raise Exception("No se pudo persistir el secreto en GCP Secret Manager.")

        # 2. Actualizar de forma automatizada en Firestore que este secreto ya está configurado (cacheado de metadata)
        tm = TokenManager()
        if tm.db:
            tenant_ref = tm.db.collection("tenants").document(tenant_id_clean)
            tenant_doc = tenant_ref.get()
            if tenant_doc.exists:
                tenant_data = tenant_doc.to_dict()
                configured_secrets = tenant_data.get("configured_secrets", {})
                if not isinstance(configured_secrets, dict):
                    configured_secrets = {}
                configured_secrets[secret_type_clean] = True
                tenant_ref.update({"configured_secrets": configured_secrets})
                logger.info(f"Metadata de secreto '{secret_type_clean}' actualizada en Firestore para '{tenant_id_clean}'.")

        # 3. Automatizar Creación/Actualización de Cloud Scheduler para el Tenant
        create_or_update_tenant_scheduler(tenant_id_clean)

        # 4. Programar tarea de Backfill Histórico asíncrono (90 días) en segundo plano
        background_tasks.add_task(run_historical_backfill_task, tenant_id_clean)

        return {
            "status": "success",
            "message": f"Secreto '{secret_type_clean}' guardado con éxito. Se programó la automatización de Cloud Scheduler y el backfill histórico en segundo plano."
        }

    except Exception as e:
        logger.error(f"Error al guardar secreto de tenant en admin: {e}")
        update_deployment_status(tenant_id_clean, "failed", "Error en Despliegue", f"No se pudo guardar la clave: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/tenants/validate-ga4-credentials", response_model=Dict[str, Any])
async def validate_ga4_credentials_admin(
    req: GA4ValidationRequest,
    user_email: str = Depends(get_current_admin)
):
    """
    Valida las credenciales JSON de GA4 (OAuth o Service Account) y retorna la lista de Cuentas y Propiedades disponibles.
    """
    try:
        etl = MCPETLService(tenant_id="temp")
        parsed_creds = etl._parse_credentials("ga4-creds", req.credentials_json)
        
        # Instanciar el servicio analítico de Google
        ga_service = GAService(credentials=parsed_creds)
        
        # 1. Recuperar cuentas de GA4 usando ga_service
        accounts = await ga_service.list_accounts()
        accounts_list = [{"id": acc.account_id, "name": acc.display_name} for acc in accounts]
        
        # 2. Recuperar propiedades de la primera cuenta por defecto
        properties_list = []
        if accounts_list:
            first_acc_id = accounts_list[0]["id"]
            properties = await ga_service.list_properties(account_id=first_acc_id)
            properties_list = [{"id": prop.property_id, "name": prop.display_name} for prop in properties]
            
        return {
            "status": "success",
            "accounts": accounts_list,
            "properties": properties_list
        }
    except Exception as e:
        logger.error(f"Error al validar credenciales de GA4 en admin: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/admin/tenants/validate-ga4-properties", response_model=Dict[str, Any])
async def validate_ga4_properties_admin(
    credentials_json: str,
    account_id: str,
    user_email: str = Depends(get_current_admin)
):
    """
    Retorna la lista de Propiedades de GA4 disponibles para una cuenta de Google específica.
    """
    try:
        etl = MCPETLService(tenant_id="temp")
        parsed_creds = etl._parse_credentials("ga4-creds", credentials_json)
        
        ga_service = GAService(credentials=parsed_creds)
        properties = await ga_service.list_properties(account_id=account_id)
        properties_list = [{"id": prop.property_id, "name": prop.display_name} for prop in properties]
        return {
            "status": "success",
            "properties": properties_list
        }
    except Exception as e:
        logger.error(f"Error al listar propiedades de GA4 en validación: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/admin/tenants/validate-adobe-credentials", response_model=Dict[str, Any])
async def validate_adobe_credentials_admin(
    req: AdobeValidationRequest,
    user_email: str = Depends(get_current_admin)
):
    """
    Valida las credenciales ingresadas de Adobe Analytics conectando con el Discovery API
    y retorna la lista de Compañías, Report Suites y Segmentos disponibles para su selección.
    """
    try:
        # Instanciar el servicio con credenciales dinámicas temporales
        service = AdobeAnalyticsService(credentials={
            "client_id": req.client_id,
            "client_secret": req.client_secret,
            "org_id": req.org_id
        })
        
        # 1. Recuperar cuentas/compañías
        accounts = await service.list_accounts()
        companies_list = [{"id": acc.account_id, "name": acc.display_name} for acc in accounts]
        
        # 2. Recuperar propiedades/report suites de la primera compañía por defecto
        suites_list = []
        segments_list = []
        if companies_list:
            first_company_id = companies_list[0]["id"]
            properties = await service.list_properties(account_id=first_company_id)
            suites_list = [{"id": prop.property_id, "name": prop.display_name} for prop in properties]
            
            # 3. Recuperar segmentos de la primera propiedad por defecto
            if suites_list:
                first_suite_id = suites_list[0]["id"]
                segments = await service.list_segments(report_suite_id=first_suite_id)
                segments_list = [{"id": seg.get("id"), "name": seg.get("name")} for seg in segments]
            
        return {
            "status": "success",
            "companies": companies_list,
            "suites": suites_list,
            "segments": segments_list
        }
    except Exception as e:
        logger.error(f"Error al validar credenciales de Adobe en admin: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/admin/tenants/validate-adobe-properties", response_model=Dict[str, Any])
async def validate_adobe_properties_admin(
    client_id: str,
    client_secret: str,
    org_id: str,
    company_id: str,
    user_email: str = Depends(get_current_admin)
):
    """
    Retorna la lista de Report Suites disponibles para una compañía específica de Adobe.
    """
    try:
        service = AdobeAnalyticsService(credentials={
            "client_id": client_id,
            "client_secret": client_secret,
            "org_id": org_id,
            "company_id": company_id
        })
        properties = await service.list_properties(account_id=company_id)
        suites_list = [{"id": prop.property_id, "name": prop.display_name} for prop in properties]
        return {
            "status": "success",
            "suites": suites_list
        }
    except Exception as e:
        logger.error(f"Error al listar propiedades de Adobe en validación: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/admin/tenants/validate-adobe-segments", response_model=Dict[str, Any])
async def validate_adobe_segments_admin(
    client_id: str,
    client_secret: str,
    org_id: str,
    company_id: str,
    property_id: str,
    user_email: str = Depends(get_current_admin)
):
    """
    Retorna la lista de Segmentos disponibles para un Report Suite específico de Adobe.
    """
    try:
        service = AdobeAnalyticsService(credentials={
            "client_id": client_id,
            "client_secret": client_secret,
            "org_id": org_id,
            "company_id": company_id
        })
        segments = await service.list_segments(report_suite_id=property_id)
        segments_list = [{"id": seg.get("id"), "name": seg.get("name")} for seg in segments]
        return {
            "status": "success",
            "segments": segments_list
        }
    except Exception as e:
        logger.error(f"Error al listar segmentos de Adobe en validación: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/admin/tenants/{tenant_id}/redeploy-etl", response_model=Dict[str, Any])
async def redeploy_tenant_etl_admin(
    tenant_id: str,
    background_tasks: BackgroundTasks,
    user_email: str = Depends(get_current_admin)
):
    """
    Fuerza el re-despliegue de la infraestructura ETL de un cliente (Solo Superadmin LLYC).
    Esto re-crea el job en Cloud Scheduler y encola un nuevo Backfill histórico de 90 días en segundo plano.
    """
    try:
        tenant_id_clean = tenant_id.lower().strip()

        # Inicializar estado de despliegue en Firestore
        update_deployment_status(tenant_id_clean, "deploying", "Iniciando re-despliegue", "Fuerza el re-despliegue de Scheduler y encola un Backfill histórico de 90 días en segundo plano...")

        # 1. Re-crear Cloud Scheduler
        create_or_update_tenant_scheduler(tenant_id_clean)

        # 2. Re-lanzar backfill histórico asíncrono
        background_tasks.add_task(run_historical_backfill_task, tenant_id_clean)

        return {
            "status": "success",
            "message": f"Se re-desplegó con éxito el Scheduler y se encoló un nuevo Backfill de 90 días en segundo plano para '{tenant_id_clean}'."
        }
    except Exception as e:
        logger.error(f"Error al re-desplegar ETL para {tenant_id}: {e}")
        update_deployment_status(tenant_id_clean, "failed", "Error en Despliegue", f"No se pudo re-desplegar: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/tenants/{tenant_id}/logo", response_model=Dict[str, Any])
async def upload_tenant_logo_admin(
    tenant_id: str,
    file: UploadFile = File(...),
    user_email: str = Depends(get_current_admin)
):
    """
    Sube un archivo de logotipo (SVG o PNG) corporativo de un cliente directamente
    a un bucket de Google Cloud Storage (GCS) y devuelve su URL CDN pública (Solo Superadmin LLYC).
    """
    try:
        gcs = GCSService()
        
        tenant_id_clean = tenant_id.lower().strip()
        content_type = file.content_type or "image/svg+xml"
        
        # Validar tipo de archivo permitido (SVG o PNG)
        if "svg" not in content_type and "png" not in content_type:
            raise HTTPException(
                status_code=400,
                detail="Formato de archivo no permitido: Sólo se admiten archivos SVG (.svg) o PNG (.png)"
            )
            
        file_content = await file.read()
        
        # Subir el logotipo a Google Cloud Storage
        public_url = gcs.upload_logo(
            tenant_id=tenant_id_clean,
            file_content=file_content,
            content_type=content_type
        )
        
        if not public_url:
            raise Exception("Error al subir el logotipo a Google Cloud Storage.")
            
        # Si Firestore está disponible, actualizar de forma automática el logo_url del tenant
        tm = TokenManager()
        if tm.db:
            tm.db.collection("tenants").document(tenant_id_clean).update({"logo_url": public_url})
            logger.info(f"Firestore actualizado con la nueva logo_url de GCS para el tenant '{tenant_id_clean}'.")
            
        return {
            "status": "success",
            "message": f"Logotipo subido y enlazado con éxito para el tenant '{tenant_id_clean}'.",
            "logo_url": public_url
        }
        
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error al subir logotipo de tenant en admin: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/etl/trigger", response_model=Dict[str, Any])
async def trigger_tenant_etl_admin(
    req: ETLTriggerRequest,
    user_email: str = Depends(get_current_admin)
):
    """
    Desencadena de manera manual o programada (Cloud Scheduler) la ingesta ETL de un cliente.
    Descarga el histórico, limpia duplicados y lo inserta de manera limpia en BigQuery.
    """
    try:
        tenant_id = req.tenant_id.lower().strip()
        
        # 1. Recuperar todas las credenciales activas del tenant desde Secret Manager
        sms = SecretManagerService()
        
        credentials = {}
        secret_types = ["brandlight-key", "peec-key", "ga4-creds", "adobe-creds"]
        for st in secret_types:
            val = sms.get_tenant_secret(tenant_id, st)
            if val:
                credentials[st] = val
                
        # 2. Definir ventana de tiempo (backfill histórico de 90 días vs incremento diario de 2 días)
        if req.historical_backfill:
            date_from = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
        else:
            date_from = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
            
        date_to = datetime.utcnow().strftime("%Y-%m-%d")
        
        # 3. Lanzar la ETL de forma asíncrona
        etl = MCPETLService(tenant_id=tenant_id)
        
        # Ejecutar sincronización
        sync_result = await etl.run_full_sync(
            credentials=credentials,
            date_from=date_from,
            date_to=date_to
        )
        
        return {
            "status": "success",
            "message": f"ETL completada para el tenant '{tenant_id}'.",
            "sync_details": sync_result
        }
        
    except Exception as e:
        logger.error(f"Error al desencadenar ETL en admin: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/etl/history", response_model=List[Dict[str, Any]])
async def list_etl_history_admin(user_email: str = Depends(get_current_admin)):
    """
    Recupera el historial de ejecuciones de ETL para todos los inquilinos desde Firestore (Solo Superadmin LLYC).
    """
    try:
        tm = TokenManager()
        if not tm.db:
            return []
            
        runs_ref = tm.db.collection("etl_runs")
        # Listar últimas 50 corridas ordenadas por fecha descendente
        docs = runs_ref.order_by("timestamp", direction="DESCENDING").limit(50).stream()
        runs = []
        for doc in docs:
            runs.append(doc.to_dict())
            
        return runs
    except Exception as e:
        logger.error(f"Error al listar historial de ETL: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/etl/alerts", response_model=List[Dict[str, Any]])
async def list_etl_alerts_admin(user_email: str = Depends(get_current_admin)):
    """
    Lista las alertas activas de fallos en el proceso ETL desde Firestore (Solo Superadmin LLYC).
    """
    try:
        tm = TokenManager()
        if not tm.db:
            return []
            
        alerts_ref = tm.db.collection("etl_alerts")
        # Filtrar únicamente alertas activas (y ordenar localmente para evitar requerir índices compuestos en Firestore)
        docs = alerts_ref.where("status", "==", "active").stream()
        alerts = []
        for doc in docs:
            alerts.append(doc.to_dict())

        # Ordenar localmente por fecha descendente
        alerts.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return alerts
    except Exception as e:
        logger.error(f"Error al listar alertas de ETL: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/etl/alerts/{alert_id}/dismiss", response_model=Dict[str, Any])
async def dismiss_etl_alert_admin(
    alert_id: str,
    user_email: str = Depends(get_current_admin)
):
    """
    Marca una alerta de ETL como resuelta/descartada en Firestore (Solo Superadmin LLYC).
    """
    try:
        tm = TokenManager()
        if tm.db:
            alert_ref = tm.db.collection("etl_alerts").document(alert_id)
            alert_ref.update({
                "status": "dismissed",
                "resolved_by": user_email,
                "resolved_at": datetime.utcnow().isoformat()
            })
            logger.info(f"Alerta '{alert_id}' marcada como resuelta por {user_email}")
            return {"status": "success", "message": f"Alerta '{alert_id}' descartada de forma exitosa."}
        else:
            raise Exception("Firestore no está disponible.")
    except Exception as e:
        logger.error(f"Error al descartar alerta de ETL: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/tenants/{tenant_id}/data-gaps", response_model=Dict[str, Any])
async def detect_tenant_data_gaps_admin(
    tenant_id: str,
    user_email: str = Depends(get_current_admin)
):
    """
    Detecta huecos (fechas faltantes sin datos) en las tablas de BigQuery para un tenant (Solo Superadmin LLYC).
    """
    try:
        bqs = BigQueryService()
        
        tenant_id_clean = tenant_id.lower().strip()
        gaps_result = bqs.get_data_gaps(tenant_id=tenant_id_clean)
        
        return gaps_result
    except Exception as e:
        logger.error(f"Error al detectar huecos para {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/tenants/{tenant_id}/patch", response_model=Dict[str, Any])
async def patch_tenant_data_gaps_admin(
    tenant_id: str,
    req: PatchGapsRequest,
    user_email: str = Depends(get_current_admin)
):
    """
    Lanza el Patcher de datos para rellenar (sincronizar) de forma masiva los huecos detectados
    en BigQuery de forma limpia y sin duplicados (Solo Superadmin LLYC).
    """
    try:
        tenant_id_clean = tenant_id.lower().strip()
        
        # 1. Recuperar todas las credenciales activas del tenant desde Secret Manager
        sms = SecretManagerService()
        
        credentials = {}
        secret_types = ["brandlight-key", "peec-key", "ga4-creds", "adobe-creds"]
        for st in secret_types:
            val = sms.get_tenant_secret(tenant_id_clean, st)
            if val:
                credentials[st] = val
                
        # 2. Instanciar el coordinador de ETL
        etl = MCPETLService(tenant_id=tenant_id_clean)
        
        patch_results = []
        
        # 3. Iterar por cada hueco/rango de fechas solicitado y sincronizarlo de forma limpia (idempotente)
        for gap in req.gaps:
            start_date = gap.get("start")
            end_date = gap.get("end")
            
            if not start_date or not end_date:
                continue
                
            logger.info(f"🛠️ Lanzando Patcher de datos para '{tenant_id_clean}' en el periodo: {start_date} a {end_date}...")
            
            sync_res = await etl.run_full_sync(
                credentials=credentials,
                date_from=start_date,
                date_to=end_date
            )
            
            patch_results.append({
                "range": f"{start_date} a {end_date}",
                "status": sync_res.get("status"),
                "records_processed": sync_res.get("records_processed", 0)
            })
            
        return {
            "status": "success",
            "message": f"Proceso de parchado (Patching) finalizado con éxito para '{tenant_id_clean}'.",
            "patched_ranges": patch_results
        }
        
    except Exception as e:
        logger.error(f"Error al parchar datos del tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
