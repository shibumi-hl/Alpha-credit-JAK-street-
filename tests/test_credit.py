import pytest

from scoring.credit import annuity_principal, decide, limit, load_policy

POLICY = load_policy()
REASONS = [{"code": "R01", "category": "высокая долговая нагрузка", "loss": 12.0, "factors": ["debt_to_ebit"]}]


def app(**kw):
    base = {"revenue": 100e6, "ebit": 10e6, "debt_service": 2e6, "age_months": 60, "turnover_months": 48,
            "bki_current_dpd": 0, "bki_max_dpd_12m": 0, "tax_debt_to_revenue": 0.0, "okved_section": "G",
            "okved": "47.11", "status": "ACTIVE", "requested_amount": 5e6, "requested_term_m": 24}
    return {**base, **kw}


@pytest.mark.parametrize("kw,risk,code", [
    ({"bki_current_dpd": 45}, 3, "S01"),
    ({"bki_max_dpd_12m": 120}, 3, "S02"),
    ({"tax_debt_to_revenue": 0.08}, 3, "S03"),
    ({"age_months": 2}, 3, "S04"),
    ({}, 7, "S05"),
    ({"okved": "92.11"}, 3, "S06"),
    ({"status": "LIQUIDATING"}, 3, "S07"),
])
def test_each_stop_factor_rejects_with_its_code(kw, risk, code):
    d = decide(app(**kw), risk, REASONS, POLICY)
    assert d.outcome == "REJECT"
    assert code in [s["code"] for s in d.stop_factors]
    assert d.offered_amount == 0


def test_limit_is_min_of_turnover_share_and_dscr_capacity():
    rate = POLICY["rate_by_class"]["3"]  # ставка по умолчанию, если цену не передали
    share = POLICY["turnover_share_by_class"]["3"]
    # большой EBIT - связывает доля оборота
    rich = limit(app(ebit=1e9), 3, POLICY)
    assert rich == pytest.approx(share * 100e6, rel=1e-6)
    # EBIT 10 млн, DSCR 1.25, обслуживание 2 млн → на новый платёж 6 млн в год
    capacity = 10e6 / POLICY["min_dscr"] - 2e6
    tight = limit(app(), 3, POLICY)
    assert 0 <= annuity_principal(capacity, rate, 24) - tight < POLICY["round_to"]  # округление вниз
    assert tight < share * 100e6
    assert limit(app(ebit=-1e6), 3, POLICY) == 0.0


def test_annuity_principal_inverts_payment():
    p = annuity_principal(12 * 10_000, 0.12, 12)  # 10 тыс. в месяц, 1%/мес, 12 мес
    assert p == pytest.approx(10_000 * (1 - 1.01 ** -12) / 0.01)


def test_within_limit_is_approved_for_requested_amount():
    d = decide(app(requested_amount=1e6), 2, REASONS, POLICY)
    assert d.outcome == "APPROVE" and d.offered_amount == 1e6 and d.limit >= 1e6
    assert d.reasons == REASONS  # одобрение: что снижает балл скоркарты


def test_above_limit_gets_counter_offer_at_limit():
    d = decide(app(requested_amount=50e6), 3, REASONS, POLICY)
    assert d.outcome == "COUNTER"
    assert d.offered_amount == d.limit < 50e6
    # EBIT 10 млн при текущих платежах 2 млн: связывает денежный поток, а не баллы скоркарты
    assert [r["code"] for r in d.reasons] == ["L02"] and d.reasons[0]["factors"] == ["dscr"]


@pytest.mark.parametrize("kw,code", [
    ({"requested_amount": 50e6}, "L02"),  # денежный поток при DSCR ≥ 1,25
    ({"ebit": 1e9, "requested_amount": 50e6}, "L03"),  # доля оборота по классу: 25% от 100 млн
    ({"product": "express", "ebit": 1e9, "revenue": 1e9, "requested_amount": 20e6}, "L04"),  # максимум продукта 10 млн
    ({"product": "overdraft", "has_rko": 1, "bank_turnover_ratio": 1.0, "ebit": 1e9, "requested_amount": 3e6},
     "L05"),  # овердрафт - половина среднемесячного оборота в банке
    ({"ebit": 1e9, "requested_amount": 66_000}, "L06"),  # меньше минимальной суммы продукта
])
def test_counter_offer_names_the_limit_that_binds(kw, code):
    d = decide(app(**kw), 3, REASONS, POLICY)
    assert d.outcome == "COUNTER" and d.offered_product == d.product
    assert [r["code"] for r in d.reasons] == [code]  # одна причина - то, что ограничило сумму, без кодов скоркарты


