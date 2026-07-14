// LLYC Intelligence Dashboard App - React Frontend (Branded Multisite)
import React, { useState, useEffect, useCallback, useRef } from 'react';
import html2canvas from 'html2canvas';
import { jsPDF } from 'jspdf';
import { WelcomeScreen } from './components/WelcomeScreen';
import { ClientLoginScreen } from './components/ClientLoginScreen';
import { Header, FilterBar } from './components/DashboardLayout';
import { KpiCard } from './components/KpiCard';
import { ChartWidget } from './components/ChartWidget';
import { TopicsCard } from './components/TopicsCard';
import { DomainsTable } from './components/DomainsTable';
import { useAnalytics } from './hooks/useAnalytics';
import { AdminPanel } from './components/AdminPanel';
import { onAuthStateChanged } from 'firebase/auth';
import { auth } from './firebase';
import { Database } from 'lucide-react';
import { secureFetch, API_BASE_URL } from './services/apiClient';

// CI Trigger: Rebuild to inject new Firebase secrets

interface TenantConfig {
  tenant_id: string;
  tenant_name: string;
  logo_url: string;
  primary_color: string;
  secondary_color: string;
  font_family: string;
  support_email: string;
  updated_at?: string;
  configured_secrets?: {
    'brandlight-key'?: boolean;
    'peec-key'?: boolean;
    'ga4-creds'?: boolean;
    'adobe-creds'?: boolean;
  };
}

export const getTenantFromUrl = (): string | null => {
  // 1. Detección por query param
  const urlParams = new URLSearchParams(window.location.search);
  const tenantParam = urlParams.get('tenant_id') || urlParams.get('tenant');
  if (tenantParam) {
    return tenantParam.toLowerCase().trim();
  }

  // 2. Detección por path name (ej: /media-impact/sanitas o /media-impact/sanitas/)
  const path = window.location.pathname;
  if (path.startsWith('/media-impact')) {
    const relativePath = path.substring('/media-impact'.length);
    const segments = relativePath.split('/').filter(s => s.length > 0);
    if (segments.length > 0) {
      const firstSegment = segments[0].toLowerCase().trim();
      const reserved = ['admin', 'assets', 'favicon.svg', 'logo_llyc.svg', 'icons.svg', 'index.html'];
      if (!reserved.includes(firstSegment)) {
        return firstSegment;
      }
    }
  }

  // 3. Detección por subdominio (producción)
  const host = window.location.hostname;
  if (host && host !== 'localhost' && host !== '127.0.0.1' && !host.endsWith('web.app')) {
    const parts = host.split('.');
    if (parts.length > 2) {
      const sub = parts[0].toLowerCase().trim();
      if (sub !== 'www' && sub !== 'dashboard' && sub !== 'analytics') {
        return sub;
      }
    }
  }

  return null;
};

