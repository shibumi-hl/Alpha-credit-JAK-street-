"""
Внешние сервисы конвейера за единым HTTP-контрактом: реестры (ЕГРЮЛ и «Прозрачный бизнес» по ИНН), бюро кредитных
историй и лента новостей. Адрес сервиса - переменная окружения (REGISTRY_URL, BKI_URL, NEWS_URL): задан - запрос по
HTTP, не задан - встроенный мок api.mocks с тем же ответом. Встроенные моки отвечают и по HTTP (/api/mock/*), так что
контракт проверяется без внешней сети, а настоящий сервис банка подключается сменой адреса, без правок конвейера.

Контракт:
  GET {REGISTRY_URL}/companies/{inn}       карточка компании; 422 - ИНН не юрлица, 404 - не найдена
  GET {BKI_URL}/reports/{inn}              отчёт бюро; 200 - получен, иначе (или нет связи) - бюро недоступно
  GET {NEWS_URL}/feed?inn=...&status=...   лента под компанию и статус её заявки
"""
import os
from datetime import date

import httpx
from fastapi import APIRouter, HTTPException

from api import mocks

SERVICES = {"registry": "REGISTRY_URL", "bki": "BKI_URL", "news": "NEWS_URL"}
BKI_RETRIES = 3  # «бюро не ответило после 3 попыток» - и в журнале заявки
TIMEOUT = 5.0


class Integrations:
    def __init__(self, personas: dict, asof: date, env=None, http=None):
        env = os.environ if env is None else env
        self.personas, self.asof = personas, asof
        self.urls = {k: (env.get(v) or "").rstrip("/") for k, v in SERVICES.items()}
        self.http = http or httpx.Client(timeout=TIMEOUT)

    def company(self, inn: str) -> dict:
        url = self.urls["registry"]
        if not url:
            return mocks.company(self.personas, inn, self.asof)
        r = self.http.get(f"{url}/companies/{inn}")
        if r.status_code in (404, 422):  # ответ реестра клиенту как есть: не юрлицо или не нашли
            raise HTTPException(r.status_code, r.json().get("detail", "Реестр не нашёл компанию"))
        r.raise_for_status()
        return r.json()

    def bki_available(self, persona: dict) -> bool:
        url = self.urls["bki"]
        if not url:
            return mocks.bki_available(persona)
        for _ in range(BKI_RETRIES):
            try:
                if self.http.get(f"{url}/reports/{persona['inn']}").status_code == 200:
                    return True
            except httpx.HTTPError:
                pass  # нет связи - следующая попытка
        return False

    def news(self, persona: dict, app_status: str | None) -> list:
        url = self.urls["news"]
        if not url:
            return mocks.news(persona, app_status)
        r = self.http.get(f"{url}/feed", params={"inn": persona["inn"], "status": app_status or ""})
        r.raise_for_status()
        return r.json()


def mock_router(personas: dict, asof: date) -> APIRouter:
    """Встроенные моки по HTTP с тем же контрактом, что у настоящих сервисов (адреса - в docs/api.md)."""
    router = APIRouter(prefix="/api/mock", tags=["моки внешних сервисов"])
    by_inn = {p["inn"]: p for p in personas.values()}

    def persona(inn: str) -> dict:
        if inn not in by_inn:
            raise HTTPException(404, "Нет такой компании")
        return by_inn[inn]

    @router.get("/registry/companies/{inn}")
    def registry(inn: str):
        return mocks.company(personas, inn, asof)

    @router.get("/bki/reports/{inn}")
    def bki(inn: str):
        p = persona(inn)
        if not mocks.bki_available(p):
            raise HTTPException(503, "Бюро кредитных историй не отвечает (мок сбоя)")
        f = p["facts"]
        return {"inn": inn, "current_dpd": f["bki_current_dpd"], "max_dpd_12m": f["bki_max_dpd_12m"],
                "overdue_cnt_12m": f["bki_overdue_cnt_12m"], "asof": str(asof)}

    @router.get("/news/feed")
    def feed(inn: str, status: str = ""):
        return mocks.news(persona(inn), status or None)

    return router
