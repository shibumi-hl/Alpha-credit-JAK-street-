"""
Конвейер заявки: хранение (SQLAlchemy, DATABASE_URL - PostgreSQL в compose, SQLite локально и в тестах), статусная
машина, автоматические шаги и действия клиента и аналитика.

Статус меняет только этот модуль. Переход атомарный: UPDATE ... WHERE status = <ожидаемый> и запись в журнал в
одной транзакции; не совпал статус - 409. Автоматические шаги (приём, проверка данных, скоринг) созревают по
next_at: их двигает фоновый воркер и чтение заявки, поэтому конвейер переживает перезапуск.

Порядок решения после скоринга: стоп-фактор → отказ; не хватает данных → дозапрос; ручной маршрут (сумма выше
полномочий автоматики, залог, сбой БКИ) → аналитик; иначе исход движка.
"""
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import HTTPException

from api import dto, mocks
from api.personas import application
from scoring.whatif import _derive, evaluate

LABELS = {"SUBMITTED": "Подана", "DATA_CHECK": "Проверка данных", "NEEDS_DATA": "Нужны данные",
          "SCORING": "Скоринг", "ANALYST": "У аналитика", "APPROVED": "Одобрено",
          "COUNTER_OFFER": "Контрпредложение", "REJECTED": "Отказ", "SIGNING": "Подписание", "ISSUED": "Выдано",
          "WITHDRAWN": "Отозвана"}
NEXT_STEP = {"SUBMITTED": "Заявка принята, проверяем комплектность", "DATA_CHECK":
             "Сверяем данные с ЕГРЮЛ и запрашиваем кредитную историю", "SCORING": "Оцениваем заявку",
             "NEEDS_DATA": "Загрузите документы из списка — срок рассмотрения на паузе",
             "ANALYST": "Заявку смотрит специалист, до 1 рабочего дня",
             "APPROVED": "Примите предложение, чтобы перейти к подписанию",
             "COUNTER_OFFER": "Банк предлагает другие условия — примите их или отзовите заявку",
             "REJECTED": "Сейчас не сможем выдать кредит — причина и что изменить ниже",
             "SIGNING": "Подпишите документы кодом с экрана", "ISSUED": "Деньги зачислены на расчётный счёт",
             "WITHDRAWN": "Вы отозвали заявку"}
AUTO = ("SUBMITTED", "DATA_CHECK", "SCORING")
CLIENT_TURN = ("NEEDS_DATA", "APPROVED", "COUNTER_OFFER", "SIGNING")
TERMINAL = ("REJECTED", "ISSUED", "WITHDRAWN")
WITHDRAWABLE = ("SUBMITTED", "DATA_CHECK", "NEEDS_DATA", "SCORING", "ANALYST", "APPROVED", "COUNTER_OFFER")
CLIENT_ACTIONS = {"upload_documents": ("NEEDS_DATA",), "accept_offer": ("APPROVED", "COUNTER_OFFER"),
                  "sign": ("SIGNING",), "withdraw": WITHDRAWABLE}
ANALYST_ACTIONS = {"approve": ("ANALYST",), "counter": ("ANALYST",), "reject": ("ANALYST",),
                   "request_info": ("ANALYST",)}
OUTCOME_STATUS = {"APPROVE": "APPROVED", "COUNTER": "COUNTER_OFFER", "REJECT": "REJECTED"}
TITLES = {"APPROVE": "Одобрено", "COUNTER": "Предложим другие условия", "REQUEST_INFO": "Нужны документы",
          "REJECT": "Сейчас не сможем"}
AUTO_MAX_AMOUNT = 10_000_000  # полномочия автоматического решения; выше - аналитик с тем же расчётом
MANUAL_PRODUCTS = ("secured",)  # залог проверяет специалист

