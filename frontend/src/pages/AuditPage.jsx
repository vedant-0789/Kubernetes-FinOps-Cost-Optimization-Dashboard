import { useState } from 'react';
import { ShieldCheck, ShieldX } from 'lucide-react';
import { Button, Card, Input, PageHeader, Query, Table, useToast } from '../components/ui';
import { api } from '../lib/api';
import { dateTime } from '../lib/format';
import { useApiMutation, useAudit } from '../lib/queries';

export default function AuditPage() {
  const toast = useToast();
  const [action, setAction] = useState('');
  const q = useAudit({ action: action || undefined, limit: 300 });
  const [result, setResult] = useState(null);
  const verify = useApiMutation(() => api('/audit/verify'));

  return (
    <>
      <PageHeader title="Audit log" subtitle="Append-only and hash-chained: each event includes the SHA-256 of the previous one."
        actions={<Button variant="secondary" icon={ShieldCheck} loading={verify.isPending}
          onClick={() => verify.mutate(undefined, { onSuccess: setResult, onError: (e) => toast(e.message, 'error') })}>Verify integrity</Button>} />
      {result && (
        <div role="status" className={`flex items-center gap-2 rounded-xl border p-3 text-sm ${result.valid ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200' : 'border-rose-500/30 bg-rose-500/10 text-rose-200'}`}>
          {result.valid ? <ShieldCheck className="h-4 w-4" /> : <ShieldX className="h-4 w-4" />}
          {result.valid ? `Chain intact: ${result.events_checked} events verified.` : `Chain broken at event #${result.first_invalid_id} (after ${result.events_checked} valid events).`}
        </div>
      )}
      <div className="w-64"><Input aria-label="Filter by action" value={action} onChange={(e) => setAction(e.target.value)} placeholder="filter, e.g. remediation" /></div>
      <Card padded={false}>
        <Query q={q}>{(rows) => (
          <Table rows={rows} rowKey={(e) => e.id} columns={[
            { key: 't', label: 'When', render: (e) => <span className="whitespace-nowrap text-xs text-slate-400">{dateTime(e.ts)}</span> },
            { key: 'u', label: 'Actor', render: (e) => e.actor },
            { key: 'a', label: 'Action', render: (e) => <span className="font-mono text-xs">{e.action}</span> },
            { key: 'g', label: 'Target', render: (e) => <span className="text-xs">{e.target || '—'}</span> },
            { key: 'h', label: 'Hash', render: (e) => <span className="font-mono text-[10px] text-slate-500" title={e.hash}>{e.hash.slice(0, 12)}…</span> },
          ]} />
        )}</Query>
      </Card>
    </>
  );
}
