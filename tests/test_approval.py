import math
import warnings
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scoring import synth
from scoring.approval import (BASE, CATEGORIES, CONTINUOUS, FACTOR, LABELS, SIGNS, ApprovalModel, approval_target,
                              bin_application, cash_flow, train_approval)
from scoring.assess import assess
from scoring.credit import load_policy
from scoring.scorecard import train

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def fitted():
    df = synth.generate(15000, seed=31, asof=date(2026, 10, 22))
    model, _ = train(df, seed=3)
    out = assess(df, model, load_policy())
    df = df.assign(pd=out.pd.to_numpy())
    y = approval_target(out, df.requested_amount)
    m, rep = train_approval(df, y, groups=out.risk_class, seed=3)
    return df, out, y, m, rep


def _apps(**cols):
    n = len(next(iter(cols.values())))
    base = {"product": ["express"] * n, "age_months": [60.0] * n, "has_rko": [0] * n, "bank_turnover_ratio": [0.0] * n,
            "amount_to_revenue": [0.05] * n, "marketplace": [0] * n, "guarantee": [0] * n, "bki_max_dpd_12m": [0.0] * n}
    return pd.DataFrame({**base, **cols})


def test_target_counts_only_real_approvals():
    out = pd.DataFrame({
        "outcome": ["APPROVE", "COUNTER", "COUNTER", "COUNTER", "REJECT", "REQUEST_INFO", "REJECT"],
        "product": ["express"] * 7,
        "offered_product": ["express", "express", "express", "card", "", "", ""],
        "offered_amount": [1e6, 6e5, 3e5, 5e5, 0, 0, 0],
        "stop_codes": [[], [], [], [], [], [], ["S01"]]})
    y = approval_target(out, pd.Series([1e6] * 7))
    assert y.tolist()[:5] == [1, 1, 0, 0, 0]  # контр < 50% и маршрут на другой продукт - не одобрение
    assert y.iloc[5:].isna().all()  # дозапрос и стоп-фактор вне обучения


def test_age_bins_fit_a_sample_of_mature_companies():
    b = bin_application(_apps(age_months=[5, 11, 12, 23, 24, 35, 36, 59, 60, 119, 120, 300]))
    assert b.business_age.tolist() == ["<12", "<12", "12-24", "12-24", "24-36", "24-36", "36-60", "36-60",
                                       "60-120", "60-120", "120+", "120+"]
    assert CATEGORIES["business_age"][1] == "120+"


def test_missing_inputs_have_no_category():
    b = bin_application(_apps(age_months=[np.nan, 30.0], bki_max_dpd_12m=[np.nan, 0.0], amount_to_revenue=[0.2, np.nan]))
    assert b.business_age.isna().tolist() == [True, False]
    assert b.bki_overdue.isna().tolist() == [True, False]  # нет БКИ - не «нет просрочек»
    assert b.amount_share.isna().tolist() == [False, True]


def test_rare_ordered_category_takes_its_neighbours_effect(fitted):
    _, _, _, m, _ = fitted
    assert m.counts["business_age=<12"] < 30  # в синтетике моложе 12 месяцев компаний нет
    assert m.coef["business_age=<12"] == m.coef["business_age=12-24"]
    t = m.points_table()
    assert t[(t.категория == "<12") & (t.признак == LABELS["business_age"])].комментарий.str.contains("мало данных").all()


def test_signs_follow_business_sense(fitted):
    _, _, _, m, _ = fitted
    c = m.coef
    for f, (cats, ref) in CATEGORIES.items():
        effects = [0.0] + [c[f"{f}={k}"] for k in cats if k != ref]
        if f == "product":  # залог не снижает шанс: остальные продукты не выше залогового
            assert max(effects[1:]) <= 0
        elif SIGNS[f] > 0:
            assert all(b >= a for a, b in zip(effects, effects[1:])), f
        else:
            assert all(b <= a for a, b in zip(effects, effects[1:])), f
    for f, sign in CONTINUOUS.items():
        assert sign * c[f] >= 0, f


def test_constraint_holds_even_when_data_say_otherwise(fitted):
    df = fitted[0]
    rng = np.random.default_rng(0)
    late = (df.bki_max_dpd_12m > 0).to_numpy()
    y = pd.Series(np.where(late, rng.random(len(df)) < 0.8, rng.random(len(df)) < 0.2).astype(float), index=df.index)
    m = ApprovalModel.fit(df, y)
    assert m.coef["bki_overdue=≤30 дн"] <= 0 and m.coef["bki_overdue=>30 дн"] <= 0
    row = df[late].iloc[[0]]
    assert m.predict(row)[0] <= m.predict(row.assign(bki_max_dpd_12m=0))[0]


def test_pd_cash_flow_and_payment_move_the_chance(fitted):
    df, _, _, m, _ = fitted
    row = df.iloc[[0]].assign(product="express", requested_term_m=24, debt_service=0.0)

    def p(**kw):
        return m.predict(row.assign(**kw))[0]

    assert p(pd=0.01) > p(pd=0.05) > p(pd=0.2)
    rev = float(row.revenue.iloc[0])
    assert p(ebit=0.3 * rev) > p(ebit=0.05 * rev) > p(ebit=-0.05 * rev)
    amounts = [0.05 * rev, 0.2 * rev, 0.6 * rev]
    chances = [p(requested_amount=a, amount_to_revenue=a / rev) for a in amounts]
    assert chances[0] > chances[1] > chances[2]


