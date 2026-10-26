# API МойАльфаКредит

Базовый адрес в Docker — `http://localhost:8080`, локально — `http://localhost:3100`. Swagger UI — `/api/docs`,
схема — `/api/openapi.json` (копия: `docs/openapi.json`), коллекция запросов — `docs/postman_collection.json`.

**Авторизация.** Защищённые методы требуют заголовок `Authorization: Bearer <token>`; токен выдаёт
`POST /api/v1/auth/login`. Токен — `base64url(JSON {sub, role, exp}).base64url(HMAC-SHA256(SECRET_KEY))`, живёт 12 ч.
Нет заголовка — 401 «Нужно войти», неверная подпись или истёкший срок — 401 «Нужно войти заново».

**Ошибки.** Тело всегда `{"detail": "..."}` (у ошибок валидации pydantic — список полей): 401 нет входа,
403 действие недоступно роли, 404 нет компании или заявки, 409 конфликт статуса или дубль, 422 некорректные
данные (в том числе ошибки движка, текст по-русски).

## Песочница (без авторизации)

| Метод и путь | Запрос | Ответ | Ошибки |
|---|---|---|---|
| `GET /api/health` | — | `{"ok": true, "asof": "2026-10-25"}` | — |
| `GET /api/v1/meta` | — | справочники: `products`, `codes`, `features`, `min_dscr`, `round_to`, `asof`, `pricing_note` | — |
| `GET /api/v1/personas` | — | `[{id, name, inn, tagline, story, okved_name, okved}]` | — |
| `GET /api/v1/personas/{pid}` | — | карточка + `facts`, `levers` | 404 |
| `POST /api/v1/evaluations` | `{persona_id, levers}` | оценка: `outcome`, `score`, `pd`, `risk_class`, `approval_probability`, `approval_mode`, `offered_product`, `offered_amount`, `limit`, `route`, `pricing`, `stop_factors`, `reasons`, `requests`, `monthly_payment`, … | 404, 422 |
| `POST /api/v1/whatif` | `{persona_id, levers}` | `{base: оценка, scenarios: [{key, title, outcome, offered_amount, approval_probability, delta_approval_pp, rate, all_in, delta_rate_pp, delta_all_in_pp, levers}]}` | 404, 422 |
| `POST /api/v1/simulate` | `{persona_id, levers, axis: "requested_amount" \| "requested_term_m", n: 4..64}` | `{axis, points, limit, binding, requested}` | 404, 422 (у возобновляемого продукта нет оси срока) |

`levers`: `product` (`express`, `secured`, `overdraft`, `credit_line`, `seller_credit`, `card`),
`requested_amount` (10 000 – 300 000 000), `requested_term_m` (1–120), `has_rko`, `bank_turnover_month_rub`,
`guarantee`, `marketplace`, `insurance`, `subscription`, `bki_consent`. Лишние поля отбрасываются: факты компании
берутся только из файла демо-компании.

## Вход

### `POST /api/v1/auth/login`

```json
{"username": "client", "password": "client"}
```

200: `{"token": "eyJ...", "role": "client", "name": "Марина Соколова"}`. 401 «Неверный логин или пароль».
Учётки: `client/client`, `client2/client2`, `analyst/analyst`.

## Компания и лента (без авторизации)

### `GET /api/v1/companies/{inn}` — мок ЕГРЮЛ / «Прозрачный бизнес»

200:

```json
{"persona_id": "marina", "name": "ООО «Тёплый дом»", "inn": "0010000017", "ogrn": "110000017001",
 "okved": "47.91", "okved_name": "Торговля розничная через интернет", "status": "ACTIVE",
 "status_label": "Действующая", "registered": "2023-10-01", "age_months": 36, "address": "г. Москва (демо-адрес)",
 "director_role": "Генеральный директор",
 "sources": [{"name": "ЕГРЮЛ (мок)", "asof": "2026-10-25"}, {"name": "Прозрачный бизнес ФНС (мок)", "asof": "2026-10-25"}]}
```

422 «ИНН юрлица — 10 цифр с верной контрольной цифрой» (например `1234567890`), 404 «Не нашли компанию по ИНН»
(например `0000000000`).

