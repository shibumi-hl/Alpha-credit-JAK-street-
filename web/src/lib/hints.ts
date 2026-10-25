// Реплика ИИгоря по правилам (без LLM): исход, код причины и лучший сценарий. Все числа — из ответа API (ТЗ §2, §5.1).
import { chance, pp } from './format';
import type { Evaluation, Scenario } from './schemas';

/** Сценарий, который сильнее всего поднимает шанс (при равенстве — сильнее снижает ставку). */
export function bestScenario(scenarios: Scenario[] | undefined): Scenario | undefined {
  return [...(scenarios ?? [])]
    .filter((s) => s.delta_approval_pp > 0.5 || (s.delta_rate_pp ?? 0) < -0.05)
    .sort((a, b) => b.delta_approval_pp - a.delta_approval_pp || (a.delta_rate_pp ?? 0) - (b.delta_rate_pp ?? 0))[0];
}

export function igorHint(e: Evaluation, scenarios: Scenario[] | undefined): string {
  const best = bestScenario(scenarios);
  const tip = best ? ` Попробуйте «${best.title}»: шанс ${pp(best.delta_approval_pp)}.` : '';
  switch (e.outcome) {
    case 'APPROVE':
      return 'Проходит вся сумма. Это предварительная оценка — решение примет банк.';
    case 'COUNTER':
      if (e.route) return `Этот продукт пока рано, но задачу можно закрыть уже сейчас.${tip}`;
      if (e.reasons[0]?.code === 'L02') return `Ограничивает платёж, а не риск.${tip}`;
      return `Сумма упирается в лимит.${tip}`;
    case 'REQUEST_INFO':
      if (e.approval_mode === 'soft') {
        return `Шанс уже видно — ${chance(e.approval_probability)}. Дадите согласие на БКИ — посчитаю точно и предложу сумму.`;
      }
      return 'Почти готово: не хватает документов, остальное я уже проверил.';
    case 'REJECT':
      return 'Сейчас не получится. Когда причина уйдёт, пересчитаю за минуту.';
  }
}