def test_holdout_metrics_show_what_pd_and_cash_flow_add(fitted):
    _, _, y, m, rep = fitted
    n = int(y.notna().sum())
    assert rep["n_train"] + rep["n_test"] == n and rep["n_test"] == pytest.approx(0.3 * n, abs=1)
    assert m.n == rep["n_train"]  # модель видит только train
    assert rep["gini_test"] > rep["gini_test_categories"] + 0.1
    assert rep["brier_test"] < rep["brier_const"]
    cls = rep["classes"]
    assert {"risk_class", "n", "факт", "прогноз"} <= set(cls.columns) and cls.n.sum() == rep["n_test"]
    assert (cls.прогноз - cls.факт).abs().max() < 0.1  # шанс откалиброван и внутри классов риска


def test_soft_mode_imputes_missing_inputs_neutrally(fitted):
    df, _, y, _, _ = fitted
    sub, ys = df[y.notna()], y[y.notna()]
    m = ApprovalModel.fit(sub, ys)
    row = sub.iloc[[0]]
    assert m.imputed(row) == [[]]
    soft = row.assign(bki_max_dpd_12m=np.nan, pd=np.nan)
    assert m.imputed(soft) == [["bki_overdue", "logit_pd"]]
    assert 0 < m.predict(soft)[0] < 1
    # пропуск = средний вклад признака по обучающей выборке, а не «лучшее» значение
    variants = pd.concat([row] * len(sub)).assign(bki_max_dpd_12m=sub.bki_max_dpd_12m.to_numpy(), pd=sub.pd.to_numpy())
    assert m.logit(soft)[0] == pytest.approx(m.logit(variants).mean())
    shown = {x["признак"]: x["категория"] for x in m.explain(soft.iloc[0])}
    assert shown[LABELS["bki_overdue"]] == "нет данных" and shown[LABELS["logit_pd"]] == "нет данных"


def test_cash_flow_multiples_match_a_hand_calculation():
    # 1,2 млн на 12 мес. под 22,5%: аннуитет 112 602,22 руб. в месяц
    app = pd.DataFrame({"revenue": [12e6], "ebit": [2.5e6], "debt_service": [0.5e6], "requested_amount": [1.2e6],
                        "requested_term_m": [12], "pd": [0.02]})
    cf = cash_flow(app).iloc[0]
    assert cf.cover == pytest.approx((2.5e6 / 1.25 - 0.5e6) / (12 * 112_602.22), rel=1e-6)  # 1,11× годового платежа
    assert cf.turnover == pytest.approx(1e6 / 112_602.22, rel=1e-6)  # 8,88× месячного платежа
    assert cf["pd"] == 0.02


def test_infinite_inputs_count_as_missing(fitted):
    df, _, _, m, _ = fitted
    row = df.iloc[[0]]
    inf = row.assign(ebit=np.inf, bki_max_dpd_12m=np.inf)  # как в кредитной логике: бесконечность - не число
    assert m.imputed(inf) == [["bki_overdue", "cash_cover"]]
    assert m.predict(inf)[0] == pytest.approx(m.predict(row.assign(ebit=np.nan, bki_max_dpd_12m=np.nan))[0])


def test_zero_or_negative_revenue_is_the_worst_case_not_missing(fitted):
    df, _, _, m, _ = fitted
    row = df.iloc[[0]]
    amount = float(row.requested_amount.iloc[0])

    def app(rev):
        return row.assign(revenue=rev, amount_to_revenue=amount / rev if rev > 0 else np.nan)

    assert m.imputed(app(0.0)) == [[]] and m.imputed(app(-5e6)) == [[]]
    assert bin_application(app(0.0)).amount_share.iloc[0] == ">30%"
    assert m.predict(app(0.0))[0] <= m.predict(app(1.0))[0]
    assert m.predict(app(-5e6))[0] <= m.predict(app(1.0))[0]


def test_too_few_decisions_raise_a_clear_error(fitted):
    df = fitted[0]
    y = pd.Series(np.nan, index=df.index)
    y.iloc[:200] = 1.0
    with pytest.raises(ValueError, match="одобрений и .* отказов"):
        train_approval(df, y)
    y.iloc[:3] = 0.0
    with pytest.raises(ValueError, match="одобрений и .* отказов"):
        train_approval(df, y)


def test_points_and_score_follow_the_pdo_scale(fitted):
    df, _, _, m, _ = fitted
    t = m.points_table()
    assert np.allclose(t.баллы, FACTOR * t.beta)
    assert set(LABELS[f] for f in CONTINUOUS) <= set(t.признак)
    assert FACTOR == pytest.approx(20 / math.log(2))
    s, lg = m.score(df.head(50)), m.logit(df.head(50))
    assert np.allclose(s, BASE + FACTOR * lg)
    p = m.predict(df.head(50))
    assert ((p > 0) & (p < 1)).all()
    assert (m.predict(df.head(50), stopped=np.ones(50)) == 0).all()


def test_explanation_sums_to_score(fitted):
    df, _, _, m, _ = fitted
    row = df.iloc[0]
    parts = m.explain(row)
    assert {x["признак"] for x in parts} == {LABELS[f] for f in [*CATEGORIES, *CONTINUOUS]}
    assert [abs(p["баллы"]) for p in parts] == sorted((abs(p["баллы"]) for p in parts), reverse=True)
    total = BASE + FACTOR * m.intercept + sum(p["баллы"] for p in parts)
    assert total == pytest.approx(m.score(df.iloc[[0]])[0])


def test_bins_follow_category_lists(fitted):
    df = fitted[0]
    b = bin_application(df)
    for f, (cats, _) in CATEGORIES.items():
        assert set(b[f]) <= set(cats)


def test_save_load(fitted, tmp_path):
    df, _, _, m, _ = fitted
    m.save(tmp_path / "a.pkl")
    assert np.allclose(ApprovalModel.load(tmp_path / "a.pkl").predict(df.head(20)), m.predict(df.head(20)))
