import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { rub } from '../lib/format';

interface Props {
  id: string;
  label: string;
  min: number;
  max: number;
  value: number;
  step: number;
  log?: boolean;
  format?(v: number): string;
  onDrag(v: number | null): void;
  onCommit(v: number): void;
}

const TICKS = [1e5, 3e5, 1e6, 3e6, 1e7, 3e7, 1e8, 3e8];

/** Слайдер суммы: логарифмическая шкала, перетаскивание — предпросмотр, отпускание — расчёт; клавиатура как у slider. */
export function AmountSlider({ id, label, min, max, value, step, log = true, format = rub, onDrag, onCommit }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [local, setLocal] = useState<number | null>(null);
  const f = log ? Math.log : (v: number) => v;
  const inv = log ? Math.exp : (v: number) => v;
  const span = f(max) - f(min) || 1;
  const frac = (v: number) => Math.min(1, Math.max(0, (f(Math.max(v, log ? min : -Infinity)) - f(min)) / span));
  const snap = (v: number) => Math.min(max, Math.max(min, Math.round(v / step) * step));
  const fromFrac = (t: number) => snap(inv(f(min) + Math.min(1, Math.max(0, t)) * span));
  const fromEvent = (e: PointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    return fromFrac((e.clientX - r.left) / r.width);
  };
  const shown = local ?? value;

  const move = (v: number) => {
    setLocal(v);
    onDrag(v);
  };
  const end = () => {
    if (local != null) onCommit(local);
    setLocal(null);
    onDrag(null);
  };
  const key = (e: KeyboardEvent) => {
    const k = e.shiftKey ? 10 : 1;
    const t = frac(value);
    const next =
      e.key === 'ArrowRight' || e.key === 'ArrowUp'
        ? fromFrac(t + k / 60)
        : e.key === 'ArrowLeft' || e.key === 'ArrowDown'
          ? fromFrac(t - k / 60)
          : e.key === 'Home'
            ? min
            : e.key === 'End'
              ? max
              : null;
    if (next == null) return;
    e.preventDefault();
    if (next !== value) onCommit(next);
  };

  return (
    <div>
      <div
        ref={ref}
        className="slider"
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          move(fromEvent(e));
        }}
        onPointerMove={(e) => local != null && move(fromEvent(e))}
        onPointerUp={end}
        onPointerCancel={end}
      >
        <div className="slider-track" />
        <div className="slider-fill" style={{ width: `${frac(shown) * 100}%` }} />
        <div
          id={id}
          className="slider-thumb"
          role="slider"
          tabIndex={0}
          aria-label={label}
          aria-valuemin={min}
          aria-valuemax={max}
          aria-valuenow={shown}
          aria-valuetext={format(shown)}
          onKeyDown={key}
          style={{ left: `${frac(shown) * 100}%` }}
        />
      </div>
      {log && (
        <div className="slider-ticks t-caption muted" aria-hidden>
          {/* насечки у самого края не подписываем: подпись вылезала за трек */}
          {TICKS.filter((t) => t > min * 1.6 && t < max / 1.6).map((t) => (
            <span key={t} style={{ left: `${frac(t) * 100}%` }}>
              {rub(t).replace(/ ₽$/, '')}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
