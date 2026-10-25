"""
Демо-компании песочницы: вымышленные юрлица, их факты (отчётность, история, БКИ) и рычаги заявки по умолчанию.

ИНН демо-компаний начинаются с 00: региона 00 нет, поэтому с реальной компанией они не совпадут, а контрольная цифра
верная. Факты берутся только из файла персонажа, клиент присылает рычаги; отношения считаются так же, как признаки
выборки из отчётности (synth.features).
"""
import json
from pathlib import Path

from scoring.synth import _ratio

PERSONAS_DIR = Path(__file__).resolve().parents[1] / "demo" / "personas"
_INN_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
BKI = ("bki_max_dpd_12m", "bki_overdue_cnt_12m", "bki_current_dpd")
# рычаги, которые клиент меняет сам; всё остальное в заявке - факты персонажа
LEVERS = ("product", "requested_amount", "requested_term_m", "has_rko", "bank_turnover_month_rub", "guarantee",
          "marketplace", "insurance", "subscription")
_COPY = ("okved_section", "okved", "status", "revenue", "ebit", "debt", "debt_service", "equity_ratio", "revenue_growth",
         "revenue_cv", "age_months", "turnover_months", *BKI)


def inn_ok(inn: str) -> bool:
    """ИНН юрлица: 10 цифр, последняя - контрольная."""
    if not (isinstance(inn, str) and len(inn) == 10 and inn.isdigit()):
        return False
    return sum(int(d) * w for d, w in zip(inn, _INN_WEIGHTS)) % 11 % 10 == int(inn[9])


def load_personas(path: Path = PERSONAS_DIR) -> dict:
    out = {}
    for f in sorted(Path(path).glob("*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        out[p["id"]] = p
    return out


def application(persona: dict, levers: dict) -> dict:
    """Заявка для движка: факты персонажа + рычаги клиента. Обороты в банке приходят рублями в месяц и становятся
    долей от суммы заявки; без согласия на БКИ (bki_consent) кредитной истории нет - soft-режим предоценки."""
    f = persona["facts"]
    a = {"inn": persona["inn"], **{k: f[k] for k in _COPY}}
    a["debt_to_revenue"] = f["debt"] / f["revenue"]
    a["debt_to_ebit"] = float(_ratio(f["debt"], f["ebit"]))
    a["interest_cover"] = float(_ratio(f["ebit"], f["interest"], neg=0))
    a["dscr"] = float(_ratio(f["ebit"], f["debt_service"]))
    a["tax_debt_to_revenue"] = f["tax_debt"] / f["revenue"]
    lv = {k: levers[k] for k in LEVERS if k in levers}
    turnover = float(lv.pop("bank_turnover_month_rub", 0) or 0)
    a.update(lv)
    a["bank_turnover_ratio"] = turnover / float(a["requested_amount"]) if a.get("has_rko") else 0.0
    if not levers.get("bki_consent", True):
        a.update({k: None for k in BKI})
    return a
