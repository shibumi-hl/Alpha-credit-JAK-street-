import warnings
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import mocks
from api.app import create_app
from api.integrations import Integrations
from api.personas import load_personas
from scoring.whatif import Engine

warnings.filterwarnings("ignore")
ENGINE = Path(__file__).resolve().parents[1] / "models" / "engine.pkl"
MOCK = {"REGISTRY_URL": "http://testserver/api/mock/registry", "BKI_URL": "http://testserver/api/mock/bki",
        "NEWS_URL": "http://testserver/api/mock/news"}


@pytest.fixture(scope="module")
def engine():
    return Engine.load(ENGINE)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("PIPELINE_STEP_DELAY", "0")
    monkeypatch.setenv("SECRET_KEY", "test")
    for k in MOCK:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_builtin_mocks_answer_over_http_with_the_api_contract(engine, env):
    c = TestClient(create_app(engine))
    assert c.get("/api/mock/registry/companies/0010000017").json() == c.get("/api/v1/companies/0010000017").json()
    assert c.get("/api/mock/registry/companies/1234567890").status_code == 422
    assert c.get("/api/mock/registry/companies/0000000000").status_code == 404
    bki = c.get("/api/mock/bki/reports/0010000017")
    assert bki.status_code == 200 and bki.json()["current_dpd"] == 0
    assert c.get("/api/mock/bki/reports/0060000005").status_code == 503  # «Ромашка»: бюро не отвечает (T6)
    feed = c.get("/api/mock/news/feed", params={"inn": "0010000017"}).json()
    assert feed == c.get("/api/v1/news", params={"persona_id": "marina"}).json()


def test_service_address_in_env_switches_to_http_with_the_same_answers(engine, env):
    app = create_app(engine)
    http = TestClient(app)
    personas, asof = load_personas(), engine.asof
    builtin, remote = Integrations(personas, asof, env={}), Integrations(personas, asof, env=MOCK, http=http)
    assert remote.urls == {"registry": MOCK["REGISTRY_URL"], "bki": MOCK["BKI_URL"], "news": MOCK["NEWS_URL"]}
    assert remote.company("0010000017") == builtin.company("0010000017")
    for bad, code in (("1234567890", 422), ("0000000000", 404)):
        with pytest.raises(HTTPException) as e:
            remote.company(bad)
        assert e.value.status_code == code
    assert remote.bki_available(personas["marina"]) and not remote.bki_available(personas["romashka"])
    assert remote.news(personas["marina"], None) == mocks.news(personas["marina"], None)


class Flaky:
    """HTTP-клиент, у которого первые fails запросов падают с ошибкой соединения."""

    def __init__(self, fails):
        self.fails, self.calls = fails, 0

    def get(self, url, **kw):
        self.calls += 1
        if self.calls <= self.fails:
            raise httpx.ConnectError("нет связи")
        return httpx.Response(200, json={}, request=httpx.Request("GET", url))


def test_bki_is_retried_three_times_then_reported_down():
    p = load_personas()["marina"]
    ok = Flaky(fails=2)
    assert Integrations({}, None, env=MOCK, http=ok).bki_available(p) and ok.calls == 3
    down = Flaky(fails=99)
    assert not Integrations({}, None, env=MOCK, http=down).bki_available(p) and down.calls == 3


def test_conveyor_runs_over_http_when_addresses_are_set(engine, env):
    for k, v in MOCK.items():
        env.setenv(k, v)
    app = create_app(engine)
    client = TestClient(app)
    app.state.integrations.http = client  # «внешние» сервисы - встроенные моки этого же приложения по HTTP
    assert app.state.integrations.urls["bki"] == MOCK["BKI_URL"]
    h = {"Authorization": "Bearer " + client.post("/api/v1/auth/login",
                                                  json={"username": "client", "password": "client"}).json()["token"]}
    lv = {**load_personas()["romashka"]["levers"], "bki_consent": True}
    app_id = client.post("/api/v1/applications", headers=h, json={"persona_id": "romashka", "levers": lv,
                                                                   "purpose": "закупка", "bki_consent": True}).json()["id"]
    for _ in range(5):
        a = client.get(f"/api/v1/applications/{app_id}", headers=h).json()
    assert a["status"] == "ANALYST" and "БКИ" in a["events"][-1]["note"]
    assert client.get("/api/v1/companies/0060000005").json()["persona_id"] == "romashka"
