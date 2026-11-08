import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { Plus, Trash2 } from 'lucide-react';
import { Button, Card, Empty, ErrorBox, Field, Input, Modal, PageHeader, Progress, Query, Select, StatusBadge, useToast } from '../components/ui';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { money } from '../lib/format';
import { useApiMutation, useBudgetsStatus } from '../lib/queries';

const EMPTY = { name: '', scope: 'cluster', scope_key: 'team', scope_value: '', monthly_amount: '', thresholds: '50, 80, 100' };

function BudgetForm({ open, onClose, clusterId }) {
  const toast = useToast();
  const [f, setF] = useState(EMPTY);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const create = useApiMutation((body) => api(`/clusters/${clusterId}/budgets`, { method: 'POST', body }), ['budgets', 'budget-defs']);
  const submit = () => {
    const body = {
      name: f.name.trim(), scope: f.scope, monthly_amount: Number(f.monthly_amount),
      thresholds: f.thresholds.split(',').map((t) => parseInt(t, 10)).filter((t) => !Number.isNaN(t)),
      ...(f.scope === 'namespace' ? { scope_value: f.scope_value.trim() } : {}),
      ...(f.scope === 'label' ? { scope_key: f.scope_key.trim(), scope_value: f.scope_value.trim() } : {}),
    };
    create.mutate(body, { onSuccess: () => { toast(`Budget "${body.name}" created`); setF(EMPTY); onClose(); } });
  };
  return (
    <Modal open={open} title="New monthly budget" onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={create.isPending} onClick={submit} disabled={!f.name || !f.monthly_amount}>Create</Button></>}>
      <Field label="Name"><Input value={f.name} onChange={set('name')} placeholder="payments team" /></Field>
      <Field label="Applies to">
        <Select value={f.scope} onChange={set('scope')} options={[{ value: 'cluster', label: 'Whole cluster' }, { value: 'namespace', label: 'A namespace' }, { value: 'label', label: 'A label (e.g. team)' }]} />
      </Field>
      {f.scope === 'label' && <Field label="Label key"><Input value={f.scope_key} onChange={set('scope_key')} /></Field>}
      {f.scope !== 'cluster' && <Field label={f.scope === 'namespace' ? 'Namespace' : 'Label value'}><Input value={f.scope_value} onChange={set('scope_value')} placeholder={f.scope === 'namespace' ? 'payments' : 'payments'} /></Field>}
      <Field label="Monthly amount (USD)"><Input type="number" min="1" step="1" value={f.monthly_amount} onChange={set('monthly_amount')} /></Field>
      <Field label="Alert at (% of budget)" hint="Each threshold alerts once per month; a forecast-to-exceed alert is added automatically.">
        <Input value={f.thresholds} onChange={set('thresholds')} />
      </Field>
      <ErrorBox error={create.error} />
    </Modal>
  );
}

export default function BudgetsPage() {
  const { clusterId } = useParams();
  const { can } = useAuth();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const q = useBudgetsStatus(clusterId);
  const remove = useApiMutation((id) => api(`/clusters/${clusterId}/budgets/${id}`, { method: 'DELETE' }), ['budgets', 'budget-defs']);

  return (
    <>
      <PageHeader title="Budgets" subtitle="Month-to-date spend against budget, with the forecast for the rest of the month (white marker)."
        actions={can('operator') && <Button icon={Plus} onClick={() => setOpen(true)}>New budget</Button>} />
      <Query q={q}>{(rows) => (rows.length ? (
        <div className="grid gap-4 md:grid-cols-2">
          {rows.map((b) => {
            const tone = b.state === 'ok' ? 'emerald' : b.state === 'at_risk' ? 'amber' : 'rose';
            return (
              <Card key={b.budget_id} title={b.name} actions={<>
                <StatusBadge status={b.state} />
                {can('operator') && <Button size="sm" variant="ghost" icon={Trash2} aria-label={`Delete ${b.name}`}
                  onClick={() => window.confirm(`Delete budget "${b.name}"?`) && remove.mutate(b.budget_id, { onSuccess: () => toast('Budget deleted') })} />}
              </>}>
                <div className="space-y-3">
                  <div className="text-xs text-slate-400">{b.scope} · {b.month}</div>
                  <Progress value={b.pct_actual / 100} marker={b.pct_projected / 100} tone={tone} />
                  <div className="grid grid-cols-3 gap-2 text-sm">
                    <div><div className="text-[11px] text-slate-400">Spent</div><div className="tabular-nums">{money(b.actual_to_date)} <span className="text-xs text-slate-500">({b.pct_actual}%)</span></div></div>
                    <div><div className="text-[11px] text-slate-400">Projected</div><div className="tabular-nums">{money(b.projected)} <span className="text-xs text-slate-500">({b.pct_projected}%)</span></div></div>
                    <div><div className="text-[11px] text-slate-400">Budget</div><div className="tabular-nums">{money(b.monthly_amount)}</div></div>
                  </div>
                  <div className="text-[11px] text-slate-500">80% range for month end: {money(b.lo80)} – {money(b.hi80)}</div>
                </div>
              </Card>
            );
          })}
        </div>
      ) : <Card><Empty>No budgets yet. Create one per team or namespace to get alerts before the bill arrives.</Empty></Card>)}</Query>
      <BudgetForm open={open} onClose={() => setOpen(false)} clusterId={clusterId} />
    </>
  );
}
