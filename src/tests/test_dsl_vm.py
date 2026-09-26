from src.dsl.compiler import compile_module as dsl_compile_module
from src.dsl.vm import execute_script
from src.dsl.vm import run_module
from src.runtime.script.compiler import (
    CodeObject,
    Instruction,
    LOAD_CONST,
    NEW_DYNAMIC,
    RETURN_NONE,
    STORE_NAME,
    UNARY_OP,
    ModuleCode,
    compile_module as runtime_compile_module,
)


def _build_test_module() -> ModuleCode:
    main = CodeObject(
        name="Main",
        params=[],
        by_value=[],
        defaults=[],
        instructions=[
            Instruction(op=LOAD_CONST, arg=True, lineno=3),
            Instruction(op=STORE_NAME, arg="Cancel", lineno=3),
            Instruction(op=RETURN_NONE, lineno=4),
        ],
        locals_=[],
        exported=False,
        is_function=False,
    )
    return ModuleCode(
        name="module://dsl-test-module",
        procedures={"Main": main},
        functions={},
        module_vars=[],
    )


class _DebugPlugin:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, int]] = []

    def before_instruction(self, *, module_id, frame, call_stack, instr) -> None:
        self.events.append((str(module_id), str(frame.code.name), int(instr.lineno or 0)))


def test_dsl_run_module_updates_context_globals() -> None:
    ctx = {"Cancel": False}
    run_module(_build_test_module(), entry="Main", initial_globals=ctx)
    assert ctx["Cancel"] is True


def test_dsl_vm_accepts_optional_debug_plugin() -> None:
    plugin = _DebugPlugin()
    run_module(
        _build_test_module(),
        entry="Main",
        initial_globals={"Cancel": False},
        debug_plugin=plugin,
    )
    assert plugin.events == [
        ("module://dsl-test-module", "Main", 3),
        ("module://dsl-test-module", "Main", 3),
        ("module://dsl-test-module", "Main", 4),
    ]


def test_dsl_compiler_shim_reexports_shared_compile_module() -> None:
    assert dsl_compile_module is runtime_compile_module


def test_execute_script_accepts_mixed_imported_bsl_constructs() -> None:
    source = """
    Процедура Main() Экспорт
        Сообщить(НСтр("ru='Ошибка'"
        ";uk='Помилка'"));
    КонецПроцедуры
    """
    result, errors = execute_script(
        source,
        language="mixed",
        entry="Main",
        extra_builtins={"Сообщить": lambda _x: None},
    )
    assert result is None
    assert errors == []


def test_execute_script_supports_1c_ternary_operator() -> None:
    source = """
    Функция Main() Экспорт
        Возврат ?(Истина, "OK", "FAIL");
    КонецФункции
    """
    result, errors = execute_script(source, language="mixed", entry="Main")
    assert result == "OK"
    assert errors == []


def test_execute_script_supports_for_loop_from_imported_bsl() -> None:
    source = """
    Функция Main() Экспорт
        Сумма = 0;
        Для Индекс = 1 По 3 Цикл
            Сумма = Сумма + Индекс;
        КонецЦикла;
        Возврат Сумма;
    КонецФункции
    """
    result, errors = execute_script(source, language="mixed", entry="Main")
    assert result == 6
    assert errors == []


def test_execute_script_supports_foreach_loop_from_imported_bsl() -> None:
    source = """
    Функция Main() Экспорт
        Значение = 0;
        Для Каждого Элемент Из Новый Массив(4, 5) Цикл
            Значение = Значение + Элемент;
        КонецЦикла;
        Возврат Значение;
    КонецФункции
    """
    result, errors = execute_script(source, language="mixed", entry="Main")
    assert result == 9
    assert errors == []


def test_execute_script_supports_russian_bsl_collection_aliases() -> None:
    source = """
    Функция Main() Экспорт
        Сумма = 0;
        Данные = Новый Структура();
        Данные.Вставить("Ключ", 7);
        Для Каждого Элемент Из Новый Массив(2, 3) Цикл
            Сумма = Сумма + Элемент;
        КонецЦикла;
        Возврат Сумма + Данные.Получить("Ключ");
    КонецФункции
    """
    result, errors = execute_script(source, language="mixed", entry="Main")
    assert result == 12
    assert errors == []


