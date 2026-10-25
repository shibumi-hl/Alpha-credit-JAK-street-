// Состояние песочницы: выбранная компания, рычаги и история для «Отменить». Серверные ответы — в TanStack Query.
import { create } from 'zustand';
import type { Levers, Scenario } from './schemas';

interface Step {
  levers: Levers;
  label: string;
}

interface Sandbox {
  personaId: string | null;
  levers: Levers | null;
  history: Step[];
  /** Сумма во время перетаскивания (по кривой или слайдеру); null — не тащим. */
  drag: number | null;
  /** Сценарий под курсором: его призрак на кривых и в плитках, ничего не применено. */
  ghost: Scenario | null;
  load(personaId: string, levers: Levers): void;
  set(change: Partial<Levers>, label: string): void;
  apply(levers: Levers, label: string): void;
  setProduct(product: string, range: { min_amount: number; max_amount: number }): void;
  undo(): void;
  setDrag(x: number | null): void;
  setGhost(s: Scenario | null): void;
}

export const useSandbox = create<Sandbox>((setState, get) => ({
  personaId: null,
  levers: null,
  history: [],
  drag: null,
  ghost: null,
  load: (personaId, levers) => setState({ personaId, levers, history: [], drag: null, ghost: null }),
  apply: (levers, label) => {
    const prev = get().levers;
    if (!prev) return;
    setState({ levers, ghost: null, history: [...get().history, { levers: prev, label }].slice(-30) });
  },
  set: (change, label) => {
    const prev = get().levers;
    if (prev) get().apply({ ...prev, ...change }, label);
  },
  setProduct: (product, { min_amount, max_amount }) => {
    const prev = get().levers;
    if (!prev) return;
    const amount = Math.min(max_amount, Math.max(min_amount, prev.requested_amount));
    get().apply({ ...prev, product, requested_amount: amount }, 'Смена продукта');
  },
  undo: () => {
    const h = get().history;
    if (!h.length) return;
    setState({ levers: h[h.length - 1].levers, history: h.slice(0, -1) });
  },
  setDrag: (x) => setState({ drag: x }),
  setGhost: (s) => setState({ ghost: s }),
}));
