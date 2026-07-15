// frontend/src/components/admin/types.ts

export interface TenantConfig {
  tenant_id: string;
  tenant_name: string;
  logo_url: string;
  primary_color: string;
  secondary_color: string;
  font_family: string;
  support_email: string;
  authorized_emails?: string[];
  authorized_domains?: string[];
  updated_at?: string;
  configured_secrets?: {
    'brandlight-key'?: boolean;
    'peec-key'?: boolean;
    'ga4-creds'?: boolean;
    'adobe-creds'?: boolean;
  };
  deployment_status?: {
    status?: 'deploying' | 'success' | 'failed';
    step?: string;
    message?: string;
    updated_at?: string;
  };
}

export const API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' 
  ? 'http://localhost:8080' 
  : '';
