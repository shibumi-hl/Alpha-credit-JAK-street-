import { describe, expect, it } from 'vitest';
import bakery from '../test/fixtures/evaluation-bakery.json';
import docs from '../test/fixtures/evaluation-docs.json';
import marina from '../test/fixtures/evaluation-marina.json';
import soft from '../test/fixtures/evaluation-marina-soft.json';
import overdue from '../test/fixtures/evaluation-overdue.json';
import young from '../test/fixtures/evaluation-young.json';
import meta from '../test/fixtures/meta.json';
import { decision } from './decision';
import { EvaluationSchema, MetaSchema } from './schemas';

const m = MetaSchema.parse(meta);
const d = (x: unknown) => decision(EvaluationSchema.parse(x), m);
const N = ' ';

describe('decision card per outcome', () => {
  it('counter-offer on the same product: the amount, the cash-flow reason, take it or see variants', () => {
    const r = d(marina);
    expect(r.tone).toBe('counter');
    expect(r.headline).toBe(`Можем выдать 3,61${N}млн${N}₽`);
    expect(r.reasons[0]).toContain('денежного потока');
    expect(r.actions.map((a) => a.kind)).toEqual(['take', 'variants']);
    expect(r.actions[0].change).toEqual({ requested_amount: 3_610_000 });
  });

  it('soft pre-assessment asks for the credit bureau consent', () => {
    const r = d(soft);
    expect(r.tone).toBe('info');
    expect(r.actions[0]).toMatchObject({ kind: 'consent', change: { bki_consent: true } });
  });

  it('a route to another product says why the requested one is closed', () => {
    const r = d(young);
    expect(r.tone).toBe('counter');
    expect(r.headline).toContain('бизнес-карта');
    expect(r.reasons[0]).toMatch(/кредитная линия.*молодой/);
    expect(r.actions[0]).toMatchObject({ kind: 'take', change: { product: 'card', requested_amount: 1_000_000 } });
  });

  it('approval offers to apply, a document request lists documents, a rejection gives the stop factor', () => {
    expect(d(bakery)).toMatchObject({ tone: 'approve', actions: [{ kind: 'submit' }] });
    const r = d(docs);
    expect([r.tone, r.actions[0].kind]).toEqual(['info', 'upload']);
    expect(r.reasons[0]).toContain('справка ФНС');
    const x = d(overdue);
    expect(x.tone).toBe('reject');
    expect(x.reasons[0]).toBe('текущая просрочка более 30 дней');
  });
});
