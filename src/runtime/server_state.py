from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Tuple

from src.mpdb.mpdb import Mpdb, MpdbError
from src.runtime.db_registry import DbRegistry


@dataclass
class RpcResponse:
    status: str
    data: Any = None
    error: str | None = None


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def create(self) -> str:
        sid = uuid.uuid4().hex
        with self._lock:
            self._sessions[sid] = {"active_db_uid": None, "created_at": time.time()}
        return sid

    def get_active_db_uid(self, sid: str) -> str | None:
        with self._lock:
            s = self._sessions.get(sid)
            return s.get("active_db_uid") if s else None

    def set_active_db_uid(self, sid: str, db_uid: str) -> None:
        with self._lock:
            if sid not in self._sessions:
                raise KeyError("Invalid session")
            self._sessions[sid]["active_db_uid"] = db_uid

    def close(self, sid: str) -> bool:
        """Forget an RPC client session without closing the shared DB."""

        with self._lock:
            return self._sessions.pop(str(sid or ""), None) is not None


class DbPool:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._dbs: dict[str, Tuple[str, Mpdb, float]] = {}

    def _warm_manifest_background(self, *, db: Mpdb, db_uid: str, db_path: str) -> None:
        try:
            from src.runtime.server_handlers_manifest import warm_manifest_caches
        except Exception as e:
            print(f"[DbPool._warm_manifest_background] import warning: {e}", flush=True)
            return

        def _worker() -> None:
            try:
                warm_manifest_caches(db, db_uid=db_uid, db_path=db_path)
            except Exception as e:
                print(f"[DbPool._warm_manifest_background] warning: {e}", flush=True)

        try:
            threading.Thread(
                target=_worker,
                name=f"mp-manifest-warmup-{db_uid[:8]}",
                daemon=True,
            ).start()
        except Exception as e:
            print(f"[DbPool._warm_manifest_background] thread warning: {e}", flush=True)

    def open_by_path(self, path: str) -> Tuple[str, str]:
        path = str(Path(path).resolve())
        normalized_path = os.path.normcase(path)
        with self._lock:
            for uid, (open_path, open_db, _last_used) in self._dbs.items():
                if os.path.normcase(str(Path(open_path).resolve())) != normalized_path:
                    continue
                name = str(open_db.meta.get("name") or "") if hasattr(open_db, "meta") else ""
                self._dbs[uid] = (open_path, open_db, time.time())
                return uid, name

        db = Mpdb(path)
        uid = db.db_uid
        name = str(db.meta.get("name") or "") if hasattr(db, "meta") else ""
        # Ensure all system tables exist on every DB open
        try:
            from src.configurator.persistence.system_tables import ensure_system_tables
            ensure_system_tables(db)
        except Exception as e:
            print(f"[DbPool.open_by_path] ensure_system_tables warning: {e}", flush=True)
        with self._lock:
            # Another request may have opened this path while Mpdb was being
            # initialized. Keep the first live handle and close the duplicate.
            for open_uid, (open_path, open_db, _last_used) in self._dbs.items():
                if os.path.normcase(str(Path(open_path).resolve())) != normalized_path:
                    continue
                try:
                    db.close()
                except Exception:
                    pass
                open_name = str(open_db.meta.get("name") or "") if hasattr(open_db, "meta") else ""
                self._dbs[open_uid] = (open_path, open_db, time.time())
                return open_uid, open_name
            old_entry = self._dbs.get(uid)
            if old_entry is not None:
                try:
                    db.close()
                except Exception:
                    pass
                old_path, old_db, _last_used = old_entry
                old_name = str(old_db.meta.get("name") or "") if hasattr(old_db, "meta") else ""
                self._dbs[uid] = (old_path, old_db, time.time())
                return uid, old_name
            self._dbs[uid] = (path, db, time.time())
        self._warm_manifest_background(db=db, db_uid=uid, db_path=path)
        return uid, name

    def get_path(self, db_uid: str) -> str | None:
        with self._lock:
            entry = self._dbs.get(db_uid)
            return entry[0] if entry else None

    def reopen_fresh(self, db_uid: str) -> Mpdb:
        """Close current db, move the file aside, open a fresh empty one."""
        import shutil as _shutil

        with self._lock:
            entry = self._dbs.get(db_uid)
            if not entry:
                raise KeyError(f"DB {db_uid!r} not in pool")
            path, old_db, _ = entry
            try:
                old_db.close()
            except Exception:
                pass
            p = Path(path)
            if p.exists():
                corrupt = p.with_name(f"{p.stem}.corrupt-{int(time.time())}{p.suffix}")
                try:
                    _shutil.move(str(p), str(corrupt))
                    print(f"[DbPool.reopen_fresh] corrupt DB moved to {corrupt}", flush=True)
                except Exception:
                    pass
            new_db = Mpdb(path)
            # Ensure system tables on fresh DB
            try:
                from src.configurator.persistence.system_tables import ensure_system_tables
                ensure_system_tables(new_db)
            except Exception as e:
                print(f"[DbPool.reopen_fresh] ensure_system_tables warning: {e}", flush=True)
            self._dbs[db_uid] = (path, new_db, time.time())
            self._warm_manifest_background(db=new_db, db_uid=db_uid, db_path=path)
            print(f"[DbPool.reopen_fresh] fresh DB created at {path}", flush=True)
            return new_db

    def replace_with_file(self, db_uid: str, replacement_path: str, *, backup_path: str | None = None) -> Mpdb:
        """Replace the live db file with a prepared mpdb file and reopen it.

        ``backup_path`` is retained. If the swap/open fails, the backup is copied
        back over the live file and the restored DB is reopened in the pool before
        the original error is re-raised.
        """
        with self._lock:
            entry = self._dbs.get(db_uid)
            if not entry:
                raise KeyError(f"DB {db_uid!r} not in pool")

            path, old_db, _ = entry
            live = Path(path)
            replacement = Path(replacement_path)
            backup = Path(backup_path) if backup_path else None
            if not replacement.exists():
                raise FileNotFoundError(f"Replacement DB not found: {replacement}")

            # Validate through a separate read-only handle before closing the
            # live database.  This is the final guard against promoting a
            # staging file whose in-process page cache masked damaged bytes.
            from src.mpdb.doctor import check as check_mpdb

            replacement_report = check_mpdb(replacement)
            if not replacement_report.ok:
                issues = "; ".join(
                    f"{issue.code} page={issue.page_id}: {issue.message}"
                    for issue in replacement_report.issues[:10]
                )
                raise MpdbError(
                    "Replacement DB failed offline integrity validation: "
                    f"bad_pages={replacement_report.pages_bad}; {issues}"
                )

            try:
                old_db.close()
            except Exception:
                pass

            try:
                os.replace(str(replacement), str(live))
                new_db = Mpdb(str(live))
                # Opening may replay WAL and therefore mutate the file. Validate
                # the activated bytes before publishing this handle to workers.
                live_report = check_mpdb(live)
                if not live_report.ok:
                    issues = "; ".join(
                        f"{issue.code} page={issue.page_id}: {issue.message}"
                        for issue in live_report.issues[:10]
                    )
                    new_db.close()
                    raise MpdbError(
                        "Activated DB failed offline integrity validation: "
                        f"bad_pages={live_report.pages_bad}; {issues}"
                    )
            except Exception as exc:
                restored_db = None
                try:
                    if backup is not None and backup.exists():
                        shutil.copy2(str(backup), str(live))
                    restored_db = Mpdb(str(live))
                    self._dbs[db_uid] = (path, restored_db, time.time())
                    print(f"[DbPool.replace_with_file] restored DB from backup after failed swap: {backup}", flush=True)
                except Exception as restore_exc:
                    if restored_db is not None:
                        try:
                            restored_db.close()
                        except Exception:
                            pass
                    print(f"[DbPool.replace_with_file] restore failed: {restore_exc}", flush=True)
                raise exc

            self._dbs[db_uid] = (path, new_db, time.time())
            self._warm_manifest_background(db=new_db, db_uid=db_uid, db_path=path)
            print(f"[DbPool.replace_with_file] live DB replaced at {path}", flush=True)
            return new_db

    def get(self, db_uid: str) -> Mpdb:
        with self._lock:
            if db_uid not in self._dbs:
                raise KeyError("DB not opened")
            path, db, _ = self._dbs[db_uid]
            self._dbs[db_uid] = (path, db, time.time())
            return db

    def list_open(self) -> list[dict[str, Any]]:
        with self._lock:
            out = []
            for uid, (path, _db, ts) in self._dbs.items():
                out.append({"db_uid": uid, "path": path, "last_used": ts})
            return out


class ImportStatusStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[str, _ImportStatusRecord] = {}

    def set(self, session_id: str, state: dict[str, Any], *, meta: dict[str, Any] | None = None) -> None:
        sid = str(session_id or "").strip()
        if not sid:
            return
        with self._lock:
            now = time.time()
            record = self._states.get(sid)
            if record is None:
                record = _ImportStatusRecord(session_id=sid, created_at=now, updated_at=now)
                self._states[sid] = record
            if meta:
                record.meta.update(dict(meta or {}))
            record.state = dict(state or {})
            record.updated_at = now
            if record.completed_at is None and record.is_terminal():
                record.completed_at = now
            record.history.append(
                {
                    "ts": now,
                    "kind": "state",
                    "state": dict(record.state),
                    **({"meta": dict(meta or {})} if meta else {}),
                }
            )

    def get(self, session_id: str) -> dict[str, Any]:
        sid = str(session_id or "").strip()
        if not sid:
            return {}
        with self._lock:
            record = self._states.get(sid)
            return dict(record.state) if record is not None else {}

    def snapshot(self, session_id: str, *, history_limit: int = 20) -> dict[str, Any]:
        sid = str(session_id or "").strip()
        if not sid:
            return {}
        with self._lock:
            record = self._states.get(sid)
            return record.snapshot(history_limit=history_limit) if record is not None else {}

    def append_event(
        self,
        session_id: str,
        kind: str,
        *,
        message: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        sid = str(session_id or "").strip()
        if not sid:
            return
        with self._lock:
            now = time.time()
            record = self._states.get(sid)
            if record is None:
                record = _ImportStatusRecord(session_id=sid, created_at=now, updated_at=now)
                self._states[sid] = record
            event = {
                "ts": now,
                "kind": str(kind or "").strip() or "event",
            }
            msg = str(message or "").strip()
            if msg:
                event["message"] = msg
            if data:
                event["data"] = dict(data)
            record.history.append(event)
            record.updated_at = now
            if record.completed_at is None and str(event["kind"]).lower() in {"done", "failed", "error"}:
                record.completed_at = now

    def list(self, *, active_only: bool = False, history_limit: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._states.values())
            if active_only:
                records = [record for record in records if record.is_active()]
            records.sort(key=lambda record: (0 if record.is_active() else 1, -record.updated_at, -record.created_at))
            return [record.snapshot(history_limit=history_limit) for record in records]

    def latest(self, *, active_only: bool = False, history_limit: int = 20) -> dict[str, Any]:
        records = self.list(active_only=active_only, history_limit=history_limit)
        return dict(records[0]) if records else {}

    def clear(self, session_id: str) -> None:
        sid = str(session_id or "").strip()
        if not sid:
            return
        with self._lock:
            self._states.pop(sid, None)


@dataclass
class _ImportStatusRecord:
    session_id: str
    created_at: float
    updated_at: float
    meta: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=256))
    completed_at: float | None = None

    def is_terminal(self) -> bool:
        phase = str(self.state.get("phase") or "").strip().lower()
        return bool(self.state.get("failed")) or phase in {"done", "failed"}

    def is_active(self) -> bool:
        if self.is_terminal():
            return False
        return bool(self.state) or bool(self.history)

    def snapshot(self, *, history_limit: int = 0) -> dict[str, Any]:
        data = dict(self.meta)
        data.update(self.state)
        data["session_id"] = self.session_id
        data["created_at"] = self.created_at
        data["updated_at"] = self.updated_at
        if data.get("started_at") in (None, ""):
            data["started_at"] = self.created_at
        data["event_count"] = len(self.history)
        data["active"] = self.is_active()
        if self.completed_at is not None:
            data["completed_at"] = self.completed_at
        if self.is_terminal():
            phase = str(self.state.get("phase") or "").strip().lower()
            data["status"] = "failed" if bool(self.state.get("failed")) or phase == "failed" else "done"
        elif self.is_active():
            data["status"] = "active"
        else:
            data["status"] = "idle"
        if history_limit > 0:
            data["history"] = list(self.history)[-max(0, int(history_limit)) :]
        return data


class _nullctx:
    """Minimal context manager wrapper for objects that lack __enter__/__exit__."""

    def __init__(self, obj):
        self._obj = obj

    def __enter__(self):
        return self._obj

    def __exit__(self, *_):
        pass


STATE_SESSIONS = SessionStore()
STATE_DBS = DbPool()
STATE_IMPORTS = ImportStatusStore()
STATE_REGISTRY = DbRegistry.load()