def test_compile_and_execute_preserves_bsl_context_annotation() -> None:
    source = """
    &НаКлиенте
    Перем ClientState;
    &НаКлиенте
    Функция Main() Экспорт
        Возврат "A" & "B";
    КонецФункции
    """

    from src.dsl.languages import MIXED_PROFILE
    from src.dsl.parser import parse

    program, diags = parse(source, MIXED_PROFILE)
    assert program is not None
    assert not [d for d in diags if d.severity == "error"]

    module = dsl_compile_module(program, module_name="module://annotated")
    assert [item.name for item in module.functions["Main"].annotations] == ["НаКлиенте"]
    assert [item.name for item in module.module_var_annotations["ClientState"]] == [
        "НаКлиенте"
    ]

    result = run_module(module, entry="Main")
    assert result == "AB"


def test_module_initializer_executes_once_per_persistent_context() -> None:
    source = """
    Counter = Counter + 1;

    Функція Main()
        Повернути Counter;
    КінецьФункції
    """
    context = {"Counter": 0}

    first, first_errors = execute_script(
        source,
        language="mixed",
        entry="Main",
        context=context,
        module_name="module://initializer-test",
    )
    second, second_errors = execute_script(
        source,
        language="mixed",
        entry="Main",
        context=context,
        module_name="module://initializer-test",
    )

    assert first_errors == []
    assert second_errors == []
    assert first == 1
    assert second == 1
    assert context["Counter"] == 1


def test_module_initializer_can_call_runtime_builtin_without_entry() -> None:
    output: list[str] = []
    result, errors = execute_script(
        'Повідомлення("initialized");',
        language="mixed",
        extra_builtins={"Повідомлення": output.append},
        context={},
        module_name="module://initializer-message",
    )

    assert result is None
    assert errors == []
    assert output == ["initialized"]


def test_execute_script_supports_keyword_like_loop_variables() -> None:
    source = """
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

    result, errors = execute_script(source, language="mixed", entry="Main")

    assert errors == []
    assert result == 8


def test_compiler_emits_unary_plus_instruction() -> None:
    from src.dsl.languages import MIXED_PROFILE
    from src.dsl.parser import parse

    program, diags = parse(
        "Функция Main() Возврат +1; КонецФункции",
        MIXED_PROFILE,
    )
    assert program is not None
    assert not [d for d in diags if d.severity == "error"]

    module = dsl_compile_module(program, module_name="module://unary-plus")
    instructions = module.functions["Main"].instructions

    assert any(item.op == UNARY_OP and item.arg == "+" for item in instructions)


def test_execute_script_supports_unary_plus() -> None:
    source = """
    Функция Main() Экспорт
        Возврат +(+41);
    КонецФункции
    """

    result, errors = execute_script(source, language="mixed", entry="Main")

    assert errors == []
    assert result == 41


def test_compiler_emits_dynamic_constructor_instruction() -> None:
    from src.dsl.languages import MIXED_PROFILE
    from src.dsl.parser import parse

    program, diags = parse(
        "Function Main() Return New(Constructor, 7); EndFunction",
        MIXED_PROFILE,
    )
    assert program is not None
    assert not [d for d in diags if d.severity == "error"]

    module = dsl_compile_module(program, module_name="module://dynamic-new")
    instructions = module.functions["Main"].instructions

    assert any(item.op == NEW_DYNAMIC and item.arg == 1 for item in instructions)


def test_execute_script_supports_dynamic_constructor_callable() -> None:
    result, errors = execute_script(
        "Function Main() Return New(Constructor, 4, 5); EndFunction",
        language="mixed",
        entry="Main",
        context={"Constructor": lambda left, right: left + right},
    )

    assert errors == []
    assert result == 9


def test_execute_script_supports_dynamic_constructor_type_descriptor() -> None:
    result, errors = execute_script(
        'Функция Main() Возврат Новый(Тип("Widget"), 7); КонецФункции',
        language="mixed",
        entry="Main",
        context={"Widget": lambda value: {"value": value}},
    )

    assert errors == []
    assert result == {"value": 7}


def test_compiler_preserves_bsl_string_literal_value() -> None:
    from src.dsl.languages import MIXED_PROFILE
    from src.dsl.parser import parse

    program, diags = parse(
        r'Функция Main() Возврат "C:\Temp"; КонецФункции',
        MIXED_PROFILE,
    )
    assert program is not None
    assert not [d for d in diags if d.severity == "error"]

    module = dsl_compile_module(program, module_name="module://bsl-string")
    instructions = module.functions["Main"].instructions

    assert any(item.op == LOAD_CONST and item.arg == r"C:\Temp" for item in instructions)


def test_execute_script_supports_bsl_string_escaping() -> None:
    source = r'''
    Функция Main() Экспорт
        Возврат "C:\Temp" + "|" + "Ім'я: ""файл""";
    КонецФункции
    '''

    result, errors = execute_script(source, language="mixed", entry="Main")

    assert errors == []
    assert result == 'C:\\Temp|Ім\'я: "файл"'


def test_execute_script_supports_import_compatible_single_quoted_string() -> None:
    result, errors = execute_script(
        "Функция Main() Возврат 'ru=''Помилка'''; КонецФункции",
        language="mixed",
        entry="Main",
    )

    assert errors == []
    assert result == "ru='Помилка'"


