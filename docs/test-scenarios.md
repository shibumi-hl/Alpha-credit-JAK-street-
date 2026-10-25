# Тестовые сценарии

Все сценарии работают на синтетических демо-компаниях (`demo/personas/`) и обученном движке `models/engine.pkl`.
Учётки: клиент `client/client`, аналитик `analyst/analyst`. Через API те же шаги собраны в
`docs/postman_collection.json` (папка «Заявки», подпапки T1-T6; T7 — в «Компания и лента»).

Между автоматическими шагами конвейера пауза `PIPELINE_STEP_DELAY` (1,2 с): после подачи заявка за 3–4 секунды
проходит Подана → Проверка данных → Скоринг и останавливается на ходе человека.

## Сценарии T1-T7

| # | Сценарий | Демо-компания (ИНН) | Шаги в интерфейсе | Шаги через API | Ожидаемый результат |
|---|---|---|---|---|---|
| T1 | Одобрение | ООО «Тёплый дом», `marina` (0010000017) | вход «Марина Соколова» → ИНН 0010000017 → «Дать согласие на запрос в БКИ» → сценарий «Взять на 24 месяца» → «Применить» → «Подать заявку» → согласие → «Отправить в банк» → «Принять предложение» → код → «Подписать» | login client → `POST /applications` marina с `requested_term_m: 24` → `GET /applications/{id}` → `accept_offer` → `sign` с `sign_code` | песочница «Одобрим 6 млн ₽ на 24 мес.»; статусы SUBMITTED → DATA_CHECK → SCORING → APPROVED (offer 6 000 000) → SIGNING → ISSUED, карточка кредита |
| T2 | Контрпредложение | `marina` (0010000017), 6 млн ₽ на 12 мес. | то же без смены срока: после согласия «Можем выдать 3,61 млн ₽» → подача → «Принять предложение» → «Подписать» | `POST /applications` marina (рычаги по умолчанию) → `GET` → `accept_offer` → `sign` | COUNTER_OFFER, `offer.amount` 3 610 000, причина L02 (денежный поток при DSCR ≥ 1,25) → SIGNING → ISSUED; журнал из 6 событий; `withdraw` после выдачи — 409 |
| T3 | Дозапрос документов | ООО «Стройресурс», `docs` (0040000046) | ИНН 0040000046 → «Нужны документы» → подача → в трекере «Загрузить документы» | `POST /applications` docs → `GET` → `upload_documents` → `GET` | NEEDS_DATA со списком `documents` (ход клиента) → после загрузки DATA_CHECK → SCORING → решение движка (COUNTER_OFFER); документы в статусе `uploaded` |
| T4 | Стоп-фактор | ООО «Транзит-М», `overdue` (0050000052) | ИНН 0050000052 → «Сейчас не сможем…» → подача | `POST /applications` overdue → `GET` | REJECTED сразу после скоринга, без аналитика; причина — стоп-фактор S01; `actions` пустой |
| T5 | Решение аналитика | ООО «Северный хлеб», `bakery` (0020000023), залог 15 млн ₽ | клиент подаёт заявку → «У аналитика» → выход → вход «Аналитик МСБ» → `#/analyst` → карточка (факты, PD, класс, балл, шанс, причина маршрута) → «Одобрить» с комментарием | client: `POST /applications` bakery → `GET` (ANALYST); client `approve` → 403; analyst: `GET /applications?status=ANALYST` → `GET /applications/{id}` (есть `risk`) → `approve` без `note` → 422 → `approve` с `note` | ANALYST (причина маршрута: залоговый кредит), затем APPROVED, `decision.by = analyst`, `offer.amount > 0` |
| T6 | Сбой БКИ | ООО «Ромашка», `romashka` (0060000005), `mock.bki_fail` | подача → трекер «У аналитика» | `POST /applications` romashka → `GET` | на шаге DATA_CHECK мок БКИ не отвечает → ANALYST, в журнале «Техническая ошибка: бюро кредитных историй (БКИ) не ответило после 3 попыток» |
| T7 | Неверный ИНН | — | на онбординге ввести 1234567890 | `GET /companies/1234567890`; `GET /companies/0000000000` | 422 «ИНН юрлица — 10 цифр с верной контрольной цифрой»; несуществующий корректный ИНН — 404 «Не нашли компанию по ИНН» |

