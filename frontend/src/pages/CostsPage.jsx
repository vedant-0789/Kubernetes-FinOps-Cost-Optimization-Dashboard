import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { FileDown, FileSpreadsheet } from 'lucide-react';
import { Badge, Button, Card, Input, Kpi, PageHeader, Query, Segmented, Select, Table, useToast } from '../components/ui';
import { CostBars } from '../components/charts';
import { download } from '../lib/api';
import { labelFor, money, pct } from '../lib/format';
import { useAllocation } from '../lib/queries';

const AGGREGATES = [
  { value: 'namespace', label: 'Namespace' }, { value: 'workload', label: 'Workload' }, { value: 'node', label: 'Node' },
  { value: 'pod', label: 'Pod' }, { value: 'label:team', label: 'Team (label)' }, { value: 'label:cost-center', label: 'Cost center (label)' },
  { value: 'custom', label: 'Other label…' },
];

function effTone(e) {
  return e >= 0.6 ? 'emerald' : e >= 0.3 ? 'amber' : 'rose';
}

export default function CostsPage() {
  const { clusterId } = useParams();
  const toast = useToast();
  const [window, setWindow] = useState('7d');
  const [agg, setAgg] = useState('label:team');
  const [customKey, setCustomKey] = useState('env');
  const [shared, setShared] = useState('distribute');
  const aggregate = agg === 'custom' ? `label:${customKey}` : agg;
  const q = useAllocation(clusterId, { window, aggregate, shared, include_idle: true });
  const [busy, setBusy] = useState(null);

  const exportReport = async (fmt) => {
    setBusy(fmt);
    try {
      const month = new Date().toISOString().slice(0, 7);
      await download(`/clusters/${clusterId}/reports/showback.${fmt}?month=${month}&aggregate=${encodeURIComponent(aggregate)}&shared=${shared}`,
        `showback-${month}.${fmt}`);
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader title="Cost allocation" subtitle="OpenCost model: containers pay max(request, usage); unreserved node capacity is idle cost."
        actions={<>
          <Button variant="secondary" icon={FileSpreadsheet} loading={busy === 'csv'} onClick={() => exportReport('csv')}>This month (CSV)</Button>
          <Button variant="secondary" icon={FileDown} loading={busy === 'pdf'} onClick={() => exportReport('pdf')}>Report (PDF)</Button>
        </>} />
      <div className="flex flex-wrap items-end gap-3">
        <Segmented value={window} onChange={setWindow} options={[{ value: '24h', label: '24 h' }, { value: '7d', label: '7 days' }, { value: '30d', label: '30 days' }]} />
        <div className="w-48"><Select aria-label="Group by" value={agg} onChange={(e) => setAgg(e.target.value)} options={AGGREGATES} /></div>
        {agg === 'custom' && <div className="w-40"><Input aria-label="Label key" value={customKey} onChange={(e) => setCustomKey(e.target.value)} placeholder="label key" /></div>}
        <Segmented value={shared} onChange={setShared} options={[{ value: 'distribute', label: 'Spread shared costs' }, { value: 'separate', label: 'Show shared separately' }]} />
      </div>
      <Query q={q}>{(r) => (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Kpi label="Total" value={money(r.total_cost)} hint={`${window} window`} />
            <Kpi label="Allocated" value={money(r.allocated_cost)} tone="cyan" />
            <Kpi label="Idle" value={money(r.idle_cost)} hint={pct(r.total_cost ? r.idle_cost / r.total_cost : 0)} tone="amber" />
            <Kpi label="Efficiency" value={pct(r.efficiency)} tone="violet" />
          </div>
          <div className="grid gap-6 lg:grid-cols-5">
            <Card title="Top 10" className="lg:col-span-2"><CostBars items={r.items} /></Card>
            <Card title={`By ${aggregate}`} className="lg:col-span-3" padded={false}>
              <Table rowKey={(i) => i.name} rows={r.items} columns={[
                { key: 'name', label: 'Name', render: (i) => <span className={i.name.startsWith('__') ? 'italic text-slate-400' : ''}>{labelFor(i.name)}</span> },
                { key: 'cpu', label: 'CPU', align: 'right', render: (i) => money(i.cpu_cost) },
                { key: 'ram', label: 'Memory', align: 'right', render: (i) => money(i.ram_cost) },
                { key: 'shared', label: 'Shared', align: 'right', render: (i) => (i.shared_cost_added ? money(i.shared_cost_added) : '—') },
                { key: 'total', label: 'Total', align: 'right', render: (i) => <b>{money(i.total_cost)}</b> },
                { key: 'eff', label: 'Efficiency', align: 'right', render: (i) => (i.name === '__idle__' ? '—' : <Badge tone={effTone(i.efficiency)}>{pct(i.efficiency)}</Badge>) },
              ]} />
            </Card>
          </div>
        </>
      )}</Query>
    </>
  );
}
