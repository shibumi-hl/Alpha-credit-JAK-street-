"""
Скоркарта OptBinning: монотонный биннинг факторов, отбор по IV, логистическая регрессия на WoE,
шкала 600 баллов при odds 50:1 (good:bad), PDO 20. Больше баллов - ниже риск.

PD - логистическое отображение балла, откалиброванное на отложенной выборке; класс риска 1…7 по PD.
Баллы по фактору линейны по его WoE, поэтому раскладываются точно: сумма баллов факторов = балл.
"""
import pickle
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from optbinning import BinningProcess, Scorecard
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, train_test_split

from scoring.synth import CATEGORICAL, FEATURES

# Направление риска по смыслу: ascending - доля дефолтов растёт с ростом фактора
ASCENDING = {"debt_to_revenue", "debt_to_ebit", "tax_debt_to_revenue", "revenue_cv",
             "bki_max_dpd_12m", "bki_overdue_cnt_12m", "bki_current_dpd", "amount_to_revenue"}
PDO, ODDS, BASE = 20, 50, 600
MIN_FACTORS, MAX_FACTORS, MIN_IV = 8, 12, 0.02
# Берутся в модель при IV ≥ MIN_IV даже вне топа: на них держатся причина «короткая история оборотов»
# и what-if по залогу
REQUIRED = ("turnover_months", "product")
# Верхние границы PD классов 1…6; класс 7 - всё выше
CLASS_PD = [0.005, 0.01, 0.02, 0.04, 0.08, 0.15]
_SPECIAL = {"Special", "Missing"}


def risk_class(pd_: np.ndarray) -> np.ndarray:
    return np.searchsorted(CLASS_PD, np.asarray(pd_, float), side="right") + 1


@dataclass
class ScoreModel:
    scorecard: Scorecard
    factors: list
    lines: dict  # фактор → (a, b): баллы = a + b * WoE
    calib: tuple  # PD = 1 / (1 + exp(-(c0 + c1 * score)))
    max_points: dict = field(default_factory=dict)
    iv: pd.DataFrame = None  # IV всех кандидатов, selected - вошёл в модель

    def points(self, X: pd.DataFrame) -> pd.DataFrame:
        woe = self.scorecard.binning_process_.transform(X[self.scorecard.binning_process_.variable_names], metric="woe")
        return pd.DataFrame({f"points_{f}": self.lines[f][0] + self.lines[f][1] * woe[f].to_numpy() for f in self.factors},
                            index=X.index)

    def score(self, df: pd.DataFrame) -> pd.DataFrame:
        pts = self.points(df)
        score = pts.sum(axis=1)
        p = 1 / (1 + np.exp(-(self.calib[0] + self.calib[1] * score)))
        out = pd.DataFrame({"score": score, "pd": p, "risk_class": risk_class(p)}, index=df.index)
        return pd.concat([out, pts], axis=1)

    def table(self) -> pd.DataFrame:
        t = self.scorecard.table("detailed")
        return t[t.Variable.isin(self.factors)][["Variable", "Bin", "Count", "Event rate", "WoE", "Points"]]

    def save(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: Path) -> "ScoreModel":
        with open(path, "rb") as f:
            return pickle.load(f)


def _ks(y, s) -> float:
    o = np.argsort(s)
    y = np.asarray(y)[o]
    bad, good = np.cumsum(y) / max(y.sum(), 1), np.cumsum(1 - y) / max((1 - y).sum(), 1)
    return float(np.max(np.abs(bad - good)))


def _binning(features):
    numeric = [f for f in features if f not in CATEGORICAL]
    fit = {f: {"monotonic_trend": "ascending" if f in ASCENDING else "descending"} for f in numeric}
    return BinningProcess(list(features), categorical_variables=[f for f in features if f in CATEGORICAL],
                          binning_fit_params=fit)


def select_factors(tr: pd.DataFrame, target: str, features) -> tuple[list, pd.DataFrame]:
    """Обязательные факторы с IV ≥ MIN_IV + лучшие по IV, всего не больше MAX_FACTORS."""
    bp = _binning(features).fit(tr[list(features)], tr[target])
    iv = bp.summary()[["name", "iv", "n_bins"]].astype({"iv": float}).sort_values("iv", ascending=False)
    ok = iv[iv.iv >= MIN_IV].name.astype(str).tolist()
    req = [f for f in REQUIRED if f in ok]
    chosen = req + [f for f in ok if f not in req][:MAX_FACTORS - len(req)]
    iv["selected"] = iv.name.isin(chosen)
    return [f for f in features if f in chosen], iv.reset_index(drop=True)


