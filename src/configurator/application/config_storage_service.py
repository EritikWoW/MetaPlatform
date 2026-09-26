from __future__ import annotations

"""Configuration storage service.

MVP implementation of a 1C-like configuration storage:
- storage is a separate Mpdb file
- locks are durable and hierarchical (object/component)
- sessions + heartbeats enable admin diagnostics
- commits/revisions store snapshots (JSON)
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QSettings

from src.mpdb.mpdb import Mpdb

from src.configurator.persistence.config_storage_tables import (
    COMMITS_TABLE,
    HEAD_TABLE,
    LOCK_OWNERSHIP_TABLE,
    REVISIONS_TABLE,
    ensure_config_storage_tables,
)
from src.configurator.persistence.object_locks import (
    acquire_object_lock,
    get_lock,
    heartbeat_object_lock,
    list_object_locks,
    make_lock_key,
    release_object_lock,
)
from src.configurator.persistence.system_tables import (
    CHECKOUT_SESSIONS_TABLE,
    audit_log,
    ensure_system_tables,
    ensure_team_checkout_tables,
)


@dataclass(frozen=True, slots=True)
class StorageConnection:
    """Connected configuration storage descriptor."""

    path: Path


class ConfigStorageService:
    """High-level access to configuration storage DB.

    The service is UI-friendly:
    - persistent connection settings via QSettings
    - local lock tokens stored to allow unlock after restarts
    - durable storage sessions with heartbeat for admin visibility
    """

    _SETTINGS_KEY_PATH = "config_storage/path"
    _SETTINGS_KEY_TOKEN_PREFIX = "config_storage/lock_token/"
    _SETTINGS_KEY_CLIENT_ID = "config_storage/client_id"
    _SETTINGS_KEY_SESSION_ID = "config_storage/session_id"

    HEARTBEAT_INTERVAL_MS = 30_000
    SESSION_TTL_MS = 90_000

    def __init__(self, *, settings: QSettings) -> None:
        self._settings = settings
        self._db: Optional[Mpdb] = None
        self._conn: Optional[StorageConnection] = None
        self._client_id = self._ensure_client_id()
        self._session_id: str = ""

        # Auto-connect if path exists.
        p = str(self._settings.value(self._SETTINGS_KEY_PATH, "") or "").strip()
        if p:
            try:
                self.connect(Path(p))
            except Exception:
                # Storage is optional; keep silent.
                pass

    # ---------------------------------------------------------------------
    # Connection
    # ---------------------------------------------------------------------

    def connection(self) -> Optional[StorageConnection]:
        """Return current storage connection (if any)."""

        return self._conn

    def connect(self, path: Path) -> None:
        """Connect to a configuration storage Mpdb file."""

        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(str(p))

        self.close()

        db = Mpdb(p)
        ensure_system_tables(db)
        ensure_team_checkout_tables(db)
        ensure_config_storage_tables(db)

        self._db = db
        self._conn = StorageConnection(path=p)
        self._settings.setValue(self._SETTINGS_KEY_PATH, str(p))

        # Start a durable storage session (SYSTEM until Users module is wired).
        self._start_session(user_id="SYSTEM")
        self.heartbeat(user_id="SYSTEM")

    def close(self) -> None:
        """Close storage connection (best effort)."""

        if self._db is not None:
            try:
                self._mark_session_closed(user_id="SYSTEM")
            except Exception:
                pass
            try:
                self._db.close()
            except Exception:
                pass

        self._db = None
        self._conn = None
        self._session_id = ""

    def disconnect(self) -> None:
        """Disconnect from storage and forget persisted path."""

        self.close()
        self._settings.remove(self._SETTINGS_KEY_PATH)
        self._settings.remove(self._SETTINGS_KEY_SESSION_ID)

    # ---------------------------------------------------------------------
    # Local token helpers
    # ---------------------------------------------------------------------

    def local_lock_token(self, lock_key: str) -> str:
        """Return locally stored lock token for lock_key (or empty string)."""

        lk = str(lock_key or "").strip()
        if not lk:
            return ""
        return str(self._settings.value(self._SETTINGS_KEY_TOKEN_PREFIX + lk, "") or "").strip()

    def get_lock_info(self, *, lock_key: str) -> Optional[dict[str, Any]]:
        """Return raw lock information for a given lock key.

        Notes:
            This is a thin wrapper over the storage DB schema and is primarily
            used by UI guards (e.g., Form Designer) to determine editability.
        """

        db = self._require_db()
        lk = str(lock_key or "").strip()
        if not lk:
            return None
        return get_lock(db, lock_key=lk)

    def is_lock_held_by_me(self, *, lock_key: str, user_id: str = "SYSTEM") -> bool:
        """Return True if the lock is active and belongs to this client.

        The current MVP uses token-based ownership (like 1C storage) and stores
        tokens locally in QSettings, so the ownership survives client restarts.
        """

        lk = str(lock_key or "").strip()
        if not lk:
            return False
        token = self.local_lock_token(lk)
        if not token:
            return False
        row = self.get_lock_info(lock_key=lk)
        if row is None:
            return False
        if str(row.get("state") or "") != "active":
            return False
        if str(row.get("lock_token") or "") != token:
            return False
        if str(row.get("locked_by") or "") != str(user_id or ""):
            return False
        return True

    # ---------------------------------------------------------------------
    # Locks
    # ---------------------------------------------------------------------

    def checkout(
        self,
        *,
        object_type: str,
        object_id: str,
        component_type: str,
        component_id: str,
        comment: str = "",
        user_id: str = "SYSTEM",
    ) -> str:
        """Acquire a durable lock in the storage.

        Returns:
            lock_key string.

        The lock token is stored locally in QSettings so the lock can be released
        after restarts and crashes.
        """

        db = self._require_db()
        token = os.urandom(16).hex()
        key = make_lock_key(
            object_type=object_type,
            object_id=object_id,
            component_type=component_type,
            component_id=component_id,
        )
        acquire_object_lock(db, key=key, user_id=user_id, lock_token=token, comment=comment)

        lk = key.as_string()
        self._settings.setValue(self._SETTINGS_KEY_TOKEN_PREFIX + lk, token)
        self._record_lock_ownership(lock_key=lk, user_id=user_id)

        audit_log(
            db,
            user_id=str(user_id or ""),
            action="storage_checkout",
            entity_type="config_storage",
            entity_id=lk,
            payload={"comment": str(comment or "")},
        )
        return lk

    def release_my_locks_for_object(self, *, object_type: str, object_id: str, user_id: str = "SYSTEM") -> int:
        """Release locks for an object that belong to this client (token-based)."""

        db = self._require_db()
        released = 0
        for row in list_object_locks(db, object_id=object_id, state="active"):
            lk = str(row.get("lock_key") or "").strip()
            if not lk:
                continue
            token = self.local_lock_token(lk)
            if not token:
                continue
            if release_object_lock(db, lock_key=lk, lock_token=token, user_id=user_id, force=False):
                released += 1
                self._settings.remove(self._SETTINGS_KEY_TOKEN_PREFIX + lk)
        return released

    def force_release_locks_for_object(self, *, object_type: str, object_id: str, user_id: str = "SYSTEM") -> int:
        """Force-release all locks for an object.

        Role policy will be enforced after the Users/Roles module is wired.
        """

        db = self._require_db()
        released = 0
        for row in list_object_locks(db, object_id=object_id, state="active"):
            lk = str(row.get("lock_key") or "").strip()
            token = str(row.get("lock_token") or "").strip()
            if not lk or not token:
                continue
            if release_object_lock(db, lock_key=lk, lock_token=token, user_id=user_id, force=True):
                released += 1
                self._settings.remove(self._SETTINGS_KEY_TOKEN_PREFIX + lk)
        return released

    def force_release_lock(self, *, lock_key: str, user_id: str = "SYSTEM", reason: str = "") -> bool:
        """Force-release a single lock by lock_key (administrative action)."""

        db = self._require_db()
        lk = str(lock_key or "").strip()
        if not lk:
            return False
        row = get_lock(db, lock_key=lk)
        if row is None:
            return False
        token = str(row.get("lock_token") or "").strip()
        if not token:
            return False

        ok = release_object_lock(db, lock_key=lk, lock_token=token, user_id=str(user_id or ""), force=True)
        if ok:
            self._settings.remove(self._SETTINGS_KEY_TOKEN_PREFIX + lk)
            audit_log(
                db,
                user_id=str(user_id or ""),
                action="storage_force_unlock",
                entity_type="ObjectLock",
                entity_id=lk,
                payload={"reason": str(reason or "")},
            )
        return ok

    # ---------------------------------------------------------------------
    # Versioned content
    # ---------------------------------------------------------------------


    def commit(self, *, lock_key: str, payload: dict, message: str = "", user_id: str = "SYSTEM") -> str:
        """Commit a new revision for lock_key but keep the lock active.

        This is the recommended operation for editors (e.g., Form Designer) where
        the user expects to keep editing after saving.

        Notes:
            The current client must have a local token for lock_key (checkout).
            Unlike submit(), this method does not release the lock and does not
            remove the local token.
        """

        db = self._require_db()
        lk = str(lock_key or "").strip()
        if not lk:
            raise ValueError("lock_key is required")

        token = self.local_lock_token(lk)
        if not token:
            raise PermissionError("No local lock token for this key")

        row = get_lock(db, lock_key=lk)
        if row is None or str(row.get("state") or "") != "active":
            raise RuntimeError("Lock is not active")
        if str(row.get("lock_token") or "") != token:
            raise RuntimeError("Lock token mismatch")

        ts = int(time.time() * 1000)
        commit_id = os.urandom(16).hex()

        raw = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ph = hashlib.sha256(raw).hexdigest()

        db.table(COMMITS_TABLE).insert({"commit_id": commit_id, "ts": ts, "user_id": str(user_id or ""), "message": str(message or "")})
        db.table(REVISIONS_TABLE).insert(
            {
                "commit_id": commit_id,
                "lock_key": lk,
                "ts": ts,
                "user_id": str(user_id or ""),
                "message": str(message or ""),
                "payload": payload or {},
                "payload_hash": ph,
            }
        )
        db.table(HEAD_TABLE).insert({"lock_key": lk, "commit_id": commit_id, "ts": ts, "user_id": str(user_id or ""), "payload_hash": ph})

        audit_log(
            db,
            user_id=str(user_id or ""),
            action="storage_commit",
            entity_type="config_storage",
            entity_id=lk,
            payload={"commit_id": commit_id, "payload_hash": ph, "message": str(message or "")},
        )
        return commit_id

    def submit(self, *, lock_key: str, payload: dict, message: str = "", user_id: str = "SYSTEM") -> str:
        """Commit a new revision for lock_key and release the lock.

        For MVP, the current client must have a local token for lock_key.
        """

        db = self._require_db()
        lk = str(lock_key or "").strip()
        if not lk:
            raise ValueError("lock_key is required")

        token = self.local_lock_token(lk)
        if not token:
            raise PermissionError("No local lock token for this key")

        row = get_lock(db, lock_key=lk)
        if row is None or str(row.get("state") or "") != "active":
            raise RuntimeError("Lock is not active")
        if str(row.get("lock_token") or "") != token:
            raise RuntimeError("Lock token mismatch")

        ts = int(time.time() * 1000)
        commit_id = os.urandom(16).hex()

        raw = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ph = hashlib.sha256(raw).hexdigest()

        db.table(COMMITS_TABLE).insert({"commit_id": commit_id, "ts": ts, "user_id": str(user_id or ""), "message": str(message or "")})
        db.table(REVISIONS_TABLE).insert(
            {
                "commit_id": commit_id,
                "lock_key": lk,
                "ts": ts,
                "user_id": str(user_id or ""),
                "message": str(message or ""),
                "payload": payload or {},
                "payload_hash": ph,
            }
        )
        db.table(HEAD_TABLE).insert({"lock_key": lk, "commit_id": commit_id, "ts": ts, "user_id": str(user_id or ""), "payload_hash": ph})

        release_object_lock(db, lock_key=lk, lock_token=token, user_id=user_id, force=False)
        self._settings.remove(self._SETTINGS_KEY_TOKEN_PREFIX + lk)

        audit_log(
            db,
            user_id=str(user_id or ""),
            action="storage_submit",
            entity_type="config_storage",
            entity_id=lk,
            payload={"commit_id": commit_id, "payload_hash": ph, "message": str(message or "")},
        )
        return commit_id

    def get_latest(self, *, lock_key: str) -> Optional[dict]:
        """Return the latest stored payload for lock_key (if any)."""

        db = self._require_db()
        lk = str(lock_key or "").strip()
        if not lk:
            return None
        rows = db.table(REVISIONS_TABLE).select({"lock_key": lk}, order_by="rowid") or []
        if not rows:
            return None
        payload = rows[-1].get("payload")
        return payload if isinstance(payload, dict) else None

    def history(self, *, lock_key: str, limit: int = 20) -> list[dict]:
        """Return recent revision entries for lock_key (newest last)."""

        db = self._require_db()
        lk = str(lock_key or "").strip()
        if not lk:
            return []
        rows = db.table(REVISIONS_TABLE).select({"lock_key": lk}, order_by="rowid") or []
        if limit and limit > 0:
            rows = rows[-int(limit) :]
        out: list[dict] = []
        for r in rows:
            out.append(
                {
                    "commit_id": str(r.get("commit_id") or ""),
                    "ts": int(r.get("ts") or 0),
                    "user_id": str(r.get("user_id") or ""),
                    "message": str(r.get("message") or ""),
                    "payload_hash": str(r.get("payload_hash") or ""),
                }
            )
        return out

    # ---------------------------------------------------------------------
    # Admin / telemetry
    # ---------------------------------------------------------------------

    def heartbeat(self, *, user_id: str = "SYSTEM") -> None:
        """Send a heartbeat for the current storage session and owned locks."""

        db = self._require_db()
        now_ms = int(time.time() * 1000)

        sid = str(self._session_id or "").strip()
        if sid:
            try:
                db.table(CHECKOUT_SESSIONS_TABLE).update(where={"session_id": sid}, set_values={"last_seen_at": now_ms, "state": "active"})
            except Exception:
                pass

        for lk in self._iter_local_lock_keys():
            token = self.local_lock_token(lk)
            if not token:
                continue
            try:
                heartbeat_object_lock(db, lock_key=lk, lock_token=token)
            except Exception:
                continue

    def list_storage_commits(self, *, limit: int = 50) -> list[dict]:
        """Return recent commits from storage (newest last)."""

        db = self._require_db()
        rows = db.table(COMMITS_TABLE).select(where={}, order_by="rowid") or []
        if limit and limit > 0:
            rows = rows[-int(limit) :]
        out: list[dict] = []
        for r in rows:
            out.append(
                {
                    "commit_id": str(r.get("commit_id") or ""),
                    "ts": int(r.get("ts") or 0),
                    "user_id": str(r.get("user_id") or ""),
                    "message": str(r.get("message") or ""),
                }
            )
        return out

    def list_sessions(self, *, limit: int = 100) -> list[dict]:
        """List known storage sessions (newest last)."""

        db = self._require_db()
        rows = db.table(CHECKOUT_SESSIONS_TABLE).select({}, order_by="rowid") or []
        if limit and limit > 0:
            rows = rows[-int(limit) :]

        now = int(time.time() * 1000)
        out: list[dict] = []
        for r in rows:
            last_seen = int(r.get("last_seen_at") or 0)
            state = str(r.get("state") or "")
            active = bool(last_seen and (now - last_seen) <= self.SESSION_TTL_MS and state == "active")
            client_id = ""
            ci = r.get("client_info")
            if isinstance(ci, dict):
                client_id = str(ci.get("client_id") or "")
            out.append(
                {
                    "session_id": str(r.get("session_id") or ""),
                    "user_id": str(r.get("user_id") or ""),
                    "repo_id": str(r.get("repo_id") or ""),
                    "started_at": int(r.get("started_at") or 0),
                    "last_seen_at": last_seen,
                    "state": state,
                    "is_active": active,
                    "client_id": client_id,
                }
            )
        return out

    def list_active_locks(self, *, ttl_ms: int | None = None) -> list[dict]:
        """Return active locks, enriched with session activity flags."""

        db = self._require_db()
        ttl = int(ttl_ms) if ttl_ms is not None else self.SESSION_TTL_MS
        now_ms = int(time.time() * 1000)

        locks = list_object_locks(db, object_id=None, state="active")

        out: list[dict] = []
        for r in locks:
            lk = str(r.get("lock_key") or "").strip()
            if not lk:
                continue
            own = self._get_lock_ownership(lock_key=lk) or {}
            sid = str(own.get("session_id") or "").strip()
            cid = str(own.get("client_id") or "").strip()
            sess = self._get_session(session_id=sid) if sid else None
            last_seen = int((sess or {}).get("last_seen_at") or 0)
            state = str((sess or {}).get("state") or "")
            is_active = bool(last_seen and (now_ms - last_seen) <= ttl and state == "active")

            out.append(
                {
                    "lock_key": lk,
                    "locked_by": str(r.get("locked_by") or ""),
                    "locked_at": int(r.get("locked_at") or 0),
                    "last_heartbeat_at": int(r.get("last_heartbeat_at") or 0),
                    "session_id": sid,
                    "client_id": cid,
                    "session_last_seen_at": last_seen,
                    "session_is_active": is_active,
                }
            )
        return out

    # ---------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------

    def _require_db(self) -> Mpdb:
        if self._db is None:
            raise RuntimeError("Configuration storage is not connected")
        return self._db

    def _ensure_client_id(self) -> str:
        """Return persistent client_id for this workstation."""

        cid = str(self._settings.value(self._SETTINGS_KEY_CLIENT_ID, "") or "").strip()
        if cid:
            return cid
        cid = os.urandom(16).hex()
        self._settings.setValue(self._SETTINGS_KEY_CLIENT_ID, cid)
        return cid

    def _repo_id(self) -> str:
        """Return a stable identifier for the connected storage."""

        if self._conn is None:
            return ""
        raw = str(self._conn.path).encode("utf-8")
        return hashlib.sha1(raw).hexdigest()  # stable, not security-sensitive

    def _start_session(self, *, user_id: str) -> None:
        """Create and persist a storage session row."""

        db = self._require_db()
        sid = os.urandom(16).hex()
        now_ms = int(time.time() * 1000)

        db.table(CHECKOUT_SESSIONS_TABLE).insert(
            {
                "session_id": sid,
                "user_id": str(user_id or ""),
                "repo_id": self._repo_id(),
                "started_at": now_ms,
                "last_seen_at": now_ms,
                "state": "active",
                "client_info": {"client_id": self._client_id, "pid": int(os.getpid())},
            }
        )

        self._session_id = sid
        self._settings.setValue(self._SETTINGS_KEY_SESSION_ID, sid)

        audit_log(
            db,
            user_id=str(user_id or ""),
            action="storage_session_start",
            entity_type="StorageSession",
            entity_id=sid,
            payload={"client_id": self._client_id, "repo_id": self._repo_id()},
        )

    def _mark_session_closed(self, *, user_id: str) -> None:
        """Mark current session as closed (best effort)."""

        db = self._require_db()
        sid = str(self._session_id or "").strip()
        if not sid:
            return
        now_ms = int(time.time() * 1000)
        db.table(CHECKOUT_SESSIONS_TABLE).update(where={"session_id": sid}, set_values={"state": "closed", "last_seen_at": now_ms})

        audit_log(
            db,
            user_id=str(user_id or ""),
            action="storage_session_close",
            entity_type="StorageSession",
            entity_id=sid,
            payload={},
        )

    def _iter_local_lock_keys(self) -> list[str]:
        """Return lock keys that have local tokens stored in QSettings."""

        try:
            keys = [k for k in self._settings.allKeys() if k.startswith(self._SETTINGS_KEY_TOKEN_PREFIX)]
        except Exception:
            return []
        out: list[str] = []
        for k in keys:
            lk = k[len(self._SETTINGS_KEY_TOKEN_PREFIX) :].strip()
            if lk:
                out.append(lk)
        return out

    def _record_lock_ownership(self, *, lock_key: str, user_id: str) -> None:
        """Record lock ownership attribution (lock_key -> session/client)."""

        db = self._require_db()
        lk = str(lock_key or "").strip()
        sid = str(self._session_id or "").strip()
        if not lk or not sid:
            return
        db.table(LOCK_OWNERSHIP_TABLE).insert(
            {
                "id": os.urandom(16).hex(),
                "ts": int(time.time() * 1000),
                "lock_key": lk,
                "user_id": str(user_id or ""),
                "session_id": sid,
                "client_id": self._client_id,
            }
        )

    def _get_lock_ownership(self, *, lock_key: str) -> Optional[dict]:
        db = self._require_db()
        lk = str(lock_key or "").strip()
        if not lk:
            return None
        rows = db.table(LOCK_OWNERSHIP_TABLE).select(where={"lock_key": lk}, order_by="rowid") or []
        return rows[-1] if rows else None

    def _get_session(self, *, session_id: str) -> Optional[dict]:
        db = self._require_db()
        sid = str(session_id or "").strip()
        if not sid:
            return None
        rows = db.table(CHECKOUT_SESSIONS_TABLE).select(where={"session_id": sid}, order_by="rowid") or []
        return rows[-1] if rows else None