def test_counter_offer_reason_uses_the_priced_rate():
    def rate_fn(product, cls, amount):  # ставка модели цены: на малые суммы дороже
        return 0.18 if amount >= 5e6 else 0.24

    d = decide(app(requested_amount=50e6), 3, REASONS, POLICY, rate_fn)
    assert d.outcome == "COUNTER" and [r["code"] for r in d.reasons] == ["L02"]


def test_limit_below_product_minimum_routes_to_smaller_product_or_rejects():
    # мощность 80 тыс./год: кредитная линия (от 500 тыс.) не проходит, бизнес-карта (от 50 тыс.) - да
    d = decide(app(ebit=2.6e6, requested_amount=5e6), 3, REASONS, POLICY)
    assert d.outcome == "COUNTER" and d.offered_product == "card"
    assert d.route["reasons"][0]["code"] == "L01"
    # мощности нет совсем - отказ с L01
    d = decide(app(ebit=2.4e6, requested_amount=5e6), 3, REASONS, POLICY)
    assert d.outcome == "REJECT" and d.stop_factors == []
    assert d.reasons[0]["code"] == "L01"


def test_small_tax_debt_or_short_history_in_weak_class_requests_info():
    d = decide(app(tax_debt_to_revenue=0.01), 3, REASONS, POLICY)
    assert d.outcome == "REQUEST_INFO" and "справка" in " ".join(d.requests)
    d = decide(app(turnover_months=12), 5, REASONS, POLICY)
    assert d.outcome == "REQUEST_INFO"
    assert decide(app(turnover_months=12), 2, REASONS, POLICY).outcome == "APPROVE"


def test_request_below_minimum_amount_is_not_approved_as_is():
    d = decide(app(ebit=1e9, requested_amount=66_000), 2, REASONS, POLICY)
    assert d.outcome == "COUNTER" and d.offered_amount == POLICY["products"]["credit_line"]["min_amount"]
    assert [r["code"] for r in d.reasons] == ["L06"]
    d = decide(app(ebit=2.4e6, requested_amount=66_000), 2, REASONS, POLICY)  # мощности нет
    assert d.outcome == "REJECT" and d.reasons[0]["code"] == "L01"


def test_express_for_young_business_is_routed_with_reason():
    d = decide(app(product="express", age_months=7, requested_amount=800_000), 3, REASONS, POLICY)
    assert d.outcome == "COUNTER" and d.offered_product == "card"
    assert d.route["from"] == "express" and d.route["reasons"][0]["code"] == "E01"
    assert 0 < d.offered_amount <= POLICY["products"]["card"]["max_amount"]


def test_overdraft_needs_rko_and_is_sized_by_bank_turnover():
    no_rko = decide(app(product="overdraft", has_rko=0, bank_turnover_ratio=0.0), 3, REASONS, POLICY)
    assert no_rko.offered_product != "overdraft" and no_rko.route["reasons"][0]["code"] == "E02"
    ok = decide(app(product="overdraft", has_rko=1, bank_turnover_ratio=1.5, requested_amount=1e6), 3, REASONS, POLICY)
    assert ok.offered_product == "overdraft"
    assert ok.limit <= 0.5 * 1.5 * 1e6 + 1  # половина среднемесячного оборота в банке


def test_seller_credit_needs_marketplace_and_routing_prefers_order():
    d = decide(app(product="seller_credit", marketplace=0, requested_amount=900_000), 3, REASONS, POLICY)
    assert d.route["reasons"][0]["code"] == "E03" and d.offered_product == "card"
    mp = decide(app(product="express", age_months=5, marketplace=1, requested_amount=3e6), 3, REASONS, POLICY)
    assert mp.offered_product == "card"  # первый в route_order


def test_higher_price_lowers_dscr_limit():
    cheap = limit(app(), 3, POLICY, rate=0.15)
    dear = limit(app(), 3, POLICY, rate=0.35)
    assert dear < cheap
    assert decide(app(), 3, REASONS, POLICY, rate_fn=lambda p, k, amount: 0.15).limit == cheap


