"""
Бухотчётность компаний выборки из ГИР БО (bo.nalog.gov.ru, публичный ресурс ФНС, токен не нужен).

На ИНН два запроса: поиск (id, ОКВЭД, статус, ОГРН) и все годовые отчёты (баланс, ОФР, ДДС).
Ответы кэшируются в data/raw/girbo/<ИНН>.json; повторный запуск докачивает только недостающее,
ошибка по одному ИНН не останавливает прогон (он повторится в следующий раз).

Запуск из папки проекта (после load_fns_opendata.py):
  py scripts/load_girbo.py                 # вся выборка data/fns/sample.csv, ~2 запроса/с (часы)
  py scripts/load_girbo.py --limit 500     # первые 500 ИНН
  py scripts/load_girbo.py --build-only    # только собрать companies.csv из кэша
  py scripts/load_girbo.py --build-only --asof 2025-06-01   # выборка на прошлую дату (без заглядывания вперёд)

Результат: data/fns/companies.csv - выборка + отчётность за последний год, поданный не позже D-1.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring.fns import parse_girbo  # noqa: E402

BASE = "https://bo.nalog.gov.ru"
ENC = "utf-8-sig"


def fetch_json(s, url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = s.get(url, params=params, timeout=30)
            if r.status_code == 429:  # просят притормозить
                time.sleep(30 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise requests.HTTPError("429 после всех повторов")


def _write_json(path: Path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def collect(inns, cache_dir: Path, s, rps=2.0, retries=3, progress=0) -> dict:
    cache_dir.mkdir(parents=True, exist_ok=True)
    got = {"fetched": 0, "cached": 0, "failed": 0}
    pause = 1.0 / rps
    for i, inn in enumerate(inns, 1):
        if not re.fullmatch(r"\d{10}", str(inn)):  # ИНН юрлица - 10 цифр; иначе это не ЮЛ или мусор
            got["failed"] += 1
            print(f"  пропуск: не ИНН юрлица {inn!r}")
            continue
        path = cache_dir / f"{inn}.json"
        if path.exists():
            got["cached"] += 1
            continue
        try:
            search = fetch_json(s, f"{BASE}/advanced-search/organizations/search", {"query": inn, "page": 0}, retries)
            time.sleep(pause)
            content = (search or {}).get("content") or []
            bfo = fetch_json(s, f"{BASE}/nbo/organizations/{content[0]['id']}/bfo/", retries=retries) if content else []
            time.sleep(pause if content else 0)
            _write_json(path, {"search": search, "bfo": bfo})
            got["fetched"] += 1
        except (requests.RequestException, ValueError, KeyError) as e:
            got["failed"] += 1
            print(f"  {inn}: {e}")
        if progress and i % progress == 0:
            print(f"  {i}/{len(inns)} {got}", flush=True)
    return got


def build_companies(universe: pd.DataFrame, cache_dir: Path, asof: date) -> pd.DataFrame:
    rows = []
    for inn in universe.inn:
        path = cache_dir / f"{inn}.json"
        if not path.exists():
            continue
        js = json.loads(path.read_text(encoding="utf-8"))
        row = parse_girbo(js["search"] or {}, js["bfo"] or [], asof)
        if row and row["inn"] == inn and row["revenue"] > 0:
            rows.append(row)
    fin = pd.DataFrame(rows)
    if fin.empty:
        return fin
    return universe.merge(fin, on="inn", how="inner").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--rps", type=float, default=2.0)
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--asof", type=date.fromisoformat, default=date.today(),
                    help="дата оценки D: берётся отчётность, поданная до D (по умолчанию сегодня)")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    a = ap.parse_args()
    uni = pd.read_csv(a.data_dir / "fns" / "sample.csv", dtype={"inn": str}, encoding=ENC)
    if a.limit:
        uni = uni.head(a.limit)
    cache = a.data_dir / "raw" / "girbo"
    if not a.build_only:
        s = requests.Session()
        s.headers.update({"User-Agent": "alpha-credit-scoring/0.1 (research)", "Referer": BASE + "/"})
        print(f"ГИР БО: {len(uni):,} ИНН, {a.rps} запр/с")
        print(collect(list(uni.inn), cache, s, a.rps, progress=200))
    df = build_companies(uni, cache, asof=a.asof)
    out = a.data_dir / "fns" / "companies.csv"
    df.to_csv(out, index=False, encoding=ENC)
    print(f"компаний с отчётностью: {len(df):,} → {out}")


if __name__ == "__main__":
    main()
