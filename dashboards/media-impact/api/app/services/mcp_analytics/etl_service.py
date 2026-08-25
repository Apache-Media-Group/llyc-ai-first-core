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
                # If wrapped in a custom connection format, extract the actual credentials
                if "credentials_json" in parsed_val:
                    inner_val = parsed_val["credentials_json"]
                    if isinstance(inner_val, str) and inner_val.strip().startswith("{"):
                        import json
                        try:
                            parsed_val = json.loads(inner_val)
                        except Exception:
                            pass
                    elif isinstance(inner_val, dict):
                        parsed_val = inner_val

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
        # 📊 EXTRACT & TRANSFORM: GA4 & Peec
        # ==========================================
        traffic_rows = []
        merged_traffic = {}

        # GA4 Sincronización
        ga4_creds_raw = credentials.get("ga4-creds")
        logger.info(f"GA4 Creds Raw for {self.tenant_id}: {bool(ga4_creds_raw)}")
        if ga4_creds_raw:
            if on_progress:
                on_progress("Ejecutando Ingesta (Google Analytics 4)", "Descargando e insertando tráfico general de GA4 directamente en BigQuery...")
            try:
                parsed_creds = self._parse_credentials("ga4-creds", ga4_creds_raw)
                # Convert dictionary credentials to proper Google Credentials object
                google_creds = parsed_creds
                
                # Extract the actual credentials dict from the wrapper
                actual_creds_dict = parsed_creds
                if isinstance(parsed_creds, dict) and "credentials_json" in parsed_creds:
                    import json
                    if isinstance(parsed_creds["credentials_json"], str):
                        actual_creds_dict = json.loads(parsed_creds["credentials_json"])
                    else:
                        actual_creds_dict = parsed_creds["credentials_json"]
                        
                if isinstance(actual_creds_dict, dict):
                    if "private_key" in actual_creds_dict:
                        from google.oauth2 import service_account
                        google_creds = service_account.Credentials.from_service_account_info(actual_creds_dict)
                    elif "token" in actual_creds_dict and "refresh_token" in actual_creds_dict:
                        from google.oauth2.credentials import Credentials
                        google_creds = Credentials(
                            token=actual_creds_dict.get("token"),
                            refresh_token=actual_creds_dict.get("refresh_token"),
                            token_uri=actual_creds_dict.get("token_uri"),
                            client_id=actual_creds_dict.get("client_id"),
                            client_secret=actual_creds_dict.get("client_secret")
                        )
                
                ga4_property_id = "properties/default"
                if isinstance(ga4_creds_raw, str) and ga4_creds_raw.strip().startswith("{"):
                    import json
                    try:
                        raw_json = json.loads(ga4_creds_raw)
                        if "properties" in raw_json and isinstance(raw_json["properties"], list) and len(raw_json["properties"]) > 0:
                            ga4_property_id = raw_json["properties"][0]
                            if not str(ga4_property_id).startswith("properties/"):
                                ga4_property_id = f"properties/{ga4_property_id}"
                    except Exception:
                        pass

                ga_service = GAService(credentials=google_creds)
                
                from app.services.mcp_analytics.ga_traffic_ia_service import GATrafficIAService
                ga_traffic_ia_service = GATrafficIAService(credentials=google_creds)
                ai_inferred_ratio = 0.0
                try:
                    logger.info(f"Analizando impacto IA inferido para GA4 '{ga4_property_id}'...")
                    res_ia = await ga_traffic_ia_service.analyze_traffic_ia(
                        property_id=ga4_property_id,
                        date_range={"start_date": date_from, "end_date": date_to}
                    )
                    total_sess_ia = float(res_ia.get("total_sessions", 0))
                    if total_sess_ia > 0:
                        inferred_ai_sess = float(res_ia.get("inferred_traffic", {}).get("total_sessions", 0))
                        ai_inferred_ratio = inferred_ai_sess / total_sess_ia
                        logger.info(f"Ratio IA Inferred calculado para GA4: {ai_inferred_ratio:.6f}")
                except Exception as eia:
                    logger.warning(f"No se pudieron calcular ratios de tráfico IA inferido para GA4: {eia}")
                
                limit = 10000
                offset = 0
                all_rows = []
                
                while True:
                    req = RunReportRequest(
                        property_id=ga4_property_id,
                        date_ranges=[{"start_date": date_from, "end_date": date_to}],
                        dimensions=["date", "sessionSource"],
                        metrics=["activeUsers", "sessions", "conversions", "averageSessionDuration", "screenPageViews"],
                        limit=limit,
                        offset=offset
                    )
                    res = await ga_service.run_report(req)
                    if res and res.rows:
                        all_rows.extend(res.rows)
                    if not res or not res.rows or len(res.rows) < limit:
                        break
                    offset += limit

                for r in all_rows:
                    date_val = self._clean_date_format(r.get("date"))
                    source_val = r.get("sessionSource", "").lower()
                    sessions_val = int(float(r.get("sessions", 0)))
                    conversions_val = float(r.get("conversions", 0))
                    avg_duration = float(r.get("averageSessionDuration", 0))
                    views_val = int(float(r.get("screenPageViews", 0)))
                    total_duration_val = sessions_val * avg_duration
                    
                    pages_per_session = views_val / sessions_val if sessions_val > 0 else 0
                    cluster = "casual"
                    if conversions_val > 0:
                        cluster = "transactional"
                    elif avg_duration > 90 and pages_per_session >= 1.5:
                        cluster = "researcher"
                    elif avg_duration < 45 and pages_per_session < 1.5:
                        cluster = "quick_answer"
                    
                    is_chatgpt = "chatgpt" in source_val or "openai" in source_val
                    is_gemini = "gemini" in source_val or "google bard" in source_val or "android-app://com.google.android.apps.bard" in source_val
                    is_perplexity = "perplexity" in source_val
                    is_claude = "claude" in source_val or "anthropic" in source_val
                    is_copilot = "copilot" in source_val or "bing ai" in source_val
                    is_other_ai = (not (is_chatgpt or is_gemini or is_perplexity or is_claude or is_copilot)) and ("ai-assistant" in source_val or "chat" in source_val)
                    is_referred = is_chatgpt or is_gemini or is_perplexity or is_claude or is_copilot or is_other_ai
                    
                    key = f"{ga4_property_id}_all-users_{date_val}"
                    if key not in merged_traffic:
                        merged_traffic[key] = {
                            "tenant_id": self.tenant_id,
                            "date": date_val,
                            "source": "all",
                            "medium": "all",
                            "total_sessions": 0,
                            "ai_referred_sessions": 0,
                            "ai_inferred_sessions": 0,
                            "chatgpt_sessions": 0,
                            "chatgpt_duration": 0.0,
                            "chatgpt_conversions": 0.0,
                            "gemini_sessions": 0,
                            "gemini_duration": 0.0,
                            "gemini_conversions": 0.0,
                            "perplexity_sessions": 0,
                            "perplexity_duration": 0.0,
                            "perplexity_conversions": 0.0,
                            "claude_sessions": 0,
                            "claude_duration": 0.0,
                            "claude_conversions": 0.0,
                            "copilot_sessions": 0,
                            "copilot_duration": 0.0,
                            "copilot_conversions": 0.0,
                            "other_ai_sessions": 0,
                            "other_ai_duration": 0.0,
                            "other_ai_conversions": 0.0,
                            "researcher_sessions": 0,
                            "quick_answer_sessions": 0,
                            "transactional_sessions": 0,
                            "casual_sessions": 0,
                            "engagement_score": 0.0,
                            "company_id": "ga4-account",
                            "property_id": ga4_property_id,
                            "segment_id": "all-users"
                        }
                    merged_traffic[key]["total_sessions"] += sessions_val
                    merged_traffic[key]["total_conversions"] = merged_traffic[key].get("total_conversions", 0) + conversions_val
                    merged_traffic[key]["total_duration"] = merged_traffic[key].get("total_duration", 0) + (sessions_val * avg_duration)
                    merged_traffic[key]["total_views"] = merged_traffic[key].get("total_views", 0) + views_val
                    
                    inferred_sess = round(sessions_val * ai_inferred_ratio)
                    merged_traffic[key]["ai_inferred_sessions"] += inferred_sess
                    
                    amount_to_add = inferred_sess
                    if is_referred:
                        amount_to_add += sessions_val
                        merged_traffic[key]["ai_referred_sessions"] += sessions_val
                    
                    if amount_to_add > 0:
                        if cluster == "transactional":
                            merged_traffic[key]["transactional_sessions"] += amount_to_add
                        elif cluster == "researcher":
                            merged_traffic[key]["researcher_sessions"] += amount_to_add
                        elif cluster == "quick_answer":
                            merged_traffic[key]["quick_answer_sessions"] += amount_to_add
                        else:
                            merged_traffic[key]["casual_sessions"] += amount_to_add
                    if is_chatgpt:
                        merged_traffic[key]["chatgpt_sessions"] += sessions_val
                        merged_traffic[key]["chatgpt_duration"] += total_duration_val
                        merged_traffic[key]["chatgpt_conversions"] += conversions_val
                    elif is_gemini:
                        merged_traffic[key]["gemini_sessions"] += sessions_val
                        merged_traffic[key]["gemini_duration"] += total_duration_val
                        merged_traffic[key]["gemini_conversions"] += conversions_val
                    elif is_perplexity:
                        merged_traffic[key]["perplexity_sessions"] += sessions_val
                        merged_traffic[key]["perplexity_duration"] += total_duration_val
                        merged_traffic[key]["perplexity_conversions"] += conversions_val
                    elif is_claude:
                        merged_traffic[key]["claude_sessions"] += sessions_val
                        merged_traffic[key]["claude_duration"] += total_duration_val
                        merged_traffic[key]["claude_conversions"] += conversions_val
                    elif is_copilot:
                        merged_traffic[key]["copilot_sessions"] += sessions_val
                        merged_traffic[key]["copilot_duration"] += total_duration_val
                        merged_traffic[key]["copilot_conversions"] += conversions_val
                    elif is_other_ai:
                        merged_traffic[key]["other_ai_sessions"] += sessions_val
                        merged_traffic[key]["other_ai_duration"] += total_duration_val
                        merged_traffic[key]["other_ai_conversions"] += conversions_val

                from app.services.mcp_analytics.calculation_service import CalculationService
                for k, stats in merged_traffic.items():
                    if stats["company_id"] == "ga4-account":
                        s_sess = stats.get("total_sessions", 0)
                        if s_sess > 0:
                            s_conv = stats.get("total_conversions", 0)
                            s_dur = stats.get("total_duration", 0) / s_sess
                            s_pag = stats.get("total_views", 0) / s_sess
                            stats["engagement_score"] = CalculationService.calculate_sniper_score(s_conv, s_dur, s_pag)
                        else:
                            stats["engagement_score"] = 0.0
                        
                        # Remove temporary fields used for Calculation before inserting to BigQuery
                        stats.pop("total_conversions", None)
                        stats.pop("total_duration", None)
                        stats.pop("total_views", None)

                results["ga4"] = f"success ({len(all_rows)} filas)"
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
                            
                            cluster_dist = res_ia.get("behavioral_clusters", {}).get("distribution", {})
                            total_clustered = sum(cluster_dist.values()) or 1
                            researcher_ratio = cluster_dist.get("researcher", 0) / total_clustered
                            quick_answer_ratio = cluster_dist.get("quick_answer", 0) / total_clustered
                            transactional_ratio = cluster_dist.get("transactional", 0) / total_clustered
                            casual_ratio = cluster_dist.get("casual", 0) / total_clustered
                            
                            engine_ratios = {}
                            engine_durations = {}
                            for item in res_ia.get("battle_of_ais", []):
                                plat = str(item.get("platform", "other_ai")).lower().replace(" ", "_")
                                if plat not in ["chatgpt", "gemini", "perplexity", "claude", "copilot"]:
                                    plat = "other_ai"
                                
                                engine_ratios[plat] = engine_ratios.get(plat, 0) + (float(item.get("sessions", 0)) / total_sess_ia)
                                engine_durations[plat] = float(item.get("raw_avg_duration_sec", 0))
                    except Exception as eia:
                        logger.warning(f"No se pudieron calcular ratios de tráfico IA para '{seg_name}': {eia}")
                        researcher_ratio, quick_answer_ratio, transactional_ratio, casual_ratio = 0, 0, 0, 1
                        engine_ratios = {}
                        engine_durations = {}

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
                                
                            total_ai_for_day = ai_referred_val + ai_inferred_val
                            segment_rows.append({
                                "tenant_id": self.tenant_id,
                                "date": date_str,
                                "source": "adobe-analytics",
                                "medium": "organic-search",
                                "total_sessions": total_sessions_val,
                                "ai_referred_sessions": ai_referred_val,
                                "ai_inferred_sessions": ai_inferred_val,
                                "chatgpt_sessions": round(total_sessions_val * engine_ratios.get("chatgpt", 0)),
                                "chatgpt_duration": engine_durations.get("chatgpt", 0) * round(total_sessions_val * engine_ratios.get("chatgpt", 0)),
                                "chatgpt_conversions": round(float(r.get("conversions", 0)) * engine_ratios.get("chatgpt", 0), 2),
                                "gemini_sessions": round(total_sessions_val * engine_ratios.get("gemini", 0)),
                                "gemini_duration": engine_durations.get("gemini", 0) * round(total_sessions_val * engine_ratios.get("gemini", 0)),
                                "gemini_conversions": round(float(r.get("conversions", 0)) * engine_ratios.get("gemini", 0), 2),
                                "perplexity_sessions": round(total_sessions_val * engine_ratios.get("perplexity", 0)),
                                "perplexity_duration": engine_durations.get("perplexity", 0) * round(total_sessions_val * engine_ratios.get("perplexity", 0)),
                                "perplexity_conversions": round(float(r.get("conversions", 0)) * engine_ratios.get("perplexity", 0), 2),
                                "claude_sessions": round(total_sessions_val * engine_ratios.get("claude", 0)),
                                "claude_duration": engine_durations.get("claude", 0) * round(total_sessions_val * engine_ratios.get("claude", 0)),
                                "claude_conversions": round(float(r.get("conversions", 0)) * engine_ratios.get("claude", 0), 2),
                                "copilot_sessions": round(total_sessions_val * engine_ratios.get("copilot", 0)),
                                "copilot_duration": engine_durations.get("copilot", 0) * round(total_sessions_val * engine_ratios.get("copilot", 0)),
                                "copilot_conversions": round(float(r.get("conversions", 0)) * engine_ratios.get("copilot", 0), 2),
                                "other_ai_sessions": round(total_sessions_val * engine_ratios.get("other_ai", 0)),
                                "other_ai_duration": engine_durations.get("other_ai", 0) * round(total_sessions_val * engine_ratios.get("other_ai", 0)),
                                "other_ai_conversions": round(float(r.get("conversions", 0)) * engine_ratios.get("other_ai", 0), 2),
                                "researcher_sessions": round(total_ai_for_day * researcher_ratio),
                                "quick_answer_sessions": round(total_ai_for_day * quick_answer_ratio),
                            "transactional_sessions": round(total_ai_for_day * transactional_ratio),
                            "casual_sessions": round(total_ai_for_day * casual_ratio),
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
        # 🤖 EXTRACT & TRANSFORM: Peec.ai (Tráfico de IA, Dominios y Tópicos)
        # ==========================================
        peec_creds_raw = credentials.get("peec-key")
        visibility_rows = []
        if peec_creds_raw:
            if on_progress:
                on_progress("Ejecutando Ingesta (Peec.ai)", "Descargando e insertando tráfico referido e inferido de IA directamente en BigQuery...")
            try:
                parsed_creds = self._parse_credentials("peec-key", peec_creds_raw)
                peec_service = PeecService(credentials=parsed_creds)
                
                # Fetch real property ID instead of hardcoding peec-default
                peec_props = await peec_service.list_properties()
                logger.info(f"PEEC PROPS RETRIEVED: {len(peec_props)} projects")
                
                matched_prop = None
                for p in peec_props:
                    # Logica heuristica para encontrar el proyecto del tenant actual
                    if "vidal" in p.display_name.lower():
                        matched_prop = p
                        break
                        
                if matched_prop:
                    peec_property_id = matched_prop.name
                    logger.info(f"✅ Proyecto PEEC encontrado para {self.tenant_id}: {p.display_name} ({peec_property_id})")
                else:
                    peec_property_id = peec_props[0].name if peec_props else "properties/peec-default"
                    logger.warning(f"⚠️ No se encontró proyecto específico para {self.tenant_id}, usando default: {peec_property_id}")
                
                req = RunReportRequest(
                    property_id=peec_property_id,
                    date_ranges=[{"start_date": date_from, "end_date": date_to}],
                    dimensions=["date"],
                    metrics=["ai_referred", "ai_inferred", "sentiment_score"]
                )
                res = await peec_service.run_report(req)
                
                for r in res.rows:
                    date_val = self._clean_date_format(r.get("date"))
                    # Asumiremos la propiedad default de GA4 para el cruce. Si no existe, la creamos
                    key = f"{ga4_property_id if 'ga4_property_id' in locals() else 'properties/default'}_all-users_{date_val}"
                    if key not in merged_traffic:
                        merged_traffic[key] = {
                            "tenant_id": self.tenant_id,
                            "date": date_val,
                            "source": "ai-engines",
                            "medium": "organic-ai",
                            "total_sessions": 0,
                            "ai_referred_sessions": 0,
                            "ai_inferred_sessions": 0,
                            "chatgpt_sessions": 0,
                            "chatgpt_conversions": 0.0,
                            "gemini_sessions": 0,
                            "gemini_duration": 0.0,
                            "gemini_conversions": 0.0,
                            "perplexity_sessions": 0,
                            "perplexity_duration": 0.0,
                            "perplexity_conversions": 0.0,
                            "claude_sessions": 0,
                            "claude_duration": 0.0,
                            "claude_conversions": 0.0,
                            "copilot_sessions": 0,
                            "copilot_duration": 0.0,
                            "copilot_conversions": 0.0,
                            "other_ai_sessions": 0,
                            "other_ai_duration": 0.0,
                            "other_ai_conversions": 0.0,
                            "researcher_sessions": 0,
                            "quick_answer_sessions": 0,
                            "transactional_sessions": 0,
                            "casual_sessions": 0,
                            "engagement_score": float(r.get("sentiment_score", 0)),
                            "company_id": "peec-account",
                            "property_id": "properties/peec-default",
                            "segment_id": "all-users"
                        }
                    
                    peec_inferred = int(float(r.get("ai_inferred", 0)))
                    merged_traffic[key]["ai_inferred_sessions"] += peec_inferred
                    
                    if peec_inferred > 0:
                        r_sess = merged_traffic[key]["researcher_sessions"]
                        q_sess = merged_traffic[key]["quick_answer_sessions"]
                        t_sess = merged_traffic[key]["transactional_sessions"]
                        c_sess = merged_traffic[key]["casual_sessions"]
                        tot_c = r_sess + q_sess + t_sess + c_sess
                        if tot_c > 0:
                            merged_traffic[key]["researcher_sessions"] += round(peec_inferred * (r_sess / tot_c))
                            merged_traffic[key]["quick_answer_sessions"] += round(peec_inferred * (q_sess / tot_c))
                            merged_traffic[key]["transactional_sessions"] += round(peec_inferred * (t_sess / tot_c))
                            merged_traffic[key]["casual_sessions"] += round(peec_inferred * (c_sess / tot_c))
                        else:
                            merged_traffic[key]["casual_sessions"] += peec_inferred
                    if merged_traffic[key]["engagement_score"] == 0:
                        merged_traffic[key]["engagement_score"] = float(r.get("sentiment_score", 0))

                # Extraer dominios (competidores) desde Peec.ai
                try:
                    domains_data = await peec_service.fetch_domains(peec_property_id, start_date=date_from, end_date=date_to)
                    for item in domains_data:
                        visibility_rows.append({
                            "tenant_id": self.tenant_id,
                            "date": self._clean_date_format(item.get("date", date_val)),
                            "domain": item.get("domain", "(not set)"),
                            "engine": item.get("engine", "Global AI"),
                            "visibility_score": float(item.get("visibility_score", 0) or item.get("score", 0)),
                            "sentiment_score": float(item.get("sentiment_score", 0)),
                            "share_of_voice": float(item.get("share_of_voice", 0)),
                            "company_id": "peec-company",
                            "property_id": peec_property_id,
                            "domain_classification": item.get("classification", "Earned")
                        })
                except Exception as e:
                    logger.error(f"Error extrayendo dominios de Peec.ai: {e}")

                # Extraer temas desde Peec.ai
                try:
                    topics_data = await peec_service.fetch_topics(peec_property_id, start_date=date_from, end_date=date_to)
                    peec_topics_rows = []
                    for item in topics_data:
                        peec_topics_rows.append({
                            "tenant_id": self.tenant_id,
                            "date": self._clean_date_format(item.get("date")),
                            "topic": item.get("topic") or item.get("query") or "(not set)",
                            "priority_score": int(float(item.get("priority_score", 0) or item.get("score", 0))),
                            "recommendation_strategy": item.get("recommendation_strategy") or "Digital / SEO",
                            "execution_steps": item.get("execution_steps", "")
                        })
                    if peec_topics_rows:
                        logger.info(f"📤 Cargando {len(peec_topics_rows)} temas desde Peec.ai en BigQuery...")
                        self.bq_service.delete_existing_records("dim_content_recommendations", self.tenant_id, date_from, date_to)
                        self.bq_service.insert_rows("dim_content_recommendations", peec_topics_rows)
                except Exception as e:
                    logger.error(f"Error extrayendo temas de Peec.ai: {e}")

                results["peec"] = f"success ({len(res.rows)} filas de tráfico, {len(visibility_rows)} dominios)"
            except Exception as e:
                logger.error(f"Error en extracción de Peec.ai: {e}")
                results["peec"] = f"error: {str(e)}"

        # Finalizamos el bloque de Tráfico cargando TODO consolidado a BigQuery
        traffic_rows = list(merged_traffic.values())
        if traffic_rows:
            logger.info(f"📤 [ETL ESCALONADA] Cargando {len(traffic_rows)} filas consolidadas de Tráfico (GA4 + Peec) en BigQuery...")
            self.bq_service.delete_existing_records("fact_traffic_evolution", self.tenant_id, date_from, date_to, segment_id="all-users")
            self.bq_service.insert_rows("fact_traffic_evolution", traffic_rows)

        # ==========================================
        # 📈 EXTRACT & TRANSFORM: Brandlight BI (Visibilidad)
        # ==========================================
        brandlight_creds_raw = credentials.get("brandlight-key")
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
                    dimensions=["date", "domain", "engine"],
                    metrics=["visibility_score", "sentiment_score", "share_of_voice"]
                )
                res = await brandlight_service.run_report(req)
                
                for r in res.rows:
                    visibility_rows.append({
                        "tenant_id": self.tenant_id,
                        "date": self._clean_date_format(r.get("date")),
                        "domain": r.get("domain"),
                        "engine": r.get("engine", "Global AI"),
                        "visibility_score": float(r.get("visibility_score", 0)),
                        "sentiment_score": float(r.get("sentiment_score", 0)),
                        "share_of_voice": float(r.get("share_of_voice", 0)),
                        "company_id": "brandlight-company",
                        "property_id": "properties/ES",
                        "domain_classification": "Earned"
                    })
                    
                # Extraer temas (new content opportunities) desde Brandlight
                try:
                    topics_data = await brandlight_service.fetch_topics("properties/ES")
                    bl_topics_rows = []
                    for item in topics_data:
                        priority_str = str(item.get("priority", "MEDIUM")).upper()
                        p_score = 3 if priority_str == "HIGH" else (2 if priority_str == "MEDIUM" else 1)
                        bl_topics_rows.append({
                            "tenant_id": self.tenant_id,
                            "date": date_to, # Asumimos la fecha final del reporte
                            "topic": item.get("topic") or "(not set)",
                            "priority_score": p_score,
                            "recommendation_strategy": item.get("category", "General"),
                            "execution_steps": f"Prioridad: {priority_str}"
                        })
                    if bl_topics_rows:
                        logger.info(f"📤 Cargando {len(bl_topics_rows)} temas desde Brandlight en BigQuery...")
                        # Se borra por tenant_id, por lo que no colisiona con otros tenants.
                        self.bq_service.delete_existing_records("dim_content_recommendations", self.tenant_id, date_from, date_to)
                        self.bq_service.insert_rows("dim_content_recommendations", bl_topics_rows)
                except Exception as e:
                    logger.error(f"Error extrayendo temas de Brandlight: {e}")
                    
                results["brandlight"] = f"success ({len(res.rows)} filas)"
            except Exception as e:
                logger.error(f"Error en extracción de Brandlight: {e}")
                results["brandlight"] = f"error: {str(e)}"

        if visibility_rows:
            logger.info(f"📤 [ETL ESCALONADA] Cargando {len(visibility_rows)} filas de Visibilidad (Peec/Brandlight) directamente en BigQuery...")
            self.bq_service.delete_existing_records("fact_ai_visibility", self.tenant_id, date_from, date_to)
            self.bq_service.insert_rows("fact_ai_visibility", visibility_rows)

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
