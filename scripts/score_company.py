"""
Скоринг одной заявки: PD и класс риска, шанс одобрения, решение или маршрут, ставка с разложением, ПСК,
причины и what-if.

Запуск из папки проекта (после train_scorecard.py):
  py scripts/score_company.py --inn 7736328675                  # компания из data/scoring/train.csv
  py scripts/score_company.py --inn 7736328675 --whatif         # + сценарии: залог, РКО, гарантия, …
  py scripts/score_company.py --json app.json --whatif --format json   # ответ JSON (например, для n8n)
"""
import argparse
import json
import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring.whatif import Engine, evaluate, whatif  # noqa: E402

ENC = "utf-8-sig"
NAMES = {"APPROVE": "одобрение", "COUNTER": "контрпредложение", "REQUEST_INFO": "дозапрос документов",
         "REJECT": "отказ"}
PRODUCTS = {"secured": "залоговый кредит", "express": "экспресс-кредит без залога", "overdraft": "овердрафт",
            "credit_line": "кредитная линия", "seller_credit": "кредит селлерам", "card": "бизнес-карта"}
PARTS = [("funding", "фондирование (G-кривая + спред)"), ("el", "ожидаемые потери PD×LGD"), ("capital", "капитал"),
         ("opex", "расходы"), ("margin", "маржа"), ("discounts", "скидки")]


def pp(x):
    return "—" if x is None else f"{x:+.1f} п.п."


def print_text(r: dict, scenarios=None):
    print(f"ИНН {r['inn']}: PD {r['pd']:.2%}, класс риска {r['risk_class']} (балл {r['score']:.0f})")
    print(f"Шанс одобрения: {r['approval_probability']:.0%} (балл одобрения {r['approval_score']:.0f})")
    for x in r["approval_explain"]:
        if abs(x["баллы"]) >= 0.5:
            print(f"  {x['признак']}: {x['категория']} {x['баллы']:+.0f}")
    print(f"Заявка: {PRODUCTS[r['product']]}, {r['requested_amount']:,.0f} руб.; лимит {r['limit']:,.0f} руб.")
    offer = f" — {PRODUCTS.get(r['offered_product'], '')} на {r['offered_amount']:,.0f} руб." if r["offered_amount"] else ""
    print(f"Решение: {r['outcome']} ({NAMES[r['outcome']]}){offer}")
    if r["route"]:
        why = "; ".join(x["category"] for x in r["route"]["reasons"])
        print(f"  продукт «{PRODUCTS[r['route']['from']]}» недоступен: {why}")
    for s in r["stop_factors"]:
        print(f"  стоп-фактор {s['code']}: {s['category']}")
    label = "снижает балл" if r["outcome"] == "APPROVE" else "причина"
    for x in r["reasons"]:
        loss = f" (−{x['loss']:.1f} балла)" if x.get("loss") else ""
        print(f"  {label} {x['code']}: {x['category']}{loss}")
    for q in r["requests"]:
        print(f"  запросить: {q}")
    p = r["pricing"]
    if p:
        print(f"Ставка {p['rate']:.2%} = " + " ".join(
            f"{'−' if k == 'discounts' else '+'} {p[k]:.2%} {name}" for k, name in PARTS).lstrip("+ "))
        print(f"Честная ставка (ПСК) {p['all_in']:.2%}: комиссия {p['fee']:.1%}, страховка {p['insurance_rate']:.1%} в год")
        kind = {"retail": "розничное МСП", "corporate": "корпоративное, базовый ПВР", "standard": "стандартный подход"}
        print(f"Капитал: вес риска {p['risk_weight']:.0%} ({kind[p['irb_class']]}), LGD для капитала {p['lgd_capital']:.0%}")
    for s in scenarios or []:
        rate = f"ставка {s['rate']:.1%} ({pp(s['delta_rate_pp'])}), ПСК {s['all_in']:.1%} ({pp(s['delta_all_in_pp'])})" \
            if s["rate"] is not None else "без предложения"
        print(f"  что если: {s['title']} → одобрение {s['approval_probability']:.0%} ({pp(s['delta_approval_pp'])}), "
              f"{NAMES[s['outcome']]}, {rate}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--inn")
    g.add_argument("--json", type=Path)
    ap.add_argument("--whatif", action="store_true")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")  # в файл/пайп Windows пишет cp1251: «−», «→», «≥» не должны ронять вывод
    engine = Engine.load(a.data_dir / "scoring" / "engine.pkl")
    if a.inn:
        df = pd.read_csv(a.data_dir / "scoring" / "train.csv", dtype={"inn": str, "okved": str}, encoding=ENC)
        df = df[df.inn == a.inn]
        if df.empty:
            sys.exit(f"ИНН {a.inn} нет в data/scoring/train.csv")
        app = df.iloc[0].to_dict()
    else:
        app = json.loads(a.json.read_text(encoding="utf-8"))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = whatif(engine, app) if a.whatif else {"base": evaluate(engine, app), "scenarios": []}
    except ValueError as e:  # некорректная заявка: понятная ошибка вместо трейсбека
        if a.format == "json":
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            print(f"Ошибка в заявке: {e}", file=sys.stderr)
        sys.exit(2)
    if a.format == "json":
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print_text(res["base"], res["scenarios"])


if __name__ == "__main__":
    main()
