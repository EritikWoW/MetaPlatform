from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest

from src.dsl.module_introspection import introspect_module_source
from src.dsl.code_templates import expand_template, templates_for
from src.ui_qt.widgets.code_editor_widget import (
    CodeEditorWidget,
    _CodeEdit,
    identifier_chain_at,
    metadata_completion_objects_from_vm,
    resolve_definition_target,
)
from src.ui_qt.viewmodels.configurator_vm_assets import ConfiguratorVmAssetsMixin


class _EditorVmStub:
    def __init__(self, text: str | None = None, *, resolved_key: str | None = None) -> None:
        self.calls: list[str] = []
        self.save_calls: list[tuple[str, str, str]] = []
        self._text = text or "Процедура Тест()\nКонецПроцедуры"
        self._resolved_key = resolved_key

    def get_text_asset(self, asset_key: str):
        self.calls.append(str(asset_key))
        resolved = str(self._resolved_key or asset_key)
        return self._text, "text/plain", resolved

    def save_text_asset(self, asset_key: str, text: str, *, mime: str = "text/plain") -> None:
        self.save_calls.append((str(asset_key), str(text), str(mime)))
        self._text = str(text)


class _FailingEditorVmStub(_EditorVmStub):
    def __init__(self, text: str | None = None) -> None:
        super().__init__(text=text)
        self.fail_reads = True
        self.fail_writes = False

    def get_text_asset(self, asset_key: str):
        if self.fail_reads:
            raise RuntimeError("Unknown action: modules.get_text")
        return super().get_text_asset(asset_key)

    def save_text_asset(self, asset_key: str, text: str, *, mime: str = "text/plain") -> None:
        if self.fail_writes:
            raise RuntimeError("runtime unavailable")
        super().save_text_asset(asset_key, text, mime=mime)


def test_code_edit_composes_workspace_diagnostics_with_current_line() -> None:
    app = QApplication.instance() or QApplication([])
    edit = _CodeEdit()
    edit.setPlainText("one\ntwo\nthree")
    edit.resize(500, 240)
    edit.show()
    app.processEvents()

    edit.set_workspace_diagnostics(
        [
            {
                "line": 2,
                "col": 2,
                "severity": "error",
                "message": "Missing member",
            }
        ]
    )

    assert sorted(edit._workspace_diagnostics) == [2]
    assert len(edit.extraSelections()) == 2
    assert any(sel.cursor.selectedText() == "two" for sel in edit.extraSelections())
    block = edit.document().findBlockByNumber(1)
    line_y = int(
        edit.blockBoundingGeometry(block).translated(edit.contentOffset()).top()
    ) + 1
    assert "Missing member" in edit.diagnostic_tooltip_at_y(
        line_y
    )
    edit.deleteLater()


def test_code_editor_filters_workspace_diagnostics_by_module_guid() -> None:
    QApplication.instance() or QApplication([])
    widget = CodeEditorWidget(
        vm=_EditorVmStub(),
        asset_key="module://module-a",
        title="Module A",
    )

    widget.set_workspace_diagnostics(
        [
            {"module_guid": "module-a", "line": 2, "severity": "warning"},
            {"module_guid": "module-b", "line": 3, "severity": "error"},
        ]
    )

    assert sorted(widget._edit._workspace_diagnostics) == [2]
    widget.deleteLater()


def test_code_editor_combines_live_parser_and_workspace_diagnostics() -> None:
    QApplication.instance() or QApplication([])
    widget = CodeEditorWidget(
        vm=_EditorVmStub(text="x = ;\n"),
        asset_key="module://module-a",
        title="Module A",
    )

    widget._refresh_local_diagnostics()
    widget.set_workspace_diagnostics(
        [
            {
                "module_guid": "module-a",
                "line": 2,
                "severity": "warning",
                "message": "Missing callable",
            }
        ]
    )

    assert sorted(widget._edit._workspace_diagnostics) == [1, 2]
    assert widget._edit._workspace_diagnostics[1][0]["source"] == "parser"
    assert widget._edit._workspace_diagnostics[2][0]["message"] == "Missing callable"
    widget.deleteLater()


def test_code_editor_reparses_changed_buffer_after_debounce() -> None:
    QApplication.instance() or QApplication([])
    widget = CodeEditorWidget(
        vm=_EditorVmStub(),
        asset_key="module://module-a",
        title="Module A",
    )

    widget._edit.setPlainText("x = ;\n")
    QTest.qWait(800)

    assert sorted(widget._edit._workspace_diagnostics) == [1]
    assert widget._edit._workspace_diagnostics[1][0]["source"] == "parser"
    widget.deleteLater()


