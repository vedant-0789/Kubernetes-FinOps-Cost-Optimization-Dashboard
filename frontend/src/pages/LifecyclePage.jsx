import React from 'react';
import { GitMerge, CheckCircle, ArrowRight, Layers, Activity } from 'lucide-react';

export default function LifecyclePage({ lifecycleData }) {
  const stages = lifecycleData?.stages || [];

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
          <GitMerge className="w-6 h-6 text-violet-400" />
          FinOps Continuous Lifecycle View
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          7-Stage operational pipeline: Observe metrics → Measure utilization → Attribute costs → Detect waste → Recommend sizes → Optimize resources → Verify savings.
        </p>
      </div>

      {/* Lifecycle Visual Stepper Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stages.map((stg, idx) => (
          <div key={stg.stage_id} className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-3 relative overflow-hidden bg-gradient-to-b from-slate-900/90 to-slate-950/90">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold px-2.5 py-1 rounded-md bg-violet-500/20 text-violet-400 border border-violet-500/30">
                Stage {idx + 1}
              </span>
              <span className="text-xs text-slate-400 font-mono">${stg.monthly_cost} /mo</span>
            </div>

            <div>
              <h4 className="font-bold text-white text-base tracking-tight">{stg.title}</h4>
              <p className="text-xs text-slate-400 mt-1 leading-relaxed">{stg.description}</p>
            </div>

            <div className="pt-2 border-t border-slate-800 flex items-center justify-between text-xs">
              <span className="text-slate-300 font-medium">{stg.badge}</span>
              <span className="text-emerald-400 font-semibold">{stg.pod_count} Active Pods</span>
            </div>
          </div>
        ))}
      </div>

      {/* Cycle Banner */}
      <div className="glass-panel p-6 rounded-2xl border border-emerald-500/30 bg-gradient-to-r from-emerald-950/20 via-slate-900/60 to-cyan-950/20 flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="space-y-1">
          <h3 className="text-base font-bold text-white tracking-tight flex items-center gap-2">
            <Activity className="w-5 h-5 text-emerald-400" />
            Closed-Loop Continuous FinOps Architecture
          </h3>
          <p className="text-xs text-slate-300 max-w-2xl leading-relaxed">
            The FinOps engine continuously polls Kubernetes telemetry, updates OpenCost allocation formulas in real time, flags idle workloads, and produces right-sizing patches. Applying a recommendation automatically loops back to Stage 7 (Verify) to validate cost reductions.
          </p>
        </div>
        <div className="px-4 py-2 rounded-xl bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-xs font-bold whitespace-nowrap">
          Continuous Closed Loop Active
        </div>
      </div>
    </div>
  );
}
