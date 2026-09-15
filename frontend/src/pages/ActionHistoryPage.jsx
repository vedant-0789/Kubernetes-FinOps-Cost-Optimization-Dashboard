import React from 'react';
import { History, CheckCircle2, Clock, ShieldAlert, Cpu, ArrowDownRight } from 'lucide-react';

export default function ActionHistoryPage({ actionHistoryData }) {
  const actions = actionHistoryData || [];
  const totalRealizedSavings = actions.reduce((acc, curr) => acc + curr.monthly_savings, 0);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <History className="w-6 h-6 text-cyan-400" />
            Remediation Action Audit Log
          </h2>
          <p className="text-xs text-slate-400 mt-1">Permanent financial audit log recording all automated and manual waste reduction operations.</p>
        </div>

        {/* Total Realized Savings Callout */}
        <div className="glass-panel px-4 py-2.5 rounded-xl border border-emerald-500/30 bg-emerald-950/20 flex items-center gap-3">
          <div className="p-2 rounded-lg bg-emerald-500/20 text-emerald-400">
            <CheckCircle2 className="w-4 h-4" />
          </div>
          <div>
            <div className="text-[11px] text-slate-400 uppercase font-semibold">Total Realized Savings</div>
            <div className="text-lg font-extrabold text-emerald-400">${totalRealizedSavings.toFixed(2)} / month</div>
          </div>
        </div>
      </div>

      {/* Main Log Table */}
      <div className="glass-panel rounded-2xl border border-slate-800 overflow-hidden">
        {actions.length === 0 ? (
          <div className="p-12 text-center text-slate-400 text-xs">No remediation actions executed yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-900/90 text-slate-400 uppercase tracking-wider font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-3.5 px-4">Timestamp</th>
                  <th className="py-3.5 px-4">Action Type</th>
                  <th className="py-3.5 px-4">Target Resource</th>
                  <th className="py-3.5 px-4">Details</th>
                  <th className="py-3.5 px-4">Triggered By</th>
                  <th className="py-3.5 px-4 text-right">Realized Savings</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-200">
                {actions.map((act) => (
                  <tr key={act.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3.5 px-4 font-mono text-slate-400">
                      {new Date(act.timestamp).toLocaleString()}
                    </td>
                    <td className="py-3.5 px-4">
                      <span className={`px-2.5 py-1 rounded-md text-xs font-bold border ${
                        act.action_type === 'RIGHT_SIZE'
                          ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                          : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                      }`}>
                        {act.action_type}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 font-mono font-semibold text-slate-100">
                      {act.namespace} / {act.target_resource}
                    </td>
                    <td className="py-3.5 px-4 text-slate-300 max-w-md">
                      {act.details}
                    </td>
                    <td className="py-3.5 px-4">
                      <span className={`px-2 py-0.5 rounded text-[11px] font-mono ${
                        act.applied_by === 'AUTO_REMEDIATION'
                          ? 'bg-violet-500/20 text-violet-400 border border-violet-500/30'
                          : 'bg-slate-800 text-slate-300 border border-slate-700'
                      }`}>
                        {act.applied_by}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-right font-extrabold text-emerald-400 text-sm">
                      +${act.monthly_savings.toFixed(2)}/mo
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