def _fit(tr: pd.DataFrame, target: str, features, strict: bool = True) -> tuple[Scorecard, list, pd.DataFrame]:
    """Отбор факторов по IV, биннинг и регрессия на tr. strict - ValueError, если факторов меньше MIN_FACTORS."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        factors, iv = select_factors(tr, target, features)
        if strict and len(factors) < MIN_FACTORS:
            raise ValueError(f"после отбора по IV осталось {len(factors)} факторов, нужно не меньше {MIN_FACTORS}: {factors}")
        if not factors:
            return None, factors, iv
        sc = Scorecard(binning_process=_binning(factors), estimator=LogisticRegression(max_iter=2000),
                       scaling_method="pdo_odds", scaling_method_params={"pdo": PDO, "odds": ODDS, "scorecard_points": BASE})
        sc.fit(tr[factors], tr[target])
    return sc, factors, iv


def cross_validate(df: pd.DataFrame, target: str = "default_12m", features=FEATURES, k: int = 5,
                   seed: int = 7) -> pd.DataFrame:
    """Gini по k стратифицированным фолдам. Отбор факторов, биннинг и регрессия - заново на каждом обучающем фолде,
    так что отложенный фолд не участвует ни в чём; по строке на фолд. Фолд, где по IV прошло меньше MIN_FACTORS
    факторов, не оценивается (Gini NaN): train() такую модель не принял бы. k < 2 - без кросс-валидации (пусто);
    дефолтов или компаний без дефолта меньше k - ValueError."""
    cols = ["fold", "n_test", "dr_test", "factors", "gini_train", "gini_test"]
    if k < 2:
        return pd.DataFrame(columns=cols)
    counts = df[target].value_counts()
    if len(counts) < 2 or counts.min() < k:
        raise ValueError(f"для {k} фолдов нужно не меньше {k} дефолтов и {k} компаний без дефолта, а их "
                         f"{int(counts.get(1, 0))} и {int(counts.get(0, 0))}")
    rows = []
    for i, (a, b) in enumerate(StratifiedKFold(k, shuffle=True, random_state=seed).split(df, df[target]), 1):
        tr, te = df.iloc[a], df.iloc[b]
        sc, factors, _ = _fit(tr, target, features, strict=False)
        g = (lambda d: 2 * roc_auc_score(d[target], sc.predict_proba(d[factors])[:, 1]) - 1) \
            if sc is not None and len(factors) >= MIN_FACTORS else (lambda d: np.nan)
        rows.append({"fold": i, "n_test": len(te), "dr_test": float(te[target].mean()), "factors": len(factors),
                     "gini_train": g(tr), "gini_test": g(te)})
    return pd.DataFrame(rows, columns=cols)


def train(df: pd.DataFrame, target: str = "default_12m", features=FEATURES, seed: int = 7, test_size: float = 0.3,
          cv: int = 5):
    """Обучение на 70% и отчёт на 30% (стратифицировано), плюс Gini по cv фолдам всей выборки (cross_validate) -
    без удачи одного разбиения; cv < 2 - без неё. ValueError, если факторов с IV ≥ 0.02 меньше 8."""
    tr, te = train_test_split(df, test_size=test_size, stratify=df[target], random_state=seed)
    sc, factors, iv = _fit(tr, target, features)
    t = sc.table("detailed")
    lines, max_points = {}, {}
    for f in factors:
        r = t[t.Variable == f]
        reg = r[~r.Bin.astype(str).isin(_SPECIAL)]
        b, a = np.polyfit(reg.WoE.astype(float), reg.Points.astype(float), 1)
        lines[f] = (float(a), float(b))
        # при скоринге пропуск и спецзначение получают WoE = 0
        max_points[f] = float(max(reg.Points.max(), a))
    model = ScoreModel(sc, factors, lines, (0.0, 0.0), max_points, iv)
    # калибровка PD на отложенной выборке: логит(PD) линеен по баллу
    s_te = model.points(te).sum(axis=1).to_numpy()
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(s_te.reshape(-1, 1), te[target])
    model.calib = (float(lr.intercept_[0]), float(lr.coef_[0, 0]))
    return model, {**report(model, tr, te, target), "cv": cross_validate(df, target, features, cv, seed)}


def report(model: ScoreModel, tr: pd.DataFrame, te: pd.DataFrame, target: str = "default_12m") -> dict:
    s_tr, s_te = model.score(tr), model.score(te)
    auc_tr, auc_te = roc_auc_score(tr[target], -s_tr.score), roc_auc_score(te[target], -s_te.score)
    by = (pd.DataFrame({"risk_class": s_te.risk_class, "pd": s_te.pd, "y": te[target].to_numpy(), "score": s_te.score})
          .groupby("risk_class").agg(count=("y", "size"), default_rate=("y", "mean"), pd_mean=("pd", "mean"),
                                     score_min=("score", "min"), score_max=("score", "max")).reset_index())
    return {"n_train": len(tr), "n_test": len(te), "dr_train": float(tr[target].mean()), "dr_test": float(te[target].mean()),
            "auc_train": auc_tr, "auc_test": auc_te, "gini_train": 2 * auc_tr - 1, "gini_test": 2 * auc_te - 1,
            "ks_test": _ks(te[target], -s_te.score), "pd_mean_test": float(s_te.pd.mean()),
            "factors": model.factors, "iv": model.iv, "classes": by, "table": model.table()}
