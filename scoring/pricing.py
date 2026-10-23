"""
Модель 2 - risk-based pricing поверх PD-скоркарты:

  ставка = фондирование + EL + капитал + опер. расходы + маржа − скидки,   EL = PD × LGD × (1 − покрытие гарантии)

Фондирование - доходность G-кривой Мосбиржи на среднюю жизнь аннуитета по кривой, известной на D-1, плюс спред.
PD_12m используется как постоянная годовая интенсивность (EL в год). Капитал = RW × CAR × (CoE − фондирование),
RW - по ПВР (scoring/irb.py, 845-П): розничное МСП до 70 млн руб. с собственным LGD не ниже пола, крупнее -
корпоративное с LGD базового ПВР и залогом по п. 17.7; approach "standard" - плоский вес risk_weight.
EL считается по экономическому LGD продукта, капитал - по LGD для капитала.
ПСК (all-in) - IRR месячных потоков с комиссией за выдачу и страховкой, × 12. Параметры - config/pricing.json.
"""
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from scoring.irb import exposure_class, risk_weight

PRICING_PATH = Path(__file__).resolve().parents[1] / "config" / "pricing.json"
COMPONENTS = ("funding", "el", "capital", "opex", "margin", "discounts")


def load_pricing(path: Path = PRICING_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _annuity(amount: float, rate: float, n: int) -> float:
    r = rate / 12
    return amount / n if r == 0 else amount * r / (1 - (1 + r) ** -n)


def psk(amount: float, rate: float, term_m: int, fee: float, insurance_rate: float) -> float:
    """Полная стоимость кредита: месячная IRR × 12. Комиссия - доля суммы при выдаче, страховка - доля суммы
    в начале каждого года."""
    pay = _annuity(amount, rate, term_m)
    t = np.arange(term_m + 1)
    flows = np.full(term_m + 1, -pay)
    flows[0] = amount * (1 - fee) - amount * insurance_rate
    flows[(t % 12 == 0) & (t > 0) & (t < term_m)] -= amount * insurance_rate
    lo, hi = 0.0, 1.0
    while float(flows @ (1 + hi) ** -t) <= 0 and hi < 1e6:  # очень дорогой кредит: расширяем интервал
        lo, hi = hi, hi * 2
    for _ in range(100):
        mid = (lo + hi) / 2
        npv = float(flows @ (1 + mid) ** -t)
        lo, hi = (lo, mid) if npv > 0 else (mid, hi)  # NPV заёмщика растёт со ставкой
    return 12 * (lo + hi) / 2


def funding(cfg: dict, curves, asof: date, term_m: int) -> tuple[float, str | None]:
    """Доходность G-кривой на D-1 для средней жизни аннуитета + спред; без кривой - запасная ставка."""
    if curves is None:
        return cfg["fallback_funding"], None
    try:
        known = curves.date_of(asof - timedelta(days=1))
    except KeyError:  # дата раньше первой кривой
        return cfg["fallback_funding"], None
    life = (term_m + 1) / 2 / 12
    return float(curves.on(known).ytm(life)) + cfg["funding_spread"], known.isoformat()


def discounts(a: dict, cfg: dict) -> float:
    d = cfg["discounts"]
    turn = a.get("bank_turnover_ratio", 0) if a.get("has_rko") else 0
    out = d["bank_turnover_100"] if turn > 1 else d["bank_turnover_40"] if turn >= 0.4 else 0.0
    if a.get("subscription"):
        out += d["subscription"]
    if a.get("insurance") or a["product"] in cfg["insurance_required"]:
        out += d["insurance"]
    return out


def capital_lgd(a: dict, cfg: dict, irb_class: str) -> float:
    """LGD для капитала: корпоративное - базовый ПВР (40% и залог с дисконтом по п. 17.7), розничное - собственная
    оценка продукта не ниже пола (п. 10.9, 17.14); гарантия МСП - доля покрытия (упрощение вместо замещения риска),
    но пол LGD розницы действует и после гарантии."""
    irb, col = cfg["capital"]["irb"], cfg["capital"]["irb"]["collateral"]
    covered = min(1.0, col["value_to_loan"] * (1 - col["haircut"])) if a["product"] == "secured" else 0.0
    guaranteed = 1 - cfg["guarantee_coverage"] * bool(a.get("guarantee"))
    if irb_class == "corporate":
        return (covered * col["lgd_secured"] + (1 - covered) * irb["lgd_corporate_unsecured"]) * guaranteed
    floor = covered * col["lgd_floor_secured"] + (1 - covered) * irb["lgd_retail_floor_unsecured"]
    return max(cfg["lgd"][a["product"]] * guaranteed, floor)


def price(a: dict, pd_12m: float, cfg: dict, curves=None, asof: date = None, amount: float = None,
          all_in: bool = True) -> dict:
    """Разложение ставки; all_in=False - без ПСК (быстро, для подбора лимита)."""
    asof = asof or date.today()
    amount = float(amount or a["requested_amount"])
    term = int(a["requested_term_m"])
    fund, curve_date = funding(cfg, curves, asof, term)
    lgd = cfg["lgd"][a["product"]] * (1 - cfg["guarantee_coverage"] * bool(a.get("guarantee")))
    c = cfg["capital"]
    approach = c.get("approach", "standard")
    if approach not in ("irb", "standard"):
        raise ValueError(f"capital.approach должен быть 'irb' или 'standard', а не {approach!r}")
    if approach == "irb":
        irb_class = exposure_class(amount, c["irb"])
        lgd_cap = capital_lgd(a, cfg, irb_class)
        rw = risk_weight(pd_12m, lgd_cap, amount, a.get("revenue"), c["irb"])["rw"]
    else:
        irb_class, lgd_cap, rw = "standard", lgd, c["risk_weight"]
    parts = {
        "funding": fund,
        "el": pd_12m * lgd,
        "capital": rw * c["car"] * max(c["cost_of_equity"] - fund, 0.0),
        "opex": cfg["opex"]["rate"] + cfg["opex"]["fixed_rub_per_year"] / max(amount, 1.0),
        "margin": cfg["margin"],
        "discounts": discounts(a, cfg),
    }
    rate = max(sum(v for k, v in parts.items() if k != "discounts") - parts["discounts"], fund)
    insured = bool(a.get("insurance")) or a["product"] in cfg["insurance_required"]
    ins = cfg["insurance_rate"] if insured else 0.0
    fee = cfg["fee"][a["product"]]
    return {**parts, "rate": rate, "lgd": lgd, "risk_weight": rw, "irb_class": irb_class, "lgd_capital": lgd_cap,
            "fee": fee, "insurance_rate": ins, "curve_date": curve_date,
            "all_in": psk(amount, rate, term, fee, ins) if all_in else None}
