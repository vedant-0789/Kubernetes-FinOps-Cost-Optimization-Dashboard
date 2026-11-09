import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';

const qs = (params) => {
  const s = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''));
  const str = s.toString();
  return str ? `?${str}` : '';
};

const c = (cid) => `/clusters/${cid}`;

export const useClusters = () => useQuery({ queryKey: ['clusters'], queryFn: () => api('/clusters'), refetchInterval: 60_000 });
export const useSummary = (cid) => useQuery({ queryKey: ['summary', cid], queryFn: () => api(`${c(cid)}/summary`), enabled: !!cid, refetchInterval: 60_000 });
export const useAllocation = (cid, p) => useQuery({ queryKey: ['allocation', cid, p], queryFn: () => api(`${c(cid)}/allocation${qs(p)}`), enabled: !!cid });
export const useTimeseries = (cid, p) => useQuery({ queryKey: ['timeseries', cid, p], queryFn: () => api(`${c(cid)}/cost-timeseries${qs(p)}`), enabled: !!cid });
export const useSavings = (cid) => useQuery({ queryKey: ['savings', cid], queryFn: () => api(`${c(cid)}/savings`), enabled: !!cid });
export const useRecommendations = (cid, p) => useQuery({ queryKey: ['recs', cid, p], queryFn: () => api(`${c(cid)}/recommendations${qs(p)}`), enabled: !!cid });
export const useRecommendation = (cid, id) => useQuery({ queryKey: ['rec', cid, id], queryFn: () => api(`${c(cid)}/recommendations/${id}`), enabled: !!cid && !!id });
export const useCompare = (cid, id) => useQuery({ queryKey: ['compare', cid, id], queryFn: () => api(`${c(cid)}/recommendations/${id}/compare`), enabled: !!cid && !!id });
export const useWaste = (cid, p) => useQuery({ queryKey: ['waste', cid, p], queryFn: () => api(`${c(cid)}/waste${qs(p)}`), enabled: !!cid });
export const useActions = (cid) => useQuery({ queryKey: ['actions', cid], queryFn: () => api(`${c(cid)}/actions`), enabled: !!cid, refetchInterval: 10_000 });
export const useForecast = (cid, p) => useQuery({ queryKey: ['forecast', cid, p], queryFn: () => api(`${c(cid)}/forecast${qs(p)}`), enabled: !!cid });
export const useAnomalies = (cid, p) => useQuery({ queryKey: ['anomalies', cid, p], queryFn: () => api(`${c(cid)}/anomalies${qs(p)}`), enabled: !!cid });
export const useBudgetsStatus = (cid) => useQuery({ queryKey: ['budgets', cid], queryFn: () => api(`${c(cid)}/budgets/status`), enabled: !!cid });
export const useBudgets = (cid) => useQuery({ queryKey: ['budget-defs', cid], queryFn: () => api(`${c(cid)}/budgets`), enabled: !!cid });
export const useUsers = () => useQuery({ queryKey: ['users'], queryFn: () => api('/users') });
export const useChannels = () => useQuery({ queryKey: ['channels'], queryFn: () => api('/notification-channels') });
export const useAudit = (p) => useQuery({ queryKey: ['audit', p], queryFn: () => api(`/audit${qs(p)}`) });

/** Mutation that invalidates the given query-key prefixes on success. */
export function useApiMutation(fn, invalidate = []) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => invalidate.forEach((k) => qc.invalidateQueries({ queryKey: Array.isArray(k) ? k : [k] })),
  });
}