def test_execute_script_supports_bsl_number_with_trailing_decimal_point() -> None:
    result, errors = execute_script(
        """
        Функция Main()
            Значение = 0.;
            Возврат Значение;
        КонецФункции
        """,
        language="mixed",
        entry="Main",
    )

    assert errors == []
    assert result == 0.0
    assert isinstance(result, float)


def test_execute_script_supports_region_named_variable_and_multiline_call() -> None:
    result, errors = execute_script(
        """
        Функция Main()
            Область = Host.Call(
                1,
                2,
                3);
            Возврат Область;
        КонецФункции
        """,
        language="mixed",
        entry="Main",
        context={"Host": {"Call": lambda *args: sum(args)}},
    )

    assert errors == []
    assert result == 6


def test_execute_script_supports_bsl_multiline_string_with_source_comment() -> None:
    result, errors = execute_script(
        '''
        Функция Main()
            Возврат "SELECT
                // source comment with "quoted-name"
                |FROM Table
                |WHERE Active";
        КонецФункции
        ''',
        language="mixed",
        entry="Main",
    )

    assert errors == []
    assert result == "SELECT\nFROM Table\nWHERE Active"


def test_execute_statement_runs_source_in_current_scope() -> None:
    result, errors = execute_script(
        '''
        Функция Main()
            Перем Значение;
            Значение = 1;
            Выполнить "Значение = Значение + 4;";
            Возврат Значение;
        КонецФункции
        ''',
        language="mixed",
        entry="Main",
    )

    assert errors == []
    assert result == 5
def test_object_attribute_assignment_keeps_value_and_target_order() -> None:
    class Box:
        Value = ""

    box = Box()
    source = (
        "Процедура Main()\n"
        "    Target.Value = \"updated\"\n"
        "КінецьПроцедури"
    )

    result, errors = execute_script(source, language="uk", entry="Main", context={"Target": box})

    assert errors == []
    assert result is None
    assert box.Value == "updated"


def test_module_globals_survive_runtime_error_after_assignment() -> None:
    context: dict[str, object] = {}
    source = (
        "Змін Result\n"
        "Процедура Main()\n"
        "    Result = 42\n"
        "    MissingCall()\n"
        "КінецьПроцедури"
    )

    result, errors = execute_script(source, language="uk", entry="Main", context=context)

    assert result is None
    assert errors == ["Name 'MissingCall' is not defined"]
    assert context["Result"] == 42


def test_structure_keys_support_property_read_and_write() -> None:
    source = (
        "Змін Result\n"
        "Процедура Main()\n"
        "    Params = Новий Структура\n"
        "    Params.Value = 42\n"
        "    Result = Params.Value\n"
        "КінецьПроцедури"
    )
    context: dict[str, object] = {}

    result, errors = execute_script(source, language="uk", entry="Main", context=context)

    assert result is None
    assert errors == []
    assert context["Result"] == 42


