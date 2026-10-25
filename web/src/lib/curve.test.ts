import { describe, expect, it } from 'vitest';
import sim from '../test/fixtures/simulate-marina.json';
import { at, kindOf, logAxis, zones } from './curve';
import { SimulationSchema } from './schemas';

const s = SimulationSchema.parse(sim);

describe('curve maths', () => {
  it('maps amounts to pixels on a log axis and back', () => {
    const ax = logAxis(300_000, 10_000_000, 0, 700);
    expect(ax.px(300_000)).toBeCloseTo(0);
    expect(ax.px(10_000_000)).toBeCloseTo(700);
    expect(ax.amount(ax.px(3_610_000), 10_000)).toBe(3_610_000);
    expect(ax.amount(-50, 10_000)).toBe(300_000); // за краем - клип к диапазону
  });

  it('interpolates the chance between sweep points and returns exact values on a point', () => {
    const p = s.points.find((q) => q.x === 3_610_000)!;
    expect(at(s.points, 3_610_000).approval_probability).toBeCloseTo(p.approval_probability);
    const [a, b] = [s.points[3], s.points[4]];
    const mid = Math.sqrt(a.x * b.x); // середина на логарифмической оси
    const v = at(s.points, mid).approval_probability;
    expect(v).toBeGreaterThanOrEqual(Math.min(a.approval_probability, b.approval_probability) - 1e-9);
    expect(v).toBeLessThanOrEqual(Math.max(a.approval_probability, b.approval_probability) + 1e-9);
    expect(at(s.points, 3_620_000).outcome).toBe('COUNTER'); // исход - ближайшей точки
  });

  it('splits the axis into outcome zones at the limit', () => {
    const z = zones(s.points, 'express');
    expect(z[0].kind).toBe('approve');
    expect(z.at(-1)!.kind).toBe('counter');
    const edge = z.find((q) => q.kind === 'counter')!.from;
    expect(edge).toBeGreaterThan(3_610_000);
    expect(edge).toBeLessThan(3_620_000);
    expect(kindOf({ outcome: 'COUNTER', offered_product: 'card' }, 'credit_line')).toBe('no'); // маршрут
  });
});
