from __future__ import annotations

from src.dsl.ast import Literal, NameExpr, NewExpr, ReturnStmt, UnaryExpr
from src.dsl.languages import MIXED_PROFILE
from src.dsl.parser import parse
from src.dsl import parse_dsl


def test_parse_uk_catalog_and_form_ok() -> None:
    text = """
    довідник Номенклатура {
      реквізити: Код: String, Найменування: String
    }

    форма Номенклатура.ФормаСписку {
      таблиця: Код, Найменування
    }
    """
    res = parse_dsl(text, language="uk")
    assert res.program is not None
    errors = [d for d in res.diagnostics if d.severity == "error"]
    assert not errors


def test_parse_en_document_ok() -> None:
    text = """
    document Invoice {
      fields: Id: String, Total: Number
    }
    """
    res = parse_dsl(text, language="en")
    assert res.program is not None
    assert not [d for d in res.diagnostics if d.severity == "error"]


def test_parse_mixed_bsl_supports_skipped_args_and_adjacent_strings() -> None:
    text = """
    #Область Test
    Процедура Тест() Экспорт
        ЗаписьЖурналаРегистрации(Событие, Уровень,,, Подробно);
        Сообщить(НСтр("ru='Ошибка'"
        ";uk='Помилка'"));
    КонецПроцедуры
    #КонецОбласти
    """
    program, diags = parse(text, MIXED_PROFILE)
    assert program is not None
    assert not [d for d in diags if d.severity == "error"]


def test_parse_mixed_bsl_supports_keyword_like_names_and_ternary() -> None:
    text = """
    Процедура Тест() Экспорт
        Запрос.Выполнить().Выбрать();
        Объект.Удалить();
        Реквизиты = Новый Массив;
        Таблица = Значения[Ключ].Выгрузить();
        Возврат ?(Истина, "A", "B");
    КонецПроцедуры
    """
    program, diags = parse(text, MIXED_PROFILE)
    assert program is not None
    assert not [d for d in diags if d.severity == "error"]


def test_parse_mixed_bsl_preserves_declaration_annotations() -> None:
    text = """
    &НаКлиенте
    Перем ClientState;
    #Область ClientHandlers
    &НаКлиенте
    &Перед("ExistingHandler")
    Процедура Тест() Экспорт
    КонецПроцедуры
    #КонецОбласти
    """

    program, diags = parse(text, MIXED_PROFILE)

    assert program is not None
    assert not [d for d in diags if d.severity == "error"]
    procedure = program.procedures()[0]
    assert [item.name for item in procedure.annotations] == ["НаКлиенте", "Перед"]
    assert procedure.annotations[1].args[0].value == "ExistingHandler"
    variable = program.var_decls()[0]
    assert [item.name for item in variable.annotations] == ["НаКлиенте"]


def test_parse_mixed_bsl_ignores_region_compatibility_annotation() -> None:
    program, diags = parse(
        "&КонецОбласти\n#КонецОбласти\nПроцедура Test()\nКонецПроцедуры",
        MIXED_PROFILE,
    )

    assert program is not None
    assert not [item for item in diags if item.severity == "error"]
    assert len(program.procedures()) == 1


def test_parse_mixed_bsl_supports_compile_directive_inside_expression() -> None:
    source = """
    Функция Main()
        Если Server
        #Если ТолстыйКлиент Тогда
            Или FileDatabase
        #КонецЕсли
        Тогда
            Возврат Истина;
        КонецЕсли;
        Возврат Ложь;
    КонецФункции
    """

    program, diags = parse(source, MIXED_PROFILE)

    assert program is not None
    assert not [item for item in diags if item.severity == "error"]


def test_parse_mixed_bsl_accepts_module_level_initialization_statements() -> None:
    text = """
    #Область Initialization
    ЗаписьЖурналаРегистрации(Событие, Уровень,,, Подробно);
    Counter = Counter + 1;
    #КонецОбласти
    """

    program, diags = parse(text, MIXED_PROFILE)

    assert program is not None
    assert not [d for d in diags if d.severity == "error"]


def test_parse_mixed_bsl_allows_keyword_like_loop_variables() -> None:
    text = """
    Функция Main() Экспорт
        Результат = 0;
        Для Каждого Область Из Новый Массив(2, 3) Цикл
            Результат = Результат + Область;
        КонецЦикла;
        Для Документ = 1 По 2 Цикл
            Результат = Результат + Документ;
        КонецЦикла;
        Возврат Результат;
    КонецФункции
    """

    program, diags = parse(text, MIXED_PROFILE)

    assert program is not None
    assert not [d for d in diags if d.severity == "error"]


def test_parse_mixed_bsl_supports_unary_plus() -> None:
    program, diags = parse(
        "Функция Main() Возврат +1; КонецФункции",
        MIXED_PROFILE,
    )

    assert program is not None
    assert not [d for d in diags if d.severity == "error"]
    statement = program.functions()[0].body[0]
    assert isinstance(statement, ReturnStmt)
    assert isinstance(statement.value, UnaryExpr)
    assert statement.value.op == "+"


def test_parse_mixed_bsl_supports_dynamic_constructor() -> None:
    program, diags = parse(
        "Функция Main() Возврат Новый(ТипЗначения, 7); КонецФункции",
        MIXED_PROFILE,
    )

    assert program is not None
    assert not [d for d in diags if d.severity == "error"]
    statement = program.functions()[0].body[0]
    assert isinstance(statement, ReturnStmt)
    assert isinstance(statement.value, NewExpr)
    assert statement.value.type_name is None
    assert isinstance(statement.value.type_expr, NameExpr)
    assert statement.value.type_expr.name == "ТипЗначения"
    assert len(statement.value.args) == 1


def test_parse_mixed_bsl_string_uses_literal_backslash() -> None:
    program, diags = parse(
        r'Функция Main() Возврат "C:\Temp"; КонецФункции',
        MIXED_PROFILE,
    )

    assert program is not None
    assert not [d for d in diags if d.severity == "error"]
    statement = program.functions()[0].body[0]
    assert isinstance(statement, ReturnStmt)
    assert isinstance(statement.value, Literal)
    assert statement.value.value == r"C:\Temp"
