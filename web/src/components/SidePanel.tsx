// Правая панель клиента: чат ИИгоря и лента новостей; действия применяются к рычагам песочницы.
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { conveyor } from '../lib/api';
import type { Levers } from '../lib/schemas';
import { useSandbox } from '../lib/store';
import { date } from './conveyor';

const scrollToLevers = () =>
  document.querySelector('.levers-col, .levers-bar')?.scrollIntoView({ behavior: 'smooth', block: 'start' });

type Msg = { role: 'user' | 'assistant'; content: string };

function IgorChat({ personaId, levers }: { personaId: string; levers: Levers }) {
  const set = useSandbox((s) => s.set);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState('');
  const [mode, setMode] = useState<'llm' | 'rules' | null>(null);
  const m = useMutation({
    mutationFn: (history: Msg[]) => conveyor.chat(personaId, levers, history),
    onSuccess: (r, history) => {
      setMsgs([...history, { role: 'assistant', content: r.reply }]);
      setMode(r.mode);
      if (r.levers) set(r.levers, 'ИИгорь');
    },
  });
  return (
    <section className="card chat" aria-label="Чат с ИИгорем">
      <div className="row-between">
        <div className="t-title">ИИгорь</div>
        {mode && <span className="t-caption muted">{mode === 'llm' ? 'LLM' : 'правила'}</span>}
      </div>
      <ol className="chat-list" aria-live="polite">
        {msgs.map((x, i) => (
          <li key={i} data-role={x.role} className="t-label">
            {x.content}
          </li>
        ))}
        {m.isPending && <li className="t-caption muted">ИИгорь думает…</li>}
      </ol>
      {m.isError && <p className="t-label muted">ИИгорь отдыхает — всё можно сделать на экране</p>}
      <form
        className="inn-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim()) return;
          const h: Msg[] = [...msgs, { role: 'user', content: text.trim() }];
          setMsgs(h);
          setText('');
          m.mutate(h);
        }}
      >
        <label className="visually-hidden" htmlFor="chat-input">
          Сообщение ИИгорю
        </label>
        <input id="chat-input" className="input" placeholder="Например: 6 млн на закупку на год" value={text} onChange={(e) => setText(e.target.value)} />
        <button type="submit" className="btn btn-primary" disabled={!text.trim() || m.isPending}>
          Спросить
        </button>
      </form>
    </section>
  );
}

function Feed({ personaId }: { personaId: string }) {
  const set = useSandbox((s) => s.set);
  const q = useQuery({ queryKey: ['news', personaId], queryFn: () => conveyor.news(personaId), staleTime: 60_000 });
  if (q.isError || (q.data && !q.data.length)) return null;
  return (
    <section aria-label="Лента" className="stack">
      <div className="t-title">Лента</div>
      {!q.data && <div className="card skeleton" style={{ height: 120 }} />}
      {q.data?.map((n) => (
        <article key={n.id} className="card news">
          <div className="t-caption muted">
            {n.tag} · {date(n.date)}
          </div>
          <div className="t-title">{n.title}</div>
          <p className="t-label">{n.body}</p>
          <p className="t-caption muted">{n.why}</p>
          {n.action?.levers && (
            <button
              type="button"
              className="btn btn-secondary t-label"
              onClick={() => {
                set(n.action!.levers!, n.action!.label);
                scrollToLevers();
              }}
            >
              {n.action.label}
            </button>
          )}
        </article>
      ))}
    </section>
  );
}

export function SidePanel({ personaId, levers }: { personaId: string; levers: Levers }) {
  return (
    <div className="side-panel stack">
      <IgorChat key={personaId} personaId={personaId} levers={levers} />
      <Feed personaId={personaId} />
    </div>
  );
}
