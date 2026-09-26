from __future__ import annotations

import json

from src.infra.onec.com_data_audit import (
    ONEC_COM_DATA_AUDIT_ASSET_KEY,
    build_com_data_audit,
    store_com_data_audit_asset,
)
from src.infra.onec.com_source import COMMetaObject
from src.mpdb.mpdb import Mpdb


class _FakeCOMConnection:
    config_name = "Demo"
    config_version = "1.0"

    def __init__(self) -> None:
        self.queries: list[str] = []
        self._objects = [
            COMMetaObject(obj_type="catalog", name="Goods", synonyms={"uk": "Товари"}, uuid="cat-1"),
            COMMetaObject(obj_type="document", name="Invoice", synonyms={"uk": "Накладна"}, uuid="doc-1"),
            COMMetaObject(obj_type="enumeration", name="Status", synonyms={"uk": "Статус"}, uuid="enum-1"),
            COMMetaObject(obj_type="constants", name="MainCurrency", synonyms={}, uuid="const-1"),
        ]

    def list_all_metadata(self, *, include_attrs: bool = True):
        assert include_attrs is False
        return list(self._objects)

    def query(self, text: str):
        self.queries.append(text)
        if "Catalog.Goods" in text:
            raise RuntimeError("english query disabled in fake")
        if "Справочник.Goods" in text and "КОЛИЧЕСТВО" in text:
            return [{"RowCount": "2"}]
        if "Справочник.Goods" in text and "ПЕРВЫЕ" in text:
            return [{"Ref": "goods-1", "Description": "Goods 1"}]
        if "Document.Invoice" in text and "COUNT" in text:
            return [{"RowCount": 1}]
        if "Document.Invoice" in text and "TOP" in text:
            return [{"Ref": "doc-1", "Number": "0001"}]
        if "Enum.Status" in text and "COUNT" in text:
            return [{"RowCount": 2}]
        if "Enum.Status" in text and "TOP" in text:
            return [{"Ref": "status-1", "Description": "Status 1"}]
        raise RuntimeError(f"unexpected query: {text}")


def test_build_com_data_audit_compares_com_counts_with_direct_migration() -> None:
    conn = _FakeCOMConnection()
    direct = {
        "summary": {"tables_imported": 2, "rows_imported": 2},
        "storage_mode": "packed",
        "packed_table": "onec__data_rows",
        "tables": [
            {"kind": "catalog", "source_rows": 2, "imported_rows": 1},
            {"kind": "document", "source_rows": 1, "imported_rows": 1},
            {"kind": "enum", "source_rows": 2, "imported_rows": 1},
        ],
    }

    report = build_com_data_audit(
        conn,
        direct_migration=direct,
        include_samples=True,
        sample_limit=1,
    )

    assert report["summary"]["metadata_objects_seen"] == 4
    assert report["summary"]["counted_objects"] == 3
    assert report["summary"]["unsupported_objects"] == 1
    assert report["summary"]["rows_visible_via_com"] == 5
    assert any("Справочник.Goods" in query for query in conn.queries)
    by_type = {row["type"]: row for row in report["comparison"]["by_type"]}
    assert by_type["catalog"]["diff_vs_imported"] == 1
    assert by_type["enumeration"]["diff_vs_imported"] == 1
    goods = next(row for row in report["objects"] if row["name"] == "Goods")
    assert goods["row_count"] == 2
    assert goods["sample_rows"][0]["Description"] == "Goods 1"


def test_store_com_data_audit_asset_roundtrips(tmp_path) -> None:
    db = Mpdb(tmp_path / "audit.mpdb")
    try:
        report = {"summary": {"rows_visible_via_com": 3}}
        asset_key = store_com_data_audit_asset(db, report)
        payload, mime = db.get_asset(ONEC_COM_DATA_AUDIT_ASSET_KEY)
        assert asset_key == ONEC_COM_DATA_AUDIT_ASSET_KEY
        assert mime == "application/json"
        assert json.loads(payload.decode("utf-8"))["summary"]["rows_visible_via_com"] == 3
    finally:
        db.close()
