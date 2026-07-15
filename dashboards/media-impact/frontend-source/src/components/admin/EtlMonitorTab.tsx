// frontend/src/components/admin/EtlMonitorTab.tsx
import React, { useState, useEffect } from 'react';
import { Database, AlertTriangle, Activity, RefreshCw, AlertCircle, Check, CheckCircle2 } from 'lucide-react';
import type { TenantConfig } from './types';
import { secureFetch } from '../../services/apiClient';

interface EtlMonitorTabProps {
  tenants: TenantConfig[];
  onRefreshTenants: () => void;
}

export const EtlMonitorTab: React.FC<EtlMonitorTabProps> = ({
  tenants,
  onRefreshTenants,
}) => {
  const [etlHistory, setEtlHistory] = useState<any[]>([]);
  const [etlAlerts, setEtlAlerts] = useState<any[]>([]);
  const [loadingEtl, setLoadingEtl] = useState(false);
  const [redeploying, setRedeploying] = useState(false);
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const fetchEtlData = async () => {
    try {
      setLoadingEtl(true);
      
      // 1. Fetch History
      const resHistory = await secureFetch(`/api/v1/mcp-analytics/admin/etl/history`);
      const dataHistory = resHistory.ok ? await resHistory.json() : [];
      setEtlHistory(dataHistory);
      
      // 2. Fetch Active Alerts
      const resAlerts = await secureFetch(`/api/v1/mcp-analytics/admin/etl/alerts`);
      const dataAlerts = resAlerts.ok ? await resAlerts.json() : [];
      setEtlAlerts(dataAlerts);
      
    } catch (err) {
      console.error("Error fetching ETL metrics:", err);
    } finally {
      setLoadingEtl(false);
    }
  };

  const handleDismissAlert = async (alertId: string) => {
    try {
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/etl/alerts/${alertId}/dismiss`, {
        method: 'POST'
      });
      if (res.ok) {
        setEtlAlerts(prev => prev.filter(a => a.alert_id !== alertId));
        setActionMessage({ type: 'success', text: "Alerta descartada con éxito." });
        setTimeout(() => setActionMessage(null), 4000);
      } else {
        throw new Error("No se pudo descartar la alerta en Firestore");
      }
    } catch (err: any) {
      setActionMessage({ type: 'error', text: err.message });
      setTimeout(() => setActionMessage(null), 4000);
    }
  };

  const triggerDirectRedeploy = async (tenantId: string) => {
    try {
      setRedeploying(true);
      setActionMessage({
        type: 'success',
        text: `Iniciando re-despliegue de ETL y backfill histórico de 90 días para el cliente '${tenantId}'...`
      });
      
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/${tenantId}/redeploy-etl`, {
        method: 'POST'
      });
      
      if (res.ok) {
        const data = await res.json();
        setActionMessage({
          type: 'success',
          text: data.message || `Infraestructura ETL de '${tenantId}' re-desplegada con éxito. Se re-creó el Cloud Scheduler y se encoló el backfill histórico.`
        });
        fetchEtlData();
        onRefreshTenants(); // Recargar tenants para ver el estado deploying en tiempo real
      } else {
        throw new Error(`Error al re-desplegar la infraestructura ETL para '${tenantId}'`);
      }
    } catch (err: any) {
      setActionMessage({ type: 'error', text: err.message || 'Error al re-desplegar la ETL' });
    } finally {
      setRedeploying(false);
    }
  };

  useEffect(() => {
    fetchEtlData();
  }, []);

  return (
    <div className="space-y-6">
      {/* MENSAJES DE ACCIÓN INTERNOS */}
      {actionMessage && (
        <div className={`p-4 rounded-xl flex items-start gap-3 border ${
          actionMessage.type === 'success' 
            ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' 
            : 'bg-red-500/10 border-red-500/20 text-red-400'
        }`}>
          {actionMessage.type === 'success' ? <CheckCircle2 className="w-5 h-5 shrink-0" /> : <AlertCircle className="w-5 h-5 shrink-0" />}
          <span className="text-xs font-semibold">{actionMessage.text}</span>
        </div>
      )}

      {/* ESTADO DE CONFIGURACIÓN DE ORÍGENES DE DATOS */}
      <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden">
        <div className="p-5 border-b border-white/10 bg-white/[0.02] flex items-center gap-2">
          <Database className="w-5 h-5 text-teal animate-pulse" />
          <h2 className="text-xs font-black uppercase tracking-widest text-white">Estado de Configuración de Orígenes (GCP Secret Manager)</h2>
        </div>
        <div className="p-5 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {tenants.map(t => {
            const secrets = t.configured_secrets || {};
            const dep = t.deployment_status || {};
            const isDeploying = dep.status === 'deploying';
            
            return (
              <div key={t.tenant_id} className="p-4 bg-white/[0.02] border border-white/5 rounded-xl flex flex-col gap-3.5">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <h3 className="font-black text-xs uppercase tracking-wider text-white">{t.tenant_name}</h3>
                    <span className="text-[9px] text-mid mb-2 block">ID: {t.tenant_id}</span>
                    <button
                      type="button"
                      onClick={() => triggerDirectRedeploy(t.tenant_id)}
                      disabled={isDeploying || redeploying}
                      className="px-2 py-1 bg-amber-500/10 hover:bg-amber-500 text-amber-400 hover:text-navy border border-amber-500/20 rounded text-[9px] font-black uppercase tracking-wider transition-all flex items-center gap-1 disabled:opacity-50"
                    >
                      <RefreshCw className={`w-2.5 h-2.5 ${(isDeploying || redeploying) ? 'animate-spin' : ''}`} />
                      {isDeploying ? 'Desplegando...' : 'Re-desplegar ETL'}
                    </button>
                  </div>
                  <div className="flex gap-1.5 flex-wrap justify-end">
                    <span className={`px-2 py-1 rounded text-[9px] font-bold uppercase ${
                      secrets['ga4-creds'] ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/5 text-white/30 border border-white/5'
                    }`} title={secrets['ga4-creds'] ? 'Configurado' : 'Sin Configurar'}>
                      GA4
                    </span>
                    <span className={`px-2 py-1 rounded text-[9px] font-bold uppercase ${
                      secrets['adobe-creds'] ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/5 text-white/30 border border-white/5'
                    }`} title={secrets['adobe-creds'] ? 'Configurado' : 'Sin Configurar'}>
                      Adobe
                    </span>
                    <span className={`px-2 py-1 rounded text-[9px] font-bold uppercase ${
                      secrets['peec-key'] ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/5 text-white/30 border border-white/5'
                    }`} title={secrets['peec-key'] ? 'Configurado' : 'Sin Configurar'}>
                      Peec
                    </span>
                    <span className={`px-2 py-1 rounded text-[9px] font-bold uppercase ${
                      secrets['brandlight-key'] ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/5 text-white/30 border border-white/5'
                    }`} title={secrets['brandlight-key'] ? 'Configurado' : 'Sin Configurar'}>
                      Brand
                    </span>
                  </div>
                </div>

                {/* Indicador de Despliegue en Tiempo Real */}
                {dep.status && (
                  <div className={`p-3 rounded-lg text-[10px] flex flex-col gap-1 border ${
                    dep.status === 'deploying' ? 'bg-blue-500/5 border-blue-500/20 text-blue-300' :
                    dep.status === 'success' ? 'bg-emerald-500/5 border-emerald-500/20 text-emerald-300' :
                    'bg-red-500/5 border-red-500/20 text-red-300'
                  }`}>
                    <div className="flex items-center gap-1.5 font-bold uppercase tracking-wide text-[9px]">
                      {dep.status === 'deploying' && <RefreshCw className="w-3 h-3 animate-spin text-blue-400" />}
                      {dep.status === 'success' && <span className="text-emerald-400">✅</span>}
                      {dep.status === 'failed' && <span className="text-red-400">❌</span>}
                      <span>{dep.step}</span>
                    </div>
                    <p className="text-[9px] opacity-80 leading-relaxed font-mono break-all">{dep.message}</p>
                    <span className="text-[8px] opacity-40 self-end">
                      Sinc: {dep.updated_at ? new Date(dep.updated_at).toLocaleTimeString() : '--:--:--'}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ALERTAS DE SALUD MAESTRAS */}
      <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden">
        <div className="p-5 border-b border-white/10 bg-white/[0.02] flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-red" />
          <h2 className="text-xs font-black uppercase tracking-widest text-white">Alertas Operacionales Activas ({etlAlerts.length})</h2>
        </div>
        
        {etlAlerts.length === 0 ? (
          <div className="p-12 text-center text-mid text-xs flex flex-col items-center gap-2">
            <CheckCircle2 className="w-8 h-8 text-emerald-500" />
            <span>¡Excelente! No hay alertas de salud activas en el ecosistema ETL.</span>
          </div>
        ) : (
          <div className="divide-y divide-white/5">
            {etlAlerts.map(a => (
              <div key={a.alert_id} className="p-5 flex items-center justify-between gap-4 hover:bg-white/[0.01] transition-all">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-red shrink-0 mt-0.5" />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-black text-xs uppercase tracking-wider text-white">Inquilino: {a.tenant_id.toUpperCase()}</span>
                      <span className="text-[9px] px-1.5 py-0.5 bg-red-500/10 text-red-400 font-bold uppercase rounded">{a.provider}</span>
                    </div>
                    <p className="text-xs text-mid mt-1 font-semibold">{a.error_message}</p>
                    <span className="text-[10px] text-mid/60 mt-1 block">Ocurrido en: {new Date(a.timestamp).toLocaleString()}</span>
                  </div>
                </div>
                <button
                  onClick={() => handleDismissAlert(a.alert_id)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/20 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-colors"
                >
                  <Check className="w-3.5 h-3.5" /> Atendido / Borrar
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* HISTORIAL DE LOGS DE INGESTA DIARIA */}
      <div className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden">
        <div className="p-5 border-b border-white/10 bg-white/[0.02] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-teal" />
            <h2 className="text-xs font-black uppercase tracking-widest text-white">Historial de Ingesta Diaria</h2>
          </div>
          <button 
            onClick={fetchEtlData}
            className="text-[10px] font-bold uppercase text-mid hover:text-white transition-all"
          >
            Sincronizar Monitor
          </button>
        </div>

        {loadingEtl ? (
          <div className="p-12 text-center text-mid text-xs flex flex-col items-center gap-2">
            <RefreshCw className="w-6 h-6 animate-spin text-red" />
            <span>Recuperando log de operaciones...</span>
          </div>
        ) : etlHistory.length === 0 ? (
          <div className="p-12 text-center text-mid text-xs">
            No hay registros de ejecución de ETL todavía en Firestore.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-white/10 bg-white/[0.01] text-mid uppercase tracking-wider font-bold text-[10px]">
                  <th className="p-4">Tenant</th>
                  <th className="p-4">Fecha Sincronización</th>
                  <th className="p-4">Estado</th>
                  <th className="p-4 text-center">Registros Traídos (BQ)</th>
                  <th className="p-4">Detalles</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {etlHistory.map(h => (
                  <tr key={h.run_id} className="hover:bg-white/[0.01] transition-colors">
                    <td className="p-4 font-black uppercase text-white">{h.tenant_id}</td>
                    <td className="p-4 text-mid font-semibold">{new Date(h.timestamp).toLocaleString()}</td>
                    <td className="p-4">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${
                        h.status === "success" 
                          ? 'bg-emerald-500/10 text-emerald-400' 
                          : h.status === "partial_success"
                          ? 'bg-amber-500/10 text-amber-400'
                          : 'bg-red-500/10 text-red-400'
                      }`}>
                        {h.status}
                      </span>
                    </td>
                    <td className="p-4 text-center font-bold text-white text-sm">{h.records_processed ?? 0}</td>
                    <td className="p-4 text-mid text-[11px] font-mono break-all max-w-[400px]">
                      {JSON.stringify(h.results_summary)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
