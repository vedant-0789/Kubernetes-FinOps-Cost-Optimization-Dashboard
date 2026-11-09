const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const usd0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

export function money(v, { whole = false } = {}) {
  if (v == null || Number.isNaN(v)) return '—';
  return (whole || Math.abs(v) >= 10000 ? usd0 : usd).format(v);
}

export function pct(v, digits = 0) {
  if (v == null || Number.isNaN(v)) return '—';
  return `${(v * 100).toFixed(digits)}%`;
}

export function cores(v) {
  if (v == null) return '—';
  if (v === 0) return '0';
  return v < 1 ? `${Math.round(v * 1000)}m` : `${+v.toFixed(2)}`;
}

export function bytes(v) {
  if (v == null) return '—';
  const mib = v / 2 ** 20;
  if (mib >= 1024) return `${+(mib / 1024).toFixed(1)} GiB`;
  return `${Math.round(mib)} MiB`;
}

/** Server timestamps are naive UTC ISO strings. */
export function parseUtc(ts) {
  if (!ts) return null;
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(ts) ? ts : `${ts}Z`);
}

export function relTime(ts, now = new Date()) {
  const d = parseUtc(ts);
  if (!d) return 'never';
  const s = Math.round((now - d) / 1000);
  if (s < 0) return 'just now';
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function shortDate(ts) {
  const d = typeof ts === 'string' ? parseUtc(ts.length === 10 ? `${ts}T00:00:00` : ts) : ts;
  if (!d) return '—';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

export function dateTime(ts) {
  const d = parseUtc(ts);
  if (!d) return '—';
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })
    + ' UTC';
}

export const LABELS = { __idle__: 'Idle capacity', __shared__: 'Shared (platform)', __unallocated__: 'Unlabelled' };
export const labelFor = (name) => LABELS[name] || name;
