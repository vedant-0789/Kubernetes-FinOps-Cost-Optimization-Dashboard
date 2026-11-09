import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from 'lucide-react';
import { clsx } from 'clsx';

export const cx = clsx;

export function Card({ title, actions, children, className, padded = true }) {
  return (
    <section className={cx('rounded-2xl glass-card', className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 px-5 pt-4">
          {title && <h2 className="text-sm font-semibold text-slate-200">{title}</h2>}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx(padded && 'p-5', !padded && 'pt-3')}>{children}</div>
    </section>
  );
}

const TONES = {
  emerald: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  cyan: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30',
  amber: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
  rose: 'text-rose-400 bg-rose-500/10 border-rose-500/30',
  violet: 'text-violet-400 bg-violet-500/10 border-violet-500/30',
  slate: 'text-slate-300 bg-slate-500/10 border-slate-500/30',
};

export function Kpi({ label, value, hint, icon: Icon, tone = 'emerald' }) {
  return (
    <div className="rounded-2xl glass-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</span>
        {Icon && <span className={cx('rounded-lg border p-1.5', TONES[tone])}><Icon className="h-4 w-4" /></span>}
      </div>
      <div className="mt-2 text-2xl font-bold tracking-tight text-white">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-400">{hint}</div>}
    </div>
  );
}

export function Badge({ tone = 'slate', children, className }) {
  return (
    <span className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold', TONES[tone], className)}>
      {children}
    </span>
  );
}

const RISK = { low: 'emerald', medium: 'amber', high: 'rose' };
export const RiskBadge = ({ risk }) => <Badge tone={RISK[risk] || 'slate'}>{risk} risk</Badge>;

const STATUS = {
  open: 'cyan', applied: 'emerald', verified: 'emerald', dismissed: 'slate', resolved: 'slate', rejected: 'slate',
  dry_run_pending: 'violet', pending_approval: 'amber', approved: 'cyan', rolling_back: 'rose', rolled_back: 'rose',
  failed: 'rose', dry_run_failed: 'rose', acknowledged: 'slate', ok: 'emerald', at_risk: 'amber', exceeded: 'rose',
};
export const StatusBadge = ({ status }) => <Badge tone={STATUS[status] || 'slate'}>{String(status).replaceAll('_', ' ')}</Badge>;

export function Button({ variant = 'primary', size = 'md', loading, icon: Icon, children, className, ...props }) {
  const v = {
    primary: 'bg-emerald-500 text-slate-950 hover:bg-emerald-400 disabled:bg-emerald-500/40',
    secondary: 'border border-slate-700 bg-slate-800/60 text-slate-200 hover:bg-slate-700/60 disabled:opacity-50',
    danger: 'border border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20 disabled:opacity-50',
    ghost: 'text-slate-300 hover:bg-slate-800/60 disabled:opacity-50',
  }[variant];
  const s = size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3.5 py-2 text-sm';
  return (
    <button type="button" className={cx('inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:cursor-not-allowed', v, s, className)}
      disabled={loading || props.disabled} {...props}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : Icon && <Icon className="h-4 w-4" />}
      {children}
    </button>
  );
}

export function Field({ label, hint, children }) {
  // The hint sits outside <label> so the input's accessible name is just the label.
  return (
    <div className="space-y-1">
      <label className="block space-y-1">
        <span className="text-xs font-medium text-slate-300">{label}</span>
        {children}
      </label>
      {hint && <p className="text-[11px] text-slate-500">{hint}</p>}
    </div>
  );
}

const inputCls = 'w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-emerald-500 focus:outline-none';
export const Input = (props) => <input className={inputCls} {...props} />;
export function Select({ options, ...props }) {
  return (
    <select className={inputCls} {...props}>
      {options.map((o) => (typeof o === 'string'
        ? <option key={o} value={o}>{o}</option>
        : <option key={o.value} value={o.value}>{o.label}</option>))}
    </select>
  );
}

