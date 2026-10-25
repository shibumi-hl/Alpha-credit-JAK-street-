"""
Кредитная логика поверх скоркарты: стоп-факторы, лимит, исход заявки.

Лимит = min(доля годового оборота по классу риска, сумма аннуитета на срок заявки, которую
выдерживает EBIT при DSCR ≥ min_dscr с учётом текущего обслуживания долга, max_amount).
Исход: стоп-фактор → REJECT; спорные данные → REQUEST_INFO; запрос < минимальной суммы продукта → COUNTER на
минимальную; запрос ≤ лимита → APPROVE; иначе COUNTER на лимит. Контрпредложение по запрошенному продукту объясняет
то, что ограничило сумму (L02 денежный поток, L03 доля оборота, L04 максимум продукта, L05 обороты в банке у
овердрафта, L06 минимальная сумма), а не баллы скоркарты. Если продукт недоступен (возраст, нет РКО или
маркетплейса, лимит ниже минимума) - маршрут на первый подходящий из route_order (карта, кредит селлерам,
залоговый) с причиной; ничего не подошло - REJECT с причинами (E01-E03, L01).
Параметры - config/credit_policy.json.
"""
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "credit_policy.json"

STOPS = {
    "S01": "текущая просрочка более 30 дней",
    "S02": "просрочка более 90 дней за последние 12 месяцев",
    "S03": "налоговая задолженность выше 5% оборота",
    "S04": "компания зарегистрирована менее 3 месяцев назад",
    "S05": "высокий риск дефолта (класс 7)",
    "S06": "вид деятельности вне кредитной политики",
    "S07": "компания не действующая (ликвидация, реорганизация, банкротство)",
}
LIMIT_REASON = {"code": "L01", "category": "денежного потока не хватает даже на минимальную сумму", "loss": None,
                "factors": ["dscr"]}
# Что ограничило сумму контрпредложения: ограничение лимита → (код, категория для клиента, факторы)
LIMITS = {
    "dscr": ("L02", "денежного потока с запасом DSCR ≥ {dscr} хватает на платёж только по этой сумме", ["dscr"]),
    "turnover": ("L03", "сумма ограничена долей годового оборота для вашего класса риска", ["revenue"]),
    "max": ("L04", "это максимальная сумма продукта", []),
    "bank_turnover": ("L05", "овердрафт ограничен оборотами по счёту в банке", ["bank_turnover_ratio"]),
    "min_amount": ("L06", "запрошенная сумма меньше минимальной для продукта", []),
}



def limit_codes(policy: dict) -> dict:
    """Код → категория для причин лимита L01–L06 (для отчётов)."""
    reasons = [limit_reason(b, policy) for b in LIMITS]
    return {"L01": LIMIT_REASON["category"], **{r["code"]: r["category"] for r in reasons}}
ELIGIBILITY = {
    "E01": "бизнес слишком молодой для продукта",
    "E02": "нужен расчётный счёт в банке",
    "E03": "нужен магазин на маркетплейсе с переданными данными",
}
_REQUIRES = {"has_rko": "E02", "marketplace": "E03"}


@dataclass
class Decision:
    outcome: str  # APPROVE | COUNTER | REQUEST_INFO | REJECT
    limit: float
    offered_amount: float
    stop_factors: list = field(default_factory=list)
    reasons: list = field(default_factory=list)
    requests: list = field(default_factory=list)
    product: str = ""  # запрошенный продукт
    offered_product: str = ""  # что предлагаем (при маршрутизации - другой продукт)
    route: dict = None  # {"from", "to", "reasons"} - почему запрошенный продукт не подошёл

    def to_dict(self):
        return asdict(self)


