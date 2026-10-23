"""
Обучение моделей скоринга МСБ на data/scoring/train.csv и отчёт.

Модель 1a - PD-скоркарта OptBinning (риск дефолта). Кредитная логика со ставкой модели 2 даёт решения,
на них учится модель 1b - вероятность одобрения (one-hot логистическая, баллы по категориям).
Модель 2 - risk-based pricing: фондирование по G-кривой Мосбиржи (data/raw/gcurve_params.csv, на D-1)
+ PD × LGD + капитал + расходы + маржа − скидки, и ПСК с комиссией и страховкой.

Запуск из папки проекта (после build_scoring_sample.py):
  py scripts/train_scorecard.py                            # капитал по подходу из config/pricing.json
  py scripts/train_scorecard.py --capital-approach both    # два отчёта: ПВР (845-П) и плоский вес риска

Результат: data/scoring/engine.pkl (обе модели, политика, цены), data/scoring/assessed.csv (решение, ставка,
шанс одобрения по каждой компании), reports/scorecard_<дата>_<irb|standard>.md. При --capital-approach both
модели и решения остаются по подходу из конфига (он считается последним).
"""
import argparse
import json
import sys
import warnings
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring.gcurve import CurveStore  # noqa: E402
from scoring.assess import OUTCOMES  # noqa: E402
from scoring.credit import ELIGIBILITY, STOPS  # noqa: E402
from scoring.pricing import load_pricing  # noqa: E402
from scoring.realcheck import validate as validate_real, real_label  # noqa: E402
from scoring.synth import load_calibration  # noqa: E402
from scoring.reasons import CATEGORIES  # noqa: E402
from scoring.whatif import Engine  # noqa: E402

ENC = "utf-8-sig"
CODES = {**CATEGORIES, **STOPS, **ELIGIBILITY, "L01": "лимит ниже минимальной суммы"}


def _md(df: pd.DataFrame, floatfmt=".4f") -> str:
    def fmt(v):
        return f"{v:{floatfmt}}" if isinstance(v, float) else str(v)
    head = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    return "\n".join(head + ["| " + " | ".join(fmt(v) for v in r) + " |" for r in df.itertuples(index=False)])


def load_curves(data_dir: Path):
    p = data_dir / "raw" / "gcurve_params.csv"
    return CurveStore.from_csv(p) if p.exists() else None


def pricing_by_class(out: pd.DataFrame) -> pd.DataFrame:
    q = out[out.pricing.notna()]
    if q.empty:
        return pd.DataFrame()
    parts = pd.DataFrame(list(q.pricing), index=q.index)
    parts["risk_class"] = q.risk_class
    cols = ["funding", "el", "capital", "opex", "margin", "discounts", "rate", "all_in", "risk_weight"]
    t = parts.groupby("risk_class")[cols].mean()
    t.insert(0, "предложений", parts.groupby("risk_class").size())
    return (100 * t[cols]).round(2).assign(предложений=t["предложений"]).reset_index()[["risk_class", "предложений", *cols]]


def capital_note(capital: dict) -> tuple[str, str]:
    """(заголовок, формула) для подхода к капиталу."""
    if capital.get("approach") == "irb":
        return ("капитал по ПВР (845-П)",
                "капитал = вес риска по ПВР (845-П, risk_weight) × норматив × (стоимость капитала − фондирование).")
    rw = capital["risk_weight"]
    return (f"капитал по плоскому весу {rw:.0%}",
            f"капитал = плоский вес риска {rw:.0%} × норматив × (стоимость капитала − фондирование).")


def real_check(df: pd.DataFrame, model, data_dir: Path, n_boot: int = 1000) -> dict | None:
    """Проверка PD-скоркарты на реальной метке ЕГРЮЛ (отложенная половина) или None, если данных ЕГРЮЛ нет."""
    egrul, comp = data_dir / "raw" / "egrul", data_dir / "fns" / "companies.csv"
    if not egrul.is_dir() or not comp.exists():
        return None
    companies = pd.read_csv(comp, dtype={"inn": str}, encoding=ENC, usecols=["inn", "status", "bfo_date"])
    label = real_label(companies, egrul)
    if label.event.sum() == 0:
        return None
    scored = pd.concat([df[["inn", "debt"]].reset_index(drop=True) if "debt" in df else
                        df[["inn"]].assign(debt=0.0).reset_index(drop=True),
                        model.score(df).reset_index(drop=True)], axis=1)
    return validate_real(scored, label, n_boot=n_boot)


