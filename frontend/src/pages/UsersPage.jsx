import { useState } from 'react';
import { Plus } from 'lucide-react';
import { Badge, Button, Card, ErrorBox, Field, Input, Modal, PageHeader, Query, Select, Table, useToast } from '../components/ui';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { relTime } from '../lib/format';
import { useApiMutation, useUsers } from '../lib/queries';

const ROLES = [{ value: 'viewer', label: 'Viewer: read only' }, { value: 'operator', label: 'Operator: propose, approve, dismiss' }, { value: 'admin', label: 'Admin: users, clusters, channels' }];

export default function UsersPage() {
  const { me } = useAuth();
  const toast = useToast();
  const q = useUsers();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ email: '', name: '', password: '', role: 'viewer' });
  const create = useApiMutation((body) => api('/users', { method: 'POST', body }), ['users']);
  const update = useApiMutation(({ id, ...body }) => api(`/users/${id}`, { method: 'PATCH', body }), ['users']);
  const change = (u, body) => update.mutate({ id: u.id, ...body }, { onSuccess: () => toast(`${u.email} updated`), onError: (e) => toast(e.message, 'error') });

  return (
    <>
      <PageHeader title="Users" subtitle="Roles take effect on the next request; changes are recorded in the audit log."
        actions={<Button icon={Plus} onClick={() => setOpen(true)}>Add user</Button>} />
      <Card padded={false}>
        <Query q={q}>{(rows) => (
          <Table rows={rows} rowKey={(u) => u.id} columns={[
            { key: 'e', label: 'User', render: (u) => <div><div>{u.email}</div><div className="text-xs text-slate-500">{u.name}</div></div> },
            { key: 'r', label: 'Role', render: (u) => (u.id === me?.user_id ? <Badge tone="violet">{u.role} (you)</Badge> : (
              <select aria-label={`Role of ${u.email}`} value={u.role} onChange={(e) => change(u, { role: e.target.value })}
                className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs">
                {['viewer', 'operator', 'admin'].map((r) => <option key={r}>{r}</option>)}
              </select>)) },
            { key: 's', label: 'Status', render: (u) => <Badge tone={u.is_active ? 'emerald' : 'slate'}>{u.is_active ? 'active' : 'disabled'}</Badge> },
            { key: 'l', label: 'Last sign-in', render: (u) => <span className="text-xs text-slate-400">{relTime(u.last_login_at)}</span> },
            { key: 'a', label: '', render: (u) => u.id !== me?.user_id && (
              <Button size="sm" variant="ghost" onClick={() => change(u, { is_active: !u.is_active })}>{u.is_active ? 'Disable' : 'Enable'}</Button>) },
          ]} />
        )}</Query>
      </Card>
      <Modal open={open} title="Add user" onClose={() => setOpen(false)}
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
          <Button loading={create.isPending} onClick={() => create.mutate(f, { onSuccess: () => { toast(`${f.email} added`); setOpen(false); setF({ email: '', name: '', password: '', role: 'viewer' }); } })}>Add</Button></>}>
        <Field label="Email"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Initial password" hint="At least 12 characters."><Input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        <Field label="Role"><Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} options={ROLES} /></Field>
        <ErrorBox error={create.error} />
      </Modal>
    </>
  );
}
