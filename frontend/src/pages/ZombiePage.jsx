import React, { useState } from 'react';
import Modal from '../components/Modal';
import { Ghost, Trash2, Clock, DollarSign, Cpu, AlertTriangle, ShieldCheck } from 'lucide-react';

export default function ZombiePage({ zombiesData, onRemediateZombie }) {
  const [selectedZombie, setSelectedZombie] = useState(null);
  const [isRemediating, setIsRemediating] = useState(false);

  const activeZombies = (zombiesData || []).filter(z => z.status === 'ACTIVE');
  const remediatedZombies = (zombiesData || []).filter(z => z.status === 'REMEDIATED');

  const handleConfirmRemediation = async () => {
    if (!selectedZombie) return;
    setIsRemediating(true);
    try {
      await onRemediateZombie(selectedZombie.id);
      setSelectedZombie(null);
    } catch (err) {
      console.error(err);
    } finally {
      setIsRemediating(false);
    }
  };

  const totalWasted = activeZombies.reduce((acc, curr) => acc + curr.wasted_monthly_cost, 0);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <Ghost className="w-6 h-6 text-rose-400" />
            Idle & Zombie Workload Detector
          </h2>
          <p className="text-xs text-slate-400 mt-1">Continuous background scan flagging workloads with sustained &lt;5% CPU utilization and zero traffic.</p>
        </div>

        {/* Wasted Cost Callout */}
        <div className="glass-panel px-4 py-2.5 rounded-xl border border-rose-500/30 bg-rose-950/20 flex items-center gap-3">
          <div className="p-2 rounded-lg bg-rose-500/20 text-rose-400">
            <DollarSign className="w-4 h-4" />
          </div>
          <div>
            <div className="text-[11px] text-slate-400 uppercase font-semibold">Active Wasted Spend</div>
            <div className="text-lg font-extrabold text-rose-400">${totalWasted.toFixed(2)} / month</div>
          </div>
        </div>
      </div>

      {/* Active Zombie Grid */}
      <div className="space-y-4">
        <h3 className="text-base font-bold text-slate-200 tracking-tight flex items-center gap-2">
          <span>Active Flagged Zombies</span>
          <span className="text-xs px-2.5 py-0.5 rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/30">
            {activeZombies.length} Detected
          </span>
        </h3>

        {activeZombies.length === 0 ? (
          <div className="glass-panel p-12 rounded-2xl text-center space-y-3">
            <ShieldCheck className="w-12 h-12 text-emerald-400 mx-auto" />
            <h4 className="text-lg font-bold text-white">Zero Zombie Workloads Detected!</h4>
            <p className="text-xs text-slate-400 max-w-md mx-auto">All active pods in your cluster maintain productive CPU/RAM usage and network IO.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {activeZombies.map((zombie) => (
              <div key={zombie.id} className="glass-panel p-5 rounded-2xl border border-rose-500/20 space-y-4 bg-gradient-to-b from-rose-950/10 to-slate-900/60 hover:border-rose-500/40 transition-all">
                <div className="flex items-start justify-between">
                  <div>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700 uppercase">
                      {zombie.namespace}
                    </span>
                    <h4 className="font-bold text-white text-sm mt-1">{zombie.pod_name}</h4>
                  </div>
                  <span className="p-1.5 rounded-lg bg-rose-500/20 text-rose-400 border border-rose-500/30">
                    <AlertTriangle className="w-4 h-4" />
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-2 text-xs bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                  <div>
                    <span className="text-slate-400 text-[11px] block">Avg CPU Usage</span>
                    <span className="font-mono text-rose-400 font-bold">{zombie.cpu_usage_avg} vCPU</span>
                  </div>
                  <div>
                    <span className="text-slate-400 text-[11px] block">Avg RAM Usage</span>
                    <span className="font-mono text-slate-300 font-medium">{zombie.mem_usage_avg_mb} MB</span>
                  </div>
                  <div>
                    <span className="text-slate-400 text-[11px] block">Network Traffic</span>
                    <span className="font-mono text-slate-300 font-medium">{zombie.net_activity_kb} KB</span>
                  </div>
                  <div>
                    <span className="text-slate-400 text-[11px] block">Idle Window</span>
                    <span className="font-mono text-slate-300 font-medium flex items-center gap-1">
                      <Clock className="w-3 h-3 text-amber-400" /> {zombie.idle_duration_hours}h
                    </span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-1">
                  <div>
                    <span className="text-[11px] text-slate-400 block">Wasted Run-Rate</span>
                    <span className="text-lg font-extrabold text-rose-400">${zombie.wasted_monthly_cost.toFixed(2)}/mo</span>
                  </div>
                  <button
                    onClick={() => setSelectedZombie(zombie)}
                    className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-xs font-semibold text-white shadow-lg shadow-rose-600/30 transition-all"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>Scale to 0</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Remediated Log Table */}
      {remediatedZombies.length > 0 && (
        <div className="space-y-3 pt-6 border-t border-slate-800">
          <h3 className="text-base font-bold text-slate-300 tracking-tight">Remediated Zombie Log</h3>
          <div className="glass-panel rounded-2xl border border-slate-800 overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-900/90 text-slate-400 uppercase tracking-wider font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-3 px-4">Namespace / Pod</th>
                  <th className="py-3 px-4">Workload</th>
                  <th className="py-3 px-4">Monthly Savings</th>
                  <th className="py-3 px-4">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {remediatedZombies.map((z) => (
                  <tr key={z.id}>
                    <td className="py-3 px-4 font-mono">{z.namespace} / {z.pod_name}</td>
                    <td className="py-3 px-4">{z.workload_name}</td>
                    <td className="py-3 px-4 font-bold text-emerald-400">${z.wasted_monthly_cost.toFixed(2)}/mo</td>
                    <td className="py-3 px-4">
                      <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                        REMEDIATED (Replicas=0)
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
        isOpen={!!selectedZombie}
        onClose={() => setSelectedZombie(null)}
        onConfirm={handleConfirmRemediation}
        title="Remediate Zombie Workload?"
        description={`Are you sure you want to scale deployment "${selectedZombie?.workload_name}" in namespace "${selectedZombie?.namespace}" down to 0 replicas? This will save $${selectedZombie?.wasted_monthly_cost.toFixed(2)}/month.`}
        confirmText="Confirm Scale to 0"
        isDestructive={true}
        isLoading={isRemediating}
      />
    </div>
  );
}
