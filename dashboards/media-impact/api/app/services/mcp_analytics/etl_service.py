# backend/app/services/mcp_analytics/etl_service.py

import os
import logging
import asyncio
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime, timedelta

from app.services.mcp_analytics.bigquery_service import BigQueryService
from app.services.mcp_analytics.brandlight_service import BrandlightService
from app.services.mcp_analytics.peec_service import PeecService
from app.services.mcp_analytics.ga_service import GAService
from app.services.mcp_analytics.adobe_service import AdobeAnalyticsService
from app.models.mcp_analytics.core_models import RunReportRequest

logger = logging.getLogger(__name__)

class MCPETLService:
    """
    Servicio de Coordinación ETL (Extract, Transform, Load) para el ecosistema analítico de LLYC.
    Extrae datos de GA4, Adobe, Brandlight y Peec.ai, los unifica y los carga en Google BigQuery.
    """

    def __init__(self, tenant_id: str, project_id: Optional[str] = None):
        self.tenant_id = tenant_id.lower().strip()
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        self.bq_service = BigQueryService(project_id=self.project_id)

    def _parse_credentials(self, secret_type: str, val: str) -> Any:
        """
        Interpreta el valor de un secreto según su tipo para retornar un diccionario limpio
        o el objeto de Credenciales OAuth/ServiceAccount correspondiente de Google.
        """
        if not val:
            return None
            
        import json
        is_json = False
        parsed_val = None
        if isinstance(val, str) and val.strip().startswith("{") and val.strip().endswith("}"):
            try:
                parsed_val = json.loads(val)
                is_json = True
            except Exception:
                pass
                
        if secret_type == "ga4-creds":
            from google.oauth2.credentials import Credentials
            from app.core.config import settings
            
            if is_json:
                if parsed_val.get("type") == "service_account" or "private_key" in parsed_val:
                    from google.oauth2 import service_account
                    return service_account.Credentials.from_service_account_info(
                        parsed_val,
                        scopes=parsed_val.get("scopes", ["https://www.googleapis.com/auth/analytics.readonly"])
                    )
                else:
                    return Credentials(
                        token=parsed_val.get("access_token") or parsed_val.get("accessToken"),
                        refresh_token=parsed_val.get("refresh_token") or parsed_val.get("refreshToken"),
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=parsed_val.get("client_id") or settings.GOOGLE_CLIENT_ID,
                        client_secret=parsed_val.get("client_secret") or settings.GOOGLE_CLIENT_SECRET,
                        scopes=parsed_val.get("scopes", ["https://www.googleapis.com/auth/analytics.readonly"])
                    )
            elif isinstance(val, dict):
                return Credentials(
                    token=val.get("access_token") or val.get("accessToken"),
                    refresh_token=val.get("refresh_token") or val.get("refreshToken"),
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=val.get("client_id") or settings.GOOGLE_CLIENT_ID,
                    client_secret=val.get("client_secret") or settings.GOOGLE_CLIENT_SECRET,
                    scopes=val.get("scopes", ["https://www.googleapis.com/auth/analytics.readonly"])
                )
            else:
                from google.oauth2.credentials import Credentials
                from app.core.config import settings
                return Credentials(
                    token=val,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=settings.GOOGLE_CLIENT_ID,
                    client_secret=settings.GOOGLE_CLIENT_SECRET,
                    scopes=["https://www.googleapis.com/auth/analytics.readonly"]
                )
                
        elif secret_type == "adobe-creds":
            if is_json:
                return parsed_val
            elif isinstance(val, dict):
                return val
            else:
                return {"client_secret": val}
                
        elif secret_type == "peec-key":
            if is_json:
                return parsed_val
            elif isinstance(val, dict):
                return val
            else:
                return {"api_key": val}
                
        elif secret_type == "brandlight-key":
            if is_json:
                return parsed_val
            elif isinstance(val, dict):
                return val
            else:
                return {"api_key": val}
                
        return val

    def _clean_date_format(self, date_val: str) -> str:
        """
        Limpia y estandariza cualquier formato de fecha a YYYY-MM-DD para BigQuery.
        Ejemplos: 'Jun 23, 2026' -> '2026-06-23', '20260623' -> '2026-06-23'.
        """
        if not date_val:
            return datetime.utcnow().strftime("%Y-%m-%d")
        date_val = str(date_val).strip()
        import re
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_val):
            return date_val
        try:
            from dateutil import parser as date_parser
            dt = date_parser.parse(date_val)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
        # Fallback manual para YYYYMMDD o formatos sin delimitadores
        clean = re.sub(r"[^0-9]", "", date_val)
        if len(clean) == 8:
            return f"{clean[:4]}-{clean[4:6]}-{clean[6:]}"
        return date_val

    async def run_full_sync(self, credentials: Dict[str, Any], date_from: str, date_to: str, on_progress: Optional[Callable[[str, str], Any]] = None) -> Dict[str, Any]:
        """
        Ejecuta un ciclo completo de sincronización de datos para el tenant de origen a fin
        de poblar las tablas analíticas en BigQuery.
        """
        logger.info(f"🔄 Iniciando ciclo de ETL unificado para el tenant '{self.tenant_id}' (Rango: {date_from} a {date_to})...")
        
        # 1. Asegurar que las tablas de BigQuery existan en el dataset 'media_impact_data'
        tables_ready = self.bq_service.create_dataset_and_tables()
        if not tables_ready:
            return {"status": "error", "message": "Fallo al inicializar las tablas en Google BigQuery."}

        results = {
            "ga4": "skipped",
            "adobe": "skipped",
            "peec": "skipped",
            "brandlight": "skipped"
        }

        # ==========================================
        # 📊 EXTRACT & TRANSFORM: GA4 & Adobe Analytics
        # ==========================================
        traffic_rows = []

        # GA4 Sincronización
        ga4_creds_raw = credentials.get("ga4-creds")
        if ga4_creds_raw:
            if on_progress:
                on_progress("Ejecutando Ingesta (Google Analytics 4)", "Descargando e insertando tráfico general de GA4 directamente en BigQuery...")
            try:
                parsed_creds = self._parse_credentials("ga4-creds", ga4_creds_raw)
                ga_service = GAService(credentials=parsed_creds)
                req = RunReportRequest(
                    property_id="properties/default",
                    date_ranges=[{"start_date": date_from, "end_date": date_to}],
                    dimensions=["date", "source", "medium"],
                    metrics=["activeUsers", "sessions", "conversions"]
                )
                res = await ga_service.run_report(req)
                ga4_rows = []
                for r in res.rows:
                    ga4_rows.append({
                        "tenant_id": self.tenant_id,
                        "date": self._clean_date_format(r.get("date")),
                        "source": r.get("source"),
                        "medium": r.get("medium"),
                        "total_sessions": int(float(r.get("sessions", 0))),
                        "ai_referred_sessions": 0,
                        "ai_inferred_sessions": 0,
                        "engagement_score": float(r.get("conversions", 0)),
                        "company_id": "ga4-account",
                        "property_id": "properties/default",
                        "segment_id": "all-users"
                    })
                if ga4_rows:
                    logger.info(f"📤 [ETL ESCALONADA] Cargando {len(ga4_rows)} filas de GA4 directamente en BigQuery...")
                    self.bq_service.delete_existing_records("fact_traffic_evolution", self.tenant_id, date_from, date_to, segment_id="all-users")
                    self.bq_service.insert_rows("fact_traffic_evolution", ga4_rows)
                    traffic_rows.extend(ga4_rows)
                results["ga4"] = f"success ({len(res.rows)} filas)"
            except Exception as e:
                logger.error(f"Error en extracción de GA4: {e}")
                results["ga4"] = f"error: {str(e)}"

        # Adobe Analytics Sincronización
        adobe_creds_raw = credentials.get("adobe-creds")
        if adobe_creds_raw:
            try:
                parsed_creds = self._parse_credentials("adobe-creds", adobe_creds_raw)
                adobe_service = AdobeAnalyticsService(credentials=parsed_creds)
                
                chosen_company = parsed_creds.get("company_id") or "adobe-company-default"
                chosen_property = parsed_creds.get("property_id") or "default"
                
                logger.info(f"Conectando en vivo con la API de Adobe Analytics para el tenant '{self.tenant_id}' (Suite: {chosen_property})...")
                
                # 1. Obtener todos los segmentos disponibles para esta Report Suite
                segments = []
                try:
                    segments = await adobe_service.list_segments(report_suite_id=chosen_property)
                    logger.info(f"Se obtuvieron {len(segments)} segmentos disponibles para '{chosen_property}'.")
                except Exception as se:
                    logger.warning(f"No se pudieron cargar segmentos para '{chosen_property}' durante la ingesta: {se}")
                
                # 2. Configurar la lista de bucles de segmentos (Tráfico general + cada segmento)
                segment_loops = [{"id": "all-users", "name": "Todos los usuarios"}]
                if segments:
                    segment_loops.extend([{"id": s["id"], "name": s["name"]} for s in segments])
                
                total_segments = len(segment_loops)
                logger.info(f"Iniciando ingesta analítica segmentada para {total_segments} variantes...")
                
                actual_rows = []
                for idx, seg in enumerate(segment_loops):
                    seg_id = seg["id"]
                    seg_name = seg["name"]
                    
                    progress_msg = f"Segmento {idx + 1} de {total_segments}: \"{seg_name}\""
                    logger.info(f"Ejecutando ETL Adobe para {progress_msg} ({seg_id})...")
                    
                    if on_progress:
                        on_progress("Ejecutando Ingesta (Adobe Analytics)", f"Descargando e insertando {progress_msg}...")

                    # Espacio de respiro proactivo (1.5 segundos) entre peticiones de segmentos
                    await asyncio.sleep(1.5)

                    # 1. Calcular ratios de IA en vivo para este segmento para distribuirlos proporcionalmente de forma diaria
                    ai_referred_ratio = 0.0
                    ai_inferred_ratio = 0.0
                    try:
                        logger.info(f"Analizando impacto IA para segmento '{seg_name}' ({seg_id})...")
                        res_ia = await adobe_service.analyze_traffic_ia(
                            property_id=chosen_property,
                            start_date=date_from,
                            end_date=date_to,
                            segment_id=seg_id if seg_id != "all-users" else None
                        )
                        total_sess_ia = float(res_ia.get("total_sessions", 0))
                        if total_sess_ia > 0:
                            known_ai_sess = sum(float(item.get("sessions", 0)) for item in res_ia.get("battle_of_ais", []))
                            inferred_ai_sess = float(res_ia.get("inferred_traffic", {}).get("total_sessions", 0))
                            
                            ai_referred_ratio = known_ai_sess / total_sess_ia
                            ai_inferred_ratio = inferred_ai_sess / total_sess_ia
                            logger.info(f"Ratios IA calculados para '{seg_name}': referred={ai_referred_ratio:.6f}, inferred={ai_inferred_ratio:.6f}")
                    except Exception as eia:
                        logger.warning(f"No se pudieron calcular ratios de tráfico IA para '{seg_name}': {eia}")

                    # Crear petición estructurada de reporte filtrada por este segmento
                    req = RunReportRequest(
                        property_id=chosen_property,
                        date_ranges=[{"start_date": date_from, "end_date": date_to}],
                        dimensions=["date"],
                        metrics=["activeUsers", "sessions", "conversions"],
                        segment_id=seg_id if seg_id != "all-users" else None
                    )
                    
                    try:
                        res = await adobe_service.run_report(req)
                        segment_rows = []
                        for r in res.rows:
                            raw_date = r.get("date")
                            date_str = self._clean_date_format(raw_date)
                            
                            total_sessions_val = int(float(r.get("sessions", 0)))
                            ai_referred_val = round(total_sessions_val * ai_referred_ratio)
                            ai_inferred_val = round(total_sessions_val * ai_inferred_ratio)
                            
                            # Asegurar de forma proactiva que la suma de IA no supere el total diario
                            if ai_referred_val + ai_inferred_val > total_sessions_val:
                                ai_referred_val = int(total_sessions_val * ai_referred_ratio)
                                ai_inferred_val = max(0, total_sessions_val - ai_referred_val)
                                
                            segment_rows.append({
                                "tenant_id": self.tenant_id,
                                "date": date_str,
                                "source": "adobe-analytics",
                                "medium": "organic-search",
                                "total_sessions": total_sessions_val,
                                "ai_referred_sessions": ai_referred_val,
                                "ai_inferred_sessions": ai_inferred_val,
                                "engagement_score": float(r.get("conversions", 0)),
                                "company_id": chosen_company,
                                "property_id": chosen_property,
                                "segment_id": seg_id
                            })
                            
                        if segment_rows:
                            logger.info(f"📤 [ETL ESCALONADA] Cargando progresivamente {len(segment_rows)} filas para segmento '{seg['name']}' ({seg_id}) en BigQuery...")
                            # 📥 Borrar duplicados únicamente para este segmento específico antes de insertar
                            self.bq_service.delete_existing_records("fact_traffic_evolution", self.tenant_id, date_from, date_to, segment_id=seg_id)
                            # 📥 Insertar las nuevas filas en BigQuery de inmediato
                            self.bq_service.insert_rows("fact_traffic_evolution", segment_rows)
                            traffic_rows.extend(segment_rows)
                            
                    except Exception as ere:
                        logger.error(f"Error extrayendo/guardando datos de Adobe para el segmento '{seg['name']}': {ere}")
                        # Continuar con el siguiente segmento para no detener toda la ETL de los demás segmentos
                        continue
                    
                results["adobe"] = f"success ({len(traffic_rows)} filas reales importadas para {len(segment_loops)} segmentos)"
            except Exception as e:
                logger.error(f"Error en extracción de Adobe: {e}")
                results["adobe"] = f"error: {str(e)}"
                raise e

        # ==========================================
        # 🤖 EXTRACT & TRANSFORM: Peec.ai (Tráfico de IA)
        # ==========================================
        peec_creds_raw = credentials.get("peec-key")
        if peec_creds_raw:
            if on_progress:
                on_progress("Ejecutando Ingesta (Peec.ai)", "Descargando e insertando tráfico referido e inferido de IA directamente en BigQuery...")
            try:
                parsed_creds = self._parse_credentials("peec-key", peec_creds_raw)
                peec_service = PeecService(credentials=parsed_creds)
                req = RunReportRequest(
                    property_id="properties/peec-default",
                    date_ranges=[{"start_date": date_from, "end_date": date_to}],
                    dimensions=["date"],
                    metrics=["ai_referred", "ai_inferred", "sentiment_score"]
                )
                res = await peec_service.run_report(req)
                
                peec_rows = []
                for r in res.rows:
                    peec_rows.append({
                        "tenant_id": self.tenant_id,
                        "date": self._clean_date_format(r.get("date")),
                        "source": "ai-engines",
                        "medium": "organic-ai",
                        "total_sessions": 0,
                        "ai_referred_sessions": int(float(r.get("ai_referred", 0))),
                        "ai_inferred_sessions": int(float(r.get("ai_inferred", 0))),
                        "engagement_score": float(r.get("sentiment_score", 0)),
                        "company_id": "peec-account",
                        "property_id": "properties/peec-default",
                        "segment_id": "all-users"
                    })
                if peec_rows:
                    logger.info(f"📤 [ETL ESCALONADA] Cargando {len(peec_rows)} filas de Peec.ai directamente en BigQuery...")
                    self.bq_service.delete_existing_records("fact_traffic_evolution", self.tenant_id, date_from, date_to, segment_id="all-users")
                    self.bq_service.insert_rows("fact_traffic_evolution", peec_rows)
                    traffic_rows.extend(peec_rows)
                results["peec"] = f"success ({len(res.rows)} filas)"
            except Exception as e:
                logger.error(f"Error en extracción de Peec.ai: {e}")
                results["peec"] = f"error: {str(e)}"

        # ==========================================
        # 📈 EXTRACT & TRANSFORM: Brandlight BI (Visibilidad)
        # ==========================================
        brandlight_creds_raw = credentials.get("brandlight-key")
        visibility_rows = []
        if brandlight_creds_raw:
            if on_progress:
                on_progress("Ejecutando Ingesta (Brandlight BI)", "Iniciando pausa de respiro preventivo de 30s para evitar Rate-Limits en Brandlight...")
            # Pausa de respiro de 30 segundos antes de comenzar Brandlight BI
            await asyncio.sleep(30.0)
            if on_progress:
                on_progress("Ejecutando Ingesta (Brandlight BI)", "Descargando e insertando datos de visibilidad y Share of Voice en LLMs...")
            try:
                parsed_creds = self._parse_credentials("brandlight-key", brandlight_creds_raw)
                if isinstance(parsed_creds, dict):
                    parsed_creds["tenant_id"] = self.tenant_id
                brandlight_service = BrandlightService(credentials=parsed_creds)
                req = RunReportRequest(
                    property_id="properties/ES",
                    date_ranges=[{"start_date": date_from, "end_date": date_to}],
                    dimensions=["date", "domain"],
                    metrics=["visibility_score", "sentiment_score", "share_of_voice"]
                )
                res = await brandlight_service.run_report(req)
                
                for r in res.rows:
                    visibility_rows.append({
                        "tenant_id": self.tenant_id,
                        "date": self._clean_date_format(r.get("date")),
                        "domain": r.get("domain"),
                        "visibility_score": float(r.get("visibility_score", 0)),
                        "sentiment_score": float(r.get("sentiment_score", 0)),
                        "share_of_voice": float(r.get("share_of_voice", 0)),
                        "company_id": "brandlight-company",
                        "property_id": "properties/ES"
                    })
                if visibility_rows:
                    logger.info(f"📤 [ETL ESCALONADA] Cargando {len(visibility_rows)} filas de Brandlight directamente en BigQuery...")
                    self.bq_service.delete_existing_records("fact_ai_visibility", self.tenant_id, date_from, date_to)
                    self.bq_service.insert_rows("fact_ai_visibility", visibility_rows)
                    
                results["brandlight"] = f"success ({len(res.rows)} filas)"
            except Exception as e:
                logger.error(f"Error en extracción de Brandlight: {e}")
                results["brandlight"] = f"error: {str(e)}"

        # ==========================================
        # 📊 SUMMARY: Consolidación final del ciclo de ETL
        # ==========================================
        # El proceso es progresivo y escalonado; las filas ya han sido insertadas con seguridad
        # Calculamos el estado de éxito total o parcial dinámicamente en base a los resultados
        has_errors = any("error" in str(val).lower() for val in results.values())
        has_success = any("success" in str(val).lower() for val in results.values())
        
        load_success = not has_errors if has_success else False
        total_records = len(traffic_rows) + len(visibility_rows)
        
        logger.info(f"🏁 Ciclo de ETL completado para '{self.tenant_id}'. Estado de carga final: {'ÉXITO' if load_success else 'PARCIAL/ERROR'}")
        
        status_str = "success" if load_success else "partial_success"
        if has_errors and not has_success:
            status_str = "error"

        sync_result = {
            "status": status_str,
            "tenant_id": self.tenant_id,
            "synced_at": datetime.utcnow().isoformat(),
            "results": results,
            "records_processed": total_records
        }

        # 📊 4. Persistir registro de ejecución y alertas en Firestore (Health Dashboard)
        try:
            from app.services.auth_utils import TokenManager
            tm = TokenManager()
            if tm.db:
                # A. Guardar log histórico de ejecución
                run_id = f"{self.tenant_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                tm.db.collection("etl_runs").document(run_id).set({
                    "run_id": run_id,
                    "tenant_id": self.tenant_id,
                    "timestamp": sync_result["synced_at"],
                    "status": status_str,
                    "records_processed": total_records,
                    "results_summary": results
                })
                
                # B. Generar alertas para cualquier componente fallido
                for provider, res_status in results.items():
                    if "error" in str(res_status).lower():
                        alert_id = f"alert-{self.tenant_id}-{provider}-{datetime.utcnow().strftime('%Y%m%d%H%M')}"
                        tm.db.collection("etl_alerts").document(alert_id).set({
                            "alert_id": alert_id,
                            "tenant_id": self.tenant_id,
                            "provider": provider,
                            "error_message": res_status,
                            "timestamp": sync_result["synced_at"],
                            "status": "active"
                        })
                        logger.info(f"🚨 Alerta de salud de ETL generada de forma autónoma en Firestore para '{self.tenant_id}': {provider}")
        except Exception as fe:
            logger.warning(f"No se pudo guardar la métrica de salud del ETL en Firestore: {fe}")
        
        return sync_result
