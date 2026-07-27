"""Modelos Pydantic para GA Conversational v2."""
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
from datetime import datetime


class HealthResponse(BaseModel):
    """Respuesta del health check."""
    status: str = "healthy"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str = "2.0.0"


class OAuthStatusResponse(BaseModel):
    """Estado de autenticación OAuth."""
    authenticated: bool
    user_email: Optional[str] = None
    expires_at: Optional[datetime] = None
    provider: str = "google"


class GAAccount(BaseModel):
    """Cuenta de Google Analytics."""
    name: str
    display_name: str
    account_id: str


class GAProperty(BaseModel):
    """Propiedad de Google Analytics."""
    name: str
    display_name: str
    property_id: str
    parent: str
    create_time: Optional[str] = None
    update_time: Optional[str] = None
    time_zone: Optional[str] = None
    currency_code: Optional[str] = None
    industry_category: Optional[str] = None


class RunReportRequest(BaseModel):
    """Request para ejecutar un reporte GA4."""
    property_id: Optional[str] = Field(None, description="ID de la propiedad GA4 (formato: properties/XXXXX)")
    date_ranges: List[Dict[str, str]] = Field(
        default=[{"start_date": "7daysAgo", "end_date": "today"}],
        description="Rangos de fechas (formato GA4: YYYY-MM-DD o NdaysAgo)"
    )
    dimensions: List[str] = Field(
        default=["date"],
        description="Dimensiones del reporte (e.g., date, country, deviceCategory)"
    )
    metrics: List[str] = Field(
        default=["activeUsers", "sessions"],
        description="Métricas del reporte (e.g., activeUsers, sessions, conversions)"
    )
    limit: int = Field(default=100, ge=1, le=10000, description="Límite de filas")
    offset: int = Field(default=0, ge=0, description="Offset para paginación")
    session_id: Optional[str] = None
    connection_id: Optional[str] = None
    live_api: bool = False
    segment_id: Optional[str] = None
    tenant_id: Optional[str] = None


class RunReportResponse(BaseModel):
    """Respuesta de un reporte GA4."""
    property_id: str
    dimension_headers: List[str]
    metric_headers: List[str]
    rows: List[Dict[str, Any]]
    row_count: int
    metadata: Optional[Dict[str, Any]] = None


class ChatMessage(BaseModel):
    """Mensaje del chat."""
    role: str = Field(..., description="user o assistant")
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DeepDiveRequest(BaseModel):
    """Request para análisis Deep Dive completo."""
    property_id: str = Field(..., description="ID de la propiedad GA4")
    start_date: str = Field(default="30daysAgo", description="Fecha de inicio (GA4 format)")
    end_date: str = Field(default="today", description="Fecha de fin (GA4 format)")
    session_id: Optional[str] = None
    connection_id: Optional[str] = None


class RiskAnalysisRequest(BaseModel):
    """Request para análisis de Riesgo y Varianza."""
    property_id: str = Field(..., description="ID de la propiedad GA4")
    start_date: str = Field(default="30daysAgo", description="Fecha de inicio")
    end_date: str = Field(default="today", description="Fecha de fin")
    break_even_roas: float = Field(default=3.0, description="Umbral de rentabilidad")
    session_id: Optional[str] = None
    connection_id: Optional[str] = None


class TrafficIARequest(BaseModel):
    """Request para análisis de Tráfico IA."""
    property_id: str = Field(..., description="ID de la propiedad GA4")
    start_date: str = Field(default="30daysAgo", description="Fecha de inicio")
    end_date: str = Field(default="today", description="Fecha de fin")
    language: str = "es"
    session_id: Optional[str] = None
    connection_id: Optional[str] = None
    segment_id: Optional[str] = None


class TrafficIABattleItem(BaseModel):
    platform: str
    sessions: int
    avg_duration: Union[float, str]
    pages_per_session: float
    conversions: Optional[int] = 0
    conversion_rate: Union[float, str]
    engagement_score: float
    relative_ratio: Optional[float] = None
    ratio_label: Optional[str] = None

class ConfidenceIndex(BaseModel):
    """Modelo para índice de confianza detallado."""
    label: str = Field(..., description="Etiqueta: High, Medium, Low")
    score: int = Field(..., description="Puntuación 0-100")
    range: Optional[str] = Field(default=None, description="Rango de confianza (ej: 60% - 80%)")
    reason: Optional[str] = Field(default=None, description="Razón de la confianza")
    description: Optional[str] = Field(default=None, description="Descripción detallada del modelo")

