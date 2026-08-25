// frontend/src/components/admin/TenantTable.tsx
import React from 'react';
import { RefreshCw, Wrench, Key, Edit2 } from 'lucide-react';
import type { TenantConfig } from './types';

interface TenantTableProps {
  tenants: TenantConfig[];
  loading: boolean;
  onPreviewTenant?: (tenantId: string) => void;
  onPreviewLiveAPI?: (tenantId: string) => void;
  openAuditModal: (tenantId: string) => void;
  openSecretModal: (tenantId: string, isEditMode?: boolean) => void;
  openEditModal: (tenant: TenantConfig) => void;
}

export const TenantTable: React.FC<TenantTableProps> = ({
  tenants,
  loading,
  onPreviewTenant,
  onPreviewLiveAPI,
  openAuditModal,
  openSecretModal,
  openEditModal,
}) => {
  return (
    <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden">
      <div className="p-5 border-b border-white/10 bg-white/[0.02]">
        <h2 className="text-xs font-black uppercase tracking-widest text-mid">Clientes Activos ({tenants.length})</h2>
      </div>

      {loading ? (
        <div className="p-12 text-center text-mid flex flex-col items-center gap-3">
          <RefreshCw className="w-8 h-8 animate-spin text-red" />
          <span className="text-xs font-bold uppercase tracking-widest">Cargando base de datos de inquilinos...</span>
        </div>
      ) : tenants.length === 0 ? (
        <div className="p-12 text-center text-mid text-xs">
          No hay clientes creados todavía en Firestore. Pulsa "Crear Nuevo Cliente" para comenzar.
        </div>
      ) : (
        <div className="divide-y divide-white/5">
          {tenants.map((t) => (
            <div key={t.tenant_id} className="p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 hover:bg-white/[0.01] transition-colors">
              {/* Branding e info del cliente */}
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-white/10 rounded-xl flex items-center justify-center p-2 border border-white/5 overflow-hidden">
                  {t.logo_url ? (
                    <img src={t.logo_url} alt={t.tenant_name} className="max-h-full object-contain" />
                  ) : (
                    <span className="text-xs font-black text-white/50 uppercase">{t.tenant_id.slice(0, 2)}</span>
                  )}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-black text-sm">{t.tenant_name}</h3>
                    <span className="text-[9px] px-1.5 py-0.5 rounded font-black bg-white/10 text-white/70 uppercase tracking-wider">
                      ID: {t.tenant_id}
                    </span>
                  </div>
                  <p className="text-xs text-mid mt-0.5">{t.support_email}</p>
                  
                  {/* Visualización de colores */}
                  <div className="flex items-center gap-2 mt-2">
                    <div className="flex items-center gap-1">
                      <div className="w-3.5 h-3.5 rounded-full border border-white/10" style={{ backgroundColor: t.primary_color }}></div>
                      <span className="text-[9px] font-mono text-mid uppercase">{t.primary_color}</span>
                    </div>
                    <div className="h-2 w-[1px] bg-white/10"></div>
                    <div className="flex items-center gap-1">
                      <div className="w-3.5 h-3.5 rounded-full border border-white/10" style={{ backgroundColor: t.secondary_color }}></div>
                      <span className="text-[9px] font-mono text-mid uppercase">{t.secondary_color}</span>
                    </div>
                  </div>

                  {/* Estado de Integraciones */}
                  <div className="flex items-center gap-1.5 mt-2.5 flex-wrap">
                    <span className="text-[9px] text-mid uppercase tracking-wider font-semibold mr-1">Integraciones (GCP):</span>
                    <span className={`px-1.5 py-0.5 rounded text-[8px] font-black uppercase tracking-wider ${
                      (t.configured_secrets || {})['ga4-creds'] ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/5 text-white/30 border border-white/5'
                    }`}>
                      GA4
                    </span>
                    <span className={`px-1.5 py-0.5 rounded text-[8px] font-black uppercase tracking-wider ${
                      (t.configured_secrets || {})['adobe-creds'] ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/5 text-white/30 border border-white/5'
                    }`}>
                      Adobe
                    </span>
                    <span className={`px-1.5 py-0.5 rounded text-[8px] font-black uppercase tracking-wider ${
                      (t.configured_secrets || {})['peec-key'] ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/5 text-white/30 border border-white/5'
                    }`}>
                      Peec.ai
                    </span>
                    <span className={`px-1.5 py-0.5 rounded text-[8px] font-black uppercase tracking-wider ${
                      (t.configured_secrets || {})['brandlight-key'] ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/5 text-white/30 border border-white/5'
                    }`}>
                      Brandlight
                    </span>
                  </div>
                </div>
              </div>

              {/* Acciones */}
              <div className="flex items-center gap-2 self-end md:self-auto">
                {onPreviewTenant && (
                  <button
                    onClick={() => onPreviewTenant(t.tenant_id)}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-colors"
                  >
                    👁️ Ver Dashboard
                  </button>
                )}
                {onPreviewLiveAPI && (
                  <button
                    onClick={() => onPreviewLiveAPI(t.tenant_id)}
                    title="Carga los datos directamente desde las APIs (Bypasses BigQuery)"
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-500/10 hover:bg-purple-500/20 text-purple-400 border border-purple-500/20 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-colors"
                  >
                    🚀 LIVE API (DEMO)
                  </button>
                )}
                <button
                  onClick={() => openAuditModal(t.tenant_id)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-teal-500/10 hover:bg-teal-500/20 text-teal-400 border border-teal-500/20 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-colors"
                >
                  <Wrench className="w-3.5 h-3.5" /> Auditoría / Patcher
                </button>
                <button
                  onClick={() => openSecretModal(t.tenant_id, false)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 border border-amber-500/20 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-colors"
                >
                  <Key className="w-3.5 h-3.5" /> + Claves
                </button>
                <button
                  onClick={() => openSecretModal(t.tenant_id, true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 border border-blue-500/20 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-colors"
                >
                  <Key className="w-3.5 h-3.5" /> Editar Claves
                </button>
                <button
                  onClick={() => openEditModal(t)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-white/5 hover:bg-white/10 text-white border border-white/10 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-colors"
                >
                  <Edit2 className="w-3.5 h-3.5" /> Editar Marca
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
