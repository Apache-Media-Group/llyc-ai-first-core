import React from 'react';
import { Calendar, MapPin, RefreshCw, FileText, Filter, FileUp } from 'lucide-react';
import type { AnalyticsState } from '../types';

interface HeaderProps {
  onRefresh: () => void;
  onExport: () => void;
  onFileUpload?: (file: File) => void;
  loading: boolean;
  exporting: boolean;
  lastUpdated: string;
  tenant?: {
    tenant_id: string;
    tenant_name: string;
    logo_url: string;
    primary_color: string;
  };
}

export const Header: React.FC<HeaderProps> = ({ onRefresh, onExport, onFileUpload, loading, exporting, lastUpdated, tenant }) => (
  <header className="h-16 bg-white border-b border-dashboard-border flex items-center justify-between px-8 sticky top-0 z-[50]">
    <div className="flex items-center gap-6">
      {tenant?.logo_url ? (
        <img src={tenant.logo_url} alt={tenant.tenant_name} className="h-8 object-contain max-w-[120px]" />
      ) : (
        <div className="text-red font-black text-xl tracking-tighter">{tenant?.tenant_name || 'LLYC'}</div>
      )}
      <div className="h-4 w-[1px] bg-dashboard-border"></div>
      <div className="text-[11px] font-black uppercase tracking-widest text-navy">
        Intelligence Dashboard <span className="text-mid font-medium">2026</span>
      </div>
    </div>
    
    <div className="flex items-center gap-3">
      <div id="ts" className="text-[10px] font-bold uppercase tracking-widest text-mid">
        Actualizado: {lastUpdated}
      </div>
      <button 
        onClick={onRefresh}
        className="w-8 h-8 flex items-center justify-center bg-dashboard-bg rounded-lg hover:bg-navy-light transition-colors"
        disabled={loading}
      >
        <RefreshCw className={`w-4 h-4 text-navy ${loading ? 'spin' : ''}`} />
      </button>
      
      {onFileUpload && (
        <label className="flex items-center gap-2 px-4 py-2 bg-navy-light text-navy rounded-lg text-[11px] font-black uppercase tracking-widest hover:opacity-90 cursor-pointer transition-opacity">
          <FileUp className="w-4 h-4" /> Importar CSV
          <input 
            type="file" 
            className="hidden" 
            onChange={(e) => {
              if (e.target.files && e.target.files[0]) {
                onFileUpload(e.target.files[0]);
              }
            }} 
            accept=".csv,.xlsx,.xls" 
          />
        </label>
      )}

      <button 
        onClick={onExport}
        disabled={exporting}
        className="flex items-center gap-2 px-4 py-2 bg-navy text-white rounded-lg text-[11px] font-black uppercase tracking-widest hover:opacity-90 transition-opacity disabled:opacity-50"
      >
        <FileText className={`w-4 h-4 ${exporting ? 'spin' : ''}`} /> {exporting ? 'Exportar PDF' : 'Exportar PDF'}
      </button>
    </div>
  </header>
);

interface FilterBarProps {
  state: AnalyticsState;
  updateState: (updates: Partial<AnalyticsState>) => void;
  onApply: () => void;
  connections?: Array<{ connection_id: string; display_name: string; platform: string }>;
  accounts?: Array<{ account_id: string; display_name: string }>;
  properties?: Array<{ property_id: string; display_name: string }>;
  segments?: Array<{ id: string; name: string }>;
  onConnectionChange?: (connectionId: string) => void;
  onAccountChange?: (accountId: string) => void;
}

