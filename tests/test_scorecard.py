import warnings
from datetime import date

import numpy as np
import pytest

from scoring import synth
from scoring.scorecard import ScoreModel, train

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def fitted():
    df = synth.generate(20000, seed=11, asof=date(2026, 10, 20))
    model, rep = train(df, seed=7)
    return df, model, rep


def test_model_uses_8_to_12_factors_and_discriminates(fitted):
    _, model, rep = fitted
    assert 8 <= len(model.factors) <= 12
    assert rep["gini_test"] > 0.3  # синтетика с шумом NOISE; цель 0.55-0.65 - на реальной выборке
    assert rep["ks_test"] > 0.2
    assert set(rep["iv"].name) >= set(model.factors)


def test_points_sum_to_score_and_higher_score_is_safer(fitted):
    df, model, _ = fitted
    s = model.score(df.head(2000))
    pts = s[[f"points_{f}" for f in model.factors]].sum(axis=1)
    assert np.allclose(pts, s.score)
    order = s.sort_values("score")
    assert order.pd.is_monotonic_decreasing
    assert order.risk_class.is_monotonic_decreasing


def test_pd_grows_with_risk_class_and_matches_observed(fitted):
    _, _, rep = fitted
    by = rep["classes"]
    assert list(by.risk_class) == sorted(by.risk_class)
    seen = by[by["count"] >= 100]
    assert seen.pd_mean.is_monotonic_increasing
    assert seen.default_rate.iloc[-1] > seen.default_rate.iloc[0]
    assert rep["pd_mean_test"] == pytest.approx(rep["dr_test"], abs=0.01)


def test_max_points_bound_each_factor(fitted):
    df, model, _ = fitted
    s = model.score(df.head(2000))
    for f in model.factors:
        assert (s[f"points_{f}"] <= model.max_points[f] + 1e-9).all()


def test_save_load_round_trip(fitted, tmp_path):
    df, model, _ = fitted
    p = tmp_path / "m.pkl"
    model.save(p)
    again = ScoreModel.load(p)
    assert np.allclose(again.score(df.head(500)).score, model.score(df.head(500)).score)


def test_too_few_informative_factors_is_an_error():
    df = synth.generate(3000, seed=5, asof=date(2026, 10, 20))
    with pytest.raises(ValueError, match="факторов"):
        train(df, features=["revenue", "age_months", "dscr"], seed=1)


def test_required_factors_kept_when_informative(fitted):
    _, model, rep = fitted
    iv = rep["iv"].set_index("name").iv
    for f in ("turnover_months", "product"):
        if iv[f] >= 0.02:
            assert f in model.factors
