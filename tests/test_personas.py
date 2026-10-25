import numpy as np
import pytest

from api.personas import application, inn_ok, load_personas
from scoring.credit import KEY_DATA, load_policy, validate


def test_inn_checksum():
    assert inn_ok("0010000017")
    assert not inn_ok("0010000018")  # контрольная цифра не та
    assert not inn_ok("001000001")  # 9 цифр
    assert not inn_ok("00100000a7")


def test_personas_are_fictional_legal_entities_with_complete_facts():
    personas = load_personas()
    assert len(personas) == 6 and "marina" in personas  # шестая - «Ромашка» для проверки сбоя БКИ (T6)
    policy = load_policy()
    for pid, p in personas.items():
        assert p["id"] == pid and p["name"] and p["tagline"]
        assert inn_ok(p["inn"]) and p["inn"].startswith("00")  # региона 00 нет - с реальной компанией не совпадёт
        a = application(p, {**p["levers"], "bki_consent": True})
        validate(a, policy)
        assert all(np.isfinite(float(a[k])) for k in KEY_DATA), pid  # без дозапроса из-за пустых ключевых полей


def test_application_takes_facts_from_the_persona_and_levers_from_the_client():
    p = load_personas()["marina"]
    levers = {**p["levers"], "has_rko": 1, "bank_turnover_month_rub": 1_500_000, "requested_amount": 3_000_000,
              "bki_consent": True, "revenue": 1.0, "ebit": 1e12}  # чужие поля среди рычагов не попадают в заявку
    a = application(p, levers)
    assert a["revenue"] == p["facts"]["revenue"] and a["ebit"] == p["facts"]["ebit"]
    assert a["bank_turnover_ratio"] == pytest.approx(0.5)  # месячный оборот в банке / сумма заявки
    assert a["debt_to_revenue"] == pytest.approx(p["facts"]["debt"] / p["facts"]["revenue"])
    assert a["dscr"] == pytest.approx(p["facts"]["ebit"] / p["facts"]["debt_service"])
    assert a["bki_current_dpd"] == p["facts"]["bki_current_dpd"]
    soft = application(p, {**levers, "bki_consent": False})
    assert soft["bki_current_dpd"] is None and soft["bki_max_dpd_12m"] is None  # без согласия БКИ не запрашиваем
    no_rko = application(p, {**levers, "has_rko": 0})
    assert no_rko["bank_turnover_ratio"] == 0
