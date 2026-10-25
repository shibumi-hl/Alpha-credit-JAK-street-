import { useMutation } from '@tanstack/react-query';
import { conveyor } from '../lib/api';
import { useAuth } from '../lib/auth';
import { go } from '../lib/route';

const ACCOUNTS = [
  { user: 'client', title: 'Клиент', name: 'Марина Соколова', note: 'Песочница, подача заявки и трекер' },
  { user: 'analyst', title: 'Аналитик', name: 'Аналитик МСБ', note: 'Очередь заявок и решения' },
];

export function Login() {
  const login = useAuth((s) => s.login);
  const m = useMutation({
    mutationFn: (u: string) => conveyor.login(u, u),
    onSuccess: (r) => {
      login(r.token, r.role, r.name);
      go(r.role === 'analyst' ? '/analyst' : '/');
    },
  });
  return (
    <main className="login">
      <h1 className="t-h1">Вход в демо-кабинет</h1>
      <p className="t-label muted">Выберите учётную запись — вход в один клик.</p>
      <div className="login-cards">
        {ACCOUNTS.map((a) => (
          <button key={a.user} type="button" className="card login-card" disabled={m.isPending} onClick={() => m.mutate(a.user)}>
            <span className="t-caption muted">{a.title}</span>
            <span className="t-title">{a.name}</span>
            <span className="t-label muted">{a.note}</span>
            <span className="t-caption muted">
              {a.user} / {a.user}
            </span>
          </button>
        ))}
      </div>
      {m.error && (
        <p className="lever-error t-label" role="alert">
          {m.error.message}
        </p>
      )}
    </main>
  );
}
