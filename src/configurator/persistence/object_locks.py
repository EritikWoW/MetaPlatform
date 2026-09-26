from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.mpdb.mpdb import Mpdb, MpdbError

from .system_tables import AUDIT_LOG_TABLE, OBJECT_LOCKS_TABLE, audit_log


def _now_ms() -> int:
    """Return current time as milliseconds since Unix epoch."""

    return int(time.time() * 1000)


@dataclass(frozen=True)
class LockKey:
    """Structured lock identifier.

    The lock key is hierarchical and supports component-level collaboration.
    The effective string form is:

        <object_type>/<object_id>/<component_type>/<component_id>

    Where component_id may be '-' for singleton components (e.g. ObjectModule).
    """

    object_type: str
    object_id: str
    component_type: str
    component_id: str

    def as_string(self) -> str:
        """Return canonical string representation."""

        ot = (self.object_type or "").strip()
        oid = (self.object_id or "").strip()
        ct = (self.component_type or "").strip() or "Object"
        cid = (self.component_id or "").strip() or "-"
        return f"{ot}/{oid}/{ct}/{cid}"


def parse_lock_key(lock_key: str) -> Optional[LockKey]:
    """Parse canonical lock key string into LockKey.

    Args:
        lock_key: Canonical string in format:
            <object_type>/<object_id>/<component_type>/<component_id>

    Returns:
        LockKey instance, or None if the string is invalid.

    Notes:
        This helper is intentionally tolerant (trims whitespace) and returns
        None instead of raising, because it is frequently used by UI glue.
    """

    lk = str(lock_key or "").strip()
    if not lk:
        return None
    parts = [p.strip() for p in lk.split("/")]
    if len(parts) != 4:
        return None
    ot, oid, ct, cid = parts
    if not ot or not oid:
        return None
    return LockKey(object_type=ot, object_id=oid, component_type=ct or "Object", component_id=cid or "-")


def make_lock_key(
    *,
    object_type: str,
    object_id: str,
    component_type: str,
    component_id: str | None = None,
) -> LockKey:
    """Create a canonical LockKey."""

    return LockKey(
        object_type=(object_type or "").strip(),
        object_id=(object_id or "").strip(),
        component_type=(component_type or "").strip(),
        component_id=(component_id or "-").strip() or "-",
    )


def _conflicts(a: str, b: str) -> bool:
    """Return True if hierarchical keys conflict.

    Conflict rule:
      - exact match
      - one key is a prefix of the other (component hierarchy)
    """

    if a == b:
        return True
    if a.startswith(b + "/"):
        return True
    if b.startswith(a + "/"):
        return True
    return False


def acquire_object_lock(
    db: Mpdb,
    *,
    key: LockKey,
    user_id: str,
    lock_token: str,
    comment: str = "",
) -> None:
    """Acquire a durable object/component lock.

    Raises:
        MpdbError: if an incompatible lock already exists.
    """

    lock_key = key.as_string()
    object_id = key.object_id
    t = db.table(OBJECT_LOCKS_TABLE)

    # We only need to scan locks for the same object_id.
    existing = t.select(where={"object_id": object_id, "state": "active"}) or []
    for row in existing:
        other = str(row.get("lock_key") or "")
        if other and _conflicts(lock_key, other):
            raise MpdbError(f"Lock conflict: {other}")

    t.insert(
        {
            "lock_key": lock_key,
            "object_type": key.object_type,
            "object_id": key.object_id,
            "component_type": key.component_type,
            "component_id": key.component_id,
            "lock_token": lock_token,
            "locked_by": str(user_id or ""),
            "locked_at": _now_ms(),
            "last_heartbeat_at": _now_ms(),
            "state": "active",
            "comment": str(comment or ""),
        }
    )

    audit_log(
        db,
        user_id=str(user_id or ""),
        action="LOCK_ACQUIRE",
        entity_type="ObjectLock",
        entity_id=lock_key,
        payload={
            "object_type": key.object_type,
            "object_id": key.object_id,
            "component_type": key.component_type,
            "component_id": key.component_id,
        },
    )


def heartbeat_object_lock(db: Mpdb, *, lock_key: str, lock_token: str) -> bool:
    """Update last_heartbeat_at for a lock.

    Returns True if updated.
    """

    lock_key = (lock_key or "").strip()
    lock_token = (lock_token or "").strip()
    if not lock_key or not lock_token:
        return False
    t = db.table(OBJECT_LOCKS_TABLE)
    rows = t.select(where={"lock_key": lock_key}) or []
    if not rows:
        return False
    row = rows[0]
    if str(row.get("lock_token") or "") != lock_token:
        return False
    if str(row.get("state") or "") != "active":
        return False
    t.update(where={"lock_key": lock_key}, set_values={"last_heartbeat_at": _now_ms()})
    return True


def release_object_lock(
    db: Mpdb,
    *,
    lock_key: str,
    lock_token: str,
    user_id: str,
    force: bool = False,
) -> bool:
    """Release a lock.

    If force=False, only the owner with the matching token can release.
    """

    lock_key = (lock_key or "").strip()
    lock_token = (lock_token or "").strip()
    if not lock_key:
        return False
    t = db.table(OBJECT_LOCKS_TABLE)
    rows = t.select(where={"lock_key": lock_key}) or []
    if not rows:
        return False
    row = rows[0]

    if str(row.get("state") or "") != "active":
        return False

    if not force:
        if str(row.get("lock_token") or "") != lock_token:
            return False
        if str(row.get("locked_by") or "") != str(user_id or ""):
            return False

    t.update(where={"lock_key": lock_key}, set_values={"state": "released", "last_heartbeat_at": _now_ms()})

    audit_log(
        db,
        user_id=str(user_id or ""),
        action="LOCK_RELEASE_FORCE" if force else "LOCK_RELEASE",
        entity_type="ObjectLock",
        entity_id=lock_key,
        payload={"force": bool(force)},
    )
    return True


def list_object_locks(db: Mpdb, *, object_id: str | None = None, state: str = "active") -> List[Dict[str, Any]]:
    """List locks (optionally filtered by object_id and state)."""

    t = db.table(OBJECT_LOCKS_TABLE)
    where: Dict[str, Any] = {"state": str(state or "").strip() or "active"}
    if object_id:
        where["object_id"] = str(object_id or "").strip()
    try:
        rows = t.select(where=where) or []
    except Exception:
        rows = []
    return rows


def get_lock(db: Mpdb, *, lock_key: str) -> Optional[Dict[str, Any]]:
    """Return lock row for lock_key (if any)."""

    lock_key = (lock_key or "").strip()
    if not lock_key:
        return None
    rows = db.table(OBJECT_LOCKS_TABLE).select(where={"lock_key": lock_key}) or []
    return rows[0] if rows else None
