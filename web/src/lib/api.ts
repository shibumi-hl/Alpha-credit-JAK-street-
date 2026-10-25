// Клиент API песочницы: каждый ответ проверяется схемой контракта.
import type { z } from 'zod';
import {
  EvaluationSchema,
  MetaSchema,
  PersonaCardSchema,
  PersonaSchema,
  SimulationSchema,
  WhatIfSchema,
  type Levers,
} from './schemas';

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
