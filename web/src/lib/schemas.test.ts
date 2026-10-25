import { describe, expect, it } from 'vitest';
import evaluation from '../test/fixtures/evaluation-marina.json';
import soft from '../test/fixtures/evaluation-marina-soft.json';
import young from '../test/fixtures/evaluation-young.json';
import meta from '../test/fixtures/meta.json';
import whatif from '../test/fixtures/whatif-marina.json';
import { EvaluationSchema, MetaSchema, WhatIfSchema } from './schemas';

describe('API contract', () => {
  it('parses an evaluation with explain, pricing and products', () => {
    const e = EvaluationSchema.parse(evaluation);
    expect(e.outcome).toBe('COUNTER');
    expect(e.reasons[0].code).toBe('L02');
    expect(e.pricing!.rate).toBeGreaterThan(0.1);
    expect(e.approval_explain.length).toBe(11);
    expect(e.products.find((p) => p.product === 'express')!.available).toBe(true);
  });
  it('parses soft mode without an offer and a route to another product', () => {
    const s = EvaluationSchema.parse(soft);
    expect([s.approval_mode, s.pricing, s.monthly_payment]).toEqual(['soft', null, null]);
    const y = EvaluationSchema.parse(young);
    expect(y.route!.to).toBe('card');
  });
  it('parses meta and what-if scenarios with their levers', () => {
    expect(MetaSchema.parse(meta).products).toHaveLength(6);
    const w = WhatIfSchema.parse(whatif);
    expect(w.scenarios.find((s) => s.key === 'term_24')!.levers.requested_term_m).toBe(24);
  });
  it('rejects a response that breaks the contract', () => {
    expect(() => EvaluationSchema.parse({ ...evaluation, outcome: 'MAYBE' })).toThrow();
  });
});

import appFixture from '../test/fixtures/application.json';
import { ApplicationSchema as AppS } from './schemas';

describe('conveyor contract', () => {
  it('parses a sample Application and keeps unknown fields', () => {
    const a = AppS.parse(appFixture) as Record<string, unknown> & { steps: unknown[]; actions: string[] };
    expect(a.steps).toHaveLength(6);
    expect(a.actions).toEqual(['sign', 'withdraw']);
    expect(a.extra_field).toBe(1);
  });
  it('rejects an unknown step state', () => {
    const bad = { ...appFixture, steps: [{ status: 'X', label: 'x', state: 'weird' }] };
    expect(AppS.safeParse(bad).success).toBe(false);
  });
});
