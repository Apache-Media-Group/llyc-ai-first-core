import React from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
  Filler
} from 'chart.js';
import { Line, Bar, Doughnut } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

interface ChartWidgetProps {
  type: 'line' | 'bar' | 'doughnut';
  title: string;
  source?: 'GA4' | 'BL' | 'Adobe';
  data: any;
  options?: any;
  height?: number;
  legendId?: string;
  footer?: React.ReactNode;
}

export const ChartWidget: React.FC<ChartWidgetProps> = ({ 
  type, 
  title, 
  source, 
  data, 
  options = {}, 
  height = 200,
  legendId,
  footer
}) => {
  const baseOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
    },
    ...options
  };

  const renderChart = () => {
    const chartKey = React.useId() + (data?.datasets?.[0]?.data?.length || 0);

    switch (type) {
      case 'line': return <Line key={chartKey} data={data} options={baseOptions} />;
      case 'bar': return <Bar key={chartKey} data={data} options={baseOptions} />;
      case 'doughnut': return <Doughnut key={chartKey} data={data} options={baseOptions} />;
      default: return null;
    }
  };

  return (
    <div className="bg-white rounded-xl p-5 border border-dashboard-border shadow-sm flex flex-col">
      <div className="text-[11px] font-bold text-navy uppercase tracking-widest mb-4 flex items-center gap-1">
        {title}
        {source && (
          <span className={`text-[9px] px-1.5 py-0.5 rounded font-black ${source === 'GA4' ? 'bg-teal-light text-teal' : 'bg-red-light text-red'}`}>
            {source}
          </span>
        )}
      </div>
      
      <div style={{ height }}>
        {renderChart()}
      </div>

      {legendId && <div id={legendId} className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-[10px] font-bold uppercase tracking-widest text-mid"></div>}
      
      {footer && <div className="mt-4">{footer}</div>}
    </div>
  );
};
