import copy
import json
from types import SimpleNamespace

import pytest

from src.runtime.onec_virtual_tables import VirtualOneCDataTables
from src.runtime.server_handlers_table import handle_table_action
from src.runtime.gateway import RuntimeGateway, GatewayDb


@pytest.fixture
def imported():
    owner = {"guid": "doc", "name": "Sales", "type": "document", "payload": {
        "requisites": [
            {"name": "Amount", "imported": {"src_uuid": "amount"}},
            {"name": "Partner", "imported": {"src_uuid": "partner"}},
        ],
        "tabular_parts": [{"name": "Goods", "imported": {"src_uuid": "goods"},
            "columns": [{"name": "Quantity", "imported": {"src_uuid": "quantity"}}]}],
    }}
    migration = {"storage_mode": "packed", "source_path": "missing.1CD", "limit_per_table": 20,
        "storage_bindings": {"amount": {"Fld": 8}, "partner": {"Fld": 4},
            "goods": {"VT": 91}, "quantity": {"Fld": 6}},
        "tables": [
            {"source_table": "_DOCUMENT7", "metadata_uuid": "doc", "logical_name": "SourceSales",
             "kind": "document", "table_role": "object", "imported_rows": 4, "source_rows": 9,
             "field_map": {"_FLD8": "fld8", "_FLD4RREF": "fld4rref"}},
            {"source_table": "_DOCUMENT7_VT91", "metadata_uuid": "doc", "logical_name": "SourceSales",
             "kind": "document", "table_role": "tabular_part", "imported_rows": 1, "source_rows": 1,
             "field_map": {"_FLD6": "fld6", "_DOCUMENT7_IDRREF": "document7_idrref"}},
        ]}
    packed = [{"rowid": i + 1, "__source_table": "_DOCUMENT7", "__source_row_index": i + 1,
        "data": {"idrref": {"uuid": f"record-{i}"}, "number": f"N-{i}", "fld8": 10 + i,
                 "fld4rref": {"uuid": "partner-1", "resolved_name": "Customer"}}} for i in range(4)]
    packed.append({"rowid": 5, "__source_table": "_DOCUMENT7_VT91", "__source_row_index": 1,
        "data": {"document7_idrref": {"uuid": "record-0"}, "lineno92": 1, "fld6": 3}})
    reads = []
    assets = {"onec_data_migration/manifest.json": migration}

    class Table:
        def __init__(self, name):
            self.name = name

        def select(self, where=None, limit=None, **kwargs):
            reads.append((self.name, where, limit))
            rows = [owner] if self.name == "manifest" else packed
            return copy.deepcopy([r for r in rows if not where or all(r.get(k) == v for k, v in where.items())][:limit])

        def select_rowid_range(self, first, last, limit=None):
            reads.append((self.name, (first, last), limit))
            return copy.deepcopy([r for r in packed if first <= r["rowid"] <= last][:limit])

    class DB:
        _meta = {"tables": {}}

        def get_asset(self, key):
            return json.dumps(assets[key]).encode(), "application/json"

        def table(self, name):
            if name not in {"manifest", "onec__data_rows"}:
                raise KeyError(name)
            return Table(name)

    db = DB()
    return SimpleNamespace(db=db, migration=migration, owner=owner, packed=packed,
                           reads=reads, assets=assets, build=lambda: VirtualOneCDataTables(db))


def test_packed_requisites_join_by_uuid_not_order(imported):
    virtual = imported.build()
    handled, rows = virtual.handle_select("data_document_sales", limit=2)
    assert handled
    assert rows[0]["Amount"] == 10
    assert rows[0]["Partner"] == "Customer"
    assert rows[0]["Partner_guid"] == "partner-1"
    assert rows[0]["_partner_raw"]["uuid"] == "partner-1"
    assert rows[0]["fld8"] == 10  # Original imported keys are not rewritten.
    assert virtual.import_status("data_document_sales")["limited"] is True


def test_first_page_does_not_truncate_later_pages_or_point_lookup(imported):
    virtual = imported.build()
    assert len(virtual.handle_select("data_document_sales", limit=1)[1]) == 1
    page = virtual.handle_select("data_document_sales", limit=2, offset=1)[1]
    assert [r["_number"] for r in page] == ["N-1", "N-2"]
    record = virtual.handle_select("data_document_sales", where={"_guid": "record-3"})[1]
    assert record[0]["Amount"] == 13
    assert len(virtual.handle_select("data_document_sales")[1]) == 4
    assert len(virtual.handle_select("data_document_sales", limit=1)[1]) == 1


def test_named_tabular_part_uses_uuid_not_numeric_order(imported):
    virtual = imported.build()
    handled, rows = virtual.handle_select("data_tp_sales_goods", where={"_doc_guid": "record-0"})
    assert handled
    assert rows[0]["Quantity"] == 3
    assert rows[0]["_line_no"] == 1
    assert rows[0]["_owner_guid"] == "record-0"
    assert virtual.handle_select("data_tp_sourcesales_goods")[1] == rows


def test_unrelated_table_does_not_resolve_storage_bindings(imported, monkeypatch):
    imported.migration.pop("storage_bindings")
    monkeypatch.setattr("src.infra.onec.storage_bindings.load_storage_bindings", lambda *_: pytest.fail("unexpected source read"))
    assert imported.build().handle_select("manifest") == (False, [])


