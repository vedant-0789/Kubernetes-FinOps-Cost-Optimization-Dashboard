import React, { useState, useEffect } from 'react';
import { Settings, Save, Cpu, HardDrive, ShieldCheck, Database, Sliders } from 'lucide-react';

export default function SettingsPage({ settingsData, onSaveSettings }) {
  const [formData, setFormData] = useState({
    cpu_hourly_rate: 0.048,
    ram_hourly_rate: 0.006,
    idle_cpu_threshold_pct: 5.0,
    evaluation_window_hours: 24,
    auto_remediation_enabled: false,
    mock_mode: true
  });

  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (settingsData) {
      setFormData(settingsData);
    }
  }, [settingsData]);

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : parseFloat(value) || value
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      await onSaveSettings(formData);
    } catch (err) {
      console.error(err);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
          <Settings className="w-6 h-6 text-slate-400" />
          FinOps Configuration & Cloud Pricing
        </h2>
        <p className="text-xs text-slate-400 mt-1">Configure hourly cloud provider rates, idle detection rules, and auto-remediation policies.</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Cloud Hourly Pricing Rules */}
        <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-4">
          <h3 className="text-base font-bold text-white tracking-tight flex items-center gap-2">
            <DollarSignIcon /> Cloud Provider Hourly Rates (OpenCost Allocation)
          </h3>
          <p className="text-xs text-slate-400">Configure base unit prices per resource unit to match your AWS, GCP, or Azure bill.</p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <Cpu className="w-4 h-4 text-emerald-400" /> CPU Hourly Rate ($ / vCPU-hour)
              </label>
              <input
                type="number"
                step="0.001"
                name="cpu_hourly_rate"
                value={formData.cpu_hourly_rate}
                onChange={handleChange}
                className="w-full px-3.5 py-2 rounded-xl bg-slate-900 border border-slate-700 text-xs font-mono text-white focus:outline-none focus:border-emerald-500/50"
              />
              <span className="text-[11px] text-slate-500">Default: $0.048/vCPU-hr (~AWS m5.large equivalent)</span>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <HardDrive className="w-4 h-4 text-cyan-400" /> RAM Hourly Rate ($ / GB-hour)
              </label>
              <input
                type="number"
                step="0.001"
                name="ram_hourly_rate"
                value={formData.ram_hourly_rate}
                onChange={handleChange}
                className="w-full px-3.5 py-2 rounded-xl bg-slate-900 border border-slate-700 text-xs font-mono text-white focus:outline-none focus:border-emerald-500/50"
              />
              <span className="text-[11px] text-slate-500">Default: $0.006/GB-hr</span>
            </div>
          </div>
        </div>

        {/* Zombie Threshold Rules */}
        <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-4">
          <h3 className="text-base font-bold text-white tracking-tight flex items-center gap-2">
            <Sliders className="w-4 h-4 text-amber-400" /> Idle / Zombie Workload Rules
          </h3>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300">Idle CPU Threshold (%)</label>
              <input
                type="number"
                step="0.5"
                name="idle_cpu_threshold_pct"
                value={formData.idle_cpu_threshold_pct}
                onChange={handleChange}
                className="w-full px-3.5 py-2 rounded-xl bg-slate-900 border border-slate-700 text-xs font-mono text-white focus:outline-none focus:border-emerald-500/50"
              />
              <span className="text-[11px] text-slate-500">Workloads using less than this % of CPU request are flagged.</span>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300">Evaluation Window (Hours)</label>
              <input
                type="number"
                name="evaluation_window_hours"
                value={formData.evaluation_window_hours}
                onChange={handleChange}
                className="w-full px-3.5 py-2 rounded-xl bg-slate-900 border border-slate-700 text-xs font-mono text-white focus:outline-none focus:border-emerald-500/50"
              />
              <span className="text-[11px] text-slate-500">Sustained duration before flagging as zombie workload.</span>
            </div>
          </div>
        </div>

        {/* System Toggles */}
        <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-4">
          <h3 className="text-base font-bold text-white tracking-tight flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400" /> Operational & Safety Controls
          </h3>

          <div className="space-y-4">
            <div className="flex items-center justify-between p-3.5 rounded-xl bg-slate-900/80 border border-slate-800">
              <div>
                <h4 className="font-semibold text-xs text-white">Simulated Mock Data Mode</h4>
                <p className="text-[11px] text-slate-400 mt-0.5">Toggle between synthetic demo cluster metrics and live Kubernetes API.</p>
              </div>
              <input
                type="checkbox"
                name="mock_mode"
                checked={formData.mock_mode}
                onChange={handleChange}
                className="w-5 h-5 accent-emerald-500 rounded cursor-pointer"
              />
            </div>

            <div className="flex items-center justify-between p-3.5 rounded-xl bg-slate-900/80 border border-slate-800">
              <div>
                <h4 className="font-semibold text-xs text-white">Auto-Apply Low-Risk Recommendations</h4>
                <p className="text-[11px] text-slate-400 mt-0.5">Automatically apply right-sizing patches without requiring manual user approval.</p>
              </div>
              <input
                type="checkbox"
                name="auto_remediation_enabled"
                checked={formData.auto_remediation_enabled}
                onChange={handleChange}
                className="w-5 h-5 accent-emerald-500 rounded cursor-pointer"
              />
            </div>
          </div>
        </div>

        <button
          type="submit"
          disabled={isSaving}
          className="px-6 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-xs font-bold text-white shadow-lg shadow-emerald-600/30 transition-all flex items-center gap-2 disabled:opacity-50"
        >
          <Save className="w-4 h-4" />
          <span>{isSaving ? 'Updating Settings...' : 'Save Settings & Recalculate Costs'}</span>
        </button>
      </form>
    </div>
  );
}

function DollarSignIcon() {
  return <span className="text-emerald-400 font-bold">$</span>;
}
