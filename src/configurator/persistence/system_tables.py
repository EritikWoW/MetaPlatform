from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.mpdb.mpdb import Mpdb, MpdbError


# ---------------------------------------------------------------------------
# Table names
# ---------------------------------------------------------------------------

USERS_TABLE = "sys_users"
ROLES_TABLE = "sys_roles"
USER_ROLES_TABLE = "sys_user_roles"
AUDIT_LOG_TABLE = "sys_audit_log"

CONFIG_RELEASES_TABLE = "config_releases"
CONFIG_HEAD_TABLE = "config_head"

# Team checkout / locks (optional module; safe to create in any DB)
OBJECT_LOCKS_TABLE = "sys_object_locks"
CHECKOUT_SESSIONS_TABLE = "sys_checkout_sessions"
REPO_CHECKOUTS_TABLE = "repo_checkouts"


def _now_ms() -> int:
    """Return current time as milliseconds since Unix epoch."""

    return int(time.time() * 1000)


def _new_guid() -> str:
    """Generate a UUIDv4 string without importing stdlib uuid.

    Note:
        The project may contain a package named `platform` which can shadow the
        stdlib `uuid` dependency chain in some environments.
    """

    b = bytearray(os.urandom(16))
    b[6] = (b[6] & 0x0F) | 0x40
    b[8] = (b[8] & 0x3F) | 0x80
    h = bytes(b).hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def ensure_users_tables(db: Mpdb) -> None:
    """Ensure core security tables exist.

    This is the minimal foundation required for:
      - attributing configuration changes to users
      - team workflows (optional modules) such as checkout/locks and repo
    """

    _ensure_table(
        db,
        USERS_TABLE,
        {
            "user_id": {"type": "str", "unique": True, "indexed": True},
            "login": {"type": "str", "unique": True, "indexed": True},
            "display_name": {"type": "str"},
            "password_hash": {"type": "str"},
            "is_active": {"type": "bool", "indexed": True},
            "created_at": {"type": "int", "indexed": True},
        },
    )

    _ensure_table(
        db,
        ROLES_TABLE,
        {
            "role_id": {"type": "str", "unique": True, "indexed": True},
            "name": {"type": "str", "unique": True, "indexed": True},
            "description": {"type": "str"},
            "created_at": {"type": "int", "indexed": True},
        },
    )

    _ensure_table(
        db,
        USER_ROLES_TABLE,
        {
            "id": {"type": "str", "unique": True, "indexed": True},
            "user_id": {"type": "str", "indexed": True},
            "role_id": {"type": "str", "indexed": True},
            "created_at": {"type": "int", "indexed": True},
        },
    )

    _ensure_table(
        db,
        AUDIT_LOG_TABLE,
        {
            "event_id": {"type": "str", "unique": True, "indexed": True},
            "ts": {"type": "int", "indexed": True},
            "user_id": {"type": "str", "indexed": True},
            "action": {"type": "str", "indexed": True},
            "entity_type": {"type": "str", "indexed": True},
            "entity_id": {"type": "str", "indexed": True},
            "payload": {"type": "json"},
        },
    )

    _seed_default_roles(db)

    # Ensure a built-in SYSTEM user exists for automated actions.
    _seed_system_user(db)


def ensure_config_versioning_tables(db: Mpdb) -> None:
    """Ensure configuration versioning tables exist.

    Standalone mode requires published configuration to be immutable and
    activations to be atomic. This is achieved by storing published releases in
    CONFIG_RELEASES_TABLE and pointing CONFIG_HEAD_TABLE to the active release.
    """

    _ensure_table(
        db,
        CONFIG_RELEASES_TABLE,
        {
            "release_id": {"type": "str", "unique": True, "indexed": True},
            "created_at": {"type": "int", "indexed": True},
            "created_by": {"type": "str", "indexed": True},
            "comment": {"type": "str"},
            "base_release_id": {"type": "str", "indexed": True},
            "manifest": {"type": "json"},
            "hash": {"type": "str", "indexed": True},
            "source_repo_commit_id": {"type": "str", "indexed": True},
            "source_repo_tag": {"type": "str", "indexed": True},
        },
    )

    _ensure_table(
        db,
        CONFIG_HEAD_TABLE,
        {
            "id": {"type": "str", "unique": True, "indexed": True},
            "active_release_id": {"type": "str", "indexed": True},
            "active_hash": {"type": "str", "indexed": True},
            "updated_at": {"type": "int", "indexed": True},
            "updated_by": {"type": "str", "indexed": True},
        },
    )

    _ensure_config_head_row(db)


