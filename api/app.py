"""
API песочницы кредита: демо-компании, расчёт заявки, сценарии «что если» и развёртка кривых.

Клиент присылает persona_id и рычаги, факты берутся только из файла демо-компании (api.personas). Движок грузится
один раз при старте; ответы кэшируются по (компания, рычаги) - движок детерминирован.

  uvicorn --factory api.app:create_app --host 127.0.0.1 --port 3100     # ENGINE_PATH - путь к engine.pkl
"""
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api import dto
from api.personas import application, load_personas
from scoring.whatif import AXES, SCENARIOS, Engine, _derive, evaluate, simulate, whatif

ROOT = Path(__file__).resolve().parents[1]
TERMS = (3, 6, 9, 12, 18, 24, 30, 36, 48, 60)  # сетка срока для развёртки, мес.


class Levers(BaseModel):
    """Что клиент меняет сам. Лишние поля (выручка, БКИ…) отбрасываются: факты - только из демо-компании."""
    product: str
    requested_amount: float = Field(ge=10_000, le=300_000_000)
    requested_term_m: int = Field(ge=1, le=120)
    has_rko: bool = False
    bank_turnover_month_rub: float = Field(0, ge=0, le=10_000_000_000)
    guarantee: bool = False
    marketplace: bool = False
    insurance: bool = False
    subscription: bool = False
    bki_consent: bool = True


class Ask(BaseModel):
    persona_id: str
    levers: Levers


class Sweep(Ask):
    axis: Literal[AXES] = "requested_amount"
    n: int = Field(32, ge=4, le=64)


def _amount_grid(levers: dict, product: dict, revenue: float, n: int, base: dict, step: int) -> list:
    """Логарифмическая сетка от минимума продукта до min(максимум, max(3× запрос, 0,6× выручки)), кратная шагу
    округления, плюс сам запрос и точки на лимите ±1 шаг - чтобы излом кривой был резким."""
    lo = float(product["min_amount"])
    hi = float(min(product["max_amount"], max(3 * levers["requested_amount"], 0.6 * revenue)))
    xs = {lo, hi, float(levers["requested_amount"])}
    for i in range(1, n - 1):
        xs.add(float(round(lo * (hi / lo) ** (i / (n - 1)) / step) * step))
    lim = base["limit"]
    if lo < lim < hi:
        xs |= {float(lim), float(lim - step), float(lim + step)}
    return sorted(x for x in xs if lo <= x <= hi)


def create_app(engine: Engine = None, personas: dict = None) -> FastAPI:
    engine = engine or Engine.load(Path(os.environ.get("ENGINE_PATH", ROOT / "data" / "scoring" / "engine.pkl")))
    personas = personas or load_personas()
    policy = engine.policy
    app = FastAPI(title="МойАльфаКредит · песочница", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.exception_handler(ValueError)
    def _bad_application(_: Request, e: ValueError):  # некорректная заявка: текст движка уже по-русски
        return JSONResponse(status_code=422, content={"detail": str(e)})

    def persona(pid: str) -> dict:
        if pid not in personas:
            raise HTTPException(404, "Нет такой демо-компании")
        return personas[pid]

    @lru_cache(maxsize=512)
    def _evaluate(pid: str, key: str) -> dict:
        a = application(personas[pid], json.loads(key))
        return dto.evaluation(evaluate(engine, a), _derive(a, policy), policy)

    @lru_cache(maxsize=256)
    def _whatif(pid: str, key: str) -> dict:
        levers = json.loads(key)
        a = application(personas[pid], levers)
        out = whatif(engine, a)
        d = _derive(a, policy)
        scenarios = []
        for s in out["scenarios"]:  # рычаги, которые воспроизводят сценарий: «Применить» на фронте
            change = SCENARIOS[s["key"]][2](d, out["base"])
            new = {**levers, **{k: v for k, v in change.items() if k != "bank_turnover_ratio"}}
            if "bank_turnover_ratio" in change:
                new["bank_turnover_month_rub"] = round(change["bank_turnover_ratio"] * new["requested_amount"])
            scenarios.append({**s, "levers": new})
        return {"base": dto.evaluation(out["base"], d, policy), "scenarios": scenarios}

    @lru_cache(maxsize=256)
    def _simulate(pid: str, key: str, axis: str, n: int) -> dict:
        levers = json.loads(key)
        p = personas[pid]
        base = _evaluate(pid, key)
        if axis == "requested_amount":
            grid = _amount_grid(levers, policy["products"][levers["product"]], p["facts"]["revenue"], n, base,
                                policy["round_to"])
        else:
            if levers["product"] in dto.REVOLVING:
                raise HTTPException(422, "У возобновляемого продукта нет срока")
            grid = sorted({*TERMS, int(levers["requested_term_m"])})
        same = base["outcome"] == "COUNTER" and base["offered_product"] == base["product"]
        return {"axis": axis, "points": simulate(engine, application(p, levers), axis, grid),
                "limit": base["limit"], "binding": base["reasons"][0]["code"] if same else None,
                "requested": levers[axis]}

    def _key(ask: Ask) -> tuple:
        persona(ask.persona_id)
        return ask.persona_id, json.dumps(ask.levers.model_dump(), sort_keys=True)

    @app.get("/api/health")
    def health():
        return {"ok": True, "asof": str(engine.asof)}

    @app.get("/api/v1/meta")
    def meta():
        return dto.meta(engine)

    @app.get("/api/v1/personas")
    def personas_list():
        return [dto.persona_card(p) for p in personas.values()]

    @app.get("/api/v1/personas/{pid}")
    def persona_detail(pid: str):
        return dto.persona_detail(persona(pid))

    @app.post("/api/v1/evaluations")
    def evaluations(ask: Ask):
        return _evaluate(*_key(ask))

    @app.post("/api/v1/whatif")
    def whatif_(ask: Ask):
        return _whatif(*_key(ask))

    @app.post("/api/v1/simulate")
    def simulate_(sweep: Sweep):
        return _simulate(*_key(sweep), sweep.axis, sweep.n)

    return app
