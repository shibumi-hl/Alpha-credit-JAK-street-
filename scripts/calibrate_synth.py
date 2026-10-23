"""
Подбор весов реальных слагаемых скрытой логики дефолта по реальной метке ЕГРЮЛ.

Метка: банкротство или исключение налоговой после подачи отчёта (scoring/realcheck.py). Подбор - только на
половине компаний «калибровка» (по хэшу ИНН); вторая половина остаётся для честной проверки в отчёте
train_scorecard.py. Налоговый долг не подбирается (срез ФНС бывает позже события). Банкротство весит в
--bankruptcy-weight раз больше исключения налоговой: исключают в основном брошенные фирмы без долгов, и без
перевеса модель учит «закрытие фирмы», а не кредитный дефолт.

Запуск из папки проекта (после load_girbo.py и load_egrul.py):
  py scripts/calibrate_synth.py
  py scripts/build_scoring_sample.py --calibrated-weights   # выборка на подобранных весах (по умолчанию - ручные)
  py scripts/train_scorecard.py --capital-approach both

Результат: config/synth_calibration.json (веса, отраслевые сдвиги, число событий, дата).
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
from scoring.calibrate import FIT_TERMS, fit_weights  # noqa: E402
from scoring.egrul import BANKRUPTCY  # noqa: E402
from scoring.realcheck import CALIBRATION, real_label  # noqa: E402

ENC = "utf-8-sig"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--c", type=float, default=1.0, help="обратная сила L2-регуляризации")
    ap.add_argument("--bankruptcy-weight", type=float, default=5.0, help="вес банкротства относительно исключения")
    ap.add_argument("--asof", type=date.fromisoformat, default=date.today())
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--out", type=Path, default=synth.CALIBRATION_PATH)
    a = ap.parse_args()
    raw = pd.read_csv(a.data_dir / "fns" / "companies.csv", dtype={"inn": str, "okved": str}, encoding=ENC)
    label = real_label(raw, a.data_dir / "raw" / "egrul")
    label = label[label["half"] == CALIBRATION]
    part = raw.merge(label[["inn", "event", "kind"]], on="inn")
    if part.event.sum() == 0:
        sys.exit("в половине «калибровка» нет событий (банкротств или исключений после отчёта) - "
                 "сначала соберите ЕГРЮЛ: py scripts/load_egrul.py")
    f = synth.features(part, a.asof)
    sw = (part.kind == BANKRUPTCY).map({True: a.bankruptcy_weight, False: 1.0}).to_numpy()
    res = fit_weights(synth.real_terms(f), f.okved_section, part.event, c=a.c, sample_weight=sw)
    out = {"source": "ЕГРЮЛ: банкротство или исключение налоговой после подачи отчёта; половина «калибровка»",
           "fitted_at": date.today().isoformat(), "half": CALIBRATION, "n": len(part), "events": int(part.event.sum()),
           "by_kind": part[part.event == 1].kind.value_counts().to_dict(), "bankruptcy_weight": a.bankruptcy_weight,
           "c": a.c, **res}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"калибровка: {out['n']:,} компаний, событий {out['events']} {out['by_kind']}; выброшены {res['dropped']}")
    for t in FIT_TERMS:
        print(f"  {t:12s} было {synth.DEFAULT_WEIGHTS[t]:5.2f}  стало {res['weights'][t]:5.2f}")
    print(f"→ {a.out}")


if __name__ == "__main__":
    main()
