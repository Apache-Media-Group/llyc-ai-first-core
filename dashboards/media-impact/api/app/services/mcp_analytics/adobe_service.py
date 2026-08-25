import logging
import aiohttp
import asyncio
import pandas as pd
import numpy as np
import math
import json
import re
from typing import List, Dict, Any, Optional
from app.services.mcp_analytics.analytics_interface import AnalyticsService
from app.models.mcp_analytics.core_models import GAAccount, GAProperty, RunReportRequest, RunReportResponse
from datetime import datetime, timedelta
from scipy import stats
from app.services.mcp_analytics.calculation_service import CalculationService

logger = logging.getLogger(__name__)

class AdobeAnalyticsService(AnalyticsService):
    """
    Implementación avanzada de AnalyticsService para Adobe Analytics 2.0 API.
    Proporciona paridad de funciones con GA4 para MCP Analytics.
    """

    def __init__(self, credentials: Dict[str, str]):
        self.client_id = (
            credentials.get("client_id") or 
            credentials.get("apiKey") or 
            credentials.get("clientId")
        )
        self.client_secret = (
            credentials.get("client_secret") or 
            credentials.get("clientSecret")
        )
        self.org_id = (
            credentials.get("org_id") or 
            credentials.get("imsOrgId") or 
            credentials.get("orgId")
        )
        self.technical_account_id = credentials.get("technical_account_id")
        self.access_token = (
            credentials.get("access_token") or 
            credentials.get("accessToken")
        )
        self.refresh_token = (
            credentials.get("refresh_token") or 
            credentials.get("refreshToken")
        )
        self.tenant_id = credentials.get("tenant_id")
        self.company_id = None
        if credentials.get("force_company_id") == "true" or credentials.get("forceCompanyId") == True:
            self.company_id = (
                credentials.get("company_id") or 
                credentials.get("globalCompanyId") or 
                credentials.get("global_company_id") or
                credentials.get("tenant_id")
            )

        self.base_url = "https://analytics.adobe.io/api"
        self._last_raw_discovery = None 
        self.provider = "adobe"
        
        self.metric_mapping = {
            "screenPageViews": "metrics/pageviews",
            "activeUsers": "metrics/visits",
            "sessions": "metrics/visits",
            "eventCount": "metrics/occurrences",
            "conversions": credentials.get("adobe_conversion_metric") or "metrics/orders",
            "totalRevenue": "metrics/revenue",
            "revenue": "metrics/revenue",
            "bounceRate": "metrics/bouncerate",
            "engagementRate": "metrics/entries",
            "userEngagementDuration": "metrics/averagetimespentonsite",
            "sessionConversionRate": credentials.get("adobe_conversion_metric") or "metrics/orders",
            "screenPageViewsPerSession": "metrics/pageviews",
            "averagePurchaseRevenue": "metrics/revenue",
            "totalUsers": "metrics/visits"
        }
        
        self.dimension_mapping = {
            "date": "variables/daterangeday",
            "pagePath": "variables/page",
            "landingPagePlusQueryString": "variables/entrypage",
            "city": "variables/geocity",
            "deviceCategory": "variables/mobiledevicetype",
            "pageTitle": "variables/page", 
            "sessionSource": "variables/referrer",
            "sessionMedium": "variables/referringdomain",
            "sessionCampaignName": "variables/campaign",
            "country": "variables/geocountry",
            "language": "variables/language",
            "channel": "variables/lasttouchchannel",
            "region": "variables/georegion"
        }

        self.ai_referrers = ["chatgpt.com", "perplexity.ai", "gemini.google.com", "copilot.microsoft.com", "claude.ai", "chatgpt", "perplexity", "gemini", "copilot", "claude"]

    def _get_headers(self, token: str, content_type: Optional[str] = None) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if self.client_id: headers["x-api-key"] = str(self.client_id)
        if self.org_id: headers["x-gw-ims-org-id"] = str(self.org_id)
        if content_type: headers["Content-Type"] = content_type
        return headers

    def _sanitize_dict(self, d: Any) -> Any:
        if isinstance(d, dict): return {str(k): self._sanitize_dict(v) for k, v in d.items()}
        elif isinstance(d, list): return [self._sanitize_dict(i) for i in d]
        return d

    async def _get_access_token(self):
        if self.client_id == "adobe-temp":
            return "mock-access-token"
        if self.refresh_token and self.client_id and self.client_secret:
            url = "https://ims-na1.adobelogin.com/ims/token/v3"
            payload = {"grant_type": "refresh_token", "client_id": self.client_id, "client_secret": self.client_secret, "refresh_token": self.refresh_token}
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.access_token = data.get("access_token")
                        if data.get("refresh_token"): self.refresh_token = data.get("refresh_token")
                        return self.access_token
        if self.client_id and self.client_secret and not self.refresh_token:
            url = "https://ims-na1.adobelogin.com/ims/token/v3"
            payload = {"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret, "scope": "openid,AdobeID,read_organizations,additional_info.projectedProductContext,https://ims-na1.adobelogin.com/s/ent_analytics_bulk_ingest_sdk"}
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.access_token = data.get("access_token")
                        return self.access_token
        if self.access_token: return self.access_token
        raise Exception("Adobe: No valid credentials available.")

    async def _get_company_id(self) -> str:
        if self.client_id == "adobe-temp":
            if self.tenant_id == "sanitas":
                return "sanita2"
            return "company-test-1"
        if self.company_id: return self.company_id
        
        accounts = await self.list_accounts()
        if accounts:
            self.company_id = accounts[0].account_id
            return self.company_id
            
        raise Exception("Adobe: No Global Company ID found.")

    async def list_accounts(self) -> List[GAAccount]:
        if self.client_id == "adobe-temp":
            if self.tenant_id == "sanitas":
                return [
                    GAAccount(name="companies/sanita2", display_name="Sanitas", account_id="sanita2")
                ]
            return [
                GAAccount(name="companies/company-test-1", display_name="LLYC España Compañía de Pruebas", account_id="company-test-1"),
                GAAccount(name="companies/company-test-2", display_name="LLYC Latam Compañía Demo", account_id="company-test-2")
            ]
        try:
            token = await self._get_access_token()
            headers = self._get_headers(token)
            url = "https://analytics.adobe.io/discovery/me"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    raw_text = await resp.text()
                    if resp.status == 200:
                        data = json.loads(raw_text)
                        ims_orgs = data.get("imsOrgs") or data.get("orgs") or []
                        accounts = []
                        for org in ims_orgs:
                            org_ims_id = org.get("imsOrgId", "").lower().strip()
                            self_org_id_clean = self.org_id.lower().strip() if self.org_id else ""
                            
                            # Comparación limpia y tolerante a fallos de formato del Org ID
                            if self_org_id_clean and org_ims_id:
                                org_ims_id_raw = org_ims_id.split("@")[0]
                                self_org_id_raw = self_org_id_clean.split("@")[0]
                                if org_ims_id_raw != self_org_id_raw:
                                    continue
                                    
                            org_name = org.get("imsOrgName") or org.get("orgName") or "Adobe Org"
                            companies = org.get("companies") or org.get("analyticsCompanies") or []
                            for company in companies:
                                g_id = company.get('globalCompanyId') or company.get('companyId') or company.get('id')
                                if g_id:
                                    c_name = company.get("companyName") or company.get("name") or g_id
                                    accounts.append(GAAccount(name=f"companies/{g_id}", display_name=f"{org_name} - {c_name}", account_id=g_id))
                        
                        # Fallback de Resiliencia: Si se filtró por Org ID y dio 0 resultados, 
                        # reintentar sin filtrar para que el usuario no se quede bloqueado si hay diferencias de metadatos en Adobe
                        if not accounts and self.org_id:
                            logger.info("Discovery: 0 compañías encontradas con el filtro de Org ID. Reintentando sin filtrar para prevenir bloqueos...")
                            for org in ims_orgs:
                                org_name = org.get("imsOrgName") or org.get("orgName") or "Adobe Org"
                                companies = org.get("companies") or org.get("analyticsCompanies") or []
                                for company in companies:
                                    g_id = company.get('globalCompanyId') or company.get('companyId') or company.get('id')
                                    if g_id:
                                        c_name = company.get("companyName") or company.get("name") or g_id
                                        accounts.append(GAAccount(name=f"companies/{g_id}", display_name=f"{org_name} - {c_name}", account_id=g_id))
                        
                        # Cache the first company ID found to prevent future 429s during deep dives
                        if accounts and not self.company_id:
                            self.company_id = accounts[0].account_id
                            
                        return accounts
                    elif resp.status == 429:
                        logger.warning("Adobe Discovery hit Rate Limit (429). Attempting fallback to environment variable if available.")
                        if self.company_id: return [GAAccount(name=f"companies/{self.company_id}", display_name="Cached Account", account_id=self.company_id)]
                        raise Exception("Adobe Discovery Rate Limit Exceeded (429 Too Many Requests).")
                    raise Exception(f"Adobe Discovery error: {resp.status}")
        except Exception as e:
            logger.error(f"Adobe Discovery failed: {e}")
            raise e

    async def list_properties(self, account_id: Optional[str] = None) -> List[GAProperty]:
        if self.client_id == "adobe-temp":
            if self.tenant_id == "sanitas" or account_id == "sanita2":
                return [
                    GAProperty(name="vrs_sanita2_sanitasmayores", display_name="Sanitas Mayores Suite (vrs_sanita2_sanitasmayores)", property_id="vrs_sanita2_sanitasmayores", parent="accounts/sanita2")
                ]
            return [
                GAProperty(name="rs-llyc-es-corp", display_name="LLYC España Corporativo Suite (rs-llyc-es-corp)", property_id="rs-llyc-es-corp", parent="accounts/company-test-1"),
                GAProperty(name="rs-llyc-mx-mkt", display_name="LLYC México Marketing Suite (rs-llyc-mx-mkt)", property_id="rs-llyc-mx-mkt", parent="accounts/company-test-1")
            ]
        try:
            token = await self._get_access_token()
            company_id = account_id or await self._get_company_id()
            headers = self._get_headers(token)
            url = f"{self.base_url}/{company_id}/collections/suites"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return [GAProperty(name=i.get("rsid"), display_name=i.get("name"), property_id=i.get("rsid"), parent=f"accounts/{company_id}") for i in data.get("content", [])]
                    return []
        except: return []

    async def list_segments(self, report_suite_id: str) -> List[Dict[str, Any]]:
        """
        Lists all available segments for a given report suite.
        """
        if self.client_id == "adobe-temp":
            if self.tenant_id == "sanitas" or report_suite_id == "vrs_sanita2_sanitasmayores":
                return [
                    {"id": "s6582_694960ac62fb9877ebbada1f", "name": "Mayores Sanitas SEM"},
                    {"id": "s6582_69271f0350a78e73f6b47e5e", "name": "Biblioteca de salud 3ª Edad"},
                    {"id": "s6582_69271ecb50a78e73f6b47e5c", "name": "Sanitas Mayores SEO"},
                    {"id": "all-users", "name": "Todos los usuarios"}
                ]
            return [
                {"id": "seg-llyc-organic-seo", "name": "Búsqueda Orgánica SEO (Google/Bing)"},
                {"id": "seg-llyc-ai-referred", "name": "Tráfico Referido por Motores IA (ChatGPT)"},
                {"id": "seg-llyc-social-media", "name": "Redes Sociales (LinkedIn/Twitter)"}
            ]
        try:
            token = await self._get_access_token()
            company_id = await self._get_company_id()
            headers = self._get_headers(token)
            
            # Parameters to get all relevant segments
            params = {
                "rsids": report_suite_id,
                "expansion": "definition,reportSuiteName,ownerFullName",
                "includeType": "all",
                "limit": 500  # Fetch up to 500 segments
            }
            
            url = f"{self.base_url}/{company_id}/segments"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        segments = data.get("content", [])
                        return [
                            {
                                "id": seg.get("id"),
                                "name": seg.get("name"),
                                "definition": seg.get("definition")
                            }
                            for seg in segments
                        ]
                    else:
                        logger.error(f"Adobe list_segments failed with status {resp.status}: {await resp.text()}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching Adobe segments: {e}", exc_info=True)
            return []

    async def run_report(self, request: RunReportRequest) -> RunReportResponse:
        token = await self._get_access_token()
        company_id = await self._get_company_id()
        rsid = request.property_id
        if not rsid or rsid == 'default' or rsid == 'adobe_analytics_source':
            suites = await self.list_properties(company_id)
            if suites: rsid = suites[0].property_id
            else: raise Exception("No Report Suites available")

        start = self._normalize_adobe_datetime(request.date_ranges[0].get("start_date"), False)
        end = self._normalize_adobe_datetime(request.date_ranges[0].get("end_date"), True)
        
        adobe_metrics = []
        for m in request.metrics:
            mapped_m = m if (m.startswith("metrics/") or m.startswith("variables/")) else self.metric_mapping.get(m, f"metrics/{m}")
            adobe_metrics.append({"id": mapped_m})

        dim_key = request.dimensions[0] if request.dimensions else "date"
        adobe_dim = dim_key if (dim_key.startswith("variables/") or dim_key.startswith("metrics/")) else self.dimension_mapping.get(dim_key, f"variables/{dim_key}")

        adobe_req = {
            "rsid": rsid,
            "globalFilters": [{"type": "dateRange", "dateRange": f"{start}/{end}"}],
            "metricContainer": {"metrics": adobe_metrics},
            "dimension": adobe_dim,
            "settings": {"limit": request.limit or 100, "page": 0}
        }

        # Add segment filter if provided
        if hasattr(request, 'segment_id') and request.segment_id:
            adobe_req["globalFilters"].append({
                "type": "segment",
                "segmentId": request.segment_id
            })

        headers = self._get_headers(token, content_type="application/json")
        url = f"{self.base_url}/{company_id}/reports"
        max_retries = 25
        base_delay = 4.0

        async with aiohttp.ClientSession() as session:
            for attempt in range(max_retries):
                async with session.post(url, headers=headers, json=adobe_req) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        rows = []
                        for row in data.get("rows", []):
                            p_row = {dim_key: row.get("value") or row.get("itemId", "(not set)")}
                            m_values = row.get("data", [])
                            for i, m_name in enumerate(request.metrics): 
                                p_row[m_name] = str(m_values[i]) if i < len(m_values) else "0"
                            rows.append(p_row)
                        return RunReportResponse(property_id=rsid, dimension_headers=[dim_key], metric_headers=request.metrics, rows=rows, row_count=len(rows), metadata={"rsid": rsid})
                    
                    elif resp.status == 429:
                        import random
                        delay = min(60.0, (base_delay * (2 ** attempt)) + random.uniform(0.5, 1.5))
                        logger.warning(f"⚠️ Adobe API Rate Limit (429) detectado en intento {attempt+1}/{max_retries}. Durmiendo {delay:.2f}s antes de reintentar para dar respiro...")
                        await asyncio.sleep(delay)
                    
                    else:
                        raise Exception(f"Adobe API Error: {resp.status}")
                        
            raise Exception("Adobe: Límite de reintentos agotado tras recibir continuos códigos 429 (Too Many Requests).")

    async def get_metadata(self, property_id: str) -> Dict[str, Any]:
        return {"name": property_id, "provider": "adobe"}

    def _calculate_sniper_score(self, conversion_rate: float, avg_duration: float, pages_per_session: float) -> float:
        import math
        try:
            base_score = 70.0 if conversion_rate > 0 else 0.0
            friction_factor = (avg_duration * pages_per_session) + 10.0
            denominator = math.log10(friction_factor)
            if denominator <= 0: denominator = 1.0
            efficiency_bonus = 30.0 / denominator
            return round(float(min(100.0, base_score + efficiency_bonus)), 1)
        except: return 0.0

    async def analyze_traffic_ia(self, property_id: str, start_date: str, end_date: str, language: str = "es", segment_id: Optional[str] = None) -> Dict[str, Any]:
        # 1. Llama a Referrers (IA & Metricas de engagement) - Aumentamos limite para evitar perdida de datos
        # Intentamos detectar si el cliente usa Leads en lugar de Orders
        conversion_metric = self.metric_mapping.get("conversions", "metrics/orders")
        
        req_referrer = RunReportRequest(
            property_id=property_id,
            date_ranges=[{"start_date": start_date, "end_date": end_date}],
            dimensions=["sessionSource"],
            metrics=["sessions", "screenPageViews", conversion_metric, "bounceRate", "userEngagementDuration"],
            limit=10000,
            segment_id=segment_id
        )
        
        # 2. Llama a Channel (SEO exacto para Olga)
        req_channel = RunReportRequest(
            property_id=property_id,
            date_ranges=[{"start_date": start_date, "end_date": end_date}],
            dimensions=["channel"], 
            metrics=["sessions", conversion_metric],
            limit=100,
            segment_id=segment_id
        )

        # 3. Llama a Totales (Para paridad exacta de sesiones de la propiedad)
        req_total = RunReportRequest(
            property_id=property_id,
            date_ranges=[{"start_date": start_date, "end_date": end_date}],
            dimensions=["date"], 
            metrics=["sessions", conversion_metric],
            limit=1000,
            segment_id=segment_id
        )
        
        try:
            report_referrer, report_channel, report_total = await asyncio.gather(
                self.run_report(req_referrer),
                self.run_report(req_channel),
                self.run_report(req_total)
            )
        except Exception as e:
            logger.error(f"Adobe Traffic IA Gather failed: {e}")
            return {"battle_of_ais": [], "total_sessions": 0, "non_ia_sessions": 0, "behavioral_clusters": {"definitions": {}, "distribution": {}}, "inferred_traffic": {"total_sessions": 0, "confidence_index": {"label": "Low", "score": 0}}}
        
        # Calculo de total absoluto de la propiedad
        total_sessions_abs = int(sum(float(r.get("sessions", 0)) for r in report_total.rows))
        total_conversions_abs = sum(float(r.get(conversion_metric, 0)) for r in report_total.rows)

        # Si no hay conversiones con la métrica por defecto (Orders), intentamos un fallback a IDs de eventos reales
        if total_conversions_abs == 0:
            try:
                # Usar event78 como métrica de éxito principal para IA
                fallback_metrics = ["metrics/event78", "metrics/event13", "metrics/event12", "metrics/event14", "metrics/event29", "metrics/event7", "metrics/event1"]
                for fb_metric in fallback_metrics:
                    logger.info(f"Attempting fallback to {fb_metric}...")
                    req_fallback = RunReportRequest(
                        property_id=property_id,
                        date_ranges=[{"start_date": start_date, "end_date": end_date}],
                        dimensions=["date"],
                        metrics=[fb_metric],
                        limit=1
                    )
                    fallback_report = await self.run_report(req_fallback)
                    if fallback_report.rows and float(fallback_report.rows[0].get(fb_metric, 0)) > 0:
                        conversion_metric = fb_metric
                        logger.info(f"✅ Successful fallback to {conversion_metric}")
                        # Re-ejecutamos los reportes principales con la métrica correcta
                        report_referrer, report_channel, report_total = await asyncio.gather(
                            self.run_report(req_referrer.copy(update={"metrics": ["sessions", "screenPageViews", conversion_metric, "bounceRate", "userEngagementDuration"]})),
                            self.run_report(req_channel.copy(update={"metrics": ["sessions", conversion_metric]})),
                            self.run_report(req_total.copy(update={"metrics": ["sessions", conversion_metric]}))
                        )
                        total_conversions_abs = sum(float(r.get(conversion_metric, 0)) for r in report_total.rows)
                        break
            except Exception as fe:
                logger.error(f"Fallback attempt failed: {fe}")
                pass

        rows = []
        for r in report_referrer.rows:
            visits = float(r.get("sessions", 0))
            if visits == 0: continue
            views = float(r.get("screenPageViews", 0))
            time_avg = float(r.get("userEngagementDuration", 0))
            conversions = float(r.get(conversion_metric, 0))
            
            if time_avg == 0: time_avg = (views / visits) * 15 if visits > 0 else 0
            
            rows.append({
                "source": str(r.get("sessionSource", "unknown")).lower(),
                "sessions": visits,
                "page_views": views,
                "conversions": conversions,
                "bounce_rate": float(r.get("bounceRate", 0)),
                "avg_duration": time_avg,
                "pages_per_session": views / visits,
                "conversion_rate": (conversions / visits) * 100
            })
            
        df = pd.DataFrame(rows)
        if df.empty: return {"battle_of_ais": [], "total_sessions": total_sessions_abs, "non_ia_sessions": total_sessions_abs, "behavioral_clusters": {"definitions": {}, "distribution": {}}, "inferred_traffic": {"total_sessions": 0, "confidence_index": {"label": "Low", "score": 0}}}

        # --- Cálculo del Baseline del Site ---
        total_sessions_ref = int(df['sessions'].sum())
        agg_dur = (df['avg_duration'] * df['sessions']).sum()
        agg_views = (df['pages_per_session'] * df['sessions']).sum()
        agg_conv = df['conversions'].sum()
        
        avg_dur_base = agg_dur / total_sessions_ref if total_sessions_ref > 0 else 0
        pages_base = agg_views / total_sessions_ref if total_sessions_ref > 0 else 0
        
        s_baseline = CalculationService.calculate_sniper_score(agg_conv, avg_dur_base, pages_base)

        df['is_known_ai'] = df['source'].apply(lambda s: any(ref in s for ref in self.ai_referrers))
        
        def cluster_row(row):
            if row['conversions'] > 0: return 'transactional'
            if row['avg_duration'] > 90 and row['pages_per_session'] >= 1.5: return 'researcher'
            if row['avg_duration'] < 45 and row['pages_per_session'] < 1.5: return 'quick_answer'
            return 'casual'
        df['cluster'] = df.apply(cluster_row, axis=1)
        
        def normalize_name(s):
            if "openai" in s or "chatgpt" in s: return "ChatGPT"
            if "copilot" in s: return "Copilot"
            if "gemini" in s or "bard" in s: return "Gemini"
            if "perplexity" in s: return "Perplexity"
            if "claude" in s or "anthropic" in s: return "Claude"
            return "Other AI"
        
        df['ai_platform'] = df.apply(lambda r: normalize_name(r['source']) if r['is_known_ai'] else None, axis=1)
        
        ai_df = df[df['is_known_ai']].copy()
        battle_of_ais = []
        if not ai_df.empty:
            b_df = ai_df.groupby('ai_platform').agg({'sessions': 'sum', 'avg_duration': 'mean', 'pages_per_session': 'mean', 'conversions': 'sum'}).reset_index()
            for _, r in b_df.iterrows():
                sess = int(r['sessions'])
                
                # Umbral mínimo de 10 sesiones
                if sess < 10:
                    battle_of_ais.append({
                        "platform": r['ai_platform'], 
                        "sessions": sess, 
                        "avg_duration": "N/A", 
                        "pages_per_session": 0, 
                        "conversions": int(r['conversions']),
                        "conversion_rate": "0%", 
                        "engagement_score": 0,
                        "relative_ratio": 0,
                        "ratio_label": "N/A — muestra insuficiente"
                    })
                    continue

                avg_dur_sec = int(r['avg_duration'])
                # Score centralizado y Ratio Relativo
                sniper = CalculationService.calculate_sniper_score(r['conversions'], avg_dur_sec, r['pages_per_session'])
                relative_ratio = round(sniper / s_baseline, 2) if s_baseline > 0 else 1.0
                
                ratio_label = "intención similar a la media"
                if relative_ratio >= 1.30: ratio_label = "intención 30% superior a la media"
                elif relative_ratio >= 1.10: ratio_label = "intención por encima de la media"
                elif relative_ratio < 0.90: ratio_label = "intención por debajo de la media"

                m, s = divmod(avg_dur_sec, 60)
                dur_str = f"{m:02d}:{s:02d}" if avg_dur_sec >= 60 else f"{avg_dur_sec}s"
                battle_of_ais.append({
                    "platform": r['ai_platform'], 
                    "sessions": sess, 
                    "avg_duration": dur_str, 
                    "pages_per_session": round(float(r['pages_per_session']), 2), 
                    "conversions": int(r['conversions']),
                    "conversion_rate": f"{round((r['conversions']/sess*100), 2)}%", 
                    "engagement_score": sniper,
                    "relative_ratio": relative_ratio,
                    "ratio_label": f"{relative_ratio}x — {ratio_label}"
                })
        
        # Force exact match between Battle of AIs table and KPI cards
        known_ia_sessions_exact = sum(item['sessions'] for item in battle_of_ais)

        # Clusters sobre sesiones IA
        ai_known_df = df[df['is_known_ai']].copy()
        if not ai_known_df.empty:
            cluster_distribution = ai_known_df.groupby('cluster')['sessions'].sum().to_dict()
        else:
            cluster_distribution = {"casual": 0, "researcher": 0, "quick_answer": 0, "transactional": 0}
        
        # Asegurar todas las llaves para el grafico del frontend
        for c in ["casual", "researcher", "quick_answer", "transactional"]:
            if c not in cluster_distribution: cluster_distribution[c] = 0

        target_df = df[~df['is_known_ai']].copy()
        target_cluster_stats = target_df.groupby('cluster')['sessions'].sum().to_dict()
        inferred_ia = int(target_cluster_stats.get('researcher', 0) * 0.4 + target_cluster_stats.get('quick_answer', 0) * 0.2)
        
        # Extracción exacta del canal SEO y Directo (Incluyendo nombres localizados sugeridos por Olga)
        total_organic = 0
        total_direct = 0
        for rc in report_channel.rows:
            ch_name = str(rc.get("channel", "")).upper()
            if ch_name in ["SEO", "NATURAL SEARCH", "BÚSQUEDA ORGÁNICA"]:
                total_organic += int(float(rc.get("sessions", 0)))
            elif ch_name in ["DIRECT", "TYPED/BOOKMARKED", "TRÁFICO DIRECTO", "SIN CANAL DE MARKETING"]:
                total_direct += int(float(rc.get("sessions", 0)))
                
        # Fallback basado en Referrers si el reporte de canales falló o está vacío
        if total_organic == 0:
            organic_mask = df['source'].str.contains('google|bing|yahoo|duckduckgo|ecosia', na=False) & ~df['source'].str.contains('syndication|doubleclick|cpc|ads', na=False)
            total_organic = int(df[organic_mask]['sessions'].sum())
        
        if total_direct == 0:
            direct_mask = df['source'].isin(['(direct)', 'typed/bookmarked'])
            total_direct = int(df[direct_mask]['sessions'].sum())
            
        # Ajuste final: Si la suma de canales conocidos supera el total, priorizamos el reporte de canales de Adobe
        # pero si es inferior, el excedente va a "Otros" automáticamente en el return final.
        # Score global centralizado
        relevant_df = target_df[target_df['cluster'].isin(['researcher', 'quick_answer'])]
        if not relevant_df.empty:
            r_sess = relevant_df['sessions'].sum()
            r_dur = (relevant_df['avg_duration'] * relevant_df['sessions']).sum() / r_sess
            r_views = (relevant_df['pages_per_session'] * relevant_df['sessions']).sum() / r_sess
            global_score = CalculationService.calculate_sniper_score(relevant_df['conversions'].sum(), r_dur, r_views)
        else:
            global_score = 0.0

        content_affinity = []
        try:
            # Asegurar que company_id esté cargado
            c_id = await self._get_company_id()
            normalized_start = self._normalize_adobe_datetime(start_date, False)
            normalized_end = self._normalize_adobe_datetime(end_date, True)
            safe_start = normalized_start.split('T')[0] if 'T' in normalized_start else normalized_start
            safe_end = normalized_end.split('T')[0] if 'T' in normalized_end else normalized_end
            
            # Query para Landing Pages mas populares (como proxy de afinidad)
            req_urls = {
                "rsid": property_id,
                "globalFilters": [{"type": "dateRange", "dateRange": f"{safe_start}T00:00:00/{safe_end}T23:59:59"}],
                "dimension": "variables/entrypage",
                "metricContainer": {"metrics": [{"id": "metrics/visits"}, {"id": "metrics/averagetimespentonsite"}]},
                "settings": {"limit": 10, "page": 0}
            }
            token = await self._get_access_token()
            headers = self._get_headers(token, content_type="application/json")
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/{c_id}/reports", headers=headers, json=req_urls) as resp:
                    if resp.status == 200:
                        url_report = await resp.json()
                        ia_ratio = known_ia_sessions_exact / total_sessions_abs if total_sessions_abs > 0 else 0
                        for ur in url_report.get("rows", []):
                            lp = str(ur.get("value") or "/")
                            m_vals = ur.get("data", [])
                            page_visits = float(m_vals[0]) if len(m_vals) > 0 else 0
                            
                            # Estimación de sesiones IA para esta URL basada en el ratio global (Heurística)
                            # En el futuro, esto debería ser un reporte con segmento de Referrers IA
                            sess_ia_est = int(page_visits * ia_ratio) + (1 if "ia" in lp.lower() or "ai" in lp.lower() else 0)
                            if sess_ia_est > page_visits: sess_ia_est = int(page_visits)
                            
                            share_pct = round((sess_ia_est / known_ia_sessions_exact) * 100, 1) if known_ia_sessions_exact > 0 else 0
                            dur = float(m_vals[1]) if len(m_vals) > 1 else 0
                            m, s = divmod(int(dur), 60)
                            dur_str = f"{m:02d}:{s:02d}" if dur >= 60 else f"{int(dur)}s"
                            
                            content_affinity.append({
                                "landing_page": lp, 
                                "sessions": sess_ia_est, 
                                "share_ia": f"{share_pct}%", 
                                "avg_duration": dur_str, 
                                "cluster": "researcher" if dur > 90 else "casual"
                            })
        except Exception as e:
            logger.error(f"Adobe Content Affinity failed: {e}")

        daily_trend = []
        try:
            req_daily = RunReportRequest(property_id=property_id, date_ranges=[{"start_date": start_date, "end_date": end_date}], dimensions=["date"], metrics=["sessions"], limit=5000)
            daily_report = await self.run_report(req_daily)
            ratio = known_ia_sessions_exact / total_sessions_abs if total_sessions_abs > 0 else 0
            for dr in daily_report.rows:
                rd = str(dr.get("date", ""))
                sess = float(dr.get("sessions", 0))
                pd_date, sk = rd, rd
                try:
                    from dateutil import parser
                    dt = parser.parse(rd)
                    pd_date, sk = dt.strftime('%Y-%m-%d'), dt.strftime('%Y%m%d')
                except: pass
                daily_trend.append({"date": pd_date, "sort_key": sk, "total_sessions": int(sess), "known_ia_sessions": int(sess * ratio)})
            daily_trend = sorted(daily_trend, key=lambda x: x['sort_key'])
            for d in daily_trend: d.pop('sort_key', None)
        except: pass

        # 9. Automated AI Insights (Powered by Gemini)
        insights = []
        try:
            import os
            from google import genai
            
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                client = genai.Client(api_key=api_key)
                lang_inst = "Responde en Español" if language == "es" else "Respond in English"
                prompt = f"""
                Analiza este reporte de 'Impacto IA' para la propiedad '{property_id}' y da 3 insights estratégicos breves.
                DATOS: Total {total_sessions_abs}, IA Conocida {known_ia_sessions_exact}, IA Inferida {inferred_ia}, SEO {total_organic}, Sniper Score {global_score}/100.
                REGLAS ESTRICTAS:
                - {lang_inst}
                - NO uses emojis.
                - NO incluyas introducciones ni saludos (ej. prohibido usar "Aquí tienes los hallazgos").
                - Ve directo al grano, escribiendo únicamente los 3 puntos solicitados.
                - No menciones marcas.
                """
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=prompt
                )
                if response and response.text:
                    for line in response.text.split('\n'):
                        line = line.strip()
                        if len(line) > 10:
                            # Remove leading bullets and numbers without breaking bold markdown
                            line = re.sub(r'^[\*\-]\s+', '', line)
                            line = re.sub(r'^\d+\.\s+', '', line)
                            insights.append(line)
                    insights = insights[:5]
            else: logger.warning("GEMINI_API_KEY not found.")
        except Exception as e: logger.error(f"Gemini error: {e}")

        # Índice de Confianza Dinámico
        confidence_index = CalculationService.calculate_confidence_index(known_ia_sessions_exact, total_sessions_abs)

        return {
            "battle_of_ais": sorted(battle_of_ais, key=lambda x: x['sessions'], reverse=True),
            "behavioral_clusters": {
                "definitions": {
                    "researcher": "Investigador Profundo (>90s, >1.5 pags)", 
                    "quick_answer": "Respuesta Rápida (<45s)", 
                    "transactional": "Alta Intención de Compra (Convertidor)"
                }, 
                "distribution": {str(k): int(v) for k, v in cluster_distribution.items()}
            },
            "inferred_traffic": {
                "total_sessions": inferred_ia, 
                "engagement_score": global_score, 
                "confidence_index": confidence_index,
                "s_baseline": s_baseline
            },
            "organic_traffic_stats": {"total_sessions": total_organic, "percentage_of_total": round((total_organic / total_sessions_abs * 100), 2) if total_sessions_abs > 0 else 0},
            "direct_traffic_stats": {"total_sessions": total_direct, "percentage_of_total": round((total_direct / total_sessions_abs * 100), 2) if total_sessions_abs > 0 else 0},
            "content_affinity": content_affinity,
            "ai_insights": insights,
            "daily_trend": daily_trend,
            "total_sessions": total_sessions_abs,
            "known_ia_sessions": known_ia_sessions_exact,
            "non_ia_sessions": max(0, total_sessions_abs - known_ia_sessions_exact - total_organic - total_direct),
            "date_range": {"start_date": start_date, "end_date": end_date}
        }

    async def analyze_url_performance(self, property_id: str, date_range: Dict[str, str], urls: List[str]) -> Dict[str, Any]:
        req = RunReportRequest(property_id=property_id, date_ranges=[{"start_date": date_range.get("start_date", "30daysAgo"), "end_date": date_range.get("end_date", "today")}], dimensions=["pagePath"], metrics=["sessions", "bounceRate", "userEngagementDuration", "conversions"], limit=10)
        try:
            report = await self.run_report(req)
            return {"daily_trend": [], "url_performance": report.rows, "traffic_sources_analysis": [], "summary": {"message": "Data loaded from Adobe proxy"}, "total_views": 0, "total_conversions": 0.0, "urls_analyzed": []}
        except: return {"daily_trend": [], "url_performance": [], "traffic_sources_analysis": [], "summary": {"error": "Error fetching data"}, "total_views": 0, "total_conversions": 0.0, "urls_analyzed": []}

    async def analyze_risk(self, property_id: str, start_date: str, end_date: str, break_even_roas: float) -> Dict[str, Any]:
        req = RunReportRequest(property_id=property_id, date_ranges=[{"start_date": start_date, "end_date": end_date}], dimensions=["date"], metrics=["conversions", "revenue", "sessions"])
        try:
            report = await self.run_report(req)
            vals = [float(r.get("revenue", 0)) for r in report.rows]
            mean_val = sum(vals) / len(vals) if vals else 0
            std_dev = math.sqrt(sum((x - mean_val) ** 2 for x in vals) / len(vals)) if vals else 0
            return {"campaign_audit": [], "risk_score": min(100, (std_dev / mean_val * 100)) if mean_val > 0 else 0, "variance_analysis": {"metric": "revenue", "mean": mean_val, "std_dev": std_dev}, "anomalies": []}
        except: return {"risk_score": 0, "variance_analysis": {}, "campaign_audit": []}

    async def analyze_ai_patterns(self, property_id: str, start_date: str, end_date: str) -> Dict[str, Any]: return {"matches": []}
    async def execute_advanced_report(self, property_id: str, report_type: str, start_date: str, end_date: str, config: Any = None) -> Dict[str, Any]: return {"rows": []}
    async def execute_funnel_analysis(self, property_id: str, steps: List[str], start_date: str, end_date: str) -> Dict[str, Any]: return {"funnel_steps": []}

    async def execute_deep_dive(self, property_id: str, start_date: str, end_date: str) -> Dict[str, Any]:
        req = RunReportRequest(property_id=property_id, date_ranges=[{"start_date": start_date, "end_date": end_date}], dimensions=["pagePath"], metrics=["sessions"], limit=5)
        try:
            r = await self.run_report(req)
            return {"sections": {"top_pages": {"rows": r.rows}}, "summary": "Deep Dive data", "date_range": {"start_date": start_date, "end_date": end_date}}
        except: return {"sections": {}, "summary": "Error", "date_range": {"start_date": start_date, "end_date": end_date}}

    async def audit_configuration(self, property_id: str) -> Dict[str, Any]: return {"audit_score": 100, "issues": [], "summary": f"Report Suite: {property_id}"}

    @staticmethod
    def _normalize_adobe_datetime(raw_value: Optional[str], is_end: bool = False) -> str:
        if not raw_value: return "today"
        import datetime, re
        today = datetime.date.today()
        val = raw_value
        if raw_value == "today": val = today
        elif "daysAgo" in raw_value:
            try: val = today - datetime.timedelta(days=int(re.sub(r'[^0-9]', '', raw_value)))
            except: val = today
        elif "yesterday" in raw_value: val = today - datetime.timedelta(days=1)
        str_val = val.strftime('%Y-%m-%d') if isinstance(val, (datetime.date, datetime.datetime)) else str(val)
        if len(str_val) == 10 and "-" in str_val:
             return f"{str_val}T23:59:59" if is_end else f"{str_val}T00:00:00"
        return str_val
