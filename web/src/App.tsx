import { useCallback, useEffect, useRef, useState } from 'react';
import { Contributions } from './components/Contributions';
import { CurveCard } from './components/CurveCard';
import { DecisionCard } from './components/DecisionCard';
import { Header } from './components/Header';
import { KpiRow } from './components/KpiRow';
import { LeversPanel } from './components/LeversPanel';
import { RateWaterfall } from './components/RateWaterfall';
import { SCENARIO_MIME, WhatIf } from './components/WhatIf';
import type { Action } from './lib/decision';
import { productLabel } from './lib/decision';
import { months, rub } from './lib/format';
import { igorHint } from './lib/hints';
import { useAmountCurve, useEvaluation, useMeta, usePersona, usePersonas, useWhatIf } from './lib/queries';
import type { Scenario } from './lib/schemas';
import { useSandbox } from './lib/store';

const DEMO_NOTICE = {
  submit: 'Это демо: заявка никуда не отправляется. В продукте здесь — подача и трекер статусов.',
  upload: 'В демо документы не загружаются. В продукте — загрузка прямо в кабинете, срок рассмотрения на паузе.',
};
// признак вклада → рычаг, который его меняет; остальное — факты компании
const LEVER_OF: Record<string, string> = {
  product: 'lever-product',
  rko: 'lever-rko',
  bank_turnover: 'lever-rko',
  guarantee: 'lever-guarantee',
  marketplace: 'lever-marketplace',
  amount_share: 'lever-amount',
  cash_cover: 'lever-amount',
  ln_turnover_to_payment: 'lever-amount',
  bki_overdue: 'lever-bki',
};

function initialCompany(): string {
  return new URLSearchParams(location.search).get('company') ?? 'marina';
}

