"""
Вселенная юрлиц для скоринга из открытых данных ФНС (nalog.gov.ru/opendata, токен не нужен).

revexp - доходы и расходы по бухотчётности (на 31.12 прошлого года), debtam - недоимка, пени и штрафы
по налогам. Берутся юрлица с доходом в [--min-income, --max-income] (по умолчанию 1 млн - 2 млрд руб.,
верхняя граница МСП), к ним присоединяется налоговый долг, из них - случайная выборка --sample.

Запуск из папки проекта:
  py scripts/load_fns_opendata.py                 # скачать (если ещё нет) и собрать выборку 20 000
  py scripts/load_fns_opendata.py --sample 5000

Результат: data/raw/fns/<набор>/*.zip, data/fns/universe.csv, data/fns/sample.csv.
"""
import argparse
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring.fns import parse_debtam, parse_revexp  # noqa: E402

PAGES = {"revexp": "https://www.nalog.gov.ru/opendata/7707329152-revexp/",
         "debtam": "https://www.nalog.gov.ru/opendata/7707329152-debtam/"}
ENC = "utf-8-sig"
FNS_HOSTS = {"www.nalog.gov.ru", "nalog.gov.ru", "file.nalog.ru"}  # архивы - только с сайтов ФНС по https
TAX =["tax_arrears", "tax_penalties", "tax_fines", "tax_debt"]


def latest_url(s, dataset: str) -> str:
    html = s.get(PAGES[dataset], timeout=60).text
    links = [u for u in re.findall(r'(https?://[^"\']+/data-\d{8}-structure-\d{8}\.zip)', html)
             if urlparse(u).scheme == "https" and urlparse(u).hostname in FNS_HOSTS]
    if not links:
        raise RuntimeError(f"{dataset}: на странице нет https-ссылки на архив на сайте ФНС")
    return max(links, key=lambda u: re.search(r"data-(\d{8})", u).group(1))


def download(s, url: str, path: Path) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with s.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    os.replace(tmp, path)
    return path


def _parse_zip(path: Path, parser) -> pd.DataFrame:
    rows = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.lower().endswith(".xml"):
                rows.extend(parser(z.read(name)))
    return pd.DataFrame(rows)


def build_universe(revexp_zip: Path, debtam_zip: Path, min_income=1e6, max_income=2e9) -> pd.DataFrame:
    rev = _parse_zip(revexp_zip, parse_revexp).drop_duplicates("inn", keep="last")
    rev = rev[(rev.income >= min_income) & (rev.income <= max_income)]
    debt = _parse_zip(debtam_zip, parse_debtam)
    if len(debt):
        debt = debt.groupby("inn", as_index=False).agg({**{c: "sum" for c in TAX}, "debtam_date": "max"})
    else:
        debt = pd.DataFrame(columns=["inn", *TAX, "debtam_date"])
    out = rev.merge(debt, on="inn", how="left")
    out[TAX] = out[TAX].fillna(0.0).astype(float)
    return out.reset_index(drop=True)


def sample(universe: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    return universe.sample(n=min(n, len(universe)), random_state=seed).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--min-income", type=float, default=1e6)
    ap.add_argument("--max-income", type=float, default=2e9)
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    a = ap.parse_args()
    raw = a.data_dir / "raw" / "fns"
    s = requests.Session()
    s.headers["User-Agent"] = "alpha-credit-scoring/0.1 (research)"
    paths = {}
    for ds in PAGES:
        local = sorted((raw / ds).glob("data-*.zip"))
        paths[ds] = local[-1] if local else download(s, (u := latest_url(s, ds)), raw / ds / u.rsplit("/", 1)[1])
        print(f"{ds}: {paths[ds].name}")
    uni = build_universe(paths["revexp"], paths["debtam"], a.min_income, a.max_income)
    out = a.data_dir / "fns"
    out.mkdir(parents=True, exist_ok=True)
    uni.to_csv(out / "universe.csv", index=False, encoding=ENC)
    smp = sample(uni, a.sample, a.seed)
    smp.to_csv(out / "sample.csv", index=False, encoding=ENC)
    print(f"юрлиц с доходом {a.min_income:,.0f}–{a.max_income:,.0f}: {len(uni):,}; "
          f"с налоговым долгом: {(uni.tax_debt > 0).mean():.1%}; выборка: {len(smp):,} → {out / 'sample.csv'}")


if __name__ == "__main__":
    main()
