import React, { useState } from 'react';
import { ArrowUpRight, ArrowDownRight, Info, X } from 'lucide-react';

interface KpiCardProps {
  label: string;
  value: string | number;
  suffix?: string;
  trend?: string;
  isPositive?: boolean;
  source?: string;
  colorClass?: string;
  tooltip?: string;
  longTooltip?: React.ReactNode;
}

export const KpiCard: React.FC<KpiCardProps> = ({ 
  label, 
  value, 
  suffix, 
  trend, 
  isPositive = true, 
  source,
  colorClass = "",
  tooltip,
  longTooltip
}) => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const valueStr = String(value);
  const isVeryLongValue = valueStr.length >= 7;
  const isLongValue = valueStr.length >= 5;
  
  const valueSizeClass = isVeryLongValue ? 'text-lg xl:text-xl tracking-tighter' : isLongValue ? 'text-xl xl:text-2xl tracking-tight' : 'text-3xl';

  return (
    <>
      <div className={`bg-white rounded-xl p-4 border border-dashboard-border shadow-sm flex flex-col gap-1.5 min-w-0 h-full ${colorClass}`}>
        <div className="flex items-start justify-between min-w-0">
          <div className="text-[10px] xl:text-[11px] font-bold text-mid uppercase tracking-widest flex items-start gap-1 flex-wrap">
            <div className="leading-tight break-words flex items-center gap-1 group relative">
              {label}
              {tooltip || longTooltip ? (
                <>
                  <button 
                    type="button"
                    onClick={() => longTooltip && setIsModalOpen(true)}
                    className={`focus:outline-none transition-colors ${longTooltip ? 'cursor-pointer hover:text-navy' : 'cursor-help hover:text-navy'} text-mid/60`}
                  >
                    <Info className="w-3 h-3" />
                  </button>
                  {tooltip && (
                    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block w-56 p-2.5 bg-navy text-white text-[10px] normal-case font-normal tracking-normal rounded-lg shadow-xl z-50 pointer-events-none before:content-[''] before:absolute before:top-full before:left-1/2 before:-translate-x-1/2 before:border-4 before:border-transparent before:border-t-navy">
                      {tooltip}
                      {longTooltip && (
                        <div className="mt-1 font-bold text-teal-light">Click para ver más detalle</div>
                      )}
                    </div>
                  )}
                </>
              ) : null}
            </div>
            {source ? (
              <span className={`text-[8px] xl:text-[9px] px-1.5 py-0.5 rounded font-black flex-shrink-0 mt-[-1px] ${source === 'GA4' ? 'bg-teal-light text-teal' : source === 'Adobe' ? 'bg-navy/10 text-navy' : 'bg-red-light text-red'}`}>
                {source}
              </span>
            ) : null}
          </div>
        </div>
        
        <div className={`${valueSizeClass} font-black text-navy flex items-baseline gap-1 min-w-0 mt-1`}>
          <span className="whitespace-nowrap leading-none">{value}</span>
          {suffix ? <em className="text-xs xl:text-sm font-normal not-italic text-mid flex-shrink-0">{suffix}</em> : null}
        </div>
        
        {trend ? (
          <div className={`text-[9px] xl:text-[10px] font-bold flex items-center gap-0.5 mt-auto ${isPositive ? 'text-green-600' : 'text-red'}`}>
            {isPositive ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
            <span className="truncate">{trend}</span>
          </div>
        ) : null}
      </div>

      {isModalOpen && longTooltip && (
        <div className="fixed inset-0 bg-navy/80 flex items-center justify-center p-5 z-[2000] backdrop-blur-sm transition-all duration-300">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden flex flex-col max-h-[90vh]">
            <div className="flex justify-between items-center p-6 border-b border-dashboard-border bg-dashboard-bg/50">
              <h3 className="text-lg font-bold text-navy uppercase tracking-widest flex items-center gap-2">
                <Info className="w-5 h-5 text-teal" />
                {label}
              </h3>
              <button 
                onClick={() => setIsModalOpen(false)}
                className="text-mid hover:text-red transition-colors p-1 rounded-full hover:bg-red-light"
              >
                <X size={20} strokeWidth={2.5} />
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto custom-scrollbar">
              <div className="space-y-4 text-sm text-navy/80 leading-relaxed">
                {longTooltip}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
