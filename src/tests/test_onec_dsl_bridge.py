from src.infra.onec.dsl_bridge import meta_to_artifacts
from src.infra.onec.module_transform import normalize_module_text, sanitize_imported_module_text
from src.infra.onec.onec_requisites_parser import (
    OneCMetaObject,
    OneCRequisite,
    OneCTabularPart,
    OneCTabularColumn,
)
from src.dsl.api import parse_dsl
from src.dsl.compiler import compile_module


def test_meta_to_artifacts_catalog_uk_en() -> None:
    obj = OneCMetaObject(
        obj_type="catalog",
        name="Контрагенты",
        synonyms={"ru": "Контрагенты", "uk": "Контрагенти"},
        uuid="u-1",
        origin_path="Catalogs/Контрагенты.xml",
        requisites=[
            OneCRequisite(
                name="Код",
                synonyms={"ru": "Код"},
                mp_type="string",
                ref_name=None,
                raw_type="xs:string",
                uuid="r-1",
            )
        ],
        tabular_parts=[
            OneCTabularPart(
                name="Контакты",
                synonyms={"ru": "Контакты"},
                uuid="tp-1",
                columns=[
                    OneCTabularColumn(
                        name="Телефон",
                        synonyms={"ru": "Телефон"},
                        mp_type="string",
                        ref_name=None,
                        raw_type="xs:string",
                        uuid="c-1",
                    )
                ],
            )
        ],
    )
    arts = meta_to_artifacts(obj, languages=("uk", "en"))
    assert len(arts) == 2
    uk = next(x for x in arts if x.language == "uk")
    en = next(x for x in arts if x.language == "en")
    assert "Довідник" in uk.text
    assert "Catalog" in en.text
    assert "табличнаЧастина" in uk.text
    assert "tablePart" in en.text


def test_normalize_module_text_preserves_string_and_comment() -> None:
    src = 'Если Истина Тогда\n    Сообщить("Если внутри строки");\n    \' Если в комментарии\n    // Возврат в комментарии\nКонецЕсли\n'
    res = normalize_module_text(src, language="uk")
    assert "Якщо Істина Тоді" in res.text
    assert '"Если внутри строки"' in res.text
    assert "' Если в комментарии" in res.text
    assert "// Возврат в комментарии" in res.text
    assert "КінецьЯкщо" in res.text


def test_sanitize_imported_module_text_removes_serialized_1c_artifacts() -> None:
    src = (
        "\ufeff////////////////////////////////////////////////////////////////////////////////\n"
        "00000018 00000018 7fffffff\n"
        "\ufffdB|\ufffdMB\ufffdtext\n"
        "#Область ПрограммныйИнтерфейс\n"
        "Процедура Тест() Экспорт\n"
        "КонецПроцедуры\n"
    )

    cleaned = sanitize_imported_module_text(src)

    assert "00000018 00000018 7fffffff" not in cleaned
    assert "\ufffd" not in cleaned
    assert cleaned.lstrip().startswith("////////////////////////////////////////////////////////////////////////////////")
    assert "Процедура Тест() Экспорт" in cleaned


def test_normalize_module_text_ukrainian_to_english() -> None:
    src = "Якщо Істина Тоді\nКінецьЯкщо\n"
    res = normalize_module_text(src, language="en")
    assert res.text == "If True Then\nEndIf\n"


def test_normalize_module_text_english_to_ukrainian() -> None:
    src = "If True Then\nElseIf False Then\nEndIf\n"
    res = normalize_module_text(src, language="uk")
    assert res.text == "Якщо Істина Тоді\nІнакшеЯкщо Хибність Тоді\nКінецьЯкщо\n"


def test_normalize_module_text_russian_to_ukrainian() -> None:
    src = "Если Истина Тогда\n#Область Тест\nКонецЕсли\n#КонецОбласти\n"
    res = normalize_module_text(src, language="uk")
    assert res.text == "Якщо Істина Тоді\n#Область Тест\nКінецьЯкщо\n#КінецьОбласті\n"


def test_normalize_module_text_russian_to_english() -> None:
    src = "Если Ложь Тогда\nИначеЕсли Истина Тогда\nКонецЕсли\n"
    res = normalize_module_text(src, language="en")
    assert res.text == "If False Then\nElsIf True Then\nEndIf\n"


def test_normalize_module_text_translates_russian_builtins_to_ukrainian() -> None:
    src = """
    Функция Main() Экспорт
        Данные = Новый Структура();
        Данные.Вставить("Ключ", СтрЗаменить(Лев("abcd", 2), "ab", "AB"));
        Возврат ЗначениеЗаполнено(Данные.Получить("Ключ")) И Не ПустаяСтрока(Данные.Получить("Ключ"));
    КонецФункции
    """
    res = normalize_module_text(src, language="uk")
    assert "Новий Структура()" in res.text
    assert 'Данные.Вставити("Ключ", СтрЗамінити(Лів("abcd", 2), "ab", "AB"))' in res.text
    assert "ЗаповненеЗнч(Данные.Отримати(" in res.text
    assert "ПорожнійРядок(Данные.Отримати(" in res.text


def test_normalize_module_text_translates_russian_builtins_to_english() -> None:
    src = """
    Функция Main() Экспорт
        Данные = Новый Структура();
        Данные.Вставить("Ключ", СтрЗаменить(Лев("abcd", 2), "ab", "AB"));
        Возврат ЗначениеЗаполнено(Данные.Получить("Ключ")) И Не ПустаяСтрока(Данные.Получить("Ключ"));
    КонецФункции
    """
    res = normalize_module_text(src, language="en")
    assert "New Structure()" in res.text
    assert 'Данные.Insert("Ключ", Replace(Left("abcd", 2), "ab", "AB"))' in res.text
    assert "IsFilled(Данные.Get(" in res.text
    assert "IsBlankString(Данные.Get(" in res.text


def test_normalized_imported_bsl_fragment_parses_and_compiles_for_uk_and_en() -> None:
    src = """
    Функция Main() Экспорт
        ЗаписьЖурналаРегистрации("Событие", УровеньЖурналаРегистрации.Ошибка,,, ПодробноеПредставлениеОшибки(""));
        Сообщить(НСтр("ru='Ошибка'"
        ";uk='Помилка'"));
        Для Индекс = 1 По 2 Цикл
            Значение = Индекс;
        КонецЦикла;
        Если Индекс = 2 ИЛИ Значение = 1 Тогда
            Возврат Новый Структура();
        ИначеЕсли Индекс = 0 И Значение = 2 Тогда
            Возврат Новый Массив();
        Иначе
            Возврат Неопределено;
        КонецЕсли;
    КонецФункции
    """
    for language in ("uk", "en"):
        normalized = normalize_module_text(src, language=language)
        parsed = parse_dsl(normalized.text, language=language)
        errors = [x for x in parsed.diagnostics if x.severity == "error"]
        assert errors == [], [x.message for x in errors]
        assert parsed.program is not None
        module = compile_module(parsed.program, module_name=f"module://normalize-{language}")
        assert "Main" in module.functions