### `GET /api/v1/news?persona_id=marina`

200: `[{id, date, tag, title, body, why, action}]` — отбор по ОКВЭД, продукту, флагам компании и статусу её
последней заявки. 404 — нет демо-компании.

## Моки внешних сервисов по HTTP (без авторизации)

Контракт, по которому конвейер ходит к реестрам, бюро и ленте (`api/integrations.py`). Адрес сервиса — переменная
окружения `REGISTRY_URL`, `BKI_URL`, `NEWS_URL`; пусто — встроенный мок без HTTP. Встроенные моки отвечают по тому же
контракту здесь, поэтому, например, `BKI_URL=http://localhost:8000/api/mock/bki` (порт приложения внутри контейнера)
прогоняет конвейер через HTTP, а настоящий сервис банка подключается сменой адреса.

### `GET /api/mock/registry/companies/{inn}` — реестры (ЕГРЮЛ, «Прозрачный бизнес»)

Тот же ответ и те же коды, что у `GET /api/v1/companies/{inn}`: 200 — карточка компании, 422 — ИНН не юрлица,
404 — не найдена.

### `GET /api/mock/bki/reports/{inn}` — бюро кредитных историй

200: `{"inn", "current_dpd", "max_dpd_12m", "overdue_cnt_12m", "asof"}`. 503 — бюро не отвечает (демо-компания
«Ромашка», `0060000005`, сценарий T6). Конвейер делает 3 попытки; если бюро так и не ответило, заявка уходит
аналитику с пометкой «Техническая ошибка».

### `GET /api/mock/news/feed?inn=0010000017&status=SUBMITTED`

200: та же лента, что `GET /api/v1/news`, по ИНН компании и статусу её заявки (`status` можно не передавать).
404 — нет демо-компании с таким ИНН.

## Заявки (Bearer)

### `POST /api/v1/applications` — подача (только роль client)

Заголовок `Idempotency-Key` (необязательный, до 128 символов). Тело:

```json
{"persona_id": "marina",
 "levers": {"product": "express", "requested_amount": 6000000, "requested_term_m": 12, "has_rko": false,
            "bank_turnover_month_rub": 0, "guarantee": false, "marketplace": true, "insurance": true,
            "subscription": false, "bki_consent": true},
 "purpose": "закупка", "bki_consent": true}
```

201: Application (статус `SUBMITTED` или дальше). Повтор с тем же `Idempotency-Key` — та же заявка.
Ошибки: 401; 403 «Подавать заявку может только клиент»; 404 нет компании; 409 «По этой компании и продукту уже
есть заявка в работе»; 422 нет `bki_consent: true` в теле или некорректные рычаги.

### `GET /api/v1/applications?status=ANALYST`

Клиент — только свои, аналитик — все; `status` — необязательный фильтр. 200:

```json
[{"id": "app_576cb8e310a5", "company": {"name": "ООО «Тёплый дом»", "inn": "0010000017"},
  "product_label": "экспресс-кредит без залога", "amount": 6000000.0, "term_m": 12, "status": "COUNTER_OFFER",
  "status_label": "Контрпредложение", "whose_turn": "client", "updated_at": "2026-10-25T17:53:42+00:00",
  "route_reason": null}]
```

### `GET /api/v1/applications/{id}`

200: Application. Чтение также двигает созревшие автоматические шаги. 404 — нет заявки или она чужая (для клиента).

### `POST /api/v1/applications/{id}/actions`

```json
{"action": "accept_offer", "note": null, "amount": null, "code": null}
```

| `action` | Роль | Поля |
|---|---|---|
| `upload_documents` | client | — |
| `accept_offer` | client | — |
| `sign` | client | `code` — код из `sign_code` |
| `withdraw` | client | — |
| `approve` | analyst | `note` обязателен |
| `counter` | analyst | `note`, `amount` обязательны |
| `reject` | analyst | `note` обязателен |
| `request_info` | analyst | `note` обязателен (название документа) |

200: Application после перехода. 403 — действие другой роли; 409 — недоступно в текущем статусе или движок не
даёт условий; 422 — неизвестное действие, нет комментария аналитика, нет суммы `counter`, неверный код подписи.
Допустимые переходы — `docs/state-machine.md`.

