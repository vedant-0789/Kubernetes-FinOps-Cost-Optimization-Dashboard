import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { vi } from 'vitest';
import { ToastProvider } from '../components/ui';
import { AuthProvider } from '../lib/auth';

/** Route table: { 'GET /auth/me': body | (req) => [status, body] }. Unknown routes 404. */
export function mockApi(routes) {
  const calls = [];
  const fetchMock = vi.fn(async (url, opts = {}) => {
    const method = opts.method || 'GET';
    const path = url.replace(/^\/api\/v1/, '').split('?')[0];
    calls.push({ method, path, url, body: opts.body ? JSON.parse(opts.body) : undefined, headers: opts.headers || {} });
    const handler = routes[`${method} ${path}`];
    let status = 200;
    let body = handler;
    if (typeof handler === 'function') [status, body] = handler({ method, path, url, opts });
    if (handler === undefined) [status, body] = [404, { detail: `no mock for ${method} ${path}` }];
    return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

export const ADMIN = { subject: 'admin@example.com', role: 'admin', user_id: 1 };

export function renderAt(path, element, routePath = '*') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <ToastProvider>
            <Routes>
              <Route path={routePath} element={element} />
              <Route path="*" element={<div>other page</div>} />
            </Routes>
          </ToastProvider>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
