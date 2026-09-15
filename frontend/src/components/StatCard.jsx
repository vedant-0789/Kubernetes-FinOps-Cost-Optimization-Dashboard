import React from 'react';

export default function StatCard({ title, value, subtext, icon: Icon, trend, color = 'emerald' }) {
  const colorMap = {
    emerald: 'from-emerald-500/20 to-emerald-500/5 text-emerald-400 border-emerald-500/30',
    cyan: 'from-cyan-500/20 to-cyan-500/5 text-cyan-400 border-cyan-500/30',
    amber: 'from-amber-500/20 to-amber-500/5 text-amber-400 border-amber-500/30',
    rose: 'from-rose-500/20 to-rose-500/5 text-rose-400 border-rose-500/30',
    violet: 'from-violet-500/20 to-violet-500/5 text-violet-400 border-violet-500/30',
  };

  const iconBgMap = {
    emerald: 'bg-emerald-500/20 text-emerald-400',
    cyan: 'bg-cyan-500/20 text-cyan-400',
    amber: 'bg-amber-500/20 text-amber-400',
    rose: 'bg-rose-500/20 text-rose-400',
    violet: 'bg-violet-500/20 text-violet-400',
  };

  return (
    <div className={`p-5 rounded-2xl glass-card bg-gradient-to-br ${colorMap[color]} transition-all hover:scale-[1.01]`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{title}</span>
        {Icon && (
          <div className={`p-2 rounded-xl ${iconBgMap[color]}`}>
            <Icon className="w-5 h-5" />
          </div>
        )}
      </div>
      
      <div className="mt-3 flex items-baseline gap-2">
        <span className="text-3xl font-extrabold tracking-tight text-white">{value}</span>
        {trend && (
          <span className="text-xs font-semibold px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
            {trend}
          </span>
        )}
      </div>

      {subtext && (
        <p className="mt-2 text-xs text-slate-400 flex items-center gap-1">
          {subtext}
        </p>
      )}
    </div>
  );
}
