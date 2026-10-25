import { describe, expect, it } from 'vitest';
import { useAuth } from './auth';

describe('login store', () => {
  it('persists token and role to localStorage and clears on logout', () => {
    useAuth.getState().login('tok-1', 'analyst', 'Аналитик МСБ');
    const saved = JSON.parse(localStorage.getItem('conveyor-auth')!);
    expect(saved.state).toMatchObject({ token: 'tok-1', role: 'analyst' });
    useAuth.getState().logout();
    expect(JSON.parse(localStorage.getItem('conveyor-auth')!).state.token).toBeNull();
  });
});
