// Геометрия кривых по точкам /api/v1/simulate: логарифмическая ось суммы, интерполяция для перетаскивания без сети
// (ТЗ §4.4) и зоны исхода.
import type { Outcome, Point } from './schemas';

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export interface Axis {
  px(v: number): number;
  /** Пиксель → сумма, кратная step и в пределах оси. */
  amount(px: number, step: number): number;
}

export function logAxis(lo: number, hi: number, x0: number, x1: number): Axis {
  const a = Math.log(lo);
  const b = Math.log(hi);
  return {
    px: (v) => x0 + ((Math.log(v) - a) / (b - a)) * (x1 - x0),
    amount: (px, step) => {
      const t = clamp((px - x0) / (x1 - x0), 0, 1);
      return clamp(Math.round(Math.exp(a + t * (b - a)) / step) * step, lo, hi);
    },
  };
}

export function linearAxis(lo: number, hi: number, x0: number, x1: number): Axis {
  return {
    px: (v) => x0 + ((v - lo) / (hi - lo)) * (x1 - x0),
    amount: (px, step) => clamp(Math.round((lo + ((px - x0) / (x1 - x0)) * (hi - lo)) / step) * step, lo, hi),
  };
}

export type Kind = 'approve' | 'counter' | 'info' | 'no';

/** Зона точки: одобрим; другая сумма того же продукта; нужны документы; другой продукт или отказ. */
export function kindOf(p: { outcome: Outcome; offered_product: string }, product: string): Kind {
  if (p.outcome === 'APPROVE') return 'approve';
  if (p.outcome === 'COUNTER' && p.offered_product === product) return 'counter';
  if (p.outcome === 'REQUEST_INFO') return 'info';
  return 'no';
}

export interface Sample {
  approval_probability: number;
  rate_requested: number;
  outcome: Outcome;
  offered_amount: number;
  offered_product: string;
  rate: number | null;
  all_in: number | null;
}

/** Значения кривой в x: шанс и ставка — линейно по ln x между соседними точками, исход и предложение — у ближайшей. */
export function at(points: Point[], x: number, log = true): Sample {
  const f = log ? Math.log : (v: number) => v;
  const first = points[0];
  const last = points[points.length - 1];
  const v = clamp(x, first.x, last.x);
  let i = 0;
  while (i < points.length - 2 && points[i + 1].x < v) i++;
  const a = points[i];
  const b = points[i + 1] ?? a;
  const t = b.x === a.x ? 0 : (f(v) - f(a.x)) / (f(b.x) - f(a.x));
  const near = t < 0.5 ? a : b;
  return {
    approval_probability: a.approval_probability + t * (b.approval_probability - a.approval_probability),
    rate_requested: a.rate_requested + t * (b.rate_requested - a.rate_requested),
    outcome: near.outcome,
    offered_amount: near.offered_amount,
    offered_product: near.offered_product,
    rate: near.rate,
    all_in: near.all_in,
  };
}

export interface Zone {
  from: number;
  to: number;
  kind: Kind;
}

/** Полосы исхода по оси X; граница — посередине (на логарифмической оси) между точками с разным исходом. */
export function zones(points: Point[], product: string, log = true): Zone[] {
  const mid = (a: number, b: number) => (log ? Math.sqrt(a * b) : (a + b) / 2);
  const out: Zone[] = [];
  points.forEach((p, i) => {
    const kind = kindOf(p, product);
    const cur = out[out.length - 1];
    if (cur && cur.kind === kind) {
      cur.to = p.x;
      return;
    }
    const edge = i === 0 ? p.x : mid(points[i - 1].x, p.x);
    if (cur) cur.to = edge;
    out.push({ from: edge, to: p.x, kind });
  });
  return out;
}
