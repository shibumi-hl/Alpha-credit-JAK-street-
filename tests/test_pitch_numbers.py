import importlib.util
from pathlib import Path

import pandas as pd
import pytest

spec = importlib.util.spec_from_file_location("pitch_numbers", Path(__file__).resolve().parents[1] / "scripts" / "pitch_numbers.py")
pitch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pitch)
figures = pitch.figures


def test_outcomes_routes_and_money_from_the_assessed_sample():
    df = pd.DataFrame({
        "outcome": ["APPROVE", "APPROVE", "COUNTER", "COUNTER", "COUNTER", "REQUEST_INFO", "REJECT", "REJECT"],
        "product": ["express", "secured", "express", "credit_line", "overdraft", "express", "express", "card"],
        "offered_product": ["express", "secured", "express", "card", "card", None, None, None],
        "offered_amount": [1e9, 2e9, 3e9, 0.5e9, 0.5e9, 0.0, 0.0, 0.0],
    })
    f = figures(df, margin=0.02)
    assert f["companies"] == 8
    assert f["outcomes"]["COUNTER"] == (3, pytest.approx(3 / 8))
    assert (f["counter_same"], f["counter_route"]) == (1, 2)  # маршрут - контрпредложение другим продуктом
    assert f["approved_bn"] == pytest.approx(3.0) and f["counter_bn"] == pytest.approx(4.0)
    assert f["offered_bn"] == pytest.approx(7.0) and f["counter_share"] == pytest.approx(4 / 7)
    assert f["margin_on_counter_bn"] == pytest.approx(0.02 * 4.0)  # маржа в год с объёма, который иначе был бы отказом
