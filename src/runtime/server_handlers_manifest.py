from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.configurator.cache.structure_cache import (
    drop_structure_cache,
    load_structure_cache_meta,
    load_structure_cache_payload,
    save_structure_cache_snapshot,
    save_structure_cache_meta_only,
)
from src.configurator.persistence.manifest_io import (
    add_object,
    bulk_update_payloads,
    build_manifest_schema_index,
    delete_object,
    ensure_manifest,
    _load_manifest_payload_asset,
    list_object_rows,
    list_objects,
    prune_orphans,
    update_fields,
    update_payload,
    update_title,
)
from src.configurator.manifest_schema import MANIFEST_TABLE
from src.configurator.persistence.system_tables import ensure_system_tables

from .server_state import RpcResponse, STATE_DBS, STATE_SESSIONS

logger = logging.getLogger("runtime.manifest")


def _obj_to_dict(o: Any, *, slim: bool = False) -> dict[str, Any]:
    d = {
        "guid":        str(o.guid),
        "type":        str(o.type),
        "kind":        str(o.kind),
        "name":        str(o.name or ""),
        "title":       str(o.title or ""),
        "parent_guid": str(o.parent_guid or ""),
    }
    if not slim:
        d["payload"] = o.payload if isinstance(o.payload, dict) else {}
    return d


def _objs_to_dicts(objs: list[Any], *, slim: bool = False) -> list[dict[str, Any]]:
    return [_obj_to_dict(o, slim=slim) for o in objs]


def _slim_subsystem_objects(db, row: dict[str, Any]) -> list[str]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    objs = payload.get("objects")
    if isinstance(objs, list):
        return [str(g).strip() for g in objs if str(g).strip()]
    ref = str(payload.get("objects_ref") or "").strip()
    if not ref:
        return []
    try:
        loaded = _load_manifest_payload_asset(db, ref=ref)
        if isinstance(loaded, list):
            return [str(g).strip() for g in loaded if str(g).strip()]
    except Exception:
        pass
    return []


def _manifest_source_row_for_guid(db, guid: str) -> dict[str, Any] | None:
    """Read a complete source row, never a lossy slim-tree projection."""

    guid = str(guid or "").strip()
    if not guid:
        return None
    active = _active_db_info_for_db(db)
    if active is not None:
        row = STATE_MANIFEST_LIST_CACHE.get_row_if_current(*active, guid, full_payload=True)
        if row is not None:
            return row
    try:
        rows = db.table(MANIFEST_TABLE).select(where={"guid": guid}) or []
    except Exception:
        return None
    row = next((r for r in rows if str(r.get("guid") or "") == guid), None)
    return row if isinstance(row, dict) else None


def _manifest_payload_for_guid(db, guid: str) -> dict[str, Any] | None:
    """Load payload for a single manifest object without hydrating all objects."""

    row = _manifest_source_row_for_guid(db, guid)
    if not isinstance(row, dict):
        return None
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    try:
        from src.configurator.persistence.manifest_io import _hydrate_manifest_payload

        return _hydrate_manifest_payload(db, payload)
    except Exception:
        return dict(payload or {})


def _manifest_objects_for_guid(db, guid: str) -> list[str] | None:
    """Load only subsystem membership objects without hydrating full payload."""

    row = _manifest_source_row_for_guid(db, guid)
    if not isinstance(row, dict):
        return None
    return _slim_subsystem_objects(db, row)


def _manifest_row_for_guid(db, guid: str) -> dict[str, Any] | None:
    """Load a single manifest row without hydrating external payloads."""

    guid = str(guid or "").strip()
    if not guid:
        return None
    # The warm manifest index is already the authoritative snapshot for the
    # active DB generation.  Reuse it for point lookups instead of scanning
    # the manifest table on every client click.
    active = _active_db_info_for_db(db)
    if active is not None:
        row = STATE_MANIFEST_LIST_CACHE.get_row_if_current(*active, guid)
        if row is not None:
            return row
    try:
        rows = db.table(MANIFEST_TABLE).select(where={"guid": guid}) or []
    except Exception:
        return None
    row = next((r for r in rows if str(r.get("guid") or "") == guid), None)
    if not isinstance(row, dict):
        return None
    return _slim_manifest_rows_from_cache_rows([dict(row)])[0] if row else None


