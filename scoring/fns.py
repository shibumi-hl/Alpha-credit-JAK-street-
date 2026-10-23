"""
Парсеры открытых данных ФНС и ГИР БО (bo.nalog.gov.ru) в плоские строки по ИНН.

revexp (ОТКРДАННЫЕ5) - доходы и расходы по бухотчётности, руб.; debtam (ОТКРДАННЫЕ6) - недоимка,
пени и штрафы по налогам, руб.; ГИР БО - отчётность по годам, тыс. руб. (переводится в руб.).
Только юрлица: ИНН из 10 цифр (ИП - физлица, в выборку не берутся).
"""
import io
import re
import xml.etree.ElementTree as ET
from datetime import date

# Разделы ОКВЭД2 по первым двум цифрам класса
_SECTIONS = [("A", 1, 3), ("B", 5, 9), ("C", 10, 33), ("D", 35, 35), ("E", 36, 39), ("F", 41, 43),
             ("G", 45, 47), ("H", 49, 53), ("I", 55, 56), ("J", 58, 63), ("K", 64, 66), ("L", 68, 68),
             ("M", 69, 75), ("N", 77, 82), ("O", 84, 84), ("P", 85, 85), ("Q", 86, 88), ("R", 90, 93),
             ("S", 94, 96), ("T", 97, 98), ("U", 99, 99)]


def okved_section(code) -> str | None:
    m = re.match(r"\s*(\d{2})", code or "")
    if not m:
        return None
    n = int(m.group(1))
    return next((s for s, lo, hi in _SECTIONS if lo <= n <= hi), None)


def reg_year(ogrn) -> int | None:
    """Год регистрации ЮЛ: 2-3 цифры ОГРН (ОГРН присваивается с 2002 г.)."""
    s = str(ogrn or "")
    return 2000 + int(s[1:3]) if re.fullmatch(r"\d{13}", s) else None


def _iso(d: str) -> str:
    dd, mm, yy = d.split(".")
    return f"{yy}-{mm}-{dd}"


def _docs(xml: bytes):
    for _, el in ET.iterparse(io.BytesIO(xml), events=("end",)):
        if el.tag == "Документ":
            np_ = el.find("СведНП")
            inn = np_.get("ИННЮЛ") if np_ is not None else None
            if inn and re.fullmatch(r"\d{10}", inn):
                yield inn, el
            el.clear()


def parse_revexp(xml: bytes) -> list[dict]:
    rows = []
    for inn, el in _docs(xml):
        s = el.find("СведДохРасх")
        if s is None:
            continue
        rows.append({"inn": inn, "income": float(s.get("СумДоход") or 0), "expenses": float(s.get("СумРасход") or 0),
                     "revexp_date": _iso(el.get("ДатаСост"))})
    return rows


def parse_debtam(xml: bytes) -> list[dict]:
    rows = []
    for inn, el in _docs(xml):
        items = el.findall("СведНедоим")
        f = lambda k: sum(float(i.get(k) or 0) for i in items)  # noqa: E731
        rows.append({"inn": inn, "tax_arrears": f("СумНедНалог"), "tax_penalties": f("СумПени"),
                     "tax_fines": f("СумШтраф"), "tax_debt": f("ОбщСумНедоим"), "debtam_date": _iso(el.get("ДатаСост"))})
    return rows


def _lines(report: dict) -> dict:
    """Все строки отчёта (баланс, ОФР, ДДС) одной коррекции в один словарь, None → нет ключа."""
    corr = (report.get("typeCorrections") or [{}])[0].get("correction") or {}
    out = {}
    for part in ("balance", "financialResult", "fundsMovement"):
        out.update({k: v for k, v in (corr.get(part) or {}).items() if v is not None})
    out["_has_cashflow"] = bool(corr.get("fundsMovement"))
    return out


def _reg_date(org: dict) -> str | None:
    """Дата регистрации: у действующей компании статус ставится при регистрации, поэтому дата статуса
    годится, если её год совпадает с годом из ОГРН."""
    d, y = org.get("statusDate"), reg_year(org.get("ogrn"))
    if org.get("statusCode") == "ACTIVE" and d and y and d[:4] == str(y):
        return d
    return None


def parse_girbo(search: dict, bfo: list, asof: date) -> dict | None:
    """Последний годовой отчёт, поданный строго до asof (данные не позже D-1); None, если его нет."""
    content = search.get("content") or []
    if not content:
        return None
    org = content[0]
    seen = [r for r in bfo if r.get("actualBfoDate") and date.fromisoformat(r["actualBfoDate"]) < asof]
    if not seen:
        return None
    seen.sort(key=lambda r: int(r["period"]))
    last = seen[-1]
    L = _lines(last)
    k = 1000.0  # тыс. руб. → руб.
    g = lambda line: float(L.get(f"current{line}", 0.0)) * k  # noqa: E731

    revenue_by_year = {}
    for r in seen:
        lr, p = _lines(r), int(r["period"])
        if "previous2110" in lr:
            revenue_by_year.setdefault(p - 1, float(lr["previous2110"]) * k)
        if "current2110" in lr:
            revenue_by_year[p] = float(lr["current2110"]) * k
    period = int(last["period"])
    ebt = g(2300) if "current2300" in L else g(2400) + g(2410)
    return {
        "inn": re.sub(r"\D", "", org.get("inn") or ""),
        "okved": org.get("okved2"), "okved_section": okved_section(org.get("okved2")),
        "status": org.get("statusCode"), "ogrn": org.get("ogrn"), "reg_year": reg_year(org.get("ogrn")),
        "reg_date": _reg_date(org),
        "period": period, "bfo_date": last["actualBfoDate"],
        "bfo_years": sum(1 for v in revenue_by_year.values() if v > 0),
        "revenue": revenue_by_year.get(period, 0.0), "revenue_prev": revenue_by_year.get(period - 1),
        "debt_lt": g(1410), "debt_st": g(1510), "debt": g(1410) + g(1510),
        "equity": g(1300), "assets": g(1600),
        "ebit": ebt + g(2330), "interest": g(2330), "net_income": g(2400),
        "interest_paid": g(4123), "loan_repaid": g(4323), "has_cashflow": int(L["_has_cashflow"]),
    }