def _real_section(real: dict | None) -> list:
    if real is None:
        return []
    t = real["table"].copy()
    ci = lambda g, lo, hi: "" if pd.isna(g) else f"{g:.2f} [{lo:.2f}; {hi:.2f}]"  # noqa: E731
    for col in ("gini_full", "full_lo", "full_hi", "gini_real", "real_lo", "real_hi"):
        if col not in t:
            t[col] = float("nan")
    view = pd.DataFrame({"событие": t["событие"], "компании": t["компании"], "событий": t["events"], "n": t["n"],
                         "Gini полного балла": [ci(*r) for r in t[["gini_full", "full_lo", "full_hi"]].to_numpy()],
                         "Gini реальных факторов": [ci(*r) for r in t[["gini_real", "real_lo", "real_hi"]].to_numpy()]})
    weights = "по реальной метке ЕГРЮЛ (половина «калибровка»)" if load_calibration() else "ручные"
    return ["## Проверка на реальной метке (ЕГРЮЛ, отложенная половина)", "",
            "Событие - банкротство или исключение налоговой после подачи отчёта; контроль - действующие компании; "
            "ликвидации и реорганизации не учитываются. Считается только на половине «проверка» (по хэшу ИНН), "
            f"не участвовавшей в подборе весов скрытой логики. Веса реальных слагаемых: {weights}. Реальные факторы: "
            f"{', '.join(real['real_factors'])} (без налогового долга). В скобках - 95% бутстреп-интервал.", "",
            _md(view), "", "### Доля событий по классам риска (отложенная половина)", "", _md(real["classes"]), ""]


