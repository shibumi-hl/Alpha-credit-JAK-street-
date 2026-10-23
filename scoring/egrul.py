"""
Выписка ЕГРЮЛ → способ прекращения, состояние, даты и вид события (реальная метка для проверки модели).

Хранится только то, что нужно для метки: способ прекращения, состояние, даты, роль руководителя без ФИО.
Выписка (PDF) разбирается в памяти и не сохраняется - в ней персональные данные.
"""
import io
import re

BANKRUPTCY, STRUCK_OFF, LIQUIDATION, REORGANIZATION, OTHER = (
    "bankruptcy", "struck_off", "liquidation", "reorganization", "other")
DISTRESS = (BANKRUPTCY, STRUCK_OFF)  # события-неплатёжеспособность: банкротство и исключение налоговой

_METHOD = re.compile(r"Способ прекращения (.+?) \d{1,3} Дата прекращения (\d\d\.\d\d\.\d{4})")
_STATE = re.compile(r"Сведения о состоянии юридического лица \d{1,3} Состояние (.+?) \d{1,3} (?:Срок|ГРН|Сведения)")
_STATE_DATE = re.compile(r"содержащей указанные сведения \d{13,15} (\d\d\.\d\d\.\d{4})")


def pdf_text(pdf: bytes) -> str:
    import pypdf  # только для загрузчика; разбор текста без него
    return " ".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def parse_extract(text: str) -> dict:
    """Способ и дата прекращения, состояние и дата записи о нём - из текста выписки."""
    t = re.sub(r"\s+", " ", text or "")
    out = {}
    m = _METHOD.search(t)
    if m:
        out["method"], out["end_date_pdf"] = m.group(1).strip(), m.group(2)
    m = _STATE.search(t)
    if m:
        out["state"] = m.group(1).strip()
        d = _STATE_DATE.search(t[m.end():m.end() + 400])
        out["state_date"] = d.group(1) if d else None
    return out


def role(head: str | None) -> str:
    """«ЛИКВИДАТОР: Фамилия Имя» → «ЛИКВИДАТОР»: ФИО не храним."""
    return (head or "").split(":")[0].strip()


def kind(rec: dict) -> str:
    method, state = str(rec.get("method") or ""), str(rec.get("state") or "")
    if "несостоят" in state or "арбитражного суд" in method:
        return BANKRUPTCY
    if method.startswith("Исключение"):
        return STRUCK_OFF
    if "реорганизац" in method.lower() or "реорганизац" in state:
        return REORGANIZATION
    if "Ликвидация" in method or "ликвидации" in state:
        return LIQUIDATION
    return OTHER


def _iso(d) -> str | None:
    return f"{d[6:10]}-{d[3:5]}-{d[:2]}" if isinstance(d, str) and re.fullmatch(r"\d\d\.\d\d\.\d{4}", d) else None


def event_date(rec: dict) -> str | None:
    """Дата события: прекращение, иначе запись о состоянии (ликвидация, банкротство, реорганизация)."""
    return _iso(rec.get("end_date_pdf")) or _iso(rec.get("end_date")) or _iso(rec.get("state_date"))