def test_missing_legacy_mapping_is_reported_and_not_retried_per_row(imported, monkeypatch):
    imported.migration.pop("storage_bindings")
    calls = []

    def unavailable(path):
        calls.append(path)
        raise FileNotFoundError("missing source")

    monkeypatch.setattr("src.infra.onec.storage_bindings.load_storage_bindings", unavailable)
    virtual = imported.build()
    rows = virtual.handle_select("data_document_sales")[1]
    assert "Amount" not in rows[0]
    assert rows[0]["fld8"] == 10
    assert virtual.import_status("data_document_sales")["binding_error"] == "missing source"
    assert calls == ["missing.1CD"]


def test_no_guessing_duplicate_storage_fields(imported):
    imported.owner["payload"]["requisites"].append({"name": "Other", "imported": {"src_uuid": "amount"}})
    rows = imported.build().handle_select("data_document_sales")[1]
    assert "Amount" not in rows[0] and "Other" not in rows[0]


def test_no_guessing_inactive_variant_storage_fields(imported):
    imported.migration["tables"][0]["field_map"].update({"_FLD8N": "number8", "_FLD8S": "text8"})
    imported.packed[0]["data"].update(number8=12, text8="inactive")
    assert "Amount" not in imported.build().handle_select("data_document_sales")[1][0]


def test_offloaded_rows_bind_exactly_like_inline_rows(imported):
    raw = json.dumps(imported.packed[0].pop("data")).encode()
    db = imported.db
    original = db.get_asset
    db.get_asset = lambda key: (raw, "application/json") if key == "rows.jsonl" else original(key)
    imported.packed[0].update(data_asset="rows.jsonl", data_offset=0, data_size=len(raw))
    assert imported.build().handle_select("data_document_sales", limit=1)[1][0]["Amount"] == 10


def test_metadata_table_rpc_does_not_initialize_business_adapter(imported, monkeypatch):
    monkeypatch.setattr("src.runtime.server_handlers_table.get_virtual_data_tables", lambda *_: pytest.fail("metadata read must bypass import"))
    response = handle_table_action(SimpleNamespace(_require_db=lambda _: imported.db), "table.select", {"table": "manifest"})
    assert response.status == "ok"
    assert response.data["rows"][0]["guid"] == "doc"


def test_rpc_gateway_and_form_bindings_retain_import_status(imported, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from src.client.forms.form_runtime_widget import FormRuntimeWidget, ObjContext

    app = QApplication.instance() or QApplication([])
    virtual = imported.build()
    monkeypatch.setattr("src.runtime.server_handlers_table.get_virtual_data_tables", lambda _: virtual)
    handler = SimpleNamespace(_require_db=lambda _: imported.db)
    gateway = RuntimeGateway("http://not-used")
    gateway.session_id = "test"

    def rpc(action, payload):
        result = handle_table_action(handler, action, payload)
        assert result.status == "ok", result.error
        return result.data

    monkeypatch.setattr(gateway, "_call", rpc)
    model = {"schema_version": 1, "root": {"id": "root", "type": "Container", "children": [
        {"id": "items", "type": "Table", "binding": "items", "props": {"columns": [
            {"name": "Amount"}, {"name": "Partner"}]}}]}}
    widget = FormRuntimeWidget(model=model, db=GatewayDb(gateway),
        ctx=ObjContext(obj_guid="doc", obj_type="document", obj_name="Sales", form_kind="list_form"))
    table = widget._list_table
    assert table.model().index(0, 0).data() == "10"
    assert table.model().index(0, 1).data() == "Customer"
    assert "20" in table._import_warning.text()
    assert not table._import_warning.isHidden()
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_empty_reference_is_not_shown_as_zero_uuid():
    assert VirtualOneCDataTables._ui_value({"uuid": "00000000-0000-0000-0000-000000000000"}) == ""


@pytest.mark.parametrize("failure", ["missing", "truncated", "invalid-json", "invalid-utf8", "not-object"])
def test_corrupt_offloaded_data_is_not_replaced_with_empty_rows(imported, failure):
    imported.packed[0].pop("data")
    raw = {"truncated": b"{}", "invalid-json": b"{x", "invalid-utf8": b'{"x":"\xff"}', "not-object": b"[]"}.get(failure)
    imported.packed[0].update(data_asset="broken", data_offset=0,
                              data_size=10 if failure in {"missing", "truncated"} else len(raw))
    original = imported.db.get_asset
    if raw is not None:
        imported.db.get_asset = lambda key: (raw, "application/json") if key == "broken" else original(key)
    virtual = imported.build()
    with pytest.raises(RuntimeError, match="imported|Imported"):
        virtual.handle_select("data_document_sales", limit=1)
    assert "_DOCUMENT7" not in virtual.source_rows_cache


def test_null_reference_has_no_openable_record_identity(imported):
    imported.packed[0]["data"]["fld4rref"] = {"uuid": "00000000-0000-0000-0000-000000000000"}
    row = imported.build().handle_select("data_document_sales", limit=1)[1][0]
    assert row["Partner"] == ""
    assert "Partner_guid" not in row
