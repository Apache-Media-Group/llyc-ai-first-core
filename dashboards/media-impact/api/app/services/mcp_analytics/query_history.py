"""Servicio para gestionar el historial de consultas de la herramienta.

Este servicio utiliza Google Cloud Firestore para almacenar de forma persistente las consultas 
realizadas por los usuarios, las respuestas generadas y metadata asociada 
(cuenta, propiedad, tiempo de ejecución).
"""

import os
import logging
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
import google.cloud.firestore as firestore
from app.core.config import settings

logger = logging.getLogger(__name__)

class QueryHistoryService:
    def __init__(self, db_path: Optional[str] = None, project_id: Optional[str] = None):
        # Mantenemos db_path por compatibilidad de firmas, pero usamos Firestore
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID") or settings.GCP_PROJECT_ID
        self._db = None
        self.collection_name = "query_history"

    @property
    def db(self) -> firestore.Client:
        """Inicializa de forma perezosa (lazy) el cliente de Firestore."""
        if self._db is None:
            try:
                if self.project_id:
                    self._db = firestore.Client(project=self.project_id)
                    logger.info(f"Cliente Firestore de QueryHistoryService inicializado: {self.project_id}")
                else:
                    self._db = firestore.Client()
                    logger.info("Cliente Firestore de QueryHistoryService inicializado de forma automática (autodetectado).")
            except Exception as e:
                logger.error(f"Error inicializando cliente Firestore en QueryHistoryService: {e}")
                self._db = None
        return self._db

    def log_query(
        self,
        user_email: str,
        query_text: str,
        account_id: Optional[str] = None,
        property_id: Optional[str] = None,
        response_data: Optional[Dict[str, Any]] = None,
        execution_time_ms: int = 0,
        status: str = "success",
        error_message: Optional[str] = None
    ) -> str:
        """Registra una nueva consulta en el historial de Firestore."""
        
        response_summary = ""
        full_response_obj = {}
        
        if response_data:
            if isinstance(response_data, dict):
                msg = response_data.get("message")
                summary = response_data.get("summary")
                
                if msg:
                    response_summary = str(msg)
                elif summary:
                    response_summary = str(summary)
                else:
                    response_summary = ""
                
                response_summary = response_summary[:500]
                full_response_obj = response_data
            else:
                response_summary = str(response_data)[:500]
                full_response_obj = {"response": response_data}

        doc_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_email": user_email.lower().strip() if user_email else "",
            "account_id": account_id,
            "property_id": property_id,
            "query_text": query_text,
            "response_summary": response_summary,
            "full_response_json": full_response_obj,  # Guardamos como objeto estructurado de Firestore
            "execution_time_ms": execution_time_ms,
            "status": status,
            "error_message": error_message
        }

        if self.db is None:
            logger.warning(f"[FALLBACK] No hay cliente Firestore. Ignorando log_query de {user_email} (desarrollo local).")
            return "mock-id-local"

        try:
            # Firestore genera automáticamente un ID de documento único
            _, doc_ref = self.db.collection(self.collection_name).add(doc_data)
            logger.info(f"✅ Query logged to Firestore: {doc_ref.id} for {user_email}")
            return doc_ref.id
        except Exception as e:
            logger.error(f"Error guardando consulta en el historial de Firestore: {e}")
            return ""

    def get_history(
        self,
        account_id: Optional[str] = None,
        property_id: Optional[str] = None,
        user_email: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Recupera el historial filtrado desde Firestore."""
        
        if self.db is None:
            logger.warning(f"[FALLBACK] No hay cliente Firestore. No se pudo recuperar el historial (desarrollo local).")
            return []

        try:
            collection_ref = self.db.collection(self.collection_name)
            query = collection_ref
            
            # Aplicar filtros
            if account_id:
                query = query.where("account_id", "==", account_id)
            if property_id:
                query = query.where("property_id", "==", property_id)
            if user_email:
                query = query.where("user_email", "==", user_email.lower().strip())
                
            # Ordenar por tiempo (descendiente) y paginar
            query = query.order_by("timestamp", direction=firestore.Query.DESCENDING)
            
            # offset manual para compatibilidad con firmas
            if offset > 0:
                # Nota: offset directo en Firestore se hace mejor mediante cursors,
                # pero para compatibilidad de firma con SQLite, usamos el offset directo de la API
                query = query.offset(offset)
                
            query = query.limit(limit)
            
            docs = query.stream()
            result = []
            for doc in docs:
                item = doc.to_dict()
                item["id"] = doc.id
                result.append(item)
                
            return result
        except Exception as e:
            logger.error(f"Error recuperando historial desde Firestore: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas básicas de uso de forma serverless."""
        if self.db is None:
            return {
                "total_queries": 0,
                "total_users": 0,
                "avg_execution_time_ms": 0.0
            }

        try:
            collection_ref = self.db.collection(self.collection_name)
            
            # Obtener conteo total eficiente usando Firestore aggregation count()
            count_query = collection_ref.count()
            total_queries = count_query.get()[0][0].value
            
            # Para total_users, dado que Firestore no tiene group by / distinct nativo directo sin leer todos los docs,
            # hacemos una aproximación o leemos un conjunto limitado de datos recientes para evitar un costo excesivo de lectura
            # En producción real, es mejor pre-computar estadísticas. Haremos una lectura básica de los últimos 200 registros.
            recent_docs = collection_ref.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(200).stream()
            users = set()
            total_time = 0
            success_count = 0
            
            for doc in recent_docs:
                data = doc.to_dict()
                if data.get("user_email"):
                    users.add(data["user_email"])
                if data.get("status") == "success" and data.get("execution_time_ms"):
                    total_time += data["execution_time_ms"]
                    success_count += 1
            
            avg_time = (total_time / success_count) if success_count > 0 else 0
            
            return {
                "total_queries": total_queries,
                "total_users": len(users) if users else 0,
                "avg_execution_time_ms": round(avg_time, 2)
            }
        except Exception as e:
            logger.error(f"Error obteniendo estadísticas de Firestore: {e}")
            return {
                "total_queries": 0,
                "total_users": 0,
                "avg_execution_time_ms": 0.0
            }
