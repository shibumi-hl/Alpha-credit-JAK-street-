"""
Коды причин: факторы, на которых компания потеряла больше всего баллов, в понятных категориях.

Потеря по фактору = максимум баллов фактора в скоркарте − баллы компании. Факторы одной категории
складываются (долг/выручка и долг/EBIT - это одна «высокая долговая нагрузка»).
"""
CATEGORIES = {
    "R01": "высокая долговая нагрузка",
    "R02": "короткая история оборотов",
    "R03": "просрочки в кредитной истории",
    "R04": "налоговая задолженность",
    "R05": "высокая сезонность выручки",
    "R06": "небольшой или падающий оборот",
    "R07": "недостаточный денежный поток для обслуживания долга",
    "R08": "отраслевой риск",
    "R09": "слабая структура капитала",
    "R10": "заявка без залога",
    "R11": "нет оборотов и данных о бизнесе в банке",
    "R12": "сумма велика относительно оборота",
}
FACTOR_REASON = {
    "debt_to_revenue": "R01", "debt_to_ebit": "R01",
    "turnover_months": "R02", "age_months": "R02",
    "bki_max_dpd_12m": "R03", "bki_overdue_cnt_12m": "R03", "bki_current_dpd": "R03",
    "tax_debt_to_revenue": "R04",
    "revenue_cv": "R05",
    "revenue": "R06", "revenue_growth": "R06",
    "dscr": "R07", "interest_cover": "R07",
    "okved_section": "R08",
    "equity_ratio": "R09",
    "product": "R10", "guarantee": "R10",
    "has_rko": "R11", "bank_turnover_ratio": "R11", "marketplace": "R11",
    "amount_to_revenue": "R12",
}
EPS = 1e-6


def reason_codes(scored_row, model, top: int = 3) -> list[dict]:
    """[{code, category, loss, factors}] по убыванию потери баллов, только с потерей > 0."""
    by = {}
    for f in model.factors:
        loss = model.max_points[f] - float(scored_row[f"points_{f}"])
        if loss > EPS:
            r = by.setdefault(FACTOR_REASON[f], {"loss": 0.0, "factors": []})
            r["loss"] += loss
            r["factors"].append(f)
    out = [{"code": c, "category": CATEGORIES[c], "loss": round(r["loss"], 2), "factors": sorted(r["factors"])}
           for c, r in by.items()]
    return sorted(out, key=lambda r: -r["loss"])[:top]
