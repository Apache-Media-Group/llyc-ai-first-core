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
import { Database, X } from 'lucide-react';
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

  // 2. Detección por path name (ej: /media-impact/client-a o /media-impact/client-a/)
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
  const [isMethodologyOpen, setIsMethodologyOpen] = useState(false);
  const [showFormulas, setShowFormulas] = useState(false);
  
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
          property_id: '',
          live_api: false
        });
      }
    } catch (err) {
      console.error("Error setting preview tenant:", err);
    }
  };

  const handlePreviewLiveAPI = async (tenantId: string) => {
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
        
        // Activar el modo de vista previa de administrador y LIVE API
        setAdminPreviewTenant(data.tenant_name + " (LIVE API DEMO)");
        setIsAdminView(false);
        setShowDashboard(true);
        updateState({
          tenant_id: data.tenant_id,
          connection_id: '',
          property_id: '',
          live_api: true
        });
      }
    } catch (err) {
      console.error("Error setting preview tenant (Live API):", err);
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

  // 0. Efecto para cargar dinámicamente la configuración visual del Tenant (Cliente A, LLYC, etc.)
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
      
      const totalData = sortedRows.map((r: any) => {
        let total = parseInt((r.sessions || '0').toString(), 10);
        return total;
      });
      const aiData = sortedRows.map((r: any) => parseInt((r.ai_referred || '0').toString(), 10) + parseInt((r.ai_inferred || '0').toString(), 10));
      
      setLineData({
        labels,
        datasets: [
          {
            label: 'Sesiones totales',
            data: totalData,
            borderColor: '#C5D2DA',
            borderWidth: 1.5,
            borderDash: [4, 3],
            pointRadius: 0,
            tension: 0.3,
            yAxisID: 'y'
          },
          {
            label: 'Sesiones IA',
            data: aiData,
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
    
    // Wait for React to render the exporting state (special header) and for images to load
    await new Promise(resolve => setTimeout(resolve, 1500));
    
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
      
      const pageH = ph - 20;
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
          pdf.addImage(sc.toDataURL('image/jpeg', 0.92), 'JPEG', 10, 10, iw, sh);
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
    return <AdminPanel adminEmailProp={adminUserEmail || undefined} onBack={handleGoToDashboard} onPreviewTenant={handlePreviewTenant} onPreviewLiveAPI={handlePreviewLiveAPI} />;
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

  const aiSource = connections.some(c => c.platform === 'PEEC') ? 'PEEC' : 'BL';

  // Obtener dominios unbranded / branded dinámicamente desde BigQuery
  const getDomainsData = () => {
    let allDomains: any[] = [];
    
    if (data && data.domains) {
      data.domains.forEach((d: any) => {
        allDomains.push({
          d: d.domain,
          m: '-', // Menciones
          g: d.visibility_score,
          c: d.classification
        });
      });
    }
    
    return allDomains.sort((a, b) => b.g - a.g).slice(0, 10);
  };

  const top10Domains = getDomainsData();

  const trafficSource = state.connection_id?.toLowerCase().includes('adobe') ? 'Adobe' : 'GA4';

  // Valores base (sin maquillaje estático)
  let aiReferredVal = parseInt((data?.ai_referred || 0).toString(), 10);
  let aiInferredVal = parseInt((data?.ai_inferred || 0).toString(), 10);
  let totalSessVal = parseInt((data?.total_sessions || 0).toString(), 10);
  
  let engScoreVal = parseFloat((data?.engagement_score || 0).toString());
  let visScoreVal = parseFloat((data?.visibility_score || 0).toString());
  let sentScoreVal = parseFloat((data?.sentiment_score || 0).toString());

  // Reverting mathematical overrides
  if (aiReferredVal + aiInferredVal > totalSessVal) {
    // If backend provides faulty data where AI > Total, we just render it as is to expose the backend issue
  }

  const restVal = Math.max(0, totalSessVal - (aiReferredVal + aiInferredVal));
  
  const referredPercent = totalSessVal > 0 ? Math.round((aiReferredVal / totalSessVal) * 1000) / 10 : 0;
  const inferredPercent = totalSessVal > 0 ? Math.round((aiInferredVal / totalSessVal) * 1000) / 10 : 0;
  const restPercent = totalSessVal > 0 ? Math.round((restVal / totalSessVal) * 1000) / 10 : 0;

  // Calcular rendimiento por motor IA dinámicamente
  type EngineData = { sessions: number, conversions: number, count: number, totalDuration: number };
  const getMotorRows = () => {
    const motors: Record<string, EngineData> = {
      'ChatGPT': { sessions: 0, conversions: 0, count: 0, totalDuration: 0 },
      'Gemini': { sessions: 0, conversions: 0, count: 0, totalDuration: 0 },
      'Perplexity': { sessions: 0, conversions: 0, count: 0, totalDuration: 0 },
      'Claude': { sessions: 0, conversions: 0, count: 0, totalDuration: 0 },
      'Copilot': { sessions: 0, conversions: 0, count: 0, totalDuration: 0 },
      'Otros': { sessions: 0, conversions: 0, count: 0, totalDuration: 0 },
    };

    if (data && data.rows) {
      data.rows.forEach((r: any) => {
        const processEngine = (name: string, sessionKey: string, durationKey: string, convKey: string) => {
          const sess = parseInt((r[sessionKey] || '0').toString(), 10);
          const dur = parseFloat((r[durationKey] || '0').toString());
          const eng = parseFloat((r[convKey] || '0').toString());
          
          if (sess > 0) {
            motors[name].sessions += sess;
            motors[name].conversions += eng;
            motors[name].count += 1;
            motors[name].totalDuration += dur;
          }
        };

        processEngine('ChatGPT', 'chatgpt_sessions', 'chatgpt_duration', 'chatgpt_conversions');
        processEngine('Gemini', 'gemini_sessions', 'gemini_duration', 'gemini_conversions');
        processEngine('Perplexity', 'perplexity_sessions', 'perplexity_duration', 'perplexity_conversions');
        processEngine('Claude', 'claude_sessions', 'claude_duration', 'claude_conversions');
        processEngine('Copilot', 'copilot_sessions', 'copilot_duration', 'copilot_conversions');
        processEngine('Otros', 'other_ai_sessions', 'other_ai_duration', 'other_ai_conversions');
      });
    }
    
    return Object.keys(motors)
      .filter(m => (motors[m].sessions > 0 || motors[m].count > 0) && (m !== 'Otros' || (motors[m].conversions > 0 || motors[m].sessions > 50)))
      .map(m => {
        const avgSecs = motors[m].sessions > 0 ? Math.round(motors[m].totalDuration / motors[m].sessions) : 0;
        const mins = Math.floor(avgSecs / 60);
        const secs = avgSecs % 60;
        const durationStr = avgSecs > 0 ? `${mins}m ${secs}s` : 'N/A';
        return {
          n: m,
          s: motors[m].sessions.toLocaleString('es-ES'),
          ds: motors[m].sessions,
          d: durationStr,
          c: motors[m].count > 0 ? (motors[m].conversions / motors[m].count).toFixed(1) + '%' : '0%',
          sc: motors[m].count > 0 ? Math.round(motors[m].conversions / motors[m].count) : 0
        };
      })
      .sort((a, b) => b.ds - a.ds);
  };
  
  const motorRows = getMotorRows();

  const mainBrandLabel = tenant?.tenant_name || 'Tu Marca';
  
  const topicsRows = [...(data?.topics_pr || []), ...(data?.topics_digital || []), ...(data?.topics_rows || [])];

  const totalUniqueDomains = data?.rows ? new Set(data.rows.map((r: any) => r.domain).filter(Boolean)).size : 0;

  const getProxiedLogoUrl = (url: string) => {
    if (!url) return '';
    if (url.startsWith('/')) return `${import.meta.env.BASE_URL || '/'}${url.substring(1)}`;
    return `${API_BASE_URL}/api/v1/mcp-analytics/tenant/proxy-logo?url=${encodeURIComponent(url)}`;
  };

  return (
    <div className="min-h-screen flex flex-col bg-dashboard-bg">
      {/* IMAGES PRELOADER FOR PDF EXPORT */}
      <div style={{ display: 'none' }}>
        {tenant?.logo_url && <img src={getProxiedLogoUrl(tenant.logo_url)} alt="preload" crossOrigin="anonymous" />}
      </div>
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
        {exporting && (
          <div className="bg-white -mx-8 -mt-8 mb-6 px-8 py-5 border-b border-dashboard-border flex items-center justify-between shadow-sm">
            <div className="flex items-center gap-6">
              {tenant?.logo_url ? (
                <img src={getProxiedLogoUrl(tenant.logo_url)} crossOrigin="anonymous" alt={tenant.tenant_name} className="h-10 object-contain max-w-[150px]" />
              ) : (
                <div className="text-red font-black text-xl tracking-tighter">{tenant?.tenant_name || 'LLYC'}</div>
              )}
              <div className="h-6 w-[1px] bg-dashboard-border"></div>
              <div className="text-[11px] font-black uppercase tracking-widest text-navy">
                Intelligence Dashboard <span className="text-mid font-medium">2026</span>
              </div>
              <div className="h-6 w-[1px] bg-dashboard-border"></div>
              <img src={`${import.meta.env.BASE_URL || '/'}llyc_logo_pdf.png`} alt="LLYC" crossOrigin="anonymous" className="h-7 object-contain" />
            </div>
            <div className="text-[11px] font-bold text-navy uppercase tracking-widest bg-dashboard-bg px-3 py-1.5 rounded-lg border border-dashboard-border">
              Fechas analizadas: <span className="text-red">{state.from || '--'}</span> <span className="text-mid font-normal">a</span> <span className="text-red">{state.to || '--'}</span>
            </div>
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8 gap-3">
          <KpiCard 
            label="Sesiones totales" 
            tooltip="Volumen total de tráfico recibido en el sitio web (incluyendo canales como orgánico, directo, pagado, referido, etc.)." 
            value={totalSessVal.toLocaleString('es-ES')} 
            suffix="" 
            trend={""} 
            source={trafficSource} 
          />
          <KpiCard 
            label="IA referida" 
            tooltip="Sesiones directas declaradas por motores de IA." 
            longTooltip={
              <>
                <p>
                  Las sesiones de <strong className="text-navy">IA Referida</strong> representan a los usuarios que han hecho clic en un enlace de tu marca directamente desde la interfaz de un motor de IA generativa y el motor declara explícitamente su origen en la cabecera HTTP (ej. <code className="bg-gray-100 px-1 rounded">chatgpt.com / referral</code>).
                </p>
                <p>
                  Es común que este número sea significativamente inferior a la IA Inferida, ya que la gran mayoría de interacciones con IA, especialmente en aplicaciones móviles (como la app de ChatGPT, Apple Intelligence, etc.) u otras plataformas, ocultan su origen inyectando el tráfico como "Directo".
                </p>
              </>
            }
            value={aiReferredVal.toLocaleString('es-ES')} 
            suffix="" 
            trend={""} 
            source={trafficSource} 
          />
          <KpiCard 
            label="IA inferida" 
            tooltip="Tráfico orgánico/directo perfilado como proviniendo de IA." 
            longTooltip={
              <>
                <p>
                  Las sesiones de <strong className="text-navy">IA Inferida</strong> representan tráfico que, aunque ingresa a tu web camuflado como "Directo" o sin referente claro, ha sido clasificado por el algoritmo algorítmico de LLYC como altamente probable de provenir de consultas de IA.
                </p>
                <p>
                  Nuestro modelo de propensión analiza factores de comportamiento en tiempo real, como la velocidad de rebote, la profundidad de scroll, el tiempo en página y la URL de aterrizaje para reconstruir el "viaje del usuario" y detectar interacciones típicas de cuando un usuario copia, pega o hace tap en un enlace sugerido por un chat de Inteligencia Artificial que no envía cabeceras de referer.
                </p>
                <p>
                  En el entorno SEO actual dominado por respuestas Zero-Click y apps nativas, <strong className="text-teal">es la norma y lo esperado</strong> que el tráfico inferido supere holgadamente al tráfico explícitamente referido.
                </p>
              </>
            }
            value={aiInferredVal.toLocaleString('es-ES')} 
            suffix="" 
            trend={""} 
            source={trafficSource} 
          />
          <KpiCard label="Engagement IA" tooltip="Calificación de 0 a 100 que evalúa la calidad y profundidad del comportamiento en la web del tráfico proveniente de la IA (considera conversiones, tiempo en página y páginas por sesión)." value={engScoreVal} suffix={data?.engagement_score !== undefined ? "/100" : ""} trend={""} source={trafficSource} />
          <KpiCard label="Visibilidad unbranded" tooltip="Share of Voice estimado de la marca dentro de los motores de IA cuando los usuarios realizan consultas genéricas del sector sin mencionar la marca explícitamente." value={data && (data?.total_monitored_domains || totalUniqueDomains) > 0 ? visScoreVal : "N/A"} suffix={data && (data?.total_monitored_domains || totalUniqueDomains) > 0 && data?.visibility_score !== undefined ? "%" : ""} trend={""} source={aiSource} colorClass="!bg-teal-light/20 border-teal/20" />
          <KpiCard label="Score sentimiento" tooltip="Puntuación promedio de 0 a 10 que evalúa qué tan positivas, neutrales o negativas son las menciones de la marca dentro de las respuestas de IA." value={data && (data?.total_monitored_domains || totalUniqueDomains) > 0 ? sentScoreVal : "N/A"} suffix={data && (data?.total_monitored_domains || totalUniqueDomains) > 0 && data?.sentiment_score !== undefined ? "/10" : ""} trend={""} source={aiSource} />
          <KpiCard label="Modelos analizados" tooltip="Cantidad total de modelos y motores conversacionales de IA que el sistema está monitorizando." value={data ? motorRows.length.toString() : "--"} trend={""} source={aiSource} />
          <KpiCard label="Dominios monitorizados" tooltip="Volumen de fuentes de información y dominios web (medios, foros, wikis) que están siendo indexados y usados por los motores de IA para generar sus respuestas." value={data && (data?.total_monitored_domains || totalUniqueDomains) > 0 ? (data?.total_monitored_domains ? data.total_monitored_domains.toLocaleString('es-ES') : totalUniqueDomains.toLocaleString('es-ES')) : "N/A"} trend={""} source={aiSource} />
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
                    grid: { color: 'rgba(0,0,0,0.05)' },
                    title: {
                      display: true,
                      text: 'Sesiones Totales',
                      color: '#0A263B',
                      font: { size: 10, weight: 'bold' }
                    }
                  },
                  y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    title: {
                      display: true,
                      text: 'Sesiones IA',
                      color: '#F54963',
                      font: { size: 10, weight: 'bold' }
                    }
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
                  {motorRows.length > 0 ? motorRows.map((r,i) => (
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
                  )) : (
                    <tr><td colSpan={5} className="px-5 py-8 text-center text-mid text-xs italic">Sin datos de tráfico para este periodo</td></tr>
                  )}
                </tbody>
             </table>
          </div>
          <ChartWidget 
            type="bar" 
            title="Visibilidad de marca por motor IA" 
            source={aiSource} 
            data={{
              labels: data?.visibility_by_engine?.length ? data.visibility_by_engine.map((e: any) => e.engine) : ['Sin datos'],
              datasets: [
                { label: mainBrandLabel, data: data?.visibility_by_engine?.length ? data.visibility_by_engine.map((e: any) => e.brand_score) : [0], backgroundColor: '#36A7B7', borderRadius: 4 },
                { label: 'Prom.', data: data?.visibility_by_engine?.length ? data.visibility_by_engine.map((e: any) => e.competitor_avg) : [0], backgroundColor: '#C5D2DA', borderRadius: 4 }
              ]
            }}
            height={200}
            footer={
              <div className="flex gap-4 text-[10px] font-bold uppercase tracking-widest text-mid">
                <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-sm bg-teal"></div> {mainBrandLabel}</div>
                <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-sm bg-mid/30"></div> Prom. competidores</div>
              </div>
            }
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {(() => {
            const rawClusters = data?.behavior_clusters?.length ? data.behavior_clusters : [
              { label: 'Transaccional', value: 0 },
              { label: 'Investigación', value: 0 },
              { label: 'Respuesta Rápida', value: 0 },
              { label: 'Casual', value: 0 }
            ];
            
            const order = ['Transaccional', 'Investigación', 'Respuesta Rápida', 'Casual'];
            const sortedClusters = [...rawClusters].sort((a, b) => order.indexOf(a.label) - order.indexOf(b.label));
            
            const clusterColorMap: Record<string, string> = {
              'Transaccional': '#F54963',
              'Investigación': '#36A7B7',
              'Respuesta Rápida': '#0A263B',
              'Casual': '#E8A020'
            };
            
            const hoverTextMap: Record<string, string> = {
              'Transaccional': 'Alta intención comercial o de conversión.',
              'Investigación': 'Fase exploratoria o evaluación detallada.',
              'Respuesta Rápida': 'Búsqueda de datos puntuales o confirmaciones.',
              'Casual': 'Interacción periférica sin intención de negocio.'
            };
            
            return (
              <ChartWidget 
                type="bar" 
                title="Clusters de comportamiento IA" 
                source={trafficSource} 
                onInfoClick={() => setIsMethodologyOpen(true)}
                data={{
                  labels: sortedClusters.map((c: any) => c.label),
                  datasets: [{ 
                    label: 'Sesiones IA',
                    data: sortedClusters.map((c: any) => c.value), 
                    backgroundColor: sortedClusters.map((c: any) => clusterColorMap[c.label] || '#999999'), 
                    borderRadius: 4 
                  }]
                }}
                options={{
                  plugins: {
                    legend: { display: false },
                    tooltip: {
                      callbacks: {
                        afterLabel: function(context: any) {
                          return hoverTextMap[context.label] || '';
                        }
                      }
                    }
                  }
                }}
              />
            );
          })()}
          
          <ChartWidget 
            type="bar" 
            title="Visibilidad unbranded — top 5" 
            source={aiSource} 
            options={{ indexAxis: 'y', plugins: { legend: { display: false } } }}
            data={{
              labels: data?.competitors?.filter((c: any) => c.classification?.toLowerCase() !== 'owned').slice(0, 5).map((c: any) => c.domain || c.name) || ['Sin datos'],
              datasets: [{ data: data?.competitors?.filter((c: any) => c.classification?.toLowerCase() !== 'owned').slice(0, 5).map((c: any) => c.visibility_score) || [0], backgroundColor: ['#F54963', '#0A263B', '#0A263B', '#0A263B', '#0A263B'], borderRadius: 4 }]
            }}
          />
          <ChartWidget 
            type="bar" 
            title="Sentimiento de marca — top 5" 
            source={aiSource} 
            options={{ indexAxis: 'y', scales: { x: { min: 5, max: 10 } }, plugins: { legend: { display: false } } }}
            data={{
              labels: data?.competitors?.slice(0, 5).map((c: any) => c.domain || c.name) || ['Sin datos'],
              datasets: [{ data: data?.competitors?.slice(0, 5).map((c: any) => c.sentiment_score) || [0], backgroundColor: ['#36A7B7', '#0A263B', '#0A263B', '#0A263B', '#0A263B'], borderRadius: 4 }]
            }}
          />
        </div>

        <div className="grid grid-cols-1 gap-6">
          <TopicsCard 
            title="Temáticas clave — Impacto en IA" 
            source={aiSource}
            topics={topicsRows.sort((a,b) => (b.w||0) - (a.w||0)).slice(0, 10)}
          />
        </div>

        <div className="grid grid-cols-1 gap-6">
          <DomainsTable title="Top 10 dominios de visibilidad" source={aiSource} rows={top10Domains} />
        </div>
          </>
        )}
      </main>

      {isMethodologyOpen && (
        <div className="fixed inset-0 bg-navy/80 flex items-center justify-center p-5 z-[2000] backdrop-blur-sm transition-all duration-300">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
            <div className="flex justify-between items-center p-6 border-b border-dashboard-border bg-dashboard-bg/50">
              <h3 className="text-lg font-bold text-navy uppercase tracking-widest flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-teal"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                Metodología de Clusters
              </h3>
              <button 
                onClick={() => setIsMethodologyOpen(false)}
                className="text-mid hover:text-red transition-colors p-1 rounded-full hover:bg-red-light"
              >
                <X size={20} strokeWidth={2.5} />
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto custom-scrollbar">
              <div className="space-y-6 text-sm text-navy/80 leading-relaxed">
                <p>
                  Los <strong className="text-navy">Clusters de Comportamiento IA</strong> clasifican el tráfico inferido basándose en modelos de intención del usuario cuando interactúa con respuestas generadas por Inteligencia Artificial.
                </p>
                
                <div className="space-y-4">
                  <div className="bg-dashboard-bg p-4 rounded-xl border border-dashboard-border/50">
                    <h4 className="font-bold text-navy mb-2 flex items-center gap-2">
                      <span className="w-3 h-3 rounded-full" style={{backgroundColor: '#F54963'}}></span>
                      Transaccional
                    </h4>
                    <p>Usuarios con alta intención de compra o conversión inmediata. Provienen de prompts que buscan productos específicos, comparativas de precios o enlaces directos de contratación.</p>
                  </div>
                  
                  <div className="bg-dashboard-bg p-4 rounded-xl border border-dashboard-border/50">
                    <h4 className="font-bold text-navy mb-2 flex items-center gap-2">
                      <span className="w-3 h-3 rounded-full" style={{backgroundColor: '#36A7B7'}}></span>
                      Investigación
                    </h4>
                    <p>Usuarios en fase exploratoria o de "mid-funnel". Sus interacciones con la IA suelen ser preguntas de profundidad, tutoriales, o evaluaciones detalladas de servicios antes de tomar una decisión.</p>
                  </div>
                  
                  <div className="bg-dashboard-bg p-4 rounded-xl border border-dashboard-border/50">
                    <h4 className="font-bold text-navy mb-2 flex items-center gap-2">
                      <span className="w-3 h-3 rounded-full" style={{backgroundColor: '#0A263B'}}></span>
                      Respuesta Rápida
                    </h4>
                    <p>Usuarios que buscan un dato puntual (FAQs, números de contacto, horarios). El clic suele ser para verificar o ampliar ligeramente la información mostrada por la IA (Zero-Click searches).</p>
                  </div>
                  
                  <div className="bg-dashboard-bg p-4 rounded-xl border border-dashboard-border/50">
                    <h4 className="font-bold text-navy mb-2 flex items-center gap-2">
                      <span className="w-3 h-3 rounded-full" style={{backgroundColor: '#E8A020'}}></span>
                      Casual
                    </h4>
                    <p>Tráfico menos dirigido, derivado de conversaciones periféricas o menciones de marca sin una intención clara de negocio. Tienen el engagement rate más bajo.</p>
                  </div>
                </div>

                <div className="mt-6 pt-6 border-t border-dashboard-border">
                  <div className="flex justify-between items-center mb-4">
                    <p className="text-xs text-mid">La distribución se calcula utilizando un modelo de propensión basado en las dimensiones semánticas de la consulta de IA inicial y el comportamiento post-clic.</p>
                    <button 
                      onClick={() => setShowFormulas(!showFormulas)}
                      className="text-xs font-bold text-teal hover:text-navy transition-colors px-3 py-1.5 border border-teal/20 rounded-md hover:bg-teal/5 flex-shrink-0 ml-4"
                    >
                      {showFormulas ? 'Ocultar Fórmulas' : 'Ver Fórmulas'}
                    </button>
                  </div>
                  
                  {showFormulas && (
                    <div className="bg-navy rounded-xl p-5 text-white/90 text-xs font-mono space-y-4 shadow-inner mt-4 animate-in fade-in slide-in-from-top-2 duration-300">
                      <div>
                        <div className="text-teal-light mb-1 font-bold">1. Transaccional (Weight: 1.5)</div>
                        <div>Score = (conversion_rate * 40) + (bounce_rate_inverse * 20) + (time_on_site_score * 20) + semantic_intent(buy, hire, price)</div>
                      </div>
                      <div>
                        <div className="text-teal-light mb-1 font-bold">2. Investigación (Weight: 1.2)</div>
                        <div>Score = (pages_per_session * 30) + (time_on_site_score * 30) + semantic_intent(how, what, compare, review)</div>
                      </div>
                      <div>
                        <div className="text-teal-light mb-1 font-bold">3. Respuesta Rápida (Weight: 1.0)</div>
                        <div>Score = (bounce_rate * 50) + (short_time_on_site * 30) + semantic_intent(contact, address, hours, faq)</div>
                      </div>
                      <div>
                        <div className="text-teal-light mb-1 font-bold">4. Casual (Weight: 0.8)</div>
                        <div>Score = Default fallback para tráfico de baja retención sin keywords transaccionales o de investigación explícitas.</div>
                      </div>
                      <div className="pt-2 border-t border-white/10 text-[10px] text-white/50">
                        * semantic_intent() se resuelve vía Natural Language Processing en BigQuery, cruzando la Query original reportada por la IA con nuestro corpus de intenciones.
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}


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
