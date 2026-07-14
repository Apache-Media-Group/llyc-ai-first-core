import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""
    PROJECT_ID: str = GCP_PROJECT_ID
    GOOGLE_CLOUD_PROJECT: str = GCP_PROJECT_ID
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    GOOGLE_CLIENT_ID: Optional[str] = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: Optional[str] = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI: Optional[str] = os.getenv("GOOGLE_REDIRECT_URI")
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    # Auth
    SECRET_KEY: Optional[str] = os.getenv("SECRET_KEY")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="allow"
    )

settings = Settings()

# Sincronizar con os.environ para que las librerías nativas de GCP (Firestore, BigQuery) lo lean automáticamente
if settings.GOOGLE_APPLICATION_CREDENTIALS:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.GOOGLE_APPLICATION_CREDENTIALS
if settings.GCP_PROJECT_ID:
    os.environ["GCP_PROJECT_ID"] = settings.GCP_PROJECT_ID
    os.environ["GOOGLE_CLOUD_PROJECT"] = settings.GCP_PROJECT_ID

