import pandas as pd
import logging
import os
import io
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Directorio temporal para almacenar archivos subidos
UPLOAD_DIR = "/tmp/uploads"
if os.name == "nt":  # Windows
    UPLOAD_DIR = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "uploads")

os.makedirs(UPLOAD_DIR, exist_ok=True)

class LocalDataService:
    def __init__(self):
        self.df: Optional[pd.DataFrame] = None
        self.filename: str = ""
        self.dimensions: List[str] = []
        self.metrics: List[str] = []
        self._cache = {}

    async def save_file(self, file: Any, user_email: str) -> Dict[str, Any]:
        """Sube y procesa un archivo desde FastAPI UploadFile."""
        try:
            content = await file.read()
            filename = file.filename
            
            # Guardar en disco
            file_path = os.path.join(UPLOAD_DIR, filename)
            with open(file_path, "wb") as f:
                f.write(content)
            
            logger.info(f"File {filename} saved for user {user_email}")
            
            # Cargar y analizar
            result = self._load_df_from_disk(filename)
            
            if result["status"] == "success":
                # Devolver un property_id especial que empiece con local:
                result["property_id"] = f"local:{filename}"
            
            return result
        except Exception as e:
            logger.error(f"Error saving file: {e}")
            return {"status": "error", "message": str(e)}

    def load_file(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        try:
            file_path = os.path.join(UPLOAD_DIR, filename)
            with open(file_path, "wb") as f:
                f.write(file_content)
            
            logger.info(f"File saved to {file_path}")
            return self._load_df_from_disk(filename)

        except Exception as e:
            logger.error(f"Error loading local file: {e}")
            return {"status": "error", "message": str(e)}

    def _load_df_from_disk(self, filename: str) -> Dict[str, Any]:
        try:
            file_path = os.path.join(UPLOAD_DIR, filename)
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File {filename} not found")
            
            file_extension = os.path.splitext(filename)[1].lower()
            
            df = None
            if file_extension == '.csv':
                for encoding in ['utf-8', 'latin1', 'cp1252']:
                    try:
                        df = pd.read_csv(file_path, encoding=encoding)
                        break
                    except UnicodeDecodeError:
                        continue
            elif file_extension in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path)
            
            if df is not None:
                self.df = df
                self.filename = filename
                self._analyze_schema()
                
                self._cache[filename] = {
                    "df": df,
                    "dimensions": self.dimensions,
                    "metrics": self.metrics
                }
                
                return {
                    "status": "success",
                    "filename": filename,
                    "rows": len(df),
                    "columns": list(df.columns),
                    "dimensions": self.dimensions,
                    "metrics": self.metrics
                }
            return {"status": "error", "message": "No se pudo leer el archivo"}
            
        except Exception as e:
            logger.error(f"Error reading file from disk: {e}")
            raise e

    def _analyze_schema(self):
        if self.df is None: return
        self.dimensions = []
        self.metrics = []
        
        # Mapeo de sinónimos comunes para GA4
        self.column_mapping = {}
        ga4_synonyms = {
            "sessionSource": ["source", "fuente", "utm_source", "origem"],
            "sessionMedium": ["medium", "medio", "utm_medium", "mídia"],
            "sessionCampaignName": ["campaign", "campaña", "utm_campaign", "campanha"],
            "sessionDefaultChannelGroup": ["channel", "canal", "default channel group"],
            "date": ["date", "fecha", "día", "day"],
            "sessions": ["sessions", "sesiones", "visitas", "visits"],
            "activeUsers": ["users", "usuarios", "active users", "total users"],
            "conversions": ["conversions", "conversiones", "goals", "objetivos", "transactions"],
            "totalRevenue": ["revenue", "ingresos", "valor", "sales", "ventas"],
            "screenPageViews": ["pageviews", "vistas", "views", "page views"],
            "averageSessionDuration": ["duration", "duración", "avg session duration", "time on site"],
            "bounceRate": ["bounce rate", "tasa de rebote", "rebote"],
            "engagementRate": ["engagement rate", "tasa de interacción"]
        }

        for col in self.df.columns:
            col_clean = str(col).lower().strip()
            
            # Intentar encontrar mapeo a GA4
            found_ga4 = False
            for ga_name, synonyms in ga4_synonyms.items():
                if col_clean == ga_name.lower() or col_clean in synonyms:
                    self.column_mapping[ga_name] = col
                    found_ga4 = True
                    break
            
            is_numeric = pd.to_numeric(self.df[col], errors='coerce').notna().all()
            if is_numeric or pd.api.types.is_numeric_dtype(self.df[col]):
                if any(x in col_clean for x in ["id", "year", "año", "date", "fecha"]) and not found_ga4:
                    self.dimensions.append(col)
                else:
                    self.metrics.append(col)
            else:
                self.dimensions.append(col)

    def run_report(self, dimensions: List[str], metrics: List[str], limit: int = 100, filename: Optional[str] = None) -> Dict[str, Any]:
        target_df = self.df
        
        if filename:
            if filename in self._cache:
                target_df = self._cache[filename]["df"]
                # Recargar mapping para este archivo
                self.df = target_df
                self._analyze_schema()
            else:
                try:
                    self._load_df_from_disk(filename)
                    target_df = self.df
                except Exception:
                    pass
        
        if target_df is None:
            raise ValueError("No hay datos cargados. Por favor sube un archivo primero.")

        # Resolver nombres de columnas usando el mapping
        real_dims = []
        for d in dimensions:
            if d in self.column_mapping:
                real_dims.append(self.column_mapping[d])
            elif d in target_df.columns:
                real_dims.append(d)
        
        real_mets = []
        for m in metrics:
            if m in self.column_mapping:
                real_mets.append(self.column_mapping[m])
            elif m in target_df.columns:
                real_mets.append(m)
        
        if not real_dims and not real_mets:
            cols_to_use = list(target_df.columns)[:5]
            result_df = target_df[cols_to_use].head(limit)
        else:
            # Asegurar que las columnas son únicas
            cols_to_select = list(dict.fromkeys(real_dims + real_mets))
            
            if real_dims and real_mets:
                try:
                    # Agrupar si hay dimensiones y métricas
                    result_df = target_df.groupby(real_dims)[real_mets].sum().reset_index()
                except:
                    result_df = target_df[cols_to_select]
            else:
                result_df = target_df[cols_to_select]
            
        # Renombrar de vuelta a nombres GA4 para que los servicios no se rompan
        reverse_mapping = {v: k for k, v in self.column_mapping.items() if v in result_df.columns}
        result_df = result_df.rename(columns=reverse_mapping)

        return {
            "rows": result_df.head(limit).to_dict(orient='records'),
            "row_count": len(result_df),
            "metadata": {
                "dimensions": self.dimensions,
                "metrics": self.metrics,
                "total_rows_in_file": len(target_df),
                "mappings_applied": list(reverse_mapping.values())
            }
        }

local_data_service = LocalDataService()
