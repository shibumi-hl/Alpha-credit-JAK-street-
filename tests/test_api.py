import warnings
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.personas import application, load_personas
from scoring import synth
from scoring.approval import monthly_payment
from scoring.gcurve import CurveStore
from scoring.whatif import Engine, evaluate

warnings.filterwarnings("ignore")
ASOF = date(2024, 2, 1)


@pytest.fixture(scope="module")
def engine():
    curves = CurveStore.from_csv(Path(__file__).parent / "fixtures" / "gcurve_params.csv")
    eng, _ = Engine.fit(synth.generate(8000, seed=43, asof=ASOF), curves=curves, asof=ASOF, seed=5, cv=0)
    return eng


@pytest.fixture(scope="module")
def client(engine):
    return TestClient(create_app(engine))


def _levers(pid, **kw):
    return {**load_personas()[pid]["levers"], "bki_consent": True, **kw}


def test_health_and_meta(client):
    assert client.get("/api/health").json()["ok"] is True
    m = client.get("/api/v1/meta").json()
    express = {p["product"]: p for p in m["products"]}["express"]
    assert (express["label"], express["min_amount"], express["max_amount"], express["revolving"]) == \
           ("экспресс-кредит без залога", 300000, 10000000, False)
    assert {p["product"]: p for p in m["products"]}["card"]["revolving"] is True
    codes = {c["code"]: c["category"] for c in m["codes"]}
    assert {"S01", "E01", "L02", "R10"} <= set(codes) and "DSCR ≥ 1,25" in codes["L02"]
    assert m["asof"] == "2024-02-01"


def test_personas_list_and_detail(client):
    lst = client.get("/api/v1/personas").json()
    assert {p["id"] for p in lst} == set(load_personas())
    d = client.get("/api/v1/personas/marina").json()
    assert d["levers"]["product"] == "express" and d["levers"]["bki_consent"] is False
    revenue = {f["key"]: f for f in d["facts"]}["revenue"]
    assert revenue["value"] == 48000000 and revenue["source"] == "демо"
    assert client.get("/api/v1/personas/nobody").status_code == 404


def test_evaluation_is_the_engine_answer_in_the_api_contract(client, engine):
    p = load_personas()["marina"]
    levers = _levers("marina", has_rko=1, bank_turnover_month_rub=2_000_000)
    r = client.post("/api/v1/evaluations", json={"persona_id": "marina", "levers": levers}).json()
    one = evaluate(engine, application(p, levers))
    for k in ("outcome", "offered_amount", "limit", "risk_class", "offered_product"):
        assert r[k] == one[k], k
    assert r["approval_probability"] == pytest.approx(one["approval_probability"])
    explain = r["approval_explain"]
    assert len(explain) == len(one["approval_explain"])
    assert {"feature", "label", "category", "category_label", "points"} <= set(explain[0])
    product = next(x for x in explain if x["feature"] == "product")
    assert product["category_label"] == "экспресс-кредит без залога"
    if r["offered_amount"]:
        assert r["monthly_payment"] == pytest.approx(
            monthly_payment(r["offered_amount"], r["pricing"]["rate"], levers["requested_term_m"]))
    products = {x["product"]: x for x in r["products"]}
    assert set(products) == set(engine.policy["products"]) and products["express"]["available"]


def test_facts_cannot_be_sent_as_levers(client):
    base = client.post("/api/v1/evaluations", json={"persona_id": "marina", "levers": _levers("marina")}).json()
    forged = _levers("marina", revenue=1e12, ebit=1e12, bki_current_dpd=0, age_months=500)
    r = client.post("/api/v1/evaluations", json={"persona_id": "marina", "levers": forged}).json()
    assert (r["outcome"], r["limit"], r["pd"]) == (base["outcome"], base["limit"], base["pd"])


def test_unavailable_product_explains_why(client):
    r = client.post("/api/v1/evaluations", json={"persona_id": "young", "levers": _levers("young")}).json()
    line = {x["product"]: x for x in r["products"]}["credit_line"]
    assert line["available"] is False and [x["code"] for x in line["reasons"]] == ["E01"]


