from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scoring.gcurve import CurveStore, GCurve

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def store():
    return CurveStore.from_csv(FIX / "gcurve_params.csv")


@pytest.mark.parametrize("d", ["2022-06-01", "2024-01-15", "2026-10-13"])
def test_matches_published_moex_yields(store, d):
    pub = pd.read_csv(FIX / "gcurve_yields.csv")
    pub = pub[pub.tradedate == d]
    curve = store.on(date.fromisoformat(d))
    model = curve.ytm(pub.period.values) * 100
    assert np.abs(model - pub.value.values).max() < 1e-3


def test_discount_factor_consistent_with_zero_rate(store):
    c = store.on(date(2026, 10, 13))
    t = np.array([0.5, 2.0, 7.0])
    assert np.allclose(c.df(t), np.exp(-c.zero(t) * t))
    assert np.allclose(c.ytm(t), np.exp(c.zero(t)) - 1)


def test_short_end_is_finite(store):
    c = store.on(date(2026, 10, 13))
    assert np.isfinite(c.zero(np.array([0.0, 1e-6]))).all()
    assert c.df(0.0) == pytest.approx(1.0)


def test_weekend_uses_previous_trading_day(store):
    sat = store.on(date(2024, 1, 20))  # no data that day
    assert store.date_of(date(2024, 1, 20)) == date(2024, 1, 15)
    assert isinstance(sat, GCurve)


def test_before_first_date_raises(store):
    with pytest.raises(KeyError):
        store.on(date(2020, 1, 1))


def test_last_date_is_latest_published_curve(store):
    assert store.last_date == date(2026, 10, 13)
