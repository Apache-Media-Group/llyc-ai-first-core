# backend/app/services/mcp_analytics/bigquery_service.py

import os
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from google.cloud import bigquery
from app.core.config import settings

logger = logging.getLogger(__name__)

class BigQueryService:
    """
    Servicio de datos empresarial para interactuar con Google BigQuery.
    Maneja la creación de tablas, la ingesta de datos de ETL (Load) y las consultas analíticas del Dashboard.
    """

    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID") or settings.GCP_PROJECT_ID
        # Nota: BigQuery no admite guiones (-) en el ID del Dataset, por lo que usamos guiones bajos (_)
        self.dataset_id = os.getenv("BQ_DATASET_ID", "media_impact_data")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                self._client = bigquery.Client(project=self.project_id)
                logger.info(f"Google BigQuery Client inicializado correctamente para el proyecto: {self.project_id}")
            except Exception as e:
                logger.warning(f"No se pudo inicializar Google BigQuery Client (posible entorno local): {e}")
        return self._client

    def create_dataset_and_tables(self) -> bool:
        """
        Crea el dataset y las tablas analíticas necesarias en BigQuery si no existen.
        """
        if not self.client:
            logger.error("BigQuery Client no disponible. Saltando creación de tablas.")
            return False

        try:
            # 1. Crear Dataset
            dataset_ref = bigquery.DatasetReference(self.project_id, self.dataset_id)
            try:
                self.client.get_dataset(dataset_ref)
                logger.info(f"El Dataset '{self.dataset_id}' ya existe en BigQuery.")
            except Exception as e:
                logger.info(f"El Dataset no pudo ser recuperado ({e}). Intentando crearlo...")
                try:
                    dataset = bigquery.Dataset(dataset_ref)
                    dataset.location = "US"  # O "EU" según corresponda
                    self.client.create_dataset(dataset, timeout=30)
                    logger.info(f"✅ Dataset '{self.dataset_id}' creado con éxito.")
                except Exception as create_e:
                    if "Already Exists" in str(create_e) or "409" in str(create_e):
                        logger.info(f"Dataset '{self.dataset_id}' ya existe (ignorado 409).")
                    else:
                        raise

            # 2. Definir esquemas de tablas
            schemas = {
                "fact_traffic_evolution": [
                    bigquery.SchemaField("tenant_id", "STRING", mode="REQUIRED"),
                    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
                    bigquery.SchemaField("source", "STRING", mode="NULLABLE"),
                    bigquery.SchemaField("medium", "STRING", mode="NULLABLE"),
                    bigquery.SchemaField("total_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("ai_referred_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("ai_inferred_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("chatgpt_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("chatgpt_duration", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("gemini_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("gemini_duration", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("perplexity_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("perplexity_duration", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("claude_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("claude_duration", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("copilot_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("copilot_duration", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("other_ai_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("chatgpt_conversions", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("gemini_conversions", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("perplexity_conversions", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("claude_conversions", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("copilot_conversions", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("other_ai_conversions", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("other_ai_duration", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("engagement_score", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("researcher_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("quick_answer_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("transactional_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("casual_sessions", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("company_id", "STRING", mode="NULLABLE"),
                    bigquery.SchemaField("property_id", "STRING", mode="NULLABLE"),
                    bigquery.SchemaField("segment_id", "STRING", mode="NULLABLE"),
                ],
                "fact_ai_visibility": [
                    bigquery.SchemaField("tenant_id", "STRING", mode="REQUIRED"),
                    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
                    bigquery.SchemaField("domain", "STRING", mode="REQUIRED"),
                    bigquery.SchemaField("engine", "STRING", mode="NULLABLE"),
                    bigquery.SchemaField("visibility_score", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("sentiment_score", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("share_of_voice", "FLOAT", mode="NULLABLE"),
                    bigquery.SchemaField("company_id", "STRING", mode="NULLABLE"),
                    bigquery.SchemaField("property_id", "STRING", mode="NULLABLE"),
                    bigquery.SchemaField("segment_id", "STRING", mode="NULLABLE"),
                ],
                "dim_content_recommendations": [
                    bigquery.SchemaField("tenant_id", "STRING", mode="REQUIRED"),
                    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
                    bigquery.SchemaField("topic", "STRING", mode="REQUIRED"),
                    bigquery.SchemaField("priority_score", "INTEGER", mode="NULLABLE"),
                    bigquery.SchemaField("recommendation_strategy", "STRING", mode="NULLABLE"),
                    bigquery.SchemaField("execution_steps", "STRING", mode="NULLABLE"),
                ]
            }

            # 3. Crear Tablas si no existen, o actualizar su esquema de forma segura si ya existen
            for table_name, schema in schemas.items():
                table_ref = bigquery.TableReference(dataset_ref, table_name)
                try:
                    table = self.client.get_table(table_ref)
                    logger.info(f"La tabla '{table_name}' ya existe en BigQuery. Verificando integridad del esquema...")
                    
                    # Identificar columnas nuevas que falten en el esquema de producción
                    existing_fields = {f.name for f in table.schema}
                    fields_to_add = [f for f in schema if f.name not in existing_fields]
                    
                    if fields_to_add:
                        logger.info(f"Actualizando esquema de '{table_name}' (agregando columnas: {[f.name for f in fields_to_add]})...")
                        new_schema = list(table.schema) + fields_to_add
                        table.schema = new_schema
                        self.client.update_table(table, ["schema"])
                        logger.info(f"✅ Esquema de '{table_name}' actualizado y migrado con éxito en BigQuery.")
                except Exception as e:
                    if "Not found" in str(e) or "not found" in str(e) or "404" in str(e):
                        logger.info(f"Creando tabla analítica '{table_name}'...")
                        table = bigquery.Table(table_ref, schema=schema)
                        # Configurar particionamiento por fecha para optimizar costos de consulta
                        table.time_partitioning = bigquery.TimePartitioning(
                            type_=bigquery.TimePartitioningType.DAY,
                            field="date"
                        )
                        self.client.create_table(table, timeout=30)
                        logger.info(f"✅ Tabla '{table_name}' creada con éxito con particionamiento diario.")
                    else:
                        logger.error(f"Error al verificar/migrar la tabla '{table_name}': {e}")
                        return False

            return True
        except Exception as e:
            logger.error(f"Error al inicializar la estructura de BigQuery: {e}")
            return False

    def insert_rows(self, table_name: str, rows: List[Dict[str, Any]]) -> bool:
        """
        Inserta de forma masiva (Stream/Load) un conjunto de registros en una tabla de BigQuery.
        """
        if not self.client or not rows:
            logger.warning("BigQuery Client no disponible o conjunto de datos vacío. Saltando inserción.")
            return False

        try:
            table_ref = bigquery.TableReference(
                bigquery.DatasetReference(self.project_id, self.dataset_id),
                table_name
            )
            table = self.client.get_table(table_ref)
            
            # Insertar filas usando Load Jobs (Batch) en vez de Streaming para evitar bloqueos del buffer en los DELETEs
            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND
            )
            load_job = self.client.load_table_from_json(rows, table_ref, job_config=job_config)
            load_job.result()  # Esperar a que el job de carga termine
            
            if load_job.errors:
                logger.error(f"Errores al insertar filas (Load Job) en BigQuery: {load_job.errors}")
                return False
                
            logger.info(f"✅ {len(rows)} filas cargadas con éxito en BigQuery ({table_name}).")
            return True
        except Exception as e:
            logger.error(f"Excepción al cargar filas en BigQuery ({table_name}): {e}")
            return False

    def delete_existing_records(self, table_name: str, tenant_id: str, start_date: str, end_date: str, segment_id: Optional[str] = None) -> bool:
        """
        Elimina registros preexistentes en el rango de fechas antes de una nueva inserción.
        Garantiza que el proceso de ETL sea IDEMPOTENTE (sin duplicados), filtrando por segmento si se especifica.
        """
        if not self.client:
            logger.warning("BigQuery Client no disponible. Saltando limpieza de duplicados.")
            return False

        try:
            segment_filter = "AND segment_id = @segment_id" if segment_id else ""
            query = f"""
                DELETE FROM `{self.project_id}.{self.dataset_id}.{table_name}`
                WHERE tenant_id = @tenant_id 
                  AND date BETWEEN @start_date AND @end_date
                  {segment_filter}
            """
            params = [
                bigquery.ScalarQueryParameter("tenant_id", "STRING", tenant_id),
                bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
                bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
            ]
            if segment_id:
                params.append(bigquery.ScalarQueryParameter("segment_id", "STRING", segment_id))
                
            job_config = bigquery.QueryJobConfig(query_parameters=params)
            query_job = self.client.query(query, job_config=job_config)
            query_job.result()  # Esperar que termine la eliminación
            logger.info(f"🧹 Limpieza de duplicados exitosa en '{table_name}' para {tenant_id} ({start_date} a {end_date}, Segmento: {segment_id or 'todos'}).")
            return True
        except Exception as e:
            logger.error(f"Error al eliminar registros preexistentes en BigQuery ({table_name}): {e}")
            return False

    def get_data_gaps(self, tenant_id: str) -> Dict[str, Any]:
        """
        Detecta huecos (fechas faltantes) en el historial de datos de BigQuery de un tenant
        desde la primera fecha de registro hasta hoy.
        """
        if not self.client:
            return {"first_date": None, "gaps": []}

        try:
            # 1. Obtener la primera fecha registrada
            query_min = f"""
                SELECT MIN(date) as min_date 
                FROM `{self.project_id}.{self.dataset_id}.fact_traffic_evolution` 
                WHERE tenant_id = @tenant_id
            """
            job_config_min = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("tenant_id", "STRING", tenant_id)]
            )
            results_min = self.client.query(query_min, job_config=job_config_min).result()
            
            min_date = None
            for row in results_min:
                if row.min_date:
                    min_date = row.min_date.strftime("%Y-%m-%d")
                    
            if not min_date:
                # Si no hay datos, no hay huecos detectables aún
                return {"first_date": None, "gaps": []}

            # 2. Query analítica de huecos de fechas en BigQuery
            query_gaps = f"""
                WITH date_sequence AS (
                  SELECT d
                  FROM UNNEST(GENERATE_DATE_ARRAY(CAST(@min_date AS DATE), CURRENT_DATE())) d
                ),
                active_dates AS (
                  SELECT DISTINCT date 
                  FROM `{self.project_id}.{self.dataset_id}.fact_traffic_evolution` 
                  WHERE tenant_id = @tenant_id
                )
                SELECT d as missing_date
                FROM date_sequence
                LEFT JOIN active_dates ON d = active_dates.date
                WHERE active_dates.date IS NULL
                ORDER BY d ASC
            """
            job_config_gaps = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("tenant_id", "STRING", tenant_id),
                    bigquery.ScalarQueryParameter("min_date", "STRING", min_date),
                ]
            )
            results_gaps = self.client.query(query_gaps, job_config=job_config_gaps).result()
            
            missing_dates = []
            for row in results_gaps:
                missing_dates.append(row.missing_date.strftime("%Y-%m-%d"))

            # 3. Consolidar fechas individuales consecutivas en rangos elegantes para la UI
            gaps_ranges = []
            if missing_dates:
                start_gap = missing_dates[0]
                prev_gap = missing_dates[0]
                
                for d_str in missing_dates[1:]:
                    d_curr = datetime.strptime(d_str, "%Y-%m-%d")
                    d_prev = datetime.strptime(prev_gap, "%Y-%m-%d")
                    
                    if d_curr - d_prev == timedelta(days=1):
                        prev_gap = d_str
                    else:
                        if start_gap == prev_gap:
                            gaps_ranges.append({"start": start_gap, "end": start_gap, "display": start_gap})
                        else:
                            gaps_ranges.append({"start": start_gap, "end": prev_gap, "display": f"{start_gap} a {prev_gap}"})
                        start_gap = d_str
                        prev_gap = d_str
                
                # Añadir el último rango
                if start_gap == prev_gap:
                    gaps_ranges.append({"start": start_gap, "end": start_gap, "display": start_gap})
                else:
                    gaps_ranges.append({"start": start_gap, "end": prev_gap, "display": f"{start_gap} a {prev_gap}"})

            return {
                "first_date": min_date,
                "gaps": gaps_ranges,
                "individual_missing_dates": missing_dates,
                "gap_count": len(missing_dates)
            }
        except Exception as e:
            logger.error(f"Error al detectar huecos de datos para {tenant_id} en BigQuery: {e}")
            return {"first_date": None, "gaps": []}

    def query_dashboard_metrics(self, tenant_id: str, start_date: str, end_date: str, segment_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Realiza consultas estructuradas en BigQuery para consolidar las métricas clave
        y evolución de tráfico de un inquilino para pintar el Dashboard de forma ultrarrápida.
        Soporta consolidación de tráfico y de visibilidad de marca de forma simultánea, filtrable por segmento.
        """
        if not self.client:
            logger.warning("BigQuery Client no disponible. Retornando consulta vacía.")
            return {}

        try:
            # Filtro de segmento por defecto para no duplicar datos (all-users + segmentos)
            target_segment = segment_id if segment_id else "all-users"
            segment_filter = "AND segment_id = @segment_id"
            
            # 1. Query para Tráfico diario (fact_traffic_evolution)
            query_traffic = f"""
                SELECT 
                    date,
                    SUM(total_sessions) as total_sessions,
                    SUM(ai_referred_sessions) as ai_referred,
                    SUM(ai_inferred_sessions) as ai_inferred,
                    SUM(other_ai_sessions) as other_ai_sessions,
                    SUM(chatgpt_conversions) as chatgpt_conversions,
                    SUM(gemini_conversions) as gemini_conversions,
                    SUM(perplexity_conversions) as perplexity_conversions,
                    SUM(claude_conversions) as claude_conversions,
                    SUM(copilot_conversions) as copilot_conversions,
                    SUM(other_ai_conversions) as other_ai_conversions,
                    SUM(chatgpt_duration) as chatgpt_duration,
                    SUM(gemini_sessions) as gemini_sessions,
                    SUM(gemini_duration) as gemini_duration,
                    SUM(perplexity_sessions) as perplexity_sessions,
                    SUM(perplexity_duration) as perplexity_duration,
                    SUM(chatgpt_sessions) as chatgpt_sessions,
                    SUM(claude_sessions) as claude_sessions,
                    SUM(claude_duration) as claude_duration,
                    SUM(copilot_sessions) as copilot_sessions,
                    SUM(copilot_duration) as copilot_duration,
                    SUM(other_ai_duration) as other_ai_duration,
                    SUM(researcher_sessions) as researcher_sessions,
                    SUM(quick_answer_sessions) as quick_answer_sessions,
                    SUM(transactional_sessions) as transactional_sessions,
                    SUM(casual_sessions) as casual_sessions,
                    AVG(engagement_score) as engagement_score
                FROM `{self.project_id}.{self.dataset_id}.fact_traffic_evolution`
                WHERE tenant_id = @tenant_id 
                  AND date BETWEEN @start_date AND @end_date
                  {segment_filter}
                GROUP BY date
                ORDER BY date ASC
            """
            
            # 2. Query para Visibilidad (fact_ai_visibility)
            query_visibility = f"""
                SELECT 
                    AVG(visibility_score) as visibility_score,
                    AVG(sentiment_score) as sentiment_score
                FROM `{self.project_id}.{self.dataset_id}.fact_ai_visibility`
                WHERE tenant_id = @tenant_id 
                  AND date BETWEEN @start_date AND @end_date
            """
            params = [
                bigquery.ScalarQueryParameter("tenant_id", "STRING", tenant_id),
                bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
                bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
                bigquery.ScalarQueryParameter("segment_id", "STRING", target_segment)
            ]
                
            job_config = bigquery.QueryJobConfig(query_parameters=params)
            
            # Ejecutar consulta de tráfico diario
            traffic_results = list(self.client.query(query_traffic, job_config=job_config).result())
            
            metrics = {
                "total_sessions": 0,
                "ai_referred": 0,
                "ai_inferred": 0,
                "engagement_score": 0,
                "visibility_score": 0,
                "has_data": False,
                "behavioral_clusters": {
                    "distribution": {
                        "researcher": 0,
                        "quick_answer": 0,
                        "transactional": 0,
                        "casual": 0
                    }
                },
                "daily_rows": [],
                "domains": [],
                "competitors": [],
                "topics_pr": [],
                "topics_digital": [],
                "total_monitored_domains": 0
            }
            
            total_sessions = 0
            total_ai_referred = 0
            total_ai_inferred = 0
            engagement_sum = 0
            traffic_count = 0
            
            total_chatgpt = 0
            total_gemini = 0
            total_perplexity = 0
            total_claude = 0
            total_copilot = 0
            
            for row in traffic_results:
                if row.total_sessions is not None:
                    row_sessions = row.total_sessions
                    row_referred = row.ai_referred or 0
                    row_inferred = row.ai_inferred or 0
                    row_eng = row.engagement_score or 0
                    
                    total_sessions += row_sessions
                    total_ai_referred += row_referred
                    total_ai_inferred += row_inferred
                    engagement_sum += row_eng
                    traffic_count += 1
                    
                    # Accumulate clusters for the whole period
                    metrics["behavioral_clusters"]["distribution"]["researcher"] += (row.researcher_sessions or 0)
                    metrics["behavioral_clusters"]["distribution"]["quick_answer"] += (row.quick_answer_sessions or 0)
                    metrics["behavioral_clusters"]["distribution"]["transactional"] += (row.transactional_sessions or 0)
                    metrics["behavioral_clusters"]["distribution"]["casual"] += (row.casual_sessions or 0)
                    
                    metrics["daily_rows"].append({
                        "date": row.date.strftime("%Y-%m-%d") if hasattr(row.date, "strftime") else str(row.date),
                        "sessions": row_sessions,
                        "ai_referred": row_referred,
                        "ai_inferred": row_inferred,
                        "other_ai_sessions": row.other_ai_sessions or 0,
                        "chatgpt_conversions": row.chatgpt_conversions or 0.0,
                        "gemini_conversions": row.gemini_conversions or 0.0,
                        "perplexity_conversions": row.perplexity_conversions or 0.0,
                        "claude_conversions": row.claude_conversions or 0.0,
                        "copilot_conversions": row.copilot_conversions or 0.0,
                        "other_ai_conversions": row.other_ai_conversions or 0.0,
                        "chatgpt_sessions": row.chatgpt_sessions or 0,
                        "chatgpt_duration": row.chatgpt_duration or 0.0,
                        "gemini_sessions": row.gemini_sessions or 0,
                        "gemini_duration": row.gemini_duration or 0.0,
                        "perplexity_sessions": row.perplexity_sessions or 0,
                        "perplexity_duration": row.perplexity_duration or 0.0,
                        "claude_sessions": row.claude_sessions or 0,
                        "claude_duration": row.claude_duration or 0.0,
                        "copilot_sessions": row.copilot_sessions or 0,
                        "copilot_duration": row.copilot_duration or 0.0,
                        "other_ai_sessions": row.other_ai_sessions or 0,
                        "other_ai_duration": row.other_ai_duration or 0.0,
                        "engagement_score": round(row_eng, 1)
                    })
                    metrics["has_data"] = True
                    
            if traffic_count > 0:
                metrics["total_sessions"] = total_sessions
                metrics["ai_referred"] = total_ai_referred
                metrics["ai_inferred"] = total_ai_inferred
                metrics["engagement_score"] = round(engagement_sum / traffic_count, 1)
                    
            # Ejecutar consulta de visibilidad
            visibility_job = self.client.query(query_visibility, job_config=job_config)
            visibility_results = list(visibility_job.result())
            
            for row in visibility_results:
                if row.visibility_score is not None:
                    metrics["visibility_score"] = round(row.visibility_score, 1)
                    metrics["sentiment_score"] = round(row.sentiment_score or 0, 1)
                    metrics["has_data"] = True
                    
            # 3. Query para Visibilidad por Motor
            query_visibility_engine = f"""
                SELECT 
                    engine,
                    AVG(visibility_score) as avg_visibility,
                    AVG(sentiment_score) as avg_sentiment
                FROM `{self.project_id}.{self.dataset_id}.fact_ai_visibility`
                WHERE tenant_id = @tenant_id 
                  AND date BETWEEN @start_date AND @end_date
                  AND engine IS NOT NULL
                GROUP BY engine
                ORDER BY avg_visibility DESC
            """
            
            try:
                vis_engine_job = self.client.query(query_visibility_engine, job_config=job_config)
                vis_engine_results = list(vis_engine_job.result())
                
                vis_engine_list = []
                for row in vis_engine_results:
                    if row.engine and row.avg_visibility is not None:
                        vis_engine_list.append({
                            "engine": row.engine,
                            "brand_score": round(row.avg_visibility, 1),
                            "competitor_avg": round(row.avg_visibility * 0.8, 1) # Heurística temporal hasta que haya datos de competidores por motor
                        })
                metrics["visibility_by_engine"] = vis_engine_list
            except Exception as e:
                logger.warning(f"Error querying visibility by engine for {tenant_id}: {e}")

            # 4. Query para Dominios y Competidores
            query_domains = f"""
                SELECT 
                    domain,
                    AVG(visibility_score) as avg_visibility,
                    AVG(sentiment_score) as avg_sentiment,
                    ANY_VALUE(domain_classification) as domain_classification
                FROM `{self.project_id}.{self.dataset_id}.fact_ai_visibility`
                WHERE tenant_id = @tenant_id 
                  AND date BETWEEN @start_date AND @end_date
                GROUP BY domain
                ORDER BY avg_visibility DESC
            """
            
            try:
                domains_job = self.client.query(query_domains, job_config=job_config)
                domains_results = list(domains_job.result())
                
                # Heurística para branded: si PEEC lo marca como Owned o el nombre de dominio coincide
                tenant_brand_name = tenant_id.lower().replace("-", "").replace("_", "")
                
                domains_list = []
                for row in domains_results:
                    domain_name = row.domain or "unknown"
                    classification = row.domain_classification or "Earned"
                    
                    is_branded = (classification.lower() == "owned") or (tenant_brand_name in domain_name.lower().replace("-", "").replace(".", ""))
                    
                    domains_list.append({
                        "domain": domain_name,
                        "visibility_score": round(row.avg_visibility or 0, 1),
                        "sentiment_score": round(row.avg_sentiment or 0, 1),
                        "classification": "Owned" if is_branded else classification,
                        "is_branded": is_branded
                    })
                
                metrics["total_monitored_domains"] = len(domains_list)
                
                # Competitors: los no branded con mayor visibilidad (Top 5)
                competitors = [d for d in domains_list if not d["is_branded"]]
                metrics["competitors"] = competitors[:5]
                metrics["domains"] = domains_list
                
            except Exception as e:
                logger.warning(f"Error querying domains for {tenant_id}: {e}")

            # 4. Query para Temáticas
            query_topics = f"""
                SELECT 
                    topic,
                    recommendation_strategy,
                    MAX(priority_score) as priority_score
                FROM `{self.project_id}.{self.dataset_id}.dim_content_recommendations`
                WHERE tenant_id = @tenant_id
                  AND date BETWEEN @start_date AND @end_date
                GROUP BY topic, recommendation_strategy
                ORDER BY priority_score DESC
            """
            
            try:
                topics_job = self.client.query(query_topics, job_config=job_config)
                topics_results = list(topics_job.result())
                
                for row in topics_results:
                    topic_obj = {
                        "name": row.topic,
                        "score": row.priority_score or 0
                    }
                    strategy = (row.recommendation_strategy or "").lower()
                    if "pr" in strategy or "comunicación" in strategy or "comunicacion" in strategy:
                        metrics["topics_pr"].append(topic_obj)
                    else:
                        metrics["topics_digital"].append(topic_obj)
            except Exception as e:
                logger.warning(f"Error querying topics for {tenant_id}: {e}")

            logger.info(f"Métricas consolidadas de BigQuery para '{tenant_id}' (has_data={metrics['has_data']}) recuperadas con éxito.")
            return metrics
            
        except Exception as e:
            logger.error(f"Error al realizar consulta analítica en BigQuery para {tenant_id}: {e}")
            return {}
