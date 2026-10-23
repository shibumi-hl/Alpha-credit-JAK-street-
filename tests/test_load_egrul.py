import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

spec = importlib.util.spec_from_file_location("load_egrul", Path(__file__).resolve().parents[1] / "scripts" / "load_egrul.py")
le = importlib.util.module_from_spec(spec)
spec.loader.exec_module(le)

TEXT = ("Сведения о прекращении юридического лица 15 Способ прекращения Исключение юридического лица из ЕГРЮЛ "
        "в связи с наличием оснований, предусмотренных статьей 21.3 16 Дата прекращения 14.10.2026 17 "
        "Сведения о лице 18 Фамилия Сидоров")


class Resp:
    def __init__(self, js=None, content=b"", ctype="application/json", status=200):
        self._js, self.content, self.status_code = js, content, status
        self.headers = {"Content-Type": ctype}

    def json(self):
        return self._js


class FakeEgrul:
    """Поиск → результат → запрос выписки → статус → PDF; captcha=True - сервис просит капчу."""

    def __init__(self, captcha=False):
        self.calls, self.captcha = [], captcha

    def request(self, method, url, data=None, timeout=None):
        self.calls.append(url)
        if url.endswith("egrul.nalog.ru/"):
            return Resp({"t": "T1", "captchaRequired": self.captcha})
        if "/search-result/" in url:
            return Resp({"rows": [{"i": "1234567890", "g": "ДИРЕКТОР: Сидоров Сидор", "e": "14.10.2026",
                                   "r": "01.02.2019", "t": "R1"}]})
        if "/vyp-status/" in url:
            return Resp({"status": "ready"})
        if "/vyp-download/" in url:
            return Resp(content=b"%PDF-fake", ctype="application/pdf")
        return Resp({})


@pytest.fixture(autouse=True)
def no_sleep_and_fake_pdf(monkeypatch):
    monkeypatch.setattr(le, "PAUSE", 0)
    monkeypatch.setattr(le, "pdf_text", lambda b: TEXT)


def test_one_company_record_has_no_names_and_no_pdf(tmp_path):
    got = le.collect(["1234567890"], tmp_path, FakeEgrul())
    assert got["done"] == 1
    rec = json.loads((tmp_path / "1234567890.json").read_text(encoding="utf-8"))
    assert rec["role"] == "ДИРЕКТОР" and rec["end_date"] == "14.10.2026" and "21.3" in rec["method"]
    assert "Сидоров" not in json.dumps(rec, ensure_ascii=False)
    assert [p.name for p in tmp_path.iterdir()] == ["1234567890.json"]


def test_cached_inn_is_not_requested_again(tmp_path):
    s = FakeEgrul()
    le.collect(["1234567890"], tmp_path, s)
    n = len(s.calls)
    assert le.collect(["1234567890"], tmp_path, s)["cached"] == 1 and len(s.calls) == n


def test_captcha_stops_the_run_without_writing(tmp_path):
    got = le.collect(["1234567890", "1234567891"], tmp_path, FakeEgrul(captcha=True))
    assert got["stopped"] and got["done"] == 0 and not list(tmp_path.glob("*.json"))


def test_inactive_inns_from_companies(tmp_path):
    c = pd.DataFrame({"inn": ["1111111111", "2222222222", "3333333333"],
                      "status": ["ACTIVE", "INACTIVE", "LIQUIDATION_STAGE"]})
    assert le.inactive_inns(c) == ["2222222222", "3333333333"]


class HtmlInsteadOfJson(FakeEgrul):
    def request(self, method, url, data=None, timeout=None):
        self.calls.append(url)
        return Resp(None, content=b"<html>captcha</html>", ctype="text/html")


class BrokenPdf(FakeEgrul):
    pass


def test_html_page_instead_of_json_stops_the_run(tmp_path):
    s = HtmlInsteadOfJson()
    got = le.collect([f"12345678{i:02d}" for i in range(10)], tmp_path, s)
    assert got["stopped"] and len(s.calls) == 1


def test_broken_pdf_is_a_failure_not_a_crash(tmp_path, monkeypatch):
    def bad(_):
        raise le.PdfError("broken")
    monkeypatch.setattr(le, "pdf_text", bad)
    got = le.collect(["1234567890"], tmp_path, FakeEgrul())
    assert got["failed"] == 1 and got["stopped"] is None and not list(tmp_path.glob("*.json"))


def test_consecutive_failures_stop_and_bad_inn_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(le, "pdf_text", lambda b: (_ for _ in ()).throw(le.PdfError("broken")))
    got = le.collect(["..\\evil", *["1234567890"] * 9], tmp_path, FakeEgrul())  # сбой не кэшируется - повтор доходит до PDF
    assert got["failed"] == le.MAX_FAILURES + 1 and got["stopped"]  # плохой ИНН + 5 сбоев подряд
    assert not (tmp_path.parent / "evil.json").exists()
