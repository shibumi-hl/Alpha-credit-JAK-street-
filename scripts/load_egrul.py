"""
Способ прекращения и состояние из ЕГРЮЛ (egrul.nalog.ru) для недействующих компаний выборки - реальная метка.

Массовой выгрузки ЕГРЮЛ нет: только поиск по ИНН и выписка. На компанию 5 запросов: поиск, результат, запрос
выписки, статус, скачивание. 1 запрос в 3 с; капча или отказ сервиса - остановка (повторный запуск продолжит).
Хранится только способ прекращения, состояние, даты и роль руководителя без ФИО; выписка разбирается в памяти.

Запуск из папки проекта (после load_girbo.py):
  py scripts/load_egrul.py              # все недействующие из data/fns/companies.csv (~520 компаний, ~2,5 ч)

Результат: data/raw/egrul/<ИНН>.json
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring.egrul import PdfError, parse_extract, pdf_text, role  # noqa: E402

BASE = "https://egrul.nalog.ru"
PAUSE = 3.0
MAX_FAILURES = 5  # подряд - сервис, похоже, отказывает: останавливаемся
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


class Stop(Exception):
    """Сервис просит капчу или отказывает - дальше не идём."""


def _get(s, path, method="GET", data=None):
    time.sleep(PAUSE)
    r = s.request(method, BASE + path, data=data, timeout=60)
    if r.status_code != 200:
        raise Stop(f"HTTP {r.status_code} на {path}")
    return r


def _json(r) -> dict:
    """Ответ сервиса как словарь; HTML (капча, страница ошибки) или неожиданный JSON - остановка."""
    try:
        js = r.json()
    except ValueError:
        js = None
    if not isinstance(js, dict):
        raise Stop("ответ не JSON-объект - возможно, капча или страница ошибки")
    return js


def one(s, inn: str) -> dict:
    js = _json(_get(s, "/", "POST", {"query": inn, "region": "", "PreventChromeAutocomplete": ""}))
    if js.get("captchaRequired"):
        raise Stop("ЕГРЮЛ просит капчу")
    rows = _json(_get(s, f"/search-result/{js['t']}")).get("rows") or []
    row = next((r for r in rows if r.get("i") == inn), None)
    if row is None:
        return {"inn": inn, "found": False}
    rec = {"inn": inn, "found": True, "role": role(row.get("g")), "reg_date": row.get("r"), "end_date": row.get("e")}
    _get(s, f"/vyp-request/{row['t']}")
    for _ in range(10):
        if _json(_get(s, f"/vyp-status/{row['t']}")).get("status") == "ready":
            break
    else:
        raise Stop("выписка не готова")
    r = _get(s, f"/vyp-download/{row['t']}")
    if "pdf" not in r.headers.get("Content-Type", ""):
        raise Stop(f"вместо выписки пришло {r.headers.get('Content-Type')}")
    rec.update(parse_extract(pdf_text(r.content)))
    return rec


def inactive_inns(companies: pd.DataFrame) -> list:
    return companies.loc[companies.status != "ACTIVE", "inn"].tolist()


def collect(inns, out: Path, s) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    got = {"done": 0, "cached": 0, "failed": 0, "stopped": None}
    streak = 0
    for inn in inns:
        if not re.fullmatch(r"\d{10}", str(inn)):  # ИНН юрлица - 10 цифр; иначе это не ЮЛ (и не путь к файлу)
            got["failed"] += 1
            print(f"  пропуск: не ИНН юрлица {inn!r}", flush=True)
            continue
        path = out / f"{inn}.json"
        if path.exists():
            got["cached"] += 1
            continue
        try:
            rec = one(s, inn)
        except Stop as e:
            got["stopped"] = f"{inn}: {e}"
            break
        except (requests.RequestException, PdfError, ValueError, KeyError) as e:
            got["failed"] += 1
            streak += 1
            print(f"  {inn}: {e}", flush=True)
            if streak >= MAX_FAILURES:
                got["stopped"] = f"{MAX_FAILURES} сбоев подряд, последний на {inn}: {e}"
                break
            continue
        streak = 0
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        got["done"] += 1
        if got["done"] % 20 == 0:
            print(f"  собрано {got['done']}", flush=True)
    return got


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    a = ap.parse_args()
    companies = pd.read_csv(a.data_dir / "fns" / "companies.csv", dtype={"inn": str}, encoding="utf-8-sig")
    inns = inactive_inns(companies)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    print(f"ЕГРЮЛ: {len(inns)} недействующих компаний, 1 запрос в {PAUSE:.0f} с", flush=True)
    got = collect(inns, a.data_dir / "raw" / "egrul", s)
    print(got)
    if got["stopped"]:
        sys.exit(f"остановлено: {got['stopped']} - повторите позже, собранное сохранено")


if __name__ == "__main__":
    main()