class _AssetsServiceStub:
    def __init__(self) -> None:
        self.module_texts: dict[str, str] = {}
        self.modules_by_owner: dict[str, list[dict]] = {}
        self.updated_modules: list[tuple[str, str, str]] = []

    def require_db(self):
        return object()

    def get_module_text(self, module_guid: str) -> str:
        return self.module_texts.get(str(module_guid), "")

    def list_modules_by_owner(self, owner_guid: str) -> list[dict]:
        return list(self.modules_by_owner.get(str(owner_guid), []))

    def update_module_text(self, module_guid: str, text: str, *, updated_by: str = "user") -> None:
        self.updated_modules.append((str(module_guid), str(text), str(updated_by)))


class _AssetsVmStub(ConfiguratorVmAssetsMixin):
    def __init__(self) -> None:
        self._service = _AssetsServiceStub()


class _DefinitionServiceStub:
    def resolve_workspace_symbol(self, qualifier: str, name: str) -> dict:
        if qualifier == "СпільнийСервер" and name == "ОтриматиНалаштування":
            return {
                "name": name,
                "module_guid": "common-module",
                "owner_guid": "common-owner",
                "owner_title": "СпільнийСервер",
                "owner_type": "common_module",
                "line": 1,
            }
        return {}

    def list_modules_by_owner(self, owner_guid: str) -> list[dict]:
        if owner_guid == "common-owner":
            return [{"module_guid": "common-module", "module_kind": "module", "lang": ""}]
        return []


class _DefinitionVmStub(_EditorVmStub):
    def __init__(self) -> None:
        super().__init__()
        self._service = _DefinitionServiceStub()
        self._objects_snapshot = [
            {
                "guid": "common-owner",
                "type": "common_module",
                "kind": "object",
                "name": "SharedServer",
                "title": "СпільнийСервер",
                "payload": {"metadata_ref": "CommonModule.СпільнийСервер"},
            },
            {
                "guid": "catalog-products",
                "type": "catalog",
                "kind": "object",
                "name": "Products",
                "title": "Товари",
                "payload": {"metadata_ref": "Catalog.Products"},
            },
        ]

    def get_text_asset(self, asset_key: str):
        if asset_key == "module://common-module":
            text = (
                "Функція ОтриматиНалаштування() Експорт\n"
                "    Повернути 1;\n"
                "КінецьФункції"
            )
            return text, "text/plain", asset_key
        return super().get_text_asset(asset_key)


def test_identifier_chain_and_definition_resolver_cover_ide_targets() -> None:
    vm = _DefinitionVmStub()
    local_source = (
        "Процедура Виконати()\n"
        "КінецьПроцедури\n\n"
        "Виконати();"
    )
    local_info = introspect_module_source(local_source, language="mixed")

    local = resolve_definition_target(
        local_source,
        local_source.rindex("Виконати") + 2,
        introspection=local_info,
        vm=vm,
    )
    module_source = "Значення = СпільнийСервер.ОтриматиНалаштування();"
    module = resolve_definition_target(
        module_source,
        module_source.index("Отримати") + 3,
        introspection=introspect_module_source(module_source, language="mixed"),
        vm=vm,
    )
    metadata_source = "Об'єкт = Метадані.Довідники.Товари;"
    metadata = resolve_definition_target(
        metadata_source,
        metadata_source.index("Товари") + 2,
        introspection=introspect_module_source(metadata_source, language="mixed"),
        vm=vm,
    )

    assert identifier_chain_at(module_source, module_source.index("Отримати")) == (
        "СпільнийСервер",
        "ОтриматиНалаштування",
    )
    assert local is not None and local.kind == "local" and local.line == 1
    assert module is not None and module.kind == "module"
    assert module.module_guid == "common-module"
    assert module.line == 1
    assert "module://common-module" not in vm.calls
    assert metadata is not None and metadata.kind == "metadata"
    assert metadata.guid == "catalog-products"


