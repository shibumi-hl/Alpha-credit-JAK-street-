import { Lock, Pause, Play } from 'lucide-react';
import { months, rub } from '../lib/format';
import type { Evaluation, Levers, Meta } from '../lib/schemas';
import { AmountSlider } from './AmountSlider';

const TERMS = [6, 12, 18, 24, 36];
const cap = (s: string) => s.replace(/^./, (c) => c.toUpperCase());

interface Props {
  meta: Meta;
  levers: Levers;
  e: Evaluation | undefined;
  okved: string;
  range: [number, number];
  drag: number | null;
  playing: boolean;
  onSet(change: Partial<Levers>, label: string): void;
  onProduct(product: string): void;
  onDrag(v: number | null): void;
  onPlay(): void;
}

function YesNo({ id, label, value, disabled, onChange }: { id: string; label: string; value: boolean; disabled?: boolean; onChange(v: boolean): void }) {
  return (
    <div className="lever-row" id={id}>
      <span className="t-label">{label}</span>
      <span className="segment" role="group" aria-label={label}>
        {[false, true].map((v) => (
          <button
            key={String(v)}
            type="button"
            className="chip"
            aria-pressed={value === v}
            aria-label={`${label}: ${v ? 'да' : 'нет'}`}
            disabled={disabled}
            onClick={() => value !== v && onChange(v)}
          >
            {v ? 'да' : 'нет'}
          </button>
        ))}
      </span>
    </div>
  );
}

/** Рычаги заявки (ТЗ §4.2): то, что клиент может поменять сам. Факты компании здесь не меняются. */
export function LeversPanel({ meta, levers, e, okved, range, drag, playing, onSet, onProduct, onDrag, onPlay }: Props) {
  const product = meta.products.find((p) => p.product === levers.product)!;
  const avail = new Map(e?.products.map((p) => [p.product, p]) ?? []);
  const trade = /^4[5-7]/.test(okved); // раздел G: торговля — данные маркетплейса имеют смысл
  const secured = levers.product === 'secured';
  const amount = drag ?? levers.requested_amount;
  const [lo, hi] = [Math.max(range[0], product.min_amount), Math.min(range[1], product.max_amount)];
  const turnoverMax = Math.max(1_000_000, Math.ceil((levers.requested_amount * 3) / 1e6) * 1e6);
  return (
    <div className="card" aria-labelledby="levers-title">
      <h2 id="levers-title" className="t-title" style={{ marginBottom: 12 }}>
        Условия
      </h2>

      <div className="lever" id="lever-product">
        <span className="t-label muted">Продукт</span>
        <div className="chips">
          {meta.products.map((p) => {
            const a = avail.get(p.product);
            const locked = a ? !a.available : false;
            const why = a?.reasons.map((r) => r.category).join('; ');
            return (
              <button
                key={p.product}
                type="button"
                className="chip"
                aria-pressed={levers.product === p.product}
                data-locked={locked}
                aria-describedby={locked ? `why-${p.product}` : undefined}
                title={locked ? cap(why ?? '') : undefined}
                onClick={() => levers.product !== p.product && onProduct(p.product)}
              >
                {locked && <Lock size={14} strokeWidth={1.75} aria-hidden />}
                {cap(p.label)}
                {locked && (
                  <span id={`why-${p.product}`} className="visually-hidden">
                    {why}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div className="lever" id="lever-amount">
        <div className="lever-row">
          <span className="t-label muted">Сумма</span>
          <span className="t-title">{rub(amount)}</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '40px minmax(0,1fr)', gap: 12, alignItems: 'start' }}>
          <button
            type="button"
            className="btn btn-secondary btn-icon"
            aria-label={playing ? 'Остановить развёртку суммы' : 'Проиграть развёртку суммы'}
            onClick={onPlay}
          >
            {playing ? <Pause size={18} aria-hidden /> : <Play size={18} aria-hidden />}
          </button>
          <AmountSlider
            id="amount-slider"
            label="Сумма"
            min={lo}
            max={hi}
            value={Math.min(hi, Math.max(lo, levers.requested_amount))}
            step={meta.round_to}
            onDrag={onDrag}
            onCommit={(v) => onSet({ requested_amount: v }, `Сумма ${rub(v)}`)}
          />
        </div>
      </div>

      {!product.revolving && (
        <div className="lever" id="lever-term">
          <span className="t-label muted">Срок</span>
          <div className="chips">
            {[...new Set([...TERMS, levers.requested_term_m])]
              .sort((a, b) => a - b)
              .map((t) => (
                <button
                  key={t}
                  type="button"
                  className="chip"
                  aria-pressed={levers.requested_term_m === t}
                  onClick={() => levers.requested_term_m !== t && onSet({ requested_term_m: t }, `Срок ${months(t)}`)}
                >
                  {months(t)}
                </button>
              ))}
          </div>
        </div>
      )}

      <div className="lever" id="lever-rko">
        <YesNo id="lever-rko-toggle" label="РКО в Альфе" value={levers.has_rko} onChange={(v) => onSet({ has_rko: v }, 'РКО в Альфе')} />
        {levers.has_rko && (
          <>
            <div className="lever-row">
              <span className="t-caption muted">Обороты по счёту в месяц</span>
              <span className="t-label">{rub(levers.bank_turnover_month_rub)}</span>
            </div>
            <AmountSlider
              id="turnover-slider"
              label="Обороты по счёту в месяц"
              min={0}
              max={turnoverMax}
              value={Math.min(turnoverMax, levers.bank_turnover_month_rub)}
              step={50_000}
              log={false}
              onDrag={() => undefined}
              onCommit={(v) => onSet({ bank_turnover_month_rub: v }, 'Обороты в банке')}
            />
          </>
        )}
      </div>

      {!['card', 'overdraft'].includes(levers.product) && (
        <div className="lever" id="lever-guarantee">
          <YesNo label="Гарантия Корпорации МСП" id="lever-guarantee-toggle" value={levers.guarantee} onChange={(v) => onSet({ guarantee: v }, 'Гарантия МСП')} />
        </div>
      )}
      {trade && (
        <div className="lever" id="lever-marketplace">
          <YesNo label="Данные маркетплейса" id="lever-marketplace-toggle" value={levers.marketplace} onChange={(v) => onSet({ marketplace: v }, 'Данные маркетплейса')} />
        </div>
      )}
      <div className="lever" id="lever-insurance">
        <YesNo
          label="Страховка"
          id="lever-insurance-toggle"
          value={secured || levers.insurance}
          disabled={secured}
          onChange={(v) => onSet({ insurance: v }, 'Страховка')}
        />
        {secured && <span className="t-caption lever-note">Для залогового кредита страховка обязательна</span>}
      </div>
      <div className="lever">
        <YesNo label="Подписка на пакет услуг" id="lever-subscription" value={levers.subscription} onChange={(v) => onSet({ subscription: v }, 'Подписка')} />
      </div>
      <div className="lever" id="lever-bki">
        <YesNo label="Согласие на запрос в БКИ" id="lever-bki-toggle" value={levers.bki_consent} onChange={(v) => onSet({ bki_consent: v }, 'Согласие на БКИ')} />
        {!levers.bki_consent && <span className="t-caption lever-note">Без кредитной истории — только предоценка шанса</span>}
      </div>
    </div>
  );
}
