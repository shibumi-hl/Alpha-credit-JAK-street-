"""
Цифры презентации по выборке движка (слайды «Конвейер» и «Деньги»): исходы кредитной логики, маршруты на другой
продукт вместо отказа, предложенный объём и маржа с объёма, который обычный процесс отклонил бы.

Вход - data/scoring/assessed.csv (его пишет scripts/train_scorecard.py: решение движка по каждой компании выборки).
Суммы заявок в выборке синтетические, поэтому рубли иллюстративны, доли устойчивее.

  py scripts/pitch_numbers.py
  py scripts/pitch_numbers.py --assessed path/assessed.csv --margin 0.02
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTCOMES = ("APPROVE", "COUNTER", "REQUEST_INFO", "REJECT")


def figures(df: pd.DataFrame, margin: float = 0.02) -> dict:
    """Исходы (число, доля), контрпредложения тем же и другим продуктом, предложенный объём в млрд ₽ и маржа в год
    с объёма контрпредложений (без учёта амортизации)."""
    n = len(df)
    counts = df.outcome.value_counts()
    co = df[df.outcome == "COUNTER"]
    route = co.offered_product != co["product"]
    bn = lambda s: float(s.offered_amount.sum()) / 1e9  # noqa: E731
    approved, counter = bn(df[df.outcome == "APPROVE"]), bn(co)
    return {
        "companies": n,
        "outcomes": {o: (int(counts.get(o, 0)), float(counts.get(o, 0)) / n) for o in OUTCOMES},
        "counter_same": int((~route).sum()), "counter_route": int(route.sum()),
        "approved_bn": approved, "counter_bn": counter, "offered_bn": approved + counter,
        "counter_share": counter / (approved + counter) if approved + counter else 0.0,
        "margin_on_counter_bn": margin * counter,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assessed", type=Path, default=ROOT / "data" / "scoring" / "assessed.csv")
    ap.add_argument("--margin", type=float, default=0.02, help="маржа в ставке, доля (config/pricing.json: margin)")
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")
    if not a.assessed.exists():
        sys.exit(f"нет {a.assessed} - сначала py scripts/train_scorecard.py")
    f = figures(pd.read_csv(a.assessed, encoding="utf-8-sig"), a.margin)
    print(f"Компаний: {f['companies']:,}".replace(",", " "))
    for o, (k, s) in f["outcomes"].items():
        print(f"  {o:12} {k:6}  {s:.1%}")
    print(f"Контрпредложения: {f['counter_same']} - меньшая сумма того же продукта, {f['counter_route']} - другой продукт")
    print(f"Предложено {f['offered_bn']:.1f} млрд ₽: одобрения {f['approved_bn']:.1f} + контрпредложения и другой продукт "
          f"{f['counter_bn']:.1f} ({f['counter_share']:.0%})")
    print(f"Маржа {a.margin:.0%} в год с {f['counter_bn']:.1f} млрд ₽: {f['margin_on_counter_bn']:.2f} млрд ₽ (без амортизации)")


if __name__ == "__main__":
    main()
