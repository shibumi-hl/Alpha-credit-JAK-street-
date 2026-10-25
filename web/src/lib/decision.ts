// Карточка решения по исходу (ТЗ §4.8): бейдж, заголовок, причины словами из API и следующий шаг. Тексты причин
// приходят из движка как есть.
import { months, rub } from './format';
import type { Evaluation, Levers, Meta } from './schemas';

export type Tone = 'approve' | 'counter' | 'info' | 'reject';
export interface Action {
  kind: 'submit' | 'take' | 'variants' | 'consent' | 'upload' | 'switch-company';
  label: string;
  change?: Partial<Levers>;
}
export interface Decision {
  tone: Tone;
  badge: string;
  headline: string;
  reasons: string[];
  actions: Action[];
}

const BKI_REQUEST = 'кредитной истории';

export function productLabel(meta: Meta | undefined, product: string): string {
  return meta?.products.find((p) => p.product === product)?.label ?? product;
}

export function decision(e: Evaluation, meta: Meta | undefined): Decision {
  const label = (p: string) => productLabel(meta, p);
  const revolving = meta?.products.find((p) => p.product === e.offered_product)?.revolving ?? false;
  const term = revolving ? '' : ` на ${months(e.requested_term_m)}`;
  switch (e.outcome) {
    case 'APPROVE':
      return {
        tone: 'approve',
        badge: 'Одобрим',
        headline: `Одобрим ${rub(e.offered_amount)}${term}`,
        reasons: [],
        actions: [{ kind: 'submit', label: 'Подать заявку' }],
      };
    case 'COUNTER':
      if (e.route) {
        const why = e.route.reasons.map((r) => r.category).join('; ');
        return {
          tone: 'counter',
          badge: 'Другой продукт',
          headline: `Можем выдать ${rub(e.offered_amount)} — ${label(e.route.to)}`,
          reasons: [`Продукт «${label(e.route.from)}» пока недоступен: ${why}`],
          actions: [
            {
              kind: 'take',
              label: `Взять: ${label(e.route.to)}`,
              change: { product: e.route.to, requested_amount: e.offered_amount },
            },
            { kind: 'variants', label: 'Что изменить' },
          ],
        };
      }
      return {
        tone: 'counter',
        badge: 'Другая сумма',
        headline: `Можем выдать ${rub(e.offered_amount)}`,
        reasons: e.reasons.map((r) => r.category),
        actions: [
          { kind: 'take', label: `Взять ${rub(e.offered_amount)}`, change: { requested_amount: e.offered_amount } },
          { kind: 'variants', label: 'Посмотреть варианты' },
        ],
      };
    case 'REQUEST_INFO': {
      const bki = e.requests.some((q) => q.includes(BKI_REQUEST));
      return {
        tone: 'info',
        badge: 'Нужны документы',
        headline: bki ? 'Нужно согласие на запрос в БКИ' : 'Нужны документы',
        reasons: e.requests,
        actions: bki
          ? [{ kind: 'consent', label: 'Дать согласие на запрос в БКИ', change: { bki_consent: true } }]
          : [{ kind: 'upload', label: 'Загрузить документы' }],
      };
    }
    case 'REJECT':
      return {
        tone: 'reject',
        badge: 'Сейчас не сможем',
        headline: 'Сейчас не сможем выдать кредит',
        reasons: (e.stop_factors.length ? e.stop_factors : e.reasons).map((r) => r.category),
        actions: [{ kind: 'switch-company', label: 'Выбрать другую компанию' }],
      };
  }
}
