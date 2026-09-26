from __future__ import annotations

import pytest

from src.dsl.semantic_rename import (
    SemanticRenameError,
    plan_semantic_rename,
    plan_workspace_export_rename,
)


def test_rename_parameter_uses_tokens_and_ignores_strings_comments_and_members() -> None:
    source = """Procedure Run(Value)
    LocalValue = Value;
    Other.Value = Value;
    Message("Value"); // Value
EndProcedure
"""

    plan = plan_semantic_rename(
        source,
        source.index("Value"),
        "Amount",
        language="mixed",
    )

    assert plan.symbol_kind == "parameter"
    assert [item.line for item in plan.occurrences] == [1, 2, 3]
    assert "Procedure Run(Amount)" in plan.updated_source
    assert "LocalValue = Amount;" in plan.updated_source
    assert "Other.Value = Amount;" in plan.updated_source
    assert 'Message("Value"); // Value' in plan.updated_source


def test_rename_module_variable_skips_shadowing_parameter() -> None:
    source = """Var State;
Procedure First()
    State = 1;
EndProcedure
Procedure Second(State)
    State = 2;
EndProcedure
"""

    plan = plan_semantic_rename(
        source,
        source.index("State"),
        "SessionState",
        language="mixed",
    )

    assert plan.symbol_kind == "module_variable"
    assert [item.line for item in plan.occurrences] == [1, 3]
    assert "Procedure Second(State)" in plan.updated_source
    assert "    State = 2;" in plan.updated_source


def test_rename_procedure_skips_foreign_member_call() -> None:
    source = """Procedure Run()
EndProcedure
Procedure Caller()
    Run();
    Other.Run();
EndProcedure
"""

    plan = plan_semantic_rename(
        source,
        source.index("Run"),
        "Execute",
        language="mixed",
    )

    assert plan.symbol_kind == "procedure"
    assert [item.line for item in plan.occurrences] == [1, 4]
    assert "Procedure Execute()" in plan.updated_source
    assert "Other.Run();" in plan.updated_source


def test_rename_rejects_scope_collision() -> None:
    source = """Procedure Run(Value, Amount)
    Value = Amount;
EndProcedure
"""

    with pytest.raises(SemanticRenameError, match="conflicts"):
        plan_semantic_rename(
            source,
            source.index("Value"),
            "Amount",
            language="mixed",
        )


def test_rename_rejects_keyword_as_identifier() -> None:
    source = """Procedure Run(Value)
EndProcedure
"""

    with pytest.raises(SemanticRenameError, match="Invalid identifier"):
        plan_semantic_rename(
            source,
            source.index("Value"),
            "If",
            language="mixed",
        )


@pytest.mark.parametrize(
    ("source", "old_name"),
    [
        (
            "Змін Стан Експорт;\n"
            "Процедура Запуск()\n"
            "    Стан = 1;\n"
            "КінецьПроцедури\n",
            "Стан",
        ),
        (
            "Перем Состояние Экспорт;\n"
            "Процедура Запуск()\n"
            "    Состояние = 1;\n"
            "КонецПроцедуры\n",
            "Состояние",
        ),
    ],
)
def test_rename_supports_ukrainian_and_compatibility_module_syntax(
    source: str,
    old_name: str,
) -> None:
    plan = plan_semantic_rename(
        source,
        source.index(old_name),
        "Сеанс",
        language="mixed",
    )

    assert plan.symbol_kind == "module_variable"
    assert len(plan.occurrences) == 2
    assert old_name not in plan.updated_source


def test_workspace_rename_updates_exported_method_and_qualified_calls() -> None:
    declaration = (
        "Function LoadSettings() Export\n"
        "    Return 1;\n"
        "EndFunction\n"
        "Procedure LocalCaller()\n"
        "    LoadSettings();\n"
        "EndProcedure\n"
    )
    caller = (
        "Value = SettingsServer.LoadSettings();\n"
        'Message("SettingsServer.LoadSettings");\n'
        "// SettingsServer.LoadSettings();\n"
        "Other.SettingsServer.LoadSettings();\n"
    )

    plan = plan_workspace_export_rename(
        [
            {
                "module_guid": "declaration",
                "name": "SettingsServer",
                "source_text": declaration,
            },
            {
                "module_guid": "caller",
                "name": "Caller",
                "source_text": caller,
            },
        ],
        declaration_module_guid="declaration",
        cursor_position=declaration.index("LoadSettings"),
        new_name="ReadSettings",
        qualifier_names=("SettingsServer",),
    )

    assert plan.symbol_kind == "function"
    assert plan.occurrence_count == 3
    assert [module.module_guid for module in plan.modules] == [
        "declaration",
        "caller",
    ]
    assert "Function ReadSettings() Export" in plan.modules[0].updated_source
    assert "    ReadSettings();" in plan.modules[0].updated_source
    assert "SettingsServer.ReadSettings()" in plan.modules[1].updated_source
    assert '"SettingsServer.LoadSettings"' in plan.modules[1].updated_source
    assert "// SettingsServer.LoadSettings();" in plan.modules[1].updated_source
    assert "Other.SettingsServer.LoadSettings();" in plan.modules[1].updated_source
    assert plan.modules[0].source_hash != plan.modules[0].updated_hash


def test_workspace_rename_rejects_non_exported_method() -> None:
    source = "Procedure Run()\nEndProcedure\n"

    with pytest.raises(SemanticRenameError, match="exported"):
        plan_workspace_export_rename(
            [{"module_guid": "module-1", "source_text": source}],
            declaration_module_guid="module-1",
            cursor_position=source.index("Run"),
            new_name="Execute",
            qualifier_names=("Module",),
        )
