import { CheckCircle2, Compass, FileText, Scale } from 'lucide-react';
import { decision, type Action } from '../lib/decision';
import type { Evaluation, Meta } from '../lib/schemas';
import { Igor } from './Igor';

const ICON = { approve: CheckCircle2, counter: Scale, info: FileText, reject: Compass };

interface Props {
  e: Evaluation;
  meta: Meta | undefined;
  hint: string;
  thinking: boolean;
  notice: string | null;
  onAction(a: Action): void;
}

/** Блок решения с ИИгорем: что ответит банк, почему и что сделать дальше (DESIGN.md «Блок решения»). */
export function DecisionCard({ e, meta, hint, thinking, notice, onAction }: Props) {
  const d = decision(e, meta);
  const Icon = ICON[d.tone];
  return (
    <section className="card decision" aria-labelledby="decision-title" aria-live="polite">
      <Igor thinking={thinking} outcome={`${e.outcome}:${e.offered_amount}`} />
      <div className="decision-body">
        <div>
          <span className="badge" data-tone={d.tone}>
            <Icon size={16} strokeWidth={1.75} aria-hidden />
            {d.badge}
          </span>
        </div>
        <h1 id="decision-title" className="t-h1">
          {d.headline}
        </h1>
        {d.reasons.length > 0 && (
          <ul className="decision-reasons">
            {d.reasons.map((r) => (
              <li key={r}>{r.replace(/^./, (c) => c.toUpperCase())}</li>
            ))}
          </ul>
        )}
        <p className="igor-says" style={{ margin: 0 }}>
          <span className="visually-hidden">ИИгорь: </span>
          {hint}
        </p>
        <div className="actions">
          {d.actions.map((a) => (
            <button
              key={a.label}
              type="button"
              className={`btn ${a.kind === 'submit' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => onAction(a)}
            >
              {a.label}
            </button>
          ))}
        </div>
        {notice && (
          <p className="notice t-label" role="status" style={{ margin: 0 }}>
            {notice}
          </p>
        )}
        <p className="t-caption muted" style={{ margin: 0 }}>
          Предварительная оценка, не решение банка
          {e.approval_mode === 'soft' && ` · без данных: ${e.approval_imputed_labels.join(', ').toLowerCase()}`}
        </p>
      </div>
    </section>
  );
}
