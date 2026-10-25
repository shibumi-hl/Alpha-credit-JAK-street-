import { useState } from 'react';
import type { Evaluation } from '../lib/schemas';

const MINUS = '−';
const fmt = (v: number) => (Math.round(v) === 0 ? '0' : `${v > 0 ? '+' : MINUS}${Math.abs(Math.round(v))}`);

/** Вклад признаков в балл одобрения, бары от нуля (ТЗ §4.5). Клик — подсветить связанный рычаг. */
export function Contributions({ e, onPick }: { e: Evaluation; onPick(feature: string): void }) {
  const [all, setAll] = useState(false);
  const items = e.approval_explain.filter((x) => Math.abs(x.points) >= 0.5);
  const shown = all ? items : items.slice(0, 5);
  // самый длинный бар не должен сжать остальные в точки: шкала — по второму, длиннее обрезается со стрелкой
  const second = Math.abs(items[1]?.points ?? items[0]?.points ?? 1);
  const cap = Math.max(second * 1.6, 20);
  return (
    <section className="card" aria-labelledby="contrib-title">
      <div className="card-head">
        <h2 id="contrib-title" className="t-title">
          Почему такой шанс
        </h2>
        <span className="t-caption muted">баллы модели · +20 — шансы вдвое выше</span>
      </div>
      <div className="bars">
        {shown.map((x) => {
          const w = Math.min(Math.abs(x.points), cap) / cap;
          const clipped = Math.abs(x.points) > cap;
          const sign = x.points >= 0 ? '+' : '-';
          return (
            <div className="bar-row" key={x.feature}>
              <button type="button" className="t-label" onClick={() => onPick(x.feature)}>
                {x.label}: <span className="muted">{x.category_label}</span>
              </button>
              <div className="bar-track" aria-hidden>
                <span className="bar-zero" />
                <span className="bar" data-sign={sign} style={{ width: `${w * 50}%` }} />
                {clipped && (
                  <span className="bar-clip" style={sign === '+' ? { right: 0 } : { left: 0 }}>
                    {sign === '+' ? '›' : '‹'}
                  </span>
                )}
              </div>
              <span className="bar-value t-label">{fmt(x.points)}</span>
            </div>
          );
        })}
      </div>
      {items.length > 5 && (
        <button type="button" className="btn-text t-label" onClick={() => setAll(!all)}>
          {all ? 'Свернуть' : `Ещё ${items.length - 5}`}
        </button>
      )}
    </section>
  );
}
