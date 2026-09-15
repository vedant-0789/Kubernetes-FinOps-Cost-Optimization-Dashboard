import React from 'react';
import { Cpu, RefreshCw, ShieldCheck, Database, Server } from 'lucide-react';

export default function Navbar({ overviewData, onRefresh, isRefreshing }) {
  const isMock = overviewData?.mock_mode ?? true;

  return (
    <header className="h-16 glass-panel border-b border-slate-800/80 px-6 flex items-center justify-between sticky top-0 z-30">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-emerald-500 to-cyan-500 flex items-center justify-center shadow-lg shadow-emerald-500/20">
            <Cpu className="w-5 h-5 text-slate-950 font-bold" />
          </div>
          <div>
            <h1 className="font-bold text-base tracking-tight text-white flex items-center gap-2">
              K8s FinOps <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">v1.0</span>
            </h1>
            <p className="text-xs text-slate-400">Kubernetes Cost Allocation & Waste Elimination</p>
          </div>
        </div>

        {/* Mock/Real Mode Badge */}
        <div className="ml-4 flex items-center gap-2">
          {isMock ? (
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
              <Database className="w-3.5 h-3.5" />
              Simulated Mock Mode
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <Server className="w-3.5 h-3.5" />
              Live K8s Cluster Connected
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-4">
        {/* Cluster Status */}
        <div className="hidden md:flex items-center gap-2 text-xs text-slate-400 bg-slate-900/60 px-3 py-1.5 rounded-lg border border-slate-800">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          <span>Cluster: <strong className="text-slate-200">prod-us-east-1</strong> (3 Nodes, {overviewData?.total_pods || 22} Pods)</span>
        </div>

        {/* Refresh Button */}
        <button
          onClick={onRefresh}
          disabled={isRefreshing}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 border border-slate-700 transition-all hover:border-emerald-500/30 disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-emerald-400' : ''}`} />
          <span>{isRefreshing ? 'Scanning...' : 'Run Scan'}</span>
        </button>
      </div>
    </header>
  );
}
