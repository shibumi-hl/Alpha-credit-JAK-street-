// Hash-маршруты без роутера: #/login, #/, #/applications, #/applications/:id, #/analyst, #/analyst/:id.
import { useSyncExternalStore } from 'react';

export type Route =
  | { name: 'login' }
  | { name: 'home' }
  | { name: 'apps' }
  | { name: 'app'; id: string }
  | { name: 'queue' }
  | { name: 'review'; id: string };

export function parse(hash: string): Route {
  const p = hash.replace(/^#/, '').split('/').filter(Boolean);
  if (p[0] === 'login') return { name: 'login' };
  if (p[0] === 'applications') return p[1] ? { name: 'app', id: decodeURIComponent(p[1]) } : { name: 'apps' };
  if (p[0] === 'analyst') return p[1] ? { name: 'review', id: decodeURIComponent(p[1]) } : { name: 'queue' };
  return { name: 'home' };
}

const sub = (cb: () => void) => {
  window.addEventListener('hashchange', cb);
  return () => window.removeEventListener('hashchange', cb);
};

export function useHash(): string {
  return useSyncExternalStore(sub, () => location.hash);
}

export function go(path: string) {
  location.hash = path;
}
