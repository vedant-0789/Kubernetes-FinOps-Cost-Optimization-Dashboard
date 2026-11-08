import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Ghost, HardDrive, Network, PowerOff, Server, XCircle } from 'lucide-react';
import { Badge, Button, Card, Kpi, PageHeader, Query, ReasonModal, RiskBadge, Segmented, StatusBadge, Table, useToast } from '../components/ui';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { bytes, cores, money, relTime } from '../lib/format';
import { useApiMutation, useWaste } from '../lib/queries';

const KINDS = {
  IDLE_WORKLOAD: { label: 'Idle workload', icon: Ghost },
  ORPHANED_VOLUME: { label: 'Orphaned volume', icon: HardDrive },
  UNUSED_LB: { label: 'Unused load balancer', icon: Network },
  UNDERUTILIZED_NODE: { label: 'Removable node', icon: Server },
};

function evidence(f) {
  const e = f.evidence;
  switch (f.kind) {
    case 'IDLE_WORKLOAD': return `p95 CPU ${cores(e.cpu_p95_cores)} of ${cores(e.cpu_request_cores)} requested · ${Math.round(e.net_bytes_per_hour / 1024)} KiB/h network · ${e.observed_hours} h observed`;
    case 'ORPHANED_VOLUME': return `${e.capacity_gib} GiB ${e.storage_class || ''} · ${e.phase} · not mounted by any pod`;
    case 'UNUSED_LB': return `no ready backends · ${e.age_hours} h old`;
    case 'UNDERUTILIZED_NODE': return `${cores(e.cpu_requested)}/${e.vcpu} vCPU, ${bytes(e.mem_requested_gib * 2 ** 30)}/${e.memory_gib} GiB requested · pods fit on ${e.fits_on.length} other nodes`;
    default: return '';
  }
}

export default function WastePage() {
  const { clusterId } = useParams();
  const { can } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const [status, setStatus] = useState('open');
  const q = useWaste(clusterId, { status });
  const [dismissing, setDismissing] = useState(null);
  const propose = useApiMutation((id) => api(`/clusters/${clusterId}/actions`, { method: 'POST', body: { finding_id: id } }), ['actions', 'waste']);
  const dismiss = useApiMutation(({ id, reason }) => api(`/clusters/${clusterId}/waste/${id}/dismiss`, { method: 'POST', body: { reason } }), ['waste', 'savings']);

  return (
    <>
      <PageHeader title="Waste" subtitle="Resources that cost money and do nothing. Idle workloads are not right-sized as well, so savings never double count." />
      <Segmented value={status} onChange={setStatus} options={['open', 'dismissed', 'resolved', 'all'].map((s) => ({ value: s, label: s }))} />
      <Query q={q}>{(rows) => (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {Object.entries(KINDS).map(([k, { label, icon }]) => {
              const items = rows.filter((f) => f.kind === k);
              return <Kpi key={k} label={label} value={money(items.reduce((s, f) => s + f.monthly_savings, 0))} hint={`${items.length} found · per month`} icon={icon} tone={k === 'UNDERUTILIZED_NODE' ? 'slate' : 'amber'} />;
            })}
          </div>
          <Card padded={false}>
            <Table rows={rows} rowKey={(f) => f.id} empty="No waste found for this filter." columns={[
              { key: 'k', label: 'Type', render: (f) => { const K = KINDS[f.kind]; return <span className="inline-flex items-center gap-1.5">{K && <K.icon className="h-4 w-4 text-slate-400" />}{K?.label || f.kind}</span>; } },
              { key: 't', label: 'Resource', render: (f) => <div><div className="text-slate-100">{f.namespace ? `${f.namespace}/` : ''}{f.name}</div><div className="text-xs text-slate-500">{evidence(f)}</div></div> },
              { key: 's', label: 'Per month', align: 'right', render: (f) => <span className="tabular-nums text-emerald-400">{money(f.monthly_savings)}</span> },
              { key: 'r', label: 'Risk', render: (f) => <RiskBadge risk={f.risk} /> },
              { key: 'd', label: 'Since', render: (f) => <span className="text-xs text-slate-400">{relTime(f.first_detected)}</span> },
              { key: 'st', label: '', render: (f) => (f.status !== 'open' ? <StatusBadge status={f.status} /> : can('operator') && (
                <div className="flex justify-end gap-1.5">
                  {f.kind === 'IDLE_WORKLOAD' && <Button size="sm" icon={PowerOff} loading={propose.isPending && propose.variables === f.id}
                    onClick={() => propose.mutate(f.id, { onSuccess: () => { toast('Scale-to-zero proposed'); nav('../actions', { relative: 'path' }); }, onError: (e) => toast(e.message, 'error') })}>Scale to 0</Button>}
                  {f.kind === 'UNDERUTILIZED_NODE' && <Badge tone="slate">see action</Badge>}
                  <Button size="sm" variant="ghost" icon={XCircle} onClick={() => setDismissing(f)} aria-label="Dismiss" />
                </div>)) },
            ]} />
          </Card>
          <p className="text-xs text-slate-500">Orphaned volumes, load balancers and nodes need a manual step (snapshot & delete, delete the Service, drain the node); KubeFinOps never deletes data on its own.</p>
        </>
      )}</Query>
      <ReasonModal open={!!dismissing} title={`Dismiss: ${dismissing?.name}`} cta="Dismiss" onClose={() => setDismissing(null)}
        loading={dismiss.isPending} error={dismiss.error}
        onSubmit={(reason) => dismiss.mutate({ id: dismissing.id, reason }, { onSuccess: () => { setDismissing(null); toast('Finding dismissed'); } })} />
    </>
  );
}
