import { useQuery } from '@tanstack/react-query';
import { conveyor } from '../lib/api';
import { months, rub } from '../lib/format';
import { dateTime, StatusChip, TurnBadge } from '../components/conveyor';

export function AppList({ status, base }: { status?: string; base: string }) {
  const q = useQuery({
    queryKey: ['applications', status ?? 'all'],
    queryFn: () => conveyor.list(status),
    refetchInterval: 5000,
  });
  if (q.error) return <div className="banner" role="alert">{q.error.message}</div>;
  if (!q.data) return <div className="card skeleton" style={{ height: 160 }} />;
  if (!q.data.length) return <div className="card t-label muted">Заявок пока нет.</div>;
  return (
    <ul className="app-list">
      {q.data.map((a) => (
        <li key={a.id}>
          <a className="card app-row" href={`#${base}/${a.id}`}>
            <div>
              <div className="t-title">{a.company.name}</div>
              <div className="t-caption muted">
                {a.product_label} · {rub(a.amount)} · {months(a.term_m)} · {dateTime(a.updated_at)}
              </div>
              {a.route_reason && <div className="t-caption muted">{a.route_reason}</div>}
            </div>
            <div className="chips">
              <StatusChip status={a.status} label={a.status_label} />
              <TurnBadge turn={a.whose_turn} />
            </div>
          </a>
        </li>
      ))}
    </ul>
  );
}

export function MyApplications() {
  return (
    <div className="stack">
      <h1 className="t-h1">Мои заявки</h1>
      <AppList base="/applications" />
    </div>
  );
}
