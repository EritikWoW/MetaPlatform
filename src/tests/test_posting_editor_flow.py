from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMdiArea

from src.configurator.domain.posting_constructor import generate_posting_handler
from src.ui_qt.services.posting_module_editor import (
    insert_document_posting_handler, resolve_document_object_module,
)
from src.ui_qt.widgets.code_editor_widget import CodeEditorWidget
from src.ui_qt.widgets.document_editor import DocumentEditorWidget
from src.ui_qt.widgets.catalog_editor import CatalogEditorWidget


class Vm:
    def __init__(self):
        self._service = self
        self.text = "Procedure Helper()\nEndProcedure\n"
        self.writes = []
        self.reads = []
        self.objects = [
            SimpleNamespace(guid="doc", kind="object", type="document", name="Sales", parent_guid="", payload={}),
            SimpleNamespace(guid="folder", kind="folder", type="document", name="modules", parent_guid="doc", payload={}),
            SimpleNamespace(guid="node", kind="object", type="module", name="ObjectModule", parent_guid="folder", payload={}),
            SimpleNamespace(guid="manager", kind="object", type="module", name="ManagerModule", parent_guid="folder", payload={}),
        ]

    def list_objects(self):
        return self.objects

    def list_subsystems(self):
        return []

    def list_modules_by_owner(self, guid):
        assert guid == "doc"
        return [{"module_guid": "executable", "owner_guid": "doc", "module_kind": "ObjectModule"},
                {"module_guid": "manager-code", "owner_guid": "doc", "module_kind": "ManagerModule"}]

    def manifest_get_payload(self, guid):
        self.reads.append(guid)
        return {"owner_guid": "doc", "module": {"asset_key": "module://" + (
            "executable" if guid == "node" else "manager-code")}}

    def get_text_asset(self, key):
        assert key == "module://executable"
        return self.text, "text/metascript", key

    def save_text_asset(self, key, text, *, mime):
        self.writes.append(key)
        self.text = text


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_resolver_uses_exact_object_module_asset_and_skips_manager():
    vm = Vm()
    target = resolve_document_object_module(vm, "doc")
    assert target.manifest_guid == "node"
    assert target.asset_key == "module://executable"
    assert vm.reads == ["node", "manager"]
    assert not vm.writes


def test_resolver_refuses_missing_or_ambiguous_targets():
    vm = Vm()
    vm.objects[2].parent_guid = "unrelated"
    with pytest.raises(ValueError):
        resolve_document_object_module(vm, "doc")
    vm = Vm()
    vm.manifest_get_payload = lambda guid: {"module_kind": "ObjectModule", "module": {"asset_key": f"module://{guid}"}}
    vm.list_modules_by_owner = lambda _: []
    with pytest.raises(ValueError):
        resolve_document_object_module(vm, "doc")


def test_insert_reuses_dirty_editor_supports_undo_and_save_reload(app):
    vm = Vm()
    editor = CodeEditorWidget(vm=vm, asset_key="module://executable")
    cursor = editor._edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText("// unsaved work\n")
    before = editor._edit.toPlainText()
    mdi = QMdiArea()
    sub = mdi.addSubWindow(editor)
    host = SimpleNamespace(_vm=vm, _open_windows={"node": sub}, mdi=mdi,
                           show_warning=lambda *args: pytest.fail(str(args)),
                           _open_module_by_guid=lambda *args: pytest.fail("Must reuse the open buffer"))
    code = generate_posting_handler(["AccumulationRegister.Sales"], language="en")
    assert insert_document_posting_handler(host, "doc", code)
    assert editor._edit.toPlainText().startswith(before)
    assert editor.is_dirty()
    assert not vm.writes
    editor._edit.undo()
    assert editor._edit.toPlainText() == before
    editor._edit.redo()
    assert editor.save()
    assert vm.writes == ["module://executable"]
    reopened = CodeEditorWidget(vm=vm, asset_key="module://executable")
    assert reopened._edit.toPlainText() == editor._edit.toPlainText()
    assert not reopened.insert_posting_handler(code)
    assert vm.writes == ["module://executable"]
    reopened.deleteLater()
    mdi.deleteLater()


