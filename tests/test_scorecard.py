import warnings
from datetime import date

import numpy as np
import pytest

import scoring.scorecard as S
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


def test_cross_validation_scores_each_company_once_out_of_fold(fitted):
    df, _, rep = fitted
    cv = rep["cv"]
    assert list(cv.fold) == [1, 2, 3, 4, 5] and cv.n_test.sum() == len(df)  # каждая компания - ровно в одном тесте
    assert cv.gini_test.mean() == pytest.approx(rep["gini_test"], abs=0.1)
    assert cv.dr_test.between(0.03, 0.07).all()  # фолды стратифицированы по дефолту


def test_held_out_fold_never_reaches_selection_binning_or_fit(fitted, monkeypatch):
    df = fitted[0]
    seen = {"select": [], "fit": []}
    real_select, real_fit = S.select_factors, S._fit

    def select(tr, *a, **k):  # отбор по IV - биннинг на этих строках
        seen["select"].append(tr.index)
        return real_select(tr, *a, **k)

    def fit(tr, *a, **k):  # биннинг и регрессия скоркарты
        seen["fit"].append(tr.index)
        return real_fit(tr, *a, **k)

    monkeypatch.setattr(S, "select_factors", select)
    monkeypatch.setattr(S, "_fit", fit)
    cv = S.cross_validate(df)
    held = [df.index.difference(ix) for ix in seen["fit"]]
    assert [len(h) for h in held] == list(cv.n_test)
    assert sum(map(len, held)) == len(df) == len(set().union(*map(set, held)))  # фолды не пересекаются, покрывают всё
    assert len(seen["select"]) == 5 and all(s.equals(f) for s, f in zip(seen["select"], seen["fit"]))


def test_fold_with_too_few_factors_is_not_scored(fitted, monkeypatch):
    monkeypatch.setattr(S, "MIN_FACTORS", 99)  # train() такую модель не принял бы
    cv = S.cross_validate(fitted[0].sample(5000, random_state=1))
    assert cv.gini_test.isna().all() and cv.gini_train.isna().all() and (cv.factors > 0).all()


def test_cross_validation_needs_a_default_in_every_fold_and_can_be_off(fitted):
    df = fitted[0]
    few = df[df.default_12m == 0].iloc[:3000].copy()
    few.iloc[:4, few.columns.get_loc("default_12m")] = 1  # 4 дефолта на 5 фолдов
    with pytest.raises(ValueError, match="не меньше 5 дефолтов"):
        S.cross_validate(few)
    assert S.cross_validate(df, k=0).empty


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