def test_no_eligible_product_is_a_reasoned_reject():
    d = decide(app(product="express", age_months=5, ebit=1e4), 3, REASONS, POLICY)
    assert d.outcome == "REJECT" and d.stop_factors == []
    assert {r["code"] for r in d.reasons} >= {"E01", "L01"}


def test_guarantee_and_bank_turnover_raise_turnover_bound_limit():
    base = limit(app(ebit=1e9), 3, POLICY)
    assert limit(app(ebit=1e9, guarantee=1), 3, POLICY) == pytest.approx(base * POLICY["guarantee_limit_mult"])
    assert limit(app(ebit=1e9, has_rko=1, bank_turnover_ratio=0.5), 3, POLICY) == pytest.approx(
        base * POLICY["bank_turnover_bonus"]["mult"])
    assert limit(app(ebit=1e9, has_rko=1, bank_turnover_ratio=0.2), 3, POLICY) == base
    assert limit(app(ebit=1e9, marketplace=1), 3, POLICY) == pytest.approx(base * POLICY["marketplace_limit_mult"], abs=POLICY["round_to"])


NAN = float("nan")
KEY_FIELDS = ["revenue", "ebit", "debt_service", "age_months", "turnover_months", "bki_current_dpd",
              "bki_max_dpd_12m", "tax_debt_to_revenue"]


@pytest.mark.parametrize("field", KEY_FIELDS)
@pytest.mark.parametrize("value", [NAN, None])
def test_missing_key_data_is_request_info_never_an_approval(field, value):
    d = decide(app(**{field: value}), 3, REASONS, POLICY)
    assert d.outcome == "REQUEST_INFO" and d.offered_amount == 0 and d.limit == 0
    assert d.requests


def test_zero_revenue_requests_statements_instead_of_reject():
    d = decide(app(revenue=0.0), 3, REASONS, POLICY)
    assert d.outcome == "REQUEST_INFO" and d.requests


def test_known_stop_factor_still_rejects_when_other_data_is_missing():
    d = decide(app(bki_current_dpd=60, ebit=NAN), 3, REASONS, POLICY)
    assert d.outcome == "REJECT" and d.stop_factors[0]["code"] == "S01"


@pytest.mark.parametrize("kw,match", [({"product": "leasing"}, "продукт"), ({"requested_term_m": 0}, "срок"),
                                      ({"requested_amount": NAN}, "сумм"), ({"requested_amount": -5}, "сумм")])
def test_malformed_application_is_an_error(kw, match):
    with pytest.raises(ValueError, match=match):
        decide(app(**kw), 3, REASONS, POLICY)


def test_limit_is_stable_when_client_requests_exactly_the_offer():
    # ставка зависит от суммы (фиксированные расходы) - лимит ищется до неподвижной точки
    def rate_fn(product, cls, amount):
        return 0.18 + 50_000 / max(amount, 1.0)
    d = decide(app(requested_amount=50e6), 3, REASONS, POLICY, rate_fn=rate_fn)
    assert d.outcome == "COUNTER"
    again = decide(app(requested_amount=d.offered_amount), 3, REASONS, POLICY, rate_fn=rate_fn)
    assert again.outcome == "APPROVE" and again.offered_amount == d.offered_amount


@pytest.mark.parametrize("status", [None, NAN, ""])
def test_unknown_status_is_not_a_stop_factor(status):
    d = decide(app(status=status), 3, REASONS, POLICY)
    assert "S07" not in [s["code"] for s in d.stop_factors]
    assert d.outcome == "APPROVE"


def test_limit_does_not_shrink_when_rate_drops_below_a_threshold():
    # ставка ступенькой (как на границе розница/корпоратив 70 млн): больше запрос - не меньше предложение
    def rate_fn(product, cls, amount):
        return 0.40 if amount > 70e6 else 0.15
    big = app(revenue=1e9, ebit=45e6, debt_service=0.0, requested_term_m=36)  # лимит 62 млн по 40%, 87 млн по 15%
    offers = {req: decide({**big, "requested_amount": req}, 3, REASONS, POLICY, rate_fn=rate_fn) for req in (70e6, 100e6, 200e6)}
    assert offers[100e6].offered_amount == offers[200e6].offered_amount == offers[70e6].offered_amount
    again = decide({**big, "requested_amount": offers[100e6].offered_amount}, 3, REASONS, POLICY, rate_fn=rate_fn)
    assert again.outcome == "APPROVE"
