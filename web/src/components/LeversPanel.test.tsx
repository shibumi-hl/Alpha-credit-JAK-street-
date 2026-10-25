import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import young from '../test/fixtures/evaluation-young.json';
import marina from '../test/fixtures/evaluation-marina.json';
import meta from '../test/fixtures/meta.json';
import persona from '../test/fixtures/persona-marina.json';
import { months } from '../lib/format';
import { EvaluationSchema, LeversSchema, MetaSchema } from '../lib/schemas';
import { LeversPanel } from './LeversPanel';

const m = MetaSchema.parse(meta);
const props = (e: unknown, levers = LeversSchema.parse(persona.levers)) => ({
  meta: m,
  levers,
  e: EvaluationSchema.parse(e),
  okved: '47.91',
  range: [300_000, 10_000_000] as [number, number],
  drag: null,
  playing: false,
  onSet: vi.fn(),
  onProduct: vi.fn(),
  onDrag: vi.fn(),
  onPlay: vi.fn(),
});

describe('levers panel', () => {
  it('a closed product shows the lock reason and can still be picked', () => {
    const p = props(young, { ...LeversSchema.parse(persona.levers), product: 'credit_line', requested_amount: 3e6 });
    render(<LeversPanel {...p} />);
    const chip = screen.getByRole('button', { name: /Кредитная линия/ });
    expect(chip).toHaveAttribute('data-locked', 'true');
    expect(chip).toHaveAccessibleDescription(/бизнес слишком молодой/);
    fireEvent.click(screen.getByRole('button', { name: /Бизнес-карта/ }));
    expect(p.onProduct).toHaveBeenCalledWith('card');
  });

  it('switches the term and the bank turnover levers', () => {
    const p = props(marina);
    render(<LeversPanel {...p} />);
    fireEvent.click(screen.getByRole('button', { name: months(24) }));
    expect(p.onSet).toHaveBeenCalledWith({ requested_term_m: 24 }, `Срок ${months(24)}`);
    fireEvent.click(screen.getByRole('button', { name: /РКО в Альфе: да/ }));
    expect(p.onSet).toHaveBeenCalledWith({ has_rko: true }, 'РКО в Альфе');
    expect(screen.getByRole('slider', { name: 'Сумма' })).toHaveAttribute('aria-valuenow', '6000000');
  });

  it('insurance is locked on for a secured loan and the term is hidden for a card', () => {
    const lv = LeversSchema.parse(persona.levers);
    const { unmount } = render(<LeversPanel {...props(marina, { ...lv, product: 'secured' })} />);
    expect(screen.getByRole('button', { name: /Страховка: да/ })).toBeDisabled();
    unmount();
    render(<LeversPanel {...props(marina, { ...lv, product: 'card', requested_amount: 5e5 })} />);
    expect(screen.queryByRole('button', { name: months(24) })).toBeNull();
  });
});