def load_policy(path: Path = POLICY_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def annuity_principal(annual_payment: float, rate: float, term_m: int) -> float:
    """Сумма кредита, которую гасит аннуитет annual_payment/12 в месяц за term_m месяцев."""
    if annual_payment <= 0:
        return 0.0
    r = rate / 12
    return annual_payment / 12 * (1 - (1 + r) ** -term_m) / r


# Ключевые данные заявки: без них решение не принимается - дозапрос (что предоставить)
KEY_DATA = {
    "revenue": "бухгалтерская отчётность за последний год",
    "ebit": "бухгалтерская отчётность за последний год",
    "debt_service": "сведения о действующих кредитах и графиках платежей",
    "age_months": "выписка из ЕГРЮЛ с датой регистрации",
    "turnover_months": "отчётность за предыдущие годы или выписки по счетам за 12 месяцев",
    "bki_current_dpd": "согласие на запрос кредитной истории",
    "bki_max_dpd_12m": "согласие на запрос кредитной истории",
    "tax_debt_to_revenue": "справка ФНС о состоянии расчётов с бюджетом",
}


def _num(v) -> float | None:
    """Конечное число или None (пусто, NaN, не число)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _product(a: dict, policy: dict) -> str:
    return a.get("product") or policy["default_product"]


def validate(a: dict, policy: dict) -> None:
    """Заявка, по которой нельзя считать: неизвестный продукт, нет суммы или срока - ValueError."""
    p = _product(a, policy)
    if p not in policy["products"]:
        raise ValueError(f"неизвестный продукт «{p}»; допустимы: {', '.join(policy['products'])}")
    amount, term = _num(a.get("requested_amount")), _num(a.get("requested_term_m"))
    if amount is None or amount <= 0:
        raise ValueError(f"сумма заявки должна быть положительным числом: {a.get('requested_amount')!r}")
    if term is None or term < 1:
        raise ValueError(f"срок заявки в месяцах должен быть не меньше 1: {a.get('requested_term_m')!r}")


def missing_data(a: dict) -> list:
    """Что запросить у клиента: ключевые поля пусты, не числа или выручка ≤ 0."""
    gaps = [k for k in KEY_DATA if _num(a.get(k)) is None]
    if "revenue" not in gaps and _num(a["revenue"]) <= 0:
        gaps.append("revenue")
    return list(dict.fromkeys(KEY_DATA[k] for k in gaps))


def _caps(a: dict, risk_class: int, policy: dict, product: str = None, rate: float = None) -> dict | None:
    """Ограничения лимита по продукту: доля оборота по классу × множитель продукта (turnover), максимум продукта
    (max), у овердрафта - доля среднемесячного оборота в банке (bank_turnover), сумма под платёж при DSCR ≥ min_dscr
    по ставке rate (dscr). None - класс риска вне политики."""
    k = str(int(risk_class))
    if k not in policy["turnover_share_by_class"]:
        return None
    pr = policy["products"][product or _product(a, policy)]
    mult = pr["turnover_mult"]
    if a.get("guarantee"):  # гарантия Корпорации МСП заменяет часть залога
        mult *= policy["guarantee_limit_mult"]
    if a.get("has_rko") and a.get("bank_turnover_ratio", 0) >= policy["bank_turnover_bonus"]["ratio_ge"]:
        mult *= policy["bank_turnover_bonus"]["mult"]  # банк видит обороты - даёт больше
    if a.get("marketplace"):
        mult *= policy["marketplace_limit_mult"]  # выручка подтверждена данными маркетплейса
    caps = {"turnover": policy["turnover_share_by_class"][k] * mult * a["revenue"], "max": pr["max_amount"]}
    if "bank_turnover_share" in pr:
        caps["bank_turnover"] = pr["bank_turnover_share"] * a.get("bank_turnover_ratio", 0) * a["requested_amount"]
    rate = policy["rate_by_class"][k] if rate is None else rate
    capacity = a["ebit"] / policy["min_dscr"] - a["debt_service"]
    caps["dscr"] = annuity_principal(capacity, rate, int(a["requested_term_m"]))
    return caps


def limit(a: dict, risk_class: int, policy: dict, product: str = None, rate: float = None) -> float:
    """Наименьшее из ограничений _caps, округлённое вниз до round_to."""
    caps = _caps(a, risk_class, policy, product, rate)
    if caps is None:
        return 0.0
    lim = max(0.0, min(caps.values()))
    step = policy["round_to"]
    return math.floor(lim / step) * step if lim >= step else lim


def binding_limit(a: dict, risk_class: int, policy: dict, product: str = None, rate: float = None) -> str | None:
    """Какое ограничение _caps задаёт лимит (наименьшее) - объяснение контрпредложения."""
    caps = _caps(a, risk_class, policy, product, rate)
    return min(caps, key=caps.get) if caps else None


def limit_reason(binding: str, policy: dict) -> dict:
    """Причина контрпредложения: что ограничило сумму, в формате кодов причин."""
    code, text, factors = LIMITS[binding]
    return {"code": code, "category": text.format(dscr=f"{policy['min_dscr']:g}".replace(".", ",")), "loss": None,
            "factors": list(factors)}


def eligibility(a: dict, product: str, policy: dict) -> list:
    """Причины, по которым продукт недоступен компании (пусто - доступен)."""
    pr = policy["products"][product]
    out = []
    if a["age_months"] < pr["min_age_months"]:
        out.append({"code": "E01", "category": f"{ELIGIBILITY['E01']}: нужно от {pr['min_age_months']} мес."})
    for need in pr["requires"]:
        if not a.get(need):
            out.append({"code": _REQUIRES[need], "category": ELIGIBILITY[_REQUIRES[need]]})
    return out


def stop_factors(a: dict, risk_class: int, policy: dict) -> list:
    """Срабатывают только по известным значениям; пропуски разбирает missing_data."""
    s = policy["stop"]
    hit = []
    known = {k: _num(a.get(k)) for k in ("bki_current_dpd", "bki_max_dpd_12m", "tax_debt_to_revenue", "age_months")}
    if known["bki_current_dpd"] is not None and known["bki_current_dpd"] > s["bki_current_dpd_gt"]:
        hit.append("S01")
    if known["bki_max_dpd_12m"] is not None and known["bki_max_dpd_12m"] > s["bki_max_dpd_12m_gt"]:
        hit.append("S02")
    if known["tax_debt_to_revenue"] is not None and known["tax_debt_to_revenue"] > s["tax_debt_to_revenue_gt"]:
        hit.append("S03")
    if known["age_months"] is not None and known["age_months"] < s["age_months_lt"]:
        hit.append("S04")
    if risk_class >= s["risk_class_ge"]:
        hit.append("S05")
    if any(str(a.get("okved") or "").startswith(p) for p in s["okved_prefixes"]):
        hit.append("S06")
    status = a.get("status")
    if isinstance(status, str) and status and status not in s["active_statuses"]:  # статус неизвестен - не стоп
        hit.append("S07")
    return [{"code": c, "category": STOPS[c]} for c in hit]


def _requests(a: dict, risk_class: int, policy: dict) -> list:
    q = policy["request_info"]
    out = []
    if a["tax_debt_to_revenue"] > q["tax_debt_to_revenue_gt"]:
        out.append("справка ФНС об исполнении обязанности по уплате налогов или подтверждение погашения долга")
    if a["turnover_months"] <= q["short_history_months_le"] and risk_class >= q["short_history_class_ge"]:
        out.append("выписки по расчётным счетам за 12 месяцев и управленческая отчётность за текущий год")
    return out


def _offer(a, product, risk_class, policy, rate_fn):
    """(лимит, сумма предложения) по продукту или None, если лимит ниже минимальной суммы продукта.

    Ставка зависит от суммы (фиксированные расходы, ступенька веса риска на границе розница/корпоратив), поэтому
    лимит, меньший запроса, пересчитывается по ставке на сам лимит, пока не перестанет уменьшаться, а затем
    ищется наибольшая сумма до запроса, которая проходит по своей же ставке: клиент, запросивший предложенный
    лимит, получит одобрение, а больший запрос не уменьшает предложение."""
    pr = policy["products"][product]
    amount = float(a["requested_amount"])

    def fits(x):  # сумма x проходит DSCR-лимит по ставке, рассчитанной на саму x
        return limit(a, risk_class, policy, product, rate_fn(product, risk_class, x)) >= x

    lim = limit(a, risk_class, policy, product, rate_fn(product, risk_class, amount) if rate_fn else None)
    for _ in range(50 if rate_fn else 0):
        if amount <= lim or lim <= 0:
            break
        nxt = limit(a, risk_class, policy, product, rate_fn(product, risk_class, lim))
        if nxt >= lim:
            break
        lim = nxt
    if rate_fn and 0 < lim < amount:
        step = policy["round_to"]
        hi = min(limit(a, risk_class, policy, product, rate_fn(product, risk_class, lim)), amount)
        if hi > lim and fits(hi):
            lim = hi
        elif hi > lim:  # между lim (проходит) и hi (не проходит) - ступенька ставки; бисекция по шагу округления
            lo = lim
            while hi - lo > step:
                mid = math.floor((lo + hi) / 2 / step) * step
                if mid <= lo:
                    break
                lo, hi = (mid, hi) if fits(mid) else (lo, mid)
            lim = lo
    if lim < pr["min_amount"]:
        return None
    offered = float(min(max(amount, pr["min_amount"]), lim))
    if offered > amount:  # запрос меньше минимальной суммы продукта
        binding = "min_amount"
    else:  # что связывает лимит - по ставке на саму предложенную сумму
        binding = binding_limit(a, risk_class, policy, product, rate_fn(product, risk_class, lim) if rate_fn else None)
    return lim, offered, binding


def decide(a: dict, risk_class: int, reasons: list, policy: dict, rate_fn=None) -> Decision:
    """rate_fn(product, risk_class, amount) -> годовая ставка для DSCR-лимита (по умолчанию rate_by_class).
    Некорректная заявка - ValueError; стоп-фактор по известным данным - REJECT; нет ключевых данных - REQUEST_INFO."""
    validate(a, policy)
    want = _product(a, policy)
    stops = stop_factors(a, risk_class, policy)
    if stops:
        return Decision("REJECT", 0.0, 0.0, stops, reasons, product=want)
    lacking = missing_data(a)
    if lacking:
        return Decision("REQUEST_INFO", 0.0, 0.0, [], reasons, lacking, product=want)
    gaps = eligibility(a, want, policy)
    offer = None if gaps else _offer(a, want, risk_class, policy, rate_fn)
    req = _requests(a, risk_class, policy)
    if req:
        return Decision("REQUEST_INFO", offer[0] if offer else 0.0, 0.0, [], reasons, req, product=want)
    if offer:
        lim, amount, binding = offer
        if amount == float(a["requested_amount"]):  # одобрение: причины - что снижает балл скоркарты
            return Decision("APPROVE", lim, amount, [], reasons, product=want, offered_product=want)
        # контрпредложение объясняет то, что ограничило сумму, а не баллы скоркарты
        return Decision("COUNTER", lim, amount, [], [limit_reason(binding, policy)], product=want, offered_product=want)
    why = gaps or [LIMIT_REASON]
    for alt in policy["route_order"]:
        if alt == want or eligibility(a, alt, policy):
            continue
        alt_offer = _offer(a, alt, risk_class, policy, rate_fn)
        if alt_offer:  # маршрут: почему не подошёл запрошенный продукт - в route
            return Decision("COUNTER", alt_offer[0], alt_offer[1], [], reasons, product=want, offered_product=alt,
                            route={"from": want, "to": alt, "reasons": why})
    extra = [LIMIT_REASON] if gaps else []
    return Decision("REJECT", 0.0, 0.0, [], [*why, *extra, *reasons], product=want)
