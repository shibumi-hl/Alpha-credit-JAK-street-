"""
Реальная метка из ЕГРЮЛ и проверка на ней модели, обученной на синтетической метке дефолта.

Событие - банкротство или исключение налоговой, случившееся строго после подачи отчёта, на котором построены
признаки; контроль - действующие компании. Добровольная ликвидация, реорганизация, события до отчёта и
недействующие без выписки в выборку не входят. Компании делятся пополам по хэшу ИНН: на «калибровке» подбираются
веса скрытой логики (scoring/calibrate.py), на «проверке» считается качество - иначе оценка завышена.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from scoring.egrul import BANKRUPTCY, DISTRESS, STRUCK_OFF, event_date, kind

CALIBRATION, HOLDOUT = "calibration", "holdout"
# реальные факторы скоркарты без налогового долга (срез ФНС может быть позже события)
REAL_FACTORS = ["revenue", "age_months", "turnover_months", "debt_to_revenue", "debt_to_ebit", "equity_ratio",
                "interest_cover", "dscr", "revenue_growth"]


def half(inn: str) -> str:
    return HOLDOUT if hashlib.md5(str(inn).encode()).digest()[0] % 2 else CALIBRATION


def real_label(companies: pd.DataFrame, egrul_dir: Path) -> pd.DataFrame:
    """inn, kind (active | bankruptcy | struck_off), event 0/1, half - только пригодные для проверки строки."""
    rows = []
    for c in companies.itertuples():
        if c.status == "ACTIVE":
            rows.append((c.inn, "active", 0))
            continue
        path = Path(egrul_dir) / f"{c.inn}.json"
        if not path.exists():
            continue
        rec = json.loads(path.read_text(encoding="utf-8"))
        k, d = kind(rec), event_date(rec)
        if k in DISTRESS and d and d > str(c.bfo_date):
            rows.append((c.inn, k, 1))
    out = pd.DataFrame(rows, columns=["inn", "kind", "event"])
    out["half"] = out.inn.map(half)
    return out


def gini_ci(y, risk, n_boot: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """Gini (риск выше - событие вероятнее) и 95% бутстреп-интервал с ресемплингом событий и контроля отдельно."""
    y, risk = np.asarray(y, int), np.asarray(risk, float)
    g = 2 * roc_auc_score(y, risk) - 1
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    rng = np.random.default_rng(seed)
    yy = np.r_[np.ones(len(pos)), np.zeros(len(neg))]
    bs = [2 * roc_auc_score(yy, np.r_[risk[rng.choice(pos, len(pos))], risk[rng.choice(neg, len(neg))]]) - 1
          for _ in range(n_boot)]
    return float(g), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def validate(scored: pd.DataFrame, label: pd.DataFrame, real_factors=REAL_FACTORS, n_boot: int = 1000,
             halves=(HOLDOUT,)) -> dict:
    """Качество на реальной метке: Gini полного балла и балла только по реальным факторам (с интервалами) по видам
    событий, для всех и для заёмщиков; доля событий по классам риска. scored - inn, score, pd, risk_class, debt,
    points_<фактор>."""
    d = scored.merge(label[label["half"].isin(halves)], on="inn")
    pts = [f"points_{f}" for f in real_factors if f"points_{f}" in d]
    d["real_score"] = d[pts].sum(axis=1) if pts else np.nan
    rows = []
    for name, kinds in [("банкротство + исключение", DISTRESS), ("банкротство", (BANKRUPTCY,)),
                        ("исключение налоговой", (STRUCK_OFF,))]:
        for pop, m in [("все", np.ones(len(d), bool)), ("заёмщики", (d["debt"] > 0).to_numpy())]:
            g = d[m & ((d.kind == "active") | d.kind.isin(kinds)).to_numpy()]
            row = {"событие": name, "компании": pop, "events": int(g.event.sum()), "n": len(g)}
            if row["events"] >= 10 and row["events"] < len(g):
                full = gini_ci(g.event, -g.score, n_boot)
                row.update(gini_full=full[0], full_lo=full[1], full_hi=full[2])
                if pts:
                    real = gini_ci(g.event, -g.real_score, n_boot)
                    row.update(gini_real=real[0], real_lo=real[1], real_hi=real[2])
            rows.append(row)
    classes = (d.groupby("risk_class").agg(n=("event", "size"), events=("event", "sum"), rate=("event", "mean"),
                                           pd_model=("pd", "mean")).reset_index())
    return {"table": pd.DataFrame(rows), "classes": classes, "n": len(d), "events": int(d.event.sum()),
            "real_factors": [p[len("points_"):] for p in pts]}
