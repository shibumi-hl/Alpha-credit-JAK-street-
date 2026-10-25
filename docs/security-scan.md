# Сканирование уязвимостей

Дата: 2026-10-25. Инструменты: trivy (image, fs, config), snyk (test, container, code).
Сырые JSON лежат в `.vuln-scan/` (в git не попадают).

## Счётчики CRITICAL / HIGH

| Поверхность | До | После |
|---|---|---|
| Образ, пакеты ОС (trivy) | 9 / 98 (Debian 12.9) | 2 / 61 (Debian 12.15), исправлений в Debian нет ни для одной |
| Образ, Python-пакеты (trivy) | 5 / 23 (все pillow 12.3.0) | 0 / 0 |
| Образ (snyk container) | 8 / 64 | не перезапускался; та же база, ожидается то же снижение |
| Репозиторий (trivy fs: зависимости, секреты, конфиги) | 0 / 0 | 0 / 0 |
| Код (snyk code), уровень error | 7 (6 Sqli, 1 PT) | 7, все ложные (см. ниже) |

MEDIUM/LOW в образе после исправления: ОС 99 / 91, Python 5 / 1.

## Группы находок

### pillow 12.3.0 - 28 CRITICAL/HIGH
- Где: `deploy/requirements-server.txt`, образ сервера.
- Вердикт: реальная уязвимая зависимость, но на сервере не нужна. Ни `api/`, ни `scoring/`, ни `scripts/` не импортируют matplotlib или PIL, optbinning тоже не импортирует matplotlib.
- Исправление: из серверных зависимостей убраны matplotlib и пакеты, которые нужны только ему: pillow, contourpy, cycler, fonttools, kiwisolver, pyparsing. Обратные зависимости проверены по метаданным venv; pillow и fonttools ещё требует pypdf, но его нет на сервере.

### Пакеты ОС Debian 12.9 - 9 CRITICAL / 98 HIGH
- Где: базовый образ `python:3.13.1-slim` (openssl, libssl3, libgnutls30, perl-base и другие).
- Вердикт: реальные, исправлены в обновлениях Debian 12.
- Исправление: в финальной стадии `Dockerfile` добавлен `apt-get upgrade`, тег Python не менялся. Осталось 2 CRITICAL (zlib1g - will_not_fix, libsqlite3-0) и 61 HIGH (util-linux, ncurses, systemd, openssl/perl и другие): у всех статус affected или fix_deferred, исправления в Debian 12 нет. Принят остаточный риск, отслеживать при обновлении базового образа.

## Snyk Code

| Правило | Где | Вердикт | Причина |
|---|---|---|---|
| python/Sqli (6, error) | `api/app.py` 220-240 | ложное | Ввод уходит в `api/conveyor.py`, там SQLAlchemy Core (`select/insert/update().where(...)`) со связанными параметрами, SQL из строк не собирается; единственный `sa.text` - константа `SELECT 1`. |
| python/PT (error) | `api/app.py` 268 | ложное | Путь SPA проходит `resolve()` и затем проверку `dist.resolve() in f.parents`: `../` и абсолютный путь дают файл вне `dist` и получают index.html. |
| python/Deserialization | `api/app.py` 106, `scripts/check_personas.py`, `scripts/score_company.py` | принято | pickle грузит `ENGINE_PATH` или модель из репозитория: это доверенный артефакт оператора, версию модели проверяет загрузчик. |
| python/PT (note, 13) | `scripts/*` | принято | CLI оператора, пути задаёт сам оператор. |
| python/Ssrf | `scripts/load_egrul.py` 41 | ложное | Фиксированный базовый URL, CLI оператора. |
| python/InsecureXmlParser | `scoring/fns.py` 40 | низкий риск | stdlib ElementTree не подгружает внешние сущности, expat в Python 3.13 защищён от раздувания сущностей; на вход идут открытые данные ФНС, которые скачал оператор. |
| NoHardcodedPasswords / HardcodedNonCryptoSecret | tests | ложное | Демо-учётки, так задумано. |
| python/InsecureHash (md5) | `scoring/realcheck.py` 27 | ложное | md5 делит ИНН на выборки и не используется для криптографии. |

## Что не запускалось
- `snyk test` (pip) упал с ошибкой «Failed to test pip project». Python-зависимости проверил trivy по образу.
- `snyk iac` не распознал compose-файл. Конфигурацию проверил `trivy config`.
