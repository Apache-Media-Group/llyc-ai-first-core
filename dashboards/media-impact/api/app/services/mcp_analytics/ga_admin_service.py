"""
GA4 Admin Service
Rol: Configuration Auditor

Responsabilidades:
- Obtener configuración de propiedades GA4
- Listar eventos de conversión
- Auditar dimensiones personalizadas
- Verificar configuración de data streams
- Validar configuración de audiencias
- Auditar vinculaciones (Ads, Search Console, Merchant Center)
- Verificar configuración de medición mejorada
- Auditar reglas de creación de eventos y filtros de datos
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional
from google.analytics.admin_v1beta import AnalyticsAdminServiceClient
from google.analytics.admin_v1beta.types import (
    Property,
    DataStream,
    ConversionEvent,
    CustomDimension,
    CustomMetric
)
from google.oauth2.credentials import Credentials
from google.api_core.exceptions import PermissionDenied, GoogleAPICallError

logger = logging.getLogger(__name__)

# Mappings for better readability
INDUSTRY_CATEGORY_MAP = {
    0: "INDUSTRY_CATEGORY_UNSPECIFIED",
    1: "AUTOMOTIVE",
    2: "BUSINESS_AND_INDUSTRIAL_MARKETS",
    3: "FINANCE",
    4: "HEALTHCARE",
    5: "TECHNOLOGY",
    6: "TRAVEL",
    7: "OTHER",
    8: "ARTS_AND_ENTERTAINMENT",
    9: "BOOKS_AND_LITERATURE",
    10: "COMMUNITIES_AND_ONLINE_FORUMS",
    11: "GAMES",
    12: "HOBBIES_AND_LEISURE",
    13: "HOME_AND_GARDEN",
    14: "INTERNET_AND_TELECOM",
    15: "LAW_AND_GOVERNMENT",
    16: "NEWS",
    17: "ONLINE_COMMUNITIES",
    18: "PEOPLE_AND_SOCIETY",
    19: "PETS_AND_ANIMALS",
    20: "REAL_ESTATE",
    21: "REFERENCE",
    22: "SCIENCE",
    23: "SPORTS",
    24: "JOBS_AND_EDUCATION",
    25: "SHOPPING"
}

# Fix: Mapping correctly from GA4 Enum values
RETENTION_DURATION_MAP = {
    0: "RETENTION_DURATION_UNSPECIFIED",
    1: "2 months",
    3: "14 months",
    4: "26 months",
    5: "38 months",
    6: "50 months"
}

class GA4AdminService:
    """Servicio de API de Admin GA4."""
    
    def __init__(self, credentials: Credentials):
        """
        Inicializa el servicio de Admin.
        
        Args:
            credentials: Credenciales OAuth2 del usuario
        """
        self.client = AnalyticsAdminServiceClient(credentials=credentials)
    
    async def get_property_config(self, property_id: str) -> Dict[str, Any]:
        """
        Obtiene la configuración completa de una propiedad.
        """
        try:
            if not property_id.startswith("properties/"):
                property_id = f"properties/{property_id}"
            
            property_config = self.client.get_property(name=property_id)
            
            # Extract Property ID explicitly
            pid = property_config.name.split('/')[-1] if property_config.name else ""
            
            # Map Industry Category
            industry_val = property_config.industry_category
            if hasattr(industry_val, "value"):
                industry_name = INDUSTRY_CATEGORY_MAP.get(industry_val.value, str(industry_val))
            else:
                industry_name = INDUSTRY_CATEGORY_MAP.get(industry_val, str(industry_val))

            return {
                "property_id": pid,
                "name": property_config.name,
                "display_name": property_config.display_name,
                "create_time": property_config.create_time.isoformat() if property_config.create_time else None,
                "update_time": property_config.update_time.isoformat() if property_config.update_time else None,
                "time_zone": property_config.time_zone,
                "currency_code": property_config.currency_code,
                "industry_category": industry_name,
                "property_type": str(property_config.property_type)
            }
        except Exception as e:
            logger.error(f"Error getting property config: {e}")
            return {"error": str(e)}

    async def list_google_ads_links(self, property_id: str) -> List[Dict[str, Any]]:
        """Lista vinculaciones con Google Ads."""
        try:
            links = []
            request = {"parent": property_id}
            for link in self.client.list_google_ads_links(request=request):
                links.append({
                    "name": link.name,
                    "customer_id": link.customer_id,
                    "ads_personalization_enabled": link.ads_personalization_enabled,
                    "create_time": link.create_time.isoformat() if link.create_time else None
                })
            return links
        except Exception as e:
            logger.warning(f"Could not fetch Google Ads links: {e}")
            return []

    async def list_search_console_links(self, property_id: str) -> List[Dict[str, Any]]:
        """Lista vinculaciones con Search Console."""
        try:
            links = []
            request = {"parent": property_id}
            for link in self.client.list_search_console_links(request=request):
                links.append({
                    "name": link.name,
                    "site_uri": link.site_uri,
                    "search_console_site_uri": link.search_console_site_uri
                })
            return links
        except Exception as e:
            logger.warning(f"Could not fetch Search Console links: {e}")
            return []

    async def list_merchant_center_links(self, property_id: str) -> List[Dict[str, Any]]:
        """Lista vinculaciones con Merchant Center."""
        try:
            links = []
            request = {"parent": property_id}
            for link in self.client.list_merchant_center_links(request=request):
                links.append({
                    "name": link.name,
                    "merchant_id": link.merchant_id,
                    "can_manage_clients": getattr(link, "can_manage_clients", None)
                })
            return links
        except Exception as e:
            logger.debug(f"Could not fetch Merchant Center links: {e}")
            return []

    async def get_enhanced_measurement_settings(self, stream_name: str) -> Dict[str, Any]:
        """Obtiene configuración de medición mejorada para un stream."""
        try:
            settings_name = f"{stream_name}/enhancedMeasurementSettings"
            settings = self.client.get_enhanced_measurement_settings(name=settings_name)
            return {
                "stream_enabled": settings.stream_enabled,
                "scrolls_enabled": settings.scrolls_enabled,
                "outbound_clicks_enabled": settings.outbound_clicks_enabled,
                "site_search_enabled": settings.site_search_enabled,
                "video_engagement_enabled": settings.video_engagement_enabled,
                "file_downloads_enabled": settings.file_downloads_enabled,
                "page_views_enabled": getattr(settings, "page_views_enabled", True),
                "form_interactions_enabled": getattr(settings, "form_interactions_enabled", False)
            }
        except Exception as e:
            logger.debug(f"Error getting enhanced measurement: {e}")
            return {}

    async def list_event_create_rules(self, property_id: str) -> List[Dict[str, Any]]:
        """Lista reglas de creación de eventos personalizados."""
        try:
            rules = []
            for rule in self.client.list_event_create_rules(parent=property_id):
                rules.append({
                    "name": rule.name,
                    "destination_event_name": rule.destination_event_name,
                    "event_conditions": [str(c) for c in rule.event_conditions],
                    "source_copy_parameters": rule.source_copy_parameters
                })
            return rules
        except Exception as e:
            logger.warning(f"Error listing event create rules: {e}")
            return []

    async def list_data_filters(self, property_id: str) -> List[Dict[str, Any]]:
        """Lista filtros de datos (tráfico interno, etc.)."""
        try:
            filters = []
            for df in self.client.list_data_filters(parent=property_id):
                filters.append({
                    "name": df.name,
                    "display_name": df.display_name,
                    "type": str(df.type_),
                    "state": str(df.state)
                })
            return filters
        except Exception as e:
            logger.warning(f"Error listing data filters: {e}")
            return []

    async def list_conversion_events(self, property_id: str) -> List[Dict[str, Any]]:
        """Lista todos los eventos de conversión configurados."""
        try:
            if not property_id.startswith("properties/"):
                property_id = f"properties/{property_id}"
            
            conversions = []
            request = {"parent": property_id}
            
            for conversion_event in self.client.list_conversion_events(request=request):
                conversions.append({
                    "name": conversion_event.name,
                    "event_name": conversion_event.event_name,
                    "create_time": conversion_event.create_time.isoformat() if conversion_event.create_time else None,
                    "is_deletable": conversion_event.deletable,
                    "is_custom": conversion_event.custom
                })
            
            return conversions
        except Exception as e:
            logger.error(f"Error listing conversion events: {e}")
            return []
    
    async def list_custom_dimensions(self, property_id: str) -> List[Dict[str, Any]]:
        """Lista todas las dimensiones personalizadas configuradas."""
        try:
            if not property_id.startswith("properties/"):
                property_id = f"properties/{property_id}"
            
            custom_dims = []
            request = {"parent": property_id}
            
            for dimension in self.client.list_custom_dimensions(request=request):
                custom_dims.append({
                    "name": dimension.name,
                    "parameter_name": dimension.parameter_name,
                    "display_name": dimension.display_name,
                    "description": dimension.description,
                    "scope": str(dimension.scope),
                    "disallow_ads_personalization": dimension.disallow_ads_personalization
                })
            
            return custom_dims
        except Exception as e:
            logger.error(f"Error listing custom dimensions: {e}")
            return []
    
    async def list_custom_metrics(self, property_id: str) -> List[Dict[str, Any]]:
        """Lista todas las métricas personalizadas configuradas."""
        try:
            if not property_id.startswith("properties/"):
                property_id = f"properties/{property_id}"
            
            custom_mets = []
            request = {"parent": property_id}
            
            for metric in self.client.list_custom_metrics(request=request):
                custom_mets.append({
                    "name": metric.name,
                    "parameter_name": metric.parameter_name,
                    "display_name": metric.display_name,
                    "description": metric.description,
                    "measurement_unit": str(metric.measurement_unit),
                    "scope": str(metric.scope)
                })
            
            return custom_mets
        except Exception as e:
            logger.error(f"Error listing custom metrics: {e}")
            return []
    
    async def audit_data_streams(self, property_id: str) -> List[Dict[str, Any]]:
        """Audita los data streams configurados en la propiedad."""
        try:
            if not property_id.startswith("properties/"):
                property_id = f"properties/{property_id}"
            
            streams = []
            request = {"parent": property_id}
            
            for stream in self.client.list_data_streams(request=request):
                stream_data = {
                    "name": stream.name,
                    "display_name": stream.display_name,
                    "type": str(stream.type_).split('.')[-1],
                    "create_time": stream.create_time.isoformat() if stream.create_time else None,
                    "update_time": stream.update_time.isoformat() if stream.update_time else None
                }
                
                if stream.type_ == DataStream.DataStreamType.WEB_DATA_STREAM:
                    if stream.web_stream_data:
                        stream_data["web_config"] = {
                            "measurement_id": stream.web_stream_data.measurement_id,
                            "default_uri": stream.web_stream_data.default_uri
                        }
                        stream_data["enhanced_measurement"] = await self.get_enhanced_measurement_settings(stream.name)
                elif stream.type_ == DataStream.DataStreamType.ANDROID_APP_DATA_STREAM:
                    if stream.android_app_stream_data:
                        stream_data["android_config"] = {
                            "package_name": stream.android_app_stream_data.package_name
                        }
                elif stream.type_ == DataStream.DataStreamType.IOS_APP_DATA_STREAM:
                    if stream.ios_app_stream_data:
                        stream_data["ios_config"] = {
                            "bundle_id": stream.ios_app_stream_data.bundle_id
                        }
                
                streams.append(stream_data)
            
            return streams
        except Exception as e:
            logger.error(f"Error auditing data streams: {e}")
            return []
    
    async def get_data_retention_settings(self, property_id: str) -> Dict[str, Any]:
        """Obtiene la configuración de retención de datos con mapeo corregido."""
        try:
            if not property_id.startswith("properties/"):
                property_id = f"properties/{property_id}"
            
            retention = self.client.get_data_retention_settings(name=f"{property_id}/dataRetentionSettings")
            
            # Map the enum to human readable string
            ret_val = retention.event_data_retention
            val_int = getattr(ret_val, "value", ret_val)
            retention_str = RETENTION_DURATION_MAP.get(val_int, str(ret_val).split('.')[-1])
            
            return {
                "event_data_retention": retention_str,
                "reset_user_data_on_new_activity": retention.reset_user_data_on_new_activity
            }
        except Exception as e:
            logger.error(f"Error getting data retention: {e}")
            return {"error": str(e)}
    
    async def perform_full_audit(self, property_id: str, ga_service=None) -> Dict[str, Any]:
        """Realiza una auditoría completa de la configuración."""
        logger.info(f"Starting full audit for property {property_id}")
        
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"

        # Fetch all in parallel
        (
            property_config, conversions, custom_dimensions, 
            custom_metrics, data_streams, retention_settings,
            ads_links, sc_links, mc_links, event_rules, data_filters
        ) = await asyncio.gather(
            self.get_property_config(property_id),
            self.list_conversion_events(property_id),
            self.list_custom_dimensions(property_id),
            self.list_custom_metrics(property_id),
            self.audit_data_streams(property_id),
            self.get_data_retention_settings(property_id),
            self.list_google_ads_links(property_id),
            self.list_search_console_links(property_id),
            self.list_merchant_center_links(property_id),
            self.list_event_create_rules(property_id),
            self.list_data_filters(property_id)
        )
        
        # Check data reception for custom dimensions if ga_service is provided
        if ga_service and custom_dimensions:
            for dim in custom_dimensions:
                dim['data_status'] = await ga_service.check_data_reception(
                    property_id, dim['parameter_name']
                )

        # Generar resumen y recomendaciones
        audit_summary = self._generate_audit_summary(
            property_config, conversions, custom_dimensions, 
            custom_metrics, data_streams, retention_settings,
            ads_links, sc_links, mc_links, event_rules, data_filters
        )
        
        return {
            "property": property_config,
            "conversions": {"total": len(conversions), "events": conversions},
            "custom_dimensions": {"total": len(custom_dimensions), "dimensions": custom_dimensions},
            "custom_metrics": {"total": len(custom_metrics), "metrics": custom_metrics},
            "data_streams": {"total": len(data_streams), "streams": data_streams},
            "data_retention": retention_settings,
            "links": {
                "google_ads": ads_links,
                "search_console": sc_links,
                "merchant_center": mc_links
            },
            "custom_events": {"total": len(event_rules), "events": event_rules},
            "data_filters": {"total": len(data_filters), "filters": data_filters},
            "audit_summary": audit_summary
        }
    
    def _generate_audit_summary(
        self,
        property_config: Dict,
        conversions: List,
        custom_dimensions: List,
        custom_metrics: List,
        data_streams: List,
        retention: Dict,
        ads_links: List,
        sc_links: List,
        mc_links: List,
        event_rules: List,
        data_filters: List
    ) -> Dict[str, Any]:
        """Genera un resumen ejecutivo de la auditoría."""
        score = 100
        critical_issues = []
        warnings = []
        recommendations = []
        
        if not data_streams:
            score -= 40
            critical_issues.append("No se detectaron Data Streams configurados.")
        
        if not conversions:
            score -= 20
            warnings.append("No hay eventos de conversión marcados.")
        
        if retention.get("event_data_retention") in ["2 months", "RETENTION_DURATION_2_MONTHS"]:
            score -= 10
            warnings.append("Retención de datos al mínimo (2 meses).")
            recommendations.append("Aumentar retención a 14 o 50 meses para análisis históricos.")
            
        if not ads_links:
            warnings.append("Sin vinculación con Google Ads.")
            recommendations.append("Vincular Google Ads para habilitar remarketing y ver datos de inversión.")

        if not data_filters:
            warnings.append("Sin filtros de datos definidos.")
            recommendations.append("Definir filtros para excluir el tráfico interno (oficinas/desarrollo).")

        return {
            "score": max(0, score),
            "critical_issues": critical_issues,
            "warnings": warnings,
            "recommendations": recommendations,
            "status": "GREEN" if score >= 90 else "YELLOW" if score >= 70 else "RED"
        }
