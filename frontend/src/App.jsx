import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import Layout from './components/Layout';
import { Loading } from './components/ui';
import { useAuth } from './lib/auth';
import { useClusters } from './lib/queries';
import ActionsPage from './pages/ActionsPage';
import AuditPage from './pages/AuditPage';
import BudgetsPage from './pages/BudgetsPage';
import ChannelsPage from './pages/ChannelsPage';
import ClustersPage from './pages/ClustersPage';
import CostsPage from './pages/CostsPage';
import ForecastPage from './pages/ForecastPage';
import LoginPage from './pages/LoginPage';
import OverviewPage from './pages/OverviewPage';
import RecommendationDetailPage from './pages/RecommendationDetailPage';
import RecommendationsPage from './pages/RecommendationsPage';
import UsersPage from './pages/UsersPage';
import WastePage from './pages/WastePage';

function RequireAuth({ children, role }) {
  const { status, can } = useAuth();
  const loc = useLocation();
  if (status === 'loading') return <Loading label="Checking your session…" />;
  if (status !== 'authenticated') return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  if (role && !can(role)) return <Navigate to="/" replace />;
  return children;
}

function Home() {
  const { data, isLoading } = useClusters();
  if (isLoading) return <Loading />;
  const first = data?.find((c) => c.is_active) || data?.[0];
  return <Navigate to={first ? `/c/${first.id}/overview` : '/clusters'} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<Home />} />
        <Route path="clusters" element={<ClustersPage />} />
        <Route path="c/:clusterId">
          <Route index element={<Navigate to="overview" replace />} />
          <Route path="overview" element={<OverviewPage />} />
          <Route path="costs" element={<CostsPage />} />
          <Route path="forecast" element={<ForecastPage />} />
          <Route path="recommendations" element={<RecommendationsPage />} />
          <Route path="recommendations/:recId" element={<RecommendationDetailPage />} />
          <Route path="waste" element={<WastePage />} />
          <Route path="actions" element={<ActionsPage />} />
          <Route path="budgets" element={<BudgetsPage />} />
        </Route>
        <Route path="admin/users" element={<RequireAuth role="admin"><UsersPage /></RequireAuth>} />
        <Route path="admin/channels" element={<RequireAuth role="admin"><ChannelsPage /></RequireAuth>} />
        <Route path="admin/audit" element={<RequireAuth role="admin"><AuditPage /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
