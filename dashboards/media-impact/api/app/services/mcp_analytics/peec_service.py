# backend/app/services/mcp_analytics/peec_service.py

import os
import logging
import aiohttp
import json
import random
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from app.services.mcp_analytics.analytics_interface import AnalyticsService
from app.models.mcp_analytics.core_models import GAAccount, GAProperty, RunReportRequest, RunReportResponse

logger = logging.getLogger(__name__)

class PeecService(AnalyticsService):
    """
    Service to connect to the Peec.ai API and fetch data.
    Implements the standard AnalyticsService interface.
    """

    def __init__(self, credentials: Dict[str, Any]):
        """
        Initializes the PeecService with the given credentials.
        """
        self.api_key = (
            os.getenv("PEEC_API_KEY_TEMP") or
            credentials.get("api_key") or 
            credentials.get("apiKey") or 
            credentials.get("token") or
            credentials.get("x-api-key")
        )
        self.project_id = credentials.get("project_id")
        
        if not self.api_key:
            raise ValueError("API key is required for Peec.ai connection.")
        self.base_url = "https://api.peec.ai/customer/v1"
        self.tenant_id = credentials.get("tenant_id") or "peec-account-1"

    async def list_accounts(self) -> List[GAAccount]:
        """
        Lists the accounts available to the user.
        """
        try:
            # Peec.ai doesn't have multiple levels of accounts in standard configurations.
            # We return a single organization/company representation.
            return [
                GAAccount(
                    name="accounts/peec-account-1",
                    display_name="Peec.ai Organization",
                    account_id="peec-account-1"
                )
            ]
        except Exception as e:
            logger.error(f"Error in PeecService.list_accounts: {e}")
            raise e

    async def list_properties(self, account_id: Optional[str] = None) -> List[GAProperty]:
        """
        Lists the properties (projects) available to the user.
        Calls GET /projects from the Peec.ai API.
        """
        try:
            if not self.api_key or self.api_key == "peec-temp":
                # Fallback mock for presentation or testing
                return [
                    GAProperty(
                        name="properties/peec-proj-1",
                        display_name="Peec.ai Proyecto Demo",
                        property_id="peec-proj-1",
                        parent="accounts/peec-account-1"
                    )
                ]

            headers = {
                "x-api-key": self.api_key,
                "Content-Type": "application/json"
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/projects", headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        projects = []
                        if isinstance(data, list):
                            projects = data
                        elif isinstance(data, dict):
                            projects = data.get("projects") or data.get("content") or data.get("data") or []

                        properties = []
                        for p in projects:
                            p_id = p.get("id") or p.get("projectId")
                            p_name = p.get("name") or p_id
                            if p_id:
                                properties.append(
                                    GAProperty(
                                        name=f"properties/{p_id}",
                                        display_name=p_name,
                                        property_id=p_id,
                                        parent="accounts/peec-account-1"
                                    )
                                )
                        if properties:
                            return properties
                    else:
                        txt = await resp.text()
                        logger.error(f"Peec API error in list_properties: {resp.status} - {txt}")
                        raise Exception(f"Peec API error: {resp.status} - {txt}")

            return []
        except Exception as e:
            logger.error(f"Error in PeecService.list_properties: {e}")
            raise e

    async def run_report(self, request: RunReportRequest) -> RunReportResponse:
        """
        Executes a report against Peec.ai data.
        Fetches real metrics from Peec.ai endpoints. No mocks are used.
        """
        property_id = request.property_id.split("/")[-1] if request.property_id else "peec-proj-1"
        
        if self.project_id:
            property_id = self.project_id
        else:
            # Corrección de Project ID: El ID almacenado en BD/config original (or_04b37997) estaba incorrecto/vacío. 
            # El verdadero proyecto de Vidal & Vidal con datos configurados es or_592a64bf-010a-4be7-a71c-53dbc491d2bb
            if self.tenant_id == "vidal-vidal" or property_id.startswith("or_04b37997"):
                property_id = "or_592a64bf-010a-4be7-a71c-53dbc491d2bb"
                logger.info(f"Peec: Usando el project_id real de Vidal & Vidal ({property_id}).")
            
        dim_headers = request.dimensions
        met_headers = request.metrics

        rows = []
        live_data_fetched = False

        if not self.api_key or self.api_key == "peec-temp":
            logger.warning("No valid Peec.ai API key available. Returning empty data to preserve integrity.")
            return RunReportResponse(
                property_id=property_id,
                dimension_headers=dim_headers,
                metric_headers=met_headers,
                rows=[],
                row_count=0,
                metadata={"provider": "peec", "live_connection": False, "status": "error", "message": "No API key"}
            )

        start_str = "2026-06-01"
        end_str = datetime.utcnow().strftime("%Y-%m-%d")
        if request.date_ranges:
            start_str = request.date_ranges[0].get("start_date", start_str)
            end_str = request.date_ranges[0].get("end_date", end_str)

        try:
            headers = {
                "x-api-key": self.api_key,
                "Content-Type": "application/json"
            }
            async with aiohttp.ClientSession() as session:
                # 1. Obtenemos el nombre del proyecto para filtrar su marca
                project_name = "Vidal & Vidal"
                async with session.get(f"{self.base_url}/projects", headers=headers) as p_resp:
                    if p_resp.status == 200:
                        p_data = await p_resp.json()
                        for p in p_data.get("data", []):
                            if p.get("id") == property_id:
                                project_name = p.get("name", project_name)
                                break
                
                payload = {
                    "project_id": property_id,
                    "limit": request.limit or 1000,
                    "start_date": start_str,
                    "end_date": end_str
                }
                
                if "date" in dim_headers:
                    payload["dimensions"] = ["date"]
                    
                logger.info(f"Peec run_report payload a reports/brands: {payload}")
                async with session.post(f"{self.base_url}/reports/brands", headers=headers, json=payload) as resp:
                    print(f"Peec status: {resp.status} for payload: {payload}")
                    if resp.status == 200:
                        data = await resp.json()
                        raw_data = data.get("data", [])
                        live_data_fetched = True
                        
                        # Filtramos por el nombre del proyecto exacto (Vidal & Vidal)
                        main_brand_data = [item for item in raw_data if item.get("brand", {}).get("name") == project_name]
                        if not main_brand_data and raw_data:
                            # Fallback if no exact match found
                            main_brand_data = raw_data
                            
                        # Defensively map the response to the requested dimensions and metrics
                        for item in main_brand_data:
                            row_data = {}
                            for dim in dim_headers:
                                if dim == "date":
                                    row_data[dim] = item.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
                                elif dim == "country":
                                    row_data[dim] = item.get("country", "(not set)")
                                elif dim == "sessionDefaultChannelGroup" or dim == "source":
                                    row_data[dim] = item.get("source", "AI Search")
                                else:
                                    row_data[dim] = item.get(dim, "(not set)")

                            for met in met_headers:
                                if met == "ai_referred":
                                    row_data[met] = str(item.get("mention_count", 0))
                                elif met == "ai_inferred":
                                    row_data[met] = str(item.get("visibility_count", 0))
                                elif met == "sentiment_score":
                                    row_data[met] = str(item.get("sentiment", 0))
                                else:
                                    row_data[met] = str(item.get(met, 0))
                            
                            rows.append(row_data)
                    else:
                        txt = await resp.text()
                        print(f"PEEC ERROR: {resp.status} - {txt}")
                        logger.error(f"Peec API error: {resp.status} - {txt}")
                        raise Exception(f"Peec API error: {resp.status} - {txt}")

        except Exception as e:
            logger.error(f"Could not fetch live reports from Peec.ai API: {e}")
            raise e

        return RunReportResponse(
            property_id=property_id,
            dimension_headers=dim_headers,
            metric_headers=met_headers,
            rows=rows,
            row_count=len(rows),
            metadata={
                "provider": "peec",
                "live_connection": live_data_fetched,
                "status": "success" if live_data_fetched else "error",
                "api_endpoint": "https://api.peec.ai/customer/v1/"
            }
        )

    async def fetch_domains(self, property_id: str, limit: int = 100, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        """
        Fetches competitor domains visibility from Peec.ai.
        """
        if not self.api_key or self.api_key == "peec-temp":
            return []

        try:
            actual_id = property_id.split("/")[-1] if property_id else "peec-proj-1"
            if self.project_id:
                actual_id = self.project_id
                
            headers = {"x-api-key": self.api_key, "Content-Type": "application/json"}
            async with aiohttp.ClientSession() as session:
                payload = {"project_id": actual_id, "limit": limit}
                if start_date:
                    payload["start_date"] = start_date
                if end_date:
                    payload["end_date"] = end_date
                    
                async with session.post(f"{self.base_url}/reports/domains", headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        domains = data.get("data", [])
                        for d in domains:
                            # Map new API fields to expected ETL fields
                            if "visibility_score" not in d:
                                d["visibility_score"] = d.get("retrieved_percentage", 0) * 100
                            if "sentiment_score" not in d:
                                d["sentiment_score"] = d.get("citation_avg", 0) * 10
                            if "share_of_voice" not in d:
                                d["share_of_voice"] = d.get("usage_rate", 0) * 100
                            
                            d["classification"] = d.get("classification", "Earned")
                        return domains
                    else:
                        txt = await resp.text()
                        logger.error(f"Peec /reports/domains returned {resp.status}: {txt}")
                        raise Exception(f"Peec API error: {resp.status} - {txt}")
        except Exception as e:
            logger.error(f"Error fetching domains from Peec.ai: {e}")
            raise e

    async def fetch_topics(self, property_id: str, limit: int = 100, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        """
        Fetches topics/citations from Peec.ai. Defensively handles 404s if endpoint is unavailable.
        """
        if not self.api_key or self.api_key == "peec-temp":
            return []

        try:
            actual_id = property_id.split("/")[-1] if property_id else "peec-proj-1"
            if self.project_id:
                actual_id = self.project_id
                
            headers = {"x-api-key": self.api_key, "Content-Type": "application/json"}
            async with aiohttp.ClientSession() as session:
                payload = {"project_id": actual_id, "limit": limit}
                if start_date:
                    payload["start_date"] = start_date
                if end_date:
                    payload["end_date"] = end_date
                    
                async with session.get(f"{self.base_url}/topics?project_id={actual_id}&limit={limit}", headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        topics = data.get("data", [])
                        
                        # Fetch topic metrics from /reports/brands
                        topic_metrics = {}
                        try:
                            project_name = "Vidal & Vidal"
                            async with session.get(f"{self.base_url}/projects", headers=headers) as p_resp:
                                if p_resp.status == 200:
                                    p_data = await p_resp.json()
                                    for p in p_data.get("data", []):
                                        if p.get("id") == actual_id:
                                            project_name = p.get("name", project_name)
                                            break
                            
                            rep_payload = {
                                "project_id": actual_id,
                                "start_date": start_date or (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"),
                                "end_date": end_date or datetime.utcnow().strftime("%Y-%m-%d"),
                                "dimensions": ["topic_id"]
                            }
                            async with session.post(f"{self.base_url}/reports/brands", json=rep_payload, headers=headers) as rep_resp:
                                if rep_resp.status == 200:
                                    rep_data = await rep_resp.json()
                                    raw_data = rep_data.get("data", [])
                                    # Filter by the main project brand
                                    main_brand_data = [item for item in raw_data if item.get("brand", {}).get("name") == project_name]
                                    if not main_brand_data and raw_data:
                                        main_brand_data = raw_data
                                        
                                    for item in main_brand_data:
                                        tid = item.get("topic", {}).get("id")
                                        if tid:
                                            topic_metrics[tid] = item.get("mention_count", 0)
                        except Exception as e:
                            logger.error(f"Error fetching topic metrics from Peec.ai: {e}")
                            
                        for t in topics:
                            t["topic"] = t.get("name", "(not set)")
                            t["priority_score"] = topic_metrics.get(t.get("id"), 0)
                            t["recommendation_strategy"] = "Digital / SEO"
                        return topics
                    else:
                        txt = await resp.text()
                        logger.warning(f"Peec /topics returned {resp.status}: {txt}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching topics from Peec.ai: {e}")
            return []

    async def get_metadata(self, property_id: str) -> Dict[str, Any]:
        """
        Returns metadata for the property.
        """
        return {
            "name": property_id,
            "provider": "peec",
            "supported_metrics": [
                "sessions", "activeUsers", "visibility_score", "sentiment_score", 
                "ai_referred", "ai_inferred", "engagement_score", "conversions"
            ],
            "supported_dimensions": ["date", "country", "source", "sessionDefaultChannelGroup"]
        }