def ensure_team_checkout_tables(db: Mpdb) -> None:
    """Ensure optional tables for team workflows exist.

    These tables enable durable object/component locks and RepoDB↔MainDB
    checkout/submit flows. They are safe to create even when the module is
    disabled; they do not affect runtime unless used by the UI/services.
    """

    _ensure_table(
        db,
        OBJECT_LOCKS_TABLE,
        {
            "lock_key": {"type": "str", "unique": True, "indexed": True},
            "object_type": {"type": "str", "indexed": True},
            "object_id": {"type": "str", "indexed": True},
            "component_type": {"type": "str", "indexed": True},
            "component_id": {"type": "str", "indexed": True},
            "lock_token": {"type": "str", "indexed": True},
            "locked_by": {"type": "str", "indexed": True},
            "locked_at": {"type": "int", "indexed": True},
            "last_heartbeat_at": {"type": "int", "indexed": True},
            "state": {"type": "str", "indexed": True},
            "comment": {"type": "str"},
        },
    )

    _ensure_table(
        db,
        CHECKOUT_SESSIONS_TABLE,
        {
            "session_id": {"type": "str", "unique": True, "indexed": True},
            "user_id": {"type": "str", "indexed": True},
            "repo_id": {"type": "str", "indexed": True},
            "started_at": {"type": "int", "indexed": True},
            "last_seen_at": {"type": "int", "indexed": True},
            "state": {"type": "str", "indexed": True},
            "client_info": {"type": "json"},
        },
    )

    # RepoDB-only helper table: tracks active checkouts and lock tokens.
    _ensure_table(
        db,
        REPO_CHECKOUTS_TABLE,
        {
            "id": {"type": "str", "unique": True, "indexed": True},
            "lock_key": {"type": "str", "indexed": True},
            "lock_token": {"type": "str", "indexed": True},
            "main_db_path": {"type": "str"},
            "object_type": {"type": "str", "indexed": True},
            "object_id": {"type": "str", "indexed": True},
            "component_type": {"type": "str", "indexed": True},
            "component_id": {"type": "str", "indexed": True},
            "checked_out_by": {"type": "str", "indexed": True},
            "checked_out_at": {"type": "int", "indexed": True},
            "status": {"type": "str", "indexed": True},
        },
    )


def ensure_system_tables(db: Mpdb) -> None:
    """Ensure all system tables for the current product stage exist."""

    ensure_users_tables(db)
    ensure_config_versioning_tables(db)
    ensure_team_checkout_tables(db)

    # Optional but safe: configuration code artifacts (1C/BAS modules, etc.)
    try:
        from .modules_tables import ensure_modules_tables

        ensure_modules_tables(db)
    except Exception:
        # Keep startup resilient even if optional module is missing.
        pass


# ---------------------------------------------------------------------------
# Data helpers (minimal MVP API)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PublishResult:
    """Result of a configuration publish operation."""

    new_release_id: str
    active_release_id: str


def audit_log(
    db: Mpdb,
    *,
    user_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: Optional[dict] = None,
) -> str:
    """Write an audit log entry and return event_id."""

    event_id = _new_guid()
    db.table(AUDIT_LOG_TABLE).insert(
        {
            "event_id": event_id,
            "ts": _now_ms(),
            "user_id": str(user_id or ""),
            "action": str(action or ""),
            "entity_type": str(entity_type or ""),
            "entity_id": str(entity_id or ""),
            "payload": payload or {},
        }
    )
    return event_id


def get_active_config_release_id(db: Mpdb) -> str:
    """Return current active configuration release id (or empty string)."""

    head = _get_config_head(db)
    return str(head.get("active_release_id") or "")


