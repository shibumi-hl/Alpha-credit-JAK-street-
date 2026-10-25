import { describe, expect, it } from 'vitest';
import { chance, months, pct, pp, rub, rubExact } from './format';

const N = ' ';

describe('ru-RU formatting', () => {
  it('shortens amounts to three significant digits', () => {
    expect(rub(3_610_000)).toBe(`3,61${N}млн${N}₽`);
    expect(rub(6_000_000)).toBe(`6${N}млн${N}₽`);
    expect(rub(41_620_000)).toBe(`41,6${N}млн${N}₽`);
    expect(rub(332_730.9)).toBe(`333${N}тыс.${N}₽`);
    expect(rub(950)).toBe(`950${N}₽`);
  });
  it('prints exact amounts with grouped digits', () => {
    expect(rubExact(3_610_000)).toBe(`3${N}610${N}000${N}₽`);
  });
  it('formats rates, chances, deltas and terms', () => {
    expect(pct(0.19029)).toBe('19,0%');
    expect(pct(0.0163, 2)).toBe('1,63%');
    expect(chance(0.6263)).toBe('63%');
    expect(pp(1.234)).toBe('+1,2 п.п.');
    expect(pp(-0.7)).toBe('−0,7 п.п.');
    expect(pp(0.01)).toBe('0,0 п.п.');
    expect(months(12)).toBe(`12${N}мес.`);
  });
});
