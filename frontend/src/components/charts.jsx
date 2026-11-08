import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import { labelFor, money, shortDate } from '../lib/format';

export const PALETTE = ['#10B981', '#22D3EE', '#8B5CF6', '#F59E0B', '#EC4899', '#3B82F6', '#84CC16'];
export const IDLE_COLOR = '#475569';
const AXIS = { stroke: '#64748B', fontSize: 11, tickLine: false, axisLine: false };
const GRID = <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" vertical={false} />;
const tooltipStyle = { contentStyle: { background: '#0F172A', border: '1px solid #334155', borderRadius: 8, fontSize: 12 } };

/** Stacked daily/hourly cost by group (top namespaces + other + idle).
 *  Daily series drop today's bucket: a partial day would look like a cost cliff. */
export function StackedCost({ points, height = 260, dropPartialToday = true }) {
  const today = new Date().toISOString().slice(0, 10);
  const shown = dropPartialToday ? points.filter((p) => !p.start.startsWith(today)) : points;
  const groups = [...new Set(shown.flatMap((p) => Object.keys(p.by_group)))];
  const data = shown.map((p) => ({ start: p.start, ...p.by_group, __idle__: p.idle_cost }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data}>
        {GRID}
        <XAxis dataKey="start" tickFormatter={shortDate} {...AXIS} minTickGap={24} />
        <YAxis tickFormatter={(v) => `$${v.toFixed(0)}`} {...AXIS} width={48} />
        <Tooltip {...tooltipStyle} labelFormatter={shortDate} formatter={(v, n) => [money(v), labelFor(n)]} />
        <Legend formatter={labelFor} wrapperStyle={{ fontSize: 11 }} />
        {groups.map((g, i) => <Area isAnimationActive={false} key={g} type="monotone" dataKey={g} stackId="1" stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.35} />)}
        <Area isAnimationActive={false} type="monotone" dataKey="__idle__" stackId="1" stroke={IDLE_COLOR} fill={IDLE_COLOR} fillOpacity={0.4} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function CostBars({ items, height = 260 }) {
  const data = items.slice(0, 10).map((i) => ({ name: labelFor(i.name), total: i.total_cost, idle: i.name === '__idle__' }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ left: 8 }}>
        {GRID}
        <XAxis type="number" tickFormatter={(v) => `$${v.toFixed(0)}`} {...AXIS} />
        <YAxis type="category" dataKey="name" width={150} {...AXIS} />
        <Tooltip {...tooltipStyle} formatter={(v) => money(v)} cursor={{ fill: '#1E293B' }} />
        <Bar isAnimationActive={false} dataKey="total" radius={[0, 4, 4, 0]} fill="#10B981" />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** History + forecast with an 80 % band. */
export function ForecastChart({ history, forecast, anomalies = [], height = 300 }) {
  const anomalyDays = new Set(anomalies.map((a) => a.day.slice(0, 10)));
  const data = [
    ...history.map((h) => ({ day: h.day, actual: h.cost, anomaly: anomalyDays.has(h.day) ? h.cost : null })),
    ...forecast.map((p) => ({ day: p.day, forecast: p.value, band: [p.lo80, p.hi80] })),
  ];
  const today = forecast[0]?.day;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data}>
        {GRID}
        <XAxis dataKey="day" tickFormatter={shortDate} {...AXIS} minTickGap={24} />
        <YAxis tickFormatter={(v) => `$${v.toFixed(0)}`} {...AXIS} width={48} />
        <Tooltip {...tooltipStyle} labelFormatter={shortDate}
          formatter={(v, n) => [Array.isArray(v) ? `${money(v[0])} – ${money(v[1])}` : money(v),
            { actual: 'Actual', forecast: 'Forecast', band: '80% range', anomaly: 'Anomaly' }[n] || n]} />
        <Area isAnimationActive={false} dataKey="band" stroke="none" fill="#22D3EE" fillOpacity={0.15} />
        <Line isAnimationActive={false} dataKey="actual" stroke="#10B981" strokeWidth={2} dot={false} />
        <Line isAnimationActive={false} dataKey="forecast" stroke="#22D3EE" strokeWidth={2} strokeDasharray="5 4" dot={false} />
        <Line dataKey="anomaly" stroke="none" dot={{ r: 5, fill: '#F43F5E', stroke: '#F43F5E' }} isAnimationActive={false} />
        {today && <ReferenceLine x={today} stroke="#64748B" strokeDasharray="2 2" label={{ value: 'today', fill: '#94A3B8', fontSize: 10 }} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** Usage over time against current and recommended request (right-sizing evidence). */
export function UsageChart({ usage, peakKey, medianKey, current, recommended, limit, format, height = 240, oomKey }) {
  const data = usage.map((u) => ({ start: u.start, peak: u[peakKey], median: u[medianKey], oom: oomKey && u[oomKey] > 0 ? u[peakKey] : null }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data}>
        {GRID}
        <XAxis dataKey="start" tickFormatter={shortDate} {...AXIS} minTickGap={32} />
        <YAxis tickFormatter={format} {...AXIS} width={64} />
        <Tooltip {...tooltipStyle} labelFormatter={(v) => new Date(`${v}Z`).toUTCString().slice(5, 22)}
          formatter={(v, n) => [format(v), { peak: 'Peak', median: 'Median', oom: 'OOM kill' }[n] || n]} />
        <Area isAnimationActive={false} dataKey="peak" stroke="#22D3EE" fill="#22D3EE" fillOpacity={0.12} />
        <Line isAnimationActive={false} dataKey="median" stroke="#10B981" dot={false} strokeWidth={1.5} />
        {oomKey && <Line dataKey="oom" stroke="none" dot={{ r: 4, fill: '#F43F5E' }} isAnimationActive={false} />}
        <ReferenceLine ifOverflow="extendDomain" y={current} stroke="#F59E0B" strokeDasharray="6 3" label={{ value: 'current request', fill: '#F59E0B', fontSize: 10, position: 'insideTopRight' }} />
        <ReferenceLine ifOverflow="extendDomain" y={recommended} stroke="#10B981" strokeDasharray="6 3" label={{ value: 'recommended', fill: '#10B981', fontSize: 10, position: 'insideBottomRight' }} />
        {limit && <ReferenceLine ifOverflow="extendDomain" y={limit} stroke="#F43F5E" strokeDasharray="2 2" label={{ value: 'limit', fill: '#F43F5E', fontSize: 10, position: 'insideTopLeft' }} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
