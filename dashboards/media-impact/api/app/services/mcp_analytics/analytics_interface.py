from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from app.models.mcp_analytics.core_models import GAAccount, GAProperty, RunReportRequest, RunReportResponse

class AnalyticsService(ABC):
    """Interfaz abstracta para servicios de analítica (Google Analytics, Adobe Analytics, etc)."""

    @abstractmethod
    async def list_accounts(self) -> List[GAAccount]:
        """Lista las cuentas disponibles."""
        pass

    @abstractmethod
    async def list_properties(self, account_id: Optional[str] = None) -> List[GAProperty]:
        """Lista las propiedades (o Report Suites) disponibles."""
        pass

    @abstractmethod
    async def run_report(self, request: RunReportRequest) -> RunReportResponse:
        """Ejecuta un reporte."""
        pass

    @abstractmethod
    async def get_metadata(self, property_id: str) -> Dict[str, Any]:
        """Obtiene metadatos (dimensiones y métricas disponibles)."""
        pass
