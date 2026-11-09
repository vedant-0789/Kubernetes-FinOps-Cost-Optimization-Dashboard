import { describe, expect, it, vi } from 'vitest';
import { api, ApiError, formatDetail, setUnauthorizedHandler, tokenStore } from '../lib/api';
import { bytes, cores, labelFor, money, pct, relTime } from '../lib/format';
import { hasRole } from '../lib/auth';

describe('format', () => {
  it('formats money, percent, cores and bytes', () => {
    expect(money(1234.5)).toBe('$1,234.50');
    expect(money(123456)).toBe('$123,456');
    expect(money(null)).toBe('—');
    expect(pct(0.256)).toBe('26%');
    expect(cores(0.25)).toBe('250m');
    expect(cores(2)).toBe('2');
    expect(bytes(512 * 2 ** 20)).toBe('512 MiB');
    expect(bytes(6 * 2 ** 30)).toBe('6 GiB');
  });

  it('treats server timestamps as UTC', () => {
    const now = new Date('2026-11-08T12:00:00Z');
    expect(relTime('2026-11-08T11:58:00', now)).toBe('2 min ago');
    expect(relTime(null, now)).toBe('never');
  });

  it('names synthetic allocation rows', () => {
    expect(labelFor('__idle__')).toBe('Idle capacity');
    expect(labelFor('payments')).toBe('payments');
  });
});

describe('roles', () => {
  it('orders viewer < operator < admin', () => {
    expect(hasRole({ role: 'operator' }, 'viewer')).toBe(true);
    expect(hasRole({ role: 'operator' }, 'admin')).toBe(false);
    expect(hasRole(null, 'viewer')).toBe(false);
  });
});

describe('api client', () => {
  it('formats FastAPI validation errors', () => {
    expect(formatDetail([{ loc: ['body', 'monthly_amount'], msg: 'must be > 0' }])).toBe('monthly_amount: must be > 0');
    expect(formatDetail('Nope')).toBe('Nope');
  });

  it('sends the bearer token and surfaces the server detail', async () => {
    tokenStore.set({ access_token: 'jwt-1', expires_at: '2999-01-01T00:00:00' });
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ detail: 'Two-person rule' }), { status: 403 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(api('/x')).rejects.toThrow('Two-person rule');
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer jwt-1');
  });

  it('calls the unauthorized handler on 401', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"Token expired"}', { status: 401 })));
    const err = await api('/x').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(401);
    expect(handler).toHaveBeenCalled();
  });

  it('drops expired sessions', () => {
    tokenStore.set({ access_token: 'old', expires_at: '2000-01-01T00:00:00' });
    expect(tokenStore.get()).toBeNull();
  });
});
