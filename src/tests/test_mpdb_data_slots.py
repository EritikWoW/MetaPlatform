from __future__ import annotations

import pytest


def test_data_pages_use_slot_directory(tmp_path):
    from mpdb.mpdb import Mpdb, PAGE_HDR_SIZE

    path = tmp_path / "test_slots.mpdb"
    db = Mpdb(path, page_size=16384, compression="zlib:6", cache_mb=8)
    db.create_table(
        "t",
        {
            "k": {"indexed": True},
        },
    )

    # Insert enough rows to span multiple pages.
    for i in range(400):
        db.table("t").insert({"k": i, "v": f"val-{i}"})

    # All data pages must be in the new slot-directory format (magic MPDT).
    tinfo = db._meta["tables"]["t"]
    assert tinfo["data_pages"], "expected at least one data page"
    max_payload = db.page_size - PAGE_HDR_SIZE
    for pid in tinfo["data_pages"]:
        payload = db._read_page(int(pid))
        assert len(payload) == max_payload
        assert payload[:4] == b"MPDT"

    # Ensure query still works.
    rows = db.query("t", where={"k": 123})
    assert rows and rows[0]["k"] == 123

    db.close()


def test_closed_database_never_serves_cached_pages(tmp_path):
    from mpdb.mpdb import Mpdb, MpdbError

    path = tmp_path / "closed_cache.mpdb"
    db = Mpdb(path, page_size=16384, compression="zlib:6", cache_mb=8)
    db.create_table("t", {"k": {"indexed": True}})
    db.table("t").insert({"k": 1, "v": "cached"})

    page_id = int(db._meta["tables"]["t"]["data_pages"][0])
    assert db._read_page(page_id)
    assert db._cache.get(page_id) is not None

    db.close()

    with pytest.raises(MpdbError, match="closed"):
        db._read_page(page_id)
