import math
import warnings
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scoring import synth
from scoring.approval import BASE, CATEGORIES, FACTOR, ApprovalModel, approval_target, bin_application
from scoring.assess import assess
from scoring.credit import load_policy
from scoring.scorecard import train

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def fitted():
    df = synth.generate(15000, seed=31, asof=date(2026, 10, 22))
    model, _ = train(df, seed=3)
    out = assess(df, model, load_policy())
    y = approval_target(out, df.requested_amount)
    return df, out, y, ApprovalModel.fit(df, y)


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


def test_reference_and_rare_categories_have_no_column(fitted):
    _, _, _, m = fitted
    for f, (cats, ref) in CATEGORIES.items():
        assert f"{f}={ref}" not in m.columns
    assert all(m.counts[c] >= 30 for c in m.columns)
    assert "business_age=<9" not in m.columns  # в выборке таких нет - эффект не оценивается


def test_points_and_score_follow_the_pdo_scale(fitted):
    df, _, _, m = fitted
    t = m.points_table()
    est = t[t.комментарий == ""]
    assert np.allclose(est.баллы, FACTOR * est.beta)
    assert FACTOR == pytest.approx(20 / math.log(2))
    s, lg = m.score(df.head(50)), m.logit(df.head(50))
    assert np.allclose(s, BASE + FACTOR * lg)
    p = m.predict(df.head(50))
    assert ((p > 0) & (p < 1)).all()
    assert (m.predict(df.head(50), stopped=np.ones(50)) == 0).all()


def test_explanation_sums_to_score(fitted):
    df, _, _, m = fitted
    row = df.iloc[0]
    parts = m.explain(row)
    assert [abs(p["баллы"]) for p in parts] == sorted((abs(p["баллы"]) for p in parts), reverse=True)
    total = BASE + FACTOR * m.intercept + sum(p["баллы"] for p in parts)
    assert total == pytest.approx(m.score(df.iloc[[0]])[0])


def test_large_amount_and_overdue_lower_approval(fitted):
    _, _, _, m = fitted
    assert m.coef["amount_share=>30%"] < m.coef["amount_share=10-30%"] < 0
    assert m.coef["bki_overdue=≤30 дн"] < 0


def test_bins_follow_category_lists(fitted):
    df, _, _, _ = fitted
    b = bin_application(df)
    for f, (cats, _) in CATEGORIES.items():
        assert set(b[f]) <= set(cats)


def test_save_load(fitted, tmp_path):
    df, _, _, m = fitted
    m.save(tmp_path / "a.pkl")
    assert np.allclose(ApprovalModel.load(tmp_path / "a.pkl").predict(df.head(20)), m.predict(df.head(20)))
