from __future__ import annotations

"""src.configurator.persistence.config_storage_tables

Tables for the 1C-like "Configuration Storage" (a separate Mpdb file).

The Mpdb engine is append-only, therefore all tables below are designed as
event logs. The current state is obtained by reading the latest row per key.

The storage contains only configuration artifacts (object/components snapshots)
and is intentionally independent from the MainDB.
"""

import time
from typing import Any, Dict

from src.mpdb.mpdb import Mpdb, MpdbError


COMMITS_TABLE = "storage_commits"
REVISIONS_TABLE = "storage_item_revisions"
HEAD_TABLE = "storage_items"

# Optional helper table to link locks to sessions/clients.
# The lock table itself is shared across modules and intentionally kept minimal.
# Therefore we store session attribution in a dedicated append-only log.
LOCK_OWNERSHIP_TABLE = "storage_lock_ownership"


def _now_ms() -> int:
    return int(time.time() * 1000)


def ensure_config_storage_tables(db: Mpdb) -> None:
    """Ensure configuration storage tables exist."""

    _ensure_table(
        db,
        COMMITS_TABLE,
        {
            "commit_id": {"type": "str", "unique": True, "indexed": True},
            "ts": {"type": "int", "indexed": True},
            "user_id": {"type": "str", "indexed": True},
            "message": {"type": "str"},
        },
    )

    _ensure_table(
        db,
        REVISIONS_TABLE,
        {
            "commit_id": {"type": "str", "indexed": True},
            "lock_key": {"type": "str", "indexed": True},
            "ts": {"type": "int", "indexed": True},
            "user_id": {"type": "str", "indexed": True},
            "message": {"type": "str"},
            "payload": {"type": "json"},
            "payload_hash": {"type": "str", "indexed": True},
        },
    )

    # "Head" is an event log as well; the latest row per lock_key is the current state.
    _ensure_table(
        db,
        HEAD_TABLE,
        {
            "lock_key": {"type": "str", "indexed": True},
            "commit_id": {"type": "str", "indexed": True},
            "ts": {"type": "int", "indexed": True},
            "user_id": {"type": "str", "indexed": True},
            "payload_hash": {"type": "str", "indexed": True},
        },
    )

    _ensure_table(
        db,
        LOCK_OWNERSHIP_TABLE,
        {
            "id": {"type": "str", "unique": True, "indexed": True},
            "ts": {"type": "int", "indexed": True},
            "lock_key": {"type": "str", "indexed": True},
            "user_id": {"type": "str", "indexed": True},
            "session_id": {"type": "str", "indexed": True},
            "client_id": {"type": "str", "indexed": True},
        },
    )


def _ensure_table(db: Mpdb, name: str, schema: Dict[str, Any]) -> None:
    """Create table if missing."""

    try:
        db.create_table(name, schema)
    except MpdbError:
        # Exists.
        return
