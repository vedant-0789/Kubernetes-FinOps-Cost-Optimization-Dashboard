import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Badge, Card, PageHeader, Query, RiskBadge, Segmented, StatusBadge, Table } from '../components/ui';
import { bytes, cores, money } from '../lib/format';
import { useRecommendations } from '../lib/queries';

export function Change({ from, to, fmt }) {
  const down = to < from;
  return (
    <span className="inline-flex items-center gap-1 tabular-nums">
      <span className="text-slate-400">{fmt(from)}</span>
      <ArrowRight className={down ? 'h-3 w-3 text-emerald-400' : 'h-3 w-3 text-amber-300'} />
      <span className={down ? 'text-emerald-300' : 'text-amber-200'}>{fmt(to)}</span>
    </span>
  );
}

export function Savings({ value }) {
  return value >= 0
    ? <span className="tabular-nums text-emerald-400">{money(value)}</span>
    : <span className="tabular-nums text-amber-300" title="Costs more, but fixes OOM kills or throttling">+{money(-value)}</span>;
}

export default function RecommendationsPage() {
  const { clusterId } = useParams();
  const nav = useNavigate();
  const [status, setStatus] = useState('open');
  const [action, setAction] = useState('');
  const q = useRecommendations(clusterId, { status, action: action || undefined });

  return (
    <>
      <PageHeader title="Right-sizing" subtitle="SLO-aware: CPU covers peaks except ε = 1 % of the time; memory covers the peak working set, OOM kills and leaks." />
      <div className="flex flex-wrap gap-3">
        <Segmented value={status} onChange={setStatus} options={['open', 'applied', 'dismissed', 'resolved', 'all'].map((s) => ({ value: s, label: s }))} />
        <Segmented value={action} onChange={setAction} options={[{ value: '', label: 'All' }, { value: 'downsize', label: 'Downsize' }, { value: 'upsize', label: 'Reliability fixes' }]} />
      </div>
      <Card padded={false}>
        <Query q={q}>{(rows) => (
          <Table rows={rows} rowKey={(r) => r.id} onRowClick={(r) => nav(String(r.id))} empty="No recommendations for this filter." columns={[
            { key: 'w', label: 'Workload', render: (r) => <div><div className="text-slate-100">{r.namespace}/{r.workload_name}</div><div className="text-xs text-slate-500">{r.workload_kind} · {r.container} · ×{+r.replicas.toFixed(1)}</div></div> },
            { key: 'a', label: 'Action', render: (r) => <Badge tone={r.action === 'downsize' ? 'emerald' : 'amber'}>{r.action === 'downsize' ? 'downsize' : 'reliability fix'}</Badge> },
            { key: 'cpu', label: 'CPU request', render: (r) => <Change from={r.current_cpu_request} to={r.recommended_cpu_request} fmt={cores} /> },
            { key: 'mem', label: 'Memory request', render: (r) => <Change from={r.current_mem_request} to={r.recommended_mem_request} fmt={bytes} /> },
            { key: 's', label: 'Per month', align: 'right', render: (r) => <Savings value={r.monthly_savings} /> },
            { key: 'c', label: 'Confidence', render: (r) => <Badge tone={r.confidence_label === 'high' ? 'emerald' : r.confidence_label === 'medium' ? 'amber' : 'rose'}>{r.confidence_label}</Badge> },
            { key: 'r', label: 'Risk', render: (r) => <RiskBadge risk={r.risk} /> },
            ...(status === 'all' ? [{ key: 'st', label: 'Status', render: (r) => <StatusBadge status={r.status} /> }] : []),
          ]} />
        )}</Query>
      </Card>
    </>
  );
}
