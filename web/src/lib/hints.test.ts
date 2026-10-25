import { describe, expect, it } from 'vitest';
import overdue from '../test/fixtures/evaluation-overdue.json';
import soft from '../test/fixtures/evaluation-marina-soft.json';
import young from '../test/fixtures/evaluation-young.json';
import whatif from '../test/fixtures/whatif-marina.json';
import { bestScenario, igorHint } from './hints';
import { EvaluationSchema, WhatIfSchema } from './schemas';

const w = WhatIfSchema.parse(whatif);

describe('ИИгорь hints', () => {
  it('prefers the scenario that turns the answer into an approval', () => {
    expect(bestScenario(w.scenarios)!.key).toBe('term_24'); // одобрение всей суммы, а не части
    const rest = w.scenarios.filter((s) => s.key !== 'term_24');
    expect(bestScenario(rest)!.key).toBe('amount_to_limit'); // одобрение важнее, чем +2 п.п. шанса от залога
  });

  it('a cash-bound counter-offer names the cause and the way out, with one full stop', () => {
    const h = igorHint(w.base, w.scenarios);
    expect(h).toMatch(/^Ограничивает платёж, а не риск\./);
    expect(h).toContain('«Взять на 24 месяца»');
    expect(h).not.toMatch(/\.\.$/);
  });

  it('a route to another product points to what is open now, not to a scenario', () => {
    const h = igorHint(EvaluationSchema.parse(young), w.scenarios);
    expect(h).not.toContain('Попробуйте');
    expect(h).toContain('сейчас');
  });

  it('soft mode shows the chance from the API; a rejection stays calm and number-free', () => {
    expect(igorHint(EvaluationSchema.parse(soft), [])).toContain('57%');
    const r = igorHint(EvaluationSchema.parse(overdue), []);
    expect(r).not.toMatch(/\d/);
  });
});
