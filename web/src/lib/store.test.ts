import { beforeEach, describe, expect, it } from 'vitest';
import persona from '../test/fixtures/persona-marina.json';
import { useSandbox } from './store';
import type { Levers } from './schemas';

const base = persona.levers as unknown as Levers;

describe('levers state', () => {
  beforeEach(() => useSandbox.getState().load('marina', base));

  it('applies a scenario and undoes it', () => {
    const s = useSandbox.getState();
    s.apply({ ...base, requested_term_m: 24 }, 'Взять на 24 месяца');
    expect(useSandbox.getState().levers.requested_term_m).toBe(24);
    expect(useSandbox.getState().history.at(-1)!.label).toBe('Взять на 24 месяца');
    useSandbox.getState().undo();
    expect(useSandbox.getState().levers.requested_term_m).toBe(12);
    expect(useSandbox.getState().history).toHaveLength(0);
  });

  it('keeps the amount inside the new product range', () => {
    useSandbox.getState().setProduct('card', { min_amount: 50_000, max_amount: 1_000_000 });
    expect(useSandbox.getState().levers).toMatchObject({ product: 'card', requested_amount: 1_000_000 });
  });

  it('loading another company resets the history', () => {
    useSandbox.getState().set({ guarantee: true }, 'Гарантия');
    useSandbox.getState().load('bakery', { ...base, product: 'secured' });
    expect(useSandbox.getState().history).toHaveLength(0);
    expect(useSandbox.getState().personaId).toBe('bakery');
  });
});