export function App() {
  const [wanted, setWanted] = useState(initialCompany);
  const [notice, setNotice] = useState<string | null>(null);
  const [sheet, setSheet] = useState(false);
  const [drop, setDrop] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [undoShown, setUndoShown] = useState<string | null>(null);
  const { personaId, levers, history, drag, ghost, load, set, apply, setProduct, undo, setDrag, setGhost } = useSandbox();

  const meta = useMeta();
  const personas = usePersonas();
  const persona = usePersona(wanted);
  const ev = useEvaluation();
  const wi = useWhatIf();
  const curve = useAmountCurve();
  const ghostCurve = useAmountCurve(ghost?.levers ?? null);

  useEffect(() => {
    if (persona.data && persona.data.id !== personaId) {
      load(persona.data.id, persona.data.levers);
      setNotice(null);
      const u = new URL(location.href);
      u.searchParams.set('company', persona.data.id);
      window.history.replaceState(null, '', u);
    }
  }, [persona.data, personaId, load]);

  // «Отменить» — чип на 5 с после изменения и Ctrl+Z
  const last = history[history.length - 1]?.label ?? null;
  useEffect(() => {
    if (!last) return setUndoShown(null);
    setUndoShown(last);
    const t = setTimeout(() => setUndoShown(null), 5000);
    return () => clearTimeout(t);
  }, [last, history.length]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !(e.target instanceof HTMLInputElement)) {
        e.preventDefault();
        undo();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [undo]);

  // ▶: развёртка суммы по уже полученной кривой за 4 с, пауза 600 мс на лимите (ТЗ §4.2)
  const raf = useRef(0);
  const play = useCallback(() => {
    cancelAnimationFrame(raf.current);
    if (playing || !curve.data) {
      setPlaying(false);
      setDrag(null);
      return;
    }
    const pts = curve.data.points;
    const [lo, hi] = [pts[0].x, pts[pts.length - 1].x];
    const lim = curve.data.limit;
    const tLim = lim > lo && lim < hi ? Math.log(lim / lo) / Math.log(hi / lo) : 2;
    const start = performance.now();
    setPlaying(true);
    const tick = (now: number) => {
      let t = (now - start) / 4000;
      if (t > tLim) t = Math.max(tLim, t - 0.15); // 600 мс стоим на лимите
      if (t >= 1) {
        setPlaying(false);
        setDrag(null);
        return;
      }
      setDrag(Math.round((lo * (hi / lo) ** t) / 10000) * 10000);
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
  }, [playing, curve.data, setDrag]);
  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  const onAction = (a: Action) => {
    if (a.change) set(a.change, a.label);
    if (a.kind === 'variants') document.getElementById('whatif')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (a.kind === 'submit' || a.kind === 'upload') setNotice(DEMO_NOTICE[a.kind]);
    if (a.kind === 'switch-company') document.getElementById('company-select')?.focus();
  };
  const applyScenario = (s: Scenario) => {
    apply(s.levers, s.title);
    setGhost(null);
  };
  const pickFeature = (feature: string) => {
    const id = LEVER_OF[feature];
    if (!id) {
      setNotice('Это факт компании: в песочнице его не изменить.');
      return;
    }
    if (window.innerWidth < 1280) setSheet(true);
    requestAnimationFrame(() => {
      const el = document.getElementById(id);
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el?.querySelector<HTMLElement>('button, [role="slider"]')?.focus({ preventScroll: true });
    });
  };

  const e = ev.data;
  const m = meta.data;
  const product = m?.products.find((p) => p.product === levers?.product);
  const range: [number, number] = curve.data?.points.length
    ? [curve.data.points[0].x, curve.data.points[curve.data.points.length - 1].x]
    : [product?.min_amount ?? 1, product?.max_amount ?? 2];
  const commitAmount = (v: number) => set({ requested_amount: v }, `Сумма ${rub(v)}`);

  const panel =
    m && levers && persona.data ? (
      <LeversPanel
        meta={m}
        levers={levers}
        e={e}
        okved={persona.data.okved}
        range={range}
        drag={drag}
        playing={playing}
        onSet={set}
        onProduct={(p) => setProduct(p, m.products.find((x) => x.product === p)!)}
        onDrag={setDrag}
        onPlay={play}
      />
    ) : (
      <div className="card skeleton" style={{ height: 480 }} />
    );

  return (
    <div className="page">
      <Header personas={personas.data} persona={persona.data} onPick={setWanted} />
      {(ev.error || meta.error) && (
        <div className="banner" role="alert">
          <span>{(ev.error ?? meta.error)?.message ?? 'Сервис скоринга недоступен'}</span>
          <button type="button" className="btn btn-secondary" onClick={() => (ev.refetch(), meta.refetch())}>
            Повторить
          </button>
        </div>
      )}
      {levers && product && (
        <div className="levers-bar">
          <span className="t-label">
            {productLabel(m, levers.product).replace(/^./, (c) => c.toUpperCase())} · {rub(drag ?? levers.requested_amount)}
            {!product.revolving && ` · ${months(levers.requested_term_m)}`}
          </span>
          <button type="button" className="btn btn-secondary t-label" onClick={() => setSheet(true)}>
            Изменить
          </button>
        </div>
      )}
      <div className="layout" style={{ marginTop: 16 }}>
        <aside
          className="levers-col"
          data-drop={drop}
          aria-label="Условия заявки"
          onDragOver={(ev2) => {
            if (ev2.dataTransfer.types.includes(SCENARIO_MIME)) {
              ev2.preventDefault();
              setDrop(true);
            }
          }}
          onDragLeave={() => setDrop(false)}
          onDrop={(ev2) => {
            setDrop(false);
            const s = wi.data?.scenarios.find((x) => x.key === ev2.dataTransfer.getData(SCENARIO_MIME));
            if (s) applyScenario(s);
          }}
        >
          {panel}
        </aside>
        <main className="main-col">
          {e ? (
            <>
              <DecisionCard e={e} meta={m} hint={igorHint(e, wi.data?.scenarios)} thinking={ev.isFetching} notice={notice} onAction={onAction} />
              <KpiRow e={e} curve={curve.data} drag={drag} ghost={ghost} stale={ev.isFetching} revolving={!!product?.revolving} />
              <div className="grid-2">
                {(['approval', 'rate'] as const).map((metric) => (
                  <CurveCard
                    key={metric}
                    metric={metric}
                    curve={curve.data}
                    ghost={ghost ? ghostCurve.data : undefined}
                    product={levers!.product}
                    amount={levers!.requested_amount}
                    drag={drag}
                    step={m?.round_to ?? 10000}
                    onDrag={setDrag}
                    onCommit={commitAmount}
                  />
                ))}
              </div>
              <WhatIf w={wi.data} base={e} onHover={setGhost} onApply={applyScenario} />
              <div className="grid-2">
                <Contributions e={e} onPick={pickFeature} />
                <RateWaterfall p={e.pricing} note={m?.pricing_note ?? ''} />
              </div>
            </>
          ) : (
            <>
              <div className="card skeleton" style={{ height: 200 }} />
              <div className="kpis">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="card skeleton" style={{ height: 120 }} />
                ))}
              </div>
            </>
          )}
          <footer className="footer t-caption muted">
            Предварительная оценка, не решение банка · параметры цены иллюстративные · демо-компании вымышлены · модели на{' '}
            {m ? new Date(m.asof).toLocaleDateString('ru-RU') : '…'}
          </footer>
        </main>
      </div>
      {sheet && (
        <>
          <div className="sheet-backdrop" onClick={() => setSheet(false)} />
          <div className="sheet" role="dialog" aria-modal="true" aria-label="Условия заявки">
            <div className="lever-row" style={{ marginBottom: 8, justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-secondary t-label" onClick={() => setSheet(false)}>
                Готово
              </button>
            </div>
            {panel}
          </div>
        </>
      )}
      {undoShown && (
        <div className="undo-chip t-label" role="status">
          <span>{undoShown}</span>
          <button type="button" onClick={undo}>
            Отменить
          </button>
        </div>
      )}
    </div>
  );
}
