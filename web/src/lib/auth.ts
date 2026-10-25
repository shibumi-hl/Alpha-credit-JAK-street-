// Вход: токен и роль в localStorage (если хранилище недоступно — живём в памяти).
import { create } from 'zustand';
import { createJSONStorage, persist, type StateStorage } from 'zustand/middleware';

const safe: StateStorage = {
  getItem: (k) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  setItem: (k, v) => {
    try {
      localStorage.setItem(k, v);
    } catch {
      // приватный режим
    }
  },
  removeItem: (k) => {
    try {
      localStorage.removeItem(k);
    } catch {
      // приватный режим
    }
  },
};

export type Role = 'client' | 'analyst';

interface Auth {
  token: string | null;
  role: Role | null;
  name: string | null;
  login(token: string, role: Role, name: string): void;
  logout(): void;
}

export const useAuth = create<Auth>()(
  persist(
    (set) => ({
      token: null,
      role: null,
      name: null,
      login: (token, role, name) => set({ token, role, name }),
      logout: () => set({ token: null, role: null, name: null }),
    }),
    { name: 'conveyor-auth', storage: createJSONStorage(() => safe) },
  ),
);
