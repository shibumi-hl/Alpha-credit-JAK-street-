"""
Модель вероятности одобрения: логистическая регрессия на категориях заявки, PD скоркарты и денежном потоке.

Учится на решениях кредитной логики (это модель политики, а не риска: риск даёт PD-скоркарта, здесь PD - вход).
Одобрение = APPROVE или COUNTER по запрошенному продукту на сумму не меньше половины запрошенной;
маршрут на другой продукт и отказ = 0; REQUEST_INFO и стоп-факторы в обучение не входят, при стоп-факторе
вероятность 0.

Признаки: категории заявки (у каждого признака одна референсная категория, без dummy trap) и три непрерывных -
логит PD; запас денежного потока = (EBIT / min DSCR − обслуживание долга) / годовой платёж по запросу (как в
DSCR-лимите кредитной логики); ln(среднемесячный оборот / платёж), как в модели Костяна. Платёж - аннуитет по
опорной ставке REF_RATE: шанс считается до расчёта цены.

Знаки ограничены смыслом (логит с ограничениями на коэффициенты, L-BFGS-B): залог, РКО, обороты в банке, маркетплейс,
гарантия, денежный поток и оборот к платежу не снижают шанс; PD, доля суммы в выручке, просрочки и молодость бизнеса
не повышают. Упорядоченные категории кодируются ступенями (категория и все дальше от референса), поэтому эффект
монотонен. Категория с числом наблюдений меньше MIN_COUNT не оценивается: эффект как у соседней категории ближе к
референсу (у продукта - как у референса).

Soft-режим (как у модели Костяна): неизвестный признак - нет БКИ, отчётности или PD - получает средний вклад по
обучающей выборке и попадает в imputed, так что шанс можно показать до полной проверки.

Шкала: балл = 600 + (20 / ln2) · logit(p); +20 баллов - вдвое выше шансы. Баллы категории = (20 / ln2) · β
относительно референса, непрерывного признака - (20 / ln2) · β · (x − среднее по обучению).
"""
import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import train_test_split

FACTOR = 20 / math.log(2)
BASE = 600
MIN_COUNT = 30
REF_RATE = 0.225  # опорная ставка платежа, годовых
MIN_DSCR = 1.25  # как в config/credit_policy.json; Engine передаёт значение из политики
L2 = 1.0  # слабый ridge для устойчивости; на тысячах решений почти не влияет
EPS = 1e-9
# признак → (категории по порядку от референса, референс)
CATEGORIES = {
    "product": (["secured", "express", "overdraft", "credit_line", "seller_credit", "card"], "secured"),
    "business_age": (["120+", "60-120", "36-60", "24-36", "12-24", "<12"], "120+"),
    "rko": (["нет", "да"], "нет"),
    "bank_turnover": (["<40%", "40-100%", ">100%"], "<40%"),
    "amount_share": (["<10%", "10-30%", ">30%"], "<10%"),
    "marketplace": (["нет", "да"], "нет"),
    "guarantee": (["нет", "да"], "нет"),
    "bki_overdue": (["нет", "≤30 дн", ">30 дн"], "нет"),
}
UNORDERED = {"product"}
# +1 - дальше от референса шанс не ниже, −1 - не выше; у продукта - любой продукт не выше залогового
SIGNS = {"product": -1, "business_age": -1, "rko": 1, "bank_turnover": 1, "amount_share": -1, "marketplace": 1,
         "guarantee": 1, "bki_overdue": -1}
CONTINUOUS = {"logit_pd": -1, "cash_cover": 1, "ln_turnover_to_payment": 1}
UNITS = {"logit_pd": "логит PD", "cash_cover": "ln(запас / платёж)", "ln_turnover_to_payment": "ln(оборот / платёж)"}
LABELS = {"product": "Продукт", "business_age": "Возраст бизнеса, мес.", "rko": "РКО в банке",
          "bank_turnover": "Обороты в банке / лимит", "amount_share": "Сумма / годовая выручка",
          "marketplace": "Селлер маркетплейса с данными", "guarantee": "Гарантия Корпорации МСП",
          "bki_overdue": "Просрочки в БКИ за 12 мес.", "logit_pd": "PD скоркарты",
          "cash_cover": "Запас денежного потока к платежу", "ln_turnover_to_payment": "Среднемесячный оборот к платежу"}
NO_DATA = "нет данных"


def _finite(df: pd.DataFrame, col: str) -> pd.Series:
    """Число или NaN: пусто, не число и ±inf - нет данных (как credit._num)."""
    x = pd.to_numeric(df[col], errors="coerce") if col in df else pd.Series(np.nan, index=df.index)
    return x.astype(float).replace([np.inf, -np.inf], np.nan)


