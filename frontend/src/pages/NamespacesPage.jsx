import React, { useState } from 'react';
import EfficiencyBadge from '../components/EfficiencyBadge';
import { Layers, ChevronRight, Server, Search, ArrowUpDown, Cpu, HardDrive } from 'lucide-react';

export default function NamespacesPage({ namespacesData, fetchPods }) {
  const [search, setSearch] = useState('');
  const [selectedNamespace, setSelectedNamespace] = useState(null);
  const [pods, setPods] = useState([]);
  const [isLoadingPods, setIsLoadingPods] = useState(false);

  const filteredNamespaces = (namespacesData || []).filter(ns => 
    ns.name.toLowerCase().includes(search.toLowerCase())
  );

  const handleSelectNamespace = async (ns) => {
    setSelectedNamespace(ns);
    setIsLoadingPods(true);
    try {
      const data = await fetchPods(ns.name);
      setPods(data);
    } catch (err) {
      console.error(err);
    } finally {
      setIsLoadingPods(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <Layers className="w-6 h-6 text-emerald-400" />
            Namespace Cost & Efficiency Attribution
          </h2>
          <p className="text-xs text-slate-400 mt-1">Detailed CPU/Memory resource allocation vs actual telemetry per namespace.</p>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search namespace..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 pr-4 py-2 rounded-xl bg-slate-900/80 border border-slate-700 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500/50 w-64"
          />
        </div>
      </div>

      {/* Main Table */}
      <div className="glass-panel rounded-2xl border border-slate-800 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-900/90 text-slate-400 uppercase tracking-wider font-semibold border-b border-slate-800">
              <tr>
                <th className="py-3.5 px-4">Namespace Name</th>
                <th className="py-3.5 px-4">Pods</th>
                <th className="py-3.5 px-4">CPU (Req vs Usage)</th>
                <th className="py-3.5 px-4">RAM (Req vs Usage)</th>
                <th className="py-3.5 px-4">Efficiency</th>
                <th className="py-3.5 px-4 text-right">Monthly Cost</th>
                <th className="py-3.5 px-4 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-200">
              {filteredNamespaces.map((ns) => {
                const cpuPct = ns.total_cpu_req > 0 ? (ns.total_cpu_usage / ns.total_cpu_req) * 100 : 0;
                const memPct = ns.total_mem_req_mb > 0 ? (ns.total_mem_usage_mb / ns.total_mem_req_mb) * 100 : 0;

                return (
                  <tr key={ns.name} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-4 px-4 font-semibold text-slate-100 flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
                      <span>{ns.name}</span>
                    </td>
                    <td className="py-4 px-4 text-slate-300">
                      <span className="px-2 py-0.5 rounded-md bg-slate-800 border border-slate-700 font-mono">
                        {ns.pod_count} Pods
                      </span>
                    </td>
                    
                    {/* CPU Bar */}
                    <td className="py-4 px-4 w-48">
                      <div className="space-y-1">
                        <div className="flex justify-between text-[11px] text-slate-400">
                          <span>{ns.total_cpu_usage} vCPU</span>
                          <span className="font-mono">req: {ns.total_cpu_req}</span>
                        </div>
                        <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${cpuPct > 65 ? 'bg-emerald-400' : cpuPct > 35 ? 'bg-amber-400' : 'bg-rose-400'}`}
                            style={{ width: `${Math.min(100, cpuPct)}%` }}
                          ></div>
                        </div>
                      </div>
                    </td>

                    {/* RAM Bar */}
                    <td className="py-4 px-4 w-48">
                      <div className="space-y-1">
                        <div className="flex justify-between text-[11px] text-slate-400">
                          <span>{Math.round(ns.total_mem_usage_mb)} MB</span>
                          <span className="font-mono">req: {Math.round(ns.total_mem_req_mb)}MB</span>
                        </div>
                        <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${memPct > 65 ? 'bg-emerald-400' : memPct > 35 ? 'bg-amber-400' : 'bg-rose-400'}`}
                            style={{ width: `${Math.min(100, memPct)}%` }}
                          ></div>
                        </div>
                      </div>
                    </td>

                    <td className="py-4 px-4">
                      <EfficiencyBadge pct={ns.efficiency_pct} />
                    </td>

                    <td className="py-4 px-4 text-right font-extrabold text-white text-sm">
                      ${ns.monthly_cost.toFixed(2)}
                    </td>

                    <td className="py-4 px-4 text-right">
                      <button
                        onClick={() => handleSelectNamespace(ns)}
                        className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-emerald-400 border border-slate-700 transition-all flex items-center gap-1 ml-auto"
                      >
                        <span>Drill Down</span>
                        <ChevronRight className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pod Level Drill Down Drawer/Modal */}
      {selectedNamespace && (
        <div className="glass-panel p-6 rounded-2xl border border-slate-700 space-y-4 animate-fade-in">
          <div className="flex items-center justify-between pb-4 border-b border-slate-800">
            <div>
              <h3 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
                <Server className="w-5 h-5 text-emerald-400" />
                Pod Detail View: <span className="text-emerald-400">{selectedNamespace.name}</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">Individual pod CPU/RAM requests, telemetry usage, and OpenCost attribution.</p>
            </div>
            <button
              onClick={() => setSelectedNamespace(null)}
              className="px-3 py-1 rounded-lg bg-slate-800 text-xs text-slate-400 hover:text-white"
            >
              Close Drawer
            </button>
          </div>

          {isLoadingPods ? (
            <div className="py-8 text-center text-slate-400 text-xs">Fetching pod metrics...</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {pods.map((pod) => (
                <div key={pod.pod_name} className="p-4 rounded-xl glass-card space-y-3">
                  <div className="flex items-start justify-between">
                    <div>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700 uppercase">
                        {pod.workload_type}
                      </span>
                      <h4 className="font-bold text-slate-100 text-sm mt-1">{pod.pod_name}</h4>
                    </div>
                    <EfficiencyBadge pct={pod.efficiency_pct} size="sm" />
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-xs bg-slate-900/60 p-3 rounded-lg border border-slate-800/80">
                    <div>
                      <div className="text-slate-400 text-[11px] flex items-center gap-1">
                        <Cpu className="w-3 h-3 text-emerald-400" /> CPU Usage / Req
                      </div>
                      <div className="font-mono text-slate-200 mt-0.5">
                        {pod.cpu_usage} / {pod.cpu_req} vCPU
                      </div>
                    </div>
                    <div>
                      <div className="text-slate-400 text-[11px] flex items-center gap-1">
                        <HardDrive className="w-3 h-3 text-cyan-400" /> RAM Usage / Req
                      </div>
                      <div className="font-mono text-slate-200 mt-0.5">
                        {pod.mem_usage_mb} / {pod.mem_req_mb} MB
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-xs pt-1">
                    <span className="text-slate-400">Net Traffic: {pod.net_rx_kb + pod.net_tx_kb} KB</span>
                    <span className="font-extrabold text-emerald-400">${pod.monthly_cost.toFixed(2)}/mo</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
