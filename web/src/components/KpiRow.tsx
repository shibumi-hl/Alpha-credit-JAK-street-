import { useEffect, useRef, useState } from 'react';
import { at } from '../lib/curve';
import { chance, months, pct, pp, rub } from '../lib/format';
import type { Evaluation, Scenario, Simulation } from '../lib/schemas';
import { AnimatedNumber } from './AnimatedNumber';

interface Props {
  e: Evaluation;
  curve: Simulation | undefined;
  drag: number | null;
  ghost: Scenario | null;
  stale: boolean;
  revolving: boolean;
}

/** Шанс, ставка, платёж. Во время перетаскивания шанс и ставка — по точкам кривой, после — точные из расчёта. */
export function KpiRow({ e, curve, drag, ghost, stale, revolving }: Props) {
  const preview = drag != null && curve ? at(curve.points, drag) : null;
  const p = preview?.approval_probability ?? e.approval_probability;
  const rate = preview ? preview.rate : (e.pricing?.rate ?? null);
  const allIn = preview ? preview.all_in : (e.pricing?.all_in ?? null);
  const offered = preview ? preview.offered_amount : e.offered_amount;

  const [delta, setDelta] = useState<number | null>(null);
  const prev = useRef(e.approval_probability);
  useEffect(() => {
    const d = (e.approval_probability - prev.current) * 100;
    prev.current = e.approval_probability;
    if (Math.abs(d) < 0.5) return;
    setDelta(d);
    const t = setTimeout(() => setDelta(null), 2000);
    return () => clearTimeout(t);
  }, [e.approval_probability]);

  return (
    <section className="kpis" aria-label="Главные числа">
      <div className="card kpi" data-stale={stale}>
        <span className="t-label muted">Шанс одобрения</span>
        <div className="kpi-value">
          <span className="t-kpi">
            <AnimatedNumber value={p} format={chance} instant={drag != null} />
          </span>
          {delta != null && drag == null && (
            <span className="delta" data-sign={delta > 0 ? '+' : '-'}>
              {delta > 0 ? '▲' : '▼'} {pp(Math.abs(delta)).replace('+', '')}
            </span>
          )}
          {ghost && <span className="ghost-value">→ {chance(ghost.approval_probability)}</span>}
        </div>
        <span className="t-caption muted">{e.approval_mode === 'soft' ? 'предоценка без кредитной истории' : 'модель одобрения'}</span>
      </div>
      <div className="card kpi" data-stale={stale}>
        <span className="t-label muted">Ставка</span>
        <div className="kpi-value">
          <span className="t-kpi">{rate != null ? <AnimatedNumber value={rate} format={pct} instant={drag != null} /> : '—'}</span>
          {ghost?.rate != null && <span className="ghost-value">→ {pct(ghost.rate)}</span>}
        </div>
        <span className="t-caption muted">
          {rate != null && allIn != null ? `ПСК ${pct(allIn)} · на ${rub(offered)}` : 'нет предложения'}
        </span>
      </div>
      <div className="card kpi" data-stale={stale || drag != null}>
        <span className="t-label muted">Платёж в месяц</span>
        <div className="kpi-value">
          <span className="t-kpi">
            {e.monthly_payment != null ? <AnimatedNumber value={e.monthly_payment} format={rub} /> : '—'}
          </span>
        </div>
        <span className="t-caption muted">
          {e.monthly_payment != null ? (revolving ? 'при полном использовании лимита' : `на ${months(e.requested_term_m)}`) : 'нет предложения'}
        </span>
      </div>
    </section>
  );
}
