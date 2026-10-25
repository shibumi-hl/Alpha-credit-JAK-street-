"""
Моки внешних источников: ЕГРЮЛ и «Прозрачный бизнес» по ИНН, бюро кредитных историй, лента новостей. Данные -
только демо-компании (demo/personas) и синтетические новости (demo/news.json). В банке каждый мок меняется на
реальный сервис сменой адреса, контракт ответа тот же.
"""
import json
from datetime import date
from pathlib import Path

from fastapi import HTTPException

from api.personas import inn_ok

NEWS_PATH = Path(__file__).resolve().parents[1] / "demo" / "news.json"
_STATUS = {"ACTIVE": "Действующая"}


def _months_back(asof: date, months: int) -> date:
    y, m = divmod(asof.year * 12 + asof.month - 1 - months, 12)
    return date(y, m + 1, 1)


def company(personas: dict, inn: str, asof: date) -> dict:
    if not inn_ok(inn):
        raise HTTPException(422, "ИНН юрлица — 10 цифр с верной контрольной цифрой")
    p = next((p for p in personas.values() if p["inn"] == inn), None)
    if p is None:
        raise HTTPException(404, "Не нашли компанию по ИНН")
    f = p["facts"]
    return {"persona_id": p["id"], "name": p["name"], "inn": inn, "ogrn": f"1{inn[2:]}{inn[:3]}",
            "okved": f["okved"], "okved_name": p["okved_name"], "status": f["status"],
            "status_label": _STATUS.get(f["status"], f["status"]),
            "registered": str(_months_back(asof, int(f["age_months"]))), "age_months": f["age_months"],
            "address": p.get("address", "г. Москва (демо-адрес)"), "director_role": "Генеральный директор",
            "sources": [{"name": "ЕГРЮЛ (мок)", "asof": str(asof)},
                        {"name": "Прозрачный бизнес ФНС (мок)", "asof": str(asof)}]}


def bki_available(persona: dict) -> bool:
    """Мок БКИ: у демо-компании с mock.bki_fail бюро «не отвечает» - проверка сбоя внешнего сервиса."""
    return not persona.get("mock", {}).get("bki_fail")


def _matches(when: dict, p: dict, app_status: str | None) -> bool:
    f, lv = p["facts"], p["levers"]
    checks = {
        "okved_section": lambda v: f["okved_section"] in v,
        "product": lambda v: lv["product"] in v,
        "marketplace": lambda v: bool(lv.get("marketplace")) == v,
        "tax_debt": lambda v: (f["tax_debt"] > 0) == v,
        "young": lambda v: (f["age_months"] < 12) == v,
        "overdue": lambda v: (f["bki_current_dpd"] > 0) == v,
        "app_status": lambda v: app_status in v,
        "any": lambda v: v,
    }
    return all(checks[k](v) for k, v in when.items())


def news(persona: dict, app_status: str | None = None) -> list:
    """Лента под клиента: отбор по ОКВЭД, продукту, флагам компании и статусу её заявки; порядок - заявка,
    госпрограмма, налоги, Банк России (слайд 09 защиты)."""
    items = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
    out = [n for n in items if _matches(n["when"], persona, app_status)]
    out.sort(key=lambda n: (n["priority"], n["date"]), reverse=False)
    f = persona["facts"]
    ctx = {"okved": f["okved"], "name": persona["name"]}
    return [{k: n[k] for k in ("id", "date", "tag", "title", "body")} | {"why": n["why"].format(**ctx),
                                                                         "action": n.get("action")} for n in out]
