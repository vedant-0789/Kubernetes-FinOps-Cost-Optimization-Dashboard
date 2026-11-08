import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Copy, KeyRound, Plus, Power } from 'lucide-react';
import { Badge, Button, Card, ErrorBox, Field, Input, Modal, PageHeader, Query, Select, Table, useToast } from '../components/ui';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { parseUtc, relTime } from '../lib/format';
import { useApiMutation, useClusters } from '../lib/queries';

function health(c) {
  const seen = parseUtc(c.last_seen_at);
  if (!c.is_active) return <Badge tone="slate">disabled</Badge>;
  if (!seen) return <Badge tone="amber">waiting for agent</Badge>;
  const age = (Date.now() - seen) / 60000;
  return age < 15 ? <Badge tone="emerald">reporting</Badge> : <Badge tone="rose">silent {relTime(c.last_seen_at)}</Badge>;
}

function TokenModal({ token, onClose }) {
  const toast = useToast();
  if (!token) return null;
  const server = `${window.location.origin}`;
  const cmd = `helm install finops-agent deploy/helm/finops-agent -n finops --create-namespace \\\n  --set agent.serverUrl=${server} \\\n  --set agent.token=${token.agent_token}`;
  const copy = (text) => navigator.clipboard?.writeText(text).then(() => toast('Copied'));
  return (
    <Modal open title={`Agent token for ${token.name}`} onClose={onClose} wide footer={<Button onClick={onClose}>Done</Button>}>
      <p className="text-sm text-amber-200">This token is shown once. Only its hash is stored; rotate it if it is lost.</p>
      <div className="flex items-center gap-2 rounded-lg bg-slate-950 p-3 font-mono text-xs text-emerald-300">
        <span className="break-all">{token.agent_token}</span>
        <Button size="sm" variant="ghost" icon={Copy} aria-label="Copy token" onClick={() => copy(token.agent_token)} />
      </div>
      <Field label="Install the agent in that cluster">
        <pre className="overflow-x-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-200">{cmd}</pre>
      </Field>
      <Button size="sm" variant="secondary" icon={Copy} onClick={() => copy(cmd.replaceAll('\\\n  ', ''))}>Copy command</Button>
    </Modal>
  );
}

export default function ClustersPage() {
  const { can } = useAuth();
  const toast = useToast();
  const q = useClusters();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: '', provider: 'aws', region: '' });
  const [token, setToken] = useState(null);
  const create = useApiMutation((body) => api('/clusters', { method: 'POST', body }), ['clusters']);
  const rotate = useApiMutation((id) => api(`/clusters/${id}/rotate-token`, { method: 'POST' }), ['clusters']);
  const toggle = useApiMutation(({ id, enable }) => api(`/clusters/${id}/${enable ? 'enable' : 'disable'}`, { method: 'POST' }), ['clusters']);

  return (
    <>
      <PageHeader title="Clusters" subtitle="Each cluster runs a read-only agent that pushes inventory and usage every 5 minutes."
        actions={can('admin') && <Button icon={Plus} onClick={() => setOpen(true)}>Register cluster</Button>} />
      <Card padded={false}>
        <Query q={q}>{(rows) => (
          <Table rows={rows} rowKey={(c) => c.id} empty="No clusters registered yet." columns={[
            { key: 'n', label: 'Cluster', render: (c) => <Link to={`/c/${c.id}/overview`} className="font-medium text-emerald-300 hover:underline">{c.name}</Link> },
            { key: 'p', label: 'Provider', render: (c) => `${c.provider.toUpperCase()} ${c.region || ''}` },
            { key: 'h', label: 'Agent', render: health },
            { key: 'v', label: 'Version', render: (c) => <span className="text-xs text-slate-400">{c.agent_version || '—'}</span> },
            { key: 's', label: 'Last report', render: (c) => <span className="text-xs text-slate-400">{relTime(c.last_seen_at)}</span> },
            { key: 'a', label: '', render: (c) => can('admin') && (
              <div className="flex justify-end gap-1.5">
                <Button size="sm" variant="ghost" icon={KeyRound} onClick={() => window.confirm(`Rotate the token for ${c.name}? The current agent stops working until you update its Secret.`)
                  && rotate.mutate(c.id, { onSuccess: setToken, onError: (e) => toast(e.message, 'error') })}>Rotate token</Button>
                <Button size="sm" variant="ghost" icon={Power} onClick={() => toggle.mutate({ id: c.id, enable: !c.is_active }, { onError: (e) => toast(e.message, 'error') })}>
                  {c.is_active ? 'Disable' : 'Enable'}
                </Button>
              </div>) },
          ]} />
        )}</Query>
      </Card>
      <Modal open={open} title="Register a cluster" onClose={() => setOpen(false)}
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
          <Button loading={create.isPending} disabled={!form.name} onClick={() => create.mutate(
            { name: form.name.trim(), provider: form.provider, region: form.region.trim() || null },
            { onSuccess: (c) => { setOpen(false); setForm({ name: '', provider: 'aws', region: '' }); setToken(c); } },
          )}>Register</Button></>}>
        <Field label="Name" hint="lowercase letters, digits and dashes"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="prod-eu" /></Field>
        <Field label="Provider (for list prices)">
          <Select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}
            options={[{ value: 'aws', label: 'AWS' }, { value: 'gcp', label: 'Google Cloud' }, { value: 'azure', label: 'Azure' }, { value: 'onprem', label: 'On-premises' }]} />
        </Field>
        <Field label="Region"><Input value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} placeholder="eu-central-1" /></Field>
        <ErrorBox error={create.error} />
      </Modal>
      <TokenModal token={token} onClose={() => setToken(null)} />
    </>
  );
}
