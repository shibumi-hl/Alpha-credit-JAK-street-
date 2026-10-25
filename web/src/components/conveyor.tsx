// Общие блоки конвейера: статус-чип, шаги, решение, предложение, кредит, журнал.
import { months, pct, rub, rubExact } from '../lib/format';
import type { Application } from '../lib/schemas';

export const ACTOR: Record<string, string> = { client: 'Клиент', system: 'Система', analyst: 'Аналитик' };

const TONE: Record<string, string> = {
  APPROVED: 'approve',
  ISSUED: 'approve',
  SIGNING: 'approve',
  COUNTER_OFFER: 'counter',
  NEEDS_DATA: 'info',
  ANALYST: 'info',
  REJECTED: 'reject',
  WITHDRAWN: 'reject',
};

export function StatusChip({ status, label }: { status: string; label: string }) {
  return (
    <span className="status-chip t-caption" data-tone={TONE[status] ?? 'neutral'}>
      {label}
    </span>
  );
}

export function TurnBadge({ turn }: { turn: Application['whose_turn'] }) {
  if (!turn) return null;
  return (
    <span className="turn-badge t-caption" data-turn={turn}>
      {turn === 'client' ? 'Ваш ход' : 'Ход банка'}
    </span>
  );
}

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
export const date = (iso: string) => new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
const rate = (x: number | null) => (x == null ? '—' : pct(x, 1));
const pay = (x: number | null) => (x == null ? '—' : rubExact(Math.round(x)));

export function Steps({ steps }: { steps: Application['steps'] }) {
  return (
    <ol className="steps">
      {steps.map((s) => (
        <li key={s.status} data-state={s.state} className="t-label" aria-current={s.state === 'current' ? 'step' : undefined}>
          <span className="step-dot" aria-hidden />
          {s.label}
        </li>
      ))}
    </ol>
  );
}

export function DecisionBlock({ d }: { d: NonNullable<Application['decision']> }) {
  return (
    <section className="card" aria-label="Решение">
      <div className="t-caption muted">Решение · {d.by === 'analyst' ? 'аналитик' : 'система'}</div>
      <div className="t-h2" style={{ margin: '4px 0 8px' }}>
        {d.title}
      </div>
      {d.reasons.length > 0 && (
        <ul className="plain-list t-label">
          {d.reasons.map((r) => (
            <li key={r.code}>{r.category}</li>
          ))}
        </ul>
      )}
      {d.requests.length > 0 && (
        <>
          <div className="t-caption muted" style={{ marginTop: 12 }}>
            Что нужно от вас
          </div>
          <ul className="plain-list t-label">
            {d.requests.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </>
      )}
      {d.note && <p className="t-label note-box">Комментарий аналитика: {d.note}</p>}
    </section>
  );
}

export function OfferCard({ o }: { o: NonNullable<Application['offer']> }) {
  return (
    <section className="card" aria-label="Предложение банка">
      <div className="t-caption muted">Предложение · {o.product_label}</div>
      <dl className="facts t-label">
        <div>
          <dt>Сумма</dt>
          <dd>{rub(o.amount)}</dd>
        </div>
        <div>
          <dt>Срок</dt>
          <dd>{months(o.term_m)}</dd>
        </div>
        <div>
          <dt>Ставка</dt>
          <dd>{rate(o.rate)}</dd>
        </div>
        <div>
          <dt>ПСК</dt>
          <dd>{rate(o.all_in)}</dd>
        </div>
        <div>
          <dt>Платёж в месяц</dt>
          <dd>{pay(o.monthly_payment)}</dd>
        </div>
      </dl>
    </section>
  );
}

export function LoanCard({ l }: { l: NonNullable<Application['loan']> }) {
  return (
    <section className="card loan-card" aria-label="Кредит">
      <div className="t-caption muted">Кредит выдан {date(l.issued_at)}</div>
      <div className="t-h2" style={{ margin: '4px 0 8px' }}>
        {rubExact(l.amount)}
      </div>
      <dl className="facts t-label">
        <div>
          <dt>Номер договора</dt>
          <dd>{l.number}</dd>
        </div>
        <div>
          <dt>Счёт зачисления</dt>
          <dd>{l.account}</dd>
        </div>
        <div>
          <dt>Срок</dt>
          <dd>{months(l.term_m)}</dd>
        </div>
        <div>
          <dt>Ставка</dt>
          <dd>{rate(l.rate)}</dd>
        </div>
        <div>
          <dt>Платёж в месяц</dt>
          <dd>{pay(l.monthly_payment)}</dd>
        </div>
      </dl>
    </section>
  );
}

export function Journal({ events }: { events: Application['events'] }) {
  return (
    <section className="card" aria-label="Журнал">
      <div className="t-title">Журнал</div>
      <ol className="journal">
        {events.map((e, i) => (
          <li key={i} className="t-label">
            <time className="muted t-caption">{dateTime(e.at)}</time>
            <span>
              <b>{e.to_label}</b> · {ACTOR[e.actor] ?? e.actor}
              {e.note && <span className="muted"> — {e.note}</span>}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