def test_f12_moves_to_local_definition_and_emits_external_target() -> None:
    app = QApplication.instance() or QApplication([])
    source = (
        "Процедура Виконати()\n"
        "КінецьПроцедури\n\n"
        "Виконати();"
    )
    widget = CodeEditorWidget(
        vm=_DefinitionVmStub(),
        asset_key="module://test-guid",
        title="Module",
    )
    widget._edit.setPlainText(source)
    widget.show()
    widget._edit.setFocus()
    cursor = widget._edit.textCursor()
    cursor.setPosition(source.rindex("Виконати") + 2)
    widget._edit.setTextCursor(cursor)
    app.processEvents()

    QTest.keyClick(widget._edit, Qt.Key.Key_F12)
    app.processEvents()

    assert widget._edit.textCursor().blockNumber() == 0
    assert widget._edit._debug_line == 0

    external_source = "Значення = СпільнийСервер.ОтриматиНалаштування();"
    widget._edit.setPlainText(external_source)
    cursor = widget._edit.textCursor()
    cursor.setPosition(external_source.index("Отримати") + 2)
    widget._edit.setTextCursor(cursor)
    targets: list[dict] = []
    widget.definitionRequested.connect(targets.append)

    QTest.keyClick(widget._edit, Qt.Key.Key_F12)
    app.processEvents()

    assert targets
    assert targets[-1]["module_guid"] == "common-module"
    assert targets[-1]["line"] == 1


def test_shift_f12_emits_qualified_usage_query() -> None:
    app = QApplication.instance() or QApplication([])
    source = "Значення = СпільнийСервер.ОтриматиНалаштування();"
    widget = CodeEditorWidget(
        vm=_DefinitionVmStub(),
        asset_key="module://test-guid",
        title="Module",
    )
    widget._edit.setPlainText(source)
    cursor = widget._edit.textCursor()
    cursor.setPosition(source.index("Отримати") + 2)
    widget._edit.setTextCursor(cursor)
    queries: list[dict] = []
    widget.usagesRequested.connect(queries.append)
    widget.show()
    widget._edit.setFocus()
    app.processEvents()

    QTest.keyClick(widget._edit, Qt.Key.Key_F12, Qt.KeyboardModifier.ShiftModifier)
    app.processEvents()

    assert len(queries) == 1
    assert queries[0]["term"] == "СпільнийСервер.ОтриматиНалаштування"
    assert queries[0]["whole_word"] is True
    assert queries[0]["module_guid"] == ""


def test_shift_f6_invokes_semantic_rename_handler() -> None:
    app = QApplication.instance() or QApplication([])
    widget = CodeEditorWidget(
        vm=_DefinitionVmStub(),
        asset_key="module://test-guid",
        title="Module",
    )
    calls: list[bool] = []
    handler = lambda: calls.append(True)
    widget._rename_symbol = handler
    widget._edit._rename_handler = handler
    widget.show()
    widget._edit.setFocus()
    app.processEvents()

    QTest.keyClick(widget._edit, Qt.Key.Key_F6, Qt.KeyboardModifier.ShiftModifier)
    app.processEvents()

    assert calls == [True]


def test_ctrl_shift_f6_opens_workspace_rename_preview() -> None:
    app = QApplication.instance() or QApplication([])
    widget = CodeEditorWidget(
        vm=_DefinitionVmStub(),
        asset_key="module://test-guid",
        title="Module",
    )
    calls: list[bool] = []
    widget._preview_workspace_rename = lambda: calls.append(True)
    widget.show()
    widget._edit.setFocus()
    app.processEvents()

    QTest.keyClick(
        widget._edit,
        Qt.Key.Key_F6,
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.ShiftModifier,
    )
    app.processEvents()

    assert calls == [True]


