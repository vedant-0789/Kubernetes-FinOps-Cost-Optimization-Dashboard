import React, { useState } from 'react';
import StatCard from '../components/StatCard';
import EfficiencyBadge from '../components/EfficiencyBadge';
import { 
  DollarSign, 
  TrendingDown, 
  CheckCircle, 
  Ghost, 
  Sliders, 
  ArrowRight,
  TrendingUp,
  PieChart as PieIcon
} from 'lucide-react';
import { 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar
} from 'recharts';

const COLORS = ['#10B981', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#06B6D4', '#EC4899', '#64748B'];

export default function OverviewPage({ overviewData, trendData, namespacesData, onNavigate }) {
  const [trendRange, setTrendRange] = useState('30d');

  if (!overviewData) return <div className="p-8 text-center text-slate-400">Loading cluster telemetry...</div>;

  const displayTrend = trendRange === '7d' ? trendData.slice(-7) : trendData;

  const pieData = (namespacesData || []).map(ns => ({
    name: ns.name,
    value: ns.monthly_cost
  }));

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-white">Cluster FinOps Overview</h2>
        <p className="text-xs text-slate-400 mt-1">Real-time resource allocation, cost attribution, and automated waste reduction opportunity.</p>
      </div>

      {/* Headline Stat Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard
          title="Total Monthly Cost"
          value={`$${overviewData.total_monthly_cost.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
          subtext="Run rate based on hourly requests"
          icon={DollarSign}
          color="emerald"
        />
        <StatCard
          title="Potential Monthly Savings"
          value={`$${overviewData.total_potential_savings.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
          subtext="Unused & over-provisioned waste"
          icon={TrendingDown}
          color="amber"
        />
        <StatCard
          title="Realized Monthly Savings"
          value={`$${overviewData.realized_monthly_savings.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
          subtext="Eliminated via remediations"
          icon={CheckCircle}
          color="cyan"
        />
        <StatCard
          title="Zombie Workloads"
          value={overviewData.zombie_count}
          subtext="Flagged <5% usage pods"
          icon={Ghost}
          color="rose"
        />
        <StatCard
          title="Overall Efficiency"
          value={`${overviewData.overall_efficiency_pct}%`}
          subtext="Resource usage / request ratio"
          icon={TrendingUp}
          color="violet"
        />
      </div>

      {/* Main Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Cost Trend Chart */}
        <div className="lg:col-span-2 glass-panel p-5 rounded-2xl border border-slate-800 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-base font-bold text-white tracking-tight">Cluster Cost Trend</h3>
              <p className="text-xs text-slate-400">Actual vs Potential Optimized Spend ($/mo rate)</p>
            </div>
            <div className="flex items-center gap-1 bg-slate-900 p-1 rounded-lg border border-slate-800 text-xs">
              <button
                onClick={() => setTrendRange('7d')}
                className={`px-2.5 py-1 rounded-md font-medium transition-all ${trendRange === '7d' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'text-slate-400 hover:text-slate-200'}`}
              >
                7 Days
              </button>
              <button
                onClick={() => setTrendRange('30d')}
                className={`px-2.5 py-1 rounded-md font-medium transition-all ${trendRange === '30d' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'text-slate-400 hover:text-slate-200'}`}
              >
                30 Days
              </button>
            </div>
          </div>

          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={displayTrend} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="actualCost" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10B981" stopOpacity={0.4}/>
                    <stop offset="95%" stopColor="#10B981" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="optCost" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#06B6D4" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#06B6D4" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" />
                <XAxis dataKey="date" stroke="#64748B" fontSize={11} tickLine={false} />
                <YAxis stroke="#64748B" fontSize={11} tickLine={false} tickFormatter={(v) => `$${v}`} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0F172A', borderColor: '#334155', borderRadius: '12px', fontSize: '12px' }}
                  formatter={(val) => [`$${val}`, 'Monthly Rate']}
                />
                <Area type="monotone" dataKey="actual_cost" name="Current Run-Rate" stroke="#10B981" strokeWidth={2} fillOpacity={1} fill="url(#actualCost)" />
                <Area type="monotone" dataKey="potential_optimized_cost" name="Optimized Target" stroke="#06B6D4" strokeWidth={2} strokeDasharray="4 4" fillOpacity={1} fill="url(#optCost)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Namespace Cost Breakdown Pie */}
        <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-bold text-white tracking-tight flex items-center gap-2">
              <PieIcon className="w-4 h-4 text-emerald-400" />
              Cost by Namespace
            </h3>
            <span className="text-xs text-slate-400">8 Namespaces</span>
          </div>

          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={75}
                  paddingAngle={4}
                  dataKey="value"
                >
                  {pieData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} stroke="#090D16" />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ backgroundColor: '#0F172A', borderColor: '#334155', borderRadius: '12px', fontSize: '12px' }}
                  formatter={(v) => [`$${v}/mo`, 'Cost']}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div className="space-y-1.5 max-h-28 overflow-y-auto pr-1">
            {pieData.map((item, idx) => (
              <div key={item.name} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: COLORS[idx % COLORS.length] }}></span>
                  <span className="text-slate-300 font-medium">{item.name}</span>
                </div>
                <span className="text-slate-400">${item.value.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Quick Action Cards Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Zombie Workloads Callout */}
        <div className="glass-panel p-5 rounded-2xl border border-slate-800 flex items-center justify-between bg-gradient-to-r from-rose-950/30 to-slate-900/60">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Ghost className="w-5 h-5 text-rose-400" />
              <h4 className="font-bold text-white text-base">Zombie Pods Detected</h4>
              <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">
                {overviewData.zombie_count} Workloads
              </span>
            </div>
            <p className="text-xs text-slate-300">Sustained zero/idle usage consuming cloud dollars continuously.</p>
          </div>
          <button
            onClick={() => onNavigate('zombies')}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-xs font-semibold text-white shadow-lg shadow-rose-600/30 transition-all shrink-0"
          >
            <span>Inspect & Clean</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>

        {/* Right-Sizing Callout */}
        <div className="glass-panel p-5 rounded-2xl border border-slate-800 flex items-center justify-between bg-gradient-to-r from-amber-950/30 to-slate-900/60">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Sliders className="w-5 h-5 text-amber-400" />
              <h4 className="font-bold text-white text-base">Right-Sizing Opportunities</h4>
              <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">
                {overviewData.active_recommendations_count} Pending
              </span>
            </div>
            <p className="text-xs text-slate-300">Over-provisioned requests identified via p95 usage analysis + 20% buffer.</p>
          </div>
          <button
            onClick={() => onNavigate('rightsizing')}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-500 text-xs font-semibold text-white shadow-lg shadow-amber-600/30 transition-all shrink-0"
          >
            <span>Apply Right-Sizing</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
