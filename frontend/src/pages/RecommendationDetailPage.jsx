import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Rocket, XCircle } from 'lucide-react';
import { Badge, Button, Card, Kpi, PageHeader, Query, ReasonModal, RiskBadge, StatusBadge, Table, useToast } from '../components/ui';
import { UsageChart } from '../components/charts';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { bytes, cores, pct } from '../lib/format';
import { useApiMutation, useCompare, useRecommendation } from '../lib/queries';
import { Change, Savings } from './RecommendationsPage';

const STRATEGY_LABEL = { slo_aware: 'SLO-aware (KubeFinOps)', vpa: 'VPA-style', p95_buffer: 'p95 + 20 %' };

export default function RecommendationDetailPage() {
  const { clusterId, recId } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { can } = useAuth();
  const q = useRecommendation(clusterId, recId);
  const cmp = useCompare(clusterId, recId);
  const [dismissing, setDismissing] = useState(false);
  const propose = useApiMutation(() => api(`/clusters/${clusterId}/actions`, { method: 'POST', body: { recommendation_id: Number(recId) } }), ['actions', 'recs']);
  const dismiss = useApiMutation((reason) => api(`/clusters/${clusterId}/recommendations/${recId}/dismiss`, { method: 'POST', body: { reason } }), ['recs', 'rec', 'savings']);

  return (
    <Query q={q}>{(r) => (
      <>
        <Link to=".." relative="path" className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200"><ArrowLeft className="h-3 w-3" />All recommendations</Link>
        <PageHeader title={`${r.namespace}/${r.workload_name}`} subtitle={`${r.workload_kind} · container ${r.container} · ${+r.replicas.toFixed(1)} replicas · strategy ${r.strategy}`}
          actions={r.status === 'open' && can('operator') && <>
            <Button variant="secondary" icon={XCircle} onClick={() => setDismissing(true)}>Dismiss</Button>
            <Button icon={Rocket} loading={propose.isPending} onClick={() => propose.mutate(undefined, {
              onSuccess: () => { toast('Change proposed: the agent will dry-run it, then a second operator approves.'); nav('../../actions', { relative: 'path' }); },
              onError: (e) => toast(e.message, 'error'),
            })}>Propose this change</Button>
          </>} />
        <div className="flex flex-wrap gap-2"><StatusBadge status={r.status} /><RiskBadge risk={r.risk} /><Badge tone="slate">confidence {r.confidence_label} ({pct(r.confidence)})</Badge></div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Kpi label="CPU request" value={<Change from={r.current_cpu_request} to={r.recommended_cpu_request} fmt={cores} />} hint={r.recommended_cpu_limit ? `limit → ${cores(r.recommended_cpu_limit)}` : 'no CPU limit'} />
          <Kpi label="Memory request" value={<Change from={r.current_mem_request} to={r.recommended_mem_request} fmt={bytes} />} hint={r.recommended_mem_limit ? `limit → ${bytes(r.recommended_mem_limit)}` : 'no memory limit'} tone="cyan" />
          <Kpi label="Per month" value={<Savings value={r.monthly_savings} />} hint={r.monthly_savings >= 0 ? 'saving' : 'extra cost to fix reliability'} tone="violet" />
          <Kpi label="History used" value={`${r.evidence.history_hours ?? '—'} h`} hint={`${pct(r.evidence.completeness ?? 0)} complete`} tone="slate" />
        </div>
        <Card title="Why">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-300">{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>
          <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
            {r.evidence.cpu_censored && <Badge tone="rose">CPU throttled at limit: demand under-observed</Badge>}
            {r.evidence.leak_suspected && <Badge tone="rose">memory leak suspected</Badge>}
            {r.evidence.oom_kills > 0 && <Badge tone="rose">{r.evidence.oom_kills} OOM kills</Badge>}
            {'cpu_headroom' in r.evidence && <Badge tone="slate">CPU headroom {pct(r.evidence.cpu_headroom)}</Badge>}
            {'mem_headroom' in r.evidence && <Badge tone="slate">memory headroom {pct(r.evidence.mem_headroom)}</Badge>}
          </div>
        </Card>
        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="CPU per pod, hourly (peak & median) vs request">
            <UsageChart usage={r.usage} peakKey="cpu_max" medianKey="cpu_p50" current={r.current_cpu_request} recommended={r.recommended_cpu_request}
              limit={r.current_cpu_limit} format={cores} />
          </Card>
          <Card title="Memory per pod, hourly (peak & median) vs request">
            <UsageChart usage={r.usage} peakKey="mem_max" medianKey="mem_p50" current={r.current_mem_request} recommended={r.recommended_mem_request}
              limit={r.current_mem_limit} format={bytes} oomKey="oom_kills" />
          </Card>
        </div>
        <Card title="Strategies on the same history" padded={false}>
          <Query q={cmp}>{(c) => (
            <Table rows={Object.entries(c.strategies).map(([name, s]) => ({ name, ...s }))} rowKey={(s) => s.name} columns={[
              { key: 'name', label: 'Strategy', render: (s) => <span className={s.name === 'slo_aware' ? 'font-semibold text-emerald-300' : ''}>{STRATEGY_LABEL[s.name] || s.name}</span> },
              { key: 'cpu', label: 'CPU request', align: 'right', render: (s) => cores(s.cpu_request) },
              { key: 'mem', label: 'Memory request', align: 'right', render: (s) => bytes(s.mem_request) },
              { key: 'ce', label: 'Time CPU peaks exceed it', align: 'right', render: (s) => pct(s.cpu_peak_exceedance, 1) },
              { key: 'me', label: 'Time memory peaks exceed it', align: 'right', render: (s) => pct(s.mem_peak_exceedance, 1) },
            ]} />
          )}</Query>
          <p className="px-5 pb-4 pt-2 text-[11px] text-slate-500">
            SLO-aware changes are capped at −50 % per step and re-evaluated after verification, so a large cut is reached in safe steps.
            Exceedance = share of 5-minute windows whose observed peak is above the request.
          </p>
        </Card>
        <ReasonModal open={dismissing} title="Dismiss recommendation" cta="Dismiss" onClose={() => setDismissing(false)}
          loading={dismiss.isPending} error={dismiss.error}
          onSubmit={(reason) => dismiss.mutate(reason, { onSuccess: () => { setDismissing(false); toast('Recommendation dismissed'); } })} />
      </>
    )}</Query>
  );
}