## Дополнительные проверки

| Проверка | Как | Ожидание |
|---|---|---|
| Вход | `POST /auth/login` с неверным паролем; запрос без токена; поддельный токен | 401 |
| Идемпотентность | два `POST /applications` с одним `Idempotency-Key` | один и тот же `id` |
| Дубль активной заявки | второй `POST` той же компании и продукта без ключа | 409 |
| Изоляция клиентов | `client2` читает заявку `client` | 404 |
| Согласие на БКИ | `POST /applications` с `bki_consent: false` | 422 |
| Отзыв | `withdraw` сразу после подачи (`bakery`) | WITHDRAWN, `actions` пустой |
| Персональная лента | `GET /news?persona_id=marina` и `docs` | разные наборы новостей, у каждой `why` |
| ИИгорь без ключа | `POST /chat` «хочу на 24 месяца» | `mode: rules`, `levers: {requested_term_m: 24}`, текст с оговоркой «Это предварительная оценка, не решение банка.» |

## Автоматические тесты

### Бэкенд, `tests/test_conveyor.py` (через HTTP, SQLite, `PIPELINE_STEP_DELAY=0`)

| Тест | Что проверяет |
|---|---|
| `test_login_rejects_wrong_password_and_requires_token` | 401 на неверный пароль, без токена, с поддельным токеном |
| `test_t2_counter_offer_then_sign_and_issue` | T2 до ISSUED, 3 610 000 и L02, неверный код подписи — 422, журнал, 409 после выдачи |
| `test_t1_approve_on_24_months` | T1: APPROVED на 6 000 000 |
| `test_t3_documents_requested_then_uploaded` | T3: NEEDS_DATA → загрузка → решение |
| `test_t4_stop_factor_rejects_without_analyst` | T4: REJECTED со стоп-фактором S.. |
| `test_t5_secured_goes_to_analyst_who_decides` | T5: очередь, 403 клиенту, обязательный комментарий, решение аналитика |
| `test_t6_bki_failure_routes_to_analyst_as_technical_error` | T6: сбой БКИ → ANALYST |
| `test_t7_wrong_inn` | T7: 422, 404 и успешный поиск по ИНН |
| `test_idempotency_duplicates_and_ownership` | идемпотентность, 409 на дубль, 404 чужому клиенту, 422 без согласия |
| `test_withdraw_before_decision` | отзыв до решения |
| `test_news_is_personal` | лента различается по компаниям |

Также `tests/test_igor.py` (правила ИИгоря, страж чисел LLM, откат при ошибке), `tests/test_api.py`,
`tests/test_personas.py` и тесты движка (`test_scorecard.py`, `test_credit.py`, `test_whatif.py` и др.).

### Фронт, vitest (`web/src/**/*.test.ts(x)`)

`pages/Tracker.test.tsx`, `components/DecisionCard.test.tsx`, `components/LeversPanel.test.tsx`,
`lib/schemas.test.ts`, `lib/auth.test.ts`, `lib/store.test.ts`, `lib/decision.test.ts`, `lib/curve.test.ts`,
`lib/format.test.ts`, `lib/hints.test.ts`.

### E2E, Playwright (`web/e2e/golden.spec.ts`, десктоп и мобильный профиль)

- «Марина: от предоценки до одобрения 6 млн» — согласие БКИ → 3,61 млн → «Взять на 24 месяца» → 6 млн → отмена.
- «все демо-компании открываются со своим исходом и без горизонтальной прокрутки».
- «Марина: подача, трекер, подписание до «Выдано»».

## Как запустить

```
python -m pytest -q                       # все тесты бэкенда
python -m pytest -q tests/test_conveyor.py  # только конвейер T1-T7
cd web && npm ci && npm test              # vitest
# e2e: в одном терминале API, в другом Vite, затем Playwright
uvicorn --factory api.app:create_app --port 3100
cd web && npm run dev
cd web && npx playwright test
```

Ручной прогон через Postman: импортировать `docs/postman_collection.json`, при необходимости поменять `baseUrl`,
запустить Collection Runner по папкам по порядку. Запросы чтения заявки ждут 5 с в pre-request, чтобы конвейер
успел дойти до решения.
