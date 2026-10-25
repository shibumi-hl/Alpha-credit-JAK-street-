// Реплика ИИгоря по правилам (без LLM): исход, код причины и лучший сценарий. Все числа — из ответа API (ТЗ §2, §5.1).
import { chance, pp } from './format';
import type { Evaluation, Scenario } from './schemas';

/** Порядок сценариев: сначала те, что дают одобрение (и на большую сумму), потом — сильнее поднимают шанс и снижают ставку. */
export const scenarioOrder = (a: Scenario, b: Scenario) =>
  Number(b.outcome === 'APPROVE') - Number(a.outcome === 'APPROVE') ||
  (a.outcome === 'APPROVE' ? b.offered_amount - a.offered_amount : 0) ||
  b.delta_approval_pp - a.delta_approval_pp ||
  (a.delta_rate_pp ?? 0) - (b.delta_rate_pp ?? 0);

export function bestScenario(scenarios: Scenario[] | undefined): Scenario | undefined {
  return [...(scenarios ?? [])]
    .filter((s) => s.delta_approval_pp > 0.5 || (s.delta_rate_pp ?? 0) < -0.05)
    .sort(scenarioOrder)[0];
}

export function igorHint(e: Evaluation, scenarios: Scenario[] | undefined): string {
  const best = bestScenario(scenarios);
  const tip = best ? ` Попробуйте «${best.title}»: шанс ${pp(best.delta_approval_pp)}` : ''; // pp() уже кончается точкой
  switch (e.outcome) {
    case 'APPROVE':
      return 'Проходит вся сумма. Это предварительная оценка — решение примет банк.';
    case 'COUNTER':
      // сценарии меняют запрошенный продукт, а он закрыт: подсказка — взять то, что доступно
      if (e.route) return 'Этот продукт пока рано. Возьмите то, что доступно сейчас, а к нему вернёмся позже.';
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
