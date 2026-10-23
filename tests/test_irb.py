import pytest

from scoring.irb import corp_correlation, irb_capital, retail_correlation, risk_weight, sme_adjustment
from scoring.pricing import load_pricing

IRB = load_pricing()["capital"]["irb"]
L = IRB["sme_revenue_limit_mln"]


def test_corporate_anchor_from_basel_illustrative_table():
    # Базель II, иллюстративные веса риска: корпоративный, PD 1%, LGD 45%, M 2,5 → 92,32%
    k = irb_capital(0.01, 0.45, corp_correlation(0.01), maturity=2.5)
    assert 12.5 * k == pytest.approx(0.9232, abs=5e-4)


def test_correlations_run_between_their_bounds():
    assert corp_correlation(1e-9) == pytest.approx(0.24, abs=1e-6)
    assert corp_correlation(0.5) == pytest.approx(0.12, abs=1e-6)
    assert retail_correlation(1e-9) == pytest.approx(0.16, abs=1e-6)
    assert retail_correlation(0.5) == pytest.approx(0.03, abs=1e-6)


def test_sme_adjustment_scales_with_revenue():
    m = IRB["sme_max_adjustment"]
    assert sme_adjustment(1.0, L, m) == pytest.approx(m)  # выручка меньше 0,1·L - максимальная скидка
    assert sme_adjustment(0.1 * L, L, m) == pytest.approx(m)
    assert sme_adjustment(0.55 * L, L, m) == pytest.approx(m / 2)
    assert sme_adjustment(L, L, m) == 0 and sme_adjustment(3 * L, L, m) == 0


def test_risk_weight_grows_with_pd_and_is_zero_without_loss():
    rws = [risk_weight(pd, 0.4, 5e6, 50e6, IRB)["rw"] for pd in (0.002, 0.01, 0.05, 0.2)]
    assert rws == sorted(rws)
    assert risk_weight(0.05, 0.0, 5e6, 50e6, IRB)["rw"] == 0
    big = [risk_weight(pd, 0.4, 2e8, 1e9, IRB)["rw"] for pd in (0.002, 0.01, 0.05, 0.2)]
    assert big == sorted(big)


def test_pd_floor_applies():
    assert risk_weight(0.0, 0.4, 2e8, 1e9, IRB)["rw"] == pytest.approx(
        risk_weight(IRB["pd_floor"], 0.4, 2e8, 1e9, IRB)["rw"])


def test_exposure_threshold_picks_retail_or_corporate():
    limit = IRB["retail_max_exposure_rub"]
    retail = risk_weight(0.02, 0.4, limit, 1e9, IRB)
    corp = risk_weight(0.02, 0.4, limit + 1, 1e9, IRB)
    assert retail["irb_class"] == "retail" and corp["irb_class"] == "corporate"
    assert retail["rw"] < corp["rw"]


def test_small_company_gets_lower_corporate_weight_and_longer_maturity_costs_more():
    small = risk_weight(0.02, 0.4, 2e8, 0.05 * L * 1e6, IRB)["rw"]
    large = risk_weight(0.02, 0.4, 2e8, 2 * L * 1e6, IRB)["rw"]
    assert small < large
    short = irb_capital(0.02, 0.4, corp_correlation(0.02), maturity=1.0)
    long_ = irb_capital(0.02, 0.4, corp_correlation(0.02), maturity=5.0)
    assert short < long_