export const FilterBar: React.FC<FilterBarProps> = ({ 
  state, 
  updateState, 
  onApply,
  connections = [],
  accounts = [],
  properties = [],
  segments = [],
  onConnectionChange,
  onAccountChange
}) => {
  const isAdobe = state.connection_id?.toLowerCase().includes('adobe');

  const generalConnections = connections.filter(c => c.platform === 'GA4' || c.platform === 'ADOBE_ANALYTICS');
  const aiConnections = connections.filter(c => c.platform === 'PEEC' || c.platform === 'BRANDLIGHT');

  return (
    <div className="bg-white border-b border-dashboard-border px-8 py-3 flex items-center gap-4 overflow-x-auto whitespace-nowrap custom-scrollbar">
      <div className="flex items-center gap-2">
        <Calendar className="w-4 h-4 text-mid" />
        <span className="text-[11px] font-bold text-mid uppercase tracking-widest">Desde</span>
        <input 
          type="date" 
          value={state.from} 
          onChange={e => updateState({ from: e.target.value })}
          className="bg-dashboard-bg border border-dashboard-border rounded px-2 py-1 text-xs outline-none focus:ring-1 ring-red/20"
        />
        <span className="text-[11px] font-bold text-mid uppercase tracking-widest">hasta</span>
        <input 
          type="date" 
          value={state.to} 
          onChange={e => updateState({ to: e.target.value })}
          className="bg-dashboard-bg border border-dashboard-border rounded px-2 py-1 text-xs outline-none focus:ring-1 ring-red/20"
        />
      </div>
      
      <div className="h-4 w-[1px] bg-dashboard-border"></div>

      {/* Orígenes / Conexiones Generales */}
      {generalConnections.length > 0 && (
        <>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-bold text-mid uppercase tracking-widest">General Analytics</span>
            <select 
              value={generalConnections.some(c => c.connection_id === state.connection_id) ? state.connection_id : ''}
              onChange={e => onConnectionChange?.(e.target.value)}
              className="bg-dashboard-bg border border-dashboard-border rounded px-2 py-1 text-xs outline-none focus:ring-1 ring-red/20 max-w-[150px] overflow-hidden text-ellipsis"
            >
              <option value="">Seleccionar Origen...</option>
              {generalConnections.map(c => (
                <option key={c.connection_id} value={c.connection_id}>
                  {c.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="h-4 w-[1px] bg-dashboard-border"></div>
        </>
      )}

      {/* Orígenes / Conexiones AI */}
      {aiConnections.length > 0 && (
        <>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-bold text-mid uppercase tracking-widest">AI Analytics</span>
            <select 
              value={aiConnections.some(c => c.connection_id === state.connection_id) ? state.connection_id : ''}
              onChange={e => onConnectionChange?.(e.target.value)}
              className="bg-dashboard-bg border border-dashboard-border rounded px-2 py-1 text-xs outline-none focus:ring-1 ring-red/20 max-w-[150px] overflow-hidden text-ellipsis"
            >
              <option value="">Seleccionar Origen...</option>
              {aiConnections.map(c => (
                <option key={c.connection_id} value={c.connection_id}>
                  {c.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="h-4 w-[1px] bg-dashboard-border"></div>
        </>
      )}

      {/* Cuentas / Compañías */}
      {accounts.length > 0 && (
        <>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-bold text-mid uppercase tracking-widest">
              {isAdobe ? 'Compañía' : 'Cuenta'}
            </span>
            <select 
              value={state.account_id || ''}
              onChange={e => onAccountChange?.(e.target.value)}
              className="bg-dashboard-bg border border-dashboard-border rounded px-2 py-1 text-xs outline-none focus:ring-1 ring-red/20 max-w-[180px] overflow-hidden text-ellipsis font-bold"
            >
              <option value="">
                {isAdobe ? 'Seleccionar Compañía...' : 'Seleccionar Cuenta...'}
              </option>
              {accounts.map(a => (
                <option key={a.account_id} value={a.account_id}>
                  {a.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="h-4 w-[1px] bg-dashboard-border"></div>
        </>
      )}

      {/* Propiedades / Suites */}
      {properties.length > 0 && (
        <>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-bold text-mid uppercase tracking-widest">
              {isAdobe ? 'Report Suite' : 'Propiedad'}
            </span>
            <select 
              value={state.property_id || ''}
              onChange={e => updateState({ property_id: e.target.value })}
              className="bg-dashboard-bg border border-dashboard-border rounded px-2 py-1 text-xs outline-none focus:ring-1 ring-red/20 max-w-[200px] overflow-hidden text-ellipsis font-bold text-red"
            >
              <option value="">
                {isAdobe ? 'Seleccionar Report Suite...' : 'Seleccionar Propiedad...'}
              </option>
              {properties.map(p => (
                <option key={p.property_id} value={p.property_id}>
                  {p.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="h-4 w-[1px] bg-dashboard-border"></div>
        </>
      )}

      {isAdobe ? (
        <>
          <div className="flex items-center gap-2">
            <MapPin className="w-4 h-4 text-[#F54963]" />
            <span className="text-[11px] font-bold text-mid uppercase tracking-widest text-[#F54963]">Mercado / Segmento</span>
            <select 
              value={state.segment_id || ''}
              onChange={e => updateState({ segment_id: e.target.value })}
              className="bg-dashboard-bg border border-dashboard-border rounded px-2 py-1 text-xs outline-none focus:ring-1 ring-red/20 max-w-[180px] overflow-hidden text-ellipsis font-bold text-[#F54963]"
            >
              <option value="">Todos los segmentos</option>
              {segments.map(s => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        </>
      ) : (
        <div className="flex items-center gap-2">
          <MapPin className="w-4 h-4 text-mid" />
          <span className="text-[11px] font-bold text-mid uppercase tracking-widest">Mercado</span>
          <select 
            value={state.market}
            onChange={e => updateState({ market: e.target.value })}
            className="bg-dashboard-bg border border-dashboard-border rounded px-2 py-1 text-xs outline-none focus:ring-1 ring-red/20"
          >
            <option value="all">Todos los mercados</option>
            <option value="es">España</option>
            <option value="mx">México</option>
            <option value="co">Colombia</option>
          </select>
        </div>
      )}
      
      <div className="h-4 w-[1px] bg-dashboard-border"></div>
      
      <button 
        onClick={onApply}
        className="bg-red/10 text-red px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest hover:bg-red hover:text-white transition-all flex items-center gap-1 shrink-0"
      >
        <Filter className="w-3 h-3" /> Aplicar Filtros
      </button>
    </div>
  );
};
