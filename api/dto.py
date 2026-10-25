"""
Ответы движка → контракт API песочницы (docs/dashboard-igor-spec.md §9.3): английские ключи, подписи категорий
человеческим языком, платёж в месяц и доступность продуктов. Числа не меняются - только форма.
"""
from scoring.approval import CATEGORIES, LABELS, monthly_payment
from scoring.credit import ELIGIBILITY, STOPS, eligibility, limit_codes
from scoring.reasons import CATEGORIES as REASONS

PRODUCTS = {"secured": "залоговый кредит", "express": "экспресс-кредит без залога", "overdraft": "овердрафт",
            "credit_line": "кредитная линия", "seller_credit": "кредит селлерам", "card": "бизнес-карта"}
REVOLVING = ("overdraft", "card")  # возобновляемые: срок не нужен (как сценарий «на 24 месяца» в whatif)
_FEATURE = {label: key for key, label in LABELS.items()}
_CATEGORY = {
    "product": PRODUCTS,
    "business_age": {"120+": "больше 10 лет", "60-120": "5–10 лет", "36-60": "3–5 лет", "24-36": "2–3 года",
                     "12-24": "1–2 года", "<12": "до года"},
    "bank_turnover": {"<40%": "меньше 40%", "40-100%": "40–100%", ">100%": "больше 100%"},
    "amount_share": {"<10%": "меньше 10%", "10-30%": "10–30%", ">30%": "больше 30%"},
    "bki_overdue": {"≤30 дн": "до 30 дней", ">30 дн": "больше 30 дней"},
}
FACTS = [("revenue", "Выручка за год", "rub"), ("revenue_growth", "Рост выручки", "pct"),
         ("ebit", "Прибыль до процентов и налогов", "rub"), ("debt", "Долг", "rub"),
         ("debt_service", "Обслуживание долга в год", "rub"), ("equity_ratio", "Доля собственного капитала", "pct"),
         ("tax_debt", "Налоговая задолженность", "rub"), ("age_months", "Возраст бизнеса", "months"),
         ("turnover_months", "История отчётности", "months"), ("bki_current_dpd", "Текущая просрочка в БКИ", "days"),
         ("bki_max_dpd_12m", "Наибольшая просрочка за 12 мес.", "days")]


def meta(engine) -> dict:
    pol = engine.policy
    products = [{"product": k, "label": PRODUCTS[k], "min_amount": v["min_amount"], "max_amount": v["max_amount"],
                 "min_age_months": v["min_age_months"], "requires": v["requires"], "revolving": k in REVOLVING}
                for k, v in pol["products"].items()]
    codes = [*({"code": c, "group": "S", "category": t} for c, t in STOPS.items()),
             *({"code": c, "group": "E", "category": t} for c, t in ELIGIBILITY.items()),
             *({"code": c, "group": "L", "category": t} for c, t in sorted(limit_codes(pol).items())),
             *({"code": c, "group": "R", "category": t} for c, t in REASONS.items())]
    return {"products": products, "codes": codes, "features": {k: LABELS[k] for k in (*CATEGORIES, "logit_pd",
                                                                                       "cash_cover",
                                                                                       "ln_turnover_to_payment")},
            "min_dscr": pol["min_dscr"], "round_to": pol["round_to"], "asof": str(engine.asof),
            "pricing_note": engine.pricing.get("_note", "")}


def persona_card(p: dict) -> dict:
    return {k: p[k] for k in ("id", "name", "inn", "tagline", "story", "okved_name")} | {"okved": p["facts"]["okved"]}


def persona_detail(p: dict) -> dict:
    f = p["facts"]
    facts = [{"key": k, "label": label, "value": f[k], "unit": unit, "source": "демо"} for k, label, unit in FACTS]
    return persona_card(p) | {"facts": facts, "levers": p["levers"]}


def _category_label(feature: str, category: str) -> str:
    return _CATEGORY.get(feature, {}).get(category, category.replace(".", ","))


def evaluation(r: dict, derived: dict, policy: dict) -> dict:
    """r - evaluate(), derived - заявка после _derive (для доступности продуктов)."""
    explain = []
    for x in r["approval_explain"]:
        f = _FEATURE[x["признак"]]
        explain.append({"feature": f, "label": x["признак"], "category": x["категория"],
                        "category_label": _category_label(f, x["категория"]), "points": x["баллы"]})
    q = r["pricing"]
    term = int(derived["requested_term_m"])
    pay = monthly_payment(r["offered_amount"], q["rate"], term) if q and r["offered_amount"] else None
    products = [{"product": k, "label": PRODUCTS[k], "available": not (why := eligibility(derived, k, policy)),
                 "reasons": why} for k in policy["products"]]
    return {**{k: v for k, v in r.items() if k != "approval_explain"}, "approval_explain": explain,
            "approval_imputed_labels": [LABELS[k] for k in r["approval_imputed"]], "requested_term_m": term,
            "monthly_payment": float(pay) if pay is not None else None, "products": products}
