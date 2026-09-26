from __future__ import annotations

import random


from mpdb.mpdb import Mpdb


def test_order_by_uses_index_and_handles_missing_values(tmp_path):
    db_path = tmp_path / "t.mpdb"
    db = Mpdb(db_path, page_size=16384, compression="zlib:6", cache_mb=8)
    db.create_table(
        "t",
        {
            "name": {"type": "str", "indexed": True},
            "qty": {"type": "int"},
        },
    )

    names = ["delta", "alpha", "charlie", "bravo", "echo"]
    random.shuffle(names)

    # Insert rows with and without the order_by field.
    for i, n in enumerate(names):
        db.table("t").insert({"name": n, "qty": i})
    db.table("t").insert({"qty": 999})
    db.table("t").insert({"qty": 1000})

    rows = db.query("t", order_by="name")

    # Verify sorted by name with missing values at the end.
    head = [r.get("name") for r in rows[:5]]
    assert head == sorted(names)

    tail = rows[5:]
    assert all(r.get("name") is None for r in tail)

    db.close()


def test_btree_range_scan(tmp_path):
    db_path = tmp_path / "r.mpdb"
    db = Mpdb(db_path, page_size=16384, compression="zlib:6", cache_mb=8)
    db.create_table(
        "t",
        {
            "name": {"type": "str", "indexed": True},
        },
    )

    for n in ["a", "b", "c", "d", "e", "f", "g"]:
        db.table("t").insert({"name": n})

    # Trigger index creation and then range-scan it.
    _ = db.query("t", where={"name": "a"})

    with db._lock:
        idx = db._meta["indexes"]["t"]["name"]
        root = int(idx["root"])
    from mpdb.mpdb import BTreeIndex

    from mpdb.mpdb import _encode_sort_key

    b = BTreeIndex(db, root)
    keys = [k for k, _bucket in b.iter_items(start=_encode_sort_key("c"), end=_encode_sort_key("f"))]
    assert keys == [_encode_sort_key("c"), _encode_sort_key("d"), _encode_sort_key("e")]

    db.close()


def test_order_by_numeric_is_numeric_not_lexicographic(tmp_path):
    db_path = tmp_path / "num.mpdb"
    db = Mpdb(db_path, page_size=16384, compression="zlib:6", cache_mb=8)
    db.create_table(
        "t",
        {
            "k": {"type": "int", "indexed": True},
            "v": {},
        },
    )
    t = db.table("t")
    t.insert({"k": 2, "v": "two"})
    t.insert({"k": 10, "v": "ten"})
    t.insert({"k": 1, "v": "one"})

    rows = db.query("t", order_by="k")
    assert [r["k"] for r in rows] == [1, 2, 10]
    db.close()