class InferredSourcePerformance(BaseModel):
    source: str
    sessions: int
    avg_duration: Union[float, str]
    pages_per_session: float
    conversions: Optional[int] = 0
    conversion_rate: Union[float, str]
    engagement_score: float
    relative_ratio: Optional[float] = None
    ratio_label: Optional[str] = None

class TrafficIAInferred(BaseModel):
    total_sessions: int
    confidence_index: Union[str, ConfidenceIndex, Dict[str, Any]] = Field(..., description="Índice de confianza")
    breakdown_by_channel: Optional[Dict[str, int]] = None
    avg_duration: Optional[Union[float, str]] = None
    pages_per_session: Optional[float] = None
    conversion_rate: Optional[Union[float, str]] = None
    engagement_score: Optional[float] = None
    top_sources: Optional[List[Union[InferredSourcePerformance, Dict[str, Any]]]] = None

class TrafficIAClusters(BaseModel):
    methodology: Optional[str] = None
    definitions: Dict[str, str]
    distribution: Dict[str, int]

class TrafficIAContentAffinity(BaseModel):
    landing_page: str
    cluster: str
    sessions: int
    avg_duration: Union[float, str]
    share_ia: Optional[str] = None

class TrafficIADailyTrend(BaseModel):
    date: str
    total_sessions: int
    known_ia_sessions: int
    inferred_ia_sessions: Optional[int] = 0

class TrafficIAURLAnalysisRequest(BaseModel):
    """Request para análisis de URLs IA."""
    property_id: str = Field(..., description="ID de la propiedad GA4")
    start_date: str = Field(default="30daysAgo", description="Fecha de inicio")
    end_date: str = Field(default="today", description="Fecha de fin")
    urls: List[str] = Field(..., description="Lista de URLs para analizar")
    session_id: Optional[str] = None
    connection_id: Optional[str] = None

class TrafficIAURLAnalysisResponse(BaseModel):
    """Respuesta del análisis de URLs IA con profundidad."""
    daily_trend: List[Dict[str, Any]] = Field(..., description="Datos evolutivos diarios")
    url_performance: List[Dict[str, Any]] = Field(..., description="Análisis de desempeño por URL")
    traffic_sources_analysis: List[Dict[str, Any]] = Field(..., description="Análisis por fuente de tráfico")
    summary: Dict[str, Any] = Field(..., description="Resumen ejecutivo del análisis")
    total_views: int = None
    total_conversions: float = None
    urls_analyzed: List[str] = None

