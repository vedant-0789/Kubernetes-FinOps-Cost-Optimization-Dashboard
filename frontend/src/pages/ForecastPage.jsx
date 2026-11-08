import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { Check } from 'lucide-react';
import { Button, Card, Kpi, PageHeader, Query, Select, StatusBadge, Table, useToast } from '../components/ui';
import { ForecastChart } from '../components/charts';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { money, pct, shortDate } from '../lib/format';
import { useAllocation, useAnomalies, useApiMutation, useForecast } from '../lib/queries';

export default function ForecastPage() {
  const { clusterId } = useParams();
  const { can } = useAuth();
  const toast = useToast();
  const [scope, setScope] = useState('cluster');
  const [days, setDays] = useState(30);
  const fc = useForecast(clusterId, { scope, days });
  const anomalies = useAnomalies(clusterId, { status: 'all' });
  const namespaces = useAllocation(clusterId, { window: '30d', aggregate: 'namespace', include_idle: false });
  const teams = useAllocation(clusterId, { window: '30d', aggregate: 'label:team', include_idle: false });
  const ack = useApiMutation((id) => api(`/clusters/${clusterId}/anomalies/${id}/ack`, { method: 'POST' }), ['anomalies']);

  const scopeOptions = [
    { value: 'cluster', label: 'Whole cluster (bill)' },
    ...(namespaces.data?.items || []).filter((i) => !i.name.startsWith('__')).map((i) => ({ value: `namespace:${i.name}`, label: `Namespace: ${i.name}` })),
    ...(teams.data?.items || []).filter((i) => !i.name.startsWith('__')).map((i) => ({ value: `label:team=${i.name}`, label: `Team: ${i.name}` })),
  ];
  const scopeAnomalies = (anomalies.data || []).filter((a) => (scope === 'cluster' ? a.scope === 'cluster' : `namespace:${a.name}` === scope));

  return (
    <>
      <PageHeader title="Forecast & anomalies" subtitle="Holt-Winters with weekly seasonality; anomalies are days the model did not expect." />
      <div className="flex flex-wrap gap-3">
        <div className="w-72"><Select aria-label="Scope" value={scope} onChange={(e) => setScope(e.target.value)} options={scopeOptions} /></div>
        <div className="w-36"><Select aria-label="Horizon" value={days} onChange={(e) => setDays(Number(e.target.value))}
          options={[{ value: 14, label: '14 days' }, { value: 30, label: '30 days' }, { value: 60, label: '60 days' }]} /></div>
      </div>
      <Query q={fc}>{(f) => (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Kpi label={`Spent in ${f.month_end.month}`} value={money(f.month_end.actual_to_date)} />
            <Kpi label="Projected month end" value={money(f.month_end.projected)} hint={`80%: ${money(f.month_end.lo80)} – ${money(f.month_end.hi80)}`} tone="cyan" />
            <Kpi label="Model" value={f.method === 'holt_winters' ? 'Holt-Winters' : f.method === 'mean' ? 'Recent mean' : '—'}
              hint={f.method === 'mean' ? 'needs 14 days for seasonality' : 'weekly season, damped trend'} tone="violet" />
            <Kpi label="Backtest error (7 d)" value={f.backtest_mape_7d == null ? 'n/a' : pct(f.backtest_mape_7d, 1)}
              hint={f.backtest_mape_7d == null ? 'needs 21 days of history' : 'mean absolute % error'} tone="slate" />
          </div>
          <Card title="Daily cost: actual, forecast and 80% range">
            {f.history.length ? <ForecastChart history={f.history} forecast={f.forecast} anomalies={scopeAnomalies} />
              : <div className="py-10 text-center text-sm text-slate-400">No complete days of data yet.</div>}
          </Card>
        </>
      )}</Query>
      <Card title="Detected anomalies" padded={false}>
        <Query q={anomalies}>{(rows) => (
          <Table rows={rows} rowKey={(a) => a.id} empty="No anomalies detected." columns={[
            { key: 'day', label: 'Day', render: (a) => shortDate(a.day) },
            { key: 'scope', label: 'Where', render: (a) => `${a.scope} · ${a.name}` },
            { key: 'actual', label: 'Actual', align: 'right', render: (a) => money(a.actual) },
            { key: 'expected', label: 'Expected', align: 'right', render: (a) => money(a.expected) },
            { key: 'delta', label: 'Difference', align: 'right', render: (a) => <span className={a.delta > 0 ? 'text-rose-300' : 'text-emerald-300'}>{a.delta > 0 ? '+' : ''}{money(a.delta)}</span> },
            { key: 'score', label: 'z', align: 'right', render: (a) => a.score.toFixed(1) },
            { key: 'status', label: 'Status', render: (a) => <StatusBadge status={a.status} /> },
            { key: 'ack', label: '', render: (a) => a.status === 'open' && can('operator') && (
              <Button size="sm" variant="secondary" icon={Check} loading={ack.isPending && ack.variables === a.id}
                onClick={() => ack.mutate(a.id, { onSuccess: () => toast('Anomaly acknowledged'), onError: (e) => toast(e.message, 'error') })}>Acknowledge</Button>) },
          ]} />
        )}</Query>
      </Card>
    </>
  );
}
