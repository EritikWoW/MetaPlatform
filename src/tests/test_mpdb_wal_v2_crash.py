from __future__ import annotations

import os
import struct

import pytest


def _read_meta_wal_pointers(db_path: str) -> tuple[int, int]:
    # Import locally to keep test collection fast.
    from mpdb.mpdb import Mpdb, META_WAL

    db = Mpdb(db_path)
    try:
        wal = db._meta[META_WAL]
        return int(wal["start"]), int(wal["end"])
    finally:
        db.close()


def test_wal_v2_ignores_partial_tail_record(tmp_path) -> None:
    """If the process crashes mid-write of the last WAL record, recovery must stop
    cleanly and still apply all fully-written committed txns."""

    from mpdb.mpdb import Mpdb, WAL_MAGIC

    db_path = str(tmp_path / "crash_partial.mpdb")

    db = Mpdb(db_path)
    db.create_table("t", {"fields": {"name": {"type": "str", "indexed": True}}})
    db.table("t").insert({"name": "a"})
    db.table("t").insert({"name": "b"})
    # Capture current EOF and then close.
    db.close()

    eof = os.path.getsize(db_path)

    # Append a *partial* WAL v2 record at EOF (simulate crash during record write).
    with open(db_path, "r+b") as f:
        f.seek(eof)
        f.write(WAL_MAGIC)  # only 4 bytes of what should be a full header
        f.flush()

    # Reopen + recover should ignore the partial tail and still see committed rows.
    db2 = Mpdb(db_path)
    try:
        rows = db2.query("t", order_by="name")
        assert [r["name"] for r in rows] == ["a", "b"]
    finally:
        db2.close()


def test_recovery_ignores_uncommitted_txn(tmp_path) -> None:
    """BEGIN + some WAL records without COMMIT must not be applied on recovery."""

    from mpdb.mpdb import (
        Mpdb,
        PT_DATA,
        WAL_BEGIN,
        WAL_PUT_PAGE,
        _data_page_init,
        _data_page_insert,
        _is_data_slot_page,
        PAGE_HDR_SIZE,
    )

    db_path = str(tmp_path / "crash_uncommitted.mpdb")
    db = Mpdb(db_path)
    db.create_table("t", {"fields": {"name": {"type": "str"}}})

    # Manually create an uncommitted WAL txn that would add a DATA page.
    txid = 0xABCDEF1234
    max_payload = db.page_size - PAGE_HDR_SIZE
    page_payload = _data_page_init(max_payload)
    page_payload, slot_pos = _data_page_insert(page_payload, b'{"rowid":1,"data":{}}')
    assert _is_data_slot_page(page_payload)

    pid = db._alloc_page_id()
    db._wal_append(WAL_BEGIN, txid, b"")
    hdr = struct.pack("<QI", int(pid), int(PT_DATA))
    db._wal_append(WAL_PUT_PAGE, txid, hdr + page_payload)
    db.close()

    # Recovery must not apply the page because there's no COMMIT.
    db2 = Mpdb(db_path)
    try:
        # The table has no rows.
        assert db2.query("t") == []
    finally:
        db2.close()


def test_recovery_uses_relocated_wal_after_crash_before_meta_switch(tmp_path) -> None:
    """If WAL relocation crashes after copying the new WAL, recovery must use it.

    This reproduces the dangerous window where META still points to the old WAL
    range, but the old overlapping prefix has already been cleared for page use.
    """

    from mpdb.mpdb import (
        META_NEXT_PAGE_ID,
        Mpdb,
        PAGE_HDR_SIZE,
        PT_DATA,
        WAL_RELOCATE_INTENT,
        _data_page_init,
    )

    db_path = str(tmp_path / "crash_relocated_wal.mpdb")
    db = Mpdb(db_path, page_size=4096, compression="zlib:6", cache_mb=4)
    db.create_table("t", {"fields": {"name": {"type": "str"}}})
    db.table("t").insert({"name": "a"})

    tx = db.transaction()
    tx.__enter__()
    try:
        new_pid = int(db._meta[META_NEXT_PAGE_ID])
        db._meta[META_NEXT_PAGE_ID] = new_pid + 1
        tx.put_page(new_pid, PT_DATA, _data_page_init(db.page_size - PAGE_HDR_SIZE))
        tx.set_meta(db._meta)

        state = {"seen_intent": False, "intent_syncs": 0}
        orig_append = db._wal_append
        orig_sync = db._sync_file

        def patched_append(rec_type: int, txid: int, payload: bytes) -> int:
            pos = orig_append(rec_type, txid, payload)
            if int(rec_type) == int(WAL_RELOCATE_INTENT):
                state["seen_intent"] = True
            return pos

        def patched_sync() -> None:
            orig_sync()
            if state["seen_intent"]:
                state["intent_syncs"] += 1
                if state["intent_syncs"] == 2:
                    raise RuntimeError("simulated crash after relocated WAL copy")

        db._wal_append = patched_append  # type: ignore[method-assign]
        db._sync_file = patched_sync  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="simulated crash"):
            tx.commit()
    finally:
        try:
            if db._file is not None:
                db._file.flush()
                db._file.close()
        finally:
            db._file = None
            db._opened = False

    db2 = Mpdb(db_path, page_size=4096, compression="zlib:6", cache_mb=4)
    try:
        rows = db2.query("t", order_by="name")
        assert [r["name"] for r in rows] == ["a"]
        db2.verify_integrity()
        pages_end = 128 + (int(db2._meta["next_page_id"]) - 1) * int(db2.page_size)
        assert int(db2._wal_start) >= pages_end
    finally:
        db2.close()
