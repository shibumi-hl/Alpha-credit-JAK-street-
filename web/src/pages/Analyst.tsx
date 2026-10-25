// Кабинет аналитика: очередь с фильтром статуса и карточка заявки с решением.
import { useState } from 'react';
import { chance, months, pct, rub } from '../lib/format';
import type { Application } from '../lib/schemas';
import { DecisionBlock, Journal, OfferCard, StatusChip, TurnBadge } from '../components/conveyor';
import { AppList } from './MyApplications';
import { useAct, useApplication } from './Tracker';

const FILTERS: [string, string][] = [
  ['ANALYST', 'У аналитика'],
  ['NEEDS_DATA', 'Нужны данные'],
  ['APPROVED', 'Одобрено'],
  ['COUNTER_OFFER', 'Контрпредложение'],
  ['REJECTED', 'Отказ'],
  ['ISSUED', 'Выдано'],
  ['', 'Все'],
];

export function Queue() {
  const [status, setStatus] = useState('ANALYST');
  return (
    <div className="stack">
      <h1 className="t-h1">Очередь заявок</h1>
      <div className="chips" role="group" aria-label="Статус">
        {FILTERS.map(([k, l]) => (
          <button key={k} type="button" className="chip t-label" aria-pressed={status === k} onClick={() => setStatus(k)}>
            {l}
          </button>
        ))}
      </div>
      <AppList status={status || undefined} base="/analyst" />
    </div>
  );
}

const DECISIONS: [string, string][] = [
  ['approve', 'Одобрить'],
  ['counter', 'Контрпредложение'],
  ['reject', 'Отказать'],
  ['request_info', 'Запросить данные'],
];

function factValue(f: { value: number | string | null; unit?: string | null }) {
  if (f.value == null) return '—';
  if (typeof f.value === 'string') return f.value;
  if (f.unit === 'rub') return rub(f.value);
  if (f.unit === 'pct') return pct(f.value, 0);
  if (f.unit === 'months') return months(f.value);
  if (f.unit === 'days') return `${f.value} дн.`;
  return String(f.value);
}

function Codes({ title, items }: { title: string; items: { code: string; category: string }[] }) {
  if (!items.length) return null;
  return (
    <>
      <div className="t-caption muted" style={{ marginTop: 12 }}>
        {title}
      </div>
      <ul className="plain-list t-label">
        {items.map((s) => (
          <li key={s.code}>{s.category}</li>
        ))}
      </ul>
    </>
  );
}

function Risk({ r }: { r: NonNullable<Application['risk']> }) {
  return (
    <section className="card" aria-label="Риск">
      <div className="t-title">Риск</div>
      <dl className="facts t-label">
        <div>
          <dt>PD</dt>
          <dd>{pct(r.pd, 1)}</dd>
        </div>
        <div>
          <dt>Класс риска</dt>
          <dd>{r.risk_class}</dd>
        </div>
        <div>
          <dt>Балл</dt>
          <dd>{Math.round(r.score)}</dd>
        </div>
        <div>
          <dt>Шанс одобрения</dt>
          <dd>{chance(r.approval_probability)}</dd>
        </div>
        <div>
          <dt>Лимит</dt>
          <dd>{rub(r.limit)}</dd>
        </div>
      </dl>
      {r.route_reason && <p className="t-label note-box">Причина маршрута: {r.route_reason}</p>}
      <Codes title="Стоп-факторы" items={r.stop_factors} />
      <Codes title="Причины" items={r.reasons} />
      {r.facts.length > 0 && (
        <table className="facts-table t-label">
          <tbody>
            {r.facts.map((f) => (
              <tr key={f.key}>
                <th scope="row">{f.label}</th>
                <td>{factValue(f)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Decide({ app }: { app: Application }) {
  const act = useAct(app.id);
  const [action, setAction] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [amount, setAmount] = useState(String(app.risk?.limit ?? app.levers.requested_amount));
  const options = DECISIONS.filter(([k]) => app.actions.includes(k));
  if (!options.length) return null;
  const amt = Number(amount.replace(/\s/g, ''));
  const ok = !!action && !!note.trim() && (action !== 'counter' || amt > 0);
  return (
    <form
      className="card stack"
      aria-label="Решение аналитика"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ok) return;
        act.mutate({ action: action!, note: note.trim(), ...(action === 'counter' ? { amount: amt } : {}) });
      }}
    >
      <div className="t-title">Решение</div>
      <div className="chips">
        {options.map(([k, l]) => (
          <button key={k} type="button" className="chip t-label" aria-pressed={action === k} onClick={() => setAction(k)}>
            {l}
          </button>
        ))}
      </div>
      {action === 'counter' && (
        <label className="t-label field">
          Сумма контрпредложения, ₽
          <input className="input" inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
      )}
      <label className="t-label field">
        Комментарий (обязательно)
        <textarea className="input" rows={3} required value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <button type="submit" className="btn btn-primary" disabled={!ok || act.isPending}>
        Отправить решение
      </button>
      {act.error && (
        <p className="lever-error t-label" role="alert">
          {act.error.message}
        </p>
      )}
    </form>
  );
}

export function Review({ id }: { id: string }) {
  const q = useApplication(id);
  if (q.error) return <div className="banner" role="alert">{q.error.message}</div>;
  if (!q.data) return <div className="card skeleton" style={{ height: 320 }} />;
  const a = q.data;
  const l = a.levers;
  return (
    <div className="stack">
      <a href="#/analyst" className="t-label">
        ← К очереди
      </a>
      <section className="card">
        <div className="row-between">
          <div>
            <div className="t-caption muted">ИНН {a.company.inn}</div>
            <h1 className="t-h1" style={{ margin: '4px 0' }}>
              {a.company.name}
            </h1>
          </div>
          <div className="chips">
            <StatusChip status={a.status} label={a.status_label} />
            <TurnBadge turn={a.whose_turn} />
          </div>
        </div>
        <p className="t-label">{a.next_step}</p>
        <dl className="facts t-label">
          <div>
            <dt>Продукт</dt>
            <dd>{a.product_label}</dd>
          </div>
          <div>
            <dt>Сумма</dt>
            <dd>{rub(l.requested_amount)}</dd>
          </div>
          <div>
            <dt>Срок</dt>
            <dd>{months(l.requested_term_m)}</dd>
          </div>
          <div>
            <dt>РКО, оборот</dt>
            <dd>{l.has_rko ? `${rub(l.bank_turnover_month_rub)} в мес.` : 'нет'}</dd>
          </div>
          <div>
            <dt>Гарантия</dt>
            <dd>{l.guarantee ? 'да' : 'нет'}</dd>
          </div>
          <div>
            <dt>Маркетплейс</dt>
            <dd>{l.marketplace ? 'да' : 'нет'}</dd>
          </div>
          <div>
            <dt>Цель</dt>
            <dd>{a.purpose}</dd>
          </div>
        </dl>
      </section>
      {a.risk && <Risk r={a.risk} />}
      {a.decision && <DecisionBlock d={a.decision} />}
      {a.offer && <OfferCard o={a.offer} />}
      <Decide key={a.status} app={a} />
      <Journal events={a.events} />
    </div>
  );
}
