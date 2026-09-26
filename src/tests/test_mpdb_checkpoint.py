from __future__ import annotations

import os


def test_checkpoint_truncates_wal_and_keeps_data(tmp_path) -> None:
    from mpdb.mpdb import Mpdb, META_WAL, META_NEXT_PAGE_ID, HEADER_SIZE

    db_path = str(tmp_path / "checkpoint.mpdb")
    db = Mpdb(db_path)
    try:
        db.create_table("t", {"fields": {"name": {"type": "str", "indexed": True}}})
        db.table("t").insert({"name": "a"})
        db.table("t").insert({"name": "b"})

        wal = db._meta[META_WAL]
        assert int(wal["end"]) >= int(wal["start"])
        # We expect some WAL data to exist after writes.
        assert int(wal["end"]) > int(wal["start"])

        # Full checkpoint: truncate WAL.
        db.checkpoint(durable=False)

        wal2 = db._meta[META_WAL]
        assert int(wal2["end"]) == int(wal2["start"])

        # Physical truncation must remove WAL tail.
        end_of_pages = HEADER_SIZE + (int(db._meta[META_NEXT_PAGE_ID]) - 1) * db.page_size
        assert os.path.getsize(db_path) == int(end_of_pages)

        # Data still visible.
        rows = db.query("t", order_by="name")
        assert [r["name"] for r in rows] == ["a", "b"]
    finally:
        db.close()
