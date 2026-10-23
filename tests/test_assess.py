import importlib.util
import json
import os
import subprocess
import sys
import warnings
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scoring import synth
from scoring.assess import OUTCOMES, assess
from scoring.credit import load_policy
from scoring.scorecard import train

warnings.filterwarnings("ignore")
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_assess_gives_score_class_decision_and_reasons():
    df = synth.generate(8000, seed=21, asof=date(2026, 10, 20))
    model, _ = train(df, seed=3)
    out = assess(df, model, load_policy())
    assert len(out) == len(df)
    assert set(out.outcome) <= set(OUTCOMES) and len(set(out.outcome)) >= 3
    rej = out[out.outcome == "REJECT"]
    assert (rej.stop_codes.str.len() + rej.reason_codes.str.len() > 0).all()
    assert (out.loc[out.outcome == "APPROVE", "offered_amount"] == df.loc[out.outcome == "APPROVE", "requested_amount"]).all()
    cnt = out[out.outcome == "COUNTER"]
    mins = cnt.offered_product.map(lambda p: load_policy()["products"][p]["min_amount"])
    assert (cnt.offered_amount <= cnt.limit).all() and (cnt.offered_amount >= mins).all()
    routed = out[out.route.notna()]
    assert len(routed) and (routed.offered_product != routed["product"]).all()
    # хуже класс - чаще отказ
    worst, best = out.risk_class.max(), out.risk_class.min()
    assert (out[out.risk_class == worst].outcome == "REJECT").mean() > (out[out.risk_class == best].outcome == "REJECT").mean()


