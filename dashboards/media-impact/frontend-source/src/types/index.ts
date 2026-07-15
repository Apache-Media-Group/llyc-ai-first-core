export interface AnalyticsState {
  market: string;
  days: number;
  from: string;
  to: string;
  connection_id: string;
  property_id: string;
  session_id?: string;
  account_id?: string;
  segment_id?: string;
  tenant_id?: string;
}

export interface ApiResponse {
  total_sessions: number;
  ai_referred: number;
  ai_inferred: number;
  engagement_score: number;
  visibility_score: number;
  sentiment_score: number;
  [key: string]: any;
}
