import importlib.util
import json
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fo = _load("load_fns_opendata")
lg = _load("load_girbo")


class FakeResp:
    def __init__(self, js, status=200):
        self._js, self.status_code = js, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._js


class FakeSession:
    """ГИР БО: поиск по ИНН и отчётность по id; ИНН из broken отвечают 500."""

    def __init__(self, broken=()):
        self.calls, self.broken = [], set(broken)

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if "search" in url:
            inn = params["query"]
            if inn in self.broken:
                return FakeResp(None, 500)
            if inn == "0000000000":
                return FakeResp({"content": []})
            return FakeResp({"content": [{"id": int(inn[:3]), "inn": inn, "ogrn": "1115809002055",
                                          "okved2": "47.11", "statusCode": "ACTIVE"}]})
        fin = {"current2110": 2000.0, "previous2110": 1000.0, "current2300": 100.0, "current2330": 10.0}
        bal = {"current1410": 100.0, "current1510": 300.0, "current1300": 700.0, "current1600": 1500.0}
        return FakeResp([{"period": "2025", "actualBfoDate": "2026-03-20",
                          "typeCorrections": [{"type": 12, "correction": {"balance": bal, "financialResult": fin}}]}])


def test_collect_caches_and_skips_already_cached(tmp_path):
    s = FakeSession()
    got = lg.collect(["1110000001", "0000000000"], tmp_path, s, rps=1000)
    assert got == {"fetched": 2, "cached": 0, "failed": 0}
    n = len(s.calls)
    assert n == 3  # 2 поиска + 1 отчётность (по пустому поиску отчётность не запрашивается)
    assert lg.collect(["1110000001", "0000000000"], tmp_path, s, rps=1000) == {"fetched": 0, "cached": 2, "failed": 0}
    assert len(s.calls) == n


def test_collect_failure_of_one_inn_does_not_stop_others(tmp_path):
    s = FakeSession(broken={"2220000002"})
    got = lg.collect(["2220000002", "3330000003"], tmp_path, s, rps=1000, retries=1)
    assert got == {"fetched": 1, "cached": 0, "failed": 1}
    assert not (tmp_path / "2220000002.json").exists()  # повторится при следующем запуске
    assert json.loads((tmp_path / "3330000003.json").read_text(encoding="utf-8"))["bfo"]


def test_build_companies_joins_universe_and_statements(tmp_path):
    lg.collect(["1110000001", "0000000000"], tmp_path, FakeSession(), rps=1000)
    uni = pd.DataFrame({"inn": ["1110000001", "0000000000"], "income": [2.1e6, 5e6], "expenses": [1.9e6, 4e6],
                        "tax_debt": [5000.0, 0.0], "tax_arrears": [5000.0, 0.0], "tax_penalties": [0.0, 0.0],
                        "tax_fines": [0.0, 0.0]})
    df = lg.build_companies(uni, tmp_path, asof=date(2026, 10, 20))
    assert list(df.inn) == ["1110000001"]  # без отчётности в ГИР БО - вне выборки
    r = df.iloc[0]
    assert r.revenue == 2_000_000.0 and r.debt == 400_000.0 and r.tax_debt == 5000.0
    assert r.okved_section == "G" and r.reg_year == 2011


def _zip(path, *xmls):
    with zipfile.ZipFile(path, "w") as z:
        for i, x in enumerate(xmls):
            z.writestr(f"f{i}.xml", x)


def _revexp(inn, income):
    return (f'<?xml version="1.0" encoding="UTF-8"?><Файл><Документ ДатаСост="31.12.2025"><СведНП ИННЮЛ="{inn}"/>'
            f'<СведДохРасх СумДоход="{income}" СумРасход="1"/></Документ></Файл>').encode("utf-8")


def test_universe_filters_by_income_and_attaches_tax_debt(tmp_path):
    _zip(tmp_path / "r.zip", _revexp("1000000001", 5e6), _revexp("1000000002", 1e3), _revexp("1000000003", 3e9))
    debt = ('<?xml version="1.0" encoding="UTF-8"?><Файл><Документ ДатаСост="01.09.2026"><СведНП ИННЮЛ="1000000001"/>'
            '<СведНедоим СумНедНалог="10" СумПени="1" СумШтраф="0" ОбщСумНедоим="11"/></Документ></Файл>').encode("utf-8")
    _zip(tmp_path / "d.zip", debt)
    uni = fo.build_universe(tmp_path / "r.zip", tmp_path / "d.zip", min_income=1e6, max_income=2e9)
    assert list(uni.inn) == ["1000000001"]
    assert uni.tax_debt.iloc[0] == 11.0


def test_sample_is_reproducible_and_capped():
    uni = pd.DataFrame({"inn": [f"{i:010d}" for i in range(100)], "income": range(100)})
    a, b = fo.sample(uni, 30, seed=7), fo.sample(uni, 30, seed=7)
    assert len(a) == 30 and list(a.inn) == list(b.inn)
    assert len(fo.sample(uni, 500, seed=7)) == 100


def test_download_skips_existing_file(tmp_path):
    p = tmp_path / "x.zip"
    p.write_bytes(b"zip")

    class NoNet:
        def get(self, *a, **k):
            raise AssertionError("не должен качать")

    assert fo.download(NoNet(), "https://example/x.zip", p) == p



def test_collect_refuses_inn_that_is_not_ten_digits(tmp_path):
    s = FakeSession()
    got = lg.collect(["..\..\evil", "12345"], tmp_path / "cache", s, rps=1000)
    assert got["failed"] == 2 and s.calls == []
    assert not list(tmp_path.rglob("*.json"))


class PageSession:
    def __init__(self, html):
        self.html = html

    def get(self, url, timeout=None):
        return type("R", (), {"text": self.html})()


def test_archive_link_must_be_https_on_fns_hosts():
    evil = '<a href="http://evil.example/x/data-20990101-structure-20180110.zip">'
    good = '<a href="https://file.nalog.ru/opendata/7707329152-revexp/data-20260925-structure-20180110.zip">'
    assert fo.latest_url(PageSession(evil + good), "revexp").startswith("https://file.nalog.ru/")
    import pytest
    with pytest.raises(RuntimeError):
        fo.latest_url(PageSession(evil), "revexp")
