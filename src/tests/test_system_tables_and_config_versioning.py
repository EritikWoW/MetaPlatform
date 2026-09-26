from __future__ import annotations

import tempfile
from pathlib import Path

from src.mpdb.mpdb import Mpdb
from src.configurator.persistence.system_tables import (
    AUDIT_LOG_TABLE,
    CONFIG_HEAD_TABLE,
    CONFIG_RELEASES_TABLE,
    ROLES_TABLE,
    USERS_TABLE,
    USER_ROLES_TABLE,
    ensure_system_tables,
    get_active_config_release_id,
    publish_config_release,
)


def test_ensure_system_tables_idempotent() -> None:
    """System tables must be created and re-runnable without side-effects."""

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "t.mpdb"
        db = Mpdb(str(db_path))
        ensure_system_tables(db)
        # Second call should not raise
        ensure_system_tables(db)

        # tables exist
        for name in [USERS_TABLE, ROLES_TABLE, USER_ROLES_TABLE, AUDIT_LOG_TABLE, CONFIG_RELEASES_TABLE, CONFIG_HEAD_TABLE]:
            _ = db.table(name)

        head = db.table(CONFIG_HEAD_TABLE).select(where={"id": "head"})
        assert head and head[0]["id"] == "head"

        db.close()


def test_publish_config_release_sets_active_head() -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "t.mpdb"
        db = Mpdb(str(db_path))
        ensure_system_tables(db)

        assert get_active_config_release_id(db) == ""

        res = publish_config_release(
            db,
            manifest={"version": 1, "objects": []},
            created_by="system",
            comment="initial",
        )
        assert res.active_release_id == res.new_release_id
        assert get_active_config_release_id(db) == res.new_release_id

        # release row exists
        rows = db.table(CONFIG_RELEASES_TABLE).select(where={"release_id": res.new_release_id})
        assert rows and rows[0]["comment"] == "initial"

        db.close()