def write_report(path: Path, fit: dict, src: str, capital: dict, real: dict | None = None):
    rep, out = fit["scorecard"], fit["assessed"]
    title, formula = capital_note(capital)
    oc = out.outcome.value_counts().reindex(OUTCOMES, fill_value=0)
    first = pd.Series([cs[0] for cs in out.reason_codes if cs]).value_counts()
    stops = pd.Series([c for cs in out.stop_codes for c in cs]).value_counts()
    routes = out[out.route.notna()].apply(lambda r: f"{r['product']} → {r.offered_product}", axis=1).value_counts()
    by_product = (out.assign(одобрено=out.outcome.isin(["APPROVE", "COUNTER"]))
                  .groupby("product").agg(заявок=("outcome", "size"), доля_предложений=("одобрено", "mean"),
                                          шанс_одобрения=("approval_probability", "mean"),
                                          ставка=("rate", "mean"), пск=("all_in", "mean")).reset_index())
    t = rep["table"].copy()
    t["Bin"] = t["Bin"].astype(str)
    at = fit["approval_table"].copy()
    lines = [
        f"# Скоринг МСБ - {date.today().isoformat()}, {title}", "",
        f"Выборка: {src}; train {rep['n_train']:,} / test {rep['n_test']:,}, "
        f"доля дефолтов {rep['dr_train']:.2%} / {rep['dr_test']:.2%}.", "",
        "## Модель 1a: PD-скоркарта (риск дефолта)", "",
        f"- Gini train {rep['gini_train']:.3f}, test {rep['gini_test']:.3f}; AUC test {rep['auc_test']:.3f}; "
        f"KS test {rep['ks_test']:.3f}",
        f"- Средний PD на test {rep['pd_mean_test']:.2%} при наблюдаемой доле {rep['dr_test']:.2%}",
        f"- Факторов в модели: {len(rep['factors'])} - {', '.join(rep['factors'])}", "",
        "### Классы риска (test)", "", _md(rep["classes"]), "",
        "## Модель 1b: вероятность одобрения (политика)", "",
        f"Обучена на {fit['approval_n']:,} решениях без дозапросов и стоп-факторов, доля одобренных "
        f"{fit['approval_rate']:.1%}. Балл = 600 + (20/ln2)·logit(p); +20 баллов - вдвое выше шансы.", "",
        _md(at, ".3f"), "",
        "## Модель 2: ставка (risk-based pricing), % годовых, среднее по предложениям", "",
        "ставка = фондирование + EL + капитал + расходы + маржа − скидки; ПСК - с комиссией и страховкой; " + formula, "",
        _md(pricing_by_class(out), ".2f"), "",
        "## По продуктам", "", _md(by_product), "",
        "## Исходы по всей выборке", "",
        _md(pd.DataFrame({"исход": oc.index, "компаний": oc.values, "доля": oc.values / max(len(out), 1)})), "",
        "## Маршрутизация вместо отказа", "",
        _md(pd.DataFrame({"маршрут": routes.index, "компаний": routes.values})), "",
        "## Главная причина (первый код)", "",
        _md(pd.DataFrame({"код": first.index, "категория": [CODES.get(c, c) for c in first.index],
                          "компаний": first.values})), "",
        "## Стоп-факторы", "",
        _md(pd.DataFrame({"код": stops.index, "категория": [STOPS[c] for c in stops.index], "компаний": stops.values})), "",
        *_real_section(real),
        "## IV факторов PD", "", _md(rep["iv"]), "",
        "## Баллы PD-скоркарты по бинам", "", _md(t, ".3f"), "",
        "_Ограничения: метка дефолта, БКИ, сезонность и поля заявки синтетические; одобрение известно только для "
        "выданных кредитов - на реальных данных нужен reject inference; параметры цены иллюстративные._", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def run(df: pd.DataFrame, pricing: dict, a, src: str) -> Path:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        engine, fit = Engine.fit(df, pricing=pricing, curves=load_curves(a.data_dir), asof=a.asof, seed=a.seed)
    engine.save(a.data_dir / "scoring" / "engine.pkl")
    out = fit["assessed"]
    flat = out.drop(columns=["stop_factors", "reasons", "requests", "pricing"]).assign(
        stop_codes=out.stop_codes.map(",".join), reason_codes=out.reason_codes.map(",".join),
        route=out.route.map(lambda r: json.dumps(r, ensure_ascii=False) if r else ""),
        requests=out.requests.map(lambda r: json.dumps(r, ensure_ascii=False)))
    flat.to_csv(a.data_dir / "scoring" / "assessed.csv", index=False, encoding=ENC)
    approach = pricing["capital"]["approach"]
    rp = a.report_dir / f"scorecard_{date.today().isoformat()}_{approach}.md"
    write_report(rp, fit, src, pricing["capital"], real_check(df, engine.scorecard, a.data_dir))
    rep = fit["scorecard"]
    print(f"[{approach}] PD: Gini test {rep['gini_test']:.3f}, KS {rep['ks_test']:.3f}, факторов {len(rep['factors'])}; "
          f"одобрение: {fit['approval_n']:,} решений; средняя ставка {out.rate.mean():.1%}, ПСК {out.all_in.mean():.1%}; "
          f"исходы: {out.outcome.value_counts().to_dict()} → {rp}")
    return rp


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--asof", type=date.fromisoformat, default=date.today())
    ap.add_argument("--capital-approach", choices=["irb", "standard", "both"],
                    help="подход к капиталу в модели 2 (по умолчанию - из config/pricing.json)")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--report-dir", type=Path, default=ROOT / "reports")
    a = ap.parse_args()
    df = pd.read_csv(a.data_dir / "scoring" / "train.csv", dtype={"inn": str, "okved": str}, encoding=ENC)
    src = "синтетика" if df.inn.str.startswith("9000").all() else "ФНС + ГИР БО + синтетика"
    a.report_dir.mkdir(parents=True, exist_ok=True)
    base = load_pricing()
    default = base["capital"].get("approach", "standard")
    if a.capital_approach == "both":  # подход из конфига - последним: его модели и решения остаются сохранёнными
        approaches = [x for x in ("irb", "standard") if x != default] + [default]
    else:
        approaches = [a.capital_approach or default]
    for approach in approaches:
        run(df, {**base, "capital": {**base["capital"], "approach": approach}}, a, src)

if __name__ == "__main__":
    main()