meta = sa.MetaData()
applications = sa.Table(
    "applications", meta,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("owner", sa.String(64), nullable=False, index=True),
    sa.Column("idempotency_key", sa.String(128)),
    sa.Column("persona_id", sa.String(64), nullable=False),
    sa.Column("inn", sa.String(10), nullable=False),
    sa.Column("company_name", sa.String(255), nullable=False),
    sa.Column("product", sa.String(32), nullable=False),
    sa.Column("levers", sa.JSON, nullable=False),
    sa.Column("purpose", sa.Text, nullable=False, default=""),
    sa.Column("status", sa.String(32), nullable=False, index=True),
    sa.Column("next_at", sa.DateTime(timezone=True), index=True),
    sa.Column("facts_patch", sa.JSON, nullable=False, default=dict),
    sa.Column("evaluation", sa.JSON),
    sa.Column("decision", sa.JSON),
    sa.Column("route_reason", sa.Text),
    sa.Column("documents", sa.JSON, nullable=False, default=list),
    sa.Column("offer", sa.JSON),
    sa.Column("sign_code", sa.String(8)),
    sa.Column("loan", sa.JSON),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("owner", "idempotency_key", name="uq_owner_idempotency"),
)
# одна активная заявка на клиента, компанию и продукт - гарантирует база, а не только проверка перед вставкой
_ACTIVE = applications.c.status.not_in(("REJECTED", "ISSUED", "WITHDRAWN"))
sa.Index("uq_active_application", applications.c.owner, applications.c.persona_id, applications.c.product,
         unique=True, postgresql_where=_ACTIVE, sqlite_where=_ACTIVE)
