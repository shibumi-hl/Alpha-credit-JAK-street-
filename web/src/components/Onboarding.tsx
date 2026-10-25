// Онбординг по ИНН: мок ЕГРЮЛ → карточка компании → песочница переключается на её персону.
import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { conveyor } from '../lib/api';
import type { PersonaCard } from '../lib/schemas';
import { date } from './conveyor';

export function Onboarding({ personas, onPick }: { personas: PersonaCard[] | undefined; onPick(id: string): void }) {
  const [inn, setInn] = useState('');
  const m = useMutation({ mutationFn: conveyor.company, onSuccess: (c) => onPick(c.persona_id) });
  const find = (v: string) => {
    setInn(v);
    if (v.trim()) m.mutate(v.trim());
  };
  const c = m.data;
  return (
    <section className="card onboarding" aria-label="Компания по ИНН">
      <form
        className="field"
        onSubmit={(e) => {
          e.preventDefault();
          find(inn);
        }}
      >
        <label className="t-title" htmlFor="inn">
          Введите ИНН компании
        </label>
        <div className="inn-row">
          <input
            id="inn"
            className="input"
            inputMode="numeric"
            maxLength={12}
            value={inn}
            aria-invalid={!!m.error}
            aria-describedby="inn-help"
            onChange={(e) => setInn(e.target.value.replace(/\D/g, ''))}
          />
          <button type="submit" className="btn btn-primary" disabled={!inn || m.isPending}>
            Найти
          </button>
        </div>
        {m.error ? (
          <p id="inn-help" className="lever-error t-label" role="alert">
            {m.error.message}
          </p>
        ) : (
          <p id="inn-help" className="t-caption muted">
            Демо-компании:{' '}
            {personas?.map((p, i) => (
              <span key={p.id}>
                {i > 0 && ', '}
                <button type="button" className="btn-text t-caption" onClick={() => find(p.inn)}>
                  {p.inn}
                </button>{' '}
                {p.name}
              </span>
            ))}
          </p>
        )}
      </form>
      {c && (
        <div className="company-card">
          <div className="t-title">{c.name}</div>
          <div className="t-caption muted">
            ИНН {c.inn}
            {c.ogrn && ` · ОГРН ${c.ogrn}`} · {c.status_label ?? c.status}
          </div>
          <dl className="facts t-label">
            <div>
              <dt>ОКВЭД</dt>
              <dd>
                {c.okved} {c.okved_name}
              </dd>
            </div>
            {c.registered && (
              <div>
                <dt>Зарегистрирована</dt>
                <dd>
                  {date(c.registered)} ({c.age_months} мес.)
                </dd>
              </div>
            )}
            {c.address && (
              <div>
                <dt>Адрес</dt>
                <dd>{c.address}</dd>
              </div>
            )}
          </dl>
          <p className="t-caption muted">Источники: {c.sources.map((s) => `${s.name} на ${date(s.asof)}`).join('; ')}</p>
        </div>
      )}
    </section>
  );
}
