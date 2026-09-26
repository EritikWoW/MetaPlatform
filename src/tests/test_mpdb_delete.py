from __future__ import annotations


from mpdb.mpdb import Mpdb


def test_delete_by_indexed_field_updates_indexes_and_hides_row(tmp_path):
    db_path = tmp_path / "d.mpdb"
    db = Mpdb(db_path, page_size=16384, compression="zlib:6", cache_mb=8)
    db.create_table(
        "t",
        {
            "name": {"type": "str", "indexed": True},
            "qty": {"type": "int"},
        },
    )

    t = db.table("t")
    r1 = t.insert({"name": "a", "qty": 1})
    r2 = t.insert({"name": "b", "qty": 2})
    r3 = t.insert({"name": "c", "qty": 3})

    assert db.query("t", where={"name": "b"}) == [{"name": "b", "qty": 2}]

    deleted = t.delete({"name": "b"})
    assert deleted == 1

    # row is gone
    assert db.query("t", where={"name": "b"}) == []

    # order_by still works and does not include deleted row
    rows = db.query("t", order_by="name")
    assert [x.get("name") for x in rows] == ["a", "c"]

    # delete by rowid works too
    assert t.delete({"rowid": r1}) == 1
    assert db.query("t", order_by="name") == [{"name": "c", "qty": 3}]

    db.close()
