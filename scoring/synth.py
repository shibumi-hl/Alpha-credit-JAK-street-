"""
Признаки компаний для скоринга и синтетическая метка дефолта.

features() считает наблюдаемые признаки из реальных полей ФНС/ГИР БО (оборот, возраст, ОКВЭД,
долговая нагрузка, покрытие, налоговый долг). enrich() добавляет то, чего в открытых данных нет:
кредитную историю БКИ, сезонность помесячной выручки, параметры заявки, и метку default_12m по
скрытой логике с шумом. Скрытый риск наружу не отдаётся - скоркарта видит только признаки.
generate() синтезирует и реальную часть (для тестов и прогона без загрузки ФНС).
"""
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

SECTIONS = list("ABCDEFGHIJKLMNOPQRS")
# Доли разделов ОКВЭД среди МСП-юрлиц (грубо) и базовая сезонность выручки
_SECTION_P = dict(A=.03, B=.005, C=.10, D=.01, E=.01, F=.13, G=.30, H=.07, I=.03, J=.04, K=.02, L=.07,
                  M=.09, N=.04, O=.001, P=.01, Q=.02, R=.01, S=.034)
_SEASON = dict(A=.55, F=.35, I=.30, R=.30, G=.20, H=.18, N=.18, C=.15)
_SECTOR_RISK = dict(F=.45, I=.35, G=.20, H=.20, A=.15, L=-.10, K=-.15, Q=-.20, D=-.20, J=-.05)

NUMERIC = ["revenue", "age_months", "turnover_months", "debt_to_revenue", "debt_to_ebit", "equity_ratio",
           "interest_cover", "dscr", "revenue_growth", "tax_debt_to_revenue", "revenue_cv",
           "bki_max_dpd_12m", "bki_overdue_cnt_12m", "bki_current_dpd",
           "has_rko", "bank_turnover_ratio", "marketplace", "guarantee", "amount_to_revenue"]
CATEGORICAL = ["okved_section", "product"]
PRODUCTS = ["secured", "express", "overdraft", "credit_line", "seller_credit", "card"]
_PRODUCT_P = [.20, .30, .15, .20, .08, .07]
_PRODUCT_RISK = dict(secured=-.6, express=.6, overdraft=.15, credit_line=0.0, seller_credit=.1, card=.45)
MIN_REQUEST = 10_000.0  # минимальная сумма заявки, руб.
NOISE = 2.3  # шум скрытой логики (ручные веса): Gini на реальной выборке ~0.6 (цель 0.55-0.65, как у скоркарт МСБ)
FEATURES = NUMERIC + CATEGORICAL
CAP = 99.0  # отношения с нулевым знаменателем


