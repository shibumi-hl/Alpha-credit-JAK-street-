import { pct } from '../lib/format';
import type { Pricing } from '../lib/schemas';

const PARTS: [keyof Pricing, string][] = [
  ['funding', 'Фондирование: G-кривая Мосбиржи + спред'],
  ['el', 'Ожидаемые потери PD × LGD'],
  ['capital', 'Капитал по ПВР (845-П)'],
  ['opex', 'Расходы'],
  ['margin', 'Маржа'],
];

/** Из чего ставка: слагаемые → скидки → ставка → хвост до ПСК (ТЗ §4.6). */
export function RateWaterfall({ p, note }: { p: Pricing | null; note: string }) {
  return (
    <section className="card" aria-labelledby="fall-title">
      <div className="card-head">
        <h2 id="fall-title" className="t-title">
          Из чего ставка
        </h2>
        {p?.curve_date && <span className="t-caption muted">G-кривая на {new Date(p.curve_date).toLocaleDateString('ru-RU')}</span>}
      </div>
      {!p ? (
        <p className="muted" style={{ margin: 0 }}>
          Ставку покажем, когда будет предложение.
        </p>
      ) : (
        <Fall p={p} />
      )}
      <p className="t-caption muted" style={{ margin: '12px 0 0' }}>
        {note}
      </p>
    </section>
  );
}

function Fall({ p }: { p: Pricing }) {
  const total = Math.max(p.all_in ?? p.rate, p.rate + p.discounts);
  const x = (v: number) => `${(v / total) * 100}%`;
  let acc = 0;
  const rows = PARTS.map(([k, label]) => {
    const v = p[k] as number;
    const row = { label, from: acc, v, kind: 'part' };
    acc += v;
    return row;
  });
  rows.push({ label: 'Скидки', from: acc - p.discounts, v: p.discounts, kind: 'discount' });
  rows.push({ label: 'Ставка', from: 0, v: p.rate, kind: 'total' });
  if (p.all_in != null) rows.push({ label: 'ПСК: + комиссия и страховка', from: p.rate, v: p.all_in - p.rate, kind: 'psk' });
  return (
    <div className="fall">
      {rows.map((r) => (
        <div className="fall-row" key={r.label}>
          <span className={r.kind === 'total' ? 't-label' : 't-caption'} style={r.kind === 'total' ? { fontWeight: 600 } : undefined}>
            {r.label}
          </span>
          <div className="fall-track" aria-hidden>
            <span className="fall-step" data-kind={r.kind} style={{ left: x(r.from), width: x(Math.max(r.v, 0.0004)) }} />
          </div>
          <span className="t-label" style={{ textAlign: 'right' }}>
            {r.kind === 'discount' ? `−${pct(r.v, 2)}` : r.kind === 'psk' ? pct(p.all_in!, 1) : pct(r.v, r.kind === 'total' ? 1 : 2)}
          </span>
        </div>
      ))}
    </div>
  );
}
