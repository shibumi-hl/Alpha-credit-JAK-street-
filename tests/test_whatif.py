import json
import warnings
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from scoring.approval import ApprovalModel, approval_target, monthly_payment
from scoring.gcurve import CurveStore
from scoring import synth
from scoring.pricing import price
from scoring.whatif import SCENARIOS, Engine, _derive, evaluate, whatif

warnings.filterwarnings("ignore")
ASOF = date(2024, 2, 1)
CURVES = CurveStore.from_csv(Path(__file__).parent / "fixtures" / "gcurve_params.csv")


@pytest.fixture(scope="module")
def eng():
    df = synth.generate(12000, seed=41, asof=ASOF)
    engine, rep = Engine.fit(df, curves=CURVES, asof=ASOF, seed=5, cv=0)
    return df, engine, rep


def _app(df, **kw):
    return {**df.iloc[0].to_dict(), **kw}


def test_fit_reports_both_models_and_chains_price_into_decisions(eng):
    df, engine, rep = eng
    assert rep["scorecard"]["gini_test"] > 0.3
    assessed = rep["assessed"]
    assert {"rate", "all_in", "approval_probability"} <= set(assessed.columns)
    priced = assessed[assessed.offered_amount > 0]
    assert (priced.all_in >= priced.rate - 1e-9).all() and priced.rate.between(0.05, 0.6).all()
    assert (assessed.loc[assessed.stop_codes.str.len() > 0, "approval_probability"] == 0).all()
    appr = rep["approval"]
    assert appr["n_train"] + appr["n_test"] == rep["approval_n"] and appr["gini_test"] > appr["gini_test_categories"]


def test_evaluate_is_json_ready_and_complete(eng):
    df, engine, _ = eng
    r = evaluate(engine, _app(df))
    json.dumps(r, ensure_ascii=False)
    assert {"pd", "risk_class", "approval_probability", "outcome", "offered_product", "pricing", "reasons",
            "approval_explain"} <= set(r)
    assert 0 <= r["approval_probability"] <= 1


def test_collateral_makes_credit_cheaper(eng):
    df, engine, _ = eng
    base_app = _app(df, product="express", bki_current_dpd=0, bki_max_dpd_12m=0, tax_debt_to_revenue=0.0,
                    status="ACTIVE", ebit=df.iloc[0].revenue * 0.2, debt_service=0.0, insurance=1)
    out = whatif(engine, base_app)
    base, sc = out["base"], {s["key"]: s for s in out["scenarios"]}
    assert "collateral" in sc
    assert sc["collateral"]["rate"] < base["pricing"]["rate"]
    assert sc["collateral"]["delta_rate_pp"] == pytest.approx(100 * (sc["collateral"]["rate"] - base["pricing"]["rate"]))
    assert sc["collateral"]["delta_approval_pp"] == pytest.approx(
        100 * (sc["collateral"]["approval_probability"] - base["approval_probability"]))
    assert sc["collateral"]["delta_approval_pp"] >= 0  # залог не снижает шанс одобрения
    assert sc["no_insurance"]["all_in"] < base["pricing"]["all_in"] or sc["no_insurance"]["rate"] > base["pricing"]["rate"]


def test_scenarios_that_do_not_apply_are_skipped(eng):
    df, engine, _ = eng
    keys = {s["key"] for s in whatif(engine, _app(df, product="secured", guarantee=1))["scenarios"]}
    assert "collateral" not in keys and "guarantee" not in keys
    assert keys <= set(SCENARIOS)


def test_stop_factor_means_zero_chance_and_reason(eng):
    df, engine, _ = eng
    r = evaluate(engine, _app(df, bki_current_dpd=60))
    assert r["outcome"] == "REJECT" and r["approval_probability"] == 0
    assert r["stop_factors"][0]["code"] == "S01"


def test_soft_mode_without_credit_history(eng):
    df, engine, _ = eng
    full = evaluate(engine, _app(df))
    assert full["approval_mode"] == "full" and full["approval_imputed"] == []
    r = evaluate(engine, _app(df, bki_max_dpd_12m=None, bki_current_dpd=None, bki_overdue_cnt_12m=None))
    assert r["outcome"] == "REQUEST_INFO"  # решение ждёт согласия на БКИ, а предоценка шанса уже есть
    assert r["approval_mode"] == "soft" and r["approval_imputed"] == ["bki_overdue"]
    assert 0 < r["approval_probability"] < 1


def _cash_bound(df, engine, rep):
    """Заявка, где сумму ограничивает денежный поток: экспресс 12 мес, EBIT на ~60% платежа по запросу."""
    out = rep["assessed"]
    i = out.index[(out.risk_class <= 3) & (out.stop_codes.str.len() == 0)][0]
    amount = 3e6
    return _derive({**df.loc[i].to_dict(), "product": "express", "requested_amount": amount, "requested_term_m": 12,
                    "revenue": 20 * amount, "debt_service": 0.0, "ebit": 1.25 * 0.6 * 12 * monthly_payment(amount, 0.2, 12),
                    "bki_current_dpd": 0, "bki_max_dpd_12m": 0, "tax_debt_to_revenue": 0.0, "status": "ACTIVE"},
                   engine.policy)


def test_cash_bound_counter_offer_is_explained_by_cash_flow(eng):
    df, engine, rep = eng
    r = evaluate(engine, _cash_bound(df, engine, rep))
    assert r["outcome"] == "COUNTER" and r["offered_product"] == "express" and r["offered_amount"] < 3e6
    assert [x["code"] for x in r["reasons"]] == ["L02"]  # причина - денежный поток, а не баллы скоркарты