def bin_application(df: pd.DataFrame) -> pd.DataFrame:
    """Категории заявки; неизвестный возраст, доля суммы или БКИ - пусто (NaN), флаги без значения - «нет».
    Выручка ≤ 0 известна и хуже любой доли: сумма - больше 30% выручки."""
    yes = lambda s: np.where(pd.Series(s).fillna(0).astype(float) > 0, "да", "нет")  # noqa: E731
    known = lambda v, x: pd.Series(v, index=df.index).where(x.notna().to_numpy())  # noqa: E731
    age = _finite(df, "age_months")
    turn = df.bank_turnover_ratio.fillna(0).astype(float)
    share = _finite(df, "amount_to_revenue").mask(_finite(df, "revenue") <= 0, 1.0)
    dpd = _finite(df, "bki_max_dpd_12m")
    return pd.DataFrame({
        "product": df["product"].values,
        "business_age": known(np.select([age < 12, age < 24, age < 36, age < 60, age < 120],
                                        ["<12", "12-24", "24-36", "36-60", "60-120"], "120+"), age),
        "rko": yes(df.has_rko.values),
        "bank_turnover": np.select([turn > 1, turn >= 0.4], [">100%", "40-100%"], "<40%"),
        "amount_share": known(np.select([share > 0.3, share >= 0.1], [">30%", "10-30%"], "<10%"), share),
        "marketplace": yes(df.marketplace.values),
        "guarantee": yes(df.guarantee.values),
        "bki_overdue": known(np.select([dpd > 30, dpd > 0], [">30 дн", "≤30 дн"], "нет"), dpd),
    }, index=df.index)


def monthly_payment(amount, rate: float, term_m):
    r = rate / 12
    return amount * r / (1 - (1 + r) ** -term_m)


def cash_flow(df: pd.DataFrame, ref_rate: float = REF_RATE, min_dscr: float = MIN_DSCR) -> pd.DataFrame:
    """PD, запас денежного потока и оборот к платежу (разы) по заявке; NaN - нет данных, выручка ≤ 0 - оборот 0."""
    num = lambda c: _finite(df, c)  # noqa: E731
    revenue = num("revenue")
    payment = monthly_payment(num("requested_amount"), ref_rate, num("requested_term_m"))
    return pd.DataFrame({"pd": num("pd"),
                         "cover": (num("ebit") / min_dscr - num("debt_service")) / (12 * payment),
                         "turnover": (revenue / 12 / payment).mask(revenue <= 0, 0.0)}, index=df.index)


def continuous_features(raw: pd.DataFrame) -> pd.DataFrame:
    p = raw["pd"].clip(1e-6, 1 - 1e-6)
    return pd.DataFrame({"logit_pd": np.log(p / (1 - p)),
                         "cash_cover": np.log(raw.cover.clip(0.1, 10)),  # убыток или долг без запаса - 0,1×
                         "ln_turnover_to_payment": np.log(raw.turnover.clip(0.2, 20))}, index=raw.index)


def _show(f: str, raw: pd.Series) -> str:
    v = raw[{"logit_pd": "pd", "cash_cover": "cover", "ln_turnover_to_payment": "turnover"}[f]]
    if pd.isna(v):
        return NO_DATA
    return f"{v:.1%}" if f == "logit_pd" else f"{v:.1f}× платежа"


def _code(bins: pd.DataFrame, f: str, j: int) -> pd.Series:
    """Колонка дизайна: у упорядоченного признака - ступень (категория j и дальше), у продукта - индикатор."""
    idx = bins[f].map({c: i for i, c in enumerate(CATEGORIES[f][0])})
    hit = idx == j if f in UNORDERED else idx >= j
    return hit.astype(float).where(idx.notna())


def _fit_logit(X: np.ndarray, y: np.ndarray, bounds: list, l2: float) -> tuple[float, np.ndarray]:
    """Логит с ограничениями на знаки коэффициентов (L-BFGS-B) и L2; свободный член без ограничений."""
    Xb = np.column_stack([np.ones(len(X)), X])

    def loss(w):
        z = Xb @ w
        g = Xb.T @ (expit(z) - y)
        g[1:] += l2 * w[1:]
        return float(np.sum(np.logaddexp(0, z) - y * z) + 0.5 * l2 * w[1:] @ w[1:]), g

    rate = float(np.clip(y.mean(), 1e-6, 1 - 1e-6))
    w0 = np.r_[math.log(rate / (1 - rate)), np.zeros(X.shape[1])]
    r = minimize(loss, w0, jac=True, method="L-BFGS-B", bounds=[(None, None), *bounds], options={"maxiter": 10000})
    return float(r.x[0]), r.x[1:]