export function Segmented({ value, onChange, options }) {
  return (
    <div className="inline-flex rounded-lg border border-slate-700 bg-slate-900/60 p-0.5">
      {options.map((o) => (
        <button key={o.value} type="button" onClick={() => onChange(o.value)}
          className={cx('rounded-md px-2.5 py-1 text-xs font-medium', value === o.value ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200')}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Table({ columns, rows, rowKey, onRowClick, empty = 'Nothing here.' }) {
  if (!rows?.length) return <Empty>{empty}</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-left text-[11px] uppercase tracking-wider text-slate-400">
            {columns.map((c) => <th key={c.key} className={cx('px-3 py-2 font-semibold', c.align === 'right' && 'text-right')}>{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={rowKey ? rowKey(r) : i} onClick={onRowClick ? () => onRowClick(r) : undefined}
              className={cx('border-b border-slate-800/60', onRowClick && 'cursor-pointer hover:bg-slate-800/40')}>
              {columns.map((c) => (
                <td key={c.key} className={cx('px-3 py-2.5 text-slate-200', c.align === 'right' && 'text-right tabular-nums')}>
                  {c.render ? c.render(r) : r[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export const Empty = ({ children }) => <div className="py-8 text-center text-sm text-slate-400">{children}</div>;

export function Loading({ label = 'Loading…' }) {
  return <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" />{label}</div>;
}

export function ErrorBox({ error }) {
  if (!error) return null;
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
      <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{error.message || String(error)}</span>
    </div>
  );
}

export function Query({ q, children, loading }) {
  if (q.isLoading) return loading || <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  return children(q.data);
}

export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Modal({ open, title, onClose, children, footer, wide }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title}
        className={cx('max-h-[90vh] w-full overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl', wide ? 'max-w-2xl' : 'max-w-md')}
        onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
          <h3 className="font-semibold text-white">{title}</h3>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-800"><X className="h-4 w-4" /></button>
        </div>
        <div className="space-y-4 p-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-slate-800 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

/** Prompt for a short reason (dismiss / reject). */
export function ReasonModal({ open, title, onClose, onSubmit, loading, error, cta = 'Confirm' }) {
  const [reason, setReason] = useState('');
  useEffect(() => { if (open) setReason(''); }, [open]);
  return (
    <Modal open={open} title={title} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="danger" loading={loading} disabled={reason.trim().length < 3} onClick={() => onSubmit(reason.trim())}>{cta}</Button>
      </>}>
      <Field label="Reason" hint="Recorded in the audit log (at least 3 characters).">
        <Input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. peak season next week" />
      </Field>
      <ErrorBox error={error} />
    </Modal>
  );
}

const ToastContext = createContext(() => {});
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((message, tone = 'success') => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);
  const icons = { success: CheckCircle2, error: XCircle, warning: AlertTriangle, info: Info };
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] space-y-2">
        {toasts.map((t) => {
          const Icon = icons[t.tone] || Info;
          return (
            <div key={t.id} role="status" className={cx('flex max-w-sm items-start gap-2 rounded-xl border px-4 py-3 text-sm shadow-xl',
              t.tone === 'error' ? 'border-rose-500/40 bg-rose-950 text-rose-100' : 'border-emerald-500/40 bg-slate-900 text-slate-100')}>
              <Icon className="mt-0.5 h-4 w-4 shrink-0" /><span>{t.message}</span>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
export const useToast = () => useContext(ToastContext);

export function Progress({ value, marker, tone = 'emerald' }) {
  const v = Math.max(0, Math.min(value, 1.5));
  const bar = { emerald: 'bg-emerald-500', amber: 'bg-amber-500', rose: 'bg-rose-500' }[tone];
  return (
    <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-slate-800">
      <div className={cx('h-full rounded-full', bar)} style={{ width: `${(Math.min(v, 1)) * 100}%` }} />
      {marker != null && <div className="absolute top-0 h-full w-0.5 bg-white/70" style={{ left: `${Math.min(marker, 1) * 100}%` }} />}
    </div>
  );
}
