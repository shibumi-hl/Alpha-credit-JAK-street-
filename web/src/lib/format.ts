// Числа по-русски (DESIGN.md «Числа и текст»): десятичная запятая, неразрывный пробел перед ₽ и «мес.».
const N = ' ';
const MINUS = '−';
const sig3 = new Intl.NumberFormat('ru-RU', { maximumSignificantDigits: 3 });
const whole = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const fixed = (digits: number) =>
  new Intl.NumberFormat('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Сумма до трёх значащих цифр: «3,61 млн ₽», «333 тыс. ₽». */
export function rub(x: number): string {
  const a = Math.abs(x);
  if (a >= 1e9) return `${sig3.format(x / 1e9)}${N}млрд${N}₽`;
  if (a >= 1e6) return `${sig3.format(x / 1e6)}${N}млн${N}₽`;
  if (a >= 1e3) return `${sig3.format(x / 1e3)}${N}тыс.${N}₽`;
  return `${whole.format(x)}${N}₽`;
}

/** Точная сумма: «3 610 000 ₽». */
export function rubExact(x: number): string {
  return `${whole.format(x)}${N}₽`;
}

/** Доля → проценты с фиксированными знаками: 0.1903 → «19,0%». */
export function pct(x: number, digits = 1): string {
  return `${fixed(digits).format(x * 100)}%`;
}

/** Шанс одобрения — целые проценты. */
export function chance(x: number): string {
  return `${Math.round(x * 100)}%`;
}

/** Дельта в процентных пунктах со знаком: «+1,2 п.п.», «−0,7 п.п.». */
export function pp(x: number): string {
  const r = Math.round(x * 10) / 10;
  if (r === 0) return `${fixed(1).format(0)}${N}п.п.`;
  return `${r > 0 ? '+' : MINUS}${fixed(1).format(Math.abs(r))}${N}п.п.`;
}

export function months(n: number): string {
  return `${n}${N}мес.`;
}