### Пример Application (Марина, T2, роль client)

```json
{
  "id": "app_576cb8e310a5",
  "persona_id": "marina",
  "company": {"name": "ООО «Тёплый дом»", "inn": "0010000017"},
  "product": "express",
  "product_label": "экспресс-кредит без залога",
  "levers": {"product": "express", "requested_amount": 6000000.0, "requested_term_m": 12, "has_rko": false,
             "bank_turnover_month_rub": 0.0, "guarantee": false, "marketplace": true, "insurance": true,
             "subscription": false, "bki_consent": true},
  "purpose": "закупка",
  "status": "COUNTER_OFFER",
  "status_label": "Контрпредложение",
  "whose_turn": "client",
  "next_step": "Банк предлагает другие условия — примите их или отзовите заявку",
  "steps": [
    {"status": "SUBMITTED", "label": "Подана", "state": "done"},
    {"status": "DATA_CHECK", "label": "Проверка данных", "state": "done"},
    {"status": "SCORING", "label": "Скоринг", "state": "done"},
    {"status": "COUNTER_OFFER", "label": "Контрпредложение", "state": "current"},
    {"status": "SIGNING", "label": "Подписание", "state": "todo"},
    {"status": "ISSUED", "label": "Выдано", "state": "todo"}
  ],
  "created_at": "2026-10-25T17:53:41.991539+00:00",
  "updated_at": "2026-10-25T17:53:42.064824+00:00",
  "decision": {"outcome": "COUNTER", "title": "Предложим другие условия", "by": "system", "note": null,
               "reasons": [{"code": "L02", "category": "денежного потока с запасом DSCR ≥ 1,25 хватает на платёж только по этой сумме"}],
               "requests": [], "route": null},
  "offer": {"product": "express", "product_label": "экспресс-кредит без залога", "amount": 3610000, "term_m": 12,
            "rate": 0.1902649165559008, "all_in": 0.2596302352717337, "monthly_payment": 332730.89149395184},
  "documents": [],
  "sign_code": null,
  "loan": null,
  "events": [
    {"at": "2026-10-25T17:53:41.991539+00:00", "from": null, "to": "SUBMITTED", "to_label": "Подана", "actor": "client", "note": "Заявка подана, согласие на запрос в БКИ получено"},
    {"at": "2026-10-25T17:53:41.996494+00:00", "from": "SUBMITTED", "to": "DATA_CHECK", "to_label": "Проверка данных", "actor": "system", "note": "Приём и валидация: заявка полная"},
    {"at": "2026-10-25T17:53:41.998525+00:00", "from": "DATA_CHECK", "to": "SCORING", "to_label": "Скоринг", "actor": "system", "note": "ЕГРЮЛ: компания действующая; БКИ: отчёт получен; выписка: обороты сверены"},
    {"at": "2026-10-25T17:53:42.064824+00:00", "from": "SCORING", "to": "COUNTER_OFFER", "to_label": "Контрпредложение", "actor": "system", "note": "Решение по правилам кредитной политики"}
  ],
  "actions": ["accept_offer", "withdraw"]
}
```

`sign_code` заполнен только для клиента в статусе `SIGNING`. Аналитику дополнительно приходит `risk`:
`{pd, risk_class, score, approval_probability, limit, stop_factors, reasons, route_reason, approval_mode,
facts: [{key, label, value, unit}]}` (`null`, пока нет расчёта).

## ИИгорь

### `POST /api/v1/chat` (Bearer)

```json
{"persona_id": "marina", "levers": {"product": "express", "requested_amount": 6000000, "requested_term_m": 12},
 "messages": [{"role": "user", "content": "хочу на 24 месяца"}]}
```

`messages` — до 40, `content` до 4000 символов. 200:

```json
{"reply": "Для вас шанс одобрения — 84%: ... Это предварительная оценка, не решение банка.",
 "levers": {"requested_term_m": 24}, "mode": "rules"}
```

`levers` — только изменённые рычаги или `null`; `mode` — `rules` (без ключа или при ошибке/страже LLM) или `llm`.
Числа в ответе всегда из расчёта движка.
