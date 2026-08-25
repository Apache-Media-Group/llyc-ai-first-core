// frontend/src/components/AdminPanel.tsx
import React, { useState } from 'react';
import { ShieldCheck, Plus, ArrowLeft, RefreshCw, AlertCircle, CheckCircle2, LogOut, User } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { auth } from '../firebase';
import { secureFetch } from '../services/apiClient';

// Subcomponentes y Tipos
import type { TenantConfig } from './admin/types';
import { TenantTable } from './admin/TenantTable';
import { TenantModal } from './admin/TenantModal';
import { CredentialModal } from './admin/CredentialModal';
import { AuditModal } from './admin/AuditModal';
import { EtlMonitorTab } from './admin/EtlMonitorTab';
import { GA4ConnectionsTab } from './admin/GA4ConnectionsTab';

interface AdminPanelProps {
  adminEmailProp?: string;
  onBack: () => void;
  onPreviewTenant?: (tenantId: string) => void;
  onPreviewLiveAPI?: (tenantId: string) => void;
}

export const AdminPanel: React.FC<AdminPanelProps> = ({ adminEmailProp, onBack, onPreviewTenant, onPreviewLiveAPI }) => {
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Selector de pestañas
  const [activeTab, setActiveTab] = useState<'tenants' | 'etl' | 'oauth'>('tenants');

  // Control de Modales
  const [editingTenant, setEditingTenant] = useState<TenantConfig | null>(null);
  const [showTenantModal, setShowTenantModal] = useState(false);

  const [secretTenantId, setSecretTenantId] = useState<string | null>(null);
  const [showSecretModal, setShowSecretModal] = useState(false);
  const [forceEditMode, setForceEditMode] = useState(false);

  const [auditTenantId, setAuditTenantId] = useState<string | null>(null);
  const [showAuditModal, setShowAuditModal] = useState(false);

  const [adminEmail] = useState(adminEmailProp || localStorage.getItem('admin_user_email') || 'consultor@llyc.global');

  // Cerrar Sesión
  const handleLogout = async () => {
    try {
      await auth.signOut();
      localStorage.removeItem('admin_user_email');
      window.location.hash = ''; // Quitar hash de admin
      onBack();
    } catch (err) {
      console.error("Error signing out:", err);
    }
  };

  // Cargar Tenants e implementar Polling automático inteligente con React Query v5
  const { data: tenants = [], isLoading: loading, refetch: fetchTenants } = useQuery<TenantConfig[]>({
    queryKey: ['adminTenants'],
    queryFn: async () => {
      const res = await secureFetch('/api/v1/mcp-analytics/admin/tenants');
      if (!res.ok) {
        throw new Error("No se pudo obtener la lista de tenants");
      }
      return res.json();
    },
    // Polling inteligente cada 4 segundos si algún tenant está en estado 'deploying'
    refetchInterval: (query) => {
      const list = query.state.data as TenantConfig[] | undefined;
      const hasActiveDeployment = list?.some(t => t.deployment_status?.status === 'deploying');
      return hasActiveDeployment ? 4000 : false;
    }
  });

  const fetchTenantsSilently = () => {
    fetchTenants();
  };

  // Manejo de Modales
  const openCreateModal = () => {
    setEditingTenant({
      tenant_id: '',
      tenant_name: '',
      logo_url: '',
      primary_color: '#F54963',
      secondary_color: '#36A7B7',
      font_family: 'Montserrat, sans-serif',
      support_email: ''
    });
    setShowTenantModal(true);
  };

  const openEditModal = (tenant: TenantConfig) => {
    setEditingTenant({ ...tenant });
    setShowTenantModal(true);
  };

  const openSecretModal = (tenantId: string, forceEditMode: boolean = false) => {
    setSecretTenantId(tenantId);
    setForceEditMode(forceEditMode);
    setShowSecretModal(true);
  };

  const openAuditModal = (tenantId: string) => {
    setAuditTenantId(tenantId);
    setShowAuditModal(true);
  };

  // Callbacks de Éxito
  const handleSaveTenantSuccess = () => {
    setMessage({ 
      type: 'success', 
      text: `Cliente '${editingTenant?.tenant_name}' guardado exitosamente.` 
    });
    setShowTenantModal(false);
    fetchTenants();
    setTimeout(() => setMessage(null), 5000);
  };

  const handleSaveSecretSuccess = (successText: string) => {
    setMessage({ type: 'success', text: successText });
    fetchTenants();
    setTimeout(() => setMessage(null), 5000);
  };

  const handleSaveSecretError = (errorText: string) => {
    setMessage({ type: 'error', text: errorText });
    setTimeout(() => setMessage(null), 5000);
  };

  return (
    <div className="min-h-screen bg-navy text-white font-sans flex flex-col">
      {/* HEADER DE ADMÍN */}
      <header className="h-16 bg-[#0a1829] border-b border-white/10 flex items-center justify-between px-8 sticky top-0 z-[50] backdrop-blur-md">
        <div className="flex items-center gap-4">
          <button 
            onClick={onBack}
            className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-mid hover:text-white transition-colors"
          >
            <ArrowLeft className="w-4 h-4" /> Volver
          </button>
          <div className="h-4 w-[1px] bg-white/10"></div>
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-red" />
            <span className="text-[11px] font-black uppercase tracking-widest text-red">
              LLYC MCP Superadmin <span className="text-white/50 font-normal">v2.0</span>
            </span>
          </div>
        </div>
        
        <div className="flex items-center gap-4">
          <button 
            onClick={() => fetchTenants()}
            className="p-2 rounded-lg hover:bg-white/5 transition-colors"
            disabled={loading}
          >
            <RefreshCw className={`w-4 h-4 text-mid ${loading ? 'animate-spin' : ''}`} />
          </button>
          
          <div className="h-4 w-[1px] bg-white/10"></div>
          
          {/* PERFIL DE USUARIO Y LOGOUT */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 bg-white/5 border border-white/5 px-3 py-1.5 rounded-lg">
              <div className="w-5 h-5 rounded-full bg-red flex items-center justify-center text-[10px] font-black uppercase text-white shadow-md shadow-red/10">
                <User className="w-3 h-3 text-white" />
              </div>
              <span className="text-[11px] font-semibold text-white/80 max-w-[150px] truncate">{adminEmail}</span>
            </div>
            
            <button 
              onClick={handleLogout}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-colors"
              title="Cerrar Sesión"
            >
              <LogOut className="w-3.5 h-3.5" /> Cerrar Sesión
            </button>
          </div>
        </div>
      </header>

      {/* CONTENIDO PRINCIPAL */}
      <main className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6">
        {/* BANNER INFORMATIVO */}
        <div className="bg-white/5 border border-white/10 rounded-2xl p-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-black tracking-tight mb-1">Administración Global de Clientes</h1>
            <p className="text-xs text-mid">
              Crea nuevos clientes, gestiona sus colores corporativos, sube sus logotipos y administra sus credenciales de forma encriptada en GCP Secret Manager.
            </p>
          </div>
          <button 
            onClick={openCreateModal}
            className="flex items-center gap-2 self-start md:self-auto px-4 py-2.5 bg-red text-white rounded-lg text-[11px] font-black uppercase tracking-widest hover:bg-red/90 transition-colors shadow-lg shadow-red/20"
          >
            <Plus className="w-4 h-4" /> Crear Nuevo Cliente
          </button>
        </div>

        {/* MENSAJES DE ESTADO */}
        {message && (
          <div className={`p-4 rounded-xl flex items-start gap-3 border ${
            message.type === 'success' 
              ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' 
              : 'bg-red-500/10 border-red-500/20 text-red-400'
          }`}>
            {message.type === 'success' ? <CheckCircle2 className="w-5 h-5 shrink-0" /> : <AlertCircle className="w-5 h-5 shrink-0" />}
            <span className="text-xs font-semibold">{message.text}</span>
          </div>
        )}

        {/* TABS SELECTOR */}
        <div className="flex border-b border-white/10 gap-6">
          <button
            onClick={() => setActiveTab('tenants')}
            className={`pb-4 text-xs font-black uppercase tracking-widest border-b-2 transition-all ${
              activeTab === 'tenants' 
                ? 'border-red text-red' 
                : 'border-transparent text-mid hover:text-white'
            }`}
          >
            📂 Gestión de Clientes
          </button>
          <button
            onClick={() => setActiveTab('etl')}
            className={`pb-4 text-xs font-black uppercase tracking-widest border-b-2 transition-all ${
              activeTab === 'etl' 
                ? 'border-red text-red font-black' 
                : 'border-transparent text-mid hover:text-white'
            }`}
          >
            ❤️ Monitor de Salud ETL
          </button>
          <button
            onClick={() => setActiveTab('oauth')}
            className={`pb-4 text-xs font-black uppercase tracking-widest border-b-2 transition-all ${
              activeTab === 'oauth' 
                ? 'border-red text-red font-black' 
                : 'border-transparent text-mid hover:text-white'
            }`}
          >
            🔑 Conexiones GA4 (Globales)
          </button>
        </div>

        {activeTab === 'tenants' ? (
          /* TAB 1: LISTADO DE CLIENTES */
          <TenantTable 
            tenants={tenants}
            loading={loading}
            onPreviewTenant={onPreviewTenant}
            onPreviewLiveAPI={onPreviewLiveAPI}
            openAuditModal={openAuditModal}
            openSecretModal={openSecretModal}
            openEditModal={openEditModal}
          />
        ) : activeTab === 'etl' ? (
          /* TAB 2: MONITOR DE SALUD ETL */
          <EtlMonitorTab 
            tenants={tenants}
            onRefreshTenants={fetchTenantsSilently}
          />
        ) : (
          /* TAB 3: CONEXIONES GA4 (GLOBALES) */
          <GA4ConnectionsTab />
        )}
      </main>

      {/* MODAL DE CREAR / EDITAR CLIENTE */}
      {showTenantModal && editingTenant && (
        <TenantModal 
          isOpen={showTenantModal}
          onClose={() => setShowTenantModal(false)}
          tenant={editingTenant}
          onSaveSuccess={handleSaveTenantSuccess}
        />
      )}

      {/* MODAL DE CLAVES API (GCP SECRET MANAGER) */}
      {showSecretModal && secretTenantId && (
        <CredentialModal 
          isOpen={showSecretModal}
          onClose={() => setShowSecretModal(false)}
          tenantId={secretTenantId}
          configuredSecrets={tenants.find(t => t.tenant_id === secretTenantId)?.configured_secrets || {}}
          forceEditMode={forceEditMode}
          onSaveSuccess={handleSaveSecretSuccess}
          onSaveError={handleSaveSecretError}
        />
      )}

      {/* MODAL DE AUDITORÍA Y PATCHER DE BIGQUERY */}
      {showAuditModal && auditTenantId && (
        <AuditModal 
          isOpen={showAuditModal}
          onClose={() => setShowAuditModal(false)}
          tenantId={auditTenantId}
        />
      )}
    </div>
  );
};