def test_scripts_end_to_end_on_synthetic(tmp_path, monkeypatch, capsys):
    build, tr, sc = _load("build_scoring_sample"), _load("train_scorecard"), _load("score_company")
    monkeypatch.setattr(sys, "argv", ["x", "--synthetic", "6000", "--data-dir", str(tmp_path)])
    build.main()
    sample = pd.read_csv(tmp_path / "scoring" / "train.csv", dtype={"inn": str})
    assert {"default_12m", *synth.FEATURES} <= set(sample.columns)
    monkeypatch.setattr(sys, "argv", ["x", "--data-dir", str(tmp_path), "--report-dir", str(tmp_path)])
    tr.main()
    assert (tmp_path / "scoring" / "engine.pkl").exists()
    assert list(tmp_path.glob("scorecard_*.md"))
    assessed = pd.read_csv(tmp_path / "scoring" / "assessed.csv", dtype={"inn": str})
    assert {"rate", "all_in", "approval_probability", "offered_product"} <= set(assessed.columns)
    monkeypatch.setattr(sys, "argv", ["x", "--inn", sample.inn.iloc[0], "--data-dir", str(tmp_path)])
    capsys.readouterr()
    sc.main()
    txt = capsys.readouterr().out
    assert "PD" in txt and any(o in txt for o in OUTCOMES)
    monkeypatch.setattr(sys, "argv", ["x", "--inn", sample.inn.iloc[1], "--whatif", "--format", "json",
                                      "--data-dir", str(tmp_path)])
    sc.main()
    res = json.loads(capsys.readouterr().out)
    assert res["base"]["outcome"] in OUTCOMES and res["scenarios"]
    assert all("delta_approval_pp" in s for s in res["scenarios"])
    script = str(SCRIPTS / "score_company.py")
    env = {**os.environ, "PYTHONIOENCODING": "cp1251"}  # вывод в файл/пайп в кодировке Windows по умолчанию
    run = subprocess.run([sys.executable, script, "--inn", sample.inn.iloc[1], "--whatif", "--data-dir", str(tmp_path)],
                         capture_output=True, env=env)
    assert run.returncode == 0, run.stderr.decode("cp1251", "replace")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**sample.iloc[1].to_dict(), "product": "leasing"}, default=str), encoding="utf-8")
    run = subprocess.run([sys.executable, script, "--json", str(bad), "--format", "json", "--data-dir", str(tmp_path)],
                         capture_output=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert run.returncode == 2
    assert "продукт" in json.loads(run.stdout.decode("utf-8"))["error"]


def test_score_company_unknown_inn_fails_cleanly(tmp_path, monkeypatch):
    build, tr, sc = _load("build_scoring_sample"), _load("train_scorecard"), _load("score_company")
    monkeypatch.setattr(sys, "argv", ["x", "--synthetic", "4000", "--data-dir", str(tmp_path)])
    build.main()
    monkeypatch.setattr(sys, "argv", ["x", "--data-dir", str(tmp_path), "--report-dir", str(tmp_path)])
    tr.main()
    monkeypatch.setattr(sys, "argv", ["x", "--inn", "1111111111", "--data-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        sc.main()


def test_build_sample_refuses_data_newer_than_asof(tmp_path, monkeypatch):
    import numpy as np
    raw = synth.generate_real(300, np.random.default_rng(3), date(2026, 10, 22))
    raw["bfo_date"], raw["debtam_date"] = "2026-03-20", "2026-09-01"
    raw.loc[::2, "debtam_date"] = None  # у большинства компаний налогового долга нет - даты среза тоже
    (tmp_path / "fns").mkdir()
    raw.to_csv(tmp_path / "fns" / "companies.csv", index=False, encoding="utf-8-sig")
    build = _load("build_scoring_sample")
    monkeypatch.setattr(sys, "argv", ["x", "--asof", "2025-06-01", "--data-dir", str(tmp_path)])
    with pytest.raises(SystemExit, match="D-1"):
        build.main()
    assert not (tmp_path / "scoring" / "train.csv").exists()
    monkeypatch.setattr(sys, "argv", ["x", "--asof", "2026-10-22", "--data-dir", str(tmp_path)])
    build.main()
    assert (tmp_path / "scoring" / "train.csv").exists()


def test_train_builds_reports_for_both_capital_approaches(tmp_path, monkeypatch):
    from scoring.whatif import Engine
    build, tr = _load("build_scoring_sample"), _load("train_scorecard")
    monkeypatch.setattr(sys, "argv", ["x", "--synthetic", "3000", "--data-dir", str(tmp_path)])
    build.main()
    monkeypatch.setattr(sys, "argv", ["x", "--capital-approach", "both", "--data-dir", str(tmp_path),
                                      "--report-dir", str(tmp_path)])
    tr.main()
    assert len(list(tmp_path.glob("scorecard_*_irb.md"))) == 1
    assert len(list(tmp_path.glob("scorecard_*_standard.md"))) == 1
    assert Engine.load(tmp_path / "scoring" / "engine.pkl").pricing["capital"]["approach"] == "irb"  # конфиг по умолчанию
    monkeypatch.setattr(sys, "argv", ["x", "--capital-approach", "standard", "--data-dir", str(tmp_path),
                                      "--report-dir", str(tmp_path)])
    tr.main()
    assert Engine.load(tmp_path / "scoring" / "engine.pkl").pricing["capital"]["approach"] == "standard"


def test_real_check_on_the_holdout_half(tmp_path):
    import numpy as np
    from scoring.realcheck import HOLDOUT, half
    from scoring.scorecard import train
    tr = _load("train_scorecard")
    df = synth.generate(6000, seed=8, asof=date(2026, 10, 23))
    model, _ = train(df, seed=2)
    assert tr.real_check(df, model, tmp_path) is None  # нет данных ЕГРЮЛ - нет раздела
    rng = np.random.default_rng(8)
    event = (rng.random(len(df)) < np.where(df.default_12m == 1, 0.5, 0.01))
    comp = pd.DataFrame({"inn": df.inn, "status": np.where(event, "INACTIVE", "ACTIVE"), "bfo_date": "2026-03-20"})
    (tmp_path / "fns").mkdir()
    comp.to_csv(tmp_path / "fns" / "companies.csv", index=False, encoding="utf-8-sig")
    eg = tmp_path / "raw" / "egrul"
    eg.mkdir(parents=True)
    for inn in df.inn[event]:
        (eg / f"{inn}.json").write_text(json.dumps({"inn": inn, "method": "Исключение юридического лица из ЕГРЮЛ",
                                                    "end_date_pdf": "01.08.2026"}, ensure_ascii=False), encoding="utf-8")
    rep = tr.real_check(df, model, tmp_path, n_boot=50)
    holdout_events = sum(1 for inn in df.inn[event] if half(inn) == HOLDOUT)
    assert rep["events"] == holdout_events
    assert rep["table"].iloc[0]["gini_full"] > 0.2


def test_report_has_the_real_label_section_only_for_the_real_sample(tmp_path, monkeypatch):
    import numpy as np
    build, tr = _load("build_scoring_sample"), _load("train_scorecard")
    raw = synth.generate_real(6000, np.random.default_rng(9), date(2026, 10, 23))
    raw["bfo_date"] = "2026-03-20"
    raw["debtam_date"] = None
    rng = np.random.default_rng(9)
    event = rng.random(len(raw)) < np.where(raw.ebit < 0, 0.10, 0.01)
    raw["status"] = np.where(event, "INACTIVE", "ACTIVE")
    (tmp_path / "fns").mkdir()
    raw.to_csv(tmp_path / "fns" / "companies.csv", index=False, encoding="utf-8-sig")
    eg = tmp_path / "raw" / "egrul"
    eg.mkdir(parents=True)
    for inn in raw.inn[event]:
        (eg / f"{inn}.json").write_text(json.dumps({"inn": inn, "method": "Исключение юридического лица из ЕГРЮЛ",
                                                    "end_date_pdf": "01.08.2026"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["x", "--asof", "2026-10-23", "--data-dir", str(tmp_path)])
    build.main()
    meta = json.loads((tmp_path / "scoring" / "train_meta.json").read_text(encoding="utf-8"))
    assert meta["source"] == "real" and meta["weights"] in ("egrul", "manual")
    monkeypatch.setattr(sys, "argv", ["x", "--data-dir", str(tmp_path), "--report-dir", str(tmp_path / "rep")])
    tr.main()
    real_report = next((tmp_path / "rep").glob("scorecard_*.md")).read_text(encoding="utf-8")
    assert "## Проверка на реальной метке" in real_report
    monkeypatch.setattr(sys, "argv", ["x", "--synthetic", "3000", "--data-dir", str(tmp_path)])
    build.main()  # синтетика с теми же папками ФНС и ЕГРЮЛ рядом
    monkeypatch.setattr(sys, "argv", ["x", "--data-dir", str(tmp_path), "--report-dir", str(tmp_path / "syn")])
    tr.main()
    syn_report = next((tmp_path / "syn").glob("scorecard_*.md")).read_text(encoding="utf-8")
    assert "## Проверка на реальной метке" not in syn_report


def test_calibrated_weights_are_opt_in(tmp_path, monkeypatch):
    import numpy as np
    build = _load("build_scoring_sample")
    raw = synth.generate_real(500, np.random.default_rng(2), date(2026, 10, 23))
    raw["bfo_date"], raw["debtam_date"] = "2026-03-20", None
    (tmp_path / "fns").mkdir()
    raw.to_csv(tmp_path / "fns" / "companies.csv", index=False, encoding="utf-8-sig")
    cal = tmp_path / "cal.json"
    cal.write_text(json.dumps({"weights": {"loss": 3.0}, "sector": {}}), encoding="utf-8")
    monkeypatch.setattr(synth, "CALIBRATION_PATH", cal)
    monkeypatch.setattr(sys, "argv", ["x", "--asof", "2026-10-23", "--data-dir", str(tmp_path)])
    build.main()
    meta = json.loads((tmp_path / "scoring" / "train_meta.json").read_text(encoding="utf-8"))
    assert meta["weights"] == "manual"  # файл калибровки есть, но без ключа не применяется
    monkeypatch.setattr(sys, "argv", ["x", "--asof", "2026-10-23", "--calibrated-weights", "--data-dir", str(tmp_path)])
    build.main()
    assert json.loads((tmp_path / "scoring" / "train_meta.json").read_text(encoding="utf-8"))["weights"] == "egrul"
