import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import marina from '../test/fixtures/evaluation-marina.json';
import overdue from '../test/fixtures/evaluation-overdue.json';
import meta from '../test/fixtures/meta.json';
import { EvaluationSchema, MetaSchema } from '../lib/schemas';
import { DecisionCard } from './DecisionCard';

const m = MetaSchema.parse(meta);

describe('decision card', () => {
  it('a counter-offer shows the amount, the reason and takes the offer on click', () => {
    const onAction = vi.fn();
    render(<DecisionCard e={EvaluationSchema.parse(marina)} meta={m} hint="Ограничивает платёж" thinking={false} notice={null} onAction={onAction} />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/Можем выдать 3,61\s+млн/);
    expect(screen.getByText(/Денежного потока с запасом DSCR/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Взять 3,61/ }));
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ kind: 'take', change: { requested_amount: 3_610_000 } }));
    expect(screen.queryByRole('button', { name: 'Подать заявку' })).toBeNull(); // подаём только одобренную сумму
  });

  it('a rejection is calm: the stop factor in words and no red submit button', () => {
    render(<DecisionCard e={EvaluationSchema.parse(overdue)} meta={m} hint="" thinking={false} notice={null} onAction={vi.fn()} />);
    expect(screen.getByText('Текущая просрочка более 30 дней')).toBeInTheDocument();
    expect(document.querySelector('.btn-primary')).toBeNull();
  });
});
