// Клиент API песочницы: каждый ответ проверяется схемой контракта.
import type { z } from 'zod';
import {
  EvaluationSchema,
  MetaSchema,
  PersonaCardSchema,
  PersonaSchema,
  SimulationSchema,
  WhatIfSchema,
  AppSummarySchema,
  ApplicationSchema,
  ChatReplySchema,
  CompanySchema,
  LoginSchema,
  NewsSchema,
  type Levers,
} from './schemas';
import { useAuth } from './auth';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<S extends z.ZodType>(path: string, schema: S, init?: RequestInit): Promise<z.infer<S>> {
  let r: Response;
  try {
    r = await fetch(path, init);
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new ApiError(0, 'Сервис скоринга недоступен');
  }
  if (!r.ok) {
    let detail: unknown;
    try {
      detail = (await r.json()).detail;
    } catch {
      // тело не JSON
    }
    if (r.status === 401 && useAuth.getState().token) useAuth.getState().logout();
    throw new ApiError(r.status, typeof detail === 'string' ? detail : 'Сервис скоринга недоступен');
  }
  return schema.parse(await r.json());
}

const post = (body: unknown, signal?: AbortSignal): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
  signal,
});

export const api = {
  meta: () => call('/api/v1/meta', MetaSchema),
  personas: () => call('/api/v1/personas', PersonaCardSchema.array()),
  persona: (id: string) => call(`/api/v1/personas/${encodeURIComponent(id)}`, PersonaSchema),
  evaluate: (persona_id: string, levers: Levers, signal?: AbortSignal) =>
    call('/api/v1/evaluations', EvaluationSchema, post({ persona_id, levers }, signal)),
  whatif: (persona_id: string, levers: Levers, signal?: AbortSignal) =>
    call('/api/v1/whatif', WhatIfSchema, post({ persona_id, levers }, signal)),
  simulate: (persona_id: string, levers: Levers, axis: 'requested_amount' | 'requested_term_m', signal?: AbortSignal) =>
    call('/api/v1/simulate', SimulationSchema, post({ persona_id, levers, axis, n: 32 }, signal)),
};

const authed = (init: RequestInit = {}, extra: Record<string, string> = {}): RequestInit => {
  const t = useAuth.getState().token;
  return {
    ...init,
    headers: { ...(init.headers as Record<string, string>), ...(t ? { Authorization: `Bearer ${t}` } : {}), ...extra },
  };
};

export interface ActionBody {
  action: string;
  note?: string;
  amount?: number;
  code?: string;
}

export const conveyor = {
  login: (username: string, password: string) => call('/api/v1/auth/login', LoginSchema, post({ username, password })),
  company: (inn: string) => call(`/api/v1/companies/${encodeURIComponent(inn)}`, CompanySchema),
  news: (persona_id: string) => call(`/api/v1/news?persona_id=${encodeURIComponent(persona_id)}`, NewsSchema.array(), authed()),
  submit: (body: { persona_id: string; levers: Levers; purpose: string; bki_consent: true }, key: string) =>
    call('/api/v1/applications', ApplicationSchema, authed(post(body), { 'Idempotency-Key': key })),
  list: (status?: string) =>
    call(`/api/v1/applications${status ? `?status=${encodeURIComponent(status)}` : ''}`, AppSummarySchema.array(), authed()),
  get: (id: string) => call(`/api/v1/applications/${encodeURIComponent(id)}`, ApplicationSchema, authed()),
  act: (id: string, body: ActionBody) =>
    call(`/api/v1/applications/${encodeURIComponent(id)}/actions`, ApplicationSchema, authed(post(body))),
  chat: (persona_id: string, levers: Levers, messages: { role: 'user' | 'assistant'; content: string }[]) =>
    call('/api/v1/chat', ChatReplySchema, authed(post({ persona_id, levers, messages }))),
};