class TrafficIAResponse(BaseModel):
    """Respuesta del análisis avanzado de Tráfico IA."""
    battle_of_ais: List[Union[TrafficIABattleItem, Dict[str, Any]]]
    behavioral_clusters: TrafficIAClusters
    inferred_traffic: TrafficIAInferred
    content_affinity: Optional[List[TrafficIAContentAffinity]] = []
    ai_insights: Optional[List[str]] = []
    total_sessions: int
    known_ia_sessions: Optional[int] = 0
    non_ia_sessions: int
    organic_traffic_stats: Optional[Dict[str, Any]] = Field(default=None, description="Estadísticas de tráfico orgánico")
    direct_traffic_stats: Optional[Dict[str, Any]] = Field(default=None, description="Estadísticas de tráfico directo")
    daily_trend: Optional[List[Union[TrafficIADailyTrend, Dict[str, Any]]]] = []
    raw_data_summary: Optional[Dict[str, Any]] = None
    date_range: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    """Request para el chat."""
    message: str
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Contexto adicional (cuenta, propiedad, datos previos)"
    )
    chat_history: Optional[List[ChatMessage]] = Field(
        default=None,
        description="Historial de mensajes previos para mantener contexto conversacional"
    )
    session_id: Optional[str] = None
    connection_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Respuesta del chat."""
    message: str
    suggestions: Optional[List[str]] = Field(
        default=None,
        description="Sugerencias de próximas acciones"
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Datos estructurados para visualización"
    )


class ErrorResponse(BaseModel):
    """Respuesta de error estándar."""
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None


# --- NEW MODELS ---

class AIPatternRequest(BaseModel):
    """Request para análisis de patrones de IA."""
    property_id: str
    start_date: str = "30daysAgo"
    end_date: str = "today"
    session_id: Optional[str] = None
    connection_id: Optional[str] = None


class HistoryFilter(BaseModel):
    """Filtro para búsqueda en el historial."""
    account_id: Optional[str] = None
    property_id: Optional[str] = None
    user_email: Optional[str] = None
    limit: int = 50
    offset: int = 0


# --- LEARNING SYSTEM MODELS ---

class FeedbackRequest(BaseModel):
    """Request para enviar feedback al sistema de aprendizaje."""
    user_feedback: Optional[str] = Field(
        default=None,
        description="El feedback o sugerencia del usuario",
        max_length=1000
    )
    rating: str = Field(
        ...,
        description="Valoración binaria: 'positive' o 'negative'",
        pattern="^(positive|negative)$"
    )
    feedback_type: Optional[str] = Field(
        default="improvement",
        description="Tipo de feedback: improvement, bug, clarification"
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Contexto adicional (property_id, issue_type, etc)"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="ID de sesión para trazabilidad"
    )


class FeedbackResponse(BaseModel):
    """Respuesta a un feedback."""
    feedback_id: str = Field(
        ...,
        description="ID único del feedback evaluado"
    )
    verdict: str = Field(
        ...,
        description="ACCEPTED, REJECTED, o PREFERENCE"
    )
    confidence: float = Field(
        ...,
        description="Nivel de confianza del veredicto (0-1)"
    )
    reasoning: str = Field(
        ...,
        description="Explicación del veredicto"
    )
    rule_description: Optional[str] = Field(
        default=None,
        description="Si es ACCEPTED, descripción de la regla"
    )
    message: str = Field(
        ...,
        description="Mensaje para mostrar al usuario"
    )


class RulesStatisticsResponse(BaseModel):
    """Estadísticas de las reglas aprendidas."""
    total_rules: int
    active_rules: int
    by_verdict: Dict[str, int]
    average_confidence: float
    created_at: Optional[str] = None


class AdvancedReportRequest(BaseModel):
    property_id: str
    report_type: str
    start_date: str = "7daysAgo"
    end_date: str = "today"
    custom_config: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    connection_id: Optional[str] = None

class FunnelAnalysisRequest(BaseModel):
    property_id: str
    steps: List[str]
    start_date: str = "7daysAgo"
    end_date: str = "today"
    session_id: Optional[str] = None
    connection_id: Optional[str] = None

class RiskAnalysisRequest(BaseModel):
    property_id: str
    start_date: str = "7daysAgo"
    end_date: str = "today"
    break_even_roas: float = 3.0
    session_id: Optional[str] = None
    connection_id: Optional[str] = None

class TrafficIAAnalysisRequest(BaseModel):
    property_id: str
    start_date: str = "7daysAgo"
    end_date: str = "today"
    language: str = "es"
    session_id: Optional[str] = None
    connection_id: Optional[str] = None

# --- SMART PDF REPORTS MODELS ---

class PDFInsightsRequest(BaseModel):
    """Request para generar insights profundos para el reporte PDF."""
    report_type: str = Field(..., description="Tipo de reporte (ej: traffic-ia, risk)")
    data: Dict[str, Any] = Field(..., description="Datos actuales del dashboard")
    language: str = Field(default="es", description="Idioma del reporte")
    property_name: Optional[str] = Field(default="Propiedad de Analytics", description="Nombre de la propiedad para el título")

class PDFSection(BaseModel):
    """Una sección del reporte PDF generada por IA."""
    title: str
    content: str = Field(..., description="Contenido en formato Markdown o texto plano")
    key_takeaway: Optional[str] = None

class PDFInsightsResponse(BaseModel):
    """Respuesta con insights estructurados para el PDF."""
    executive_summary: str
    sections: List[PDFSection]
    footer_disclaimer: Optional[str] = None


class EngagementScoreExplanationRequest(BaseModel):
    """Request para explicar el Engagement Score (Sniper Score)."""
    engagement_score: float
    conversions: float
    avg_duration: float
    pages_per_session: float
    language: str = "es"


class EngagementScoreExplanationResponse(BaseModel):
    """Respuesta con la explicación de la IA sobre el score."""
    explanation: str
    methodology_summary: str
    calculation_detail: str
