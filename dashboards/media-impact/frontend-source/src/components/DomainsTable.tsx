import React from 'react';

interface Row {
  d: string;
  m: number;
  g: number;
  c?: string;
}

interface DomainsTableProps {
  title: string;
  rows: Row[];
  source?: string;
}

export const DomainsTable: React.FC<DomainsTableProps> = ({ title, rows, source }) => {
  return (
    <div className="bg-white rounded-xl overflow-hidden border border-dashboard-border shadow-sm">
      <div className="p-5 pb-0">
        <div className="text-[11px] font-bold text-navy uppercase tracking-widest mb-4 flex items-center gap-1">
          {title}
          {source && (
            <span className={`text-[9px] px-1.5 py-0.5 rounded font-black ${source === 'GA4' ? 'bg-teal-light text-teal' : 'bg-red-light text-red'}`}>
              {source}
            </span>
          )}
        </div>
      </div>
      <table className="w-full text-left border-collapse">
        <thead className="bg-dashboard-bg/50">
          <tr>
            <th className="px-5 py-2 text-[10px] font-bold text-mid uppercase tracking-widest">Dominio</th>
            <th className="px-5 py-2 text-[10px] font-bold text-mid uppercase tracking-widest text-right">Score de Visibilidad</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-dashboard-border">
          {rows.length > 0 ? rows.map((r, i) => (
            <tr key={i} className="hover:bg-dashboard-bg/20 transition-colors">
              <td className="px-5 py-2.5 text-xs font-medium text-navy flex items-center gap-2">
                {r.d}
                {r.c && (
                  <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${
                    r.c.toLowerCase() === 'owned' ? 'bg-green-100 text-green-700' :
                    r.c.toLowerCase() === 'ugc' ? 'bg-purple-100 text-purple-700' :
                    'bg-blue-100 text-blue-700'
                  }`}>
                    {r.c}
                  </span>
                )}
              </td>
              <td className={`px-5 py-2.5 text-xs font-bold text-right ${r.g >= 0 ? 'text-green-600' : 'text-red'}`}>
                {r.g >= 0 ? `+${r.g}` : r.g}
              </td>
            </tr>
          )) : (
            <tr><td colSpan={2} className="px-5 py-8 text-center text-mid text-xs italic">Sin datos de dominios para este periodo</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
};
