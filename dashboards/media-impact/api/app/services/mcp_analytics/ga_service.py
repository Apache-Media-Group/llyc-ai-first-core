"""Servicio para interactuar con Google Analytics Data API v1 y Admin API."""
import os
import logging
from typing import List, Optional, Dict, Any
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest as GARunReportRequest,
    DateRange,
    Dimension,
    Metric,
)
from google.analytics.admin_v1beta import AnalyticsAdminServiceClient
from google.analytics.admin_v1beta.types import ListPropertiesRequest
from google.oauth2.credentials import Credentials
from google.protobuf.json_format import MessageToDict
from app.models.mcp_analytics.core_models import GAAccount, GAProperty, RunReportRequest, RunReportResponse

logger = logging.getLogger(__name__)


from app.services.mcp_analytics.analytics_interface import AnalyticsService

class GAService(AnalyticsService):
    """Cliente para Google Analytics Data API."""

    def __init__(self, credentials: Optional[Credentials] = None, inspector=None, is_local: bool = False):
        """
        Inicializa el servicio GA.
        
        Args:
            credentials: Credenciales OAuth2 del usuario.
            inspector: DataInspectorService para loguear tráfico raw.
            is_local: Si es verdadero, opera en modo mockeado local sin APIs reales.
        """
        self.credentials = credentials
        self.inspector = inspector
        self.is_local = is_local
        self._client = None
        self._admin_client = None
        
        if isinstance(credentials, dict):
            if "private_key" in credentials:
                from google.oauth2 import service_account
                self.credentials = service_account.Credentials.from_service_account_info(credentials)
            elif "token" in credentials and "refresh_token" in credentials:
                from google.oauth2.credentials import Credentials
                self.credentials = Credentials(
                    token=credentials.get("token"),
                    refresh_token=credentials.get("refresh_token"),
                    token_uri=credentials.get("token_uri"),
                    client_id=credentials.get("client_id"),
                    client_secret=credentials.get("client_secret")
                )
            elif "credentials" in credentials and isinstance(credentials["credentials"], dict):
                # Handle nested credentials (like in ga4-creds)
                creds = credentials["credentials"]
                from google.oauth2.credentials import Credentials
                self.credentials = Credentials(
                    token=creds.get("token"),
                    refresh_token=creds.get("refresh_token"),
                    token_uri=creds.get("token_uri"),
                    client_id=creds.get("client_id"),
                    client_secret=creds.get("client_secret")
                )
            else:
                self.credentials = credentials
        else:
            self.credentials = credentials

    @property
    def client(self) -> BetaAnalyticsDataClient:
        """Lazy load del cliente GA."""
        if self._client is None:
            if self.credentials:
                self._client = BetaAnalyticsDataClient(credentials=self.credentials)
            else:
                # Usa ADC (Application Default Credentials)
                self._client = BetaAnalyticsDataClient()
        return self._client

    @property
    def admin_client(self) -> AnalyticsAdminServiceClient:
        """Lazy load del cliente Admin API."""
        if self._admin_client is None:
            if self.credentials:
                self._admin_client = AnalyticsAdminServiceClient(credentials=self.credentials)
            else:
                self._admin_client = AnalyticsAdminServiceClient()
        return self._admin_client

    async def check_data_reception(self, property_id: str, dimension_name: str) -> str:
        """
        Verifica si una dimensión (personalizada o no) ha recibido datos en los últimos 30 días.
        """
        try:
            from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Dimension, Metric
            
            request = RunReportRequest(
                property=f"properties/{property_id}" if not property_id.startswith("properties/") else property_id,
                dimensions=[Dimension(name=f"customEvent:{dimension_name}" if not dimension_name.startswith("customEvent:") else dimension_name)],
                metrics=[Metric(name="eventCount")],
                date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
                limit=1
            )
            
            response = self.client.run_report(request)
            return "Active" if response.row_count > 0 else "No data (30d)"
        except Exception as e:
            logger.debug(f"Error checking data reception for {dimension_name}: {e}")
            return "Unknown"

    async def list_accounts(self) -> List[GAAccount]:
        """
        Lista las cuentas GA4 del usuario autenticado.
        """
        if self.is_local:
            return [
                GAAccount(
                    name="accounts/local",
                    display_name="Local Data Source",
                    account_id="local",
                )
            ]
        logger.info("Attempting to list GA4 accounts using Admin API")
        try:
            accounts = []
            for account in self.admin_client.list_accounts():
                logger.debug(f"Found account: {account.display_name} ({account.name})")
                accounts.append(
                    GAAccount(
                        name=account.name,
                        display_name=account.display_name,
                        account_id=account.name.split("/")[-1],
                    )
                )
            logger.info(f"Listed {len(accounts)} GA4 accounts")
            # Sort alphabetically by display name
            accounts.sort(key=lambda x: x.display_name.lower())
            return accounts
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Error listing accounts: {exc}", exc_info=True)
            raise

    async def list_properties(self, account_id: Optional[str] = None) -> List[GAProperty]:
        """
        Lista las propiedades GA4.
        """
        if self.is_local:
            return [
                GAProperty(
                    name="properties/bigquery-fact",
                    display_name="BigQuery Consolidated Data",
                    property_id="bigquery-fact",
                    parent="accounts/local"
                )
            ]
        logger.info(f"DEBUG: list_properties called with account_id={account_id}")
        try:
            properties: List[GAProperty] = []

            # Si se especifica account_id, filtramos por ese padre
            if account_id:
                parent = account_id if account_id.startswith("accounts/") else f"accounts/{account_id}"
                logger.info(f"DEBUG: Filtering by parent={parent}")
                try:
                    # In some library versions, parent is passed directly to the method
                    response = self.admin_client.list_properties(parent=parent)
                    for prop in response:
                        properties.append(
                            GAProperty(
                                name=prop.name,
                                display_name=prop.display_name,
                                property_id=prop.name.split("/")[-1],
                                parent=prop.parent,
                                create_time=prop.create_time.isoformat() if prop.create_time else None,
                                update_time=prop.update_time.isoformat() if prop.update_time else None,
                                time_zone=prop.time_zone,
                                currency_code=prop.currency_code,
                                industry_category=str(prop.industry_category),
                            )
                        )
                    logger.info(f"DEBUG: Successfully listed {len(properties)} properties for account {account_id}")
                except Exception as e:
                    logger.error(f"DEBUG: Error in admin_client.list_properties: {e}")
                    # Fallback to summaries if specific list fails
                    account_id_numeric = account_id.split("/")[-1]
                    logger.info(f"DEBUG: Attempting fallback to summaries for account {account_id_numeric}")
                    for summary in self.admin_client.list_account_summaries():
                        if summary.account.split("/")[-1] == account_id_numeric:
                            for prop_summary in summary.property_summaries:
                                properties.append(
                                    GAProperty(
                                        name=prop_summary.property,
                                        display_name=prop_summary.display_name,
                                        property_id=prop_summary.property.split("/")[-1],
                                        parent=prop_summary.parent
                                    )
                                )
                return properties

            # Si no se especifica cuenta, usamos summaries para reunir todas de forma eficiente.
            logger.info("DEBUG: Listing all property summaries across all accounts")
            for summary in self.admin_client.list_account_summaries():
                for prop_summary in summary.property_summaries:
                    properties.append(
                        GAProperty(
                            name=prop_summary.property,
                            display_name=prop_summary.display_name,
                            property_id=prop_summary.property.split("/")[-1],
                            parent=prop_summary.parent
                        )
                    )

            logger.info(f"DEBUG: Listed {len(properties)} properties in total")
            # Sort alphabetically by display name
            properties.sort(key=lambda x: x.display_name.lower())
            return properties
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Error listing properties: {exc}", exc_info=True)
            raise

    async def run_report(self, request: RunReportRequest) -> RunReportResponse:
        """
        Ejecuta un reporte GA4.
        
        Args:
            request: Parámetros del reporte
            
        Returns:
            RunReportResponse con los datos del reporte
        """
        if self.is_local:
            return RunReportResponse(
                property_id=request.property_id or "",
                dimension_headers=request.dimensions,
                metric_headers=request.metrics,
                rows=[],
                row_count=0,
                metadata=None
            )
        # Asegurar formato correcto de property_id
        property_id = request.property_id
        if not property_id.startswith("properties/") and not property_id.startswith("local:"):
            property_id = f"properties/{property_id}"

        # Construir request GA4
        date_ranges = [
            DateRange(start_date=dr["start_date"], end_date=dr["end_date"])
            for dr in request.date_ranges
        ]
        
        dimensions = [Dimension(name=dim) for dim in request.dimensions]
        metrics = [Metric(name=met) for met in request.metrics]

        ga_request = GARunReportRequest(
            property=property_id,
            date_ranges=date_ranges,
            dimensions=dimensions,
            metrics=metrics,
            limit=request.limit,
            offset=request.offset,
        )

        # Ejecutar reporte
        response = self.client.run_report(ga_request)

        # Log to inspector if available
        if self.inspector:
            try:
                self.inspector.log_api_call(
                    endpoint="run_report",
                    request_body=MessageToDict(ga_request._pb),
                    response_data=MessageToDict(response._pb),
                    metadata={"property_id": request.property_id}
                )
            except Exception as e:
                logger.warning(f"Error logging to inspector: {e}")

        # Parsear respuesta
        dimension_headers = [header.name for header in response.dimension_headers]
        metric_headers = [header.name for header in response.metric_headers]

        rows = []
        for row in response.rows:
            row_data = {}
            
            # Dimensiones
            for i, dim_value in enumerate(row.dimension_values):
                row_data[dimension_headers[i]] = dim_value.value
            
            # Métricas
            for i, met_value in enumerate(row.metric_values):
                row_data[metric_headers[i]] = met_value.value

            rows.append(row_data)

        return RunReportResponse(
            property_id=request.property_id or "",
            dimension_headers=dimension_headers,
            metric_headers=metric_headers,
            rows=rows,
            row_count=len(rows),
            metadata={
                "property_quota": MessageToDict(response.property_quota._pb, preserving_proto_field_name=True),
                "kind": response.kind,
            } if hasattr(response, 'property_quota') else None
        )

    async def get_metadata(self, property_id: str) -> Dict[str, Any]:
        """
        Obtiene metadatos de una propiedad (dimensiones y métricas disponibles).
        
        Args:
            property_id: ID de la propiedad (formato: properties/XXXXX)
        """
        if self.is_local:
            return {
                "name": f"properties/{property_id}/metadata",
                "dimensions": [
                    {"api_name": "date", "ui_name": "Fecha", "description": "Fecha del reporte", "category": "Time"}
                ],
                "metrics": [
                    {"api_name": "sessions", "ui_name": "Sesiones", "description": "Sesiones totales", "type": "INTEGER", "category": "Traffic"}
                ]
            }
        # Asegurar formato correcto de property_id
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"

        from google.analytics.data_v1beta.types import GetMetadataRequest

        request = GetMetadataRequest(name=f"{property_id}/metadata")
        metadata = self.client.get_metadata(request)

        dimensions = [
            {
                "api_name": dim.api_name,
                "ui_name": dim.ui_name,
                "description": dim.description,
                "category": dim.category,
            }
            for dim in metadata.dimensions
        ]

        metrics = [
            {
                "api_name": met.api_name,
                "ui_name": met.ui_name,
                "description": met.description,
                "type": met.type_.name if hasattr(met, 'type_') else None,
                "category": met.category,
            }
            for met in metadata.metrics
        ]

        return {
            "name": metadata.name,
            "dimensions": dimensions,
            "metrics": metrics,
        }
