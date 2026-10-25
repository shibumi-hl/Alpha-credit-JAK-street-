import { Building2, ChevronDown } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { months, pct, rub } from '../lib/format';
import type { Persona, PersonaCard } from '../lib/schemas';

const value = (f: Persona['facts'][number]) => {
  const v = Number(f.value);
  if (f.unit === 'rub') return v === 0 ? 'нет' : rub(v);
  if (f.unit === 'pct') return pct(v, 0);
  if (f.unit === 'months') return months(v);
  return v === 0 ? 'нет' : `${v} дн.`;
};

/** Шапка: бренд, выбор демо-компании и её факты (с бейджем источника). */
export function Header({ personas, persona, onPick }: { personas: PersonaCard[] | undefined; persona: Persona | undefined; onPick(id: string): void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', close);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', close);
    };
  }, [open]);
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden>
          А
        </span>
        <div>
          <div className="t-title">МойАльфаКредит</div>
          <div className="t-caption muted">Песочница кредита</div>
        </div>
      </div>
      <label className="visually-hidden" htmlFor="company-select">
        Демо-компания
      </label>
      <select
        id="company-select"
        className="select t-label"
        value={persona?.id ?? ''}
        onChange={(e) => onPick(e.target.value)}
      >
        {personas?.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      <div style={{ position: 'relative' }} ref={box}>
        <button type="button" className="btn btn-secondary t-label" aria-expanded={open} onClick={() => setOpen(!open)}>
          <Building2 size={18} strokeWidth={1.75} aria-hidden />
          Факты<span className="hide-mobile"> компании</span>
          <ChevronDown size={16} aria-hidden />
        </button>
        {open && persona && (
          <div className="popover" role="dialog" aria-label={`Факты: ${persona.name}`}>
            <div className="t-title">{persona.name}</div>
            <div className="t-caption muted">
              ИНН {persona.inn} · ОКВЭД {persona.okved} · {persona.okved_name}
            </div>
            <p className="t-label" style={{ margin: '8px 0 0' }}>
              {persona.tagline}
            </p>
            <dl className="facts t-label">
              {persona.facts.map((f) => (
                <div key={f.key}>
                  <dt>{f.label}</dt>
                  <dd>{value(f)}</dd>
                </div>
              ))}
            </dl>
            <p className="t-caption muted" style={{ margin: '12px 0 0' }}>
              Демо-компания: данные вымышлены, ИНН с несуществующим кодом региона 00
            </p>
          </div>
        )}
      </div>
    </header>
  );
}
