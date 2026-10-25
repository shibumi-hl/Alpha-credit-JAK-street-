# Alpha credit

Скоринг МСБ на реальных юрлицах из открытых данных ФНС и ГИР БО: PD-скоркарта, шанс одобрения, кредитная
логика, risk-based ставка с капиталом по ПВР (845-П), ПСК и what-if.

## Commands
- Python: `py` (команда `python` на этой машине — заглушка Microsoft Store)
- Install: `py -m pip install -r requirements.txt -r requirements-dev.txt`
- Test: `py -m pytest -q`
- Данные: `py scripts/load_moex_gcurve.py`, `py scripts/load_fns_opendata.py`, `py scripts/load_girbo.py`, `py scripts/load_egrul.py`, `py scripts/calibrate_synth.py`
- Модели: `py scripts/build_scoring_sample.py`, `py scripts/train_scorecard.py --capital-approach both`
- В PowerShell перед скриптами с русским выводом: `$env:PYTHONIOENCODING='utf-8'`
- Песочница: API `py -m uvicorn --factory api.app:create_app --port 3100` (в worktree порт 3100 + `.wt-offset`), фронт `cd web; npm run dev`
- Фронт: `cd web; npm test`, `npm run typecheck`, `npm run build`, e2e `npx playwright test` (подняты API и Vite)
- Демо-компании на модели: `py scripts/check_personas.py`; деплой: `bash scripts/deploy.sh`

## Rules
- `data/` не коммитится (выборка ФНС, кэш ГИР БО, модели).
- Оценка на дату D использует данные не позже D-1 (без заглядывания в будущее).
- Только юрлица (ИНН из 10 цифр); ИП и ФИО не хранятся.
- Фикстуры тестов синтетические, кроме публичных данных G-кривой Мосбиржи.
