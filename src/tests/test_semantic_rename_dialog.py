from __future__ import annotations

from PySide6.QtWidgets import QApplication, QPlainTextEdit

from src.dsl.semantic_rename import plan_semantic_rename
from src.ui_qt.widgets.semantic_rename_dialog import (
    SemanticRenameDialog,
    WorkspaceRenamePreviewDialog,
    apply_semantic_rename_plan,
)


def _source() -> str:
    return (
        "Procedure Run(Value)\n"
        "    Value = Value + 1;\n"
        "EndProcedure\n"
    )


def test_semantic_rename_dialog_builds_reactive_preview() -> None:
    QApplication.instance() or QApplication([])
    source = _source()
    dialog = SemanticRenameDialog(
        source=source,
        cursor_position=source.index("Value"),
    )

    dialog.ed_new_name.setText("Amount")
    dialog._refresh_preview()

    assert dialog.plan is not None
    assert dialog.plan.old_name == "Value"
    assert dialog.plan.new_name == "Amount"
    assert dialog.table.rowCount() == 3
    assert dialog.btn_apply.isEnabled()


def test_apply_semantic_rename_plan_is_one_undo_operation() -> None:
    QApplication.instance() or QApplication([])
    source = _source()
    plan = plan_semantic_rename(
        source,
        source.index("Value"),
        "Amount",
    )
    editor = QPlainTextEdit()
    editor.setPlainText(source)

    apply_semantic_rename_plan(editor, plan)

    assert editor.toPlainText() == plan.updated_source
    editor.undo()
    assert editor.toPlainText() == source


def test_workspace_rename_preview_lists_modules_and_occurrences() -> None:
    QApplication.instance() or QApplication([])
    dialog = WorkspaceRenamePreviewDialog(
        {
            "old_name": "LoadSettings",
            "new_name": "ReadSettings",
            "module_count": 2,
            "occurrence_count": 2,
            "modules": [
                {
                    "module_guid": "module-1",
                    "module_name": "SettingsServer",
                    "occurrences": [
                        {
                            "line": 1,
                            "preview": "Function LoadSettings() Export",
                            "declaration": True,
                        }
                    ],
                },
                {
                    "module_guid": "module-2",
                    "module_name": "ApplicationModule",
                    "occurrences": [
                        {
                            "line": 10,
                            "preview": "SettingsServer.LoadSettings();",
                            "declaration": False,
                        }
                    ],
                },
            ],
        }
    )

    assert dialog.table.rowCount() == 2
    assert dialog.table.item(0, 0).text() == "SettingsServer"
    assert dialog.table.item(1, 0).text() == "ApplicationModule"
    assert dialog.table.item(1, 1).text() == "10"
