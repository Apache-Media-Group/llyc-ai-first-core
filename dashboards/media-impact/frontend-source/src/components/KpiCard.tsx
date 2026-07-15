import React from 'react';
import { ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface KpiCardProps {
  label: string;
  value: string | number;
  suffix?: string;
  trend?: string;
  isPositive?: boolean;
  source?: string;
  colorClass?: string;
}

export const KpiCard: React.FC<KpiCardProps> = ({ 
  label, 
  value, 
  suffix, 
  trend, 
  isPositive = true, 
  source,
  colorClass = ""
}) => {
  return (
    <div className={`bg-white rounded-xl p-5 border border-dashboard-border shadow-sm flex flex-col gap-1 ${colorClass}`}>
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-bold text-mid uppercase tracking-widest flex items-center gap-1">
          {label}
          {source && (
            <span className={`text-[9px] px-1.5 py-0.5 rounded font-black ${source === 'GA4' ? 'bg-teal-light text-teal' : 'bg-red-light text-red'}`}>
              {source}
            </span>
          )}
        </div>
      </div>
      
      <div className="text-3xl font-black text-navy flex items-baseline gap-1">
        {value}
        {suffix && <em className="text-sm font-normal not-italic text-mid">{suffix}</em>}
      </div>
      
      {trend && (
        <div className={`text-[10px] font-bold flex items-center gap-0.5 ${isPositive ? 'text-green-600' : 'text-red'}`}>
          {isPositive ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
          {trend}
        </div>
      )}
    </div>
  );
};
