from __future__ import annotations

import hashlib

from src.mpdb.mpdb import PAGE_HDR_SIZE, PT_META, Mpdb


def _wide_schema(field_count: int = 1400) -> dict:
    fields = {
        "anchor": {"type": "str", "indexed": True},
    }
    for idx in range(field_count):
        digest = hashlib.sha1(f"field:{idx}".encode("utf-8")).hexdigest()
        fields[f"field_{idx:04d}_{digest}"] = {"type": "str"}
    return {"fields": fields}


def test_create_table_externalizes_wide_schema_and_keeps_table_usable(tmp_path) -> None:
    path = tmp_path / "wide_schema.mpdb"
    db = Mpdb(str(path))
    schema = _wide_schema()

    db.create_table("wide", schema)
    tinfo = db._meta["tables"]["wide"]

    assert "schema" not in tinfo
    assert str(tinfo.get("schema_ref") or "").startswith("__ts/")

    row = {"anchor": "A-1", "field_0000_5f3f8ce2118d852ec1b23d7dc2a368c3d51f4f39": "hello"}
    db.table("wide").insert(row)
    assert db.table("wide").select(where={"anchor": "A-1"})[0]["anchor"] == "A-1"
    db.verify_integrity()
    db.close()

    db2 = Mpdb(str(path))
    try:
        rows = db2.table("wide").select(where={"anchor": "A-1"})
        assert rows[0]["field_0000_5f3f8ce2118d852ec1b23d7dc2a368c3d51f4f39"] == "hello"
        db2.verify_integrity()
    finally:
        db2.close()


def test_many_external_schema_tables_keep_meta_page_compact(tmp_path) -> None:
    path = tmp_path / "many_external_schema_tables.mpdb"
    db = Mpdb(str(path))
    schema = {"fields": {"value": {"type": "str"}}}

    for idx in range(320):
        table_name = f"onec__physical_{idx:04d}"
        db.create_table(table_name, schema, external_schema=True)
        db.table(table_name).insert({"value": str(idx)})

    db.checkpoint(durable=True, keep_wal_bytes=0)
    payload = db._encode_meta(db._meta)
    need = PAGE_HDR_SIZE + len(db._compressor.compress(payload))
    assert need <= db.page_size
    db.close()

    db2 = Mpdb(str(path))
    try:
        assert db2.table("onec__physical_0319").select(where={"rowid": 1})[0]["value"] == "319"
        db2.verify_integrity()
    finally:
        db2.close()


def test_many_external_schema_tables_fit_meta_page_with_lzma(tmp_path) -> None:
    path = tmp_path / "many_external_schema_tables_lzma.mpdb"
    db = Mpdb(str(path))
    tables = {}
    for idx in range(1200):
        table_name = f"onec__physical_{idx:04d}"
        tables[table_name] = {
            "data_pages": [],
            "next_rowid": idx + 1,
            "schema_ref": f"__ts/{table_name}.json",
        }

    db._meta["tables"] = tables
    payload = db._encode_meta(db._meta)
    assert PAGE_HDR_SIZE + len(db._meta_compressor.compress(payload)) <= db.page_size
    db._write_page(1, PT_META, payload)
    db._write_header()
    db.close()

    db2 = Mpdb(str(path))
    try:
        assert len(db2._meta["tables"]) == 1200
    finally:
        db2.close()


def test_meta_compacts_data_page_ranges_and_expands_back(tmp_path) -> None:
    path = tmp_path / "meta_ranges.mpdb"
    db = Mpdb(str(path))
    pages = list(range(1000, 1525))

    db._meta["tables"]["range_table"] = {
        "data_pages": pages,
        "next_rowid": 1,
        "rowid_index_root": 0,
        "schema": {},
    }

    payload = db._encode_meta(db._meta)
    assert b'"p":[[1000,1524]]' in payload

    decoded = db._decode_meta(payload)
    assert decoded["tables"]["range_table"]["data_pages"] == pages
    db.close()
