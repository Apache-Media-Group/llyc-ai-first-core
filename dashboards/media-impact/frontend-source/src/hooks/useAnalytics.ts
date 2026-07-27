import { useState, useCallback } from 'react';
import type { AnalyticsState, ApiResponse } from '../types';
import { secureFetch } from '../services/apiClient';

const getInitialDates = () => {
  const today = new Date();
  const ninetyDaysAgo = new Date();
  ninetyDaysAgo.setDate(today.getDate() - 90);
  return {
    from: ninetyDaysAgo.toISOString().split('T')[0],
    to: today.toISOString().split('T')[0]
  };
};

const dates = getInitialDates();

export const useAnalytics = () => {
  const [state, setState] = useState<AnalyticsState>({
    market: 'all',
    days: 90,
    from: dates.from,
    to: dates.to,
    connection_id: '',
    property_id: '',
    account_id: '',
    segment_id: '',
    tenant_id: '',
  });

  const [data, setData] = useState<ApiResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (overrides?: Partial<AnalyticsState>) => {
    const currentState = { ...state, ...overrides };
    if (!currentState.connection_id && !currentState.property_id) return;

    setLoading(true);
    setError(null);
    try {
      const response = await secureFetch('/api/v1/mcp-analytics/run-report', {
        method: 'POST',
        body: JSON.stringify({
          connection_id: currentState.connection_id,
          property_id: currentState.property_id,
          session_id: currentState.session_id,
          date_ranges: [{ start_date: currentState.from, end_date: currentState.to }],
          market: currentState.market,
          segment_id: currentState.segment_id || undefined,
          tenant_id: currentState.tenant_id || undefined,
          live_api: currentState.live_api || undefined
        })
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'API Error');
      }

      const result = await response.json();
      
      // Parsear la estructura de RunReportResponse a ApiResponse plano esperado por App.tsx
      if (result && result.rows && result.rows.length > 0) {
        let total_sessions = 0;
        let ai_referred = 0;
        let ai_inferred = 0;
        let engagement_sum = 0;
        let valid_engagement_days = 0;
        let visibility_sum = 0;
        let sentiment_sum = 0;
        let count = result.rows.length;
        
        result.rows.forEach((row: any) => {
          total_sessions += parseInt(row.sessions || row.total_sessions || '0', 10);
          ai_referred += parseFloat(row.ai_referred || row.known_ia_sessions || '0');
          ai_inferred += parseFloat(row.ai_inferred || row.inferred_ia_sessions || '0');
          
          const rowEngagement = parseFloat(row.engagement_score || row.conversions || '0');
          if (rowEngagement > 0) {
            engagement_sum += rowEngagement;
            valid_engagement_days++;
          }
          
          visibility_sum += parseFloat(row.visibility_score || '0');
          sentiment_sum += parseFloat(row.sentiment_score || '0');
        });
        
        const mappedData: ApiResponse = {
          total_sessions: total_sessions,
          ai_referred: Math.round(ai_referred * 10) / 10,
          ai_inferred: Math.round(ai_inferred * 10) / 10,
          engagement_score: valid_engagement_days > 0 ? Math.round(engagement_sum / valid_engagement_days) : 0,
          visibility_score: count > 0 ? Math.round((visibility_sum / count) * 10) / 10 : 0,
          sentiment_score: count > 0 ? Math.round((sentiment_sum / count) * 10) / 10 : 0,
          rows: result.rows,
          row_count: result.row_count || count,
          total_monitored_domains: result.metadata?.total_monitored_domains || 0,
          competitors: result.metadata?.competitors || [],
          topics_pr: result.metadata?.topics_pr || [],
          topics_digital: result.metadata?.topics_digital || [],
          domains: result.metadata?.domains || [],
          visibility_by_engine: result.metadata?.visibility_by_engine || [],
          behavior_clusters: result.metadata?.behavioral_clusters?.distribution ? [
            { label: 'Investigación', value: result.metadata.behavioral_clusters.distribution.researcher || 0 },
            { label: 'Respuesta Rápida', value: result.metadata.behavioral_clusters.distribution.quick_answer || 0 },
            { label: 'Transaccional', value: result.metadata.behavioral_clusters.distribution.transactional || 0 },
            { label: 'Casual', value: result.metadata.behavioral_clusters.distribution.casual || 0 }
          ] : undefined
        };
        
        setData(mappedData);
      } else if (result && typeof result.total_sessions !== 'undefined') {
        // Fallback si la respuesta ya venía mapeada de forma plana
        setData(result);
      } else {
        setData(null);
      }
    } catch (err: any) {
      console.error("Fetch error:", err);
      setError(err.message);
      // Fallback or keep old data
    } finally {
      setLoading(false);
    }
  }, [state]);

  const updateState = (updates: Partial<AnalyticsState>) => {
    setState(prev => ({ ...prev, ...updates }));
  };

  return { state, data, loading, error, fetchData, updateState };
};
