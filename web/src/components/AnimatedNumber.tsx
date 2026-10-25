import { animate, useReducedMotion } from 'motion/react';
import { useEffect, useRef } from 'react';

/** Число доезжает до нового значения за 240 мс; при перетаскивании и reduced motion — сразу. */
export function AnimatedNumber({ value, format, instant = false }: { value: number; format: (v: number) => string; instant?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  const prev = useRef(value);
  const reduce = useReducedMotion();
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const from = prev.current;
    prev.current = value;
    if (instant || reduce || from === value) {
      el.textContent = format(value);
      return;
    }
    const c = animate(from, value, { duration: 0.24, ease: [0.2, 0, 0, 1], onUpdate: (v) => (el.textContent = format(v)) });
    return () => c.stop();
  }, [value, instant, reduce, format]);
  return <span ref={ref}>{format(value)}</span>;
}
