from copy import deepcopy

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from src.tests.test_posting_mapping import schema, mapping
from src.tests.test_posting_mapping import manifest
from src.tests.test_posting_editor_flow import Vm
from src.ui_qt.widgets.document_editor import DocumentEditorWidget
from src.ui_qt.widgets.posting_mapping_dialog import PostingMappingDialog
from src.tests.test_runtime_posting import setup_db, movements


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def choose(combo, value):
    index = next(i for i in range(combo.count()) if combo.itemData(i) == value)
    combo.setCurrentIndex(index)


def test_mapping_dialog_requires_explicit_direction_and_fields(app):
    dialog = PostingMappingDialog(schema(), language="en")
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    choose(dialog.direction, "expense")
    choose(dialog.fields.cellWidget(0, 2), {"scope": "document", "field": "Date"})
    choose(dialog.fields.cellWidget(1, 2), {"scope": "document", "field": "Сума"})
    assert ok.isEnabled()
    assert dialog.plan() == mapping()
    assert ".Сума = ThisObject.Сума" in dialog.preview.toPlainText()
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.deleteLater()


def test_mapping_dialog_restores_draft_and_preserves_invalid_bindings(app):
    plan = mapping("Lines")
    original = deepcopy(plan)
    dialog = PostingMappingDialog(schema(), plan=plan)
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert dialog.plan() == plan
    choose(dialog.source, "")
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert dialog.fields.cellWidget(1, 2).currentData()["field"] == "Quantity"
    assert plan == original
    dialog.reject()
    assert dialog.result() == dialog.DialogCode.Rejected
    dialog.deleteLater()


def test_configurator_persists_mapping_draft_restores_it_and_blocks_stale_insertion(app, monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QMessageBox
    provider = Vm()
    provider.objects = [SimpleNamespace(**{**dict(kind="object", name="", parent_guid="", payload={}), **r}) for r in manifest()]
    payload = {"name": "Invoice", "register_records": ["AccumulationRegister.Stock"]}
    editor = DocumentEditorWidget("Invoice", payload=payload, vm=provider, obj_guid="doc")
    dialog = PostingMappingDialog(editor._posting_mapping_schema(), plan=mapping(), language="en")
    editor._set_posting_draft(dialog.preview.toPlainText(), payload["register_records"], plan=dialog.plan())
    saved = {**payload, **editor._shell.pending_patch()}
    assert saved["posting_mappings"] == mapping()
    restored = DocumentEditorWidget("Invoice", payload=saved, vm=provider, obj_guid="doc")
    assert restored.ed_posting_handler.toPlainText() == dialog.preview.toPlainText()
    signals = []
    restored.postingModuleRequested.connect(signals.append)
    restored._insert_posting_handler()
    assert signals == [dialog.preview.toPlainText()]
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args))
    provider.objects = [obj for obj in provider.objects if obj.guid != "amount"]
    restored._insert_posting_handler()
    assert errors and len(signals) == 1
    assert not provider.writes
    dialog.deleteLater()
    editor.deleteLater()
    restored.deleteLater()


def test_dialog_to_saved_module_to_real_http_posting(app, setup_db):
    import threading
    from http.server import ThreadingHTTPServer
    from src.configurator.manifest_schema import MANIFEST_TABLE
    from src.runtime.server import RuntimeHandler
    from src.runtime.server_state import RpcResponse
    from src.runtime.gateway import RuntimeGateway
    db, _ = setup_db
    rows = [r for r in manifest() if r["guid"] not in {"parts", "lines", "cols", "qty"}]
    for row in rows:
        if row["guid"] not in {"doc", "reg"}:
            db.table(MANIFEST_TABLE).insert(row)
    dialog = PostingMappingDialog(schema(rows), language="uk")
    choose(dialog.direction, "expense")
    choose(dialog.fields.cellWidget(0, 2), {"scope": "document", "field": "Date"})
    choose(dialog.fields.cellWidget(1, 2), {"scope": "document", "field": "Сума"})
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted

    class Handler(RuntimeHandler):
        def _require_db(self, payload):
            return db if payload.get("session_id") == "test" else RpcResponse("error", error="session required")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    gateway = RuntimeGateway(f"http://127.0.0.1:{server.server_port}")
    gateway.session_id = "test"
    try:
        payload = {"register_records": ["AccumulationRegister.Stock"], "posting_mappings": dialog.plan(),
                   "posting_handler": dialog.preview.toPlainText()}
        gateway.manifest_update_payload("doc", payload)
        assert gateway.manifest_get_payload("doc")["posting_mappings"] == dialog.plan()
        gateway.module_update_text("object-module", dialog.preview.toPlainText())
        assert gateway.module_get_text("object-module") == dialog.preview.toPlainText()
        result = gateway.document_post(doc_name="Invoice", doc_guid="rec")
        assert result.ok, result.messages
        assert movements(db)[0]["Amount"] == 42
        assert gateway.document_post(doc_name="Invoice", doc_guid="rec", post=False).ok
        assert not movements(db)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        dialog.deleteLater()
