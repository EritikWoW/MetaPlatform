from __future__ import annotations

import datetime as dt
import json
import os
import struct
from decimal import Decimal
from pathlib import Path

import pytest

from src.infra.onec.parser.database_parser import OneCDatabase
from src.infra.onec.parser.schema_reader import SchemaReader
from src.infra.onec.parser.value_decoder import to_json_safe


def _write_database(path: Path, version: str) -> bytes:
    """Small real 1CD page graphs: root, descriptor and three numeric rows."""
    modern = version == "8.3.8.0"
    page_size = 8192 if modern else 4096
    pages = [bytearray(page_size) for _ in range(6 if modern else 11)]
    struct.pack_into("<8s4bIi", pages[0], 0, b"1CDBMSV8", *map(int, version.split(".")), len(pages), 1)
    if modern:
        struct.pack_into("<I", pages[0], 20, page_size)
    data_object = 4 if modern else 8
    descriptor = (
        '{"T",0,\n{"Fields",\n{"VALUE","N",0,5,3,"CS"}\n},\n'
        '{"Indexes",\n{"VAL",1,\n{"VALUE",3}\n}\n},\n'
        f'{{"Recordlock","1"}},\n{{"Files",{data_object},0,0}}\n}}'
    )
    # An eight-byte hidden version follows the deleted marker.
    rows = b"".join(
        bytes([deleted]) + b"\0" * 8 + number
        for deleted, number in ((0, bytes.fromhex("184723")), (1, bytes.fromhex("110000")), (0, bytes.fromhex("000091")))
    )

    def object_header(number: int, data_page: int, length: int) -> None:
        if modern:
            struct.pack_into("<2sH3IQI", pages[number], 0, b"\x1c\xfd", 0, 0, 0, 0, length, data_page)
        else:
            struct.pack_into("<8si", pages[number], 0, b"1CDBOBV8", length)
            struct.pack_into("<I", pages[number], 24, number + 1)
            struct.pack_into("<iI", pages[number + 1], 0, 1, data_page)

    root_payload = struct.pack("<32sii", b"en", 1, 2 if modern else 5)
    if modern:
        object_header(2, 3, 1024)
        for chunk, payload in ((1, root_payload), (2, descriptor.encode("utf-8"))):
            assert len(payload) <= 250
            struct.pack_into("<Ih", pages[3], chunk * 256, 0, len(payload))
            pages[3][chunk * 256 + 6:chunk * 256 + 6 + len(payload)] = payload
        object_header(4, 5, len(rows))
        pages[5][:len(rows)] = rows
    else:
        object_header(2, 4, len(root_payload))
        pages[4][:len(root_payload)] = root_payload
        encoded = descriptor.encode("utf-16-le")
        object_header(5, 7, len(encoded))
        pages[7][:len(encoded)] = encoded
        object_header(8, 10, len(rows))
        pages[10][:len(rows)] = rows
    data = b"".join(pages)
    path.write_bytes(data)
    return data


@pytest.mark.parametrize("version", ["8.2.14.0", "8.3.8.0"])
def test_internal_reader_streams_both_formats_without_modifying_source(tmp_path: Path, version: str) -> None:
    path = tmp_path / "custom-name.1CD"
    original = _write_database(path, version)
    with OneCDatabase(str(path)) as db:
        assert db._fh is not None and db._fh.mode == "rb"
        assert db._description_errors == []
        assert db.get_table_names() == ["T"]
        assert db.get_total_rows("T") == 3
        table = db.get_table_info("T")
        assert table is not None
        assert table.row_size == 12
        assert table.fields[0].offset == 9
        assert table.indexes[0].fields[0].name == "VALUE"
        assert [row["VALUE"] for row in db.iter_table_rows("T", decode=False)] == [Decimal("84.723"), Decimal("-0.091")]
        assert len(list(db.iter_table_rows("T", include_deleted=True))) == 3
        assert db.get_table_data("T", limit=0) == []
        assert db.get_table_data("T", limit=1, offset=2)[0]["VALUE"] == "-0.091"
        export_path = tmp_path / "schema.json"
        db.export_structure(str(export_path))
        assert json.loads(export_path.read_text(encoding="utf-8"))["tables"]["T"]["indexes"][0]["fields"][0]["name"] == "VALUE"
    assert path.read_bytes() == original


@pytest.mark.parametrize("export", ["structure", "json", "csv", "schema"])
@pytest.mark.parametrize("alias", [False, True])
def test_exports_cannot_overwrite_source_or_hardlink(tmp_path: Path, export: str, alias: bool) -> None:
    path = tmp_path / "source.1CD"
    original = _write_database(path, "8.3.8.0")
    target = tmp_path / "alias.json" if alias else path
    if alias:
        os.link(path, target)
    with OneCDatabase(str(path)) as db:
        with pytest.raises(ValueError, match="read-only 1CD source"):
            if export == "structure":
                db.export_structure(str(target))
            elif export == "json":
                db.export_table_json("T", str(target))
            elif export == "csv":
                db.export_table_csv("T", str(target))
            else:
                SchemaReader(db).export(str(target))
    assert path.read_bytes() == original


def test_failed_reopen_closes_handle_and_clears_previous_tables(tmp_path: Path) -> None:
    path = tmp_path / "source.1CD"
    _write_database(path, "8.3.8.0")
    db = OneCDatabase(str(path))
    assert db.open()
    old_handle = db._fh
    db.filepath = str(tmp_path / "missing.1CD")
    assert db.open() is False
    assert old_handle is not None and old_handle.closed
    assert db._fh is None
    assert db.tables == {}
    assert db.header is None
    assert db.last_error


@pytest.mark.parametrize("value,expected", [(dt.date(2026, 9, 27), "2026-09-27"), (dt.time(12, 34, 56), "12:34:56")])
def test_json_safe_date_and_time(value: dt.date | dt.time, expected: str) -> None:
    assert to_json_safe(value) == expected