const App: React.FC = () => {
  const { state, data, loading, fetchData, updateState } = useAnalytics();
  const [lastUpdated, setLastUpdated] = useState('--:--');
  const [exporting, setExporting] = useState(false);
  const dashboardRef = useRef<HTMLDivElement>(null);
  const [isAdminView, setIsAdminView] = useState(false);
  
  // Estados de autenticación seguros y verificados por Firebase SDK
  const [adminUserEmail, setAdminUserEmail] = useState<string | null>(null);
  const [currentUserEmail, setCurrentUserEmail] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  
  const [tenant, setTenant] = useState<TenantConfig>({
    tenant_id: 'llyc',
    tenant_name: 'LLYC Intelligence',
    logo_url: `${import.meta.env.BASE_URL}logo_llyc.svg`,
    primary_color: '#F54963',
    secondary_color: '#36A7B7',
    font_family: 'Montserrat, sans-serif',
    support_email: 'intelligence.mcp@llyc.global'
  });

  // Estados de autorización de inquilino para clientes
  const [isTenantAuthorized, setIsTenantAuthorized] = useState<boolean | null>(null);
  const [verifyingAccess, setVerifyingAccess] = useState(false);
  const [is2faRequired, setIs2faRequired] = useState(false);

  // Inicializa showDashboard en true si se accede con un tenant específico en la URL o subdominio
  const [showDashboard, setShowDashboard] = useState(() => {
    const detected = getTenantFromUrl();
    if (detected && detected !== 'llyc') {
      return true;
    }
    return false;
  });

  // 1. Observador de estado de Auth oficial de Firebase para mantener consistencia de login
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      if (user) {
        const email = user.email || '';
        const emailLower = email.toLowerCase();
        setCurrentUserEmail(emailLower);
        
        if (emailLower.endsWith('@llyc.global') || emailLower.endsWith('@llyc.ai')) {
          setAdminUserEmail(emailLower);
          localStorage.setItem('admin_user_email', emailLower);
        } else {
          setAdminUserEmail(null);
          localStorage.removeItem('admin_user_email');
        }
      } else {
        setCurrentUserEmail(null);
        setAdminUserEmail(null);
        localStorage.removeItem('admin_user_email');
      }
      setAuthLoading(false);
    });
    return () => unsubscribe();
  }, []);

  // 1.1. Verificar acceso del usuario actual al inquilino seleccionado
  useEffect(() => {
    if (!showDashboard || !tenant?.tenant_id) return;

    if (!currentUserEmail) {
      setIsTenantAuthorized(false);
      setIs2faRequired(false);
      return;
    }

    const checkAccess = async () => {
      try {
        setVerifyingAccess(true);
        const res = await secureFetch(`/api/v1/mcp-analytics/tenant/verify?tenant=${tenant.tenant_id}`);
        if (res.ok) {
          const result = await res.json();
          if (result.authorized) {
            setIsTenantAuthorized(true);
            setIs2faRequired(false);
          } else if (result['2fa_required']) {
            setIs2faRequired(true);
            setIsTenantAuthorized(false);
          } else {
            setIsTenantAuthorized(false);
            setIs2faRequired(false);
          }
        } else {
          setIsTenantAuthorized(false);
          setIs2faRequired(false);
        }
      } catch (err) {
        console.error("Error verificando acceso al inquilino:", err);
        setIsTenantAuthorized(false);
        setIs2faRequired(false);
      } finally {
        setVerifyingAccess(false);
      }
    };

    checkAccess();
  }, [showDashboard, currentUserEmail, tenant?.tenant_id]);

  // 2. Guardia de Ruta Estricto en el Ruteo Nativo de la SPA
  useEffect(() => {
    const handleLocationChange = () => {
      const isHashAdmin = window.location.hash === '#admin' || window.location.pathname === '/admin';
      
      if (isHashAdmin) {
        // Evitar falsos negativos o expulsiones prematuras mientras Firebase Auth está inicializándose
        if (authLoading) return;
        
        // Verificar si existe una sesión de administrador corporativo LLYC activa y verificada
        const isLlycEmail = adminUserEmail && (adminUserEmail.endsWith('@llyc.global') || adminUserEmail.endsWith('@llyc.ai'));
        
        if (!isLlycEmail) {
          // Bloquear el renderizado y expulsar inmediatamente a la landing
          window.location.hash = '';
          setIsAdminView(false);
          alert("Acceso denegado: Se requiere iniciar sesión con una cuenta corporativa de LLYC (@llyc.global o @llyc.ai) para acceder al panel de administración.");
        } else {
          setIsAdminView(true);
          setAdminPreviewTenant(null); // Limpiar modo vista previa al volver al panel de admin
        }
      } else {
        setIsAdminView(false);
      }
    };
    
    // Ejecutar chequeo en la carga inicial
    handleLocationChange();
    
    window.addEventListener('popstate', handleLocationChange);
    window.addEventListener('hashchange', handleLocationChange);
    
    return () => {
      window.removeEventListener('popstate', handleLocationChange);
      window.removeEventListener('hashchange', handleLocationChange);
    };
  }, [adminUserEmail, authLoading]);

  const [adminPreviewTenant, setAdminPreviewTenant] = useState<string | null>(null);

  const handlePreviewTenant = async (tenantId: string) => {
    try {
      const res = await secureFetch(`/api/v1/mcp-analytics/tenant/config?tenant=${tenantId}`);
      if (res.ok) {
        const data: TenantConfig = await res.json();
        setTenant(data);
        
        // Aplicar la paleta de colores de marca dinámicamente en el documento
        if (data.primary_color) {
          document.documentElement.style.setProperty('--red', data.primary_color);
          document.documentElement.style.setProperty('--red-light', data.primary_color + '1A');
        }
        if (data.secondary_color) {
          document.documentElement.style.setProperty('--teal', data.secondary_color);
          document.documentElement.style.setProperty('--teal-light', data.secondary_color + '1A');
        }
        
        // Activar el modo de vista previa de administrador
        setAdminPreviewTenant(data.tenant_name);
        setIsAdminView(false);
        setShowDashboard(true);
        updateState({
          tenant_id: data.tenant_id,
          connection_id: '',
          property_id: ''
        });
      }
    } catch (err) {
      console.error("Error setting preview tenant:", err);
    }
  };

  const handleGoToDashboard = () => {
    window.location.hash = '';
    setIsAdminView(false);
    setAdminPreviewTenant(null); // Limpiar modo vista previa al volver de forma normal
    setShowDashboard(true); // Saltar WelcomeScreen al volver de admin
  };


  // Orígenes de datos, Cuentas, Propiedades y Segmentos
  const [connections, setConnections] = useState<any[]>([]);
  const [accounts, setAccounts] = useState<any[]>([]);
  const [properties, setProperties] = useState<any[]>([]);
  const [segments, setSegments] = useState<any[]>([]);

  // 1. Efecto secundario dinámico para buscar si este Tenant tiene conexiones personalizadas en GCP Secret Manager
  useEffect(() => {
    if (tenant?.configured_secrets) {
      const list: any[] = [];
      const sec = tenant.configured_secrets;
      if (sec['ga4-creds']) {
        list.push({ connection_id: 'local', display_name: 'Google Analytics 4', platform: 'GA4' });
      }
      if (sec['adobe-creds']) {
        list.push({ connection_id: 'adobe-temp', display_name: 'Adobe Analytics', platform: 'ADOBE_ANALYTICS' });
      }
      if (sec['peec-key']) {
        list.push({ connection_id: 'peec-temp', display_name: 'Peec.ai (Comportamiento)', platform: 'PEEC' });
      }
      if (sec['brandlight-key']) {
        list.push({ connection_id: 'brandlight-temp', display_name: 'Brandlight (Visibilidad)', platform: 'BRANDLIGHT' });
      }
      setConnections(list);
      
      // Auto-select the first valid general connection
      const generalConnections = list.filter(c => c.platform === 'GA4' || c.platform === 'ADOBE_ANALYTICS');
      if (generalConnections.length > 0) {
        const currentConn = state.connection_id;
        const hasCurrent = generalConnections.find(c => c.connection_id === currentConn);
        if (!hasCurrent) {
          setTimeout(() => {
            handleConnectionChange(generalConnections[0].connection_id);
          }, 0);
        }
      }

      // Auto-select the first valid AI connection
      const aiConns = list.filter(c => c.platform === 'PEEC' || c.platform === 'BRANDLIGHT');
      if (aiConns.length > 0) {
        const currentAi = state.ai_connection_id;
        const hasCurrentAi = aiConns.find(c => c.connection_id === currentAi);
        if (!hasCurrentAi) {
          setTimeout(() => {
            updateState({ ai_connection_id: aiConns[0].connection_id });
          }, 0);
        }
      }
    }
  }, [tenant]);

  // Cargar cuentas cuando cambia la conexión/origen
  const handleConnectionChange = async (connId: string) => {
    updateState({ connection_id: connId, account_id: '', property_id: '', segment_id: '' });
    setAccounts([]);
    setProperties([]);
    setSegments([]);

    if (!connId) return;

    try {
      const tId = tenant?.tenant_id || state.tenant_id || '';
      const tenantQuery = tId ? `&tenant_id=${tId}` : '';
      const res = await secureFetch(`/api/v1/mcp-analytics/accounts?connection_id=${connId}${tenantQuery}`);
      if (res.ok) {
        const data = await res.json();
        const loadedAccounts = data.accounts || [];
        setAccounts(loadedAccounts);
        
        // Seleccionar cuenta por defecto e iniciar cascada
        if (loadedAccounts.length > 0) {
          const firstAcc = loadedAccounts[0].account_id;
          updateState({ connection_id: connId, account_id: firstAcc, property_id: '', segment_id: '' });
          handleAccountChange(connId, firstAcc);
        }
      }
    } catch (e) {
      console.error("Error loading accounts:", e);
    }
  };

  // Cargar propiedades cuando cambia la cuenta
  const handleAccountChange = async (connId: string, accId: string) => {
    updateState({ account_id: accId, property_id: '', segment_id: '' });
    setProperties([]);
    setSegments([]);

    if (!connId || !accId) return;

    try {
      const tId = tenant?.tenant_id || state.tenant_id || '';
      const tenantQuery = tId ? `&tenant_id=${tId}` : '';
      const res = await secureFetch(`/api/v1/mcp-analytics/properties?connection_id=${connId}&account_id=${accId}${tenantQuery}`);
      if (res.ok) {
        const data = await res.json();
        const loadedProperties = data.properties || [];
        setProperties(loadedProperties);
        
        // Seleccionar propiedad por defecto e iniciar cascada de segmentos si es Adobe
        if (loadedProperties.length > 0) {
          const firstProp = loadedProperties[0].property_id;
          updateState({ account_id: accId, property_id: firstProp, segment_id: '' });
          if (connId.toLowerCase().includes('adobe')) {
            handlePropertyChange(connId, firstProp);
          }
        }
      }
    } catch (e) {
      console.error("Error loading properties:", e);
    }
  };

  // Cargar segmentos cuando cambia la propiedad/suite de Adobe
  const handlePropertyChange = async (connId: string, propId: string) => {
    updateState({ property_id: propId, segment_id: '' });
    setSegments([]);

    if (!connId || !propId) return;

    try {
      const tId = tenant?.tenant_id || state.tenant_id || '';
      const tenantQuery = tId ? `&tenant_id=${tId}` : '';
      const res = await secureFetch(`/api/v1/mcp-analytics/adobe/segments/${propId}?connection_id=${connId}${tenantQuery}`);
      if (res.ok) {
        const data = await res.json();
        setSegments(data.segments || []);
      }
    } catch (e) {
      console.error("Error loading segments:", e);
    }
  };

  // 0. Efecto para cargar dinámicamente la configuración visual del Tenant (Sanitas, LLYC, etc.)
  useEffect(() => {
    if (adminPreviewTenant) return;
    
    // Al volver al tenant por defecto, podemos limpiar los estados de simulación local
    updateState({ connection_id: '', property_id: '' });

    const tenantParam = getTenantFromUrl();
    
    const fetchTenantConfig = async () => {
      try {
        const url = tenantParam 
          ? `/api/v1/mcp-analytics/tenant/config?tenant=${tenantParam}`
          : `/api/v1/mcp-analytics/tenant/config`;
          
        const res = await secureFetch(url);
        if (res.ok) {
          const data: TenantConfig = await res.json();
          setTenant(data);
          updateState({ tenant_id: data.tenant_id });
          
          // Aplicar la paleta de colores de marca dinámicamente en el documento
          if (data.primary_color) {
            document.documentElement.style.setProperty('--red', data.primary_color);
            // Generar una versión al 10% de opacidad para el color de fondo claro
            document.documentElement.style.setProperty('--red-light', data.primary_color + '1A');
          }
          if (data.secondary_color) {
            document.documentElement.style.setProperty('--teal', data.secondary_color);
            document.documentElement.style.setProperty('--teal-light', data.secondary_color + '1A');
          }
        }
      } catch (err) {
        console.error("Error fetching tenant config:", err);
      }
    };
    
    fetchTenantConfig();
  }, [adminPreviewTenant]);

  const [lineData, setLineData] = useState<any>({
    labels: [],
    datasets: []
  });

  const handleApplyFilters = useCallback(() => {
    fetchData();
  }, [fetchData]);

  // 1. Efecto para inicialización desde URL (solo una vez al montar)
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const connId = urlParams.get('connection_id');
    const sessId = urlParams.get('session_id');
    
    if (connId || sessId) {
      updateState({ connection_id: connId || 'google', session_id: sessId || '' });
      setShowDashboard(true);
    }
  }, []); // Sin dependencias para que solo corra una vez

  // 2. Efecto para carga inicial de datos cuando se activa el dashboard
  useEffect(() => {
    if (showDashboard && (state.connection_id || state.property_id)) {
      fetchData();
    }
  }, [showDashboard, state.connection_id, state.property_id]);

  // 3. Efecto dinámico para mapear y actualizar lineData con los registros de BigQuery en tiempo real
  useEffect(() => {
    if (data && data.rows && data.rows.length > 0) {
      const sortedRows = [...data.rows].sort((a: any, b: any) => a.date.localeCompare(b.date));
      
      const labels = sortedRows.map((r: any) => {
        const parts = r.date.split('-');
        return parts.length === 3 ? `${parts[2]}/${parts[1]}` : r.date;
      });
      
      const sessions = sortedRows.map((r: any) => parseInt(r.sessions || '0', 10));
      const aiSessions = sortedRows.map((r: any) => {
        const referred = parseFloat(r.ai_referred || '0');
        const inferred = parseFloat(r.ai_inferred || '0');
        return Math.round(referred + inferred);
      });
      
      setLineData({
        labels,
        datasets: [
          {
            label: 'Sesiones totales',
            data: sessions,
            borderColor: '#C5D2DA',
            borderWidth: 1.5,
            borderDash: [4, 3],
            pointRadius: 0,
            tension: 0.3,
            yAxisID: 'y'
          },
          {
            label: 'Sesiones IA',
            data: aiSessions,
            borderColor: '#F54963',
            borderWidth: 2,
            pointRadius: 3,
            backgroundColor: 'rgba(245,73,99,0.05)',
            fill: true,
            tension: 0.3,
            yAxisID: 'y1'
          }
        ]
      });
    } else {
      setLineData({ labels: [], datasets: [] });
    }
    setLastUpdated(new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }));
  }, [data]);

  const handleSelectGA4 = () => {
    window.location.href = `${API_BASE_URL}/api/v1/mcp-analytics/oauth/login`;
  };

  const handleSelectAdobe = (creds: any) => {
    console.log("Adobe Creds:", creds);
    setShowDashboard(true);
    handleConnectionChange('adobe-temp');
  };

  const handleSelectPeec = (apiKey: string) => {
    console.log("Peec API Key:", apiKey);
    setShowDashboard(true);
    handleConnectionChange('peec-temp');
  };

  const handleFileUpload = async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      const res = await secureFetch(`/api/v1/mcp-analytics/upload-data`, {
        method: 'POST',
        body: formData
      });
      const result = await res.json();
      if (result.status === 'success') {
        updateState({ connection_id: 'local', property_id: result.property_id });
        setShowDashboard(true);
      } else {
        alert("Error: " + result.message);
      }
    } catch (err) {
      alert("Error de conexión");
    }
  };

  const handleExportPDF = async () => {
    if (!dashboardRef.current) return;
    setExporting(true);
    
    try {
      const el = dashboardRef.current;
      const cv = await html2canvas(el, {
        scale: 1.5,
        useCORS: true,
        backgroundColor: '#F0F2F4',
        logging: false
      });
      
      const pdf = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' });
      const pw = pdf.internal.pageSize.getWidth();
      const ph = pdf.internal.pageSize.getHeight();
      const iw = pw - 20;
      const ih = iw / (cv.width / cv.height);
      
      pdf.setFillColor(10, 38, 59);
      pdf.rect(0, 0, pw, 14, 'F');
      pdf.setTextColor(255, 255, 255);
      pdf.setFontSize(10);
      pdf.text('LLYC — Intelligence Dashboard', 10, 9);
      
      const pageH = ph - 18 - 8;
      let rem = ih;
      let sy = 0;
      let first = true;
      
      while (rem > 0) {
        if (!first) pdf.addPage();
        const sh = Math.min(pageH, rem);
        const ss = (sh / ih) * cv.height;
        
        const sc = document.createElement('canvas');
        sc.width = cv.width;
        sc.height = Math.round(ss);
        const ctx = sc.getContext('2d');
        if (ctx) {
          ctx.drawImage(cv, 0, Math.round(sy), cv.width, Math.round(ss), 0, 0, cv.width, Math.round(ss));
          pdf.addImage(sc.toDataURL('image/jpeg', 0.92), 'JPEG', 10, first ? 18 : 10, iw, sh);
        }
        
        sy += ss;
        rem -= sh;
        first = false;
      }
      
      pdf.save(`LLYC_Dashboard_${state.market}_${new Date().toISOString().split('T')[0]}.pdf`);
    } catch (e) {
      console.error("PDF Export error:", e);
      alert("Error al generar el PDF");
    } finally {
      setExporting(false);
    }
  };

  if (isAdminView) {
    return <AdminPanel adminEmailProp={adminUserEmail || undefined} onBack={handleGoToDashboard} onPreviewTenant={handlePreviewTenant} />;
  }

  if (!showDashboard) {
    return (
      <WelcomeScreen 
        onSelectGA4={handleSelectGA4}
        onSelectAdobe={handleSelectAdobe}
        onSelectPeec={handleSelectPeec}
        onFileUpload={handleFileUpload}
        tenant={tenant}
      />
    );
  }

  // Pantalla de carga mientras se inicializa Auth o se verifica el acceso en vivo
  if (authLoading || (currentUserEmail && verifyingAccess)) {
    return (
      <div className="fixed inset-0 bg-[#060c18] flex flex-col items-center justify-center p-5 z-[1000] gap-4">
        <div className="w-12 h-12 border-4 border-t-transparent rounded-full animate-spin" style={{ borderColor: tenant.primary_color || '#E51D24', borderTopColor: 'transparent' }} />
        <p className="text-white text-xs uppercase tracking-widest font-bold">Verificando Credenciales de {tenant.tenant_name}…</p>
      </div>
    );
  }

  // Pantalla de inicio de sesión o acceso restringido si no está autorizado
  if (!isTenantAuthorized) {
    return (
      <ClientLoginScreen 
        tenant={tenant}
        isAccessDenied={!!currentUserEmail && !is2faRequired}
        onClearAccessDenied={() => {
          setIsTenantAuthorized(null);
          setIs2faRequired(false);
        }}
        is2faRequired={is2faRequired}
        on2faSuccess={() => {
          setIs2faRequired(false);
          setIsTenantAuthorized(true);
        }}
      />
    );
  }

  // Obtener dominios unbranded / branded dinámicamente desde BigQuery
  const getDomainsList = () => {
    if (!data || !data.rows) return [];
    
    const domainMap: { [key: string]: { visibility: number, count: number } } = {};
    data.rows.forEach((r: any) => {
      const dom = r.domain;
      if (dom) {
        if (!domainMap[dom]) {
          domainMap[dom] = { visibility: 0, count: 0 };
        }
        domainMap[dom].visibility += parseFloat(r.visibility_score || '0');
        domainMap[dom].count += 1;
      }
    });
    
    return Object.keys(domainMap).map(d => ({
      d,
      m: domainMap[d].count, // Menciones reales
      g: Math.round(domainMap[d].visibility / domainMap[d].count) // Score de visibilidad real
    })).sort((a, b) => b.m - a.m); // Ordenar por menciones descendente
  };

  const dynamicDomains = getDomainsList();
  const top10Unbranded = dynamicDomains.slice(0, 10);
  const top10Branded = dynamicDomains.slice(0, 10);

  const trafficSource = state.connection_id?.toLowerCase().includes('adobe') ? 'Adobe' : 'GA4';

  const aiReferredVal = data?.ai_referred || 0;
  const aiInferredVal = data?.ai_inferred || 0;
  const totalSessVal = data?.total_sessions || 0;
  const restVal = Math.max(0, totalSessVal - (aiReferredVal + aiInferredVal));
  
  const referredPercent = totalSessVal > 0 ? Math.round((aiReferredVal / totalSessVal) * 1000) / 10 : 0;
  const inferredPercent = totalSessVal > 0 ? Math.round((aiInferredVal / totalSessVal) * 1000) / 10 : 0;
  const restPercent = totalSessVal > 0 ? Math.round((restVal / totalSessVal) * 1000) / 10 : 0;

  // Calcular rendimiento por motor IA dinámicamente
  const getMotorRows = () => {
    if (!data || !data.rows) return [];
    
    const motors: { [key: string]: { sessions: number, conversions: number, count: number } } = {};
    data.rows.forEach((r: any) => {
      const src = r.source || 'Otros';
      if (!motors[src]) {
        motors[src] = { sessions: 0, conversions: 0, count: 0 };
      }
      motors[src].sessions += parseInt(r.sessions || '0', 10);
      motors[src].conversions += parseFloat(r.conversions || r.engagement_score || '0');
      motors[src].count += 1;
    });
    
    return Object.keys(motors).map(m => ({
      n: m,
      s: motors[m].sessions.toLocaleString('es-ES'),
      d: 'N/A',
      c: motors[m].count > 0 ? (motors[m].conversions / motors[m].count).toFixed(1) + '%' : '0%',
      sc: motors[m].count > 0 ? Math.round(motors[m].conversions / motors[m].count) : 0
    }));
  };
  
  const motorRows = getMotorRows();

  return (
    <div className="min-h-screen flex flex-col bg-dashboard-bg">
      {adminPreviewTenant && (
        <div className="bg-amber-500 text-navy py-2 px-8 flex items-center justify-between text-xs font-black uppercase tracking-wider shadow-md z-[100]">
          <div className="flex items-center gap-2">
            <span>👁️ Modo Vista Previa de Administrador</span>
            <span className="bg-navy text-white px-2 py-0.5 rounded text-[10px] font-black uppercase">Visualizando: {adminPreviewTenant}</span>
          </div>
          <button 
            onClick={() => {
              window.location.hash = '#admin';
              setIsAdminView(true);
            }}
            className="underline hover:text-white transition-colors"
          >
            Volver a la Administración →
          </button>
        </div>
      )}
      <Header 
        onRefresh={handleApplyFilters} 
        onExport={handleExportPDF} 
        onFileUpload={handleFileUpload} 
        loading={loading} 
        exporting={exporting}
        lastUpdated={lastUpdated} 
        tenant={tenant}
      />
      <FilterBar
        state={state}
        updateState={updateState}
        onApply={handleApplyFilters}
        connections={connections}
        accounts={accounts}
        properties={properties}
        segments={segments}
        onConnectionChange={handleConnectionChange}
        onAccountChange={(accId) => handleAccountChange(state.connection_id, accId)}
      />

      <main ref={dashboardRef} className="flex-1 p-8 space-y-6 max-w-[1400px] mx-auto w-full">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8 gap-3">
          <KpiCard label="Sesiones totales" value={data?.total_sessions !== undefined ? data.total_sessions.toLocaleString('es-ES') : '--'} suffix="" trend={data?.total_sessions !== undefined ? "+12.3%" : ""} source={trafficSource} />
          <KpiCard label="IA referida" value={data?.ai_referred !== undefined ? data.ai_referred : '--'} suffix="" trend={data?.ai_referred !== undefined ? "+34.1%" : ""} source={trafficSource} />
          <KpiCard label="IA inferida" value={data?.ai_inferred !== undefined ? data.ai_inferred : '--'} suffix="" trend={data?.ai_inferred !== undefined ? "+21.7%" : ""} source={trafficSource} />
          <KpiCard label="Engagement IA" value={data?.engagement_score !== undefined ? data.engagement_score : '--'} suffix={data?.engagement_score !== undefined ? "/100" : ""} trend={data?.engagement_score !== undefined ? "+8 pts" : ""} source={trafficSource} />
          <KpiCard label="Visibilidad unbranded" value={data?.visibility_score !== undefined ? data.visibility_score : '--'} suffix={data?.visibility_score !== undefined ? "%" : ""} trend={data?.visibility_score !== undefined ? "+5 pts" : ""} source="BL" colorClass="!bg-teal-light/20 border-teal/20" />
          <KpiCard label="Score sentimiento" value={data?.sentiment_score !== undefined ? data.sentiment_score : '--'} suffix={data?.sentiment_score !== undefined ? "/10" : ""} trend={data?.sentiment_score !== undefined ? "+0.4" : ""} source="BL" />
          <KpiCard label="Modelos analizados" value={data ? "5" : "--"} trend={data ? "GPT · Gemini · Perplexity..." : ""} source="BL" />
          <KpiCard label="Dominios monitorizados" value={data ? "847" : "--"} trend={data ? "+23 nuevos" : ""} source="BL" />
        </div>

        {!data && !loading ? (
          <div className="p-12 text-center border border-dashed border-white/10 rounded-2xl bg-white/5 text-mid text-sm flex flex-col items-center gap-3">
            <Database className="w-8 h-8 text-amber-500 animate-bounce" />
            <h3 className="font-black text-xs uppercase tracking-widest text-white">No se detectaron datos en Google BigQuery para este inquilino</h3>
            <p className="max-w-md text-[10px] leading-relaxed text-mid">
              Para ver el dashboard analítico real de tu cliente, ingresa al Panel de Administración maestro y haz clic en "Re-desplegar ETL" para iniciar la ingesta real de los últimos 90 días de datos en BigQuery.
            </p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <ChartWidget 
              type="line" 
              title="Evolución tráfico IA" 
              source={trafficSource} 
              data={lineData}
              options={{
                scales: {
                  y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: { color: 'rgba(0,0,0,0.05)' }
                  },
                  y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    grid: { drawOnChartArea: false }
                  }
                }
              }}
              height={200}
              footer={
                <div className="flex gap-4 text-[10px] font-bold uppercase tracking-widest text-mid">
                  <div className="flex items-center gap-1.5"><div className="w-2.5 h-1 border-t-2 border-dashed border-mid/50"></div> Sesiones totales</div>
                  <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-sm bg-red"></div> Sesiones IA</div>
                </div>
              }
            />
          </div>
          <div>
            <ChartWidget 
              type="doughnut" 
              title="Composición de audiencia" 
              source={trafficSource} 
              data={{
                labels: ['IA directa', 'IA inferida', 'Resto'],
                datasets: [{
                  data: [aiReferredVal, aiInferredVal, restVal],
                  backgroundColor: ['#F54963', '#36A7B7', '#0A263B'],
                  borderWidth: 0
                }]
              }}
              height={200}
              footer={
                <div className="flex flex-wrap gap-x-4 gap-y-2 text-[10px] font-bold uppercase tracking-widest text-mid">
                  <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-sm bg-red"></div> IA directa {referredPercent}%</div>
                  <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-sm bg-navy"></div> IA inferida {inferredPercent}%</div>
                  <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-sm bg-mid/30"></div> Resto {restPercent}%</div>
                </div>
              }
            />
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-xl overflow-hidden border border-dashboard-border shadow-sm">
             <div className="p-5 pb-0">
                <div className="text-[11px] font-bold text-navy uppercase tracking-widest mb-1 flex items-center gap-1">
                  Rendimiento por motor IA <span className={`text-[9px] px-1.5 py-0.5 rounded font-black uppercase ${trafficSource === 'Adobe' ? 'bg-navy/10 text-navy' : 'bg-teal-light text-teal'}`}>{trafficSource}</span>
                </div>
                <div className="text-[10px] text-mid mb-4">Sesiones · duración · conversión · score</div>
             </div>
             <table className="w-full text-left border-collapse">
                <thead className="bg-dashboard-bg/50">
                  <tr className="text-[10px] font-bold text-mid uppercase tracking-widest">
                    <th className="px-5 py-2">Motor</th>
                    <th className="px-5 py-2 text-right">Sesiones</th>
                    <th className="px-5 py-2 text-right">Duración</th>
                    <th className="px-5 py-2 text-right">Conv.</th>
                    <th className="px-5 py-2">Score</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-dashboard-border text-xs">
                  {motorRows.map((r,i) => (
                    <tr key={i} className="hover:bg-dashboard-bg/20 transition-colors">
                      <td className="px-5 py-2 font-bold text-navy">{r.n}</td>
                      <td className="px-5 py-2 text-right text-mid">{r.s}</td>
                      <td className="px-5 py-2 text-right text-mid">{r.d}</td>
                      <td className="px-5 py-2 text-right text-mid">{r.c}</td>
                      <td className="px-5 py-2">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-1 bg-dashboard-bg rounded-full overflow-hidden min-w-[40px]">
                            <div className="h-full bg-red" style={{width:`${r.sc}%`}}></div>
                          </div>
                          <span className="text-[10px] font-bold text-mid">{r.sc}</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
             </table>
          </div>
          <ChartWidget 
            type="bar" 
            title="Visibilidad de marca por motor IA" 
            source="BL" 
            data={{
              labels: ['ChatGPT', 'Gemini', 'Perplexity', 'Claude', 'Copilot'],
              datasets: [
                { label: 'LLYC', data: [72, 65, 58, 81, 44], backgroundColor: '#36A7B7', borderRadius: 4 },
                { label: 'Prom.', data: [51, 48, 43, 55, 38], backgroundColor: '#C5D2DA', borderRadius: 4 }
              ]
            }}
            height={200}
            footer={
              <div className="flex gap-4 text-[10px] font-bold uppercase tracking-widest text-mid">
                <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-sm bg-teal"></div> LLYC</div>
                <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-sm bg-mid/30"></div> Prom. competidores</div>
              </div>
            }
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <ChartWidget 
            type="bar" 
            title="Clusters de comportamiento IA" 
            source="GA4" 
            data={{
              labels: ['Investigadores', 'Transaccional', 'Resumen', 'Casual'],
              datasets: [{ data: [38, 27, 22, 13], backgroundColor: ['#F54963', '#36A7B7', '#0A263B', '#E8A020'], borderRadius: 4 }]
            }}
          />
          <ChartWidget 
            type="bar" 
            title="Visibilidad unbranded — top 5" 
            source="BL" 
            options={{ indexAxis: 'y' }}
            data={{
              labels: ['LLYC', 'Weber', 'Edelman', 'FTI', 'Brunswick'],
              datasets: [{ data: [68, 54, 47, 39, 31], backgroundColor: ['#F54963', '#0A263B', '#0A263B', '#0A263B', '#0A263B'], borderRadius: 4 }]
            }}
          />
          <ChartWidget 
            type="bar" 
            title="Sentimiento de marca — top 5" 
            source="BL" 
            options={{ indexAxis: 'y', scales: { x: { min: 5, max: 10 } } }}
            data={{
              labels: ['LLYC', 'Weber', 'Edelman', 'FTI', 'Brunswick'],
              datasets: [{ data: [7.8, 7.1, 6.9, 6.4, 6.0], backgroundColor: ['#36A7B7', '#0A263B', '#0A263B', '#0A263B', '#0A263B'], borderRadius: 4 }]
            }}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <TopicsCard 
            title="Temáticas clave — Comunicación & PR" 
            source="BL"
            topics={[
              {l:'Reputación corporativa',w:91},{l:'Comunicación de crisis',w:78},
              {l:'Relaciones con medios',w:65},{l:'ESG & sostenibilidad',w:54},{l:'Comunicación interna',w:42}
            ]}
          />
          <TopicsCard 
            title="Temáticas clave — Digital & Crisis" 
            source="BL"
            topics={[
              {l:'Transformación digital',w:88},{l:'IA generativa',w:82},
              {l:'Gestión de crisis online',w:71},{l:'Social media strategy',w:60},{l:'Influencer relations',w:38}
            ]}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <DomainsTable title="Top 10 dominios · gap score (unbranded)" source="BL" rows={top10Unbranded} />
          <DomainsTable title="Top 10 dominios · gap score (branded)" source="BL" rows={top10Branded} />
        </div>
          </>
        )}
      </main>

      {exporting && (
        <div className="fixed inset-0 bg-navy/80 flex items-center justify-center p-5 z-[2000]">
          <div className="bg-white rounded-xl p-8 max-w-xs w-full shadow-2xl text-center flex flex-col items-center gap-4">
            <div className="w-12 h-12 border-4 border-red/20 border-t-red rounded-full spin"></div>
            <p className="text-navy font-bold uppercase tracking-widest text-xs">Generando PDF…</p>
          </div>
        </div>
      )}
    </div>
  );
};

export default App;
