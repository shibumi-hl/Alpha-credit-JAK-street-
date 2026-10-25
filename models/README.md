# Обученный движок скоринга

`engine.pkl` — все модели движка одним файлом (`scoring.whatif.Engine`): PD-скоркарта, модель шанса одобрения,
кредитная политика, параметры цены и G-кривая Мосбиржи. На нём работает песочница кредита
(https://alfahack.artsch.dev) и `scripts/check_personas.py`.

| | |
|---|---|
| Дата модели (`asof`) | 2026-10-25, данные не позже D-1 |
| Обучающая выборка | 19 600 юрлиц из открытых данных ФНС и отчётности ГИР БО; метка дефолта, БКИ и поля заявки синтетические (`scoring/synth.py`) |
| PD-скоркарта | 12 факторов, Gini 0,602 ± 0,027 по 5 фолдам (`reports/scorecard_2026-10-25_irb.md`) |
| Модель одобрения | версия признаков 4, 10 000 решений, Gini 0,960 ± 0,008 |
| Капитал | ПВР по 845-П (`config/pricing.json`, `"approach": "irb"`) |
| SHA-256 | `75cd52d0d68d3cc0e77801499976c67bd0184e9d033757906b2d29e01d9f0240` |

В файле только параметры моделей: бины, коэффициенты, счётчики, конфиги и публичная G-кривая. ИНН и строк выборки в
нём нет.

## Как пользоваться

```python
from scoring.whatif import Engine, evaluate, whatif
engine = Engine.load("models/engine.pkl")
evaluate(engine, app)   # app - заявка: поля как в data/scoring/train.csv или demo/personas (через api.personas.application)
```

```
py scripts/check_personas.py   # исходы демо-компаний и числа Марины: data/scoring/engine.pkl, без него - этот файл
```

API песочницы и `scripts/deploy.sh` берут модель так же: `ENGINE_PATH`, иначе свежеобученная
`data/scoring/engine.pkl`, иначе этот файл.

## Ограничения

- Это pickle: загрузка выполняет код. Грузите только файл из этого репозитория, сверив SHA-256.
- Грузится только на тех же версиях библиотек, что при обучении: `deploy/requirements-server.txt` (numpy 2.5.3,
  pandas 3.0.5, scikit-learn 1.9.1, scipy 1.18.1, optbinning 1.0.0). Модель другой версии признаков `Engine.load`
  не загрузит и попросит переобучить.
- Переобучили (`py scripts/train_scorecard.py --capital-approach both`) — скопируйте новый
  `data/scoring/engine.pkl` сюда, обновите таблицу выше и закоммитьте вместе с кодом моделей.
