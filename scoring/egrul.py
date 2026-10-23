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

_METHOD = re.compile(r"Способ прекращения (.{1,300}?) \d{1,3} Дата прекращения (\d\d\.\d\d\.\d{4})")
# состояние - до следующей строки таблицы («N Срок/ГРН») или до следующего раздела («Сведения…»), не дальше 300 знаков
_STATE = re.compile(r"Сведения о состоянии юридического лица \d{1,3} Состояние (.{1,300}?)(?: \d{1,3} (?:Срок|ГРН)| Сведения|$)")
_STATE_DATE = re.compile(r"содержащей указанные сведения \d{13,15} (\d\d\.\d\d\.\d{4})")
# колонтитул страницы выписки: «Страница 2 из 5 Выписка из ЕГРЮЛ 23.10.2026 09:56 ОГРН 1222300057044»
_FOOTER = re.compile(r" ?Страница \d+ из(?: \d+)? Выписка из ЕГРЮЛ \d\d\.\d\d\.\d{4} \d\d:\d\d ОГРН \d{13}(?: \d{1,3}(?= \d{1,3} ))?")


class PdfError(ValueError):
    """Выписку не удалось разобрать (битый или чужой PDF)."""


def pdf_text(pdf: bytes, max_bytes: int = 20_000_000) -> str:
    import pypdf  # только для загрузчика; разбор текста без него
    if len(pdf) > max_bytes:
        raise PdfError(f"выписка больше {max_bytes} байт")
    try:
        return " ".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    except pypdf.errors.PyPdfError as e:
        raise PdfError(str(e)) from e


def parse_extract(text: str) -> dict:
    """Способ и дата прекращения, состояние и дата записи о нём - из текста выписки."""
    t = _FOOTER.sub("", re.sub(r"\s+", " ", text or ""))
    out = {}
    m = _METHOD.search(t)
    if m:
        out["method"], out["end_date_pdf"] = m.group(1).strip(), m.group(2)
    m = _STATE.search(t)
    if m:
        out["state"] = m.group(1).strip()
        rest = t[m.end(1):]
        nxt = rest.find("Сведения")  # дата берётся только из строк самого раздела о состоянии
        d = _STATE_DATE.search(rest[:nxt if nxt >= 0 else 400][:400])
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
