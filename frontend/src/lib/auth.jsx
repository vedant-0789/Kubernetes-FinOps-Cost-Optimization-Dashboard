import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, setUnauthorizedHandler, tokenStore } from './api';

const ROLES = ['viewer', 'operator', 'admin'];
const AuthContext = createContext(null);

export function hasRole(me, role) {
  if (!me) return false;
  return ROLES.indexOf(me.role) >= ROLES.indexOf(role);
}

export function AuthProvider({ children }) {
  const qc = useQueryClient();
  const [me, setMe] = useState(null);
  const [status, setStatus] = useState('loading'); // loading | authenticated | anonymous

  const refresh = useCallback(async () => {
    try {
      setMe(await api('/auth/me'));
      setStatus('authenticated');
    } catch {
      setMe(null);
      setStatus('anonymous');
    }
  }, []);

  const logout = useCallback(() => {
    tokenStore.clear();
    qc.clear();
    setMe(null);
    setStatus('anonymous');
  }, [qc]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (tokenStore.get() || status === 'authenticated') logout();
    });
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(async (email, password) => {
    const session = await api('/auth/login', { method: 'POST', body: { email, password }, auth: false });
    tokenStore.set(session);
    await refresh();
  }, [refresh]);

  const value = useMemo(() => ({ me, status, login, logout, can: (r) => hasRole(me, r) }), [me, status, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth outside AuthProvider');
  return ctx;
}
