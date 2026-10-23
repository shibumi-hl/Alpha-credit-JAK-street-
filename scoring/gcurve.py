"""
G-кривая Мосбиржи (кривая бескупонной доходности ОФЗ) по опубликованным параметрам.

Методика Мосбиржи: G(t) в базисных пунктах, непрерывное начисление,
  G(t) = B1 + (B2 + B3)·(T1/t)·(1 − e^(−t/T1)) − B3·e^(−t/T1) + Σ Gi·e^(−(t − ai)² / bi²),
  a1 = 0, a2 = 0.6, a(i+1) = a(i) + 0.6·1.6^(i−1), bi = 0.6·1.6^(i−1).
Эффективная годовая доходность = e^(G/10000) − 1.
"""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

_K, _A2 = 1.6, 0.6
_A = np.cumsum([0.0, _A2] + [_A2 * _K ** i for i in range(1, 8)])
_B = np.array([_A2 * _K ** i for i in range(9)])


@dataclass(frozen=True)
class GCurve:
    b1: float
    b2: float
    b3: float
    t1: float
    g: tuple  # G1..G9

    @classmethod
    def from_row(cls, r) -> "GCurve":
        return cls(r["B1"], r["B2"], r["B3"], r["T1"], tuple(float(r[f"G{i}"]) for i in range(1, 10)))

    def zero(self, t):
        """Непрерывная бескупонная ставка, доли единицы. t в годах."""
        t = np.asarray(t, float)
        e = np.exp(-t / self.t1)
        x = t / self.t1
        safe = np.where(x > 1e-8, x, 1.0)
        ratio = np.where(x > 1e-8, (1 - e) / safe, 1 - x / 2)  # предел (1−e^−x)/x при x→0
        bp = self.b1 + (self.b2 + self.b3) * ratio - self.b3 * e
        bp = bp + np.exp(-((t[..., None] - _A) ** 2) / _B ** 2) @ np.asarray(self.g)
        return bp / 1e4

    def df(self, t):
        t = np.asarray(t, float)
        return np.exp(-self.zero(t) * t)

    def ytm(self, t):
        """Эффективная годовая доходность бескупонной ОФЗ, доли единицы."""
        return np.exp(self.zero(t)) - 1


class CurveStore:
    """Кривые по датам; на дату без торгов берётся последняя предыдущая."""

    def __init__(self, params: pd.DataFrame):
        p = params.sort_values("tradedate")
        self._dates = [date.fromisoformat(str(d)) for d in p.tradedate]
        self._rows = p.to_dict("records")
        self._cache: dict[date, GCurve] = {}

    @classmethod
    def from_csv(cls, path: Path) -> "CurveStore":
        return cls(pd.read_csv(path))

    @property
    def last_date(self) -> date:
        return self._dates[-1]

    def date_of(self, d: date) -> date:
        i = bisect_right(self._dates, d) - 1
        if i < 0:
            raise KeyError(f"нет G-кривой на {d} или раньше")
        return self._dates[i]

    def on(self, d: date) -> GCurve:
        k = self.date_of(d)
        if k not in self._cache:
            self._cache[k] = GCurve.from_row(self._rows[self._dates.index(k)])
        return self._cache[k]
