import sqlite3
import json
import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

if os.getenv("K_SERVICE") or os.getenv("ENVIRONMENT") == "production":
    DB_PATH = "/tmp/history_v1.db"
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "history.db")

class HistoryService:
    """Servicio para gestionar el historial de consultas y resultados."""

    def __init__(self):
        self._init_db()

    def _init_db(self):
        """Inicializa la base de datos y crea las tablas si no existen."""
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Crear tabla base si no existe
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                property_id TEXT,
                prompt TEXT,
                response_type TEXT,
                result_json TEXT,
                user_email TEXT,
                execution_time_ms INTEGER DEFAULT 0,
                status TEXT DEFAULT 'success'
            )
        ''')
        
        # Migraciones
        try:
            cursor.execute("PRAGMA table_info(history)")
            columns = [info[1] for info in cursor.fetchall()]
            if "user_email" not in columns:
                cursor.execute("ALTER TABLE history ADD COLUMN user_email TEXT")
            if "execution_time_ms" not in columns:
                cursor.execute("ALTER TABLE history ADD COLUMN execution_time_ms INTEGER DEFAULT 0")
            if "status" not in columns:
                cursor.execute("ALTER TABLE history ADD COLUMN status TEXT DEFAULT 'success'")
            
            # Índices
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_prop ON history(property_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user ON history(user_email)")
        except Exception as e:
            logger.error(f"Error en migración de DB: {e}")
            
        conn.commit()
        conn.close()

    def save_event(self, property_id: str, prompt: str, response_type: str, result: Any, user_email: Optional[str] = None, execution_time_ms: int = 0):
        """Guarda un evento en el historial."""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO history (property_id, prompt, response_type, result_json, user_email, execution_time_ms)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (property_id, prompt, response_type, json.dumps(result), user_email, execution_time_ms))
            conn.commit()
            conn.close()
            logger.info(f"Event saved to history: {response_type} for {property_id} (User: {user_email})")
        except Exception as e:
            logger.error(f"Error saving to history: {e}")

    def log_query(self, user_email: str, query_text: str, property_id: str, response_data: Any, execution_time_ms: int = 0):
        """Nuevo método para compatibilidad con el plan de mejora."""
        self.save_event(
            property_id=property_id,
            prompt=query_text,
            response_type="query",
            result=response_data,
            user_email=user_email,
            execution_time_ms=execution_time_ms
        )

    def get_history(self, limit: int = 20, user_email: Optional[str] = None, property_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Recupera los últimos eventos del historial."""
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = 'SELECT * FROM history WHERE 1=1'
            params = []
            
            if user_email:
                query += ' AND user_email = ?'
                params.append(user_email)
            if property_id:
                query += ' AND property_id = ?'
                params.append(property_id)
                
            query += ' ORDER BY timestamp DESC LIMIT ?'
            params.append(limit)
                
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            
            events = []
            for row in rows:
                event = dict(row)
                if event.get('result_json'):
                    try:
                        event['result'] = json.loads(event['result_json'])
                    except Exception:
                        event['result'] = {}
                events.append(event)
                
            return events
        except Exception as e:
            logger.error(f"Error getting history: {e}")
            return []

    def get_event_by_id(self, event_id: int) -> Optional[Dict[str, Any]]:
        """Recupera un evento específico por su ID."""
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM history WHERE id = ?', (event_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                event = dict(row)
                event['result'] = json.loads(event['result_json'])
                return event
            return None
        except Exception as e:
            logger.error(f"Error getting event {event_id}: {e}")
            return None


# Crear instancia singleton
history_service = HistoryService()
