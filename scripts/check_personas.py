"""
Проверка демо-компаний песочницы на обученном движке: исход каждой компании совпадает с ожиданием из её файла,
а Марина даёт числа текста защиты (слайды 07 и 12).

  py scripts/check_personas.py                         # data/scoring/engine.pkl, без него - models/engine.pkl
  py scripts/check_personas.py --engine path/engine.pkl
"""
import argparse
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.app import default_engine_path  # noqa: E402
from api.personas import application, load_personas  # noqa: E402
from scoring.whatif import Engine, evaluate, whatif  # noqa: E402

# числа Марины из текста защиты; шанс до БКИ на этих входах 57,4%, а в защите 58% (слайды 06, 07) - поправить слайды
PITCH = {"pd": 0.0163, "risk_class": 3, "score": 602, "offered_amount": 3_610_000, "rate": 0.1903, "all_in": 0.2596,
         "approval": 0.63, "approval_soft": 0.574, "rate_24": 0.197}


def _codes(r):
    return [x["code"] for x in r["stop_factors"] + r["reasons"]]


def check(engine) -> list:
    """Список расхождений: пусто - всё сходится."""
    bad = []
    for pid, p in load_personas().items():
        r = evaluate(engine, application(p, p["levers"]))
        exp = p["expect"]
        print(f"{pid:8} {r['outcome']:12} {r['offered_product'] or '-':12} {r['offered_amount']:>12,.0f}  "
              f"шанс {r['approval_probability']:.0%}  коды {_codes(r)}")
        if r["outcome"] != exp["outcome"]:
            bad.append(f"{pid}: исход {r['outcome']}, ожидался {exp['outcome']}")
        if "offered_product" in exp and r["offered_product"] != exp["offered_product"]:
            bad.append(f"{pid}: продукт {r['offered_product']}, ожидался {exp['offered_product']}")
        if "codes" in exp and _codes(r)[:len(exp["codes"])] != exp["codes"]:
            bad.append(f"{pid}: коды {_codes(r)}, ожидались {exp['codes']}")
        if "route_codes" in exp and [x["code"] for x in (r["route"] or {}).get("reasons", [])] != exp["route_codes"]:
            bad.append(f"{pid}: причины маршрута {r['route']}, ожидались {exp['route_codes']}")
    bad += marina(engine)
    return bad


def marina(engine) -> list:
    p = load_personas()["marina"]
    levers = {**p["levers"], "bki_consent": True}
    r = evaluate(engine, application(p, levers))
    soft = evaluate(engine, application(p, p["levers"]))
    t24 = {s["key"]: s for s in whatif(engine, application(p, levers))["scenarios"]}["term_24"]
    got = {"pd": r["pd"], "risk_class": r["risk_class"], "score": round(r["score"]),
           "offered_amount": r["offered_amount"], "rate": r["pricing"]["rate"], "all_in": r["pricing"]["all_in"],
           "approval": r["approval_probability"], "approval_soft": soft["approval_probability"], "rate_24": t24["rate"]}
    tol = {"pd": 0.0005, "rate": 0.0005, "all_in": 0.0005, "approval": 0.005, "approval_soft": 0.005, "rate_24": 0.0005}
    print(f"Марина: исход {r['outcome']} {_codes(r)}; на 24 мес {t24['outcome']} {t24['offered_amount']:,.0f}")
    bad = [f"marina: {k} = {got[k]}, в защите {v}" for k, v in PITCH.items() if abs(got[k] - v) > tol.get(k, 0)]
    if (r["outcome"], _codes(r)) != ("COUNTER", ["L02"]) or (t24["outcome"], t24["offered_amount"]) != ("APPROVE", 6e6):
        bad.append(f"marina: исход {r['outcome']} {_codes(r)}, на 24 мес {t24['outcome']} {t24['offered_amount']}")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", type=Path, default=default_engine_path())
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bad = check(Engine.load(a.engine))
    for b in bad:
        print("расхождение:", b)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
