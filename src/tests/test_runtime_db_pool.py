from __future__ import annotations

import shutil

import pytest

from src.runtime.server_state import DbPool, SessionStore
from src.mpdb.mpdb import Mpdb, MpdbError


def test_db_pool_replace_with_file_swaps_prepared_database(tmp_path):
    live_path = tmp_path / "live.mpdb"
    pool = DbPool()
    db_uid, _name = pool.open_by_path(str(live_path))
    live_db = pool.get(db_uid)
    live_db.create_table("old_table", {"fields": {"value": {"type": "str"}}})
    old_page_id = int(live_db._meta["root"])
    assert live_db._read_page(old_page_id)
    live_db.checkpoint(durable=True, keep_wal_bytes=0)

    backup_path = tmp_path / "live.backup.mpdb"
    staging_path = tmp_path / "live.staging.mpdb"
    shutil.copy2(live_path, backup_path)
    shutil.copy2(live_path, staging_path)

    staging_db = Mpdb(str(staging_path))
    try:
        staging_db.create_table("new_table", {"fields": {"value": {"type": "str"}}})
        staging_db.checkpoint(durable=True, keep_wal_bytes=0)
    finally:
        staging_db.close()

    swapped_db = pool.replace_with_file(db_uid, str(staging_path), backup_path=str(backup_path))
    try:
        assert "new_table" in swapped_db._meta["tables"]
        assert backup_path.exists()
        assert not staging_path.exists()
        with pytest.raises(MpdbError, match="closed"):
            live_db._read_page(old_page_id)
    finally:
        swapped_db.close()


def test_db_pool_keeps_pool_identity_when_replacement_has_different_internal_uid(tmp_path):
    live_path = tmp_path / "live.mpdb"
    staging_path = tmp_path / "staging.mpdb"
    pool = DbPool()
    pool_uid, _name = pool.open_by_path(str(live_path))
    live_db = pool.get(pool_uid)
    live_db.checkpoint(durable=True, keep_wal_bytes=0)

    staging_db = Mpdb(str(staging_path))
    replacement_uid = staging_db.db_uid
    staging_db.checkpoint(durable=True, keep_wal_bytes=0)
    staging_db.close()
    assert replacement_uid != pool_uid

    swapped_db = pool.replace_with_file(pool_uid, str(staging_path))
    try:
        assert swapped_db.db_uid == replacement_uid
        assert pool.get_path(pool_uid) == str(live_path)
        assert pool.get(pool_uid) is swapped_db
        assert pool.open_by_path(str(live_path))[0] == pool_uid
    finally:
        swapped_db.close()


def test_db_pool_rejects_replacement_with_corrupt_page_without_closing_live(tmp_path):
    live_path = tmp_path / "live.mpdb"
    pool = DbPool()
    db_uid, _name = pool.open_by_path(str(live_path))
    live_db = pool.get(db_uid)
    live_db.create_table("old_table", {"fields": {"value": {"type": "str"}}})
    live_db.table("old_table").insert({"value": "kept"})
    live_db.checkpoint(durable=True, keep_wal_bytes=0)

    staging_path = tmp_path / "live.staging.mpdb"
    shutil.copy2(live_path, staging_path)
    # Page 2 is a valid allocated page in this fixture (the table schema
    # asset). Corrupting its magic models the live failure without depending
    # on a particular row-storage strategy.
    page_id = 2
    page_offset = 128 + (page_id - 1) * live_db.page_size
    with staging_path.open("r+b") as stream:
        stream.seek(page_offset)
        stream.write(b"\x00")

    with pytest.raises(MpdbError, match="offline integrity validation"):
        pool.replace_with_file(db_uid, str(staging_path))

    assert pool.get(db_uid) is live_db
    assert live_db._opened is True
    assert "old_table" in live_db._meta["tables"]
    assert staging_path.exists()


def test_db_pool_rolls_back_when_opening_activated_file_corrupts_it(tmp_path, monkeypatch):
    live_path = tmp_path / "live.mpdb"
    pool = DbPool()
    db_uid, _name = pool.open_by_path(str(live_path))
    live_db = pool.get(db_uid)
    live_db.create_table("old_table", {"fields": {"value": {"type": "str"}}})
    live_db.table("old_table").insert({"value": "kept"})
    live_db.checkpoint(durable=True, keep_wal_bytes=0)

    backup_path = tmp_path / "live.backup.mpdb"
    staging_path = tmp_path / "live.staging.mpdb"
    shutil.copy2(live_path, backup_path)
    shutil.copy2(live_path, staging_path)
    staging_db = Mpdb(str(staging_path))
    staging_db.create_table("new_table", {"fields": {"value": {"type": "str"}}})
    staging_db.checkpoint(durable=True, keep_wal_bytes=0)
    staging_db.close()

    real_mpdb = Mpdb

    class CorruptOnceMpdb(real_mpdb):
        should_corrupt = True

        def __init__(self, path, *args, **kwargs):
            super().__init__(path, *args, **kwargs)
            if self.should_corrupt and str(path) == str(live_path):
                type(self).should_corrupt = False
                page_offset = 128 + self.page_size
                with open(path, "r+b") as stream:
                    stream.seek(page_offset)
                    stream.write(b"\x00")

    monkeypatch.setattr("src.runtime.server_state.Mpdb", CorruptOnceMpdb)

    with pytest.raises(MpdbError, match="Activated DB failed"):
        pool.replace_with_file(db_uid, str(staging_path), backup_path=str(backup_path))

    restored = pool.get(db_uid)
    try:
        assert "old_table" in restored._meta["tables"]
        assert "new_table" not in restored._meta["tables"]
    finally:
        restored.close()


def test_db_pool_reuses_live_handle_for_repeated_path_open(tmp_path):
    db_path = tmp_path / "shared.mpdb"
    pool = DbPool()

    first_uid, _ = pool.open_by_path(str(db_path))
    first_db = pool.get(first_uid)
    second_uid, _ = pool.open_by_path(str(db_path))
    second_db = pool.get(second_uid)

    try:
        assert second_uid == first_uid
        assert second_db is first_db
        assert len(pool.list_open()) == 1
    finally:
        first_db.close()


def test_session_store_close_forgets_only_target_session() -> None:
    sessions = SessionStore()
    first = sessions.create()
    second = sessions.create()
    sessions.set_active_db_uid(first, "db-1")
    sessions.set_active_db_uid(second, "db-2")

    assert sessions.close(first) is True
    assert sessions.close(first) is False
    assert sessions.get_active_db_uid(first) is None
    assert sessions.get_active_db_uid(second) == "db-2"
