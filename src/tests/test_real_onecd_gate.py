from __future__ import annotations

import pytest

from src.scripts.real_onecd_gate import _representative_document_report


class _PackedTable:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def select_rowid_range(self, first: int, last: int, limit: int | None = None):
        rows = [
            row
            for row in self._rows
            if first <= int(row.get("rowid") or 0) <= last
        ]
        return rows[:limit] if limit is not None else rows


class _Db:
    def __init__(self, rows: list[dict]) -> None:
        self._table = _PackedTable(rows)

    def table(self, name: str):
        assert name == "onec__data_rows"
        return self._table


def _manifest() -> dict:
    return {
        "packed_table": "onec__data_rows",
        "tables": [
            {
                "source_table": "_REFERENCE1",
                "kind": "catalog",
                "table_role": "object",
                "metadata_uuid": "catalog",
                "logical_name": "Partners",
                "source_rows": 1,
                "_source_row_index": 1,
                "imported_rows": 1,
                "errors": [],
                "limited": False,
            },
            {
                "source_table": "_DOCUMENT7",
                "kind": "document",
                "table_role": "object",
                "metadata_uuid": "doc",
                "logical_name": "RealizaciyaTovarovUslug",
                "logical_title": "Реализация товаров и услуг",
                "source_rows": 3,
                "_source_row_index": 3,
                "imported_rows": 3,
                "errors": [],
                "limited": False,
            },
            {
                "source_table": "_DOCUMENT7_VT91",
                "kind": "document",
                "table_role": "tabular_part",
                "metadata_uuid": "doc",
                "logical_name": "RealizaciyaTovarovUslug",
                "source_rows": 5,
                "_source_row_index": 5,
                "imported_rows": 5,
                "errors": [],
                "limited": False,
            },
        ],
    }


def test_representative_document_report_verifies_document_and_tabular_tables() -> None:
    db = _Db(
        [
            {"rowid": 1, "data": {"idrref": {"uuid": "partner"}}},
            {
                "rowid": 2,
                "data": {
                    "idrref": {"uuid": "doc-1"},
                    "number": "000001",
                    "date_time": "2026-09-27",
                },
            },
        ]
    )

    report = _representative_document_report(
        db,
        _manifest(),
        "Реализация товаров и услуг",
    )

    assert report["source_table"] == "_DOCUMENT7"
    assert report["active_rows"] == 3
    assert report["imported_rows"] == 3
    assert report["sample_fields"] == ["date_time", "idrref", "number"]
    assert report["related_tables"] == [
        {
            "source_table": "_DOCUMENT7_VT91",
            "table_role": "tabular_part",
            "source_rows": 5,
            "active_rows": 5,
            "imported_rows": 5,
        }
    ]


def test_representative_document_report_fails_on_related_row_loss() -> None:
    manifest = _manifest()
    manifest["tables"][2]["imported_rows"] = 4

    with pytest.raises(AssertionError, match="active/imported row mismatch"):
        _representative_document_report(
            _Db([]),
            manifest,
            "RealizaciyaTovarovUslug",
        )
