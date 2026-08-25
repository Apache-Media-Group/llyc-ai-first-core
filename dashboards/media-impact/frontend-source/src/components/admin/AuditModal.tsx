// frontend/src/components/admin/AuditModal.tsx
import React, { useState, useEffect } from 'react';
import { Database, RefreshCw, CalendarRange, AlertCircle, CheckCircle2, Wrench } from 'lucide-react';
import { secureFetch } from '../../services/apiClient';

interface AuditModalProps {
  isOpen: boolean;
  onClose: () => void;
  tenantId: string | null;
}

export const AuditModal: React.FC<AuditModalProps> = ({
  isOpen,
  onClose,
  tenantId,
}) => {
  const [auditData, setAuditData] = useState<{ first_date: string | null; gaps: any[]; gap_count: number } | null>(null);
  const [loadingAudit, setLoadingAudit] = useState(false);
  const [patching, setPatching] = useState(false);

  const fetchDataGaps = async (id: string) => {
    try {
      setLoadingAudit(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/${id}/data-gaps`);
      if (res.ok) {
        const data = await res.json();
        setAuditData(data);
      } else {
        throw new Error("No se pudieron detectar los huecos de BigQuery");
      }
    } catch (err: any) {
      alert("Error al auditar huecos: " + err.message);
    } finally {
      setLoadingAudit(false);
    }
  };

  useEffect(() => {
    if (isOpen && tenantId) {
      setAuditData(null);
      fetchDataGaps(tenantId);
    }
  }, [isOpen, tenantId]);

  if (!isOpen || !tenantId) return null;

  const handleRunPatcher = async () => {
    if (!auditData || auditData.gaps.length === 0) return;
    
    try {
      setPatching(true);
      const res = await secureFetch(`/api/v1/mcp-analytics/admin/tenants/${tenantId}/patch`, {
        method: 'POST',
        body: JSON.stringify({ gaps: auditData.gaps })
      });
      
      const result = await res.json();
      if (res.ok) {
        alert("¡Proceso de parchado completado con éxito! Se rellenaron los huecos en BigQuery.");
        fetchDataGaps(tenantId);
      } else {
        throw new Error(result.detail || "Error al ejecutar el parchado");
      }
    } catch (err: any) {
      alert("Fallo de parchado: " + err.message);
    } finally {
      setPatching(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-navy/80 backdrop-blur-sm flex items-center justify-center p-5 z-[1000]">
      <div className="bg-[#0a1829] border border-white/10 rounded-2xl max-w-xl w-full shadow-2xl overflow-hidden">
        <div className="p-6 border-b border-white/10 bg-white/[0.02] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Database className="w-5 h-5 text-teal-400" />
            <h3 className="font-black text-sm uppercase tracking-widest text-teal-400">
              Auditoría del Data Lake & Patcher
            </h3>
          </div>
          <button 
            onClick={onClose}
            className="text-xs font-bold text-mid hover:text-white transition-colors"
          >
            Cerrar [X]
          </button>
        </div>
        
        <div className="p-6 space-y-5">
          <div className="flex items-center justify-between bg-white/5 border border-white/5 p-4 rounded-xl">
            <div>
              <span className="block text-[9px] font-bold uppercase tracking-widest text-mid">Cliente en auditoría</span>
              <span className="font-black text-sm text-white uppercase">{tenantId}</span>
            </div>
            <div className="text-right">
              <span className="block text-[9px] font-bold uppercase tracking-widest text-mid">Dataset de BigQuery</span>
              <span className="font-mono text-xs text-teal-400 font-bold">media_impact_data</span>
            </div>
          </div>

          {loadingAudit ? (
            <div className="p-12 text-center text-mid text-xs flex flex-col items-center gap-2">
              <RefreshCw className="w-6 h-6 animate-spin text-teal-400" />
              <span>Analizando consistencia de BigQuery...</span>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Primera fecha de datos */}
              <div className="flex items-center justify-between border-b border-white/5 pb-3">
                <span className="text-xs font-semibold text-white flex items-center gap-1.5">
                  <CalendarRange className="w-4 h-4 text-mid" /> Primera fecha registrada
                </span>
                <span className="font-mono text-xs font-bold bg-white/10 px-2 py-0.5 rounded text-white">
                  {auditData?.first_date || 'Sin datos todavía'}
                </span>
              </div>

              {/* Diagnóstico de Huecos */}
              <div>
                <span className="block text-[10px] font-bold uppercase tracking-wider text-mid mb-2">
                  Huecos de datos detectados ({auditData?.gap_count || 0} días faltantes)
                </span>
                
                {(!auditData || auditData.gaps.length === 0) ? (
                  <div className="p-6 bg-emerald-500/5 border border-emerald-500/10 rounded-xl text-center text-emerald-400 text-xs flex flex-col items-center gap-2">
                    <CheckCircle2 className="w-6 h-6 text-emerald-500" />
                    <span>¡Línea de tiempo 100% íntegra! No se detectan huecos en la base de datos.</span>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="max-h-40 overflow-y-auto divide-y divide-white/5 border border-white/10 rounded-xl bg-white/[0.01] custom-scrollbar">
                      {auditData.gaps.map((g, idx) => (
                        <div key={idx} className="p-3 flex items-center justify-between text-xs text-red-400 font-mono">
                          <span className="flex items-center gap-1.5">
                            <AlertCircle className="w-3.5 h-3.5" /> Hueco: {g.display}
                          </span>
                          <span className="text-[10px] bg-red-500/10 text-red-400 px-1.5 py-0.5 rounded font-black uppercase">Faltante</span>
                        </div>
                      ))}
                    </div>

                    {/* Botón de Patcher */}
                    <button
                      onClick={handleRunPatcher}
                      disabled={patching}
                      className="w-full py-3 bg-teal-500 hover:bg-teal-600 text-navy text-xs font-black uppercase tracking-widest rounded-xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-teal-500/25 disabled:opacity-50"
                    >
                      <Wrench className="w-4 h-4" /> 
                      {patching ? 'Parchando Base de Datos...' : 'Parchar Huecos de Datos'}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