def test_workspace_rename_applies_preview_and_reloads_persisted_module(
    monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    source = "Function LoadSettings() Export\nEndFunction\n"
    vm = _EditorVmStub(text=source)
    calls: list[dict] = []

    class _Service:
        def plan_workspace_symbol_rename(self, module_guid: str, **options):
            calls.append({"stage": "plan", "module_guid": module_guid, **options})
            return {
                "module_count": 1,
                "occurrence_count": 1,
                "modules": [
                    {
                        "module_guid": module_guid,
                        "source_hash": "source-hash",
                        "updated_hash": "updated-hash",
                        "occurrences": [
                            {
                                "line": 1,
                                "preview": "Function LoadSettings() Export",
                                "declaration": True,
                            }
                        ],
                    }
                ],
            }

        def apply_workspace_symbol_rename(self, module_guid: str, **options):
            calls.append({"stage": "apply", "module_guid": module_guid, **options})
            vm._text = source.replace("LoadSettings", "ReadSettings")
            return {"updated": 1, "occurrence_count": 1}

    vm._service = _Service()
    widget = CodeEditorWidget(
        vm=vm,
        asset_key="module://module-1",
        title="SettingsServer",
    )
    cursor = widget._edit.textCursor()
    cursor.setPosition(source.index("LoadSettings"))
    widget._edit.setTextCursor(cursor)
    monkeypatch.setattr(
        "src.ui_qt.widgets.code_editor_widget.QInputDialog.getText",
        lambda *_args, **_kwargs: ("ReadSettings", True),
    )
    monkeypatch.setattr(
        "src.ui_qt.widgets.semantic_rename_dialog.request_workspace_rename_apply",
        lambda *_args, **_kwargs: True,
    )

    widget._preview_workspace_rename()
    app.processEvents()

    assert [item["stage"] for item in calls] == ["plan", "apply"]
    assert calls[1]["modules"][0]["source_hash"] == "source-hash"
    assert widget._edit.toPlainText() == vm._text
    assert "ReadSettings" in widget._edit.toPlainText()
    assert widget.is_dirty() is False


def test_code_editor_widget_builds_and_loads_module_text() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub()
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget.show()
    app.processEvents()

    assert vm.calls == ["module://test-guid"]
    assert "Процедура Тест" in widget._edit.toPlainText()
    assert widget._diag_panel.font().pointSize() == 9
    assert widget._lang_combo.count() == 2
    assert [widget._lang_combo.itemText(i) for i in range(widget._lang_combo.count())] == ["UK", "EN"]


def test_code_editor_uses_resizable_ide_workbench_and_real_toolbar_icons() -> None:
    app = QApplication.instance() or QApplication([])
    widget = CodeEditorWidget(vm=_EditorVmStub(), asset_key="module://test-guid", title="Module")
    widget.show()
    app.processEvents()

    assert widget._workbench_split.orientation() == Qt.Orientation.Vertical
    assert widget._workbench_split.indexOf(widget._edit) == 0
    assert widget._workbench_split.indexOf(widget._debug_context_tabs) == 1
    assert widget._workbench_split.indexOf(widget._diag_panel) == 2
    assert not widget._btn_check.icon().isNull()
    assert not widget._btn_bp_params.icon().isNull()
    assert not widget._btn_close.icon().isNull()
    assert widget.minimumSizeHint().width() <= 740
    assert not widget._btn_bp_clear.isVisible()
    assert not widget._btn_bp_move_up.isVisible()


def test_ctrl_f7_runs_code_check() -> None:
    app = QApplication.instance() or QApplication([])
    widget = CodeEditorWidget(vm=_EditorVmStub(), asset_key="module://test-guid", title="Module")
    widget.show()
    widget._edit.setFocus()
    app.processEvents()
    calls: list[str] = []
    widget._on_check = lambda: calls.append("check")

    QTest.keyClick(widget._edit, Qt.Key.Key_F7, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()

    assert calls == ["check"]


def test_code_editor_discard_close_clears_dirty_state(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    widget = CodeEditorWidget(vm=_EditorVmStub(), asset_key="module://test-guid", title="Module")
    widget._edit.setPlainText("local draft")
    app.processEvents()
    monkeypatch.setattr(
        "src.ui_qt.widgets.code_editor_widget.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )

    assert widget.confirm_close() is True
    assert widget.is_dirty() is False


def test_code_editor_initial_load_failure_stays_empty_and_clean() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _FailingEditorVmStub()

    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    app.processEvents()

    assert widget._edit.toPlainText() == ""
    assert widget.state.is_dirty is False
    assert widget.state.is_loaded is False
    assert "modules.get_text" in widget.state.last_load_error
    assert " *" not in widget._lbl_title.text()


def test_code_editor_reload_failure_preserves_loaded_dirty_buffer() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _FailingEditorVmStub(text="persisted text")
    vm.fail_reads = False
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget._edit.setPlainText("local draft")
    app.processEvents()
    vm.fail_reads = True

    assert widget.reload() is False

    assert widget._edit.toPlainText() == "local draft"
    assert widget.state.is_dirty is True
    assert widget.state.is_loaded is True
    assert "modules.get_text" in widget.state.last_load_error


def test_get_text_asset_module_path_raises_instead_of_returning_empty(monkeypatch) -> None:
    vm = _AssetsVmStub()

    def _broken_get_module_text(module_guid: str) -> str:
        raise RuntimeError(f"boom:{module_guid}")

    monkeypatch.setattr(vm._service, "get_module_text", _broken_get_module_text)

    with pytest.raises(RuntimeError, match="Failed to load module text"):
        vm.get_text_asset("module://module-guid")


def test_get_text_asset_resolves_stale_owner_guid_module_key(monkeypatch) -> None:
    vm = _AssetsVmStub()
    vm._service.modules_by_owner["owner-guid"] = [
        {"module_guid": "real-module-guid", "lang": "", "storage_kind": "inline"}
    ]
    vm._service.module_texts["real-module-guid"] = "Процедура Тест()\nКінецьПроцедури"

    text, mime, resolved = vm.get_text_asset("module://owner-guid")

    assert "Процедура Тест" in text
    assert mime == "text/plain"
    assert resolved == "module://real-module-guid"


def test_get_text_asset_prefers_manifest_module_payload(monkeypatch) -> None:
    vm = _AssetsVmStub()
    vm._service.manifest_get_payload = lambda guid: {
        "module": {"asset_key": "module://real-module-guid"},
        "title": "AppModule",
    } if guid == "owner-guid" else {}

    def _fail_owner_scan(*_args, **_kwargs):
        raise AssertionError("owner scan should not run when manifest payload has module.asset_key")

    monkeypatch.setattr(vm._service, "list_modules_by_owner", _fail_owner_scan)
    vm._service.module_texts["real-module-guid"] = "Процедура Тест()\nКінецьПроцедури"

    text, mime, resolved = vm.get_text_asset("module://owner-guid")

    assert "Процедура Тест" in text
    assert mime == "text/plain"
    assert resolved == "module://real-module-guid"


def test_save_text_asset_resolves_stale_owner_guid_module_key(monkeypatch) -> None:
    vm = _AssetsVmStub()
    vm._service.modules_by_owner["owner-guid"] = [
        {"module_guid": "real-module-guid", "lang": "", "storage_kind": "inline"}
    ]

    vm.save_text_asset("module://owner-guid", "new text")

    assert vm._service.updated_modules == [("real-module-guid", "new text", "user")]


def test_code_editor_widget_saves_using_resolved_module_key() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub(resolved_key="module://real-module-guid")
    widget = CodeEditorWidget(vm=vm, asset_key="module://owner-guid", title="Module")
    saved: list[str] = []
    widget.saved.connect(saved.append)
    widget.show()
    app.processEvents()

    widget._edit.setPlainText("Процедура Тест()\nКонецПроцедури")
    assert widget.save() is True
    app.processEvents()

    assert vm.save_calls
    assert vm.save_calls[0][0] == "module://real-module-guid"
    assert saved == ["module://real-module-guid"]


def test_code_editor_widget_save_confirms_persisted_text_from_vm() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub(resolved_key="module://real-module-guid")
    widget = CodeEditorWidget(vm=vm, asset_key="module://owner-guid", title="Module")
    widget.show()
    app.processEvents()

    widget._edit.setPlainText("Процедура Тест()\nКонецПроцедури")
    assert widget.save() is True
    app.processEvents()

    assert vm.save_calls
    assert vm.calls == ["module://owner-guid", "module://real-module-guid"]
    assert widget.state.is_dirty is False


def test_code_editor_widget_failed_save_keeps_dirty_buffer() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _FailingEditorVmStub(text="persisted text")
    vm.fail_reads = False
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget._edit.setPlainText("local draft")
    app.processEvents()
    vm.fail_writes = True

    assert widget.save() is False

    assert widget._edit.toPlainText() == "local draft"
    assert widget.state.is_dirty is True


def test_code_editor_widget_reload_from_vm_aliases_reload() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub(text="Процедура Перезавантаження()\nКінецьПроцедури")
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget._edit.setPlainText("dirty")
    assert widget.reload_from_vm() is True
    app.processEvents()

    assert "Перезавантаження" in widget._edit.toPlainText()
    assert vm.calls == ["module://test-guid", "module://test-guid"]


def test_autocomplete_activation_inserts_full_completion() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub()
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget.show()
    app.processEvents()

    widget._edit.setPlainText("Як")
    cursor = widget._edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    widget._edit.setTextCursor(cursor)
    widget._edit.apply_autocomplete_completion("Якщо")
    app.processEvents()

    assert widget._edit.toPlainText() == "Якщо"


def test_autocomplete_completes_metadata_chain_after_dot() -> None:
    app = QApplication.instance() or QApplication([])
    widget = CodeEditorWidget(vm=_EditorVmStub(), asset_key="module://test-guid", title="Module")
    widget.show()
    widget._edit.setPlainText("Metadata.Ca")
    cursor = widget._edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    widget._edit.setTextCursor(cursor)

    widget._edit.trigger_autocomplete(force=True)
    model = widget._edit._autocomplete_completer.model()
    assert "Catalogs" in model.stringList()

    widget._edit.apply_autocomplete_completion("Catalogs")
    app.processEvents()
    assert widget._edit.toPlainText() == "Metadata.Catalogs"


def test_autocomplete_uses_cached_manifest_names_for_metadata_collection() -> None:
    app = QApplication.instance() or QApplication([])
    widget = CodeEditorWidget(vm=_EditorVmStub(), asset_key="module://test-guid", title="Module")
    widget._edit.set_autocomplete_metadata_objects({"catalog": ["Products", "Customers"]})
    widget._edit.setPlainText("Метадані.Довідники.")
    cursor = widget._edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    widget._edit.setTextCursor(cursor)

    widget._edit.trigger_autocomplete(force=True)
    assert "Products" in widget._edit._autocomplete_completer.model().stringList()


def test_autocomplete_loads_exported_common_module_members_once() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub(text="SettingsServer.Re")
    calls: list[str] = []

    class _Service:
        def get_common_module_completion(self, name: str):
            calls.append(name)
            return {
                "found": True,
                "members": [
                    {"name": "ReadSettings", "kind": "function"},
                    {"name": "ResetCache", "kind": "procedure"},
                ],
            }

    vm._service = _Service()
    widget = CodeEditorWidget(
        vm=vm,
        asset_key="module://test-guid",
        title="Module",
    )
    cursor = widget._edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    widget._edit.setTextCursor(cursor)

    widget._edit.trigger_autocomplete(force=True)
    first = widget._edit._autocomplete_completer.model().stringList()
    widget._edit.trigger_autocomplete(force=True)
    app.processEvents()

    assert "ReadSettings" in first
    assert "ResetCache" in first
    assert calls == ["SettingsServer"]


def test_metadata_completion_index_exposes_repaired_onec_object_name() -> None:
    broken_title = "Контрагенты".encode("cp1251").decode("latin1")
    vm = type(
        "Vm",
        (),
        {
            "_objects_snapshot": [
                {
                    "type": "catalog",
                    "kind": "object",
                    "name": "Kontrahenty",
                    "title": broken_title,
                },
                {"type": "catalog", "kind": "folder", "name": "forms", "title": "Forms"},
            ]
        },
    )()

    objects = metadata_completion_objects_from_vm(vm)

    assert objects["catalog"] == ["Kontrahenty", "Контрагенты"]


def test_ctrl_space_triggers_autocomplete_handler() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub()
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget.show()
    widget._edit.setFocus()
    app.processEvents()

    calls: list[bool] = []

    def _record(force: bool = False) -> None:
        calls.append(bool(force))

    widget._edit._autocomplete_handler = _record
    QTest.keyClick(widget._edit, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()

    assert calls == [True]


def test_code_templates_are_localized_and_choose_free_counter_name() -> None:
    uk = templates_for("uk", "Змін Счетчик Експорт;")
    loop = next(item for item in uk if item.key == "for")
    assert "Для Сч = 0 По Значення Цикл" in loop.body
    assert "КінецьЦиклу" in loop.body

    en = templates_for("en", "Var Counter;")
    loop_en = next(item for item in en if item.key == "for")
    assert "For I = 0 To Value Do" in loop_en.body
    assert "EndDo" in loop_en.body

    text, offset = expand_template(next(item for item in uk if item.key == "if"))
    assert "Якщо Умова Тоді" in text
    assert text[offset - len("Умова"):offset] == "Умова"


def test_enter_auto_indents_ukrainian_block_and_dedents_else() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub()
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget.show()
    widget._edit.setPlainText("Якщо Умова Тоді")
    cursor = widget._edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    widget._edit.setTextCursor(cursor)
    QTest.keyClick(widget._edit, Qt.Key.Key_Return)
    widget._edit.insertPlainText("Сообщить(1);")
    QTest.keyClick(widget._edit, Qt.Key.Key_Return)
    widget._edit.insertPlainText("Інакше")
    QTest.keyClick(widget._edit, Qt.Key.Key_Return)
    assert widget._edit.toPlainText() == "Якщо Умова Тоді\n    Сообщить(1);\nІнакше\n    "
    widget.deleteLater()


def test_tab_indents_selected_block_instead_of_replacing_it() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub()
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget.show()
    widget._edit.setPlainText("line1\nline2")
    cursor = widget._edit.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(len("line1\nline2"), QTextCursor.MoveMode.KeepAnchor)
    widget._edit.setTextCursor(cursor)
    widget._edit.setFocus()
    app.processEvents()

    QTest.keyClick(widget._edit, Qt.Key.Key_Tab)
    app.processEvents()

    assert widget._edit.toPlainText() == "    line1\n    line2"


def test_shift_tab_outdents_selected_block() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub()
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget.show()
    widget._edit.setPlainText("    line1\n    line2")
    cursor = widget._edit.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(len("    line1\n    line2"), QTextCursor.MoveMode.KeepAnchor)
    widget._edit.setTextCursor(cursor)
    widget._edit.setFocus()
    app.processEvents()

    QTest.keyClick(widget._edit, Qt.Key.Key_Backtab)
    app.processEvents()

    assert widget._edit.toPlainText() == "line1\nline2"


def test_tab_indents_lines_when_only_code_fragment_is_selected() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub()
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget.show()
    widget._edit.setPlainText("alpha\nbeta")
    cursor = widget._edit.textCursor()
    cursor.setPosition(2)
    cursor.setPosition(len("alpha\nbe"), QTextCursor.MoveMode.KeepAnchor)
    widget._edit.setTextCursor(cursor)
    widget._edit.setFocus()
    app.processEvents()

    QTest.keyClick(widget._edit, Qt.Key.Key_Tab)
    app.processEvents()

    assert widget._edit.toPlainText() == "    alpha\n    beta"


def test_code_editor_gutter_is_compact_and_line_numbers_area_present() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub()
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget.show()
    widget._edit.setPlainText("\n".join(f"line {i}" for i in range(1, 250)))
    app.processEvents()

    width = widget._edit.line_number_area_width()
    assert width > 0
    assert width <= 64


def test_code_editor_check_parses_imported_bsl_in_mixed_mode() -> None:
    app = QApplication.instance() or QApplication([])
    bsl_text = (
        "#Область Test\n"
        "ЗаписьЖурналаРегистрации(Событие, Уровень,,, Подробно);\n"
        "Сообщить(НСтр(\"ru='Ошибка'\" \n"
        "\";uk='Помилка'\"));\n"
        "#КонецОбласти\n"
    )
    vm = _EditorVmStub(text=bsl_text)
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget.show()
    app.processEvents()
    widget._on_check()
    app.processEvents()

    assert not widget._diag_panel.isVisible()
    assert widget._status.text() in {
        "OK",
        "✓ No errors",
        "✓ Без помилок",
    }


def test_module_assets_use_internal_mixed_profile_without_public_mixed_option() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _EditorVmStub(text="Если Истина Тогда\nКонецЕсли\n")
    widget = CodeEditorWidget(vm=vm, asset_key="module://test-guid", title="Module")
    widget.show()
    app.processEvents()

    assert widget._effective_module_language() == "mixed"
    assert [widget._lang_combo.itemText(i) for i in range(widget._lang_combo.count())] == ["UK", "EN"]


def test_code_template_tab_moves_between_editable_placeholders() -> None:
    app = QApplication.instance() or QApplication([])
    edit = _CodeEdit()
    edit.setPlainText("")
    edit.show()
    app.processEvents()

    cursor = edit.textCursor()
    cursor.insertText("Name Condition Value")
    edit.setTextCursor(cursor)
    assert edit._activate_snippet_stops("Name Condition Value", 0)
    assert edit.textCursor().selectedText() == "Name"

    QTest.keyClick(edit, Qt.Key.Key_Tab)
    assert edit.textCursor().selectedText() == "Condition"
    QTest.keyClick(edit, Qt.Key.Key_Tab)
    assert edit.textCursor().selectedText() == "Value"
    QTest.keyClick(edit, Qt.Key.Key_Tab)
    assert not edit.textCursor().hasSelection()
    edit.deleteLater()