def approval_target(out: pd.DataFrame, requested: pd.Series) -> pd.Series:
    """1 - одобрено по существу, 0 - маршрут/отказ, NaN - дозапрос или стоп-фактор (вне обучения)."""
    same = out.offered_product == out["product"]
    ok = (out.outcome == "APPROVE") | ((out.outcome == "COUNTER") & same & (out.offered_amount >= 0.5 * requested))
    y = ok.astype(float)
    stopped = out.stop_codes.str.len() > 0
    return y.where(~(stopped | (out.outcome == "REQUEST_INFO")))


@dataclass
class ApprovalModel:
    steps: dict = field(default_factory=dict)  # признак → номера оцениваемых категорий
    continuous: tuple = tuple(CONTINUOUS)
    intercept: float = 0.0
    params: dict = field(default_factory=dict)  # колонка дизайна → β (у упорядоченных - шаг к соседу)
    coef: dict = field(default_factory=dict)  # "признак=категория" → эффект к референсу; непрерывный → β
    counts: dict = field(default_factory=dict)
    fill: dict = field(default_factory=dict)  # колонка категории → среднее по обучению (при пропуске)
    center: dict = field(default_factory=dict)  # непрерывный признак → среднее по обучению
    n: int = 0
    ref_rate: float = REF_RATE
    min_dscr: float = MIN_DSCR

    def _columns(self, f: str) -> list:
        return [f"{f}={CATEGORIES[f][0][j]}" for j in self.steps.get(f, [])]

    def _raw(self, df: pd.DataFrame) -> pd.DataFrame:
        return cash_flow(df, self.ref_rate, self.min_dscr)

    def design(self, df: pd.DataFrame) -> pd.DataFrame:
        bins, num = bin_application(df), continuous_features(self._raw(df))
        X = {c: _code(bins, f, j).fillna(self.fill[c])
             for f, js in self.steps.items() for j, c in zip(js, self._columns(f))}
        X.update({f: (num[f] - self.center[f]).fillna(0.0) for f in self.continuous})
        return pd.DataFrame(X, index=df.index)

    @classmethod
    def fit(cls, df: pd.DataFrame, y: pd.Series, continuous=tuple(CONTINUOUS), ref_rate: float = REF_RATE,
            min_dscr: float = MIN_DSCR, l2: float = L2) -> "ApprovalModel":
        keep = y.notna()
        d = df[keep]
        bins = bin_application(d)
        counts = {f"{f}={c}": int((bins[f] == c).sum()) for f, (cats, _) in CATEGORIES.items() for c in cats}
        steps = {f: [j for j, c in enumerate(cats) if c != ref and counts[f"{f}={c}"] >= MIN_COUNT]
                 for f, (cats, ref) in CATEGORIES.items()}
        m = cls(steps, tuple(continuous), counts=counts, n=int(keep.sum()), ref_rate=ref_rate, min_dscr=min_dscr)
        m.fill = {c: float(np.nan_to_num(_code(bins, f, j).mean()))
                  for f, js in steps.items() for j, c in zip(js, m._columns(f))}
        num = continuous_features(m._raw(d))
        m.center = {f: float(np.nan_to_num(num[f].mean())) for f in m.continuous}
        X = m.design(d)
        sign = lambda c: CONTINUOUS[c] if c in CONTINUOUS else SIGNS[c.split("=")[0]]  # noqa: E731
        bounds = [(0.0, None) if sign(c) > 0 else (None, 0.0) if sign(c) < 0 else (None, None) for c in X.columns]
        m.intercept, beta = _fit_logit(X.to_numpy(), y[keep].to_numpy(float), bounds, l2)
        m.params = dict(zip(X.columns, map(float, beta)))
        m.coef = m._effects()
        return m

    def _effects(self) -> dict:
        coef = {}
        for f, (cats, ref) in CATEGORIES.items():
            acc = 0.0
            for c in cats:
                if c == ref:
                    continue
                step = self.params.get(f"{f}={c}", 0.0)
                acc = step if f in UNORDERED else acc + step
                coef[f"{f}={c}"] = acc
        return {**coef, **{f: self.params[f] for f in self.continuous}}

    def logit(self, df: pd.DataFrame) -> np.ndarray:
        X = self.design(df)
        return self.intercept + X.to_numpy() @ np.array([self.params[c] for c in X.columns])

    def predict(self, df: pd.DataFrame, stopped=None) -> np.ndarray:
        p = 1 / (1 + np.exp(-self.logit(df)))
        return np.where(np.asarray(stopped, bool), 0.0, p) if stopped is not None else p

    def score(self, df: pd.DataFrame) -> np.ndarray:
        return BASE + FACTOR * self.logit(df)

    def imputed(self, df: pd.DataFrame) -> list[list[str]]:
        """По каждой строке - признаки, заменённые средним по обучению (soft-режим); пусто - полный режим."""
        miss = pd.concat([bin_application(df)[list(self.steps)].isna(),
                          continuous_features(self._raw(df))[list(self.continuous)].isna()], axis=1)
        return [[c for c in miss.columns if r[c]] for _, r in miss.iterrows()]

    def points_table(self) -> pd.DataFrame:
        rows = []
        for f, (cats, ref) in CATEGORIES.items():
            prev = ref
            for c in cats:
                key = f"{f}={c}"
                like = "как референс" if f in UNORDERED else f"как «{prev}»"
                if c == ref:
                    beta, note = 0.0, "референс"
                elif key not in self.params:
                    beta, note = self.coef[key], f"мало данных (<{MIN_COUNT}): {like}"
                else:
                    beta = self.coef[key]
                    note = f"ограничение знака: {like}" if abs(self.params[key]) < EPS else ""
                rows.append({"признак": LABELS[f], "категория": c, "наблюдений": self.counts.get(key, 0),
                             "beta": beta, "баллы": FACTOR * beta, "комментарий": note})
                prev = c
        for f in self.continuous:
            b = self.params[f]
            note = f"на единицу от среднего {self.center[f]:.2f}" + ("; ограничение знака" if abs(b) < EPS else "")
            rows.append({"признак": LABELS[f], "категория": UNITS[f], "наблюдений": self.n, "beta": b,
                         "баллы": FACTOR * b, "комментарий": note})
        return pd.DataFrame(rows)

    def explain(self, row: pd.Series | dict) -> list[dict]:
        """Вклад признаков заявки в баллы одобрения, по убыванию модуля; пропуск - «нет данных» и средний вклад."""
        one = pd.DataFrame([dict(row)])
        b, raw, X = bin_application(one).iloc[0], self._raw(one).iloc[0], self.design(one).iloc[0]
        out = [{"признак": LABELS[f], "категория": b[f] if isinstance(b[f], str) else NO_DATA,
                "баллы": FACTOR * sum(self.params[c] * X[c] for c in self._columns(f))} for f in CATEGORIES]
        out += [{"признак": LABELS[f], "категория": _show(f, raw), "баллы": FACTOR * self.params[f] * X[f]}
                for f in self.continuous]
        return sorted(out, key=lambda r: -abs(r["баллы"]))

    def save(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: Path) -> "ApprovalModel":
        with open(path, "rb") as f:
            return pickle.load(f)


