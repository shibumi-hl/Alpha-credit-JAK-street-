// Серверное состояние: ключ запроса — компания и рычаги, устаревший запрос отменяется, пока идёт новый — на экране
// прошлый ответ (без мигания).
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { api } from './api';
import type { Levers } from './schemas';
import { useSandbox } from './store';

export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity });
}

export function usePersonas() {
  return useQuery({ queryKey: ['personas'], queryFn: api.personas, staleTime: Infinity });
}

export function usePersona(id: string | null) {
  return useQuery({ queryKey: ['persona', id], queryFn: () => api.persona(id!), enabled: !!id, staleTime: Infinity });
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function useEvaluation() {
  const { personaId, levers } = useSandbox();
  return useQuery({
    queryKey: ['evaluation', personaId, levers],
    queryFn: ({ signal }) => api.evaluate(personaId!, levers!, signal),
    enabled: !!personaId && !!levers,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
}

export function useWhatIf() {
  const { personaId, levers } = useSandbox();
  const lv = useDebounced(levers, 250);
  return useQuery({
    queryKey: ['whatif', personaId, lv],
    queryFn: ({ signal }) => api.whatif(personaId!, lv!, signal),
    enabled: !!personaId && !!lv,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
}

/** Кривая по сумме не зависит от самой суммы заявки: ключ без неё, иначе каждое движение ползунка — новый запрос. */
export function useAmountCurve(override?: Levers | null) {
  const { personaId, levers: current } = useSandbox();
  const levers = override ?? current;
  const key = levers ? { ...levers, requested_amount: 0 } : null;
  return useQuery({
    queryKey: ['simulate', personaId, key],
    queryFn: ({ signal }) => api.simulate(personaId!, levers!, 'requested_amount', signal),
    enabled: !!personaId && !!levers,
    placeholderData: override ? undefined : keepPreviousData,
    staleTime: Infinity,
  });
}
