from src.dsl.module_introspection import introspect_module_source, repair_cp1251_mojibake_name


def test_introspection_extracts_1c_module_symbols_and_runtime_names() -> None:
    source = (
        "Змін глФормаНачальнойНастройкиПрограммы Експорт;\n"
        "Процедура ПередНачаломРаботыСистемы()\n"
        "КінецьПроцедури\n"
        "Функція ПолучитьЗначение(Параметр) Експорт\n"
        "    Повернути Параметр\n"
        "КінецьФункції\n"
    )

    info = introspect_module_source(source, language="mixed")

    assert "глФормаНачальнойНастройкиПрограммы" in info.symbol_by_name
    assert "ПередНачаломРаботыСистемы" in info.procedures
    assert "ПолучитьЗначение" in info.functions
    assert "Метаданные" in info.symbol_by_name


def test_repair_cp1251_mojibake_name() -> None:
    assert repair_cp1251_mojibake_name("ãëÔîðìàÍà÷àëüíîéÍàñòðîéêèÏðîãðàììû") == "глФормаНачальнойНастройкиПрограммы"


def test_introspection_extracts_procedure_scope_locals_and_params() -> None:
    source = (
        "Змін глЗначення Експорт;\n"
        "Процедура Обробити(Параметр)\n"
        "    Змін Локальна;\n"
        "    Локальна = Параметр;\n"
        "    Виведена = Локальна;\n"
        "    Для Індекс = 1 По 3 Цикл\n"
        "        Поточне = Індекс;\n"
        "    КінецьЦиклу;\n"
        "КінецьПроцедури\n"
    )

    info = introspect_module_source(source, language="mixed")
    scope = next(item for item in info.scopes if item.name == "Обробити")

    assert scope.params == ("Параметр",)
    assert "Параметр" in scope.locals
    assert "Локальна" in scope.locals
    assert "Виведена" in scope.locals
    assert "Індекс" in scope.locals
    assert "Поточне" in scope.locals
    assert "глЗначення" not in scope.locals
    assert scope.contains_line(4) is True
    assert scope.contains_line(50) is False
