import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import google.cloud.firestore as firestore
from app.core.config import settings

logger = logging.getLogger(__name__)

class SessionService:
    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID") or settings.GCP_PROJECT_ID
        self._db = None
        self.collection_name = "sessions"

    @property
    def db(self) -> firestore.Client:
        """Inicializa de forma perezosa (lazy) el cliente de Firestore."""
        if self._db is None:
            try:
                # Inicializar el cliente Firestore
                if self.project_id:
                    self._db = firestore.Client(project=self.project_id)
                    logger.info(f"Cliente Firestore de SessionService inicializado para el proyecto: {self.project_id}")
                else:
                    self._db = firestore.Client()
                    logger.info("Cliente Firestore de SessionService inicializado de forma automática (autodetectado).")
            except Exception as e:
                logger.error(f"Error inicializando cliente Firestore en SessionService: {e}")
                # Fallback seguro para desarrollo local sin GCP en vivo
                self._db = None
        return self._db

    def save_session(self, session_id: str, data: Dict[str, Any], ttl_seconds: int = 86400):
        """Guarda o actualiza una sesión en Firestore."""
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)
        
        session_doc = {
            "session_id": session_id,
            "data": data,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat()
        }
        
        if self.db is None:
            logger.warning(f"[FALLBACK] No hay cliente Firestore. Ignorando guardado de sesión {session_id} (desarrollo local).")
            return

        try:
            doc_ref = self.db.collection(self.collection_name).document(session_id)
            doc_ref.set(session_doc)
            logger.info(f"✅ Session saved to Firestore: {session_id}")
        except Exception as e:
            logger.error(f"❌ Error saving session {session_id} to Firestore: {e}")

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Recupera una sesión activa de Firestore si no ha expirado."""
        if self.db is None:
            logger.warning(f"[FALLBACK] No hay cliente Firestore. No se pudo recuperar la sesión {session_id} (desarrollo local).")
            return None

        try:
            doc_ref = self.db.collection(self.collection_name).document(session_id)
            doc = doc_ref.get()
            
            if doc.exists:
                session_data = doc.to_dict()
                expires_at_str = session_data.get("expires_at")
                
                if expires_at_str:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    if expires_at > datetime.utcnow():
                        logger.info(f"✅ Session retrieved from Firestore: {session_id}")
                        return session_data.get("data")
                    else:
                        logger.warning(f"⚠️ Session expired: {session_id}. Eliminando...")
                        self.delete_session(session_id)
                        return None
                        
                logger.info(f"✅ Session retrieved from Firestore (sin fecha expiración): {session_id}")
                return session_data.get("data")
                
            logger.warning(f"⚠️ Session NOT found in Firestore: {session_id}")
            return None
        except Exception as e:
            logger.error(f"❌ Error getting session {session_id} from Firestore: {e}")
            return None

    def delete_session(self, session_id: str):
        """Elimina una sesión de Firestore."""
        if self.db is None:
            return

        try:
            doc_ref = self.db.collection(self.collection_name).document(session_id)
            doc_ref.delete()
            logger.info(f"✅ Session deleted from Firestore: {session_id}")
        except Exception as e:
            logger.error(f"Error deleting session {session_id} from Firestore: {e}")

session_service = SessionService()