def test_structure_property_type_and_iteration_follow_bsl_semantics() -> None:
    source = """
    Функція Main()
        Params = Новий Структура;
        Params.Вставить("Answer", 42);
        Якщо Params.Свойство("Answer") = Хибність Тоді
            Повернути -1;
        КінецьЯкщо;
        Якщо ТипЗнч(Params) <> Тип("Структура") Тоді
            Повернути -2;
        КінецьЯкщо;
        Для Кожного Item З Params Цикл
            Повернути Item.Значение;
        КінецьЦиклу;
        Повернути 0;
    КінецьФункції
    """

    result, errors = execute_script(source, language="uk", entry="Main")

    assert errors == []
    assert result == 42


def test_runtime_error_reports_source_line_without_debug_plugin() -> None:
    source = """
    Функція Main()
        Missing = Невизначено;
        Повернути Missing();
    КінецьФункції
    """

    _result, errors = execute_script(
        source,
        language="uk",
        entry="Main",
        module_name="module://line-test",
    )

    assert errors == ["'None' is not callable at module://line-test:Main:L4"]


def test_missing_call_arguments_use_literal_parameter_defaults() -> None:
    source = """
    Функція Prefix(Value, Separator = "", Enabled = Істина)
        Якщо Enabled Тоді
            Повернути Separator + Value;
        КінецьЯкщо;
        Повернути "disabled";
    КінецьФункції

    Функція Main()
        Повернути Prefix("Subsystem");
    КінецьФункції
    """

    result, errors = execute_script(source, language="uk", entry="Main")

    assert errors == []
    assert result == "Subsystem"


def test_module_function_has_priority_over_external_context_name() -> None:
    source = """
    Функція Resolve()
        Повернути 42;
    КінецьФункції

    Функція Main()
        Повернути Resolve();
    КінецьФункції
    """

    result, errors = execute_script(
        source,
        language="uk",
        entry="Main",
        context={"Resolve": "external-value"},
    )

    assert errors == []
    assert result == 42


def test_fixed_array_constructor_copies_source_array() -> None:
    source = """
    Функція Main()
        Source = Новий Масив;
        Source.Додати(42);
        Copy = Новий ФиксированныйМассив(Source);
        Source.Додати(7);
        Повернути Copy.Кількість();
    КінецьФункції
    """

    result, errors = execute_script(source, language="uk", entry="Main")

    assert errors == []
    assert result == 1


def test_array_uses_zero_based_bsl_indexes() -> None:
    source = """
    Функція Main()
        Items = Новий Масив("first", "second");
        Items.Встановити(1, "updated");
        Повернути Items[0] + ":" + Items.Отримати(1);
    КінецьФункції
    """

    result, errors = execute_script(source, language="uk", entry="Main")

    assert errors == []
    assert result == "first:updated"


def test_logical_operators_short_circuit_right_operand() -> None:
    source = """
    Функція Main()
        Якщо Хибність Та MissingCall() Тоді
            Повернути -1;
        КінецьЯкщо;
        Якщо Істина Або MissingCall() Тоді
            Повернути 42;
        КінецьЯкщо;
        Повернути 0;
    КінецьФункції
    """

    result, errors = execute_script(source, language="uk", entry="Main")

    assert errors == []
    assert result == 42


def test_implicit_procedure_variables_are_local_and_do_not_shadow_types() -> None:
    class Widget:
        def __init__(self, value=0) -> None:
            self.value = value

    source = """
    Функція Main()
        Widget = Новий Widget(41);
        Widget = Новий Widget(Widget.value + 1);
        Повернути Widget.value;
    КінецьФункції
    """
    context = {"Widget": lambda value=0: Widget(value)}

    result, errors = execute_script(
        source,
        language="uk",
        entry="Main",
        extra_builtins=context,
        context=context,
    )

    assert errors == []
    assert result == 42
    assert callable(context["Widget"])
