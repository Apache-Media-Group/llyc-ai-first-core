import React from 'react';

interface Topic {
  l: string;
  w: number;
}

interface TopicsCardProps {
  title: string;
  topics: Topic[];
  source?: 'GA4' | 'BL';
}

export const TopicsCard: React.FC<TopicsCardProps> = ({ title, topics, source }) => {
  return (
    <div className="bg-white rounded-xl p-5 border border-dashboard-border shadow-sm">
      <div className="text-[11px] font-bold text-navy uppercase tracking-widest mb-4 flex items-center gap-1">
        {title}
        {source && (
          <span className={`text-[9px] px-1.5 py-0.5 rounded font-black ${source === 'GA4' ? 'bg-teal-light text-teal' : 'bg-red-light text-red'}`}>
            {source}
          </span>
        )}
      </div>
      <div className="space-y-4">
        {topics.map((t, i) => (
          <div key={i} className="flex items-center gap-3">
            <span className="text-[10px] font-bold text-navy w-32 truncate">{t.l}</span>
            <div className="flex-1 h-1.5 bg-dashboard-bg rounded-full overflow-hidden">
              <div 
                className="h-full bg-red transition-all duration-1000" 
                style={{ width: `${t.w}%` }}
              ></div>
            </div>
            <span className="text-[10px] font-bold text-mid w-4 text-right">{t.w}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
