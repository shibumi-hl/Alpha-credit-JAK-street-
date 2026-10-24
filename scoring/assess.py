"""Полная оценка заявок: балл и PD скоркарты → коды причин → кредитное решение → цена (модель 2)."""
import numpy as np
import pandas as pd

from scoring.credit import decide
from scoring.pricing import price
from scoring.reasons import reason_codes

OUTCOMES = ("APPROVE", "COUNTER", "REQUEST_INFO", "REJECT")
_FIELDS = ["revenue", "ebit", "debt_service", "age_months", "turnover_months", "bki_current_dpd", "bki_max_dpd_12m",
           "tax_debt_to_revenue", "okved_section", "okved", "status", "requested_amount", "requested_term_m",
           "product", "has_rko", "marketplace", "bank_turnover_ratio", "guarantee", "subscription", "insurance"]


def assess(df: pd.DataFrame, model, policy: dict, top: int = 3, pricing: dict = None, curves=None,
           asof=None) -> pd.DataFrame:
    """С pricing ставка модели 2 идёт в DSCR-лимит каждого пробуемого продукта, а предложение получает
    разложение ставки и ПСК; без pricing - ставка по классу из политики, без цены."""
    scored = model.score(df)
    rows = []
    for (_, a), (_, s) in zip(df.iterrows(), scored.iterrows()):
        app = {k: a.get(k) for k in _FIELDS}
        reasons = reason_codes(s, model, top, a)
        rate_fn = None
        if pricing is not None:
            def rate_fn(product, _cls, amount, app=app, pd_=float(s.pd)):
                return price({**app, "product": product}, pd_, pricing, curves, asof, amount, all_in=False)["rate"]
        d = decide(app, int(s.risk_class), reasons, policy, rate_fn)
        quote = None
        if pricing is not None and d.offered_amount > 0:
            quote = price({**app, "product": d.offered_product}, float(s.pd), pricing, curves, asof, d.offered_amount)
        rows.append({"inn": a.get("inn"), "score": s.score, "pd": s.pd, "risk_class": int(s.risk_class),
                     "outcome": d.outcome, "limit": d.limit, "offered_amount": d.offered_amount,
                     "product": d.product, "offered_product": d.offered_product, "route": d.route,
                     "rate": quote["rate"] if quote else np.nan, "all_in": quote["all_in"] if quote else np.nan,
                     "pricing": quote,
                     "stop_codes": [x["code"] for x in d.stop_factors], "reason_codes": [x["code"] for x in d.reasons],
                     "stop_factors": d.stop_factors, "reasons": d.reasons, "requests": d.requests})
    return pd.DataFrame(rows, index=df.index)
