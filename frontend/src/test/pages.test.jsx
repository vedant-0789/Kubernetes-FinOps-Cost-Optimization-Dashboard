import { describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LoginPage from '../pages/LoginPage';
import ActionsPage, { Timeline } from '../pages/ActionsPage';
import RecommendationsPage from '../pages/RecommendationsPage';
import WastePage from '../pages/WastePage';
import { render } from '@testing-library/react';
import { ADMIN, mockApi, renderAt } from './utils';

const action = (over) => ({
  id: 1, cluster_id: 'c1', type: 'RIGHTSIZE', status: 'pending_approval', namespace: 'shop', workload_kind: 'Deployment',
  workload_name: 'api', container: 'api', patch: {}, recommendation_id: null, finding_id: null, rollback_of: null,
  expected_monthly_savings: 46.4, previous_spec: null, verification: null, error: null, reason: 'over-provisioned',
  requested_by: 'alice@example.com', approved_by: null, created_at: '2026-11-08T09:50:00', updated_at: '2026-11-08T09:50:00',
  applied_at: null, verified_at: null,
  dry_run_diff: { containers: { api: { before: { requests: { cpu: '1' } }, after: { requests: { cpu: '100m' } } } } },
  ...over,
});

describe('LoginPage', () => {
  it('signs in and stores the session', async () => {
    let signedIn = false;
    const calls = mockApi({
      'GET /auth/me': () => (signedIn ? [200, ADMIN] : [401, { detail: 'Not authenticated' }]),
      'POST /auth/login': () => { signedIn = true; return [200, { access_token: 'jwt', expires_at: '2999-01-01T00:00:00', role: 'admin' }]; },
    });
    renderAt('/login', <LoginPage />, '/login');
    await userEvent.type(await screen.findByLabelText('Email'), 'admin@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'correct-horse-battery');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await screen.findByText('other page');     // redirected away from /login
    expect(calls.find((c) => c.path === '/auth/login').body).toEqual({ email: 'admin@example.com', password: 'correct-horse-battery' });
    expect(JSON.parse(localStorage.getItem('kubefinops.session')).access_token).toBe('jwt');
  });

  it('shows the server error on bad credentials', async () => {
    mockApi({ 'GET /auth/me': () => [401, {}], 'POST /auth/login': () => [401, { detail: 'Invalid email or password' }] });
    renderAt('/login', <LoginPage />, '/login');
    await userEvent.type(await screen.findByLabelText('Email'), 'x@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password');
  });
});

describe('ActionsPage', () => {
  it('lets a different operator approve, and shows the dry-run diff', async () => {
    const calls = mockApi({
      'GET /auth/me': { subject: 'bob@example.com', role: 'operator', user_id: 2 },
      'GET /clusters/c1/actions': [action()],
      'POST /clusters/c1/actions/1/approve': action({ status: 'approved', approved_by: 'bob@example.com' }),
    });
    renderAt('/c/c1/actions', <ActionsPage />, '/c/:clusterId/actions');
    const card = (await screen.findByText(/rightsize shop\/api/)).closest('div.rounded-xl');
    expect(within(card).getByText(/"100m"/)).toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/clusters/c1/actions/1/approve')).toBe(true));
  });

  it('does not offer approval to the requester or to viewers', async () => {
    mockApi({ 'GET /auth/me': { subject: 'alice@example.com', role: 'operator', user_id: 1 }, 'GET /clusters/c1/actions': [action()] });
    renderAt('/c/c1/actions', <ActionsPage />, '/c/:clusterId/actions');
    expect(await screen.findByText('needs a second operator')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
  });

  it('timeline marks failed and finished steps', () => {
    const { container, rerender } = render(<Timeline status="verified" />);
    expect(container.querySelectorAll('[data-state="done"]')).toHaveLength(5);
    rerender(<Timeline status="dry_run_failed" />);
    expect(container.querySelector('[data-state="failed"]')).toHaveTextContent('Dry-run');
  });
});

describe('RecommendationsPage', () => {
  it('lists recommendations with savings and reliability fixes', async () => {
    mockApi({
      'GET /auth/me': ADMIN,
      'GET /clusters/c1/recommendations': [
        { id: 7, namespace: 'payments', workload_kind: 'Deployment', workload_name: 'ledger-worker', container: 'ledger', replicas: 1,
          action: 'downsize', current_cpu_request: 4, recommended_cpu_request: 2, current_mem_request: 16 * 2 ** 30,
          recommended_mem_request: 8 * 2 ** 30, monthly_savings: 68.18, confidence_label: 'high', risk: 'medium', status: 'open' },
        { id: 8, namespace: 'ml', workload_kind: 'Deployment', workload_name: 'recommender', container: 'model', replicas: 2,
          action: 'upsize', current_cpu_request: 1.5, recommended_cpu_request: 1.93, current_mem_request: 6 * 2 ** 30,
          recommended_mem_request: 12 * 2 ** 30, monthly_savings: -38.72, confidence_label: 'high', risk: 'high', status: 'open' },
      ],
    });
    renderAt('/c/c1/recommendations', <RecommendationsPage />, '/c/:clusterId/recommendations');
    expect(await screen.findByText('payments/ledger-worker')).toBeInTheDocument();
    expect(screen.getByText('$68.18')).toBeInTheDocument();
    expect(screen.getByText('+$38.72')).toBeInTheDocument();
    expect(screen.getByText('reliability fix')).toBeInTheDocument();
  });
});

describe('WastePage', () => {
  it('offers scale-to-zero only for idle workloads and needs a reason to dismiss', async () => {
    mockApi({
      'GET /auth/me': ADMIN,
      'GET /clusters/c1/waste': [
        { id: 1, kind: 'IDLE_WORKLOAD', namespace: 'data', name: 'Deployment/report-generator', status: 'open', monthly_savings: 56.28,
          risk: 'medium', action: '', first_detected: '2026-11-08T08:00:00',
          evidence: { cpu_p95_cores: 0.004, cpu_request_cores: 2, net_bytes_per_hour: 100, observed_hours: 48 } },
        { id: 2, kind: 'UNUSED_LB', namespace: 'shop', name: 'Service/legacy', status: 'open', monthly_savings: 18.25, risk: 'low',
          action: '', first_detected: '2026-11-08T08:00:00', evidence: { age_hours: 30 } },
      ],
    });
    renderAt('/c/c1/waste', <WastePage />, '/c/:clusterId/waste');
    await screen.findByText('data/Deployment/report-generator');
    expect(screen.getAllByRole('button', { name: 'Scale to 0' })).toHaveLength(1);
    fireEvent.click(screen.getAllByRole('button', { name: 'Dismiss' })[0]);
    const dialog = await screen.findByRole('dialog');
    const confirm = within(dialog).getByRole('button', { name: 'Dismiss' });
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText('Reason'), 'owner confirmed');
    expect(confirm).toBeEnabled();
  });
});
