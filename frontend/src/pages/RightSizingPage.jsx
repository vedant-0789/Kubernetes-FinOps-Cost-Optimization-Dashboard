import React, { useState } from 'react';
import Modal from '../components/Modal';
import { Sliders, Check, ArrowRight, ShieldCheck, Cpu, HardDrive, DollarSign, Sparkles } from 'lucide-react';

export default function RightSizingPage({ recommendationsData, onApplyRecommendation }) {
  const [selectedRec, setSelectedRec] = useState(null);
  const [isApplying, setIsApplying] = useState(false);

  const pendingRecs = (recommendationsData || []).filter(r => r.status === 'PENDING');
  const appliedRecs = (recommendationsData || []).filter(r => r.status === 'APPLIED');

  const handleConfirmApply = async () => {
    if (!selectedRec) return;
    setIsApplying(true);
    try {
      await onApplyRecommendation(selectedRec.id);
      setSelectedRec(null);
    } catch (err) {
      console.error(err);
    } finally {
      setIsApplying(false);
    }
  };

  const totalPotentialSavings = pendingRecs.reduce((acc, curr) => acc + curr.monthly_savings, 0);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <Sliders className="w-6 h-6 text-amber-400" />
            Pod Right-Sizing Recommendation Engine
          </h2>
          <p className="text-xs text-slate-400 mt-1">Calculates optimal CPU/RAM requests using p95 historical usage telemetry + 20% safety buffer.</p>
        </div>

        {/* Total Right-Sizing Savings */}
        <div className="glass-panel px-4 py-2.5 rounded-xl border border-amber-500/30 bg-amber-950/20 flex items-center gap-3">
          <div className="p-2 rounded-lg bg-amber-500/20 text-amber-400">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <div className="text-[11px] text-slate-400 uppercase font-semibold">Right-Sizing Savings Pool</div>
            <div className="text-lg font-extrabold text-amber-400">${totalPotentialSavings.toFixed(2)} / month</div>
          </div>
        </div>
      </div>

      {/* Recommendations Cards */}
      <div className="space-y-4">
        <h3 className="text-base font-bold text-slate-200 tracking-tight flex items-center gap-2">
          <span>Active Right-Sizing Suggestions</span>
          <span className="text-xs px-2.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
            {pendingRecs.length} Suggestions
          </span>
        </h3>

        {pendingRecs.length === 0 ? (
          <div className="glass-panel p-12 rounded-2xl text-center space-y-3">
            <ShieldCheck className="w-12 h-12 text-emerald-400 mx-auto" />
            <h4 className="text-lg font-bold text-white">All Workloads Optimally Sized!</h4>
            <p className="text-xs text-slate-400 max-w-md mx-auto">No over-provisioned CPU or Memory request bottlenecks identified in the current telemetry window.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {pendingRecs.map((rec) => (
              <div key={rec.id} className="glass-panel p-5 rounded-2xl border border-amber-500/20 space-y-4 bg-gradient-to-b from-amber-950/10 to-slate-900/60 hover:border-amber-500/40 transition-all">
                <div className="flex items-start justify-between">
                  <div>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700 uppercase">
                      {rec.namespace}
                    </span>
                    <h4 className="font-bold text-white text-base mt-1">{rec.pod_name}</h4>
                  </div>
                  <span className="text-xs font-semibold px-2 py-1 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                    p95 + 20% Buffer
                  </span>
                </div>

                {/* Comparison Grid */}
                <div className="grid grid-cols-2 gap-3 p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 text-xs">
                  {/* Current */}
                  <div className="space-y-1.5 border-r border-slate-800 pr-3">
                    <span className="text-slate-400 text-[11px] font-semibold uppercase tracking-wider block">Current Request</span>
                    <div className="flex items-center gap-1.5 text-slate-200 font-mono">
                      <Cpu className="w-3.5 h-3.5 text-slate-400" /> {rec.current_cpu_req} vCPU
                    </div>
                    <div className="flex items-center gap-1.5 text-slate-200 font-mono">
                      <HardDrive className="w-3.5 h-3.5 text-slate-400" /> {rec.current_mem_req_mb} MB
                    </div>
                    <div className="text-[11px] text-slate-400 pt-1">
                      Cost: <span className="text-rose-400 font-bold">${rec.current_monthly_cost.toFixed(2)}/mo</span>
                    </div>
                  </div>

                  {/* Recommended */}
                  <div className="space-y-1.5 pl-1">
                    <span className="text-emerald-400 text-[11px] font-semibold uppercase tracking-wider block flex items-center gap-1">
                      Recommended <ArrowRight className="w-3 h-3" />
                    </span>
                    <div className="flex items-center gap-1.5 text-emerald-400 font-mono font-bold">
                      <Cpu className="w-3.5 h-3.5" /> {rec.recommended_cpu_req} vCPU
                    </div>
                    <div className="flex items-center gap-1.5 text-emerald-400 font-mono font-bold">
                      <HardDrive className="w-3.5 h-3.5" /> {rec.recommended_mem_req_mb} MB
                    </div>
                    <div className="text-[11px] text-slate-400 pt-1">
                      Cost: <span className="text-emerald-400 font-bold">${rec.recommended_monthly_cost.toFixed(2)}/mo</span>
                    </div>
                  </div>
                </div>

                {/* Action Footer */}
                <div className="flex items-center justify-between pt-1">
                  <div>
                    <span className="text-[11px] text-slate-400 block">Monthly Savings</span>
                    <span className="text-lg font-extrabold text-emerald-400">${rec.monthly_savings.toFixed(2)}/mo</span>
                  </div>
                  <button
                    onClick={() => setSelectedRec(rec)}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-500 text-xs font-semibold text-white shadow-lg shadow-amber-600/30 transition-all"
                  >
                    <Check className="w-4 h-4" />
                    <span>Apply Right-Sizing</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Applied Recommendations Log */}
      {appliedRecs.length > 0 && (
        <div className="space-y-3 pt-6 border-t border-slate-800">
          <h3 className="text-base font-bold text-slate-300 tracking-tight">Applied Right-Sizing History</h3>
          <div className="glass-panel rounded-2xl border border-slate-800 overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-900/90 text-slate-400 uppercase tracking-wider font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-3 px-4">Namespace / Pod</th>
                  <th className="py-3 px-4">CPU Change</th>
                  <th className="py-3 px-4">RAM Change</th>
                  <th className="py-3 px-4">Monthly Savings</th>
                  <th className="py-3 px-4">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {appliedRecs.map((r) => (
                  <tr key={r.id}>
                    <td className="py-3 px-4 font-mono">{r.namespace} / {r.pod_name}</td>
                    <td className="py-3 px-4 font-mono">{r.current_cpu_req} → {r.recommended_cpu_req} vCPU</td>
                    <td className="py-3 px-4 font-mono">{r.current_mem_req_mb} → {r.recommended_mem_req_mb} MB</td>
                    <td className="py-3 px-4 font-bold text-emerald-400">${r.monthly_savings.toFixed(2)}/mo</td>
                    <td className="py-3 px-4">
                      <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                        APPLIED & PATCHED
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Confirmation Modal */}
      <Modal
        isOpen={!!selectedRec}
        onClose={() => setSelectedRec(null)}
        onConfirm={handleConfirmApply}
        title="Apply Right-Sizing Recommendation?"
        description={`This action will patch the container CPU request to ${selectedRec?.recommended_cpu_req} vCPU and Memory request to ${selectedRec?.recommended_mem_req_mb}MB for deployment "${selectedRec?.workload_name}" in namespace "${selectedRec?.namespace}". Realizing $${selectedRec?.monthly_savings.toFixed(2)}/month savings.`}
        confirmText="Confirm & Patch K8s"
        isDestructive={false}
        isLoading={isApplying}
      />
    </div>
  );
}
