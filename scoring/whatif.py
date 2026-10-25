"""
Обе модели вместе и what-if: что изменится в шансе одобрения, решении и ставке, если поменять заявку.

Engine.fit обучает PD-скоркарту (риск), прогоняет кредитную логику со ставкой модели 2 и учит на её решениях
модель одобрения (политика). evaluate - полный ответ по заявке (JSON-готовый), whatif - базовый ответ и сценарии
с дельтами в п.п. Сценарий показывается, только если он применим к заявке.
"""
import pickle
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from scoring.approval import VERSION as APPROVAL_VERSION, ApprovalModel, approval_target, train_approval
from scoring.assess import assess
from scoring.credit import _num, load_policy, validate
from scoring.pricing import load_pricing, price
from scoring.scorecard import ScoreModel, train
from scoring.synth import FEATURES


def _turnover_ok(a):
    return bool(a.get("has_rko")) and float(a.get("bank_turnover_ratio") or 0) >= 0.4


# ключ → (что предлагаем клиенту, применимо ли (заявка, базовый ответ), изменение заявки)
SCENARIOS = {
    "collateral": ("Добавить залог недвижимости",
                   lambda a, b: a["product"] != "secured", lambda a, b: {"product": "secured"}),
    "rko_turnover": ("Открыть РКО и вести обороты в банке ≥ 40% лимита",
                     lambda a, b: not _turnover_ok(a),
                     lambda a, b: {"has_rko": 1, "bank_turnover_ratio": max(float(a.get("bank_turnover_ratio") or 0), 0.5)}),
    "guarantee": ("Получить гарантию Корпорации МСП",
                  lambda a, b: not a.get("guarantee") and a["product"] not in ("card", "overdraft"),
                  lambda a, b: {"guarantee": 1}),
    "amount_to_limit": ("Запросить сумму в пределах лимита",
                        lambda a, b: b["outcome"] == "COUNTER" and b["offered_product"] == a["product"]
                        and 0 < b["limit"] < a["requested_amount"],
                        lambda a, b: {"requested_amount": b["limit"],  # месячный оборот в банке тот же
                                      "bank_turnover_ratio": float(a.get("bank_turnover_ratio") or 0)
                                      * float(a["requested_amount"]) / b["limit"]}),
    # меньше платёж - денежного потока хватает на большую сумму; овердрафту и карте срок не нужен (возобновляемые)
    "term_24": ("Взять на 24 месяца",
                lambda a, b: a["product"] not in ("overdraft", "card") and float(a["requested_term_m"]) < 24,
                lambda a, b: {"requested_term_m": 24}),
    "marketplace": ("Подключить данные маркетплейса",
                    lambda a, b: not a.get("marketplace") and a.get("okved_section") == "G",
                    lambda a, b: {"marketplace": 1}),
    "no_insurance": ("Отказаться от страховки",
                     lambda a, b: bool(a.get("insurance")) and a["product"] != "secured",
                     lambda a, b: {"insurance": 0}),
    "add_insurance": ("Оформить страховку",
                      lambda a, b: not a.get("insurance") and a["product"] != "secured",
                      lambda a, b: {"insurance": 1}),
}


