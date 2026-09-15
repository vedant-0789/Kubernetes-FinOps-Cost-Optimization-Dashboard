import React from 'react';

export default function EfficiencyBadge({ pct, size = 'md' }) {
  let colorClass = 'bg-rose-500/10 text-rose-400 border-rose-500/30';
  let label = 'High Waste';
  
  if (pct >= 65.0) {
    colorClass = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
    label = 'Optimal';
  } else if (pct >= 35.0) {
    colorClass = 'bg-amber-500/10 text-amber-400 border-amber-500/30';
    label = 'Over-provisioned';
  }

  const pxSize = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs font-semibold';

  return (
    <span className={`inline-flex items-center gap-1.5 rounded-lg border ${pxSize} ${colorClass}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${pct >= 65 ? 'bg-emerald-400' : pct >= 35 ? 'bg-amber-400' : 'bg-rose-400'}`}></span>
      <span>{pct}%</span>
      <span className="opacity-75 font-normal">({label})</span>
    </span>
  );
}
