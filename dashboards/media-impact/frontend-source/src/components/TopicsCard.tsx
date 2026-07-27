import React from 'react';

interface Topic {
  l?: string;
  w?: number;
  name?: string;
  score?: number;
}

interface TopicsCardProps {
  title: string;
  topics: Topic[];
  source?: string;
}

export const TopicsCard: React.FC<TopicsCardProps> = ({ title, topics, source }) => {
  // Encontrar el valor máximo para calcular los anchos proporcionales
  const maxScore = Math.max(...topics.map(t => t.w !== undefined ? t.w : (t.score || 0)), 1);

  return (
    <div className="bg-gradient-to-br from-white to-dashboard-bg/30 rounded-2xl p-6 border border-dashboard-border shadow-sm hover:shadow-md transition-shadow duration-300">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-xs font-black text-navy uppercase tracking-widest flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-red animate-pulse"></span>
          {title}
        </h3>
        {source && (
          <span className={`text-[9px] px-2 py-1 rounded shadow-sm font-black ${source === 'GA4' ? 'bg-teal/10 text-teal' : 'bg-red/10 text-red border border-red/10'}`}>
            {source}
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
        {topics.length > 0 && topics.reduce((acc, t) => acc + (t.w !== undefined ? t.w : (t.score || 0)), 0) > 0 ? topics.map((t, i) => {
          const label = t.l || t.name || 'Sin título';
          const weight = t.w !== undefined ? t.w : (t.score || 0);
          const percentage = Math.max(5, (weight / maxScore) * 100); // Mínimo 5% visual
          
          return (
            <div key={i} className="group relative flex flex-col gap-1.5 p-3 rounded-xl hover:bg-white border border-transparent hover:border-dashboard-border/60 transition-all duration-300 cursor-default">
              <div className="flex justify-between items-end">
                <span className="text-xs font-bold text-navy truncate pr-2 group-hover:text-red transition-colors" title={label}>{label}</span>
                <span className="text-[10px] font-black text-mid group-hover:text-navy transition-colors">{weight.toLocaleString('es-ES')}</span>
              </div>
              <div className="w-full h-1.5 bg-dashboard-border/40 rounded-full overflow-hidden">
                <div 
                  className="h-full bg-gradient-to-r from-red-light to-red rounded-full transition-all duration-1000 ease-out relative overflow-hidden" 
                  style={{ width: `${percentage}%` }}
                >
                  <div className="absolute inset-0 bg-white/20 w-full h-full transform -translate-x-full group-hover:animate-[shimmer_1.5s_infinite]"></div>
                </div>
              </div>
            </div>
          );
        }) : (
          <div className="col-span-full flex flex-col items-center justify-center py-10 text-center">
             <div className="w-10 h-10 mb-3 rounded-full bg-dashboard-border/30 flex items-center justify-center">
                <svg className="w-4 h-4 text-mid/60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
             </div>
             <p className="text-xs font-bold text-mid/80 uppercase tracking-widest">Sin datos de impacto</p>
             <p className="text-[10px] text-mid/60 mt-1 max-w-xs">No hay suficientes menciones o volumen en este periodo para generar un ranking temático.</p>
          </div>
        )}
      </div>
      
      <style>{`
        @keyframes shimmer {
          100% { transform: translateX(100%); }
        }
      `}</style>
    </div>
  );
};
