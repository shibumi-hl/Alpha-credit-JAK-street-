"""Конвейер заявки через HTTP на обученном движке models/engine.pkl: сценарии T1-T7 до конечного статуса, роли,
недопустимые переходы, идемпотентность и журнал."""
import warnings
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.personas import load_personas
from scoring.whatif import Engine

warnings.filterwarnings("ignore")
ENGINE = Path(__file__).resolve().parents[1] / "models" / "engine.pkl"


@pytest.fixture(scope="module")
def engine():
    return Engine.load(ENGINE)


@pytest.fixture()
def client(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("PIPELINE_STEP_DELAY", "0")
    monkeypatch.setenv("SECRET_KEY", "test")
    return TestClient(create_app(engine))


def login(client, who):
    r = client.post("/api/v1/auth/login", json={"username": who, "password": who})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def submit(client, h, pid, key=None, **kw):
    levers = {**load_personas()[pid]["levers"], "bki_consent": True, **kw}
    headers = {**h, **({"Idempotency-Key": key} if key else {})}
    return client.post("/api/v1/applications", headers=headers,
                       json={"persona_id": pid, "levers": levers, "purpose": "закупка", "bki_consent": True})


def settle(client, h, app_id):
    """Чтение заявки двигает созревшие автоматические шаги; читаем, пока ход банка и статус меняется."""
    seen = None
    for _ in range(10):
        a = client.get(f"/api/v1/applications/{app_id}", headers=h).json()
        if a["status"] == seen:
            return a
        seen = a["status"]
    return a


def act(client, h, app_id, action, **kw):
    return client.post(f"/api/v1/applications/{app_id}/actions", headers=h, json={"action": action, **kw})


def test_login_rejects_wrong_password_and_requires_token(client):
    assert client.post("/api/v1/auth/login", json={"username": "client", "password": "x"}).status_code == 401
    assert client.get("/api/v1/applications").status_code == 401
    assert client.get("/api/v1/applications", headers={"Authorization": "Bearer forged.sig"}).status_code == 401


def test_t2_counter_offer_then_sign_and_issue(client):
    h = login(client, "client")
    r = submit(client, h, "marina")
    assert r.status_code == 201, r.text
    a = settle(client, h, r.json()["id"])
    assert a["status"] == "COUNTER_OFFER" and a["whose_turn"] == "client"
    assert a["offer"]["amount"] == 3610000 and a["decision"]["reasons"][0]["code"] == "L02"
    assert "risk" not in a and set(a["actions"]) == {"accept_offer", "withdraw"}
    a = act(client, h, a["id"], "accept_offer").json()
    assert a["status"] == "SIGNING" and len(a["sign_code"]) == 4
    assert act(client, h, a["id"], "sign", code="0000" if a["sign_code"] != "0000" else "1111").status_code == 422
    a = act(client, h, a["id"], "sign", code=a["sign_code"]).json()
    assert a["status"] == "ISSUED" and a["loan"]["amount"] == 3610000
    assert [e["to"] for e in a["events"]] == ["SUBMITTED", "DATA_CHECK", "SCORING", "COUNTER_OFFER", "SIGNING",
                                              "ISSUED"]
    assert act(client, h, a["id"], "withdraw").status_code == 409  # выдано - терминальный статус


def test_t1_approve_on_24_months(client):
    h = login(client, "client")
    a = settle(client, h, submit(client, h, "marina", requested_term_m=24).json()["id"])
    assert a["status"] == "APPROVED" and a["offer"]["amount"] == 6000000


def test_t3_documents_requested_then_uploaded(client):
    h = login(client, "client")
    a = settle(client, h, submit(client, h, "docs").json()["id"])
    assert a["status"] == "NEEDS_DATA" and a["documents"] and a["actions"][0] == "upload_documents"
    a = act(client, h, a["id"], "upload_documents").json()
    a = settle(client, h, a["id"])
    assert a["status"] not in ("NEEDS_DATA", "DATA_CHECK", "SCORING")
    assert all(d["status"] == "uploaded" for d in a["documents"])


def test_t4_stop_factor_rejects_without_analyst(client):
    h = login(client, "client")
    a = settle(client, h, submit(client, h, "overdue").json()["id"])
    assert a["status"] == "REJECTED" and a["decision"]["reasons"][0]["code"].startswith("S")
    assert a["actions"] == []


def test_t5_secured_goes_to_analyst_who_decides(client):
    hc, ha = login(client, "client"), login(client, "analyst")
    a = settle(client, hc, submit(client, hc, "bakery").json()["id"])
    assert a["status"] == "ANALYST" and a["whose_turn"] == "bank"
    assert act(client, hc, a["id"], "approve", note="сам себе").status_code == 403
    queue = client.get("/api/v1/applications?status=ANALYST", headers=ha).json()
    assert [q["id"] for q in queue] == [a["id"]]
    card = client.get(f"/api/v1/applications/{a['id']}", headers=ha).json()
    assert card["risk"]["risk_class"] >= 1 and card["risk"]["route_reason"]
    assert act(client, ha, a["id"], "approve").status_code == 422  # комментарий обязателен
    a = act(client, ha, a["id"], "approve", note="залог проверен").json()
    assert a["status"] == "APPROVED" and a["decision"]["by"] == "analyst" and a["offer"]["amount"] > 0


def test_t6_bki_failure_routes_to_analyst_as_technical_error(client):
    h = login(client, "client")
    a = settle(client, h, submit(client, h, "romashka").json()["id"])
    assert a["status"] == "ANALYST" and "БКИ" in a["events"][-1]["note"]


def test_t7_wrong_inn(client):
    r = client.get("/api/v1/companies/1234567890")
    assert r.status_code == 422 and "10 цифр" in r.json()["detail"]
    assert client.get("/api/v1/companies/0000000000").status_code == 404
    c = client.get("/api/v1/companies/0010000017").json()
    assert c["persona_id"] == "marina" and c["sources"]


def test_idempotency_duplicates_and_ownership(client):
    h = login(client, "client")
    first = submit(client, h, "marina", key="k1").json()["id"]
    assert submit(client, h, "marina", key="k1").json()["id"] == first
    assert submit(client, h, "marina").status_code == 409  # активная заявка той же компании и продукта
    other = {"Authorization": "Bearer " + client.post("/api/v1/auth/login", json={
        "username": "client2", "password": "client2"}).json()["token"]}
    assert client.get(f"/api/v1/applications/{first}", headers=other).status_code == 404
    r = client.post("/api/v1/applications", headers=h, json={
        "persona_id": "young", "levers": load_personas()["young"]["levers"], "purpose": "x", "bki_consent": False})
    assert r.status_code == 422


def test_withdraw_before_decision(client):
    h = login(client, "client")
    a = submit(client, h, "bakery").json()
    a = act(client, h, a["id"], "withdraw").json()
    assert a["status"] == "WITHDRAWN" and a["actions"] == []


def test_news_is_personal(client):
    seller = client.get("/api/v1/news?persona_id=marina").json()
    builder = client.get("/api/v1/news?persona_id=docs").json()
    assert seller and builder and {n["id"] for n in seller} != {n["id"] for n in builder}
    assert all(n["why"] for n in seller)