def publish_config_release(
    db: Mpdb,
    *,
    manifest: dict,
    created_by: str,
    comment: str = "",
    expected_active_release_id: Optional[str] = None,
    source_repo_commit_id: str = "",
    source_repo_tag: str = "",
) -> PublishResult:
    """Publish a new immutable configuration release.

    Args:
        manifest: Full configuration manifest (already validated by schema).
        created_by: User id.
        comment: Optional human comment.
        expected_active_release_id: Optional optimistic concurrency guard.
        source_repo_commit_id: Optional link to repository module.
        source_repo_tag: Optional link to repository module.

    Returns:
        PublishResult containing both new release id and new active pointer.

    Raises:
        RuntimeError: if expected_active_release_id is provided and differs
            from current active release.
    """

    import hashlib
    import json

    ensure_config_versioning_tables(db)

    current_active = get_active_config_release_id(db)
    if expected_active_release_id is not None and expected_active_release_id != current_active:
        raise RuntimeError(
            f"Active config changed: expected={expected_active_release_id!r}, actual={current_active!r}"
        )

    # Content hash for integrity tracking.
    manifest_bytes = json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()

    new_release_id = _new_guid()
    created_at = _now_ms()
    base_release_id = current_active

    # IMPORTANT (MVP): table-layer operations start their own transactions.
    # mpdb does not support nested transactions yet, so we perform this as two
    # sequential durable steps:
    #   1) write release row
    #   2) switch active head pointer
    #
    # This is safe in the sense that the system can always recover:
    # - if step (1) succeeds but step (2) fails, the release exists but is not active.
    # - step (2) never points to a non-existent release.
    db.table(CONFIG_RELEASES_TABLE).insert(
        {
            "release_id": new_release_id,
            "created_at": created_at,
            "created_by": str(created_by or ""),
            "comment": str(comment or ""),
            "base_release_id": str(base_release_id or ""),
            "manifest": manifest,
            "hash": manifest_hash,
            "source_repo_commit_id": str(source_repo_commit_id or ""),
            "source_repo_tag": str(source_repo_tag or ""),
        }
    )

    head = _get_config_head(db)
    db.table(CONFIG_HEAD_TABLE).update(
        where={"id": head["id"]},
        set_values={
            "active_release_id": new_release_id,
            "active_hash": manifest_hash,
            "updated_at": created_at,
            "updated_by": str(created_by or ""),
        },
    )

    audit_log(
        db,
        user_id=created_by,
        action="CONFIG_PUBLISH",
        entity_type="config_release",
        entity_id=new_release_id,
        payload={"base_release_id": base_release_id, "hash": manifest_hash, "comment": comment},
    )

    return PublishResult(new_release_id=new_release_id, active_release_id=new_release_id)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _ensure_table(db: Mpdb, name: str, schema: Dict[str, Any]) -> None:
    """Create mpdb table if it does not exist."""

    try:
        db.table(name)
        return
    except Exception:
        pass
    db.create_table(name, schema=schema)


def _seed_default_roles(db: Mpdb) -> None:
    """Seed a small set of built-in roles (idempotent)."""

    t = db.table(ROLES_TABLE)
    existing = {str(r.get("name") or "") for r in (t.select() or [])}

    def add(name: str, description: str) -> None:
        if name in existing:
            return
        t.insert(
            {
                "role_id": _new_guid(),
                "name": name,
                "description": description,
                "created_at": _now_ms(),
            }
        )

    add("Admin", "Full access")
    add("ConfigMaintainer", "Can edit and publish configuration")
    add("Developer", "Can work with objects in development workflows")
    add("Reviewer", "Can review/approve configuration changes")
    add("Deployer", "Can deploy releases to runtime database")
    add("Viewer", "Read-only access")


def _ensure_user_has_role(db: Mpdb, *, user_id: str, role_name: str) -> None:
    """Ensure a user has the given role (idempotent).

    Note:
        This helper is intended for seeding/MVP defaults. In production, role
        grants are managed via the UI.
    """

    user_id = str(user_id or "").strip()
    role_name = str(role_name or "").strip()
    if not user_id or not role_name:
        return

    roles = db.table(ROLES_TABLE).select(where={"name": role_name}) or []
    if not roles:
        return
    role_id = str(roles[0].get("role_id") or "").strip()
    if not role_id:
        return

    link_t = db.table(USER_ROLES_TABLE)
    existing = link_t.select(where={"user_id": user_id, "role_id": role_id}) or []
    if existing:
        return
    link_t.insert(
        {
            "id": _new_guid(),
            "user_id": user_id,
            "role_id": role_id,
            "created_at": _now_ms(),
        }
    )


def _seed_system_user(db: Mpdb) -> None:
    """Ensure built-in SYSTEM user exists (idempotent)."""

    t = db.table(USERS_TABLE)
    rows = t.select(where={"login": "system"})
    if not rows:
        t.insert(
            {
                "user_id": "system",
                "login": "system",
                "display_name": "SYSTEM",
                "password_hash": "",
                "is_active": True,
                "created_at": _now_ms(),
            }
        )

    # The SYSTEM user should be able to run maintenance operations in early MVP.
    # Real deployments can remove these grants and use explicit admin accounts.
    _ensure_user_has_role(db, user_id="system", role_name="Admin")
    _ensure_user_has_role(db, user_id="system", role_name="ConfigMaintainer")


def _ensure_config_head_row(db: Mpdb) -> None:
    """Ensure CONFIG_HEAD_TABLE contains a single row (idempotent)."""

    t = db.table(CONFIG_HEAD_TABLE)
    rows = t.select() or []
    if rows:
        return
    t.insert(
        {
            "id": "head",
            "active_release_id": "",
            "active_hash": "",
            "updated_at": _now_ms(),
            "updated_by": "system",
        }
    )


def _get_config_head(db: Mpdb) -> Dict[str, Any]:
    """Return the single config head row; creates it if missing."""

    ensure_config_versioning_tables(db)
    t = db.table(CONFIG_HEAD_TABLE)
    rows = t.select(where={"id": "head"}) or []
    if not rows:
        _ensure_config_head_row(db)
        rows = t.select(where={"id": "head"}) or []
    if not rows:
        raise MpdbError("CONFIG_HEAD_TABLE is missing head row")
    return rows[0]
