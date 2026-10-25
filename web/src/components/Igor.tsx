import { useEffect, useRef, useState } from 'react';

export type IgorState = 'idle' | 'thinking' | 'react';

/** ИИгорь: дышит, думает во время расчёта, поворачивается на новый исход и следит за курсором (DESIGN.md «ИИгорь»). */
export function Igor({ thinking, outcome }: { thinking: boolean; outcome?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [react, setReact] = useState(false);
  const last = useRef(outcome);
  useEffect(() => {
    if (!outcome || outcome === last.current) return;
    last.current = outcome;
    setReact(true);
    const t = setTimeout(() => setReact(false), 320);
    return () => clearTimeout(t);
  }, [outcome]);
  useEffect(() => {
    const mq = (q: string) => window.matchMedia?.(q).matches ?? false;
    if (!mq('(pointer: fine)') || mq('(prefers-reduced-motion: reduce)')) return;
    const onMove = (e: PointerEvent) => {
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const tilt = Math.max(-6, Math.min(6, ((e.clientX - (r.left + r.width / 2)) / 400) * 6));
      el.style.setProperty('--tilt', `${tilt.toFixed(2)}deg`);
    };
    window.addEventListener('pointermove', onMove);
    return () => window.removeEventListener('pointermove', onMove);
  }, []);
  const state: IgorState = thinking ? 'thinking' : react ? 'react' : 'idle';
  return (
    <div className="igor" data-state={state} ref={ref}>
      <img src="/igor-256.png" width={96} height={96} alt="ИИгорь, помощник по кредитам" />
    </div>
  );
}
