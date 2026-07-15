import logging
import math
import pandas as pd
from typing import Dict, Any, List
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    DateRange,
    Dimension,
    Metric,
    FilterExpression,
    Filter,
    OrderBy
)
from google.api_core.exceptions import GoogleAPICallError
from app.services.mcp_analytics.calculation_service import calculate_ratio, calculate_conversion_rate, CalculationService

logger = logging.getLogger(__name__)

class GATrafficIAService:
    def __init__(self, credentials=None, client=None):
        if client:
            self.client = client
        else:
            self.client = BetaAnalyticsDataClient(credentials=credentials)
        
        # 1. Deterministic AI Sources (The "Known" List)
        self.ai_referrers = [
            "chatgpt.com", "perplexity.ai", "gemini.google.com", "copilot.microsoft.com", "claude.ai", 
            "chatgpt", "perplexity", "gemini", "copilot", "claude"
        ]
        
        # 2. AI UTM Patterns
        self.ai_utm_patterns = [
            "utm_source=ai", "utm_medium=ai", "utm_campaign=ai",
            "utm_source=chatbot", "utm_medium=referral_ai"
        ]

    async def analyze_traffic_ia(self, property_id: str, date_range: Dict[str, str], language: str = "es") -> Dict[str, Any]:
        """
        Ejecuta el análisis avanzado de 'Audit de Audiencia IA' para GA4.
        """
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"
            
        logger.info(f"Starting ADVANCED AI PROFILING for {property_id}")
        
        df_aggregated = self._fetch_aggregated_ai_data(property_id, date_range)
        if df_aggregated.empty:
            raise ValueError("No data available for analysis")
        
        df_granular = self._fetch_granular_data(property_id, date_range)
        df_aggregated = self._tag_traffic_sources(df_aggregated)
        df_granular = self._tag_traffic_sources(df_granular)
        
        # --- NUEVO: Cálculo del Baseline del Site ---
        total_sessions = int(df_aggregated['sessions'].sum())
        total_dur = df_aggregated['userEngagementDuration'].sum()
        total_views = df_aggregated['screenPageViews'].sum()
        total_conv = df_aggregated['conversions'].sum()
        
        avg_dur_base = total_dur / total_sessions if total_sessions > 0 else 0
        pages_base = total_views / total_sessions if total_sessions > 0 else 0
        
        s_baseline = CalculationService.calculate_sniper_score(total_conv, avg_dur_base, pages_base)
        
        battle_of_ais = self._analyze_battle_of_ais(df_aggregated, s_baseline)
        battle_of_ais_total_sessions = sum(item['sessions'] for item in battle_of_ais)
        
        # --- CORRECCIÓN: Clusters sobre sesiones IA ---
        ai_granular = df_granular[df_granular['is_known_ai']].copy()
        if not ai_granular.empty:
            ai_granular = self._assign_behavioral_clusters(ai_granular)
            cluster_distribution = ai_granular.groupby('cluster')['sessions'].sum().to_dict()
        else:
            cluster_distribution = {"casual": 0, "researcher": 0, "quick_answer": 0, "transactional": 0}

        df_granular = self._assign_behavioral_clusters(df_granular)
        inference_results = self._infer_hidden_ai_traffic(df_granular, s_baseline)
        
        content_affinity = self._analyze_content_affinity(df_granular, total_ai_sessions=int(battle_of_ais_total_sessions))
        daily_trend = self._fetch_evolutionary_data(property_id, date_range)
        
        known_ia_sessions = int(battle_of_ais_total_sessions)
        inferred_ia_sessions = int(inference_results["total_inferred_sessions"])
        
        organic_df = df_aggregated[(df_aggregated['medium'] == 'organic') & 
                                   (~df_aggregated['source'].str.contains('cpc|ads|syndication|doubleclick', na=False))]
        total_organic_sessions = int(organic_df['sessions'].sum()) if not organic_df.empty else 0
        organic_percentage = (total_organic_sessions / total_sessions * 100) if total_sessions > 0 else 0
        
        direct_df = df_aggregated[(df_aggregated['source'].isin(['(direct)', 'direct'])) | (df_aggregated['medium'].isin(['(none)', 'none']))]
        total_direct_sessions = int(direct_df['sessions'].sum()) if not direct_df.empty else 0
        direct_percentage = (total_direct_sessions / total_sessions * 100) if total_sessions > 0 else 0
        
        # 9. Automated AI Insights (GA4 + Gemini)
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
                DATOS: Total {total_sessions}, IA Conocida {known_ia_sessions}, IA Inferida {inferred_ia_sessions}, SEO {total_organic_sessions}, Sniper Score {inference_results['engagement_score']}/100.
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
                            import re
                            line = re.sub(r'^[\*\-]\s+', '', line)
                            line = re.sub(r'^\d+\.\s+', '', line)
                            insights.append(line)
                    insights = insights[:5]
            else: logger.warning("GEMINI_API_KEY not found.")
        except Exception as e: logger.error(f"Gemini GA4 error: {e}")

        # --- NUEVO: Índice de Confianza Dinámico ---
        confidence_index = CalculationService.calculate_confidence_index(known_ia_sessions, total_sessions)
        
        return self._safe_serialize({
            "battle_of_ais": battle_of_ais,
            "behavioral_clusters": {
                "definitions": {
                    "researcher": "Investigador Profundo (>90s, >1.5 pags)",
                    "quick_answer": "Respuesta Rápida (<45s)",
                    "transactional": "Alta Intención de Compra (Convertidor)"
                },
                "distribution": {str(k): int(v) for k, v in cluster_distribution.items()}
            },
            "inferred_traffic": {
                "total_sessions": inferred_ia_sessions,
                "confidence_index": confidence_index,
                "engagement_score": inference_results["engagement_score"],
                "s_baseline": s_baseline
            },
            "content_affinity": content_affinity,
            "ai_insights": insights,
            "total_sessions": total_sessions,
            "known_ia_sessions": known_ia_sessions,
            "non_ia_sessions": max(0, total_sessions - known_ia_sessions - inferred_ia_sessions - total_organic_sessions - total_direct_sessions),
            "organic_traffic_stats": {
                "total_sessions": total_organic_sessions,
                "percentage_of_total": round(organic_percentage, 2)
            },
            "direct_traffic_stats": {
                "total_sessions": total_direct_sessions,
                "percentage_of_total": round(direct_percentage, 2)
            },
            "daily_trend": daily_trend,
            "date_range": date_range
        })

    def analyze_url_performance(self, property_id: str, date_range: Dict[str, str], urls: List[str]) -> Dict[str, Any]:
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"
        cleaned_urls = [u.strip() for u in urls if u.strip()]
        from google.analytics.data_v1beta.types import FilterExpressionList
        expressions = [FilterExpression(filter=Filter(field_name="landingPagePlusQueryString", string_filter=Filter.StringFilter(value=val, match_type=Filter.StringFilter.MatchType.CONTAINS))) for val in cleaned_urls]
        filter_expression = FilterExpression(or_group=FilterExpressionList(expressions=expressions))
        request_daily = RunReportRequest(property=property_id, date_ranges=[DateRange(start_date=date_range["start_date"], end_date=date_range["end_date"])], dimensions=[Dimension(name="date"), Dimension(name="landingPagePlusQueryString")], metrics=[Metric(name="screenPageViews"), Metric(name="conversions"), Metric(name="sessions"), Metric(name="userEngagementDuration"), Metric(name="bounceRate")], dimension_filter=filter_expression, order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))])
        response_daily = self.client.run_report(request_daily)
        daily_data = []
        url_stats = {}
        for row in response_daily.rows:
            date, url = row.dimension_values[0].value, row.dimension_values[1].value
            views, conversions, sessions, engagement, bounce = int(row.metric_values[0].value), float(row.metric_values[1].value), int(row.metric_values[2].value), float(row.metric_values[3].value), float(row.metric_values[4].value)
            daily_data.append({"date": date, "views": views, "conversions": conversions, "sessions": sessions, "engagement_duration": engagement, "bounce_rate": bounce})
            if url not in url_stats: url_stats[url] = {"views": 0, "conversions": 0.0, "sessions": 0, "avg_engagement": 0.0, "bounce_rate": 0.0}
            url_stats[url]["views"] += views
            url_stats[url]["conversions"] += conversions
            url_stats[url]["sessions"] += sessions
            url_stats[url]["avg_engagement"] += engagement
        url_performance = []
        for url, stats in url_stats.items():
            url_performance.append({"url": url, "views": stats["views"], "conversions": stats["conversions"], "sessions": stats["sessions"], "conversion_rate": round((stats["conversions"]/stats["views"]*100) if stats["views"]>0 else 0, 2), "avg_engagement_duration": round(stats["avg_engagement"]/len(daily_data) if daily_data else 0, 1), "views_per_session": round(stats["views"]/stats["sessions"] if stats["sessions"]>0 else 0, 2)})
        return {"daily_trend": daily_data, "url_performance": sorted(url_performance, key=lambda x: x["conversions"], reverse=True), "summary": {"total_views": sum(u['views'] for u in url_performance), "period": f"{date_range['start_date']} to {date_range['end_date']}"}}

    def _fetch_evolutionary_data(self, property_id: str, date_range: Dict[str, str]) -> List[Dict[str, Any]]:
        request = RunReportRequest(property=property_id, date_ranges=[DateRange(start_date=date_range["start_date"], end_date=date_range["end_date"])], dimensions=[Dimension(name="date"), Dimension(name="sessionSource"), Dimension(name="sessionMedium")], metrics=[Metric(name="sessions"), Metric(name="userEngagementDuration"), Metric(name="screenPageViews"), Metric(name="conversions")], order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))])
        response = self.client.run_report(request)
        daily_stats = {}
        for row in response.rows:
            date_str, source, medium, sessions = row.dimension_values[0].value, row.dimension_values[1].value.lower(), row.dimension_values[2].value.lower(), int(row.metric_values[0].value)
            if date_str not in daily_stats: daily_stats[date_str] = {"date": date_str, "total_sessions": 0, "known_ia_sessions": 0, "inferred_ia_sessions": 0}
            daily_stats[date_str]["total_sessions"] += sessions
            if any(ref in source for ref in self.ai_referrers): daily_stats[date_str]["known_ia_sessions"] += sessions
            else:
                dur, views, conv = float(row.metric_values[1].value)/sessions if sessions>0 else 0, int(row.metric_values[2].value)/sessions if sessions>0 else 0, float(row.metric_values[3].value)
                if (conv==0 and dur>90 and views>=1.5) or (conv==0 and dur<45 and views<1.5):
                    if medium in ['organic', 'referral', '(none)', 'direct']: daily_stats[date_str]["inferred_ia_sessions"] += int(sessions * 0.3)
        return [{"date": d["date"], "total_sessions": int(d["total_sessions"]), "known_ia_sessions": int(d["known_ia_sessions"]), "inferred_ia_sessions": int(d["inferred_ia_sessions"])} for d in sorted(daily_stats.values(), key=lambda x: x["date"])]

    def _safe_serialize(self, obj: Any) -> Any:
        if isinstance(obj, dict): return {k: self._safe_serialize(v) for k, v in obj.items()}
        if isinstance(obj, list): return [self._safe_serialize(x) for x in obj]
        if isinstance(obj, float): return 0.0 if math.isnan(obj) or math.isinf(obj) else float(obj)
        if isinstance(obj, (np.int64, np.int32, np.integer)): return int(obj)
        if isinstance(obj, (np.float64, np.float32, np.floating)): return 0.0 if np.isnan(obj) or np.isinf(obj) else float(obj)
        return obj

    def _fetch_granular_data(self, property_id: str, date_range: Dict[str, str]) -> pd.DataFrame:
        request = RunReportRequest(property=property_id, date_ranges=[DateRange(start_date=date_range["start_date"], end_date=date_range["end_date"])], dimensions=[Dimension(name="sessionSource"), Dimension(name="sessionMedium"), Dimension(name="landingPagePlusQueryString"), Dimension(name="deviceCategory")], metrics=[Metric(name="sessions"), Metric(name="engagedSessions"), Metric(name="userEngagementDuration"), Metric(name="screenPageViews"), Metric(name="conversions")], order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)], limit=15000)
        response = self.client.run_report(request)
        data = []
        for row in response.rows:
            sess = int(float(row.metric_values[0].value))
            if sess == 0: continue
            dur, views = float(row.metric_values[2].value), int(float(row.metric_values[3].value))
            data.append({"source": row.dimension_values[0].value.lower(), "medium": row.dimension_values[1].value.lower(), "landing_page": row.dimension_values[2].value, "device": row.dimension_values[3].value, "sessions": sess, "engaged_sessions": int(float(row.metric_values[1].value)), "userEngagementDuration": dur, "screenPageViews": views, "conversions": float(row.metric_values[4].value), "avg_duration": dur/sess, "pages_per_session": views/sess, "conversion_rate": (float(row.metric_values[4].value)/sess)*100})
        return pd.DataFrame(data)

    def _fetch_aggregated_ai_data(self, property_id: str, date_range: Dict[str, str]) -> pd.DataFrame:
        request = RunReportRequest(property=property_id, date_ranges=[DateRange(start_date=date_range["start_date"], end_date=date_range["end_date"])], dimensions=[Dimension(name="sessionSource"), Dimension(name="sessionMedium"), Dimension(name="deviceCategory")], metrics=[Metric(name="sessions"), Metric(name="engagedSessions"), Metric(name="userEngagementDuration"), Metric(name="screenPageViews"), Metric(name="conversions")], order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)], limit=10000)
        response = self.client.run_report(request)
        data = []
        for row in response.rows:
            sess = int(float(row.metric_values[0].value))
            if sess == 0: continue
            dur, views = float(row.metric_values[2].value), int(float(row.metric_values[3].value))
            data.append({"source": row.dimension_values[0].value.lower(), "medium": row.dimension_values[1].value.lower(), "device": row.dimension_values[2].value, "sessions": sess, "engaged_sessions": int(float(row.metric_values[1].value)), "userEngagementDuration": dur, "screenPageViews": views, "conversions": float(row.metric_values[4].value), "avg_duration": dur/sess, "pages_per_session": views/sess, "conversion_rate": (float(row.metric_values[4].value)/sess)*100})
        return pd.DataFrame(data)

    def _tag_traffic_sources(self, df: pd.DataFrame) -> pd.DataFrame:
        df['is_known_ai'] = df['source'].apply(lambda s: any(ref in s for ref in self.ai_referrers))
        def normalize_name(s):
            if "openai" in s or "chatgpt" in s: return "ChatGPT"
            if "copilot" in s: return "Copilot"
            if "gemini" in s or "bard" in s: return "Gemini"
            if "perplexity" in s: return "Perplexity"
            if "claude" in s or "anthropic" in s: return "Claude"
            return "Other AI"
        df['ai_platform'] = df.apply(lambda r: normalize_name(r['source']) if r['is_known_ai'] else None, axis=1)
        return df

    def _analyze_battle_of_ais(self, df: pd.DataFrame, s_baseline: float = 1.0) -> List[Dict]:
        ai_df = df[df['is_known_ai']].copy()
        if ai_df.empty: return []
        results = []
        for platform in ai_df['ai_platform'].unique():
            p_data = ai_df[ai_df['ai_platform'] == platform]
            sess, dur_mass, views_mass = p_data['sessions'].sum(), p_data['userEngagementDuration'].sum(), p_data['screenPageViews'].sum()
            
            # --- NUEVO: Umbral mínimo de 10 sesiones ---
            if sess < 10:
                results.append({
                    "platform": platform, 
                    "sessions": int(sess), 
                    "avg_duration": "N/A", 
                    "pages_per_session": 0, 
                    "conversions": int(p_data['conversions'].sum()),
                    "conversion_rate": "0%", 
                    "engagement_score": 0,
                    "relative_ratio": 0,
                    "ratio_label": "N/A — muestra insuficiente"
                })
                continue

            avg_dur, avg_depth, cv_rate = calculate_ratio(dur_mass, sess, decimals=1), calculate_ratio(views_mass, sess, decimals=2), calculate_conversion_rate(p_data['conversions'].sum(), sess, decimals=2)
            
            # --- NUEVO: Sniper Score centralizado y Ratio Relativo ---
            sniper = CalculationService.calculate_sniper_score(p_data['conversions'].sum(), avg_dur, avg_depth)
            relative_ratio = round(sniper / s_baseline, 2) if s_baseline > 0 else 1.0
            
            ratio_label = "intención similar a la media"
            if relative_ratio >= 1.30: ratio_label = "intención 30% superior a la media"
            elif relative_ratio >= 1.10: ratio_label = "intención por encima de la media"
            elif relative_ratio < 0.90: ratio_label = "intención por debajo de la media"

            m, s = divmod(int(avg_dur), 60)
            results.append({
                "platform": platform, 
                "sessions": int(sess), 
                "avg_duration": f"{m:02d}:{s:02d}" if avg_dur>=60 else f"{int(avg_dur)}s", 
                "pages_per_session": round(avg_depth, 2), 
                "conversions": int(p_data['conversions'].sum()),
                "conversion_rate": f"{cv_rate}%", 
                "engagement_score": sniper,
                "relative_ratio": relative_ratio,
                "ratio_label": f"{relative_ratio}x — {ratio_label}"
            })
        return sorted(results, key=lambda x: x['sessions'], reverse=True)

    def _assign_behavioral_clusters(self, df: pd.DataFrame) -> pd.DataFrame:
        def classify(row):
            if row['conversions'] > 0: return 'transactional'
            if row['avg_duration'] > 90 and row['pages_per_session'] >= 1.5: return 'researcher'
            if row['avg_duration'] < 45 and row['pages_per_session'] < 1.5: return 'quick_answer'
            return 'casual'
        df['cluster'] = df.apply(classify, axis=1)
        return df

    def _infer_hidden_ai_traffic(self, df: pd.DataFrame, s_baseline: float = 1.0) -> Dict:
        target_df = df[df['medium'].isin(['organic', 'referral', '(none)', 'direct']) & ~df['is_known_ai']].copy()
        cluster_stats = target_df.groupby('cluster')['sessions'].sum().to_dict()
        inferred_sess = cluster_stats.get('researcher', 0)*0.4 + cluster_stats.get('quick_answer', 0)*0.2
        relevant_df = target_df[target_df['cluster'].isin(['researcher', 'quick_answer'])]
        if not relevant_df.empty:
            s_mass, d_mass, v_mass, c_mass = relevant_df['sessions'].sum(), relevant_df['userEngagementDuration'].sum(), relevant_df['screenPageViews'].sum(), relevant_df['conversions'].sum()
            avg_dur, pages_per, cvr = d_mass/s_mass, v_mass/s_mass, (c_mass/s_mass)*100
            # --- Score centralizado ---
            score = CalculationService.calculate_sniper_score(c_mass, avg_dur, pages_per)
        else: avg_dur, pages_per, cvr, score = 0, 0, 0, 0.0
        
        source_stats = relevant_df.groupby('source').agg({'sessions': 'sum', 'userEngagementDuration': 'sum', 'screenPageViews': 'sum', 'conversions': 'sum'}).reset_index()
        top_sources = []
        for _, r in source_stats.sort_values('sessions', ascending=False).head(10).iterrows():
            s_s, s_d, s_p, s_c = int(r['sessions']), r['userEngagementDuration']/r['sessions'], r['screenPageViews']/r['sessions'], (r['conversions']/r['sessions'])*100
            # --- Score centralizado ---
            top_sources.append({
                "source": r['source'], 
                "sessions": s_s, 
                "avg_duration": round(float(s_d), 1), 
                "pages_per_session": round(float(s_p), 2), 
                "conversions": int(r['conversions']),
                "conversion_rate": round(float(s_c), 2), 
                "engagement_score": CalculationService.calculate_sniper_score(r['conversions'], s_d, s_p)
            })
        
        # --- Nota: La confianza se calcula ahora en analyze_traffic_ia usando CalculationService ---
        return {"cluster_distribution": {str(k): int(v) for k, v in cluster_stats.items()}, "total_inferred_sessions": int(inferred_sess), "avg_duration": round(float(avg_dur), 1), "pages_per_session": round(float(pages_per), 2), "conversion_rate": round(float(cvr), 2), "engagement_score": round(float(score), 1), "top_sources": top_sources}

    def _analyze_content_affinity(self, df: pd.DataFrame, total_ai_sessions: int = 1) -> List[Dict]:
        # Filtrar solo si es IA conocida para el share real
        ai_known_df = df[df['is_known_ai']].copy()
        if ai_known_df.empty: return []
        
        top = ai_known_df.groupby('landing_page').agg({'sessions': 'sum', 'userEngagementDuration': 'mean', 'cluster': lambda x: x.mode().iloc[0] if not x.mode().empty else 'casual'}).sort_values('sessions', ascending=False).head(10).reset_index()
        res = []
        for _, r in top.iterrows():
            s, d = int(r['sessions']), float(r['userEngagementDuration'])
            m, sc = divmod(int(d), 60)
            res.append({"landing_page": str(r['landing_page']), "sessions": s, "share_ia": f"{round((s/total_ai_sessions)*100, 1) if total_ai_sessions>0 else 0}%", "avg_duration": f"{m:02d}:{sc:02d}" if d>=60 else f"{int(d)}s", "cluster": str(r['cluster'])})
        return res

    def _calculate_sniper_score(self, conversion_rate: float, avg_duration: float, pages_per_session: float, engaged_sessions: int = 0, total_sessions: int = 1) -> float:
        # Wrapper para mantener compatibilidad si se llama internamente, pero redirigido a central
        return CalculationService.calculate_sniper_score(1 if conversion_rate > 0 else 0, avg_duration, pages_per_session)