@pytest.mark.parametrize("bad", [
    "Procedure Posting(Cancel, Mode)",
    'Text = "unterminated', "/* unfinished", "Procedure Other()\nEndFunction",
])
def test_insertion_refuses_damaged_module_without_touching_buffer(app, bad):
    vm = Vm()
    vm.text = bad
    editor = CodeEditorWidget(vm=vm, asset_key="module://executable")
    assert not editor.insert_posting_handler(generate_posting_handler(["AccumulationRegister.Sales"]))
    assert editor._edit.toPlainText() == bad
    assert not vm.writes
    editor.deleteLater()


def test_insertion_refuses_invalid_draft_and_failed_load(app):
    vm = Vm()
    editor = CodeEditorWidget(vm=vm, asset_key="module://executable")
    assert not editor.insert_posting_handler("Procedure Posting()\nEndProcedure")
    assert not editor.insert_posting_handler("Procedure Posting(Cancel, Mode)")
    code = generate_posting_handler(["AccumulationRegister.Sales"])
    assert not editor.insert_posting_handler(code + "\nRun();")
    editor._state.last_load_error = "Runtime unavailable"
    assert not editor.insert_posting_handler(code)
    assert editor._edit.toPlainText() == vm.text
    editor.deleteLater()


@pytest.mark.parametrize("widget_class", [DocumentEditorWidget, CatalogEditorWidget])
def test_subsystems_use_guids_not_duplicate_labels_and_keep_pending_selection(app, widget_class):
    subs = [
        {"guid": "a", "name": "First", "title": "Same", "path": "Same", "parent_guid": ""},
        {"guid": "b", "name": "Second", "title": "Same", "path": "Same", "parent_guid": ""},
        {"guid": "c", "name": "Child", "path": "Same / Child", "parent_guid": "b"},
        {"guid": "x", "name": "CycleX", "parent_guid": "y"},
        {"guid": "y", "name": "CycleY", "parent_guid": "x"},
    ]
    original = deepcopy(subs)
    widget = widget_class("Sales", payload={"name": "Sales", "subsystems": ["missing"]}, available_subsystems=subs)
    items = {item.data(0, Qt.ItemDataRole.UserRole): item for item in widget._iter_subsystem_items()}
    assert len(items) == 6
    assert items["c"].parent() is items["b"]
    assert items["x"].parent() is None
    assert items["y"].parent() is items["x"]
    items["c"].setCheckState(0, Qt.CheckState.Checked)
    widget._load_to_ui()
    assert set(widget._shell.pending_patch()["subsystems"]) == {"c", "missing"}
    assert set(widget._payload_raw["subsystems"]) == {"c", "missing"}
    assert subs == original
    widget.deleteLater()


def test_movements_selection_filter_remove_and_draft_restore(app):
    vm = Vm()
    vm.objects.append(SimpleNamespace(guid="reg", kind="object", type="register_accum",
        name="PhysicalAlias", title="User synonym", parent_guid="",
        payload={"source_name": "Sales", "metadata_ref": "AccumulationRegister.Sales"}))
    payload = {"name": "Sales", "register_records": ["AccumulationRegister.Sales"]}
    widget = DocumentEditorWidget("Sales", payload=payload, vm=vm, obj_guid="doc")
    assert widget.tree_register_records.topLevelItem(0).child(0).text(0) == "Sales"
    assert widget.table_movements.rowCount() == 1
    widget.ed_register_search.setText("not present")
    assert widget._checked_register_records() == ["AccumulationRegister.Sales"]
    widget._generate_posting_handler()
    assert widget.btn_insert_posting.isEnabled()
    code = widget.ed_posting_handler.toPlainText()
    widget.ed_posting_handler.appendPlainText("// manual draft note")
    saved = {**payload, **widget._shell.pending_patch()}
    restored = DocumentEditorWidget("Sales", payload=saved, vm=vm, obj_guid="doc")
    assert restored.ed_posting_handler.toPlainText() == code + "\n// manual draft note"
    assert restored.btn_insert_posting.isEnabled()
    emitted = []
    restored.postingModuleRequested.connect(emitted.append)
    restored._insert_posting_handler()
    assert len(emitted) == 1
    restored.table_movements.selectRow(0)
    restored._remove_selected_movements()
    assert restored.table_movements.rowCount() == 0
    assert restored._payload_raw["register_records"] == []
    assert not restored.btn_insert_posting.isEnabled()
    assert not vm.writes
    widget.deleteLater()
    restored.deleteLater()
