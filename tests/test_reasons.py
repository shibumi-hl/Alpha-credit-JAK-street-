import pandas as pd

from scoring.reasons import CATEGORIES, FACTOR_REASON, reason_codes
from scoring.scorecard import ScoreModel
from scoring.synth import FEATURES

MAXP = {"debt_to_revenue": 60.0, "debt_to_ebit": 55.0, "turnover_months": 50.0, "bki_max_dpd_12m": 70.0,
        "revenue_cv": 40.0}
MODEL = ScoreModel(None, list(MAXP), {}, (0.0, 0.0), MAXP)


def _row(**pts):
    return pd.Series({f"points_{f}": pts.get(f, MAXP[f]) for f in MAXP})


def test_every_feature_maps_to_a_known_category():
    assert set(FEATURES) <= set(FACTOR_REASON)
    assert set(FACTOR_REASON.values()) <= set(CATEGORIES)


def test_biggest_point_loss_comes_first():
    rs = reason_codes(_row(turnover_months=20.0, bki_max_dpd_12m=60.0), MODEL)
    assert [r["code"] for r in rs] == ["R02", "R03"]
    assert rs[0]["category"] == "короткая история оборотов"
    assert rs[0]["loss"] == 30.0


def test_factors_of_one_category_are_folded_together():
    # долг/выручка −10 и долг/EBIT −15 → одна причина «высокая долговая нагрузка» с потерей 25 > 20
    rs = reason_codes(_row(debt_to_revenue=50.0, debt_to_ebit=40.0, turnover_months=30.0), MODEL)
    assert rs[0]["code"] == "R01" and rs[0]["loss"] == 25.0
    assert rs[0]["factors"] == ["debt_to_ebit", "debt_to_revenue"]
    assert rs[1]["code"] == "R02"


def test_no_loss_no_reason_and_top_limit():
    assert reason_codes(_row(), MODEL) == []
    rs = reason_codes(_row(debt_to_revenue=0.0, turnover_months=0.0, bki_max_dpd_12m=0.0, revenue_cv=0.0), MODEL, top=2)
    assert [r["code"] for r in rs] == ["R03", "R01"]
