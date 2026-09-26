from __future__ import annotations

import random

from mpdb.mpdb import Mpdb, MpdbError


def test_btree_index_point_lookup(tmp_path):
    db_path = tmp_path / "btree1.mpdb"
    db = Mpdb(db_path, page_size=4096, compression="zlib:6", cache_mb=8)
    db.create_table(
        "items",
        {
            "code": {"indexed": True},
            "name": {},
        },
    )
    t = db.table("items")

    # Insert enough distinct keys to force multiple leaf splits.
    keys = [f"K{n:04d}" for n in range(400)]
    random.shuffle(keys)
    for k in keys:
        t.insert({"code": k, "name": f"Name {k}"})

    # Point lookups should return exactly one row.
    for k in ("K0000", "K0001", "K0123", "K0399"):
        rows = db.query("items", {"code": k})
        assert len(rows) == 1
        assert rows[0]["code"] == k

    db.verify_integrity()
    db.close()


def test_btree_index_duplicate_bucket(tmp_path):
    db_path = tmp_path / "btree2.mpdb"
    db = Mpdb(db_path, page_size=4096, compression="zlib:6", cache_mb=8)
    db.create_table(
        "events",
        {
            "type": {"indexed": True},
            "payload": {},
        },
    )
    t = db.table("events")

    for i in range(50):
        t.insert({"type": "click", "payload": {"i": i}})
    for i in range(20):
        t.insert({"type": "view", "payload": {"i": i}})

    rows_click = db.query("events", {"type": "click"})
    rows_view = db.query("events", {"type": "view"})
    assert len(rows_click) == 50
    assert len(rows_view) == 20

    db.verify_integrity()
    db.close()


def test_empty_secondary_index_result_falls_back_to_table_scan(tmp_path, monkeypatch):
    db_path = tmp_path / "btree-stale-index.mpdb"
    db = Mpdb(db_path, page_size=4096, compression="zlib:6", cache_mb=8)
    db.create_table(
        "items",
        {
            "code": {"type": "str", "unique": True},
            "name": {"type": "str"},
        },
    )
    table = db.table("items")
    table.insert({"code": "A", "name": "Original"})

    monkeypatch.setattr(table, "_try_index", lambda _where: set())

    assert table.select(where={"code": "A"}) == [{"code": "A", "name": "Original"}]
    assert table.update({"code": "A"}, {"name": "Updated"}) == 1
    assert table.select(where={"code": "A"}) == [{"code": "A", "name": "Updated"}]
    assert table.delete({"code": "A"}) == 1
    assert table.select(where={"code": "A"}) == []

    db.close()


def test_broken_secondary_index_falls_back_to_table_scan(tmp_path, monkeypatch):
    db_path = tmp_path / "btree-broken-index.mpdb"
    db = Mpdb(db_path, page_size=4096, compression="zlib:6", cache_mb=8)
    db.create_table(
        "items",
        {
            "code": {"type": "str", "unique": True},
            "name": {"type": "str"},
        },
    )
    table = db.table("items")
    table.insert({"code": "A", "name": "Original"})

    def broken_index(_where):
        raise MpdbError("broken secondary index")

    monkeypatch.setattr(table, "_try_index", broken_index)

    assert table.select(where={"code": "A"}) == [{"code": "A", "name": "Original"}]
    assert table.update({"code": "A"}, {"name": "Updated"}) == 1
    assert table.select(where={"code": "A"}) == [{"code": "A", "name": "Updated"}]
    assert table.delete({"code": "A"}) == 1
    assert table.select(where={"code": "A"}) == []

    db.close()


def test_indexed_point_read_uses_rowid_locator_before_stale_data_page(tmp_path):
    db_path = tmp_path / "btree-stale-data-page.mpdb"
    db = Mpdb(db_path, page_size=4096, compression="zlib:6", cache_mb=8)
    db.create_table(
        "items",
        {
            "code": {"type": "str", "unique": True},
            "name": {"type": "str"},
        },
    )
    table = db.table("items")
    table.insert({"code": "A", "name": "Original"})

    db._meta["tables"]["items"]["data_pages"].insert(0, 999_999)

    assert table.select(where={"code": "A"}) == [{"code": "A", "name": "Original"}]

    db._meta["tables"]["items"]["data_pages"].pop(0)
    db.close()
