"""
Модель вероятности одобрения: логистическая регрессия на one-hot категориях заявки.

Учится на решениях кредитной логики (это модель политики, а не риска - риск даёт PD-скоркарта).
Одобрение = APPROVE или COUNTER по запрошенному продукту на сумму не меньше половины запрошенной;
маршрут на другой продукт и отказ = 0; REQUEST_INFO и стоп-факторы в обучение не входят, при стоп-факторе
вероятность 0. У каждого признака одна референсная категория (без dummy trap): коэффициент - эффект
относительно неё. Категории с числом наблюдений меньше MIN_COUNT не оцениваются (эффект = референсу).

Шкала: балл = 600 + (20 / ln2) · logit(p), баллы категории = (20 / ln2) · β; +20 баллов - вдвое выше шансы.
"""
import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

FACTOR = 20 / math.log(2)
BASE = 600
MIN_COUNT = 30
# признак → (категории по порядку, референс)
CATEGORIES = {
    "product": (["secured", "express", "overdraft", "credit_line", "seller_credit", "card"], "secured"),
    "business_age": (["24+", "12-24", "9-12", "<9"], "24+"),
    "rko": (["нет", "да"], "нет"),
    "bank_turnover": (["<40%", "40-100%", ">100%"], "<40%"),
    "amount_share": (["<10%", "10-30%", ">30%"], "<10%"),
    "marketplace": (["нет", "да"], "нет"),
    "guarantee": (["нет", "да"], "нет"),
    "bki_overdue": (["нет", "≤30 дн", ">30 дн"], "нет"),
}
LABELS = {"product": "Продукт", "business_age": "Возраст бизнеса, мес.", "rko": "РКО в банке",
          "bank_turnover": "Обороты в банке / лимит", "amount_share": "Сумма / годовая выручка",
          "marketplace": "Селлер маркетплейса с данными", "guarantee": "Гарантия Корпорации МСП",
          "bki_overdue": "Просрочки в БКИ за 12 мес."}


def bin_application(df: pd.DataFrame) -> pd.DataFrame:
    yes = lambda s: np.where(pd.Series(s).fillna(0).astype(float) > 0, "да", "нет")  # noqa: E731
    age = df.age_months.astype(float)
    turn = df.bank_turnover_ratio.fillna(0).astype(float)
    share = df.amount_to_revenue.astype(float)
    dpd = df.bki_max_dpd_12m.fillna(0).astype(float)
    return pd.DataFrame({
        "product": df["product"].values,
        "business_age": np.select([age < 9, age < 12, age < 24], ["<9", "9-12", "12-24"], "24+"),
        "rko": yes(df.has_rko.values),
        "bank_turnover": np.select([turn > 1, turn >= 0.4], [">100%", "40-100%"], "<40%"),
        "amount_share": np.select([share > 0.3, share >= 0.1], [">30%", "10-30%"], "<10%"),
        "marketplace": yes(df.marketplace.values),
        "guarantee": yes(df.guarantee.values),
        "bki_overdue": np.select([dpd > 30, dpd > 0], [">30 дн", "≤30 дн"], "нет"),
    }, index=df.index)


def approval_target(out: pd.DataFrame, requested: pd.Series) -> pd.Series:
    """1 - одобрено по существу, 0 - маршрут/отказ, NaN - дозапрос или стоп-фактор (вне обучения)."""
    same = out.offered_product == out["product"]
    ok = (out.outcome == "APPROVE") | ((out.outcome == "COUNTER") & same & (out.offered_amount >= 0.5 * requested))
    y = ok.astype(float)
    stopped = out.stop_codes.str.len() > 0
    return y.where(~(stopped | (out.outcome == "REQUEST_INFO")))


@dataclass
class ApprovalModel:
    columns: list = field(default_factory=list)
    intercept: float = 0.0
    coef: dict = field(default_factory=dict)  # "признак=категория" → β
    counts: dict = field(default_factory=dict)

    def design(self, bins: pd.DataFrame, columns=None) -> pd.DataFrame:
        cols = columns or self.columns
        return pd.DataFrame({c: (bins[c.split("=")[0]] == c.split("=", 1)[1]).astype(float) for c in cols},
                            index=bins.index)

    @classmethod
    def fit(cls, df: pd.DataFrame, y: pd.Series) -> "ApprovalModel":
        keep = y.notna()
        bins = bin_application(df[keep])
        counts = {f"{f}={c}": int((bins[f] == c).sum()) for f, (cats, _) in CATEGORIES.items() for c in cats}
        cols = [f"{f}={c}" for f, (cats, ref) in CATEGORIES.items() for c in cats
                if c != ref and counts[f"{f}={c}"] >= MIN_COUNT]
        m = cls(cols, 0.0, {}, counts)
        lr = LogisticRegression(C=np.inf, max_iter=5000).fit(m.design(bins), y[keep].astype(int))
        m.intercept = float(lr.intercept_[0])
        m.coef = dict(zip(cols, map(float, lr.coef_[0])))
        return m

    def logit(self, df: pd.DataFrame) -> np.ndarray:
        X = self.design(bin_application(df))
        return self.intercept + X.to_numpy() @ np.array([self.coef[c] for c in self.columns])

    def predict(self, df: pd.DataFrame, stopped=None) -> np.ndarray:
        p = 1 / (1 + np.exp(-self.logit(df)))
        return np.where(np.asarray(stopped, bool), 0.0, p) if stopped is not None else p

    def score(self, df: pd.DataFrame) -> np.ndarray:
        return BASE + FACTOR * self.logit(df)

    def points_table(self) -> pd.DataFrame:
        rows = []
        for f, (cats, ref) in CATEGORIES.items():
            for c in cats:
                key = f"{f}={c}"
                beta = 0.0 if c == ref else self.coef.get(key)
                note = "референс" if c == ref else ("" if key in self.coef else f"мало данных (<{MIN_COUNT})")
                rows.append({"признак": LABELS[f], "категория": c, "наблюдений": self.counts.get(key, 0),
                             "beta": beta if beta is not None else 0.0,
                             "баллы": FACTOR * (beta or 0.0), "комментарий": note})
        return pd.DataFrame(rows)

    def explain(self, row: pd.Series | dict) -> list[dict]:
        """Вклад категорий заявки в баллы одобрения, по убыванию модуля."""
        b = bin_application(pd.DataFrame([dict(row)])).iloc[0]
        out = [{"признак": LABELS[f], "категория": b[f], "баллы": FACTOR * self.coef.get(f"{f}={b[f]}", 0.0)}
               for f in CATEGORIES]
        return sorted(out, key=lambda r: -abs(r["баллы"]))

    def save(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: Path) -> "ApprovalModel":
        with open(path, "rb") as f:
            return pickle.load(f)
