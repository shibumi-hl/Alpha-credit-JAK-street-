import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scoring import synth
from scoring.calibrate import FIT_TERMS, fit_weights

ASOF = date(2026, 10, 23)


def _terms(n, rng):
    return pd.DataFrame({t: (rng.random(n) < 0.3).astype(float) for t in FIT_TERMS})


def test_fit_recovers_known_weights():
    rng = np.random.default_rng(0)
    n = 60000
    X = _terms(n, rng)
    true = {t: 0.0 for t in FIT_TERMS} | {"loss": 1.2, "dscr_lt1": 0.8, "fall": 0.5}
    z = -4 + sum(true[t] * X[t] for t in FIT_TERMS)
    y = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(int)
    sections = pd.Series(rng.choice(list("FGC"), n))
    w = fit_weights(X, sections, y, c=10.0)
    for t in ("loss", "dscr_lt1", "fall"):
        assert w["weights"][t] == pytest.approx(true[t], abs=0.2)
    assert all(abs(w["weights"][t]) < 0.25 for t in FIT_TERMS if true[t] == 0)
    assert abs(sum(w["sector"].values())) < 1e-9 or set(w["sector"]) == {"F", "G", "C"}


def test_risk_term_with_wrong_sign_is_zeroed_and_listed():
    rng = np.random.default_rng(1)
    n = 40000
    X = _terms(n, rng)
    z = -3.5 + 1.0 * X["loss"] - 0.9 * X["lev"]  # «долг снижает риск» - как пустые фирмы без долгов
    y = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(int)
    w = fit_weights(X, pd.Series(["G"] * n), y, c=10.0)
    assert w["weights"]["lev"] == 0 and "lev" in w["dropped"]
    assert w["weights"]["loss"] == pytest.approx(1.0, abs=0.2)


def test_tax_is_not_fitted():
    assert "tax" not in FIT_TERMS


def test_synth_uses_calibration_file_and_falls_back_without_it(tmp_path):
    raw = synth.generate_real(4000, np.random.default_rng(3), ASOF)
    assert synth.load_calibration(tmp_path / "none.json") is None
    cal = {"weights": {"loss": 6.0}, "sector": {"G": 0.0}}
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(cal), encoding="utf-8")
    w = synth.load_calibration(p)
    assert w["loss"] == 6.0 and w["lev"] == synth.DEFAULT_WEIGHTS["lev"] and w["sector"] == {"G": 0.0}
    base = synth.enrich(raw, 3, ASOF)
    heavy = synth.enrich(raw, 3, ASOF, weights=w)
    gap = lambda d: d[d.ebit < 0].default_12m.mean() - d[d.ebit >= 0].default_12m.mean()  # noqa: E731
    assert gap(heavy) > gap(base) + 0.05


def test_script_fits_on_the_calibration_half_and_writes_config(tmp_path, monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path
    from scoring.realcheck import CALIBRATION, half
    spec = importlib.util.spec_from_file_location("cal", Path(__file__).resolve().parents[1] / "scripts" / "calibrate_synth.py")
    cal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cal)
    rng = np.random.default_rng(4)
    raw = synth.generate_real(8000, rng, ASOF)
    raw["bfo_date"] = "2026-03-20"
    p_event = np.where(raw.ebit < 0, 0.12, 0.01)  # убыточные закрываются чаще
    event = rng.random(len(raw)) < p_event
    raw["status"] = np.where(event, "INACTIVE", "ACTIVE")
    (tmp_path / "fns").mkdir()
    raw.to_csv(tmp_path / "fns" / "companies.csv", index=False, encoding="utf-8-sig")
    eg = tmp_path / "raw" / "egrul"
    eg.mkdir(parents=True)
    for inn in raw.inn[event]:
        (eg / f"{inn}.json").write_text(json.dumps({"inn": inn, "method": "Исключение юридического лица из ЕГРЮЛ",
                                                    "end_date_pdf": "01.08.2026"}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "cal.json"
    monkeypatch.setattr(sys, "argv", ["x", "--data-dir", str(tmp_path), "--out", str(out), "--asof", "2026-10-23"])
    cal.main()
    res = json.loads(out.read_text(encoding="utf-8"))
    calib_events = sum(1 for inn in raw.inn[event] if half(inn) == CALIBRATION)
    assert res["events"] == calib_events and res["half"] == CALIBRATION
    assert set(res["weights"]) == set(FIT_TERMS) and res["weights"]["loss"] > 1.0