def _ratio(num, den, cap=CAP, neg=CAP):
    """num/den; den == 0 → 0 при num == 0, cap при num > 0, −cap при num < 0 (убыток без долга - худшее покрытие);
    den < 0 (убыток) → neg."""
    num, den = np.asarray(num, float), np.asarray(den, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        zero = np.where(num == 0, 0.0, np.where(num > 0, cap, -cap))
        r = np.where(den > 0, num / np.where(den > 0, den, 1), np.where(den < 0, neg, zero))
    return np.clip(r, -cap, cap)


def debt_service(raw: pd.DataFrame) -> np.ndarray:
    """Годовое обслуживание долга: по ДДС (проценты + возврат), без ДДС - проценты + 1/2 краткосрочного
    + 1/5 долгосрочного долга."""
    cf = raw.interest_paid + raw.loan_repaid
    proxy = raw.interest + 0.5 * raw.debt_st + 0.2 * raw.debt_lt
    return np.where((raw.has_cashflow == 1) & (cf > 0), cf, proxy)


def features(raw: pd.DataFrame, asof: date) -> pd.DataFrame:
    rev = raw.revenue.astype(float)
    out = pd.DataFrame({"inn": raw.inn.values, "okved_section": raw.okved_section.fillna("NA").values})
    out["revenue"] = rev.values
    by_year = (asof.year - raw.reg_year.fillna(asof.year)) * 12 + asof.month - 6  # регистрация в середине года
    if "reg_date" in raw:
        reg = pd.to_datetime(raw.reg_date, errors="coerce")
        exact = (asof.year - reg.dt.year) * 12 + asof.month - reg.dt.month
        by_year = exact.where(reg.notna(), by_year)
    out["age_months"] = np.clip(by_year.astype(float), 1, None).values
    out["turnover_months"] = (raw.bfo_years.astype(int) * 12).values
    out["debt_to_revenue"] = (raw.debt / rev).values
    out["debt_to_ebit"] = _ratio(raw.debt, raw.ebit)
    out["equity_ratio"] = np.clip(_ratio(raw.equity, raw.assets, cap=1, neg=0), -5, 1)
    out["interest_cover"] = _ratio(raw.ebit, raw.interest, neg=0)
    out["dscr"] = _ratio(raw.ebit, debt_service(raw))  # без обслуживания: прибыль - лучшее, убыток - худшее
    prev = raw.revenue_prev.astype(float)
    out["revenue_growth"] = np.where(prev > 0, np.clip(rev / prev.where(prev > 0) - 1, -1, 10), np.nan)
    out["tax_debt_to_revenue"] = (raw.tax_debt / rev).values
    out["debt_service"] = debt_service(raw)
    out["ebit"] = raw.ebit.values
    for c in ("status", "okved", "debt", "period"):
        if c in raw:
            out[c] = raw[c].values
    return out


def generate_real(n: int, rng: np.random.Generator, asof: date) -> pd.DataFrame:
    """Синтетическая замена реальных полей ФНС/ГИР БО (та же схема, что data/fns/companies.csv)."""
    sec = rng.choice(list(_SECTION_P), size=n, p=np.array(list(_SECTION_P.values())) / sum(_SECTION_P.values()))
    revenue = np.exp(rng.normal(np.log(25e6), 1.4, n)).clip(1e6, 2e9)
    margin = rng.normal(0.06, 0.12, n)
    ebit = revenue * margin
    has_debt = rng.random(n) < 0.45
    debt = np.where(has_debt, revenue * np.exp(rng.normal(np.log(0.25), 1.0, n)), 0.0)
    st_share = rng.uniform(0.2, 1.0, n)
    assets = revenue * np.exp(rng.normal(np.log(0.6), 0.6, n))
    equity = assets * rng.normal(0.35, 0.35, n).clip(-1, 0.95)
    interest = debt * rng.uniform(0.08, 0.22, n)
    bfo_years = rng.choice([1, 2, 3, 4, 5, 6], size=n, p=[.10, .10, .10, .10, .10, .50])
    reg = asof.year - np.maximum(bfo_years, rng.integers(0, 22, n))
    has_cf = rng.random(n) < 0.3
    tax = np.where(rng.random(n) < 0.24, revenue * np.exp(rng.normal(np.log(0.002), 1.8, n)), 0.0)
    return pd.DataFrame({
        "inn": [f"{9000000000 + i:010d}" for i in range(n)], "okved_section": sec, "status": "ACTIVE",
        "reg_year": reg, "bfo_years": bfo_years, "period": asof.year - 1,
        "revenue": revenue, "revenue_prev": np.where(bfo_years > 1, revenue / np.exp(rng.normal(0.08, 0.3, n)), np.nan),
        "debt": debt, "debt_st": debt * st_share, "debt_lt": debt * (1 - st_share), "equity": equity, "assets": assets,
        "ebit": ebit, "interest": interest, "interest_paid": np.where(has_cf, interest, 0.0),
        "loan_repaid": np.where(has_cf, debt * st_share, 0.0), "has_cashflow": has_cf.astype(int),
        "tax_debt": tax, "income": revenue * 1.02,
    })


def _stress(f: pd.DataFrame) -> np.ndarray:
    """Финансовый стресс из реальных признаков - общий драйвер просрочек и дефолта."""
    lev = np.log1p(np.clip(f.debt_to_revenue, 0, 10))
    loss = (f.ebit < 0).astype(float)
    tax = np.log1p(200 * np.clip(f.tax_debt_to_revenue, 0, 1))
    young = (f.age_months < 24).astype(float)
    weak_eq = (f.equity_ratio < 0).astype(float)
    return 1.1 * lev + 0.8 * loss + 0.5 * tax + 0.5 * young + 0.6 * weak_eq


def _bki(f, stress, rng):
    n = len(f)
    has_loans = (f.debt > 0).to_numpy() | (rng.random(n) < 0.25)
    p_late = 1 / (1 + np.exp(-(-2.6 + 1.1 * stress + rng.normal(0, 0.7, n))))
    late = has_loans & (rng.random(n) < p_late)
    sev = rng.exponential(1.0 + 0.8 * stress, n)
    dpd = np.where(late, np.select([sev < 0.8, sev < 1.6, sev < 2.4, sev < 3.2], [5, 20, 45, 75], 120), 0)
    cnt = np.where(late, 1 + rng.poisson(0.5 + 0.6 * stress), 0)
    cur = np.where(late & (rng.random(n) < 0.15 + 0.1 * np.minimum(stress, 3)), np.minimum(dpd, rng.choice([5, 15, 40, 95], n)), 0)
    return dpd, cnt, cur


# Веса реальных слагаемых скрытой логики (лог-шансы). Ручные - по умолчанию; подобранные по реальной метке ЕГРЮЛ
# (scripts/calibrate_synth.py) лежат в config/synth_calibration.json и используются при сборке выборки из ФНС.
DEFAULT_WEIGHTS = {"lev": 0.99, "loss": 0.72, "tax": 0.45, "age_lt24": 0.45, "weak_eq": 0.54, "dscr_lt1": 0.8,
                   "dscr_1_13": 0.3, "fall": 0.6, "small": 0.4, "short12": 0.9, "short13_24": 0.4, "age_lt36": 0.4,
                   "sector": dict(_SECTOR_RISK)}
CALIBRATION_PATH = Path(__file__).resolve().parents[1] / "config" / "synth_calibration.json"


def real_terms(f: pd.DataFrame) -> pd.DataFrame:
    """Слагаемые скрытой логики, построенные только из реальных полей (ФНС, ГИР БО)."""
    return pd.DataFrame({
        "lev": np.log1p(np.clip(f.debt_to_revenue, 0, 10)),
        "loss": (f.ebit < 0).astype(float),
        "tax": np.log1p(200 * np.clip(f.tax_debt_to_revenue, 0, 1)),
        "age_lt24": (f.age_months < 24).astype(float),
        "weak_eq": (f.equity_ratio < 0).astype(float),
        "dscr_lt1": (f.dscr < 1).astype(float),
        "dscr_1_13": ((f.dscr >= 1) & (f.dscr < 1.3)).astype(float),
        "fall": (f.revenue_growth.fillna(0) < -0.3).astype(float),
        "small": (f.revenue < 5e6).astype(float),
        "short12": (f.turnover_months <= 12).astype(float),
        "short13_24": ((f.turnover_months > 12) & (f.turnover_months <= 24)).astype(float),
        "age_lt36": (f.age_months < 36).astype(float),
    }, index=f.index)


def load_calibration(path: Path = CALIBRATION_PATH) -> dict | None:
    """Веса из калибровки по реальной метке или None, если файла нет."""
    if not Path(path).exists():
        return None
    try:
        cal = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as e:
        raise ValueError(f"{path}: файл калибровки не JSON ({e})") from e
    weights, sector = cal.get("weights") if isinstance(cal, dict) else None, None
    if isinstance(cal, dict):
        sector = cal.get("sector", DEFAULT_WEIGHTS["sector"])
    numeric = lambda d: isinstance(d, dict) and all(isinstance(v, (int, float)) for v in d.values())  # noqa: E731
    if not numeric(weights) or set(weights) - set(DEFAULT_WEIGHTS) or not numeric(sector):
        raise ValueError(f"{path}: нужны словари чисел weights (ключи {sorted(DEFAULT_WEIGHTS)}) и sector")
    return {**DEFAULT_WEIGHTS, **weights, "sector": sector}


def _real_part(f: pd.DataFrame, weights: dict) -> np.ndarray:
    terms = real_terms(f)
    z = sum(weights[k] * terms[k].to_numpy() for k in terms.columns)
    return z + f.okved_section.map(weights["sector"]).fillna(0).to_numpy()


def _logit(f: pd.DataFrame, stress, rng, weights: dict = DEFAULT_WEIGHTS) -> np.ndarray:
    """Скрытая логика дефолта: реальные слагаемые с весами (ручными или подобранными по ЕГРЮЛ), синтетические
    слагаемые (БКИ, продукт, сезонность × долг, РКО, маркетплейс, сумма, гарантия), шум."""
    over = np.select([f.bki_max_dpd_12m > 90, f.bki_max_dpd_12m > 30, f.bki_max_dpd_12m > 0], [2.0, 1.2, 0.4], 0)
    current = np.where(f.bki_current_dpd > 30, 1.5, np.where(f.bki_current_dpd > 0, 0.6, 0))
    season_x_lev = 1.2 * np.clip(f.revenue_cv - 0.25, 0, None) * np.log1p(np.clip(f.debt_to_revenue, 0, 10))
    product = f["product"].map(_PRODUCT_RISK).fillna(0).to_numpy()
    in_bank = np.select([f.bank_turnover_ratio >= 1, f.bank_turnover_ratio >= 0.4], [-0.5, -0.25], 0)
    mp = np.where(f.marketplace == 1, -0.25, 0)
    big = np.select([f.amount_to_revenue > 0.3, f.amount_to_revenue > 0.1], [0.5, 0.15], 0)
    gar = np.where(f.guarantee == 1, -0.1, 0)
    return (_real_part(f, weights) + over + current + season_x_lev
            + product + in_bank + mp + big + gar + rng.normal(0, NOISE, len(f)))


def _application(f: pd.DataFrame, rng) -> None:
    """Поля заявки (синтетика): продукт, сумма и срок, РКО и обороты в банке, маркетплейс, гарантия, допы."""
    n = len(f)
    mp_p = np.where(f.okved_section == "G", 0.25, 0.04)
    f["marketplace"] = (rng.random(n) < mp_p).astype(int)
    product = rng.choice(PRODUCTS, n, p=_PRODUCT_P)
    product = np.where((product == "seller_credit") & (f.marketplace == 0), "express", product)
    product = np.where((f.marketplace == 1) & (rng.random(n) < 0.4), "seller_credit", product)
    f["product"] = product
    amount = np.round(f.revenue * np.exp(rng.normal(np.log(0.12), 0.6, n)), -3)
    overdraft = np.round(f.revenue * np.exp(rng.normal(np.log(0.03), 0.5, n)), -3)  # порядка месячного оборота
    req = np.select([product == "card", product == "overdraft"], [np.minimum(amount, 1e6), overdraft], amount)
    f["requested_amount"] = np.maximum(req, MIN_REQUEST)  # выручка в ГИР БО бывает 1 тыс. руб. - заявка не нулевая
    term = rng.choice([12, 24, 36], n, p=[.4, .4, .2])
    long_term = rng.choice([24, 36, 60], n, p=[.3, .4, .3])  # под залог дают дольше
    f["requested_term_m"] = np.select([np.isin(product, ["overdraft", "card"]), product == "secured"], [12, long_term], term)
    f["has_rko"] = (rng.random(n) < 0.35).astype(int)
    share = rng.uniform(0.2, 0.9, n)
    # среднемесячный оборот через счёт в банке / запрошенный лимит
    f["bank_turnover_ratio"] = np.where(f.has_rko == 1, np.clip(f.revenue * share / 12 / f.requested_amount.clip(lower=1), 0, 20), 0.0)
    gp = 0.06 * ~np.isin(product, ["card", "overdraft"])
    f["guarantee"] = (rng.random(n) < gp).astype(int)
    f["amount_to_revenue"] = f.requested_amount / f.revenue
    f["subscription"] = (rng.random(n) < 0.2).astype(int)
    f["insurance"] = (rng.random(n) < 0.5).astype(int)


def _calibrate(z: np.ndarray, target: float) -> float:
    lo, hi = -20.0, 10.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if (1 / (1 + np.exp(-(z + mid)))).mean() < target else (lo, mid)
    return (lo + hi) / 2


def enrich(raw: pd.DataFrame, seed: int, asof: date, default_rate: float = 0.05, weights: dict = None) -> pd.DataFrame:
    """Признаки + синтетика + метка. weights - веса реальных слагаемых (по умолчанию ручные)."""
    rng = np.random.default_rng(seed)
    f = features(raw.reset_index(drop=True), asof)
    n = len(f)
    stress = _stress(f)
    base = f.okved_section.map(_SEASON).fillna(0.12).to_numpy()
    f["revenue_cv"] = np.clip(base * np.exp(rng.normal(0, 0.35, n)) + 0.05 * np.minimum(stress, 3) * rng.random(n), 0.02, 1.5)
    f["bki_max_dpd_12m"], f["bki_overdue_cnt_12m"], f["bki_current_dpd"] = _bki(f, stress, rng)
    _application(f, rng)
    z = _logit(f, stress, rng, weights or DEFAULT_WEIGHTS)
    p = 1 / (1 + np.exp(-(z + _calibrate(z, default_rate))))
    f["default_12m"] = (rng.random(n) < p).astype(int)
    return f


def generate(n: int, seed: int, asof: date, default_rate: float = 0.05) -> pd.DataFrame:
    return enrich(generate_real(n, np.random.default_rng(seed), asof), seed + 1, asof, default_rate)
