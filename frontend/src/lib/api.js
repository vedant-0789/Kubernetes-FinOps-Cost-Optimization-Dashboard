// Thin fetch wrapper: base URL, JWT, JSON, and errors with the server's detail.
const BASE = import.meta.env.VITE_API_BASE || '/api/v1';
const TOKEN_KEY = 'kubefinops.session';

export const tokenStore = {
  get() {
    try {
      const raw = localStorage.getItem(TOKEN_KEY);
      if (!raw) return null;
      const t = JSON.parse(raw);
      // Server timestamps are naive UTC.
      if (t.expires_at && new Date(`${t.expires_at.replace(/Z$/, '')}Z`) <= new Date()) {
        localStorage.removeItem(TOKEN_KEY);
        return null;
      }
      return t;
    } catch {
      return null;
    }
  },
  set(t) {
    try { localStorage.setItem(TOKEN_KEY, JSON.stringify(t)); } catch { /* private mode */ }
  },
  clear() {
    try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
  },
};

export class ApiError extends Error {
  constructor(status, detail) {
    super(formatDetail(detail));
    this.status = status;
    this.detail = detail;
  }
}

/** FastAPI returns a string, or a list of validation errors. */
export function formatDetail(detail) {
  if (detail == null) return 'Request failed';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc || []).filter((x) => x !== 'body').join('.') || 'request'}: ${d.msg}`).join('; ');
  }
  return JSON.stringify(detail);
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

export async function api(path, { method = 'GET', body, raw = false, auth = true } = {}) {
  const headers = {};
  const session = auth ? tokenStore.get() : null;
  if (session) headers.Authorization = `Bearer ${session.access_token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && auth) onUnauthorized();
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, detail);
  }
  if (raw) return res;
  if (res.status === 204) return null;
  return res.json();
}

/** Download an authenticated file (CSV, PDF, YAML) without exposing the token in a URL. */
export async function download(path, filename) {
  const res = await api(path, { raw: true });
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
