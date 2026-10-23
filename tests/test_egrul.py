import pytest

from scoring.egrul import event_date, kind, parse_extract, role

# Синтетические фрагменты текста выписки ЕГРЮЛ (структура как в настоящих, лица вымышленные)
STRUCK = ("Сведения о прекращении юридического лица 15 Способ прекращения Исключение юридического лица из ЕГРЮЛ "
          "в связи с наличием оснований, предусмотренных статьей 21.3 Федерального закона от 08.08.2001 № 129-ФЗ "
          "16 Дата прекращения 14.10.2026 17 Наименование органа")
LIQ_STATE = ("Сведения о состоянии юридического лица 14 Состояние Находится в стадии ликвидации 15 Срок ликвидации "
             "08.06.2027 16 ГРН и дата внесения в ЕГРЮЛ записи, содержащей указанные сведения 2267801837884 17.06.2026 "
             "Сведения о лице, имеющем право без доверенности 18 Фамилия Иванов")
BANKRUPT = ("Сведения о состоянии юридического лица 14 Состояние Юридическое лицо признано несостоятельным (банкротом) и "
            "в отношении него открыто конкурсное производство 15 ГРН и дата внесения в ЕГРЮЛ записи, содержащей "
            "указанные сведения 2237700111222 05.03.2026 Сведения о лице")
MERGED = ("Сведения о прекращении юридического лица 15 Способ прекращения Прекращение деятельности юридического лица "
          "путем реорганизации в форме присоединения 16 Дата прекращения 20.07.2026 17 Наименование")
COURT = ("Сведения о прекращении юридического лица 15 Способ прекращения Прекращение деятельности юридического лица в "
         "связи с его ликвидацией на основании определения арбитражного суда о завершении конкурсного производства "
         "16 Дата прекращения 11.02.2026 17")


def test_termination_method_and_date():
    rec = parse_extract(STRUCK)
    assert rec["method"].startswith("Исключение юридического лица из ЕГРЮЛ") and "21.3" in rec["method"]
    assert rec["end_date_pdf"] == "14.10.2026"


def test_state_and_its_record_date_without_people():
    rec = parse_extract(LIQ_STATE)
    assert rec["state"] == "Находится в стадии ликвидации" and rec["state_date"] == "17.06.2026"
    assert "Иванов" not in str(rec)


@pytest.mark.parametrize("text,expected", [(STRUCK, "struck_off"), (LIQ_STATE, "liquidation"), (BANKRUPT, "bankruptcy"),
                                           (MERGED, "reorganization"), (COURT, "bankruptcy"), ("", "other")])
def test_kind_of_event(text, expected):
    assert kind(parse_extract(text)) == expected


def test_event_date_prefers_termination_then_state():
    assert event_date(parse_extract(STRUCK)) == "2026-10-14"
    assert event_date(parse_extract(BANKRUPT)) == "2026-03-05"
    assert event_date({}) is None


def test_role_drops_the_name():
    assert role("ЛИКВИДАТОР: Петров Пётр Петрович") == "ЛИКВИДАТОР"
    assert role("ГЕНЕРАЛЬНЫЙ ДИРЕКТОР") == "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР" and role(None) == ""
