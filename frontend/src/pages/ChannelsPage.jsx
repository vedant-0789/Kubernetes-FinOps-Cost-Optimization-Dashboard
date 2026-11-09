import { useState } from 'react';
import { Plus, Send, Trash2 } from 'lucide-react';
import { Badge, Button, Card, ErrorBox, Field, Input, Modal, PageHeader, Query, Select, Table, useToast } from '../components/ui';
import { api } from '../lib/api';
import { useApiMutation, useChannels } from '../lib/queries';

const EVENTS = ['budget', 'anomaly', 'remediation'];
const EMPTY = { name: '', type: 'slack', url: '', to: '', events: [...EVENTS] };

export default function ChannelsPage() {
  const toast = useToast();
  const q = useChannels();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState(EMPTY);
  const create = useApiMutation((body) => api('/notification-channels', { method: 'POST', body }), ['channels']);
  const remove = useApiMutation((id) => api(`/notification-channels/${id}`, { method: 'DELETE' }), ['channels']);
  const test = useApiMutation((id) => api(`/notification-channels/${id}/test`, { method: 'POST' }));

  const submit = () => {
    const body = { name: f.name.trim(), type: f.type, events: f.events,
      ...(f.type === 'email' ? { to: f.to.split(',').map((s) => s.trim()).filter(Boolean) } : { url: f.url.trim() }) };
    create.mutate(body, { onSuccess: () => { toast(`Channel "${body.name}" added`); setOpen(false); setF(EMPTY); } });
  };

  return (
    <>
      <PageHeader title="Notifications" subtitle="Where budget alerts, cost anomalies and remediation events (approvals, failures, rollbacks) are sent."
        actions={<Button icon={Plus} onClick={() => setOpen(true)}>Add channel</Button>} />
      <Card padded={false}>
        <Query q={q}>{(rows) => (
          <Table rows={rows} rowKey={(c) => c.id} empty="No channels yet: alerts are only visible in the UI." columns={[
            { key: 'n', label: 'Name', render: (c) => c.name },
            { key: 't', label: 'Type', render: (c) => <Badge tone="cyan">{c.type}</Badge> },
            { key: 'd', label: 'Destination', render: (c) => <span className="font-mono text-xs text-slate-400">{c.config.url || (c.config.to || []).join(', ')}</span> },
            { key: 'e', label: 'Events', render: (c) => <div className="flex flex-wrap gap-1">{c.events.map((e) => <Badge key={e}>{e}</Badge>)}</div> },
            { key: 'a', label: '', render: (c) => (
              <div className="flex justify-end gap-1.5">
                <Button size="sm" variant="secondary" icon={Send} loading={test.isPending && test.variables === c.id}
                  onClick={() => test.mutate(c.id, { onSuccess: (r) => toast(r.status === 'sent' ? 'Test message sent' : `Failed: ${r.error}`, r.status === 'sent' ? 'success' : 'error') })}>Test</Button>
                <Button size="sm" variant="ghost" icon={Trash2} aria-label={`Delete ${c.name}`} onClick={() => window.confirm(`Delete channel "${c.name}"?`) && remove.mutate(c.id)} />
              </div>) },
          ]} />
        )}</Query>
      </Card>
      <Modal open={open} title="Add notification channel" onClose={() => setOpen(false)}
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button loading={create.isPending} onClick={submit}>Add</Button></>}>
        <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="#finops-alerts" /></Field>
        <Field label="Type"><Select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}
          options={[{ value: 'slack', label: 'Slack incoming webhook' }, { value: 'webhook', label: 'Generic webhook (JSON)' }, { value: 'email', label: 'Email (SMTP)' }]} /></Field>
        {f.type === 'email'
          ? <Field label="Recipients" hint="Comma-separated"><Input value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} placeholder="finops@example.com" /></Field>
          : <Field label="URL" hint="Stored server-side; shown masked afterwards."><Input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://hooks.slack.com/services/…" /></Field>}
        <Field label="Events">
          <div className="flex gap-3">
            {EVENTS.map((ev) => (
              <label key={ev} className="flex items-center gap-1.5 text-sm text-slate-300">
                <input type="checkbox" checked={f.events.includes(ev)}
                  onChange={(e) => setF({ ...f, events: e.target.checked ? [...f.events, ev] : f.events.filter((x) => x !== ev) })} />{ev}
              </label>
            ))}
          </div>
        </Field>
        <ErrorBox error={create.error} />
      </Modal>
    </>
  );
}