events = sa.Table(
    "events", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("application_id", sa.String(40), sa.ForeignKey("applications.id"), nullable=False, index=True),
    sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("from_status", sa.String(32)),
    sa.Column("to_status", sa.String(32), nullable=False),
    sa.Column("actor", sa.String(16), nullable=False),
    sa.Column("note", sa.Text),
    sa.Column("correlation_id", sa.String(40), nullable=False),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(t: datetime | None) -> datetime | None:
    return t if t is None or t.tzinfo else t.replace(tzinfo=timezone.utc)  # SQLite отдаёт время без зоны


class Conveyor:
    def __init__(self, engine, personas: dict, url: str = None, delay: float = None):
        self.engine, self.personas, self.policy = engine, personas, engine.policy
        url = url or os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
        if url.startswith("sqlite:///") and not url.startswith("sqlite:///:"):
            os.makedirs(os.path.dirname(url[len("sqlite:///"):]) or ".", exist_ok=True)
        self.db = sa.create_engine(url, pool_pre_ping=True)
        meta.create_all(self.db)
        self.delay = float(os.environ.get("PIPELINE_STEP_DELAY", "1.2") if delay is None else delay)

    def ping(self) -> bool:
        try:
            with self.db.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
            return True
        except sa.exc.SQLAlchemyError:
            return False

    # --- расчёт ---------------------------------------------------------------------------------------------
    def _evaluate(self, row, levers: dict = None, bki: bool = True) -> dict:
        p = self.personas[row["persona_id"]]
        persona = {**p, "facts": {**p["facts"], **(row["facts_patch"] or {})}}
        a = application(persona, {**(levers or row["levers"]), "bki_consent": bki})
        return dto.evaluation(evaluate(self.engine, a), _derive(a, self.policy), self.policy)

    @staticmethod
    def _offer(ev: dict, term: int) -> dict:
        q = ev["pricing"] or {}
        return {"product": ev["offered_product"], "product_label": dto.PRODUCTS.get(ev["offered_product"], ""),
                "amount": int(ev["offered_amount"]), "term_m": None if ev["offered_product"] in dto.REVOLVING else term,
                "rate": q.get("rate"), "all_in": q.get("all_in"), "monthly_payment": ev["monthly_payment"]}

    @staticmethod
    def _decision(ev: dict, by: str = "system", note: str = None, outcome: str = None) -> dict:
        outcome = outcome or ev["outcome"]
        reasons = ev["stop_factors"] or ev["reasons"]
        return {"outcome": outcome, "title": TITLES[outcome], "by": by, "note": note,
                "reasons": [{"code": r["code"], "category": r["category"]} for r in reasons],
                "requests": ev["requests"], "route": ev["route"]}

    # --- переходы -------------------------------------------------------------------------------------------
    def _move(self, conn, row, to: str, actor: str, note: str = None, **changes):
        """Атомарный переход из текущего статуса строки; кто-то успел раньше - 409."""
        now = _now()
        values = {"status": to, "updated_at": now, "next_at": now + timedelta(seconds=self.delay) if to in AUTO
                  else None, **changes}
        res = conn.execute(applications.update().where(applications.c.id == row["id"],
                                                       applications.c.status == row["status"]).values(**values))
        if res.rowcount != 1:
            raise HTTPException(409, "Заявка уже изменилась — обновите страницу")
        conn.execute(events.insert().values(application_id=row["id"], at=now, from_status=row["status"],
                                            to_status=to, actor=actor, note=note,
                                            correlation_id=uuid.uuid4().hex))

    def _row(self, conn, app_id: str):
        r = conn.execute(sa.select(applications).where(applications.c.id == app_id)).mappings().first()
        if r is None:
            raise HTTPException(404, "Заявка не найдена")
        return dict(r)

    def advance(self, app_id: str) -> bool:
        """Один автоматический шаг созревшей заявки. True - статус изменился."""
        with self.db.begin() as conn:
            row = self._row(conn, app_id)
            if row["status"] not in AUTO or (_aware(row["next_at"]) or _now()) > _now():
                return False
            p = self.personas[row["persona_id"]]
            if row["status"] == "SUBMITTED":
                self._move(conn, row, "DATA_CHECK", "system", "Приём и валидация: заявка полная")
            elif row["status"] == "DATA_CHECK":
                if not mocks.bki_available(p):
                    ev = self._evaluate(row, bki=False)
                    reason = "Техническая ошибка: бюро кредитных историй (БКИ) не ответило после 3 попыток"
                    self._move(conn, row, "ANALYST", "system", reason + " — заявка передана аналитику",
                               evaluation=ev, route_reason=reason)
                else:
                    self._move(conn, row, "SCORING", "system",
                               "ЕГРЮЛ: компания действующая; БКИ: отчёт получен; выписка: обороты сверены")
            else:
                self._score(conn, row)
        return True

    def _score(self, conn, row):
        ev = self._evaluate(row)
        lv = row["levers"]
        if ev["stop_factors"]:
            self._move(conn, row, "REJECTED", "system", "Стоп-фактор: " + ev["stop_factors"][0]["category"],
                       evaluation=ev, decision=self._decision(ev, outcome="REJECT"))
        elif ev["outcome"] == "REQUEST_INFO":
            docs = [{"name": d, "status": "requested"} for d in ev["requests"]] or \
                   [{"name": "отчётность за последний год", "status": "requested"}]
            self._move(conn, row, "NEEDS_DATA", "system", "Нужны документы: " + "; ".join(d["name"] for d in docs),
                       evaluation=ev, decision=self._decision(ev), documents=docs)
        elif lv["requested_amount"] > AUTO_MAX_AMOUNT or lv["product"] in MANUAL_PRODUCTS:
            reason = ("залоговый кредит: залог проверяет специалист" if lv["product"] in MANUAL_PRODUCTS else
                      f"сумма выше полномочий автоматического решения ({AUTO_MAX_AMOUNT // 1_000_000} млн ₽)")
            self._move(conn, row, "ANALYST", "system", "Маршрут к аналитику: " + reason, evaluation=ev,
                       route_reason=reason)
        else:
            to = OUTCOME_STATUS[ev["outcome"]]
            offer = self._offer(ev, int(lv["requested_term_m"])) if to != "REJECTED" else None
            self._move(conn, row, to, "system", "Решение по правилам кредитной политики", evaluation=ev,
                       decision=self._decision(ev), offer=offer)

    def step_due(self) -> int:
        with self.db.connect() as conn:
            ids = conn.execute(sa.select(applications.c.id).where(applications.c.status.in_(AUTO),
                                                                  applications.c.next_at <= _now())).scalars().all()
        moved = 0
        for i in ids:
            try:
                moved += self.advance(i)
            except HTTPException:  # заявку успели изменить параллельно - следующий проход
                pass
        return moved

    # --- API ------------------------------------------------------------------------------------------------
    def create(self, user: dict, persona_id: str, levers: dict, purpose: str, consent: bool, key: str = None):
        if user["role"] != "client":
            raise HTTPException(403, "Подавать заявку может только клиент")
        if persona_id not in self.personas:
            raise HTTPException(404, "Нет такой демо-компании")
        if not consent:
            raise HTTPException(422, "Для подачи нужно согласие на запрос в бюро кредитных историй")
        p = self.personas[persona_id]
        try:
            return self._insert(user, persona_id, p, levers, purpose, key)
        except sa.exc.IntegrityError:  # параллельная подача: повтор с тем же ключом или вторая активная заявка
            if key:
                with self.db.connect() as conn:
                    old = conn.execute(sa.select(applications.c.id).where(
                        applications.c.owner == user["sub"], applications.c.idempotency_key == key)).scalar()
                if old:
                    return old
            raise HTTPException(409, "По этой компании и продукту уже есть заявка в работе") from None

    def _insert(self, user, persona_id, p, levers, purpose, key):
        with self.db.begin() as conn:
            if key:
                old = conn.execute(sa.select(applications.c.id).where(
                    applications.c.owner == user["sub"], applications.c.idempotency_key == key)).scalar()
                if old:
                    return old
            active = conn.execute(sa.select(applications.c.id).where(
                applications.c.owner == user["sub"], applications.c.persona_id == persona_id,
                applications.c.product == levers["product"], applications.c.status.not_in(TERMINAL))).scalar()
            if active:
                raise HTTPException(409, "По этой компании и продукту уже есть заявка в работе")
            app_id, now = "app_" + uuid.uuid4().hex[:12], _now()
            conn.execute(applications.insert().values(
                id=app_id, owner=user["sub"], idempotency_key=key, persona_id=persona_id, inn=p["inn"],
                company_name=p["name"], product=levers["product"], levers={**levers, "bki_consent": True},
                purpose=purpose or "", status="SUBMITTED", next_at=now + timedelta(seconds=self.delay),
                facts_patch={}, documents=[], created_at=now, updated_at=now))
            conn.execute(events.insert().values(application_id=app_id, at=now, from_status=None,
                                                to_status="SUBMITTED", actor="client",
                                                note="Заявка подана, согласие на запрос в БКИ получено",
                                                correlation_id=uuid.uuid4().hex))
        return app_id

    def _visible(self, conn, user: dict, app_id: str) -> dict:
        row = self._row(conn, app_id)
        if user["role"] == "client" and row["owner"] != user["sub"]:
            raise HTTPException(404, "Заявка не найдена")
        return row

    def get(self, user: dict, app_id: str) -> dict:
        with self.db.connect() as conn:
            self._visible(conn, user, app_id)
        while self.advance(app_id) and self.delay == 0:  # без задержки - сразу до хода человека
            pass
        with self.db.connect() as conn:
            row = self._visible(conn, user, app_id)
            evs = conn.execute(sa.select(events).where(events.c.application_id == app_id)
                               .order_by(events.c.id)).mappings().all()
        return self._view(row, [dict(e) for e in evs], user)

    def list(self, user: dict, status: str = None) -> list:
        self.step_due()
        q = sa.select(applications).order_by(applications.c.updated_at.desc())
        if user["role"] == "client":
            q = q.where(applications.c.owner == user["sub"])
        if status:
            q = q.where(applications.c.status == status)
        with self.db.connect() as conn:
            rows = conn.execute(q).mappings().all()
        return [{"id": r["id"], "company": {"name": r["company_name"], "inn": r["inn"]},
                 "product_label": dto.PRODUCTS.get(r["product"], r["product"]),
                 "amount": r["levers"]["requested_amount"], "term_m": r["levers"]["requested_term_m"],
                 "status": r["status"], "status_label": LABELS[r["status"]], "whose_turn": self._turn(r["status"]),
                 "updated_at": _aware(r["updated_at"]).isoformat(), "route_reason": r["route_reason"]} for r in rows]

    def latest_status(self, persona_id: str) -> str | None:
        with self.db.connect() as conn:
            return conn.execute(sa.select(applications.c.status).where(applications.c.persona_id == persona_id)
                                .order_by(applications.c.updated_at.desc()).limit(1)).scalar()

    def act(self, user: dict, app_id: str, action: str, note: str = None, amount: float = None, code: str = None):
        table = CLIENT_ACTIONS if user["role"] == "client" else ANALYST_ACTIONS
        if action not in CLIENT_ACTIONS and action not in ANALYST_ACTIONS:
            raise HTTPException(422, f"Неизвестное действие «{action}»")
        if action not in table:
            raise HTTPException(403, "Это действие недоступно вашей роли")
        if user["role"] == "analyst" and not (note or "").strip():
            raise HTTPException(422, "Решение аналитика требует комментария")
        with self.db.begin() as conn:
            row = self._visible(conn, user, app_id)
            if row["status"] not in table[action]:
                raise HTTPException(409, f"В статусе «{LABELS[row['status']]}» это действие недоступно")
            getattr(self, "_" + action)(conn, row, note=note, amount=amount, code=code)
        return self.get(user, app_id)

    # действия клиента
    def _upload_documents(self, conn, row, **_):
        docs = [{**d, "status": "uploaded"} for d in row["documents"]]
        patch = self.personas[row["persona_id"]].get("after_docs", {})
        self._move(conn, row, "DATA_CHECK", "client", "Документы загружены: " + "; ".join(d["name"] for d in docs),
                   documents=docs, facts_patch={**(row["facts_patch"] or {}), **patch})

    def _accept_offer(self, conn, row, **_):
        self._move(conn, row, "SIGNING", "client", "Клиент принял условия", sign_code=f"{secrets.randbelow(10000):04d}")

    def _sign(self, conn, row, code=None, **_):
        if not code or code.strip() != row["sign_code"]:
            raise HTTPException(422, "Код подписи не совпадает")
        o = row["offer"]
        loan = {"number": f"КД-{_now():%Y}-{row['id'][-6:].upper()}", "amount": o["amount"], "term_m": o["term_m"],
                "rate": o["rate"], "monthly_payment": o["monthly_payment"], "product_label": o["product_label"],
                "issued_at": _now().isoformat(), "account": "40702810" + "".join(c for c in row["inn"]) + "01"}
        self._move(conn, row, "ISSUED", "client", "Документы подписаны простой электронной подписью (мок), "
                                                  "деньги зачислены", loan=loan, sign_code=None)

    def _withdraw(self, conn, row, **_):
        self._move(conn, row, "WITHDRAWN", "client", "Клиент отозвал заявку")

    # действия аналитика
    def _approve(self, conn, row, note=None, **_):
        ev = self._evaluate(row)  # аналитик подтвердил данные, в том числе кредитную историю вручную
        if ev["stop_factors"] or ev["outcome"] not in ("APPROVE", "COUNTER"):
            raise HTTPException(409, "Движок не даёт условий для одобрения: " + "; ".join(
                r["category"] for r in (ev["stop_factors"] or ev["reasons"])[:2]) +
                " — выберите отказ или дозапрос")
        to = OUTCOME_STATUS[ev["outcome"]]
        self._move(conn, row, to, "analyst", note, evaluation=ev, offer=self._offer(ev, row["levers"]["requested_term_m"]),
                   decision=self._decision(ev, by="analyst", note=note))

    def _counter(self, conn, row, note=None, amount=None, **_):
        if not amount or amount <= 0:
            raise HTTPException(422, "Укажите сумму контрпредложения")
        levers = {**row["levers"], "requested_amount": float(amount)}
        ev = self._evaluate(row, levers)
        if ev["outcome"] != "APPROVE":
            raise HTTPException(409, f"На {amount:,.0f} ₽ движок не одобряет — лимит {ev['limit']:,.0f} ₽"
                                .replace(",", " "))
        self._move(conn, row, "COUNTER_OFFER", "analyst", note, evaluation=ev,
                   offer=self._offer(ev, row["levers"]["requested_term_m"]),
                   decision=self._decision(ev, by="analyst", note=note, outcome="COUNTER"))

    def _reject(self, conn, row, note=None, **_):
        ev = row["evaluation"] or self._evaluate(row)
        self._move(conn, row, "REJECTED", "analyst", note, decision=self._decision(ev, by="analyst", note=note,
                                                                                    outcome="REJECT"))

    def _request_info(self, conn, row, note=None, **_):
        docs = [{"name": note.strip(), "status": "requested"}]
        self._move(conn, row, "NEEDS_DATA", "analyst", note, documents=docs)

    # --- представление -------------------------------------------------------------------------------------
    @staticmethod
    def _turn(status: str) -> str | None:
        return None if status in TERMINAL else "client" if status in CLIENT_TURN else "bank"

    @staticmethod
    def _steps(status: str, visited: list) -> list:
        seen = lambda s: s in visited or s == status  # noqa: E731
        path = ["SUBMITTED", "DATA_CHECK", *(["NEEDS_DATA"] if seen("NEEDS_DATA") else []), "SCORING",
                *(["ANALYST"] if seen("ANALYST") else [])]
        decision = next((s for s in ("APPROVED", "COUNTER_OFFER", "REJECTED") if s in visited or s == status), None)
        tail = [decision or "APPROVED"] + ([] if decision == "REJECTED" else ["SIGNING", "ISSUED"])
        if status == "WITHDRAWN":
            path = [s for s in path if s in visited] + ["WITHDRAWN"]
            tail = []
        steps = path + tail
        cur = len(steps) - 1 - steps[::-1].index(status) if status in steps else len(steps)
        out = [{"status": s, "label": "Решение" if s == "APPROVED" and decision is None else LABELS[s],
                "state": "done" if i < cur else "current" if i == cur else "todo"} for i, s in enumerate(steps)]
        if status in TERMINAL:
            out[-1]["state"] = "done"
        return out

    def _view(self, row: dict, evs: list, user: dict) -> dict:
        status, ev = row["status"], row["evaluation"]
        table = CLIENT_ACTIONS if user["role"] == "client" else ANALYST_ACTIONS
        actions = [a for a, allowed in table.items() if status in allowed]
        if user["role"] == "client" and status == "NEEDS_DATA":
            actions = ["upload_documents"] + [a for a in actions if a != "upload_documents"]
        out = {"id": row["id"], "persona_id": row["persona_id"],
               "company": {"name": row["company_name"], "inn": row["inn"]}, "product": row["product"],
               "product_label": dto.PRODUCTS.get(row["product"], row["product"]), "levers": row["levers"],
               "purpose": row["purpose"], "status": status, "status_label": LABELS[status],
               "whose_turn": self._turn(status), "next_step": NEXT_STEP[status],
               "steps": self._steps(status, [e["to_status"] for e in evs]),
               "created_at": _aware(row["created_at"]).isoformat(), "updated_at": _aware(row["updated_at"]).isoformat(),
               "decision": row["decision"], "offer": row["offer"], "documents": row["documents"] or [],
               "sign_code": row["sign_code"] if user["role"] == "client" and status == "SIGNING" else None,
               "loan": row["loan"],
               "events": [{"at": _aware(e["at"]).isoformat(), "from": e["from_status"], "to": e["to_status"],
                           "to_label": LABELS[e["to_status"]], "actor": e["actor"], "note": e["note"]} for e in evs],
               "actions": actions}
        if user["role"] == "analyst":
            p = self.personas[row["persona_id"]]
            facts = {**p["facts"], **(row["facts_patch"] or {})}
            out["risk"] = None if ev is None else {
                "pd": ev["pd"], "risk_class": ev["risk_class"], "score": ev["score"],
                "approval_probability": ev["approval_probability"], "limit": ev["limit"],
                "stop_factors": ev["stop_factors"], "reasons": ev["reasons"], "route_reason": row["route_reason"],
                "approval_mode": ev["approval_mode"],
                "facts": [{"key": k, "label": label, "value": facts[k], "unit": unit} for k, label, unit in dto.FACTS]}
        return json.loads(json.dumps(out, default=float))