@pytest.mark.parametrize("bad", [{"requested_amount": -5}, {"requested_amount": 1e12}, {"product": "leasing"},
                                 {"requested_term_m": 0}, {"bank_turnover_month_rub": -1}])
def test_bad_levers_are_rejected(client, bad):
    r = client.post("/api/v1/evaluations", json={"persona_id": "marina", "levers": _levers("marina", **bad)})
    assert r.status_code == 422


def test_unknown_persona_is_404(client):
    r = client.post("/api/v1/evaluations", json={"persona_id": "nobody", "levers": _levers("marina")})
    assert r.status_code == 404


def test_whatif_scenarios_carry_the_levers_that_reproduce_them(client):
    levers = _levers("marina")
    out = client.post("/api/v1/whatif", json={"persona_id": "marina", "levers": levers}).json()
    assert out["base"]["outcome"] and out["scenarios"]
    for s in out["scenarios"]:
        again = client.post("/api/v1/evaluations", json={"persona_id": "marina", "levers": s["levers"]}).json()
        assert again["approval_probability"] == pytest.approx(s["approval_probability"]), s["key"]
        assert again["outcome"] == s["outcome"], s["key"]


def test_simulate_amount_axis_covers_the_request_and_the_limit(client):
    levers = _levers("marina")
    base = client.post("/api/v1/evaluations", json={"persona_id": "marina", "levers": levers}).json()
    sim = client.post("/api/v1/simulate", json={"persona_id": "marina", "levers": levers, "axis": "requested_amount",
                                                "n": 24}).json()
    xs = [p["x"] for p in sim["points"]]
    assert xs == sorted(xs) and len(xs) == len(set(xs)) and 24 <= len(xs) <= 28
    assert xs[0] == 300000 and xs[-1] == 10000000  # от минимума до максимума экспресса
    assert levers["requested_amount"] in xs
    if 0 < base["limit"] < 10_000_000:
        assert base["limit"] in xs and sim["limit"] == base["limit"]


def test_simulate_validation(client):
    body = {"persona_id": "marina", "levers": _levers("marina"), "axis": "requested_amount", "n": 200}
    assert client.post("/api/v1/simulate", json=body).status_code == 422
    card = {**body, "n": 16, "axis": "requested_term_m", "levers": _levers("marina", product="card",
                                                                         requested_amount=500000)}
    assert client.post("/api/v1/simulate", json=card).status_code == 422  # у возобновляемого продукта срока нет
    term = {**body, "n": 16, "axis": "requested_term_m"}
    xs = [p["x"] for p in client.post("/api/v1/simulate", json=term).json()["points"]]
    assert 12 in xs and xs == sorted(xs)


def test_simulate_hides_another_products_limit_on_a_route(client):
    levers = _levers("bakery", product="overdraft", requested_amount=2_000_000, has_rko=False)
    base = client.post("/api/v1/evaluations", json={"persona_id": "bakery", "levers": levers}).json()
    assert base["route"]["from"] == "overdraft" and base["route"]["reasons"][0]["code"] == "E02"  # овердрафт - только с РКО
    sim = client.post("/api/v1/simulate", json={"persona_id": "bakery", "levers": levers, "n": 16}).json()
    assert (sim["limit"], sim["binding"]) == (0, None)  # лимит карты на кривой овердрафта вводил бы в заблуждение


def test_engine_path_prefers_env_then_fresh_training_then_the_committed_model(tmp_path, monkeypatch):
    import api.app as app_module
    monkeypatch.setattr(app_module, "ROOT", tmp_path)
    monkeypatch.delenv("ENGINE_PATH", raising=False)
    assert app_module.default_engine_path() == tmp_path / "models" / "engine.pkl"  # свежий клон: data/ нет в git
    fresh = tmp_path / "data" / "scoring" / "engine.pkl"
    fresh.parent.mkdir(parents=True)
    fresh.write_bytes(b"")
    assert app_module.default_engine_path() == fresh  # переобучили локально - берём своё
    monkeypatch.setenv("ENGINE_PATH", str(tmp_path / "other.pkl"))
    assert app_module.default_engine_path() == tmp_path / "other.pkl"
