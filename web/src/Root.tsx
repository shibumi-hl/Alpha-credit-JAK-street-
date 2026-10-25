// Маршрутизация кабинета: вход, клиент (песочница, заявки, трекер), аналитик (очередь, карточка).
import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { App } from './App';
import { useAuth } from './lib/auth';
import { go, parse, useHash } from './lib/route';
import { Queue, Review } from './pages/Analyst';
import { Login } from './pages/Login';
import { MyApplications } from './pages/MyApplications';
import { Tracker } from './pages/Tracker';

function NavBar() {
  const { role, name, logout } = useAuth();
  const qc = useQueryClient();
  return (
    <nav className="navbar t-label" aria-label="Кабинет">
      <span className="muted">
        {role === 'analyst' ? 'Аналитик' : 'Клиент'} · {name}
      </span>
      <span className="nav-links">
        {role === 'client' && (
          <>
            <a href="#/">Песочница</a>
            <a href="#/applications">Мои заявки</a>
          </>
        )}
        {role === 'analyst' && <a href="#/analyst">Очередь</a>}
        <button
          type="button"
          className="btn-text t-label"
          onClick={() => {
            logout();
            qc.clear();
            go('/login');
          }}
        >
          Выйти
        </button>
      </span>
    </nav>
  );
}

export function Root() {
  const hash = useHash();
  const route = parse(hash);
  const role = useAuth((s) => s.role);
  const token = useAuth((s) => s.token);
  const authed = !!token && !!role;
  const analystRoute = route.name === 'queue' || route.name === 'review';
  const target =
    !authed && route.name !== 'login'
      ? '/login'
      : authed && route.name === 'login'
        ? role === 'analyst' ? '/analyst' : '/'
        : authed && role === 'analyst' && !analystRoute
          ? '/analyst'
          : authed && role === 'client' && analystRoute
            ? '/'
            : null;
  useEffect(() => {
    if (target) go(target);
  }, [target]);
  if (target) return null;
  if (route.name === 'login') return <Login />;
  return (
    <>
      <NavBar />
      {route.name === 'home' ? (
        <App />
      ) : (
        <div className="page narrow">
          {route.name === 'apps' && <MyApplications />}
          {route.name === 'app' && <Tracker id={route.id} />}
          {route.name === 'queue' && <Queue />}
          {route.name === 'review' && <Review id={route.id} />}
        </div>
      )}
    </>
  );
}
