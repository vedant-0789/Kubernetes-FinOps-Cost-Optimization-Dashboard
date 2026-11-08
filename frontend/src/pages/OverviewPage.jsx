import { Link, useParams } from 'react-router-dom';
import { AlertTriangle, Coins, Cpu, Gauge, PiggyBank, Server } from 'lucide-react';
import { Badge, Card, Kpi, PageHeader, Progress, Query, RiskBadge, StatusBadge } from '../components/ui';
import { StackedCost } from '../components/charts';
import { money, pct, relTime, shortDate } from '../lib/format';
import { useAnomalies, useBudgetsStatus, useRecommendations, useSavings, useSummary, useTimeseries } from '../lib/queries';

const WASTE_LABELS = {
  IDLE_WORKLOAD: 'Idle workloads', ORPHANED_VOLUME: 'Orphaned volumes', UNUSED_LB: 'Unused load balancers',
  UNDERUTILIZED_NODE: 'Removable nodes',
};

export default function OverviewPage() {
  const { clusterId } = useParams();
  const summary = useSummary(clusterId);
  const series = useTimeseries(clusterId, { window: '30d', step: '1d', top: 6 });
  const savings = useSavings(clusterId);
  const recs = useRecommendations(clusterId, { status: 'open' });
  const anomalies = useAnomalies(clusterId, { status: 'open' });
  const budgets = useBudgetsStatus(clusterId);

  return (
    <>
      <Query q={summary}>{(s) => (
        <>
          <PageHeader title={s.cluster.name}
            subtitle={`${s.cluster.provider.toUpperCase()} ${s.cluster.region || ''} · agent ${s.cluster.agent_version || 'n/a'} · last seen ${relTime(s.cluster.last_seen_at)}`} />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <Kpi label="Monthly run rate" value={money(s.monthly_run_rate, { whole: true })} hint={`${money(s.hourly_run_rate)}/h for running nodes`} icon={Coins} />
            <Kpi label="Last 24 h" value={money(s.cost_last_24h)} hint="allocated + idle" icon={Gauge} tone="cyan" />
            <Kpi label="Idle capacity" value={pct(s.idle_pct)} hint={`${money(s.idle_cost_last_24h)} in 24 h`} icon={AlertTriangle} tone={s.idle_pct > 0.3 ? 'amber' : 'emerald'} />
            <Kpi label="Efficiency" value={pct(s.efficiency)} hint="cost of used vs. paid resources" icon={Cpu} tone="violet" />
            <Kpi label="Nodes" value={s.nodes} hint={`${s.spot_nodes} spot · ${s.workloads} workloads`} icon={Server} tone="slate" />
          </div>
        </>
      )}</Query>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Daily cost, last 30 complete days" className="lg:col-span-2">
          <Query q={series}>{(pts) => <StackedCost points={pts} />}</Query>
        </Card>
        <Card title="Potential savings" actions={<Link to="../recommendations" className="text-xs text-emerald-400 hover:underline">Details</Link>}>
          <Query q={savings}>{(s) => (
            <div className="space-y-4">
              <div>
                <div className="text-3xl font-bold text-emerald-400">{money(s.total_monthly_savings)}<span className="text-sm font-normal text-slate-400"> / month</span></div>
                <div className="text-xs text-slate-400">non-overlapping · strategy {s.strategy}</div>
              </div>
              <ul className="space-y-2 text-sm">
                <li className="flex justify-between"><span className="text-slate-300">Right-sizing ({s.rightsizing.count})</span><span className="tabular-nums">{money(s.rightsizing.monthly_savings)}</span></li>
                {Object.entries(s.waste).map(([k, v]) => (
                  <li key={k} className="flex justify-between">
                    <span className="text-slate-300">{WASTE_LABELS[k] || k} ({v.count}){s.overlapping.includes(k) && <Badge tone="slate" className="ml-1.5">overlaps</Badge>}</span>
                    <span className="tabular-nums">{money(v.monthly_savings)}</span>
                  </li>
                ))}
                {s.reliability_fixes.count > 0 && (
                  <li className="flex justify-between border-t border-slate-800 pt-2 text-amber-300">
                    <span>Reliability fixes ({s.reliability_fixes.count})</span><span className="tabular-nums">+{money(s.reliability_fixes.monthly_cost)}</span>
                  </li>
                )}
              </ul>
            </div>
          )}</Query>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Top right-sizing" className="lg:col-span-2" actions={<Link to="../recommendations" className="text-xs text-emerald-400 hover:underline">All</Link>}>
          <Query q={recs}>{(rows) => (
            <ul className="divide-y divide-slate-800">
              {[...rows].sort((a, b) => b.monthly_savings - a.monthly_savings).slice(0, 6).map((r) => (
                <li key={r.id}>
                  <Link to={`../recommendations/${r.id}`} className="flex items-center justify-between gap-3 py-2.5 hover:bg-slate-800/30">
                    <div className="min-w-0">
                      <div className="truncate text-sm text-slate-100">{r.namespace}/{r.workload_name} <span className="text-slate-500">· {r.container}</span></div>
                      <div className="text-xs text-slate-400">{r.reasons[0]}</div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <RiskBadge risk={r.risk} />
                      <span className={r.monthly_savings >= 0 ? 'tabular-nums text-emerald-400' : 'tabular-nums text-amber-300'}>
                        {r.monthly_savings >= 0 ? money(r.monthly_savings) : `+${money(-r.monthly_savings)}`}
                      </span>
                    </div>
                  </Link>
                </li>
              ))}
              {!rows.length && <li className="py-6 text-center text-sm text-slate-400">No open recommendations.</li>}
            </ul>
          )}</Query>
        </Card>
        <div className="space-y-6">
          <Card title="Cost anomalies" actions={<Link to="../forecast" className="text-xs text-emerald-400 hover:underline">Forecast</Link>}>
            <Query q={anomalies}>{(rows) => (rows.length ? (
              <ul className="space-y-2 text-sm">
                {rows.slice(0, 4).map((a) => (
                  <li key={a.id} className="flex justify-between gap-2">
                    <span className="truncate text-slate-300">{shortDate(a.day)} · {a.scope} <b>{a.name}</b></span>
                    <span className="tabular-nums text-rose-300">+{money(a.delta)}</span>
                  </li>
                ))}
              </ul>
            ) : <div className="text-sm text-slate-400">No open anomalies.</div>)}</Query>
          </Card>
          <Card title="Budgets" actions={<Link to="../budgets" className="text-xs text-emerald-400 hover:underline">Manage</Link>}>
            <Query q={budgets}>{(rows) => (rows.length ? (
              <ul className="space-y-3">
                {rows.map((b) => (
                  <li key={b.budget_id} className="space-y-1">
                    <div className="flex justify-between text-sm"><span className="text-slate-200">{b.name}</span><StatusBadge status={b.state} /></div>
                    <Progress value={b.pct_actual / 100} marker={b.pct_projected / 100} tone={b.state === 'ok' ? 'emerald' : b.state === 'at_risk' ? 'amber' : 'rose'} />
                    <div className="text-[11px] text-slate-400">{money(b.actual_to_date)} of {money(b.monthly_amount)} · projected {money(b.projected)}</div>
                  </li>
                ))}
              </ul>
            ) : <div className="flex items-center gap-2 text-sm text-slate-400"><PiggyBank className="h-4 w-4" />No budgets yet.</div>)}</Query>
          </Card>
        </div>
      </div>
    </>
  );
}