def _manifest_subtree_for_guid(db, guid: str) -> list[dict[str, Any]] | None:
    """Load a manifest subtree (row + descendants) without hydrating payloads."""

    guid = str(guid or "").strip()
    if not guid:
        return None
    active = _active_db_info_for_db(db)
    if active is not None:
        subtree = STATE_MANIFEST_LIST_CACHE.get_subtree_if_current(*active, guid)
        if subtree is not None:
            return subtree or None
    cached = None
    if cached is None and active is not None:
        try:
            cached = _build_manifest_list_slim(db, active=active)
        except Exception:
            cached = None
    if cached is not None:
        by_parent: dict[str, list[dict[str, Any]]] = {}
        by_guid: dict[str, dict[str, Any]] = {}
        for item in cached:
            if not isinstance(item, dict):
                continue
            item_guid = str(item.get("guid") or "").strip()
            if not item_guid:
                continue
            by_guid[item_guid] = item
            by_parent.setdefault(str(item.get("parent_guid") or "").strip(), []).append(item)
        root = by_guid.get(guid)
        if not isinstance(root, dict):
            return None
        out: list[dict[str, Any]] = []
        seen: set[str] = set()

        def walk_cached(node: dict[str, Any]) -> None:
            nid = str(node.get("guid") or "").strip()
            if not nid or nid in seen:
                return
            seen.add(nid)
            out.append(dict(node))
            for child in by_parent.get(nid, []):
                walk_cached(child)

        walk_cached(root)
        return out

    try:
        root_rows = db.table(MANIFEST_TABLE).select(where={"guid": guid}) or []
    except Exception:
        return None
    root = next((r for r in root_rows if str(r.get("guid") or "") == guid), None)
    if not isinstance(root, dict):
        return None

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def walk(node: dict[str, Any]) -> None:
        nid = str(node.get("guid") or "").strip()
        if not nid or nid in seen:
            return
        seen.add(nid)
        out.append(dict(node))
        try:
            children = db.table(MANIFEST_TABLE).select(where={"parent_guid": nid}) or []
        except Exception:
            children = []
        for child in children:
            if not isinstance(child, dict):
                continue
            walk(child)

    walk(root)
    return _slim_manifest_rows_from_cache_rows(out)


def _manifest_info_meta_only(db_uid: str, db_path: str, rows: list[dict[str, Any]]):
    from src.configurator.cache.structure_cache import compute_structure_hash

    return save_structure_cache_meta_only(
        db_path,
        db_uid=db_uid,
        structure_hash=compute_structure_hash(rows),
        object_count=len(rows),
        generated_at=int(time.time()),
    )


def _manifest_info_full_snapshot(db_uid: str, db_path: str, objs: list[Any]):
    return save_structure_cache_snapshot(
        db_path,
        db_uid=db_uid,
        generated_at=int(time.time()),
        objects=objs,
    )


class ManifestInfoMemoryCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _stat(db_path: str) -> tuple[int, int]:
        try:
            st = Path(db_path).stat()
            return int(st.st_mtime_ns), int(st.st_size)
        except OSError:
            return 0, 0

    def get_if_current(self, db_uid: str, db_path: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._entries.get(str(db_uid or ""))
            if not isinstance(entry, dict):
                return None
            mtime_ns, size = self._stat(db_path)
            if int(entry.get("db_mtime_ns") or 0) != mtime_ns or int(entry.get("db_size") or 0) != size:
                self._entries.pop(str(db_uid or ""), None)
                return None
            return dict(entry)

    def put(self, db_uid: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._entries[str(db_uid or "")] = dict(payload)

    def invalidate(self, db_uid: str) -> None:
        with self._lock:
            self._entries.pop(str(db_uid or ""), None)


STATE_MANIFEST_INFO_CACHE = ManifestInfoMemoryCache()


class ManifestListMemoryCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _stat(db_path: str) -> tuple[int, int]:
        try:
            st = Path(db_path).stat()
            return int(st.st_mtime_ns), int(st.st_size)
        except OSError:
            return 0, 0

    def _entry_if_current(self, db_uid: str, db_path: str) -> dict[str, Any] | None:
        # Callers hold _lock while checking the generation and reading its index.
        entry = self._entries.get(str(db_uid or ""))
        if not isinstance(entry, dict):
            return None
        mtime_ns, size = self._stat(db_path)
        if (
            entry.get("db_path") != str(db_path)
            or int(entry.get("db_mtime_ns") or 0) != mtime_ns
            or int(entry.get("db_size") or 0) != size
        ):
            self._entries.pop(str(db_uid or ""), None)
            return None
        return entry

    def get_if_current(self, db_uid: str, db_path: str) -> list[dict[str, Any]] | None:
        with self._lock:
            entry = self._entry_if_current(db_uid, db_path)
            if entry is None:
                return None
            objects = entry.get("objects")
            return [dict(row) for row in objects] if isinstance(objects, list) else None

    def get_row_if_current(
        self, db_uid: str, db_path: str, guid: str, *, full_payload: bool = False,
    ) -> dict[str, Any] | None:
        with self._lock:
            entry = self._entry_if_current(db_uid, db_path)
            if entry is None:
                return None
            index = entry["source_by_guid" if full_payload else "by_guid"]
            row = index.get(guid)
            # Copy only the requested row, including mutable inline payload data.
            return deepcopy(row) if row is not None else None

    def get_subtree_if_current(
        self, db_uid: str, db_path: str, guid: str,
    ) -> list[dict[str, Any]] | None:
        with self._lock:
            entry = self._entry_if_current(db_uid, db_path)
            if entry is None:
                return None
            result = []
            pending = [guid]
            seen = set()
            while pending:
                current = pending.pop()
                if current in seen:
                    continue
                seen.add(current)
                row = entry["by_guid"].get(current)
                if row is not None:
                    result.append(deepcopy(row))
                    pending.extend(reversed(entry["children"].get(current, [])))
            return result

    def put(
        self, db_uid: str, db_path: str, objects: list[dict[str, Any]], *,
        source_objects: list[dict[str, Any]] | None = None,
    ) -> None:
        with self._lock:
            mtime_ns, size = self._stat(db_path)
            cached_rows = [dict(row) for row in objects]
            children: dict[str, list[str]] = {}
            for row in cached_rows:
                children.setdefault(str(row.get("parent_guid") or ""), []).append(str(row.get("guid") or ""))
            self._entries[str(db_uid or "")] = {
                "db_path": str(db_path),
                "db_mtime_ns": mtime_ns,
                "db_size": size,
                "objects": cached_rows,
                "by_guid": {str(row.get("guid") or ""): row for row in cached_rows},
                "children": children,
                # Full payloads are retained only when explicitly supplied by a
                # raw DB scan or a validated structure snapshot, never slim rows.
                "source_by_guid": {
                    str(row.get("guid") or ""): deepcopy(row)
                    for row in source_objects or []
                },
            }

    def invalidate(self, db_uid: str) -> None:
        with self._lock:
            self._entries.pop(str(db_uid or ""), None)


STATE_MANIFEST_LIST_CACHE = ManifestListMemoryCache()
STATE_MANIFEST_SCHEMA_CACHE = ManifestListMemoryCache()
_MANIFEST_WARMUP_LOCK = threading.RLock()
_MANIFEST_WARMUP_RUNNING: set[str] = set()


def _active_db_info_for_db(db) -> tuple[str, str] | None:
    """Resolve cache identity for a live DB handle without a client session."""

    db_uid = str(getattr(db, "db_uid", "") or "").strip()
    if not db_uid:
        for candidate_uid, entry in getattr(STATE_DBS, "_dbs", {}).items():
            if isinstance(entry, tuple) and len(entry) >= 2 and entry[1] is db:
                db_uid = str(candidate_uid or "").strip()
                break
    if not db_uid:
        return None
    db_path = str(STATE_DBS.get_path(db_uid) or "").strip()
    return (db_uid, db_path) if db_path else None


def _manifest_info_payload(db_uid: str, db_path: str, meta) -> dict[str, Any]:
    return {
        "db_uid": db_uid,
        "db_path": db_path,
        "structure_hash": meta.structure_hash,
        "object_count": meta.object_count,
        "generated_at": meta.generated_at,
        "db_mtime_ns": meta.db_mtime_ns,
        "db_size": meta.db_size,
    }


def _slim_manifest_rows_from_cache_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source_row in rows or []:
        if not isinstance(source_row, dict):
            continue
        row = {
            "guid": str(source_row.get("guid") or ""),
            "type": str(source_row.get("type") or ""),
            "kind": str(source_row.get("kind") or ""),
            "name": str(source_row.get("name") or ""),
            "title": str(source_row.get("title") or ""),
            "parent_guid": str(source_row.get("parent_guid") or ""),
        }
        payload = source_row.get("payload") if isinstance(source_row.get("payload"), dict) else {}
        if isinstance(payload, dict):
            # Preserve only structural flags required by the tree and context
            # menus. Dropping these made physical system folders appear as raw
            # `forms/commands/layouts` names and removed their protection.
            for key in (
                "auto",
                "menu",
                "order",
                "protected",
                "seed",
                "section",
                "subtype",
                "system",
                "virtual",
            ):
                if key in payload:
                    row.setdefault("payload", {})[key] = payload[key]
            imported = payload.get("imported") if isinstance(payload.get("imported"), dict) else {}
            origin = str(imported.get("origin") or "").strip()
            if origin:
                row.setdefault("payload", {})
                row["payload"]["imported"] = {"origin": origin}
            metadata_ref = str(payload.get("metadata_ref") or "").strip()
            if metadata_ref:
                row.setdefault("payload", {})
                row["payload"]["metadata_ref"] = metadata_ref
            if str(source_row.get("type") or "").lower() == "subsystem":
                objs_list = payload.get("objects")
                if isinstance(objs_list, list):
                    row["objects"] = [str(x).strip() for x in objs_list if str(x).strip()]
        result.append(row)
    return result


def _build_manifest_list_slim(db, *, active: tuple[str, str] | None = None) -> list[dict[str, Any]]:
    """Build slim manifest rows without hydrating external payloads."""

    rows = list_object_rows(db)
    result: list[dict[str, Any]] = []
    for r in rows:
        base = {
            "guid": str(r.get("guid") or ""),
            "type": str(r.get("type") or ""),
            "kind": str(r.get("kind") or ""),
            "name": str(r.get("name") or ""),
            "title": str(r.get("title") or ""),
            "parent_guid": str(r.get("parent_guid") or ""),
        }
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        for key in (
            "auto",
            "menu",
            "order",
            "protected",
            "seed",
            "section",
            "subtype",
            "system",
            "virtual",
        ):
            if key in payload:
                base.setdefault("payload", {})[key] = payload[key]
        imported = payload.get("imported") if isinstance(payload.get("imported"), dict) else {}
        origin = str(imported.get("origin") or "").strip()
        if origin:
            base.setdefault("payload", {})["imported"] = {"origin": origin}
        metadata_ref = str(payload.get("metadata_ref") or "").strip()
        if metadata_ref:
            base.setdefault("payload", {})
            base["payload"]["metadata_ref"] = metadata_ref
        if str(r.get("type") or "").lower() == "subsystem":
            base["objects"] = _slim_subsystem_objects(db, r)
        result.append(base)
    active = active or _active_db_info_for_db(db)
    if active is not None:
        STATE_MANIFEST_LIST_CACHE.put(*active, result, source_objects=rows)
    return result


def _filter_manifest_nav_slim(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter the warm structure index down to client navigation rows."""

    nav_types = {"catalog", "document", "register_accum", "register_info", "report", "subsystem"}
    result: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("kind") or "").lower() != "object":
            continue
        if str(row.get("type") or "").lower() not in nav_types:
            continue
        result.append(dict(row))
    return result


def _build_manifest_nav_slim(db) -> list[dict[str, Any]]:
    """Build only the rows needed for client navigation."""

    return _filter_manifest_nav_slim(_build_manifest_list_slim(db))


def warm_manifest_caches(db, *, db_uid: str, db_path: str) -> None:
    """Populate info/list caches for a DB if they are stale or missing."""

    db_uid = str(db_uid or "").strip()
    db_path = str(db_path or "").strip()
    if not db_uid or not db_path:
        return

    cache_key = f"{db_uid}|{db_path}"
    with _MANIFEST_WARMUP_LOCK:
        if cache_key in _MANIFEST_WARMUP_RUNNING:
            return
        _MANIFEST_WARMUP_RUNNING.add(cache_key)

    started = time.perf_counter()
    try:
        if getattr(db, "_opened", True) is False:
            return
        cached_info = STATE_MANIFEST_INFO_CACHE.get_if_current(db_uid, db_path)
        cached_list = STATE_MANIFEST_LIST_CACHE.get_if_current(db_uid, db_path)
        if cached_info is not None and cached_list is not None:
            return

        ensure_system_tables(db)
        ensure_manifest(db, seed_defaults=False)

        meta = load_structure_cache_meta(db_path, db_uid=db_uid, verify_db_state=True)
        cached_rows: list[dict[str, Any]] | None = None
        if meta is not None and int(meta.object_count or 0) > 0:
            payload_cache = load_structure_cache_payload(db_path, db_uid=db_uid, verify_db_state=True)
            if payload_cache is not None and payload_cache.objects:
                cached_rows = _slim_manifest_rows_from_cache_rows(list(payload_cache.objects or []))
                STATE_MANIFEST_LIST_CACHE.put(
                    db_uid, db_path, cached_rows, source_objects=payload_cache.objects,
                )
        if meta is None or int(meta.object_count or 0) == 0 or cached_rows is None:
            rows = _build_manifest_list_slim(db, active=(db_uid, db_path))
            meta = _manifest_info_meta_only(db_uid, db_path, rows)
        data = _manifest_info_payload(db_uid, db_path, meta)
        STATE_MANIFEST_INFO_CACHE.put(db_uid, data)
    except Exception as exc:
        if "database closed" in str(exc).casefold():
            logger.debug("warmup.cancelled db_uid=%s reason=database_closed", db_uid)
        else:
            logger.exception("warmup.failed db_uid=%s", db_uid)
    finally:
        with _MANIFEST_WARMUP_LOCK:
            _MANIFEST_WARMUP_RUNNING.discard(cache_key)
        logger.info(
            "warmup.finished db_uid=%s took=%.3fs",
            db_uid,
            time.perf_counter() - started,
        )


def _active_db_info(payload: dict[str, Any]) -> tuple[str, str] | RpcResponse:
    sid = str(payload.get("session_id") or "")
    db_uid = str(STATE_SESSIONS.get_active_db_uid(sid) or "")
    if not db_uid:
        return RpcResponse("error", error="No active database for this session")
    db_path = str(STATE_DBS.get_path(db_uid) or "").strip()
    if not db_path:
        return RpcResponse("error", error="Active DB path not found in pool")
    return db_uid, db_path


def _invalidate_for_payload(payload: dict[str, Any], *, drop_disk_cache: bool = False) -> None:
    active = _active_db_info(payload)
    if isinstance(active, RpcResponse):
        return
    db_uid, db_path = active
    STATE_MANIFEST_INFO_CACHE.invalidate(db_uid)
    STATE_MANIFEST_LIST_CACHE.invalidate(db_uid)
    STATE_MANIFEST_SCHEMA_CACHE.invalidate(db_uid)
    if drop_disk_cache:
        try:
            drop_structure_cache(db_path)
        except Exception:
            pass


def _do_manifest_open(db, *, seed: bool, seed_if_empty: bool) -> list[Any]:
    ensure_system_tables(db)
    ensure_manifest(db, seed_defaults=False)
    rows = list_object_rows(db)
    if prune_orphans(db):
        rows = list_object_rows(db)
    if (seed or seed_if_empty) and not rows:
        ensure_manifest(db, seed_defaults=True)
        if prune_orphans(db):
            rows = list_object_rows(db)
        else:
            rows = list_object_rows(db)
    if prune_orphans(db):
        rows = list_object_rows(db)
    return list_objects(db)


def handle_manifest_action(handler, action: str, payload: dict) -> RpcResponse | None:
    if action == "manifest.info":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        active = _active_db_info(payload)
        if isinstance(active, RpcResponse):
            return active
        db_uid, db_path = active

        started = time.perf_counter()
        try:
            cached = STATE_MANIFEST_INFO_CACHE.get_if_current(db_uid, db_path)
            if cached is not None:
                print(
                    f"[runtime.manifest.info] memory-hit took={time.perf_counter() - started:.3f}s",
                    flush=True,
                )
                return RpcResponse("ok", cached)

            meta = load_structure_cache_meta(db_path, db_uid=db_uid, verify_db_state=True)
            if meta is not None:
                cached_list: list[dict[str, Any]] | None = None
                try:
                    payload = load_structure_cache_payload(db_path, db_uid=db_uid, verify_db_state=True)
                    if payload is not None and int(payload.meta.object_count or 0) > 0:
                        cached_list = _slim_manifest_rows_from_cache_rows(list(payload.objects or []))
                except Exception:
                    cached_list = None
                if cached_list is not None:
                    STATE_MANIFEST_LIST_CACHE.put(
                        db_uid, db_path, cached_list, source_objects=payload.objects,
                    )
                if int(meta.object_count or 0) == 0:
                    ensure_system_tables(db)
                    ensure_manifest(db, seed_defaults=False)
                    live_rows = list_object_rows(db)
                    if live_rows:
                        from src.configurator.persistence.manifest_io import list_objects as _list_objs

                        try:
                            objs = _list_objs(db, hydrate_payload=False)
                            meta = _manifest_info_full_snapshot(db_uid, db_path, objs)
                        except Exception:
                            meta = _manifest_info_meta_only(db_uid, db_path, live_rows)
                        data = _manifest_info_payload(db_uid, db_path, meta)
                        STATE_MANIFEST_INFO_CACHE.put(db_uid, data)
                        print(
                            f"[runtime.manifest.info] repaired zero cache objects={meta.object_count} took={time.perf_counter() - started:.3f}s",
                            flush=True,
                        )
                        return RpcResponse("ok", data)
                data = _manifest_info_payload(db_uid, db_path, meta)
                STATE_MANIFEST_INFO_CACHE.put(db_uid, data)
                print(
                    f"[runtime.manifest.info] cache-hit took={time.perf_counter() - started:.3f}s",
                    flush=True,
                )
                return RpcResponse("ok", data)

            ensure_system_tables(db)
            ensure_manifest(db, seed_defaults=False)
            # Use hydrate_payload=False for cache rebuild — payload is not needed
            # for the tree view, and hydration of 9k+ external assets is very slow.
            from src.configurator.persistence.manifest_io import list_objects as _list_objs
            objs = _list_objs(db, hydrate_payload=False)
            try:
                meta = _manifest_info_full_snapshot(db_uid, db_path, objs)
            except Exception:
                rows = list_object_rows(db)
                meta = _manifest_info_meta_only(db_uid, db_path, rows)
            data = _manifest_info_payload(db_uid, db_path, meta)
            STATE_MANIFEST_INFO_CACHE.put(db_uid, data)
            if 'objs' in locals() and isinstance(objs, list):
                try:
                    STATE_MANIFEST_LIST_CACHE.put(
                        db_uid,
                        db_path,
                        _slim_manifest_rows_from_cache_rows([_obj_to_dict(o) for o in objs]),
                        source_objects=[_obj_to_dict(o) for o in objs],
                    )
                except Exception:
                    pass
            print(
                f"[runtime.manifest.info] rebuilt cache objects={meta.object_count} took={time.perf_counter() - started:.3f}s",
                flush=True,
            )
            return RpcResponse("ok", data)
        except Exception as e:
            return RpcResponse("error", error=f"manifest.info: {e}")

    if action == "manifest.open":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        try:
            objs = _do_manifest_open(
                db,
                seed=bool(payload.get("seed_defaults", True)),
                seed_if_empty=bool(payload.get("seed_defaults_if_empty", False)),
            )
            _invalidate_for_payload(payload, drop_disk_cache=True)
            return RpcResponse("ok", {"objects": _objs_to_dicts(objs)})
        except Exception as e:
            sid = str(payload.get("session_id") or "")
            db_uid = STATE_SESSIONS.get_active_db_uid(sid) if sid else None
            if db_uid:
                print(f"[manifest.open] DB corrupt ({e}), attempting recovery...", flush=True)
                try:
                    db = STATE_DBS.reopen_fresh(db_uid)
                    objs = _do_manifest_open(
                        db,
                        seed=bool(payload.get("seed_defaults", True)),
                        seed_if_empty=bool(payload.get("seed_defaults_if_empty", False)),
                    )
                    _invalidate_for_payload(payload, drop_disk_cache=True)
                    print("[manifest.open] recovery successful", flush=True)
                    return RpcResponse("ok", {"objects": _objs_to_dicts(objs)})
                except Exception as e2:
                    return RpcResponse("error", error=f"manifest.open: recovery failed: {e2}")
            return RpcResponse("error", error=f"manifest.open: {e}")

    if action == "manifest.schema_index":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        try:
            started = time.perf_counter()
            active = _active_db_info(payload)
            if not isinstance(active, RpcResponse):
                db_uid, db_path = active
                cached = STATE_MANIFEST_SCHEMA_CACHE.get_if_current(db_uid, db_path)
                if cached is not None:
                    print(
                        f"[runtime.manifest.schema_index] memory-hit objects={len(cached)} "
                        f"took={time.perf_counter() - started:.3f}s",
                        flush=True,
                    )
                    return RpcResponse("ok", {"objects": cached})

            structure_rows: list[dict[str, Any]] | None = None
            if not isinstance(active, RpcResponse):
                db_uid, db_path = active
                structure_rows = STATE_MANIFEST_LIST_CACHE.get_if_current(db_uid, db_path)
                if structure_rows is None:
                    try:
                        payload_cache = load_structure_cache_payload(
                            db_path,
                            db_uid=db_uid,
                            verify_db_state=True,
                        )
                        if payload_cache is not None and payload_cache.objects:
                            structure_rows = _slim_manifest_rows_from_cache_rows(
                                list(payload_cache.objects or [])
                            )
                    except Exception:
                        structure_rows = None
            if structure_rows is None:
                structure_rows = _build_manifest_list_slim(db)

            result = build_manifest_schema_index(db, structure_rows)
            if not isinstance(active, RpcResponse):
                STATE_MANIFEST_SCHEMA_CACHE.put(db_uid, db_path, result)
            print(
                f"[runtime.manifest.schema_index] objects={len(result)} "
                f"took={time.perf_counter() - started:.3f}s",
                flush=True,
            )
            return RpcResponse("ok", {"objects": result})
        except Exception as e:
            return RpcResponse("error", error=f"manifest.schema_index: {e}")

    if action == "manifest.list":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        slim = bool(payload.get("slim", True))
        try:
            started = time.perf_counter()
            if slim:
                active = _active_db_info(payload)
                if not isinstance(active, RpcResponse):
                    db_uid, db_path = active
                    cached = STATE_MANIFEST_LIST_CACHE.get_if_current(db_uid, db_path)
                    if cached is not None:
                        print(
                            f"[runtime.manifest.list] memory-hit objects={len(cached)} slim={slim} took={time.perf_counter() - started:.3f}s",
                            flush=True,
                        )
                        return RpcResponse("ok", {"objects": cached})
                    try:
                        meta = load_structure_cache_meta(db_path, db_uid=db_uid, verify_db_state=True)
                        if meta is not None and int(meta.object_count or 0) > 0:
                            payload_cache = load_structure_cache_payload(
                                db_path, db_uid=db_uid, verify_db_state=True
                            )
                            if payload_cache is not None and payload_cache.objects:
                                cached_list = _slim_manifest_rows_from_cache_rows(list(payload_cache.objects or []))
                                STATE_MANIFEST_LIST_CACHE.put(
                                    db_uid, db_path, cached_list, source_objects=payload_cache.objects,
                                )
                                print(
                                    f"[runtime.manifest.list] disk-cache-hit objects={len(cached_list)} slim={slim} took={time.perf_counter() - started:.3f}s",
                                    flush=True,
                                )
                                return RpcResponse("ok", {"objects": cached_list})
                    except Exception:
                        pass
                # Fast path: read raw rows without hydrating externalized assets.
                # For 15k objects this is much faster than a hydrated scan.
                result = _build_manifest_list_slim(
                    db, active=active if not isinstance(active, RpcResponse) else None,
                )
            else:
                objs = list_objects(db)
                result = _objs_to_dicts(objs, slim=False)
            print(
                f"[runtime.manifest.list] objects={len(result)} slim={slim} "
                f"took={time.perf_counter() - started:.3f}s",
                flush=True,
            )
            return RpcResponse("ok", {"objects": result})
        except Exception as e:
            return RpcResponse("error", error=f"manifest.list: {e}")

    if action == "manifest.nav":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        try:
            started = time.perf_counter()
            active = _active_db_info(payload)
            if not isinstance(active, RpcResponse):
                db_uid, db_path = active
                cached = STATE_MANIFEST_LIST_CACHE.get_if_current(db_uid, db_path)
                if cached is not None:
                    nav_rows = _filter_manifest_nav_slim(cached)
                    print(
                        f"[runtime.manifest.nav] cache-hit objects={len(nav_rows)} took={time.perf_counter() - started:.3f}s",
                        flush=True,
                    )
                    return RpcResponse("ok", {"objects": nav_rows})
            nav_rows = _build_manifest_nav_slim(db)
            print(
                f"[runtime.manifest.nav] objects={len(nav_rows)} took={time.perf_counter() - started:.3f}s",
                flush=True,
            )
            return RpcResponse("ok", {"objects": nav_rows})
        except Exception as e:
            return RpcResponse("error", error=f"manifest.nav: {e}")

    if action == "manifest.lookup":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        type_name = str(payload.get("type") or "").strip().casefold()
        name = str(payload.get("name") or "").strip().casefold()
        limit = max(1, min(int(payload.get("limit") or 1000), 5000))
        if not type_name and not name:
            return RpcResponse("error", error="type or name required")
        try:
            active = _active_db_info(payload)
            rows: list[dict[str, Any]] | None = None
            if not isinstance(active, RpcResponse):
                db_uid, db_path = active
                rows = STATE_MANIFEST_LIST_CACHE.get_if_current(db_uid, db_path)
            if rows is None:
                rows = _build_manifest_list_slim(
                    db, active=active if not isinstance(active, RpcResponse) else None,
                )
            result: list[dict[str, Any]] = []
            for row in rows:
                if type_name and str(row.get("type") or "").strip().casefold() != type_name:
                    continue
                if name:
                    from src.dsl.module_introspection import repair_cp1251_mojibake_name

                    repaired_title = repair_cp1251_mojibake_name(str(row.get("title") or ""))
                    aliases = {
                        str(row.get("name") or "").strip().casefold(),
                        str(row.get("title") or "").strip().casefold(),
                        repaired_title.strip().casefold(),
                    }
                    if name not in aliases:
                        continue
                result.append(dict(row))
                if len(result) >= limit:
                    break
            return RpcResponse("ok", {"objects": result})
        except Exception as e:
            return RpcResponse("error", error=f"manifest.lookup: {e}")

    if action == "manifest.get_payload":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        guid = str(payload.get("guid") or "").strip()
        if not guid:
            return RpcResponse("error", error="guid required")
        try:
            obj_payload = _manifest_payload_for_guid(db, guid)
            if obj_payload is None:
                return RpcResponse("error", error=f"Object not found: {guid}")
            return RpcResponse("ok", {
                "guid":    guid,
                "payload": obj_payload,
            })
        except Exception as e:
            return RpcResponse("error", error=f"manifest.get_payload: {e}")

    if action == "manifest.object_context":
        """Return the lazy client context for one metadata object.

        The client needs the owner, its hydrated payload and form descendants
        to render a screen.  Keeping this aggregation in Runtime avoids a
        sequence of client-side table scans and still leaves module source
        text lazy (it is fetched only when a module is opened or executed).
        """
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        guid = str(payload.get("guid") or "").strip()
        if not guid:
            return RpcResponse("error", error="guid required")
        try:
            row = _manifest_row_for_guid(db, guid)
            if not isinstance(row, dict):
                return RpcResponse("error", error=f"Object not found: {guid}")
            owner_payload = _manifest_payload_for_guid(db, guid) or {}
            subtree = _manifest_subtree_for_guid(db, guid) or []
            form_rows: list[dict[str, Any]] = []
            form_guids: list[str] = []
            for item in subtree:
                item_guid = str(item.get("guid") or "").strip()
                item_type = str(item.get("type") or "").strip().lower()
                if not item_guid or item_guid == guid:
                    continue
                if item_type not in {"form", "common_form"}:
                    continue
                if str(item.get("kind") or "object").lower() != "object":
                    continue
                hydrated = dict(item)
                hydrated["payload"] = _manifest_payload_for_guid(db, item_guid) or {}
                form_rows.append(hydrated)
                form_guids.append(item_guid)

            # Module metadata is cheap; source remains a separate lazy call.
            from src.configurator.persistence.modules_dao import list_modules_by_owner

            module_rows: list[dict[str, Any]] = []
            for owner_guid in [guid, *form_guids]:
                for module in list_modules_by_owner(db, owner_guid=owner_guid) or []:
                    if isinstance(module, dict):
                        module_rows.append({k: v for k, v in module.items() if k != "text"})
            return RpcResponse("ok", {
                "guid": guid,
                "row": row,
                "payload": owner_payload,
                "forms": form_rows,
                "modules": module_rows,
            })
        except Exception as e:
            return RpcResponse("error", error=f"manifest.object_context: {e}")

    if action == "manifest.get_row":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        guid = str(payload.get("guid") or "").strip()
        if not guid:
            return RpcResponse("error", error="guid required")
        try:
            row = _manifest_row_for_guid(db, guid)
            if row is None:
                return RpcResponse("error", error=f"Object not found: {guid}")
            return RpcResponse("ok", {"guid": guid, "row": row})
        except Exception as e:
            return RpcResponse("error", error=f"manifest.get_row: {e}")

    if action == "manifest.get_objects":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        guid = str(payload.get("guid") or "").strip()
        if not guid:
            return RpcResponse("error", error="guid required")
        try:
            objects = _manifest_objects_for_guid(db, guid)
            if objects is None:
                return RpcResponse("error", error=f"Object not found: {guid}")
            return RpcResponse("ok", {
                "guid": guid,
                "objects": objects,
            })
        except Exception as e:
            return RpcResponse("error", error=f"manifest.get_objects: {e}")

    if action == "manifest.get_subtree":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        guid = str(payload.get("guid") or "").strip()
        if not guid:
            return RpcResponse("error", error="guid required")
        try:
            rows = _manifest_subtree_for_guid(db, guid)
            if rows is None:
                return RpcResponse("error", error=f"Object not found: {guid}")
            return RpcResponse("ok", {"rows": rows})
        except Exception as e:
            return RpcResponse("error", error=f"manifest.get_subtree: {e}")

    if action == "manifest.add":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        o = payload.get("object") or {}
        try:
            mo = add_object(
                db,
                obj_type=str(o.get("type") or ""),
                name=str(o.get("name") or ""),
                title=str(o.get("title") or ""),
                parent_guid=str(o.get("parent_guid") or ""),
                payload=o.get("payload") or {},
                kind=str(o.get("kind") or "object"),
            )
            _invalidate_for_payload(payload, drop_disk_cache=True)
            return RpcResponse("ok", {"object": _obj_to_dict(mo)})
        except Exception as e:
            return RpcResponse("error", error=f"manifest.add: {e}")

    if action == "manifest.update_payload":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        guid = str(payload.get("guid") or "")
        pay = payload.get("payload") or {}
        if not guid:
            return RpcResponse("error", error="guid required")
        started = time.perf_counter()
        try:
            update_payload(db, guid, pay)
            print(
                f"[runtime.manifest.update_payload] guid={guid} keys={sorted((pay or {}).keys())} took={time.perf_counter() - started:.3f}s",
                flush=True,
            )
            _invalidate_for_payload(payload, drop_disk_cache=True)
            return RpcResponse("ok", {"guid": guid})
        except Exception as e:
            return RpcResponse("error", error=f"manifest.update_payload: {e}")

    if action == "manifest.bulk_update_payloads":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        source = payload.get("payloads") or {}
        if not isinstance(source, dict):
            return RpcResponse("error", error="payloads must be an object")
        updates = {
            str(guid or "").strip(): value
            for guid, value in source.items()
            if str(guid or "").strip() and isinstance(value, dict)
        }
        if not updates:
            return RpcResponse("ok", {"updated": 0})
        started = time.perf_counter()
        try:
            updated = bulk_update_payloads(db, updates)
            print(
                f"[runtime.manifest.bulk_update_payloads] updated={updated} took={time.perf_counter() - started:.3f}s",
                flush=True,
            )
            _invalidate_for_payload(payload, drop_disk_cache=True)
            return RpcResponse("ok", {"updated": int(updated)})
        except Exception as e:
            return RpcResponse("error", error=f"manifest.bulk_update_payloads: {e}")

    if action == "manifest.update_title":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        guid = str(payload.get("guid") or "")
        title = str(payload.get("title") or "")
        if not guid:
            return RpcResponse("error", error="guid required")
        try:
            update_title(db, guid, title)
            _invalidate_for_payload(payload, drop_disk_cache=True)
            return RpcResponse("ok", {"guid": guid})
        except Exception as e:
            return RpcResponse("error", error=f"manifest.update_title: {e}")

    if action == "manifest.update_fields":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        guid = str(payload.get("guid") or "")
        if not guid:
            return RpcResponse("error", error="guid required")
        try:
            update_fields(
                db,
                guid,
                obj_type=payload.get("obj_type"),
                name=payload.get("name"),
                title=payload.get("title"),
                parent_guid=payload.get("parent_guid"),
                payload=payload.get("payload"),
            )
            _invalidate_for_payload(payload, drop_disk_cache=True)
            return RpcResponse("ok", {"guid": guid})
        except Exception as e:
            return RpcResponse("error", error=f"manifest.update_fields: {e}")

    if action == "manifest.delete":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        guid = str(payload.get("guid") or "")
        if not guid:
            return RpcResponse("error", error="guid required")
        try:
            try:
                objs = {o.guid: o for o in list_objects(db)}
                o = objs.get(guid)
                if o and str(o.type) == "common_picture":
                    p = o.payload if isinstance(o.payload, dict) else {}
                    ak = str(((p.get("picture") or {}).get("asset_key") or "")).strip()
                    if ak:
                        try:
                            db.delete_asset(ak)
                        except Exception:
                            pass
            except Exception:
                pass
            delete_object(db, guid)
            try:
                prune_orphans(db)
            except Exception:
                pass
            _invalidate_for_payload(payload, drop_disk_cache=True)
            return RpcResponse("ok", {"guid": guid})
        except Exception as e:
            return RpcResponse("error", error=f"manifest.delete: {e}")

    return None
