import { NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  Bell, ClipboardCheck, Coins, Gauge, Ghost, LineChart, LogOut, Server, ShieldCheck, Sliders, Target, Users,
} from 'lucide-react';
import { useAuth } from '../lib/auth';
import { useClusters } from '../lib/queries';
import { cx } from './ui';

const CLUSTER_NAV = [
  { to: 'overview', label: 'Overview', icon: Gauge },
  { to: 'costs', label: 'Cost allocation', icon: Coins },
  { to: 'forecast', label: 'Forecast & anomalies', icon: LineChart },
  { to: 'recommendations', label: 'Right-sizing', icon: Sliders },
  { to: 'waste', label: 'Waste', icon: Ghost },
  { to: 'actions', label: 'Changes & approvals', icon: ClipboardCheck },
  { to: 'budgets', label: 'Budgets', icon: Target },
];
const ADMIN_NAV = [
  { to: '/admin/users', label: 'Users', icon: Users },
  { to: '/admin/channels', label: 'Notifications', icon: Bell },
  { to: '/admin/audit', label: 'Audit log', icon: ShieldCheck },
];

function NavItem({ to, label, icon: Icon }) {
  return (
    <NavLink to={to} className={({ isActive }) => cx('flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
      isActive ? 'bg-emerald-500/15 text-emerald-300' : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200')}>
      <Icon className="h-4 w-4" />{label}
    </NavLink>
  );
}

function ClusterSwitcher() {
  const { clusterId } = useParams();
  const { data: clusters = [] } = useClusters();
  const nav = useNavigate();
  const loc = useLocation();
  if (!clusters.length) return null;
  const sub = loc.pathname.split('/')[3] || 'overview';
  return (
    <select aria-label="Cluster" value={clusterId || ''} onChange={(e) => nav(`/c/${e.target.value}/${sub}`)}
      className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none">
      {!clusterId && <option value="">Select a cluster</option>}
      {clusters.map((c) => <option key={c.id} value={c.id}>{c.name}{c.is_active ? '' : ' (disabled)'}</option>)}
    </select>
  );
}

export default function Layout() {
  const { me, logout, can } = useAuth();
  const { clusterId } = useParams();
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-800 bg-slate-950/80 px-3 py-4 md:flex">
        <div className="mb-6 flex items-center gap-2 px-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-500 to-cyan-500 font-black text-slate-950">K</div>
          <div>
            <div className="text-sm font-bold text-white">KubeFinOps</div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Kubernetes cost platform</div>
          </div>
        </div>
        {clusterId && (
          <nav className="space-y-0.5">
            <div className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Cluster</div>
            {CLUSTER_NAV.map((n) => <NavItem key={n.to} {...n} to={`/c/${clusterId}/${n.to}`} />)}
          </nav>
        )}
        <nav className="mt-6 space-y-0.5">
          <div className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Platform</div>
          <NavItem to="/clusters" label="Clusters" icon={Server} />
          {can('admin') && ADMIN_NAV.map((n) => <NavItem key={n.to} {...n} />)}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-slate-800 bg-slate-950/80 px-6 py-3 backdrop-blur">
          <ClusterSwitcher />
          <div className="flex items-center gap-3 text-sm">
            <span className="text-slate-300">{me?.subject}</span>
            <span className="rounded-full border border-slate-700 px-2 py-0.5 text-[11px] uppercase tracking-wider text-slate-400">{me?.role}</span>
            {me?.subject !== 'anonymous' && (
              <button type="button" onClick={logout} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200" aria-label="Sign out">
                <LogOut className="h-4 w-4" />
              </button>
            )}
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 space-y-6 p-6"><Outlet /></main>
      </div>
    </div>
  );
}