def train_approval(df: pd.DataFrame, y: pd.Series, groups: pd.Series = None, seed: int = 7, test_size: float = 0.3,
                   **kw) -> tuple[ApprovalModel, dict]:
    """Обучение на 70% решений и метрики на отложенных 30% (стратифицировано). Для сравнения на том же разбиении
    учится модель только на категориях заявки (без PD и денежного потока); groups - классы риска для калибровки."""
    idx = y.index[y.notna()]
    yes, no = int((y[idx] == 1).sum()), int((y[idx] == 0).sum())
    if min(yes, no) < MIN_COUNT:
        raise ValueError(f"для модели одобрения нужно не меньше {MIN_COUNT} одобрений и {MIN_COUNT} отказов среди "
                         f"решений без дозапросов и стоп-факторов, а их {yes} и {no}")
    tr, te = train_test_split(idx, test_size=test_size, stratify=y[idx], random_state=seed)
    m = ApprovalModel.fit(df.loc[tr], y.loc[tr], **kw)
    only_bins = ApprovalModel.fit(df.loc[tr], y.loc[tr], **{**kw, "continuous": ()})
    y_tr, y_te = y.loc[tr].astype(int).to_numpy(), y.loc[te].astype(int).to_numpy()
    p_tr, p_te = m.predict(df.loc[tr]), m.predict(df.loc[te])
    gini = lambda yy, pp: 2 * roc_auc_score(yy, pp) - 1  # noqa: E731
    rep = {"n_train": len(tr), "n_test": len(te), "rate_train": float(y_tr.mean()), "rate_test": float(y_te.mean()),
           "gini_train": gini(y_tr, p_tr), "gini_test": gini(y_te, p_te),
           "gini_test_categories": gini(y_te, only_bins.predict(df.loc[te])),
           "brier_test": float(np.mean((p_te - y_te) ** 2)), "brier_const": float(np.mean((y_tr.mean() - y_te) ** 2)),
           "logloss_test": float(log_loss(y_te, np.clip(p_te, 1e-9, 1 - 1e-9))), "mean_p_test": float(p_te.mean())}
    if groups is not None:
        g = pd.DataFrame({"risk_class": groups.loc[te].to_numpy(), "y": y_te, "p": p_te})
        rep["classes"] = (g.groupby("risk_class").agg(n=("y", "size"), факт=("y", "mean"), прогноз=("p", "mean"))
                          .reset_index())
    return m, rep