def test_longer_term_scenario_raises_a_cash_bound_offer(eng):
    df, engine, rep = eng
    app = _cash_bound(df, engine, rep)
    out = whatif(engine, app)
    sc = {s["key"]: s for s in out["scenarios"]}
    assert "term_24" in sc
    longer = sc["term_24"]
    assert longer["offered_amount"] > out["base"]["offered_amount"]  # платёж меньше - денежного потока хватает на больше
    assert longer["delta_approval_pp"] > 0
    for kw in ({"product": "card", "requested_amount": 5e5}, {"product": "overdraft"}, {"requested_term_m": 24},
               {"requested_term_m": 36}):
        keys = {s["key"] for s in whatif(engine, {**app, **kw})["scenarios"]}
        assert "term_24" not in keys, kw  # возобновляемым продуктам и длинным срокам сценарий не нужен


def test_headroom_payment_uses_the_priced_rate(eng):
    df, engine, rep = eng
    out = rep["assessed"]
    i = out.index[(out.risk_class <= 3) & (out.stop_codes.str.len() == 0)][0]
    app = _derive({**df.loc[i].to_dict(), "product": "secured", "requested_term_m": 24, "debt_service": 0.0,
                   "bki_current_dpd": 0, "bki_max_dpd_12m": 0, "tax_debt_to_revenue": 0.0, "status": "ACTIVE"},
                  engine.policy)
    pd_ = evaluate(engine, app)["pd"]
    rate = price(app, pd_, engine.pricing, engine.curves, engine.asof, app["requested_amount"], all_in=False)["rate"]
    assert rate < 0.215  # ниже опорной 22,5%, так что при опорной ставке запас был бы ниже 0,5×
    app["ebit"] = 1.25 * 0.505 * 12 * monthly_payment(app["requested_amount"], rate, 24)  # 0,505× по ставке заявки
    r = evaluate(engine, app)
    at_reference = engine.approval.predict(pd.DataFrame([app]).assign(pd=r["pd"]))[0]  # без ставки - опорная
    assert r["approval_probability"] > at_reference + 0.05  # ступень 0,5× дана по реальной ставке


def test_engine_saved_before_this_model_is_refused_with_a_clear_message(eng, tmp_path):
    _, engine, _ = eng
    before_cap = replace(engine.approval)
    del before_cap.__dict__["version"]  # пикл до номера версии признаков (запас ещё до 10×)
    before_step = replace(engine.approval, version=engine.approval.version - 1)  # запас до 1×, без ступени на 0,5×
    for old in (SimpleNamespace(columns=[], intercept=0.0, coef={}, counts={}), before_cap, before_step):
        replace(engine, approval=old).save(tmp_path / "engine.pkl")
        with pytest.raises(ValueError, match="train_scorecard"):
            Engine.load(tmp_path / "engine.pkl")
    engine.save(tmp_path / "engine.pkl")
    assert Engine.load(tmp_path / "engine.pkl").approval.version == engine.approval.version


def test_scenarios_never_lower_the_chance_even_if_decisions_suggest_it(eng):
    df, engine, rep = eng
    out = rep["assessed"]
    y = approval_target(out, df.requested_amount)
    perks = (df.marketplace == 1) | (df.has_rko == 1) | (df.guarantee == 1) | (df["product"] == "secured")
    y_adv = y.where(~perks, 0.0).where(y.notna())  # решения, где клиентам с «плюсами» якобы чаще отказывают
    adv = replace(engine, approval=ApprovalModel.fit(df.assign(pd=out.pd.to_numpy()), y_adv))
    keys = ["marketplace", "rko_turnover", "guarantee", "collateral"]
    rows = df[(df.okved_section == "G") & (df.marketplace == 0) & (df.has_rko == 0)].head(25)
    deltas = {k: [] for k in keys}
    for _, a in rows.iterrows():
        for s in whatif(adv, {**a.to_dict(), "bki_current_dpd": 0, "status": "ACTIVE"}, scenarios=keys)["scenarios"]:
            deltas[s["key"]].append(s["delta_approval_pp"])
    assert all(deltas.values())
    assert min(min(v) for v in deltas.values()) >= -1e-9



def test_request_within_limit_keeps_monthly_bank_turnover():
    _, _, change = SCENARIOS["amount_to_limit"]
    a = {"product": "overdraft", "requested_amount": 2e6, "has_rko": 1, "bank_turnover_ratio": 0.5}
    c = change(a, {"limit": 1e6})
    assert c["requested_amount"] == 1e6
    assert c["bank_turnover_ratio"] * c["requested_amount"] == pytest.approx(0.5 * 2e6)


def test_application_defaults_and_validation(eng):
    df, engine, _ = eng
    app = _app(df)
    for k in ("product", "has_rko", "marketplace", "guarantee", "subscription", "insurance", "bank_turnover_ratio"):
        app.pop(k, None)
    r = evaluate(engine, app)
    assert r["product"] == engine.policy["default_product"]
    with pytest.raises(ValueError, match="продукт"):
        evaluate(engine, _app(df, product="leasing"))
    nan = evaluate(engine, _app(df, ebit=float("nan"), bki_current_dpd=None))
    assert nan["outcome"] == "REQUEST_INFO" and nan["offered_amount"] == 0


def test_whatif_works_on_a_minimal_application(eng):
    df, engine, _ = eng
    app = _app(df)
    for k in ("product", "has_rko", "marketplace", "guarantee", "subscription", "insurance", "bank_turnover_ratio"):
        app.pop(k, None)
    app["status"] = None
    out = whatif(engine, app)
    assert out["base"]["product"] == engine.policy["default_product"]
    assert "S07" not in [s["code"] for s in out["base"]["stop_factors"]]
    assert out["scenarios"] and {"collateral", "rko_turnover"} <= {s["key"] for s in out["scenarios"]}
