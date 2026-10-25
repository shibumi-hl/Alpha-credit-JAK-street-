// Трекер заявки клиента: шаги, чей ход, решение, предложение, действия строго из Application.actions, журнал.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { conveyor, type ActionBody } from '../lib/api';
import type { Application } from '../lib/schemas';
import { DecisionBlock, Journal, LoanCard, OfferCard, StatusChip, Steps, TurnBadge } from '../components/conveyor';

export function useApplication(id: string) {
  return useQuery({
    queryKey: ['application', id],
    queryFn: () => conveyor.get(id),
    refetchInterval: (q) => (q.state.data?.whose_turn === 'bank' ? 1000 : false),
  });
}

export function useAct(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: ActionBody) => conveyor.act(id, b),
    onSuccess: (app) => {
      qc.setQueryData(['application', id], app);
      qc.invalidateQueries({ queryKey: ['applications'] });
    },
  });
}

function Uploads({ docs, busy, onSend }: { docs: Application['documents']; busy: boolean; onSend(): void }) {
  const [done, setDone] = useState<Set<string>>(() => new Set(docs.filter((d) => d.status === 'uploaded').map((d) => d.name)));
  const all = docs.every((d) => done.has(d.name));
  return (
    <div className="action-block">
      <div className="t-title">Документы</div>
      <ul className="doc-list">
        {docs.map((d) => (
          <li key={d.name} className="t-label">
            <span>{d.name}</span>
            {done.has(d.name) ? (
              <span className="muted t-caption">Загружено</span>
            ) : (
              <button type="button" className="btn btn-secondary t-label" onClick={() => setDone(new Set(done).add(d.name))}>
                Загрузить
              </button>
            )}
          </li>
        ))}
      </ul>
      <button type="button" className="btn btn-primary" disabled={!all || busy} onClick={onSend}>
        Отправить документы
      </button>
    </div>
  );
}

function Sign({ code, busy, onSign }: { code: string | null | undefined; busy: boolean; onSign(c: string): void }) {
  const [v, setV] = useState('');
  return (
    <form
      className="action-block"
      onSubmit={(e) => {
        e.preventDefault();
        onSign(v.trim());
      }}
    >
      <div className="t-title">Подписание</div>
      {code && <p className="t-label">Код подписи: <b>{code}</b></p>}
      <label className="t-caption muted" htmlFor="sign-code">
        Введите код, чтобы подписать договор простой электронной подписью
      </label>
      <input id="sign-code" className="input" inputMode="numeric" autoComplete="one-time-code" value={v} onChange={(e) => setV(e.target.value)} />
      <button type="submit" className="btn btn-primary" disabled={!v.trim() || busy}>
        Подписать
      </button>
    </form>
  );
}

export function TrackerView({ app, busy, error, onAct }: { app: Application; busy: boolean; error?: string | null; onAct(b: ActionBody): void }) {
  const a = new Set(app.actions);
  return (
    <div className="stack">
      <section className="card">
        <div className="row-between">
          <div>
            <div className="t-caption muted">
              {app.company.name} · {app.product_label}
            </div>
            <h1 className="t-h1" style={{ margin: '4px 0' }}>
              {app.status_label}
            </h1>
          </div>
          <div className="chips">
            <StatusChip status={app.status} label={app.status_label} />
            <TurnBadge turn={app.whose_turn} />
          </div>
        </div>
        <p className="t-label" style={{ margin: '8px 0 16px' }}>
          {app.next_step}
        </p>
        <Steps steps={app.steps} />
      </section>
      {app.loan && <LoanCard l={app.loan} />}
      {app.decision && <DecisionBlock d={app.decision} />}
      {app.offer && !app.loan && <OfferCard o={app.offer} />}
      {app.actions.length > 0 && (
        <section className="card stack" aria-label="Действия">
          {a.has('upload_documents') && (
            <Uploads docs={app.documents} busy={busy} onSend={() => onAct({ action: 'upload_documents' })} />
          )}
          {a.has('accept_offer') && (
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => onAct({ action: 'accept_offer' })}>
              Принять предложение
            </button>
          )}
          {a.has('sign') && <Sign code={app.sign_code} busy={busy} onSign={(code) => onAct({ action: 'sign', code })} />}
          {a.has('withdraw') && (
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => onAct({ action: 'withdraw' })}>
              Отозвать заявку
            </button>
          )}
          {error && (
            <p className="lever-error t-label" role="alert">
              {error}
            </p>
          )}
        </section>
      )}
      <Journal events={app.events} />
    </div>
  );
}

export function Tracker({ id }: { id: string }) {
  const q = useApplication(id);
  const act = useAct(id);
  if (q.error) return <div className="banner" role="alert">{q.error.message}</div>;
  if (!q.data) return <div className="card skeleton" style={{ height: 320 }} />;
  return <TrackerView app={q.data} busy={act.isPending} error={act.error?.message} onAct={(b) => act.mutate(b)} />;
}
