import { useState } from 'react';
import { pp, rub } from '../lib/format';
import { scenarioOrder } from '../lib/hints';
import type { Evaluation, Scenario, WhatIf as WhatIfData } from '../lib/schemas';

export const SCENARIO_MIME = 'application/x-alfa-scenario';

function outcomeShort(s: Scenario): string {
  if (s.outcome === 'APPROVE') return `Одобрим ${rub(s.offered_amount)}`;
  if (s.outcome === 'COUNTER') return `Можем выдать ${rub(s.offered_amount)}`;
  if (s.outcome === 'REQUEST_INFO') return 'Нужны документы';
  return 'Не сможем';
}

/** «Что если» (ТЗ §4.7): наведение — призрак, «Применить» или перетаскивание в условия — сценарий в заявку. */
export function WhatIf({ w, base, onHover, onApply }: { w: WhatIfData | undefined; base: Evaluation; onHover(s: Scenario | null): void; onApply(s: Scenario): void }) {
  const [dragging, setDragging] = useState<string | null>(null);
  const list = [...(w?.scenarios ?? [])].sort(scenarioOrder);
  return (
    <section className="card" id="whatif" aria-labelledby="whatif-title">
      <div className="card-head">
        <h2 id="whatif-title" className="t-title">
          Что если
        </h2>
        <span className="t-caption muted">наведите — увидите на графиках, перетащите в условия — применится</span>
      </div>
      {!w ? (
        <div className="skeleton" style={{ height: 120 }} />
      ) : !list.length ? (
        <p className="muted" style={{ margin: 0 }}>
          Для этой заявки сценариев нет.
        </p>
      ) : (
        <div className="scenarios">
          {list.map((s) => {
            const changed = s.outcome !== base.outcome || s.offered_amount !== base.offered_amount;
            return (
              <article
                key={s.key}
                className="scenario"
                draggable
                data-dragging={dragging === s.key}
                onDragStart={(e) => {
                  e.dataTransfer.setData(SCENARIO_MIME, s.key);
                  e.dataTransfer.effectAllowed = 'copy';
                  setDragging(s.key);
                }}
                onDragEnd={() => setDragging(null)}
                onMouseEnter={() => onHover(s)}
                onMouseLeave={() => onHover(null)}
                onFocus={() => onHover(s)}
                onBlur={() => onHover(null)}
                aria-label={s.title}
              >
                <h3 className="t-title" style={{ fontSize: 15, lineHeight: '20px' }}>
                  {s.title}
                </h3>
                <p className="t-label" style={{ margin: 0 }}>
                  Шанс <Delta v={s.delta_approval_pp} good={1} />
                  {s.delta_rate_pp != null && Math.abs(s.delta_rate_pp) >= 0.05 && (
                    <>
                      {' · ставка '}
                      <Delta v={s.delta_rate_pp} good={-1} />
                    </>
                  )}
                </p>
                {changed && <p className="t-label muted" style={{ margin: 0 }}>→ {outcomeShort(s)}</p>}
                <button type="button" className="btn btn-secondary t-label" style={{ minHeight: 40, justifySelf: 'start' }} onClick={() => onApply(s)}>
                  Применить
                </button>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function Delta({ v, good }: { v: number; good: 1 | -1 }) {
  const r = Math.round(v * 10) / 10;
  if (r === 0) return <span className="muted">без изменений</span>;
  const better = Math.sign(r) === good;
  return (
    <span style={{ color: better ? 'var(--plus)' : 'var(--minus)', fontWeight: 600 }}>
      {r > 0 ? '▲' : '▼'} {pp(Math.abs(r)).replace('+', '')}
    </span>
  );
}
