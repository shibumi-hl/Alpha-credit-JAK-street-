from datetime import date

import numpy as np
import pandas as pd
import pytest

from scoring import synth

ASOF = date(2026, 10, 20)


@pytest.fixture(scope="module")
def big():
    return synth.generate(30000, seed=1, asof=ASOF)


def test_schema_has_features_and_label_but_no_hidden_risk(big):
    assert set(synth.FEATURES) <= set(big.columns)
    assert set(big.default_12m.unique()) == {0, 1}
    assert not {"pd", "logit", "true_pd", "stress"} & set(big.columns)
    assert big[[c for c in synth.NUMERIC if c != "revenue_growth"]].notna().all().all()  # NaN только у роста


def test_reproducible_by_seed():
    a, b = synth.generate(500, seed=3, asof=ASOF), synth.generate(500, seed=3, asof=ASOF)
    pd.testing.assert_frame_equal(a, b)
    assert not synth.generate(500, seed=4, asof=ASOF).equals(a)


def test_default_rate_hits_target(big):
    assert big.default_12m.mean() == pytest.approx(0.05, abs=0.01)
    other = synth.generate(20000, seed=2, asof=ASOF, default_rate=0.10)
    assert other.default_12m.mean() == pytest.approx(0.10, abs=0.01)


def test_risk_grows_with_debt_load_and_overdue(big):
    dr = big.groupby(pd.qcut(big.debt_to_revenue.rank(method="first"), 4, labels=False)).default_12m.mean()
    assert dr.iloc[-1] > 1.5 * dr.iloc[0]
    clean = big[big.bki_max_dpd_12m == 0].default_12m.mean()
    late = big[big.bki_max_dpd_12m > 30].default_12m.mean()
    assert late > 2 * clean
    assert big[big.tax_debt_to_revenue > 0.01].default_12m.mean() > big[big.tax_debt_to_revenue == 0].default_12m.mean()


def test_enrich_keeps_real_values():
    raw = synth.generate_real(300, np.random.default_rng(5), ASOF)
    out = synth.enrich(raw, seed=5, asof=ASOF)
    assert list(out.inn) == list(raw.inn)
    assert np.allclose(out.revenue, raw.revenue)
    assert np.allclose(out.debt_to_revenue, raw.debt / raw.revenue)
    assert (out.age_months >= 1).all() and (out.turnover_months == raw.bfo_years * 12).all()


def test_application_fields_have_expected_mix(big):
    share = big["product"].value_counts(normalize=True)
    assert set(share.index) == set(synth.PRODUCTS)
    assert 0.2 < share["express"] < 0.4 and share["secured"] > 0.1
    assert (big.loc[big["product"] == "seller_credit", "marketplace"] == 1).all()
    assert (big.loc[big.has_rko == 0, "bank_turnover_ratio"] == 0).all()
    assert (big.loc[big["product"] == "card", "requested_amount"] <= 1e6).all()
    assert np.allclose(big.amount_to_revenue, big.requested_amount / big.revenue)


def test_unsecured_riskier_and_bank_turnover_safer(big):
    dr = big.groupby("product").default_12m.mean()
    assert dr["express"] > dr["secured"]
    assert big[big.bank_turnover_ratio >= 1].default_12m.mean() < big[big.has_rko == 0].default_12m.mean()


def test_secured_gets_longer_terms_and_overdraft_is_sized_by_monthly_turnover(big):
    assert big.loc[big["product"] == "secured", "requested_term_m"].max() == 60
    od = big[big["product"] == "overdraft"]
    assert (od.requested_term_m == 12).all() and (od.amount_to_revenue.median() < 0.06)


def test_loss_without_debt_gets_the_worst_coverage_not_the_best():
    raw = synth.generate_real(3, np.random.default_rng(1), ASOF)
    for c in ("debt", "debt_st", "debt_lt", "interest", "interest_paid", "loan_repaid"):
        raw[c] = 0.0
    raw["ebit"] = [-3e6, 0.0, 2e6]
    f = synth.features(raw, ASOF)
    assert f.interest_cover.iloc[0] == -synth.CAP and f.dscr.iloc[0] == -synth.CAP
    assert f.dscr.iloc[2] == synth.CAP  # прибыль без долга - лучшее покрытие


def test_every_generated_application_is_valid_for_the_credit_logic():
    from scoring.credit import load_policy, validate
    raw = synth.generate_real(2000, np.random.default_rng(9), ASOF)
    raw["revenue"] = 1000.0  # в ГИР БО бывает выручка 1 тыс. руб. (доходы прочие): сумма заявки не должна стать нулём
    f = synth.enrich(raw, seed=9, asof=ASOF)
    policy = load_policy()
    for _, r in f.iterrows():
        validate(r.to_dict(), policy)
