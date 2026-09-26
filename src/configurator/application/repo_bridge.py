from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.mpdb.mpdb import Mpdb, MpdbError

from ..persistence.manifest_io import MANIFEST_TABLE, ensure_manifest
from ..persistence.object_locks import LockKey, acquire_object_lock, make_lock_key, release_object_lock
from ..persistence.system_tables import REPO_CHECKOUTS_TABLE, ensure_system_tables, ensure_team_checkout_tables


def _now_ms() -> int:
    return int(time.time() * 1000)


def _open_db(path: str) -> Mpdb:
    path = (path or "").strip()
    if not path:
        raise MpdbError("DB path is empty")
    return Mpdb.open(path)


def _upsert_row(t, where: Dict[str, Any], values: Dict[str, Any]) -> None:
    rows = t.select(where=where) or []
    if rows:
        t.update(where=where, set_values=values)
    else:
        t.insert(values)


@dataclass(frozen=True)
class CheckoutRequest:
    repo_db_path: str
    main_db_path: str
    user_id: str
    object_type: str
    object_id: str
    component_type: str
    component_id: str
    comment: str = ""


def checkout(req: CheckoutRequest) -> str:
    """Checkout an object/component from MainDB into the current RepoDB.

    Returns:
        lock_key string.
    """

    key = make_lock_key(
        object_type=req.object_type,
        object_id=req.object_id,
        component_type=req.component_type,
        component_id=req.component_id,
    )
    lock_key = key.as_string()
    lock_token = f"{req.user_id}:{_now_ms()}"

    main = _open_db(req.main_db_path)
    repo = _open_db(req.repo_db_path)
    try:
        ensure_system_tables(main)
        ensure_manifest(main, seed_defaults=True)
        ensure_system_tables(repo)
        ensure_team_checkout_tables(repo)
        ensure_manifest(repo, seed_defaults=True)

        acquire_object_lock(main, key=key, user_id=req.user_id, lock_token=lock_token, comment=req.comment)

        # Copy manifest row (object root) into repo.
        src_rows = main.table(MANIFEST_TABLE).select(where={"guid": req.object_id}) or []
        if not src_rows:
            raise MpdbError(f"Object not found in main DB: {req.object_id}")
        src = dict(src_rows[0])

        # Upsert into repo manifest.
        _upsert_row(
            repo.table(MANIFEST_TABLE),
            where={"guid": req.object_id},
            values=src,
        )

        # Track checkout in repo.
        _upsert_row(
            repo.table(REPO_CHECKOUTS_TABLE),
            where={"lock_key": lock_key, "status": "active"},
            values={
                "id": f"{lock_key}:{lock_token}",
                "lock_key": lock_key,
                "lock_token": lock_token,
                "main_db_path": req.main_db_path,
                "object_type": req.object_type,
                "object_id": req.object_id,
                "component_type": req.component_type,
                "component_id": req.component_id,
                "checked_out_by": req.user_id,
                "checked_out_at": _now_ms(),
                "status": "active",
            },
        )

        return lock_key
    except Exception:
        # If anything fails after acquiring the lock, attempt to release it.
        try:
            release_object_lock(main, lock_key=lock_key, lock_token=lock_token, user_id=req.user_id, force=False)
        except Exception:
            pass
        raise
    finally:
        main.close()
        repo.close()


def submit(
    *,
    repo_db_path: str,
    object_id: str,
    component_type: str,
    component_id: str,
    user_id: str,
    force: bool = False,
) -> None:
    """Submit a checked-out object/component from RepoDB to MainDB."""

    repo = _open_db(repo_db_path)
    try:
        ensure_team_checkout_tables(repo)
        rows = repo.table(REPO_CHECKOUTS_TABLE).select(
            where={
                "object_id": (object_id or "").strip(),
                "component_type": (component_type or "").strip(),
                "component_id": (component_id or "-").strip() or "-",
                "status": "active",
            }
        ) or []
        if not rows:
            raise MpdbError("No active checkout found for this component")
        c = rows[0]
        main_db_path = str(c.get("main_db_path") or "").strip()
        lock_key = str(c.get("lock_key") or "").strip()
        lock_token = str(c.get("lock_token") or "").strip()

        main = _open_db(main_db_path)
        try:
            ensure_system_tables(main)
            ensure_manifest(main, seed_defaults=True)
            ensure_manifest(repo, seed_defaults=True)

            src_rows = repo.table(MANIFEST_TABLE).select(where={"guid": object_id}) or []
            if not src_rows:
                raise MpdbError("Object missing in repo manifest")
            src = dict(src_rows[0])

            _upsert_row(main.table(MANIFEST_TABLE), where={"guid": object_id}, values=src)

            ok = release_object_lock(main, lock_key=lock_key, lock_token=lock_token, user_id=user_id, force=force)
            if not ok:
                raise MpdbError("Unable to release lock (token mismatch or not owner)")

            repo.table(REPO_CHECKOUTS_TABLE).update(
                where={"id": str(c.get("id") or "")},
                set_values={"status": "submitted"},
            )
        finally:
            main.close()
    finally:
        repo.close()


def force_unlock(
    *,
    main_db_path: str,
    lock_key: str,
    user_id: str,
) -> bool:
    """Force-release a lock in MainDB.

    Role checks are enforced by the UI layer (Admin/ConfigMaintainer).
    """

    main = _open_db(main_db_path)
    try:
        ensure_system_tables(main)
        return release_object_lock(main, lock_key=lock_key, lock_token="", user_id=user_id, force=True)
    finally:
        main.close()
