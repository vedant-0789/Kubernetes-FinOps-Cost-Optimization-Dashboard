import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { Check, Download, ShieldAlert, X } from 'lucide-react';
import { Badge, Button, Card, Empty, PageHeader, Query, ReasonModal, StatusBadge, cx, useToast } from '../components/ui';
import { api, download } from '../lib/api';
import { useAuth } from '../lib/auth';
import { dateTime, money } from '../lib/format';
import { useActions, useApiMutation } from '../lib/queries';

const STEPS = [
  { key: 'proposed', label: 'Proposed' },
  { key: 'dry_run', label: 'Dry-run' },
  { key: 'approved', label: 'Approval' },
  { key: 'applied', label: 'Apply' },
  { key: 'verified', label: 'Verify' },
];
const PROGRESS = { dry_run_pending: 1, pending_approval: 2, approved: 3, applied: 4, verified: 5, rolling_back: 4, rolled_back: 4 };
const FAILED_AT = { dry_run_failed: 1, rejected: 2, failed: 3 };

export function Timeline({ status }) {
  const done = PROGRESS[status] ?? FAILED_AT[status] ?? 0;
  const failedAt = FAILED_AT[status];
  return (
    <ol className="flex items-center gap-1" aria-label={`progress: ${status}`}>
      {STEPS.map((s, i) => {
        const state = failedAt === i ? 'failed' : i < done ? 'done' : i === done ? 'current' : 'todo';
        return (
          <li key={s.key} className="flex items-center gap-1">
            <span data-state={state} className={cx('rounded-full px-2 py-0.5 text-[10px] font-semibold',
              state === 'done' && 'bg-emerald-500/20 text-emerald-300', state === 'current' && 'bg-cyan-500/20 text-cyan-300',
              state === 'failed' && 'bg-rose-500/20 text-rose-300', state === 'todo' && 'bg-slate-800 text-slate-500')}>{s.label}</span>
            {i < STEPS.length - 1 && <span className="h-px w-3 bg-slate-700" />}
          </li>
        );
      })}
    </ol>
  );
}

function Diff({ diff }) {
  if (!diff || !Object.keys(diff).length) return <div className="text-xs text-slate-500">Dry-run: no effective change.</div>;
  return (
    <div className="space-y-1 rounded-lg bg-slate-950/60 p-3 font-mono text-[11px]">
      {diff.replicas && <div>replicas: <span className="text-rose-300">{diff.replicas.before}</span> → <span className="text-emerald-300">{diff.replicas.after}</span></div>}
      {Object.entries(diff.containers || {}).map(([name, c]) => (
        <div key={name}>
          <div className="text-slate-400">{name}</div>
          <div className="pl-3 text-rose-300">- {JSON.stringify(c.before)}</div>
          <div className="pl-3 text-emerald-300">+ {JSON.stringify(c.after)}</div>
        </div>
      ))}
    </div>
  );
}

function ActionCard({ a, clusterId, me, can }) {
  const toast = useToast();
  const [rejecting, setRejecting] = useState(false);
  const approve = useApiMutation(() => api(`/clusters/${clusterId}/actions/${a.id}/approve`, { method: 'POST' }), ['actions']);
  const reject = useApiMutation((reason) => api(`/clusters/${clusterId}/actions/${a.id}/reject`, { method: 'POST', body: { reason } }), ['actions']);
  const mine = a.requested_by === me?.subject;
  const v = a.verification;
  return (
    <div className={cx('rounded-xl border p-4', a.type === 'ROLLBACK' ? 'border-rose-500/30 bg-rose-500/5' : 'border-slate-800 bg-slate-900/50')}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            #{a.id} {a.type === 'ROLLBACK' && <ShieldAlert className="h-4 w-4 text-rose-400" />}{a.type.toLowerCase()} {a.namespace}/{a.workload_name}{a.container ? ` · ${a.container}` : ''}
            <StatusBadge status={a.status} />
          </div>
          <div className="mt-0.5 text-xs text-slate-400">
            by {a.requested_by}{a.approved_by && ` · approved by ${a.approved_by}`} · {dateTime(a.created_at)}
            {a.expected_monthly_savings > 0 && <> · saves <span className="text-emerald-400">{money(a.expected_monthly_savings)}</span>/mo</>}
          </div>
        </div>
        <div className="flex gap-1.5">
          <Button size="sm" variant="ghost" icon={Download} onClick={() => download(`/clusters/${clusterId}/actions/${a.id}/patch.yaml`, `kubefinops-action-${a.id}.yaml`).catch((e) => toast(e.message, 'error'))}>GitOps patch</Button>
          {a.status === 'pending_approval' && can('operator') && !mine && <>
            <Button size="sm" variant="danger" icon={X} onClick={() => setRejecting(true)}>Reject</Button>
            <Button size="sm" icon={Check} loading={approve.isPending} onClick={() => approve.mutate(undefined, { onSuccess: () => toast(`Action #${a.id} approved`), onError: (e) => toast(e.message, 'error') })}>Approve</Button>
          </>}
          {a.status === 'pending_approval' && mine && <Badge tone="amber">needs a second operator</Badge>}
        </div>
      </div>
      <div className="mt-3"><Timeline status={a.status} /></div>
      {a.reason && <p className="mt-2 text-xs text-slate-400">{a.reason}</p>}
      {a.status !== 'dry_run_pending' && a.dry_run_diff && <div className="mt-3"><Diff diff={a.dry_run_diff} /></div>}
      {a.error && <p className="mt-2 rounded-lg bg-rose-500/10 p-2 text-xs text-rose-200">{a.error}</p>}
      {v && (
        <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-slate-300">
          {['before', 'after'].map((k) => (
            <div key={k} className="rounded-lg bg-slate-950/60 p-2">
              <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500">{k} the change</div>
              OOM kills {v[k].oom_kills} · restarts {v[k].restarts} · throttled {(v[k].throttled_share * 100).toFixed(0)}%
            </div>
          ))}
          {v.regressions?.length > 0 && <div className="col-span-2 text-rose-300">Regressions: {v.regressions.join('; ')}</div>}
        </div>
      )}
      <ReasonModal open={rejecting} title={`Reject action #${a.id}`} cta="Reject" onClose={() => setRejecting(false)} loading={reject.isPending} error={reject.error}
        onSubmit={(reason) => reject.mutate(reason, { onSuccess: () => { setRejecting(false); toast('Action rejected'); } })} />
    </div>
  );
}

export default function ActionsPage() {
  const { clusterId } = useParams();
  const { me, can } = useAuth();
  const q = useActions(clusterId);
  return (
    <>
      <PageHeader title="Changes & approvals"
        subtitle="Every change: dry-run in the cluster → approval by a second operator → apply in the change window → watch period → verified or rolled back automatically." />
      <Query q={q}>{(rows) => {
        const pending = rows.filter((a) => a.status === 'pending_approval');
        const active = rows.filter((a) => ['dry_run_pending', 'approved', 'applied', 'rolling_back'].includes(a.status));
        const done = rows.filter((a) => !pending.includes(a) && !active.includes(a));
        const section = (title, items, empty) => (
          <Card title={`${title} (${items.length})`}>
            {items.length ? <div className="space-y-3">{items.map((a) => <ActionCard key={a.id} a={a} clusterId={clusterId} me={me} can={can} />)}</div> : <Empty>{empty}</Empty>}
          </Card>
        );
        return (
          <>
            {section('Waiting for approval', pending, 'Nothing waiting for approval.')}
            {section('In progress', active, 'Nothing in progress.')}
            {section('History', done, 'No finished changes yet.')}
          </>
        );
      }}</Query>
    </>
  );
}
