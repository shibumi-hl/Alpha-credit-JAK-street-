from datetime import date

import pytest

from scoring.fns import okved_section, parse_debtam, parse_girbo, parse_revexp, reg_year

# Синтетические файлы в формате открытых данных ФНС (ОТКРДАННЫЕ5 / ОТКРДАННЫЕ6)
REVEXP = """<?xml version="1.0" encoding="UTF-8"?><Файл ИдФайл="X" ВерсФорм="4.01" ТипИнф="ОТКРДАННЫЕ5" КолДок="3">
<Документ ИдДок="1" ДатаДок="25.09.2026" ДатаСост="31.12.2025"><СведНП НаимОрг="ООО &quot;А&quot;" ИННЮЛ="1234567890"/>
<СведДохРасх СумДоход="1000000.00" СумРасход="800000.00"/></Документ>
<Документ ИдДок="2" ДатаДок="25.09.2026" ДатаСост="31.12.2025"><СведНП НаимОрг="ИП Б" ИННЮЛ="123456789012"/>
<СведДохРасх СумДоход="5.00" СумРасход="1.00"/></Документ>
<Документ ИдДок="3" ДатаДок="25.09.2026" ДатаСост="31.12.2025"><СведНП НаимОрг="ООО &quot;В&quot;" ИННЮЛ="0987654321"/>
<СведДохРасх СумДоход="0.00" СумРасход="10.00"/></Документ></Файл>""".encode("utf-8")

DEBTAM = """<?xml version="1.0" encoding="UTF-8"?><Файл ИдФайл="Y" ТипИнф="ОТКРДАННЫЕ6" КолДок="1">
<Документ ИдДок="1" ДатаДок="25.09.2026" ДатаСост="01.09.2026"><СведНП НаимОрг="ООО &quot;А&quot;" ИННЮЛ="1234567890"/>
<СведНедоим НаимНалог="НДС" СумНедНалог="1000.00" СумПени="0.00" СумШтраф="0.00" ОбщСумНедоим="1000.00"/>
<СведНедоим НаимНалог="Суммы пеней" СумНедНалог="0.00" СумПени="50.50" СумШтраф="10.00" ОбщСумНедоим="60.50"/>
</Документ></Файл>""".encode("utf-8")


def test_revexp_keeps_legal_entities_with_amounts():
    rows = parse_revexp(REVEXP)
    assert [r["inn"] for r in rows] == ["1234567890", "0987654321"]
    assert rows[0] == {"inn": "1234567890", "income": 1_000_000.0, "expenses": 800_000.0,
                       "revexp_date": "2025-12-31"}


def test_debtam_sums_all_taxes_per_company():
    (row,) = parse_debtam(DEBTAM)
    assert row["inn"] == "1234567890"
    assert row["tax_arrears"] == pytest.approx(1000.0)
    assert row["tax_penalties"] == pytest.approx(50.5)
    assert row["tax_fines"] == pytest.approx(10.0)
    assert row["tax_debt"] == pytest.approx(1060.5)
    assert row["debtam_date"] == "2026-09-01"


@pytest.mark.parametrize("code,section", [("01.11", "A"), ("10.71", "C"), ("41.20", "F"), ("47.11", "G"),
                                          ("64.20", "K"), ("68", "L"), ("99.00", "U"), ("", None), (None, None)])
def test_okved_section(code, section):
    assert okved_section(code) == section


def test_reg_year_from_ogrn():
    assert reg_year("1115809002055") == 2011
    assert reg_year("1207700227118") == 2020
    assert reg_year("bad") is None


def _report(period, filed, revenue, prev_revenue, debt_lt=0.0, debt_st=0.0, cashflow=None):
    corr = {
        "balance": {"current1410": debt_lt, "current1510": debt_st, "current1300": 500.0, "current1600": 2000.0},
        "financialResult": {"current2110": revenue, "previous2110": prev_revenue, "current2300": 100.0,
                            "current2330": 20.0, "current2400": 80.0},
        "fundsMovement": cashflow,
    }
    return {"period": period, "actualBfoDate": filed, "typeCorrections": [{"type": 12, "correction": corr}]}


SEARCH = {"content": [{"id": 1, "inn": "<strong>1234567890</strong>", "ogrn": "1115809002055", "okved2": "10.71",
                       "statusCode": "ACTIVE", "statusDate": "2011-10-27"}]}


def test_girbo_takes_latest_report_filed_before_asof():
    bfo = [_report("2024", "2025-03-28", 1500.0, 1400.0, debt_lt=300.0, debt_st=200.0),
           _report("2025", "2026-03-26", 1800.0, 1500.0, debt_lt=999.0)]
    row = parse_girbo(SEARCH, bfo, asof=date(2026, 3, 26))  # отчёт 2025 подан в день D - ещё не виден
    assert row["period"] == 2024
    assert row["revenue"] == 1_500_000.0  # тыс. руб. → руб.
    assert row["revenue_prev"] == 1_400_000.0
    assert row["debt"] == 500_000.0
    assert row["ebit"] == 120_000.0
    assert row["interest"] == 20_000.0
    assert row["bfo_years"] == 2  # 2024 и 2023 (previous)
    assert row["okved"] == "10.71" and row["okved_section"] == "C" and row["reg_year"] == 2011
    assert row["has_cashflow"] == 0


def test_girbo_cashflow_debt_service_when_present():
    bfo = [_report("2025", "2026-03-26", 1800.0, 1500.0, cashflow={"current4123": 15.0, "current4323": 250.0})]
    row = parse_girbo(SEARCH, bfo, asof=date(2026, 10, 20))
    assert row["has_cashflow"] == 1
    assert row["interest_paid"] == 15_000.0 and row["loan_repaid"] == 250_000.0


def test_girbo_no_reports_before_asof_returns_none():
    assert parse_girbo(SEARCH, [_report("2025", "2026-03-26", 1.0, 1.0)], asof=date(2026, 1, 1)) is None
    assert parse_girbo({"content": []}, [], asof=date(2026, 1, 1)) is None


def test_girbo_registration_date_only_when_consistent_with_ogrn():
    bfo = [_report("2025", "2026-03-26", 1800.0, 1500.0)]
    assert parse_girbo(SEARCH, bfo, asof=date(2026, 10, 20))["reg_date"] == "2011-10-27"
    other = {"content": [{**SEARCH["content"][0], "statusDate": "2019-05-01"}]}
    assert parse_girbo(other, bfo, asof=date(2026, 10, 20))["reg_date"] is None


def test_non_numeric_inn_is_dropped():
    xml = ("""<?xml version="1.0" encoding="UTF-8"?><Файл><Документ ДатаСост="31.12.2025">"""
           """<СведНП ИННЮЛ="..\..\evil"/><СведДохРасх СумДоход="5" СумРасход="1"/></Документ></Файл>""").encode("utf-8")
    assert parse_revexp(xml) == []
