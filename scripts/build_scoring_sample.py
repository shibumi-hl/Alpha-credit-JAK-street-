"""
Обучающая выборка для скоринга МСБ: реальные юрлица (ФНС + ГИР БО) + синтетические поля и метка.

Реальные: оборот, возраст, ОКВЭД, долговая нагрузка, покрытие, рост выручки, налоговый долг.
Синтетика: просрочки БКИ, сезонность выручки, сумма и срок заявки, default_12m по скрытой логике.
Веса реальных слагаемых скрытой логики ручные; с --calibrated-weights - из config/synth_calibration.json
(scripts/calibrate_synth.py, подбор по банкротствам и исключениям из ЕГРЮЛ). По умолчанию не применяется:
банкротств, начавшихся после отчёта, в выборке 12 - подбор учит «закрытие фирмы», а не кредитный дефолт.

Запуск из папки проекта (после load_fns_opendata.py и load_girbo.py):
  py scripts/build_scoring_sample.py                    # из data/fns/companies.csv
  py scripts/build_scoring_sample.py --synthetic 20000  # полностью синтетическая, без загрузки ФНС

Результат: data/scoring/train.csv
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring import synth  # noqa: E402

ENC = "utf-8-sig"


def check_known_before(raw: pd.DataFrame, asof: date) -> None:
    """Правило D-1: отчётность и налоговый долг должны быть известны до даты оценки, иначе - выход с пояснением."""
    late, d = [], asof.isoformat()
    bfo = raw["bfo_date"].dropna().astype(str) if "bfo_date" in raw else pd.Series(dtype=str)
    tax = raw["debtam_date"].dropna().astype(str) if "debtam_date" in raw else pd.Series(dtype=str)
    if (bfo >= d).any():
        late.append(f"отчётность подана {bfo.max()} - пересоберите: load_girbo.py --build-only --asof {asof}")
    if (tax >= d).any():
        late.append(f"налоговый долг ФНС на {tax.max()} - срез ФНС не откатить, выберите --asof позже")
    if late:
        sys.exit(f"данные новее даты оценки {asof} (правило D-1): " + "; ".join(late))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synthetic", type=int, help="число полностью синтетических компаний")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--default-rate", type=float, default=0.05)
    ap.add_argument("--asof", type=date.fromisoformat, default=date.today())
    ap.add_argument("--calibrated-weights", action="store_true",
                    help="веса скрытой логики из config/synth_calibration.json (scripts/calibrate_synth.py)")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    a = ap.parse_args()
    meta = {"built_at": date.today().isoformat(), "asof": a.asof.isoformat()}
    if a.synthetic:
        df = synth.generate(a.synthetic, a.seed, a.asof, a.default_rate)
        src = "синтетика"
        meta.update(source="synthetic", weights="manual")
    else:
        raw = pd.read_csv(a.data_dir / "fns" / "companies.csv", dtype={"inn": str, "okved": str}, encoding=ENC)
        check_known_before(raw, a.asof)
        # веса реальных слагаемых по ЕГРЮЛ (calibrate_synth.py) - только по ключу: честных банкротств после отчёта
        # пока мало (12), подбор учит «закрытие фирмы», а не кредитный дефолт
        weights = synth.load_calibration(synth.CALIBRATION_PATH) if a.calibrated_weights else None
        df = synth.enrich(raw, a.seed, a.asof, a.default_rate, weights=weights)
        src = "ФНС + ГИР БО + синтетика, веса " + ("по реальной метке ЕГРЮЛ" if weights else "ручные")
        meta.update(source="real", weights="egrul" if weights else "manual")
    out = a.data_dir / "scoring" / "train.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding=ENC)
    (out.parent / "train_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")  # для отчёта
    print(f"{src}: {len(df):,} компаний, дефолтов {df.default_12m.sum():,} ({df.default_12m.mean():.1%}) → {out}")


if __name__ == "__main__":
    main()
