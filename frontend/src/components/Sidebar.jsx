import React from 'react';
import { 
  LayoutDashboard, 
  Layers, 
  Ghost, 
  Sliders, 
  History, 
  GitMerge, 
  Settings 
} from 'lucide-react';

export default function Sidebar({ activeTab, setActiveTab, zombieCount = 0, recCount = 0 }) {
  const navItems = [
    { id: 'overview', label: 'Cluster Overview', icon: LayoutDashboard },
    { id: 'namespaces', label: 'Namespaces & Pods', icon: Layers },
    { 
      id: 'zombies', 
      label: 'Zombie Workloads', 
      icon: Ghost, 
      badge: zombieCount > 0 ? zombieCount : null,
      badgeColor: 'bg-rose-500/20 text-rose-400 border-rose-500/30'
    },
    { 
      id: 'rightsizing', 
      label: 'Right-Sizing', 
      icon: Sliders,
      badge: recCount > 0 ? recCount : null,
      badgeColor: 'bg-amber-500/20 text-amber-400 border-amber-500/30'
    },
    { id: 'history', label: 'Action Audit Log', icon: History },
    { id: 'lifecycle', label: 'FinOps Lifecycle', icon: GitMerge },
    { id: 'settings', label: 'Settings & Pricing', icon: Settings },
  ];

  return (
    <aside className="w-64 glass-panel border-r border-slate-800/80 flex flex-col justify-between py-6 px-3 shrink-0 min-h-[calc(100vh-4rem)]">
      <div className="space-y-1">
        <div className="px-3 pb-3 text-xs font-semibold text-slate-400 tracking-wider uppercase">
          FinOps Core Navigation
        </div>
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-500/20 to-cyan-500/10 text-emerald-400 border border-emerald-500/30 shadow-lg shadow-emerald-500/10'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
              }`}
            >
              <div className="flex items-center gap-3">
                <Icon className={`w-4 h-4 ${isActive ? 'text-emerald-400' : 'text-slate-400'}`} />
                <span>{item.label}</span>
              </div>
              {item.badge && (
                <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${item.badgeColor}`}>
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Footer Info Box */}
      <div className="px-3 pt-4 border-t border-slate-800/60">
        <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-400 space-y-1">
          <div className="font-semibold text-slate-300">OpenCost Engine</div>
          <p className="text-[11px]">Calculates vCPU & RAM allocation cost per namespace continuous stream.</p>
        </div>
      </div>
    </aside>
  );
}
