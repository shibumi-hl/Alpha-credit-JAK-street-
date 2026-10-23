"""
Кривая бескупонной доходности ОФЗ (G-кривая) Московской биржи, история с 2022 года.
Публичные данные ISS, токен не нужен.

Запуск из папки проекта:
  python scripts/load_moex_gcurve.py
Повторный запуск докачивает новые даты.

Результат:
  data/raw/gcurve_yields.csv   - доходности по стандартным срокам (дата, срок в годах, доходность % год.)
  data/raw/gcurve_params.csv   - параметры кривой Мосбиржи на каждую дату
"""
import time
from datetime import date, timedelta
from pathlib import Path

import requests
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
URL = "https://iss.moex.com/iss/engines/stock/zcyc.json"
ENC = "utf-8-sig"


def block(js, name):
    b = js.get(name) or {}
    cols, data = b.get("columns"), b.get("data")
    return pd.DataFrame(data, columns=cols) if cols else pd.DataFrame()


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    fy, fp = RAW / "gcurve_yields.csv", RAW / "gcurve_params.csv"
    old_y = pd.read_csv(fy) if fy.exists() else pd.DataFrame()
    old_p = pd.read_csv(fp) if fp.exists() else pd.DataFrame()
    done = set(old_y["tradedate"].astype(str)) if len(old_y) else set()

    days, d = [], date(2022, 1, 3)
    while d <= date.today():
        if d.weekday() < 5 and d.isoformat() not in done:
            days.append(d)
        d += timedelta(days=1)
    print(f"Дат к загрузке: {len(days)}")

    ys, ps, s = [], [], requests.Session()
    failed = 0
    for i, d in enumerate(days, 1):
        try:
            r = s.get(URL, params={"date": d.isoformat(), "iss.meta": "off"}, timeout=30)
            js = r.json()
        except Exception as e:
            print(f"  {d}: ошибка {e}")
            failed += 1
            time.sleep(2)
            continue
        y, p = block(js, "yearyields"), block(js, "params")
        if i == 1 and y.empty:
            print("  Неожиданный формат ответа ISS:", str(js)[:300])
        if not y.empty:
            ys.append(y)
        if not p.empty:
            ps.append(p)
        if i % 100 == 0 or i == len(days):
            print(f"  {i}/{len(days)}")
        time.sleep(0.1)

    if ys:
        y = pd.concat([old_y] + ys, ignore_index=True)
        y["tradedate"] = y["tradedate"].astype(str)
        y = y.drop_duplicates(subset=["tradedate", "period"]).sort_values(["tradedate", "period"])
        y.to_csv(fy, index=False, encoding=ENC)
        print(f"Доходности: {y.tradedate.nunique()} дат -> {fy.relative_to(ROOT)}")
    if ps:
        p = pd.concat([old_p] + ps, ignore_index=True)
        p["tradedate"] = p["tradedate"].astype(str)
        p = p.drop_duplicates(subset=["tradedate"]).sort_values("tradedate")
        p.to_csv(fp, index=False, encoding=ENC)
        print(f"Параметры: {len(p)} дат -> {fp.relative_to(ROOT)}")


    if days and failed == len(days):  # ISS недоступен: пусть конвейер увидит сбой, а не старую кривую
        raise SystemExit(f"Ни одного ответа ISS из {len(days)} запросов — G-кривая не обновлена")


if __name__ == "__main__":
    main()
