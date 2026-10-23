"""
Вес риска по подходу на основе внутренних рейтингов (ПВР), Положение Банка России № 845-П.

Функция риска (п. 3.1, 4.2) - базельская: K = [LGD·N((N⁻¹(PD) + √R·N⁻¹(0,999)) / √(1−R)) − PD·LGD],
для корпоративных требований × (1 + (M − 2,5)·b) / (1 − 1,5·b), b = (0,11852 − 0,05478·ln PD)²; RW = 12,5·K.
Корреляция: корпоративные 0,12…0,24 с поправкой для МСП по выручке S относительно предельной выручки среднего
предприятия L (п. 3.3, S < 0,1·L → S = 0,1·L); розничные прочие (МСП с задолженностью ≤ 70 млн руб., п. 1.4)
0,03…0,16, без поправки на срок. В тексте 845-П формулы даны изображениями: коэффициенты взяты по Базелю
(BCBS), поправка МСП −δ·(1 − (S − 0,1·L)/(0,9·L)) - базельская шкала 5–50 млн евро на отрезке 0,1·L–L.
Числовые параметры (пол PD, LGD, M, порог розницы, L) - config/pricing.json, блок capital.irb.
"""
from math import exp, log, sqrt
from statistics import NormalDist

_N, _NINV = NormalDist().cdf, NormalDist().inv_cdf


def _weight(pd: float, k: float) -> float:
    return (1 - exp(-k * pd)) / (1 - exp(-k))


def corp_correlation(pd: float) -> float:
    w = _weight(pd, 50)
    return 0.12 * w + 0.24 * (1 - w)


def retail_correlation(pd: float) -> float:
    w = _weight(pd, 35)
    return 0.03 * w + 0.16 * (1 - w)


def sme_adjustment(revenue_mln: float, limit_mln: float, max_adj: float) -> float:
    """Скидка к корреляции для МСП: максимальная при выручке ≤ 0,1·L, линейно до нуля при L и выше."""
    if revenue_mln >= limit_mln:
        return 0.0
    s = max(revenue_mln, 0.1 * limit_mln)
    return max_adj * (1 - (s - 0.1 * limit_mln) / (0.9 * limit_mln))


def irb_capital(pd: float, lgd: float, r: float, maturity: float | None = None, confidence: float = 0.999) -> float:
    """K - капитал на рубль требования (только непредвиденные потери: EL вычитается)."""
    if pd >= 1:
        return 0.0
    k = lgd * _N((_NINV(pd) + sqrt(r) * _NINV(confidence)) / sqrt(1 - r)) - pd * lgd
    if maturity is not None:
        b = (0.11852 - 0.05478 * log(pd)) ** 2
        k *= (1 + (maturity - 2.5) * b) / (1 - 1.5 * b)
    return max(k, 0.0)


def exposure_class(exposure_rub: float, cfg: dict) -> str:
    """Розничное МСП - требование не больше порога (п. 1.4), иначе корпоративное."""
    return "retail" if exposure_rub <= cfg["retail_max_exposure_rub"] else "corporate"


def risk_weight(pd: float, lgd: float, exposure_rub: float, revenue_rub: float | None, cfg: dict) -> dict:
    """{rw, irb_class, r}: розничное МСП при требовании ≤ порога, иначе корпоративное с поправкой МСП.
    Выручка неизвестна - поправки МСП нет (консервативно)."""
    pd = max(float(pd), cfg["pd_floor"])
    if exposure_class(exposure_rub, cfg) == "retail":
        r = retail_correlation(pd)
        return {"rw": 12.5 * irb_capital(pd, lgd, r, None, cfg["confidence"]), "irb_class": "retail", "r": r}
    adj = 0.0
    if revenue_rub is not None and revenue_rub == revenue_rub:  # не NaN
        adj = sme_adjustment(revenue_rub / 1e6, cfg["sme_revenue_limit_mln"], cfg["sme_max_adjustment"])
    r = corp_correlation(pd) - adj
    return {"rw": 12.5 * irb_capital(pd, lgd, r, cfg["maturity_years"], cfg["confidence"]), "irb_class": "corporate",
            "r": r}