def _py(x):
    """numpy и pandas → обычные типы Python для JSON."""
    if isinstance(x, dict):
        return {k: _py(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_py(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, float) and np.isnan(x):
        return None
    return x


FLAGS = ("has_rko", "marketplace", "guarantee", "subscription", "insurance")


def _rates(df: pd.DataFrame, pds, pricing: dict, curves, asof) -> list:
    """Ставка модели цены по запрошенным продукту и сумме: по ней модель одобрения считает платёж в запасе денежного
    потока, как кредитная логика - DSCR-лимит."""
    return [price(a, float(p), pricing, curves, asof, float(a["requested_amount"]), all_in=False)["rate"]
            for a, p in zip(df.to_dict("records"), pds)]


def _derive(app: dict, policy: dict) -> dict:
    """Заявка → полный набор полей: продукт по умолчанию, флаги 0, нет признака - пусто (NaN), производные поля.
    Некорректная заявка (продукт, сумма, срок) - ValueError."""
    a = {k: (np.nan if v is None else v) for k, v in app.items()}
    a["product"] = a.get("product") if isinstance(a.get("product"), str) and a["product"] else policy["default_product"]
    validate(a, policy)
    for k in FLAGS:
        a[k] = int(bool(_num(a.get(k)))) if k in a else 0
    for k in FEATURES:
        a.setdefault(k, np.nan)
    revenue = _num(a.get("revenue"))
    a["amount_to_revenue"] = float(a["requested_amount"]) / revenue if revenue and revenue > 0 else np.nan
    a["bank_turnover_ratio"] = (_num(a.get("bank_turnover_ratio")) or 0.0) if a["has_rko"] else 0.0
    return a


@dataclass
class Engine:
    scorecard: ScoreModel
    approval: ApprovalModel
    policy: dict
    pricing: dict
    curves: object
    asof: date

    @classmethod
    def fit(cls, df: pd.DataFrame, policy=None, pricing=None, curves=None, asof: date = None, seed: int = 7,
            cv: int = 5):
        """cv - число фолдов для Gini обеих моделей в отчёте; cv < 2 - без кросс-валидации (быстрее)."""
        policy, pricing, asof = policy or load_policy(), pricing or load_pricing(), asof or date.today()
        model, rep = train(df, seed=seed, cv=cv)
        out = assess(df, model, policy, pricing=pricing, curves=curves, asof=asof)
        y = approval_target(out, df.requested_amount)
        # PD скоркарты и ставка модели цены - входы модели одобрения
        scored = df.assign(pd=out.pd.to_numpy(), rate=_rates(df, out.pd, pricing, curves, asof))
        appr, appr_rep = train_approval(scored, y, groups=out.risk_class, seed=seed, cv=cv, min_dscr=policy["min_dscr"])
        out["approval_probability"] = appr.predict(scored, stopped=(out.stop_codes.str.len() > 0).to_numpy())
        eng = cls(model, appr, policy, pricing, curves, asof)
        return eng, {"scorecard": rep, "approval": appr_rep, "assessed": out, "approval_table": appr.points_table(),
                     "approval_n": int(y.notna().sum()), "approval_rate": float(y.mean())}

    def save(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: Path) -> "Engine":
        with open(path, "rb") as f:
            eng = pickle.load(f)
        if getattr(eng.approval, "version", 0) != APPROVAL_VERSION:  # признаки другой версии (до PD, до запаса 1×)
            raise ValueError(f"{path}: модели обучены прошлой версией кода - переобучите: py scripts/train_scorecard.py")
        return eng


def evaluate(engine: Engine, app: dict) -> dict:
    a = _derive(app, engine.policy)
    df = pd.DataFrame([a])
    r = assess(df, engine.scorecard, engine.policy, pricing=engine.pricing, curves=engine.curves,
               asof=engine.asof).iloc[0]
    stopped = len(r.stop_codes) > 0
    scored = df.assign(pd=r.pd, rate=_rates(df, [r.pd], engine.pricing, engine.curves, engine.asof))
    imputed = engine.approval.imputed(scored)[0]  # soft-режим: чего не хватило, заменено средним
    return _py({
        "inn": a.get("inn"), "score": r.score, "pd": r.pd, "risk_class": r.risk_class,
        "approval_probability": float(engine.approval.predict(scored, stopped=[stopped])[0]),
        "approval_score": float(engine.approval.score(scored)[0]),
        "approval_explain": engine.approval.explain(scored.iloc[0])[:5],
        "approval_mode": "soft" if imputed else "full", "approval_imputed": imputed,
        "outcome": r.outcome, "product": r["product"], "offered_product": r.offered_product,
        "requested_amount": a["requested_amount"], "offered_amount": r.offered_amount, "limit": r.limit,
        "route": r.route, "pricing": r.pricing, "stop_factors": r.stop_factors, "reasons": r.reasons,
        "requests": r.requests,
    })


def whatif(engine: Engine, app: dict, scenarios=None) -> dict:
    app = _derive(app, engine.policy)  # сценарии видят продукт по умолчанию и флаги, как и сама оценка
    base = evaluate(engine, app)
    rate0 = (base["pricing"] or {}).get("rate")
    all0 = (base["pricing"] or {}).get("all_in")
    out = []
    for key in scenarios or SCENARIOS:
        title, applies, change = SCENARIOS[key]
        if not applies(app, base):
            continue
        r = evaluate(engine, {**app, **change(app, base)})
        rate, all_in = (r["pricing"] or {}).get("rate"), (r["pricing"] or {}).get("all_in")
        out.append(_py({
            "key": key, "title": title, "outcome": r["outcome"], "offered_product": r["offered_product"],
            "offered_amount": r["offered_amount"], "approval_probability": r["approval_probability"],
            "delta_approval_pp": 100 * (r["approval_probability"] - base["approval_probability"]),
            "pd": r["pd"], "rate": rate, "all_in": all_in,
            "delta_rate_pp": 100 * (rate - rate0) if rate is not None and rate0 is not None else None,
            "delta_all_in_pp": 100 * (all_in - all0) if all_in is not None and all0 is not None else None,
        }))
    return {"base": base, "scenarios": out}
