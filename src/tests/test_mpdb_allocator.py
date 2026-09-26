import threading

from mpdb.doctor import check
from mpdb.mpdb import ASSETS_TABLE, PT_DATA, Mpdb, Table


def test_free_list_reuse(tmp_path) -> None:
    path = tmp_path / "reuse.mpdb"
    db = Mpdb(path, page_size=4096, compression="zlib:6", cache_mb=4)
    db.create_table("t", {"fields": {"v": {"type": "str"}}})

    # Force allocation of at least one data page.
    rowid1 = db.table("t").insert({"v": "a" * 2000})
    assert rowid1 == 1

    # Store an asset, then overwrite it to trigger transactional free of blob pages.
    db.put_asset("assets/x.bin", b"x" * 8000, mime="application/octet-stream")
    db.put_asset("assets/x.bin", b"y" * 10, mime="application/octet-stream")

    legacy_free = len(db._meta.get("free_pages", []))
    fl = db._meta.get("freelist", {})
    fl_count = int(fl.get("count") or 0) if isinstance(fl, dict) else 0
    free_before = legacy_free + fl_count
    assert free_before >= 1

    # Insert again; allocator should be able to reuse freed pages without corruption.
    _ = db.table("t").insert({"v": "b" * 2000})
    db.verify_integrity()
    db.close()

    # Reopen and verify again.
    db2 = Mpdb(path, page_size=4096, compression="zlib:6", cache_mb=4)
    db2.verify_integrity()
    db2.close()


def test_text_assets_are_transparently_compressed(tmp_path) -> None:
    path = tmp_path / "compressed_asset.mpdb"
    db = Mpdb(path, page_size=4096, compression="zlib:6", cache_mb=4)

    payload = (
        b'{"items":['
        + b'{"id":1,"name":"Alpha","value":"'
        + (b"A" * 4000)
        + b'"},'
        + b'{"id":2,"name":"Beta","value":"'
        + (b"B" * 4000)
        + b'"}]'
    )

    db.put_asset("assets/config.json", payload, mime="application/json")
    stored_row = db.table(ASSETS_TABLE).select(where={"key": "assets/config.json"})[0]
    restored, mime = db.get_asset("assets/config.json")

    assert mime == "application/json"
    assert restored == payload
    assert int(stored_row["size"]) < len(payload)
    db.close()


def test_assets_written_in_migration_fast_mode_remain_addressable(tmp_path) -> None:
    path = tmp_path / "fast_mode_assets.mpdb"
    db = Mpdb(path, page_size=4096, compression="zlib:6", cache_mb=4)

    db._migration_fast_mode = True
    db.put_assets_bulk([
        ("assets/fast.json", b'{"ok":true}', "application/json"),
    ])
    db._migration_fast_mode = False

    payload, mime = db.get_asset("assets/fast.json")
    assert payload == b'{"ok":true}'
    assert mime == "application/json"
    assert "assets/fast.json" in db.list_assets("assets/")
    db.close()

    reopened = Mpdb(path, page_size=4096, compression="zlib:6", cache_mb=4)
    payload, mime = reopened.get_asset("assets/fast.json")
    assert payload == b'{"ok":true}'
    assert mime == "application/json"
    assert "assets/fast.json" in reopened.list_assets("assets/")
    reopened.close()


def test_asset_point_read_uses_indexes_without_locator_table_scan(tmp_path, monkeypatch) -> None:
    db = Mpdb(str(tmp_path / "asset_point_read.mpdb"))
    db.put_asset("assets/indexed.json", b'{"ok":true}', mime="application/json")

    original_select = Table.select

    def reject_asset_scan(self, *args, **kwargs):
        if self.name == ASSETS_TABLE:
            raise AssertionError("asset locator table must not be scanned for an indexed point read")
        return original_select(self, *args, **kwargs)

    monkeypatch.setattr(Table, "select", reject_asset_scan)

    data, mime = db.get_asset("assets/indexed.json")

    assert data == b'{"ok":true}'
    assert mime == "application/json"
    db.close()


def test_wal_relocated_when_pages_grow(tmp_path) -> None:
    """Growing the pages region must never overwrite WAL.

    This test creates WAL records and then forces page allocations in later
    transactions; WAL must be relocated forward as needed.
    """

    path = tmp_path / "wal_move.mpdb"
    db = Mpdb(path, page_size=4096, compression="zlib:6", cache_mb=4)
    db.create_table("t", {"fields": {"v": {"type": "str"}}})

    # First insert creates WAL activity.
    db.table("t").insert({"v": "x" * 2000})

    # Repeated inserts force new pages (large rows) and thus page allocations
    # after WAL already contains records.
    for _ in range(20):
        db.table("t").insert({"v": "y" * 3000})

    db.verify_integrity()
    wal_start = int(db._wal_start)
    pages_end = 128 + (int(db._meta["next_page_id"]) - 1) * int(db.page_size)
    assert wal_start >= pages_end

    db.close()

    # Reopen to ensure recovery can still replay and meta pointers are consistent.
    db2 = Mpdb(path, page_size=4096, compression="zlib:6", cache_mb=4)
    db2.verify_integrity()
    db2.close()


def test_transaction_abort_restores_in_memory_meta(tmp_path) -> None:
    path = tmp_path / "tx_abort_meta.mpdb"
    db = Mpdb(path, page_size=4096, compression="zlib:6", cache_mb=4)
    db.create_table("t", {"fields": {"v": {"type": "str"}}})

    before_tables = db._meta["tables"]["t"].copy()

    try:
        with db.transaction() as tx:
            db._meta["tables"]["t"]["data_pages"] = [999]
            tx.set_meta(db._meta)
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    after_tables = db._meta["tables"]["t"]
    assert after_tables["data_pages"] == before_tables["data_pages"]
    db.close()


def test_allocator_skips_invalid_zero_page_ids(tmp_path) -> None:
    path = tmp_path / "invalid_free_page_zero.mpdb"
    db = Mpdb(path, page_size=4096, compression="zlib:6", cache_mb=4)
    db.create_table("t", {"fields": {"v": {"type": "str"}}})

    db._meta.setdefault("free_pages", []).append(0)
    rowid = db.table("t").insert({"v": "x" * 2000})

    assert rowid == 1
    db.verify_integrity()
    db.close()


def test_transaction_holds_allocator_lock_until_page_is_committed(tmp_path) -> None:
    path = tmp_path / "concurrent_allocator.mpdb"
    db = Mpdb(path, page_size=4096, compression="zlib:6", cache_mb=4)
    db.create_table("t", {"fields": {"v": {"type": "str"}}})

    first = db.transaction()
    first.__enter__()
    allocated = db._alloc_page_id()
    second_finished = threading.Event()

    def insert_from_second_thread() -> None:
        db.table("t").insert({"v": "second"})
        second_finished.set()

    worker = threading.Thread(target=insert_from_second_thread)
    worker.start()
    try:
        assert second_finished.wait(0.1) is False
        first.put_page(allocated, PT_DATA, b"")
        first.set_meta(db._meta)
        first.commit()
        assert second_finished.wait(5.0) is True
    finally:
        if first._active:
            first.abort()
        worker.join(timeout=5.0)

    db.checkpoint(durable=True, keep_wal_bytes=0)
    db.close()
    report = check(path)
    assert report.ok, report.issues
