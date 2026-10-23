"""
Подбор весов реальных слагаемых скрытой логики по реальной метке ЕГРЮЛ (банкротство + исключение налоговой).

L2-логистическая регрессия события на слагаемые synth.real_terms и отрасль. Налоговый долг не подбирается: срез ФНС
бывает позже события (утечка), его вес остаётся ручным. Риск-слагаемые не могут снижать риск: слагаемое с
отрицательным весом выбрасывается и модель переподбирается (у пустых фирм без долгов «долг снижает риск» - это
эффект выборки, а не причинность). Отраслевые сдвиги центрируются по выборке. Свободный член не нужен:
synth сам подстраивает уровень под целевую долю дефолтов.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

FIT_TERMS = ["lev", "loss", "age_lt24", "weak_eq", "dscr_lt1", "dscr_1_13", "fall", "small", "short12", "short13_24",
             "age_lt36"]


def fit_weights(terms: pd.DataFrame, sections: pd.Series, event, c: float = 1.0) -> dict:
    """{weights: {слагаемое: вес}, sector: {раздел: сдвиг}, dropped: [...]} - веса в лог-шансах."""
    y = np.asarray(event, int)
    sec = pd.get_dummies(pd.Series(sections).fillna("NA").astype(str).to_numpy(), prefix="sec", dtype=float)
    keep, dropped = list(FIT_TERMS), []
    while True:
        X = pd.concat([terms[keep].reset_index(drop=True), sec], axis=1)
        lr = LogisticRegression(C=c, max_iter=5000).fit(X.to_numpy(), y)
        coef = dict(zip(X.columns, lr.coef_[0]))
        wrong = [t for t in keep if coef[t] < 0]
        if not wrong:
            break
        worst = min(wrong, key=lambda t: coef[t])
        keep.remove(worst)
        dropped.append(worst)
    weights = {t: (float(coef[t]) if t in keep else 0.0) for t in FIT_TERMS}
    shares = sec.mean()
    centre = float(sum(coef[col] * shares[col] for col in sec.columns))
    sector = {col[len("sec_"):]: float(coef[col] - centre) for col in sec.columns}
    return {"weights": weights, "sector": sector, "dropped": dropped}
