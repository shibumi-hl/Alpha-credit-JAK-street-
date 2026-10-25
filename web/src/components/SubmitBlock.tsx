// Подтверждение подачи: цель и согласие на запрос в БКИ, POST с Idempotency-Key, переход в трекер.
import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { conveyor } from '../lib/api';
import { go } from '../lib/route';
import type { Levers } from '../lib/schemas';

interface Props {
  personaId: string;
  levers: Levers;
  story: string;
  onConsent(): void;
  onClose(): void;
}

// randomUUID есть только в защищённом контексте (HTTPS, localhost); по HTTP на IP стенда — getRandomValues
function idempotencyKey(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('');
}

export function SubmitBlock({ personaId, levers, story, onConsent, onClose }: Props) {
  const [purpose, setPurpose] = useState(story);
  const [consent, setConsent] = useState(!!levers.bki_consent);
  const [key] = useState(idempotencyKey); // один ключ на форму: повторное нажатие не создаёт вторую заявку
  const m = useMutation({
    mutationFn: () => conveyor.submit({ persona_id: personaId, levers: { ...levers, bki_consent: true }, purpose: purpose.trim(), bki_consent: true }, key),
    onSuccess: (a) => go(`/applications/${a.id}`),
  });
  return (
    <form
      className="card submit-block stack"
      aria-label="Подача заявки"
      onSubmit={(e) => {
        e.preventDefault();
        if (consent && purpose.trim()) m.mutate();
      }}
    >
      <div className="t-title">Подать заявку</div>
      <label className="t-label field">
        Цель кредита
        <input className="input" value={purpose} onChange={(e) => setPurpose(e.target.value)} required />
      </label>
      <label className="t-label check">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => {
            setConsent(e.target.checked);
            if (e.target.checked && !levers.bki_consent) onConsent();
          }}
        />
        Согласен на запрос в бюро кредитных историй
      </label>
      {m.error && (
        <p className="lever-error t-label" role="alert">
          {m.error.message}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={!consent || !purpose.trim() || m.isPending}>
          Отправить в банк
        </button>
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          Отмена
        </button>
      </div>
    </form>
  );
}
