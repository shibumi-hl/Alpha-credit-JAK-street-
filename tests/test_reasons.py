import warnings
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scoring import synth
from scoring.assess import assess
from scoring.credit import KEY_DATA, load_policy
from scoring.reasons import CATEGORIES, FACTOR_REASON, reason_codes
from scoring.scorecard import ScoreModel, train
from scoring.synth import FEATURES

warnings.filterwarnings("ignore")
BKI = ["bki_max_dpd_12m", "bki_overdue_cnt_12m", "bki_current_dpd"]

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


def test_factor_with_missing_value_gives_no_reason():
    # просрочки неизвестны (None/NaN) - баллы нейтральные, но о просрочках это ничего не говорит
    pts = _row(turnover_months=20.0, bki_max_dpd_12m=60.0)
    for unknown in (None, np.nan):
        rs = reason_codes(pts, MODEL, app={"turnover_months": 12, "bki_max_dpd_12m": unknown})
        assert [r["code"] for r in rs] == ["R02"]
    rs = reason_codes(pts, MODEL, app={"turnover_months": 12, "bki_max_dpd_12m": 0})
    assert [r["code"] for r in rs] == ["R02", "R03"]


@pytest.fixture(scope="module")
def synth_model():
    df = synth.generate(8000, seed=21, asof=date(2026, 10, 20))
    model, _ = train(df, seed=3, cv=0)
    return df, model


def test_application_without_credit_history_has_no_overdue_reason(synth_model):
    df, model = synth_model
    nobki = df.head(300).assign(**{f: np.nan for f in BKI})
    in_model = [f for f in BKI if f in model.factors]
    assert in_model  # иначе проверять нечего
    pts = model.score(nobki)
    # пропуск получает WoE = 0 - баллы ниже максимума, расчёт «максимум − баллы» дал бы R03 каждой заявке
    assert all((model.max_points[f] - pts[f"points_{f}"] > 1e-6).all() for f in in_model)
    out = assess(nobki, model, load_policy(), top=len(model.factors))
    assert not out.reason_codes.map(lambda cs: "R03" in cs).any()
    asked = out[out.stop_codes.str.len() == 0]
    assert len(asked) and (asked.outcome == "REQUEST_INFO").all()
    assert asked.requests.map(lambda q: KEY_DATA["bki_max_dpd_12m"] in q).all()


def test_known_factors_keep_their_reasons_when_credit_history_is_missing(synth_model):
    df, model = synth_model
    rows = df.head(300)
    nobki = rows.assign(**{f: np.nan for f in BKI})
    k = len(model.factors)
    seen_r03 = False
    for (_, a), (_, s), (_, b), (_, t) in zip(rows.iterrows(), model.score(rows).iterrows(),
                                              nobki.iterrows(), model.score(nobki).iterrows()):
        known = reason_codes(s, model, k, app=a)
        seen_r03 |= any(r["code"] == "R03" for r in known)
        assert reason_codes(t, model, k, app=b) == [r for r in known if r["code"] != "R03"]
    assert seen_r03  # известные просрочки по-прежнему дают R03
