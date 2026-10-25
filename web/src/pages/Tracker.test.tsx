import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import fixture from '../test/fixtures/application.json';
import { ApplicationSchema } from '../lib/schemas';
import { TrackerView } from './Tracker';

const base = ApplicationSchema.parse(fixture);
const view = (actions: string[], extra = {}) =>
  render(<TrackerView app={{ ...base, ...extra, actions }} busy={false} onAct={() => {}} />);

describe('tracker actions', () => {
  it('shows sign code and withdraw for SIGNING', () => {
    view(['sign', 'withdraw']);
    expect(screen.getByText('4821')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Подписать' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отозвать заявку' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Принять предложение' })).toBeNull();
  });

  it('shows only accept_offer when that is the only action', () => {
    view(['accept_offer']);
    expect(screen.getByRole('button', { name: 'Принять предложение' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Подписать' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Отозвать заявку' })).toBeNull();
  });

  it('upload checklist gates the send button', () => {
    view(['upload_documents']);
    expect(screen.getByRole('button', { name: 'Отправить документы' })).toBeDisabled();
    screen.getByRole('button', { name: 'Загрузить' }).click();
  });

  it('no action area when actions are empty', () => {
    view([], { whose_turn: 'bank' });
    expect(screen.getByText('Ход банка')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Действия' })).toBeNull();
  });
});
