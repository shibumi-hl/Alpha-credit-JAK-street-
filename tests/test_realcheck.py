import json

import numpy as np
import pandas as pd
import pytest

from scoring.realcheck import CALIBRATION, HOLDOUT, gini_ci, half, real_label, validate


def _write(d, inn, **rec):
    (d / f"{inn}.json").write_text(json.dumps({"inn": inn, "found": True, **rec}, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def companies(tmp_path):
    d = tmp_path / "egrul"
    d.mkdir()
    _write(d, "2000000001", state="Юридическое лицо признано несостоятельным (банкротом)", state_date="05.03.2026")
    _write(d, "2000000002", method="Исключение юридического лица из ЕГРЮЛ", end_date_pdf="14.10.2026")
    _write(d, "2000000003", method="Ликвидация юридического лица", end_date_pdf="01.06.2026")
    _write(d, "2000000004", method="Прекращение деятельности путем реорганизации в форме присоединения",
           end_date_pdf="01.06.2026")
    _write(d, "2000000005", method="Исключение юридического лица из ЕГРЮЛ", end_date_pdf="01.02.2025")  # до отчёта
    c = pd.DataFrame({"inn": ["1000000001", "2000000001", "2000000002", "2000000003", "2000000004", "2000000005",
                              "2000000006"],
                      "status": ["ACTIVE", "LIQUIDATION_STAGE", "INACTIVE", "INACTIVE", "INACTIVE", "INACTIVE",
                                 "INACTIVE"],
                      "bfo_date": ["2026-03-20"] * 5 + ["2025-03-20", "2026-03-20"]})
    return c, d


def test_label_keeps_active_and_distress_after_the_report(companies):
    c, d = companies
    lab = real_label(c, d).set_index("inn")
    assert lab.loc["1000000001", "event"] == 0 and lab.loc["1000000001", "kind"] == "active"
    assert lab.loc["2000000002", "event"] == 1 and lab.loc["2000000002", "kind"] == "struck_off"
    # банкротство с записью 05.03.2026 - до отчёта 20.03.2026: не прогноз, выкидывается
    assert "2000000001" not in lab.index
    # ликвидация, реорганизация, исключение до отчёта, нет выписки - вне выборки
    assert not {"2000000003", "2000000004", "2000000005", "2000000006"} & set(lab.index)
    assert set(lab["half"]) <= {CALIBRATION, HOLDOUT}


def test_halves_are_stable_and_balanced():
    inns = [f"{i:010d}" for i in range(10000)]
    h = [half(x) for x in inns]
    assert h == [half(x) for x in inns]
    assert 0.47 < h.count(HOLDOUT) / len(h) < 0.53


def test_gini_ci_on_known_signal():
    rng = np.random.default_rng(0)
    y = np.r_[np.ones(200), np.zeros(5000)]
    perfect = gini_ci(y, y, n_boot=200)
    assert perfect[0] == pytest.approx(1.0)
    noise = gini_ci(y, rng.random(len(y)), n_boot=200)
    assert abs(noise[0]) < 0.15 and noise[1] <= noise[0] <= noise[2]  # интервал не обязан накрыть 0 в одном прогоне
    sig = gini_ci(y, y + rng.normal(0, 1.0, len(y)), n_boot=200)
    assert sig[1] < sig[0] < sig[2] and sig[0] > 0.4


def test_validate_uses_only_the_holdout_half():
    rng = np.random.default_rng(1)
    n = 6000
    inns = [f"{i:010d}" for i in range(n)]
    event = (rng.random(n) < 0.03).astype(int)
    lab = pd.DataFrame({"inn": inns, "event": event, "kind": np.where(event == 1, "bankruptcy", "active"),
                        "half": [half(x) for x in inns]})
    scored = pd.DataFrame({"inn": inns, "score": 600 - 40 * event + rng.normal(0, 20, n), "pd": 0.05,
                           "risk_class": rng.integers(2, 7, n), "debt": rng.random(n),
                           "points_dscr": -20 * event + rng.normal(0, 10, n)})
    rep = validate(scored, lab, real_factors=["dscr"], n_boot=100)
    hold = lab[lab["half"] == HOLDOUT]
    first = rep["table"].iloc[0]
    assert first["events"] == hold.event.sum()
    assert first["gini_full"] > 0.5 and first["gini_real"] > 0.5
    assert rep["classes"]["n"].sum() == len(hold)


def test_report_dates_are_parsed_and_broken_files_are_skipped(tmp_path):
    d = tmp_path / "eg"
    d.mkdir()
    _write(d, "3000000001", method="Исключение юридического лица из ЕГРЮЛ", end_date_pdf="14.10.2026")
    _write(d, "3000000002", method="Исключение юридического лица из ЕГРЮЛ", end_date_pdf="14.10.2026")
    (d / "3000000003.json").write_text("", encoding="utf-8")  # битый файл
    c = pd.DataFrame({"inn": ["3000000001", "3000000002", "3000000003", "3000000004"],
                      "status": ["INACTIVE", "INACTIVE", "INACTIVE", "INACTIVE"],
                      "bfo_date": ["30.03.2026", None, "2026-03-20", "2026-03-20"]})
    lab = real_label(c, d)
    assert list(lab.inn) == ["3000000001"]  # дата отчёта в формате ДД.ММ.ГГГГ понята; без даты - вне выборки
    assert lab.attrs["skipped"] == {"no_report_date": 1, "unreadable": 1, "no_extract": 1}
