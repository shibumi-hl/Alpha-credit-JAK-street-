from datetime import date
from pathlib import Path

import pytest

from scoring.gcurve import CurveStore
from scoring.pricing import COMPONENTS, load_pricing, price, psk

CFG = load_pricing()
CURVES = CurveStore.from_csv(Path(__file__).parent / "fixtures" / "gcurve_params.csv")  # публичные данные Мосбиржи


def app(**kw):
    base = {"product": "express", "requested_amount": 5e6, "requested_term_m": 24, "guarantee": 0, "has_rko": 0,
            "bank_turnover_ratio": 0.0, "subscription": 0, "insurance": 0}
    return {**base, **kw}


def test_components_add_up_to_rate():
    p = price(app(), 0.03, CFG, CURVES, date(2024, 1, 20))
    assert p["rate"] == pytest.approx(sum(p[c] for c in COMPONENTS if c != "discounts") - p["discounts"])
    assert p["el"] == pytest.approx(0.03 * CFG["lgd"]["express"])


def test_funding_uses_curve_known_the_day_before():
    on_day = price(app(), 0.03, CFG, CURVES, date(2024, 1, 15))  # кривая 15.01 ещё неизвестна → 01.06.2022
    after = price(app(), 0.03, CFG, CURVES, date(2024, 1, 16))
    assert on_day["curve_date"] == "2022-06-01" and after["curve_date"] == "2024-01-15"
    life = (24 + 1) / 2 / 12
    assert after["funding"] == pytest.approx(float(CURVES.on(date(2024, 1, 15)).ytm(life)) + CFG["funding_spread"])
    assert price(app(), 0.03, CFG, None, date(2024, 1, 16))["funding"] == pytest.approx(CFG["fallback_funding"])


def test_collateral_and_guarantee_lower_expected_loss():
    unsecured = price(app(), 0.04, CFG, CURVES, date(2024, 2, 1))
    secured = price(app(product="secured"), 0.04, CFG, CURVES, date(2024, 2, 1))
    guaranteed = price(app(guarantee=1), 0.04, CFG, CURVES, date(2024, 2, 1))
    assert secured["el"] < unsecured["el"] and secured["rate"] < unsecured["rate"]
    assert guaranteed["el"] == pytest.approx(unsecured["el"] * (1 - CFG["guarantee_coverage"]))


def test_higher_pd_costs_more():
    assert price(app(), 0.08, CFG, CURVES, date(2024, 2, 1))["rate"] > price(app(), 0.01, CFG, CURVES, date(2024, 2, 1))["rate"]


def test_cross_sell_discounts():
    d = CFG["discounts"]
    base = price(app(), 0.03, CFG, CURVES, date(2024, 2, 1))
    assert base["discounts"] == 0
    assert price(app(has_rko=1, bank_turnover_ratio=0.5), 0.03, CFG, CURVES, date(2024, 2, 1))["discounts"] == pytest.approx(d["bank_turnover_40"])
    assert price(app(has_rko=1, bank_turnover_ratio=3), 0.03, CFG, CURVES, date(2024, 2, 1))["discounts"] == pytest.approx(d["bank_turnover_100"])
    full = price(app(has_rko=1, bank_turnover_ratio=3, subscription=1, insurance=1), 0.03, CFG, CURVES, date(2024, 2, 1))
    assert full["discounts"] == pytest.approx(d["bank_turnover_100"] + d["subscription"] + d["insurance"])


def test_all_in_rate_includes_fee_and_insurance():
    assert psk(1e6, 0.24, 24, 0.0, 0.0) == pytest.approx(0.24, abs=1e-6)  # без допов ПСК = номинал
    with_fee = psk(1e6, 0.24, 24, 0.02, 0.0)
    with_both = psk(1e6, 0.24, 24, 0.02, 0.015)
    assert 0.24 < with_fee < with_both
    p = price(app(insurance=1), 0.03, CFG, CURVES, date(2024, 2, 1))
    assert p["all_in"] > p["rate"] and p["insurance_rate"] == CFG["insurance_rate"]


def test_secured_requires_property_insurance():
    p = price(app(product="secured", insurance=0), 0.03, CFG, CURVES, date(2024, 2, 1))
    assert p["insurance_rate"] == CFG["insurance_rate"]



def test_psk_is_not_capped_for_very_expensive_credit():
    assert psk(1e6, 15.0, 12, 0.0, 0.0) == pytest.approx(15.0, rel=1e-6)


def test_funding_falls_back_when_asof_precedes_the_first_curve():
    p = price(app(), 0.03, CFG, CURVES, date(2000, 1, 1))
    assert p["funding"] == pytest.approx(CFG["fallback_funding"]) and p["curve_date"] is None


def test_irb_capital_by_exposure_class_collateral_and_guarantee():
    d = date(2024, 2, 1)
    small = price(app(revenue=50e6), 0.03, CFG, CURVES, d)
    big = price(app(revenue=5e9, requested_amount=2e8), 0.03, CFG, CURVES, d)
    assert small["irb_class"] == "retail" and big["irb_class"] == "corporate"
    assert big["lgd_capital"] == pytest.approx(CFG["capital"]["irb"]["lgd_corporate_unsecured"])
    secured = price(app(revenue=5e9, requested_amount=2e8, product="secured"), 0.03, CFG, CURVES, d)
    assert secured["lgd_capital"] < big["lgd_capital"] and secured["capital"] < big["capital"]
    guaranteed = price(app(revenue=50e6, guarantee=1), 0.03, CFG, CURVES, d)
    assert guaranteed["capital"] < small["capital"]
    assert price(app(revenue=50e6), 0.10, CFG, CURVES, d)["risk_weight"] > small["risk_weight"]
    c = CFG["capital"]
    assert small["capital"] == pytest.approx(small["risk_weight"] * c["car"] * (c["cost_of_equity"] - small["funding"]))


def test_retail_lgd_respects_regulatory_floor():
    cfg = {**CFG, "lgd": {**CFG["lgd"], "express": 0.10}}  # собственная оценка ниже пола 30%
    p = price(app(revenue=50e6), 0.03, cfg, CURVES, date(2024, 2, 1))
    assert p["lgd_capital"] == pytest.approx(CFG["capital"]["irb"]["lgd_retail_floor_unsecured"])
    assert p["el"] == pytest.approx(0.03 * 0.10)  # EL - экономический LGD, пол только для капитала


def test_standard_approach_keeps_flat_weight():
    cfg = {**CFG, "capital": {**CFG["capital"], "approach": "standard"}}
    p = price(app(revenue=50e6), 0.03, cfg, CURVES, date(2024, 2, 1))
    assert p["risk_weight"] == CFG["capital"]["risk_weight"] and p["irb_class"] == "standard"


def test_guarantee_never_takes_retail_lgd_below_the_floor():
    p = price(app(revenue=50e6, product="seller_credit", guarantee=1), 0.03, CFG, CURVES, date(2024, 2, 1))
    assert p["irb_class"] == "retail"
    assert p["lgd_capital"] >= CFG["capital"]["irb"]["lgd_retail_floor_unsecured"] - 1e-12


def test_unknown_capital_approach_is_an_error():
    cfg = {**CFG, "capital": {**CFG["capital"], "approach": "IRB"}}
    with pytest.raises(ValueError, match="approach"):
        price(app(revenue=50e6), 0.03, cfg, CURVES, date(2024, 2, 1))
