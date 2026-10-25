import { motion } from 'motion/react';
import { useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { at, logAxis, zones, type Kind } from '../lib/curve';
import { chance, pct, rub } from '../lib/format';
import type { Point, Simulation } from '../lib/schemas';

const H = 220;
const M = { l: 44, r: 14, t: 26, b: 26 };
const SAMPLES = 96; // кривая пересэмплирована на постоянную сетку — путь плавно меняет форму при новом ответе
const TICKS = [1e5, 3e5, 1e6, 3e6, 1e7, 3e7, 1e8, 3e8];
const ZONE: Record<Kind, [string, string]> = {
  approve: ['var(--zone-approve)', 'Одобрим'],
  counter: ['var(--zone-counter)', 'Другая сумма'],
  info: ['var(--zone-info)', 'Нужны документы'],
  no: ['var(--zone-no)', 'Другой продукт или отказ'],
};

interface Props {
  metric: 'approval' | 'rate';
  curve: Simulation | undefined;
  ghost: Simulation | undefined;
  product: string;
  amount: number;
  drag: number | null;
  step: number;
  onDrag(v: number | null): void;
  onCommit(v: number): void;
}

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(260, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

/** Кривая шанса или ставки от суммы (ТЗ §4.4): зоны исхода, лимит с кодом, точка-ползунок, призрак сценария. */
export function CurveCard({ metric, curve, ghost, product, amount, drag, step, onDrag, onCommit }: Props) {
  const [box, w] = useWidth();
  const [table, setTable] = useState(false);
  const [local, setLocal] = useState<number | null>(null);
  const pts = curve?.points ?? [];
  const lo = pts[0]?.x ?? 1;
  const hi = pts[pts.length - 1]?.x ?? 2;
  const ax = logAxis(lo, hi, M.l, w - M.r);
  const val = (p: { approval_probability: number; rate_requested: number }) =>
    metric === 'approval' ? p.approval_probability : p.rate_requested;

  const [y0, y1] = useMemo(() => {
    if (metric === 'approval' || !pts.length) return [0, 1];
    const vs = pts.flatMap((p) => [p.rate_requested, ...(p.all_in != null && p.offered_amount === p.x && p.offered_product === product ? [p.all_in] : [])]);
    return [Math.floor(Math.min(...vs) * 100 - 1) / 100, Math.ceil(Math.max(...vs) * 100 + 1) / 100];
  }, [metric, pts, product]);
  const py = (v: number) => M.t + (1 - (v - y0) / (y1 - y0)) * (H - M.t - M.b);

  const path = (points: Point[]) => {
    if (points.length < 2) return '';
    const a = Math.log(points[0].x);
    const b = Math.log(points[points.length - 1].x);
    let d = '';
    for (let i = 0; i < SAMPLES; i++) {
      const x = Math.exp(a + ((b - a) * i) / (SAMPLES - 1));
      d += `${i ? 'L' : 'M'}${ax.px(x).toFixed(1)},${py(val(at(points, x))).toFixed(1)}`;
    }
    return d;
  };
  const psk = useMemo(() => {
    if (metric !== 'rate') return '';
    let d = '';
    let open = false;
    for (const p of pts) {
      const ok = p.all_in != null && p.offered_amount === p.x && p.offered_product === product; // ПСК только своего продукта
      if (ok) d += `${open ? 'L' : 'M'}${ax.px(p.x).toFixed(1)},${py(p.all_in!).toFixed(1)}`;
      open = ok;
    }
    return d;
  }, [metric, pts, w, y0, y1, product]);

  const cur = local ?? drag ?? amount;
  const inRange = pts.length > 1 && cur >= lo && cur <= hi;
  const sample = inRange ? at(pts, cur) : null;
  const dragging = local != null;

  const fromEvent = (e: PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return ax.amount(((e.clientX - r.left) / r.width) * w, step);
  };
  const move = (v: number) => {
    setLocal(v);
    onDrag(v);
  };
  const end = () => {
    if (local != null) onCommit(local);
    setLocal(null);
    onDrag(null);
  };
  const key = (e: KeyboardEvent) => {
    const dx = (e.shiftKey ? 40 : 8) * (e.key === 'ArrowRight' || e.key === 'ArrowUp' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -1 : 0);
    if (!dx) return;
    e.preventDefault();
    onCommit(ax.amount(ax.px(amount) + dx, step));
  };

  const title = metric === 'approval' ? 'Шанс одобрения от суммы' : 'Ставка и ПСК от суммы';
  const color = metric === 'approval' ? 'var(--approval)' : 'var(--rate)';
  const zs = pts.length ? zones(pts, product) : [];
  const kinds = [...new Set(zs.map((z) => z.kind))];
  const showLimit = curve && curve.limit > lo && curve.limit < hi;
  const yTicks = metric === 'approval' ? [0, 0.25, 0.5, 0.75, 1] : [y0, (y0 + y1) / 2, y1];

  return (
    <section className="card" aria-labelledby={`curve-${metric}`}>
      <div className="card-head">
        <h2 id={`curve-${metric}`} className="t-title">
          {title}
        </h2>
        <button type="button" className="btn-text t-label" aria-pressed={table} onClick={() => setTable(!table)}>
          {table ? 'Графиком' : 'Таблицей'}
        </button>
      </div>
      <div ref={box}>
        {!pts.length ? (
          <div className="skeleton" style={{ height: H }} />
        ) : table ? (
          <CurveTable points={pts} />
        ) : (
          <svg
            className="chart"
            viewBox={`0 0 ${w} ${H}`}
            height={H}
            data-dragging={dragging}
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              move(fromEvent(e));
            }}
            onPointerMove={(e) => dragging && move(fromEvent(e))}
            onPointerUp={end}
            onPointerCancel={end}
            role="img"
            aria-label={`${title}: от ${rub(lo)} до ${rub(hi)}`}
          >
            {zs.map((z, i) => (
              <rect key={i} x={ax.px(z.from)} y={M.t} width={Math.max(0, ax.px(z.to) - ax.px(z.from))} height={H - M.t - M.b} fill={ZONE[z.kind][0]} />
            ))}
            <g className="grid axis">
              {yTicks.map((t) => (
                <g key={t}>
                  <line x1={M.l} x2={w - M.r} y1={py(t)} y2={py(t)} />
                  <text x={M.l - 6} y={py(t) + 4} textAnchor="end">
                    {metric === 'approval' ? chance(t) : pct(t, 0)}
                  </text>
                </g>
              ))}
              {TICKS.filter((t) => t > lo * 1.1 && t < hi / 1.1).map((t) => (
                <text key={t} x={ax.px(t)} y={H - 8} textAnchor="middle">
                  {rub(t).replace(/ ₽$/, '')}
                </text>
              ))}
            </g>
            {showLimit && (
              <g>
                <line x1={ax.px(curve!.limit)} x2={ax.px(curve!.limit)} y1={M.t - 4} y2={H - M.b} stroke="var(--ink)" strokeWidth={1.5} strokeDasharray="4 4" />
                <text className="limit-chip" x={Math.min(ax.px(curve!.limit) + 6, w - M.r - 150)} y={M.t - 10} fill="var(--ink)">
                  Лимит {rub(curve!.limit)}
                  {curve!.binding ? ` · ${curve!.binding}` : ''}
                </text>
              </g>
            )}
            {ghost && ghost.points.length > 1 && (
              <motion.path d={path(ghost.points)} fill="none" stroke={color} strokeWidth={2} strokeDasharray="6 5" initial={{ opacity: 0 }} animate={{ opacity: 0.45 }} transition={{ duration: 0.15 }} />
            )}
            <motion.path d={path(pts)} initial={false} animate={{ d: path(pts) }} transition={{ duration: 0.26, ease: [0.2, 0, 0, 1] }} fill="none" stroke={color} strokeWidth={2.5} strokeLinejoin="round" />
            {psk && <path d={psk} fill="none" stroke={color} strokeWidth={2} strokeDasharray="3 4" opacity={0.8} />}
            {sample && (
              <circle
                className="dot"
                cx={ax.px(cur)}
                cy={py(val(sample))}
                r={6}
                fill={color}
                stroke="var(--bg)"
                strokeWidth={3}
                tabIndex={0}
                role="slider"
                aria-label={`Сумма на графике «${title}»`}
                aria-valuemin={lo}
                aria-valuemax={hi}
                aria-valuenow={cur}
                aria-valuetext={`${rub(cur)}: ${metric === 'approval' ? `шанс ${chance(sample.approval_probability)}` : `ставка ${pct(sample.rate_requested)}`}`}
                onKeyDown={key}
              />
            )}
          </svg>
        )}
      </div>
      <div className="legend t-caption muted">
        {kinds.map((k) => (
          <span key={k}>
            <i style={{ background: ZONE[k][0], outline: '1px solid var(--line)' }} />
            {ZONE[k][1]}
          </span>
        ))}
        {metric === 'rate' && <span>пунктир — ПСК</span>}
      </div>
    </section>
  );
}

function CurveTable({ points }: { points: Point[] }) {
  return (
    <table className="table-view">
      <thead>
        <tr>
          <th>Сумма</th>
          <th>Шанс</th>
          <th>Ставка</th>
          <th>Предложение</th>
        </tr>
      </thead>
      <tbody>
        {points.map((p) => (
          <tr key={p.x}>
            <td>{rub(p.x)}</td>
            <td>{chance(p.approval_probability)}</td>
            <td>{pct(p.rate_requested)}</td>
            <td>{p.offered_amount ? rub(p.offered_amount) : '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
