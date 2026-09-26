from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

from src.dsl.workspace_symbols import (
    WorkspaceSemanticIndex,
    build_workspace_semantic_index,
    filter_form_shadow_diagnostics,
    workspace_symbol_id,
)
from src.configurator.persistence.modules_dao import (
    apply_module_text_updates_atomic,
    get_module_text_from_row,
    get_module_text,
    list_modules_by_owner,
    normalize_modules_language,
    resolve_common_module,
    search_module_sources,
    update_module_text,
)
from src.configurator.persistence.modules_tables import MODULES_TABLE

from .server_handlers_manifest import STATE_MANIFEST_LIST_CACHE
from .server_state import RpcResponse, STATE_DBS, STATE_SESSIONS


class ModuleResolutionMemoryCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, dict] = {}

    @staticmethod
    def _stat(db_path: str) -> tuple[int, int]:
        try:
            stat = Path(db_path).stat()
            return int(stat.st_mtime_ns), int(stat.st_size)
        except OSError:
            return 0, 0

    def get(self, db_uid: str, db_path: str, name: str) -> tuple[bool, dict | None]:
        with self._lock:
            entry = self._entries.get(str(db_uid or ""))
            if not isinstance(entry, dict):
                return False, None
            mtime_ns, size = self._stat(db_path)
            if (int(entry.get("mtime_ns") or 0), int(entry.get("size") or 0)) != (mtime_ns, size):
                self._entries.pop(str(db_uid or ""), None)
                return False, None
            modules = entry.get("modules")
            key = str(name or "").strip().casefold()
            if not isinstance(modules, dict) or key not in modules:
                return False, None
            module = modules[key]
            return True, dict(module) if isinstance(module, dict) else None

    def put(self, db_uid: str, db_path: str, name: str, module: dict | None) -> None:
        with self._lock:
            mtime_ns, size = self._stat(db_path)
            entry = self._entries.get(str(db_uid or ""))
            if not isinstance(entry, dict) or (
                int(entry.get("mtime_ns") or 0), int(entry.get("size") or 0)
            ) != (mtime_ns, size):
                entry = {"mtime_ns": mtime_ns, "size": size, "modules": {}}
                self._entries[str(db_uid or "")] = entry
            entry["modules"][str(name or "").strip().casefold()] = dict(module) if isinstance(module, dict) else None

    def invalidate(self, db_uid: str) -> None:
        with self._lock:
            self._entries.pop(str(db_uid or ""), None)


STATE_MODULE_RESOLUTION_CACHE = ModuleResolutionMemoryCache()
STATE_MODULE_COMPLETION_CACHE = ModuleResolutionMemoryCache()


class ModuleSourceMemoryCache:
    """Hydrated module sources used by Runtime-side IDE text search."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, dict] = {}

    @staticmethod
    def _revision_signature(rows: list[dict]) -> tuple[tuple, ...]:
        return tuple(
            sorted(
                (
                    str(row.get("module_guid") or ""),
                    str(row.get("sha256") or ""),
                    int(row.get("version") or 0),
                    int(row.get("updated_at") or 0),
                    int(row.get("size_bytes") or 0),
                    str(row.get("storage_kind") or ""),
                    str(row.get("content_ref") or ""),
                    str(row.get("text") or "") if not row.get("sha256") else "",
                )
                for row in rows
            )
        )

    def get_or_build(self, db_uid: str, db_path: str, db) -> list[dict]:
        with self._lock:
            mtime_ns, size = ModuleResolutionMemoryCache._stat(db_path)
            entry = self._entries.get(str(db_uid or ""))
            if isinstance(entry, dict) and (
                int(entry.get("mtime_ns") or 0),
                int(entry.get("size") or 0),
            ) == (mtime_ns, size):
                return list(entry.get("sources") or [])
            rows = [dict(row) for row in (db.table(MODULES_TABLE).select(where=None) or [])]
            signature = self._revision_signature(rows)
            if isinstance(entry, dict) and entry.get("signature") == signature:
                entry["mtime_ns"] = mtime_ns
                entry["size"] = size
                return list(entry.get("sources") or [])
            sources = []
            for row in rows:
                item = dict(row)
                item["source_text"] = get_module_text_from_row(db, row)
                item["_source_text_casefold"] = item["source_text"].casefold()
                sources.append(item)
            self._entries[str(db_uid or "")] = {
                "mtime_ns": mtime_ns,
                "size": size,
                "signature": signature,
                "sources": sources,
            }
            return list(sources)

    def invalidate(self, db_uid: str) -> None:
        with self._lock:
            self._entries.pop(str(db_uid or ""), None)


STATE_MODULE_SOURCE_CACHE = ModuleSourceMemoryCache()


class WorkspaceSemanticIndexMemoryCache:
    """Runtime-owned semantic index tied to the current mpdb file state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, dict] = {}
        self._generations: dict[str, int] = {}
        self._build_events: dict[str, threading.Event] = {}

    @staticmethod
    def _manifest_revision_signature(rows: list[dict]) -> tuple[tuple, ...]:
        schema_keys = (
            "attributes",
            "requisites",
            "tabular_parts",
            "parameters",
            "commands",
        )
        result: list[tuple] = []
        for raw in rows:
            row = raw if isinstance(raw, dict) else {}
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            schema_payload = {
                key: payload.get(key)
                for key in schema_keys
                if key in payload
            }
            result.append(
                (
                    str(row.get("guid") or ""),
                    str(row.get("type") or ""),
                    str(row.get("name") or ""),
                    str(row.get("title") or ""),
                    str(row.get("parent_guid") or ""),
                    str(payload.get("metadata_ref") or ""),
                    *(str(payload.get(f"{key}_ref") or "") for key in schema_keys),
                    json.dumps(
                        schema_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ),
                )
            )
        return tuple(sorted(result))

    def get_or_build(
        self,
        db_uid: str,
        db_path: str,
        *,
        sources: list[dict],
        manifest_rows: list[dict],
        owner_payload_loader: Callable[[str], dict] | None = None,
    ) -> WorkspaceSemanticIndex:
        cache_key = str(db_uid or "")
        mtime_ns, size = ModuleResolutionMemoryCache._stat(db_path)
        signature = (
            ModuleSourceMemoryCache._revision_signature(sources),
            self._manifest_revision_signature(manifest_rows),
        )
        with self._lock:
            entry = self._entries.get(cache_key)
            if isinstance(entry, dict) and entry.get("signature") == signature:
                entry["mtime_ns"] = mtime_ns
                entry["size"] = size
                cached = entry.get("index")
                if isinstance(cached, WorkspaceSemanticIndex):
                    return cached
            build_event = self._build_events.get(cache_key)
            is_builder = build_event is None
            if build_event is None:
                build_event = threading.Event()
                self._build_events[cache_key] = build_event

        if not is_builder:
            build_event.wait(timeout=300.0)
            with self._lock:
                entry = self._entries.get(cache_key)
                if isinstance(entry, dict) and entry.get("signature") == signature:
                    cached = entry.get("index")
                    if isinstance(cached, WorkspaceSemanticIndex):
                        return cached
            return self.get_or_build(
                db_uid,
                db_path,
                sources=sources,
                manifest_rows=manifest_rows,
                owner_payload_loader=owner_payload_loader,
            )

        try:
            owners = {
                str(row.get("guid") or "").strip(): row
                for row in manifest_rows
                if isinstance(row, dict) and str(row.get("guid") or "").strip()
            }
            index = build_workspace_semantic_index(
                sources,
                owners_by_guid=owners,
            )
            if owner_payload_loader is not None:
                candidate_owner_guids = {
                    diagnostic.owner_guid
                    for diagnostic in index.diagnostics
                    if diagnostic.code in {"unresolved_member", "unresolved_module"}
                    and diagnostic.owner_guid
                }
                owner_payloads: dict[str, dict] = {}
                for owner_guid in candidate_owner_guids:
                    owner = owners.get(owner_guid)
                    if not isinstance(owner, dict):
                        continue
                    if str(owner.get("type") or "").strip().lower() not in {
                        "form",
                        "common_form",
                    }:
                        continue
                    try:
                        loaded = owner_payload_loader(owner_guid)
                    except Exception:
                        continue
                    if isinstance(loaded, dict):
                        owner_payloads[owner_guid] = loaded
                if owner_payloads:
                    index = filter_form_shadow_diagnostics(
                        index,
                        owner_payloads,
                    )
            with self._lock:
                entry = self._entries.get(cache_key)
                if isinstance(entry, dict) and entry.get("signature") == signature:
                    cached = entry.get("index")
                    if isinstance(cached, WorkspaceSemanticIndex):
                        return cached
                generation = int(self._generations.get(cache_key, 0)) + 1
                self._generations[cache_key] = generation
                index.generation = generation
                self._entries[cache_key] = {
                    "mtime_ns": mtime_ns,
                    "size": size,
                    "signature": signature,
                    "index": index,
                }
                return index
        finally:
            with self._lock:
                event = self._build_events.pop(cache_key, None)
                if event is not None:
                    event.set()

    def get_if_current(
        self,
        db_uid: str,
        db_path: str,
    ) -> WorkspaceSemanticIndex | None:
        with self._lock:
            entry = self._entries.get(str(db_uid or ""))
            if not isinstance(entry, dict):
                return None
            cached = entry.get("index")
            return cached if isinstance(cached, WorkspaceSemanticIndex) else None

    def invalidate(self, db_uid: str) -> None:
        with self._lock:
            self._entries.pop(str(db_uid or ""), None)


STATE_WORKSPACE_SEMANTIC_INDEX = WorkspaceSemanticIndexMemoryCache()
_WORKSPACE_WARMUP_LOCK = threading.RLock()
_WORKSPACE_WARMUP_PENDING: set[str] = set()


def _semantic_owner_payload_loader(db, manifest_rows: list[dict]):
    from src.configurator.persistence.manifest_io import _hydrate_manifest_payload
    from src.configurator.manifest_schema import MANIFEST_TABLE

    rows_by_guid = {
        str(row.get("guid") or "").strip(): row
        for row in manifest_rows
        if isinstance(row, dict) and str(row.get("guid") or "").strip()
    }

    def _load(owner_guid: str) -> dict:
        guid = str(owner_guid or "").strip()
        row = rows_by_guid.get(guid)
        if not isinstance(row, dict):
            return {}
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if "form_model" not in payload and not payload.get("form_model_ref"):
            raw_rows = db.table(MANIFEST_TABLE).select(where={"guid": guid}) or []
            raw_row = raw_rows[0] if raw_rows and isinstance(raw_rows[0], dict) else {}
            raw_payload = (
                raw_row.get("payload")
                if isinstance(raw_row.get("payload"), dict)
                else {}
            )
            if raw_payload:
                payload = raw_payload
        return _hydrate_manifest_payload(db, payload)

    return _load


def schedule_workspace_semantic_index_warmup(
    db_uid: str,
    *,
    delay: float = 0.5,
) -> bool:
    """Warm the persisted workspace index without blocking db.open."""

    uid = str(db_uid or "").strip()
    if not uid:
        return False
    with _WORKSPACE_WARMUP_LOCK:
        if uid in _WORKSPACE_WARMUP_PENDING:
            return False
        _WORKSPACE_WARMUP_PENDING.add(uid)

    def _run() -> None:
        started = time.perf_counter()
        try:
            if delay > 0:
                time.sleep(float(delay))
            db_path = str(STATE_DBS.get_path(uid) or "").strip()
            db = STATE_DBS.get(uid)
            if not db_path:
                return
            manifest_rows = None
            manifest_cache_ready = False
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                manifest_rows = STATE_MANIFEST_LIST_CACHE.get_if_current(uid, db_path)
                if manifest_rows is not None:
                    manifest_cache_ready = True
                    break
                time.sleep(0.5)
            if manifest_rows is None:
                from src.configurator.persistence.manifest_io import list_object_rows

                manifest_rows = list_object_rows(db)
            elif manifest_cache_ready:
                # Let Configurator finish tree construction before bulk source
                # hydration starts competing for the same runtime and CPU.
                time.sleep(10.0)
            sources = STATE_MODULE_SOURCE_CACHE.get_or_build(uid, db_path, db)
            index = STATE_WORKSPACE_SEMANTIC_INDEX.get_or_build(
                uid,
                db_path,
                sources=sources,
                manifest_rows=manifest_rows,
                owner_payload_loader=_semantic_owner_payload_loader(
                    db,
                    manifest_rows,
                ),
            )
            print(
                "[runtime.semantic_index.warmup] "
                f"db_uid={uid} generation={index.generation} "
                f"modules={len(index.modules)} took={time.perf_counter() - started:.3f}s",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[runtime.semantic_index.warmup] db_uid={uid} error={type(exc).__name__}: {exc}",
                flush=True,
            )
        finally:
            with _WORKSPACE_WARMUP_LOCK:
                _WORKSPACE_WARMUP_PENDING.discard(uid)

    threading.Thread(
        target=_run,
        name=f"semantic-index-{uid[:8]}",
        daemon=True,
    ).start()
    return True


def workspace_semantic_index_warmup_pending(db_uid: str) -> bool:
    with _WORKSPACE_WARMUP_LOCK:
        return str(db_uid or "").strip() in _WORKSPACE_WARMUP_PENDING


def _active_db_key(payload: dict) -> tuple[str, str] | None:
    sid = str(payload.get("session_id") or "").strip()
    db_uid = str(STATE_SESSIONS.get_active_db_uid(sid) or "").strip()
    if not db_uid:
        return None
    db_path = str(STATE_DBS.get_path(db_uid) or "").strip()
    return (db_uid, db_path) if db_path else None


def _cached_manifest_rows(payload: dict) -> list[dict] | None:
    active = _active_db_key(payload)
    if active is None:
        return None
    db_uid, db_path = active
    return STATE_MANIFEST_LIST_CACHE.get_if_current(db_uid, db_path)


def _resolve_common_module_cached(db, payload: dict, name: str) -> dict | None:
    active = _active_db_key(payload)
    cache_hit = False
    module = None
    if active is not None:
        cache_hit, module = STATE_MODULE_RESOLUTION_CACHE.get(*active, name)
    if not cache_hit:
        cached_rows = _cached_manifest_rows(payload)
        if cached_rows is None:
            module = resolve_common_module(db, name=name)
        else:
            module = resolve_common_module(
                db,
                name=name,
                manifest_rows=cached_rows,
            )
        if active is not None:
            STATE_MODULE_RESOLUTION_CACHE.put(*active, name, module)
    return module


def _workspace_semantic_index(db, payload: dict) -> WorkspaceSemanticIndex:
    active = _active_db_key(payload)
    if active is None:
        raise ValueError("Active database is not available")
    sources = STATE_MODULE_SOURCE_CACHE.get_or_build(active[0], active[1], db)
    manifest_rows = _cached_manifest_rows(payload)
    if manifest_rows is None:
        from src.configurator.persistence.manifest_io import list_object_rows

        manifest_rows = list_object_rows(db)
    return STATE_WORKSPACE_SEMANTIC_INDEX.get_or_build(
        active[0],
        active[1],
        sources=sources,
        manifest_rows=manifest_rows,
        owner_payload_loader=_semantic_owner_payload_loader(
            db,
            manifest_rows,
        ),
    )


def _common_module_completion(db, payload: dict, name: str) -> dict:
    active = _active_db_key(payload)
    if active is not None:
        cache_hit, cached = STATE_MODULE_COMPLETION_CACHE.get(*active, name)
        if cache_hit and isinstance(cached, dict):
            return cached
    if active is not None:
        index = STATE_WORKSPACE_SEMANTIC_INDEX.get_if_current(*active)
    else:
        index = None
    if index is not None:
        module_identity = index.module_for_qualifier(name)
        if module_identity is None:
            result = {"found": False, "name": name, "members": []}
        else:
            result = {
                "found": True,
                "name": name,
                "module_guid": module_identity.module_guid,
                "owner_guid": module_identity.owner_guid,
                "owner_name": module_identity.owner_name,
                "owner_title": module_identity.owner_title,
                "members": index.exported_members(name),
            }
        if active is not None:
            STATE_MODULE_COMPLETION_CACHE.put(*active, name, result)
        return result

    module = _resolve_common_module_cached(db, payload, name)
    if not isinstance(module, dict):
        result = {"found": False, "name": name, "members": []}
    else:
        from src.dsl.module_introspection import introspect_module_source

        info = introspect_module_source(
            str(module.get("text") or ""),
            language="mixed",
        )
        members = []
        seen: set[str] = set()
        for symbol in info.symbols:
            folded = str(symbol.name or "").casefold()
            if (
                not folded
                or folded in seen
                or not bool(symbol.exported)
                or str(symbol.kind or "") not in {"procedure", "function"}
            ):
                continue
            seen.add(folded)
            members.append(
                {
                    "name": str(symbol.name or ""),
                    "kind": str(symbol.kind or ""),
                    "params": list(symbol.params),
                    "line": int(symbol.line or 0),
                }
            )
        members.sort(key=lambda item: str(item.get("name") or "").casefold())
        result = {
            "found": True,
            "name": name,
            "module_guid": str(module.get("module_guid") or ""),
            "owner_guid": str(module.get("owner_guid") or ""),
            "owner_name": str(module.get("owner_name") or ""),
            "owner_title": str(module.get("owner_title") or ""),
            "members": members,
        }
    if active is not None:
        STATE_MODULE_COMPLETION_CACHE.put(*active, name, result)
    return result


def _workspace_rename_plan(db, payload: dict):
    active = _active_db_key(payload)
    if active is None:
        raise ValueError("Active database is not available")
    module_guid = str(payload.get("module_guid") or "").strip()
    if not module_guid:
        raise ValueError("module_guid is required")
    sources = STATE_MODULE_SOURCE_CACHE.get_or_build(active[0], active[1], db)
    target = next(
        (
            row
            for row in sources
            if str(row.get("module_guid") or "").strip() == module_guid
        ),
        None,
    )
    if not isinstance(target, dict):
        raise ValueError(f"Module was not found: {module_guid}")
    source = str(target.get("source_text") or "")
    position_value = payload.get("cursor_position")
    if position_value is None:
        symbol_name = str(payload.get("symbol_name") or "").strip()
        position = source.find(symbol_name) if symbol_name else -1
        if position < 0:
            raise ValueError("cursor_position or an existing symbol_name is required")
    else:
        position = int(position_value)

    manifest_rows = _cached_manifest_rows(payload)
    if manifest_rows is None:
        from src.configurator.persistence.manifest_io import list_object_rows

        manifest_rows = list_object_rows(db)
    owners_by_guid = {
        str(row.get("guid") or "").strip(): row
        for row in manifest_rows
        if isinstance(row, dict) and str(row.get("guid") or "").strip()
    }
    planner_sources = []
    for source_row in sources:
        item = dict(source_row)
        source_owner = owners_by_guid.get(
            str(item.get("owner_guid") or "").strip(),
            {},
        )
        item["owner_name"] = str(source_owner.get("name") or "")
        item["owner_title"] = str(source_owner.get("title") or "")
        planner_sources.append(item)

    owner_guid = str(target.get("owner_guid") or "").strip()
    owner = owners_by_guid.get(owner_guid, {})
    owner_payload = (
        owner.get("payload")
        if isinstance(owner, dict) and isinstance(owner.get("payload"), dict)
        else {}
    )
    metadata_ref = str(owner_payload.get("metadata_ref") or "").strip()
    qualifiers = [
        str(payload.get("module_name") or "").strip(),
        str(owner.get("name") or "").strip() if isinstance(owner, dict) else "",
        str(owner.get("title") or "").strip() if isinstance(owner, dict) else "",
        metadata_ref.rsplit(".", 1)[-1],
    ]
    from src.dsl.semantic_rename import plan_workspace_export_rename, symbol_name_at

    selected_name = symbol_name_at(source, position, language="mixed")
    if not selected_name:
        raise ValueError("Selected workspace rename symbol was not resolved")
    qualified_needles = tuple(
        f"{qualifier}.{selected_name}".casefold()
        for qualifier in qualifiers
        if str(qualifier or "").strip()
    )
    semantic_index = STATE_WORKSPACE_SEMANTIC_INDEX.get_if_current(*active)
    candidate_module_guids: set[str] = {module_guid}
    target_symbol_id = ""
    if semantic_index is not None:
        for qualifier in qualifiers:
            resolved = semantic_index.resolve(qualifier, selected_name)
            if resolved is not None:
                target_symbol_id = resolved[1].symbol_id
                break
        if target_symbol_id:
            candidate_module_guids.update(
                reference.module_guid
                for reference in semantic_index.references
                if reference.target_symbol_id == target_symbol_id
            )
    if target_symbol_id:
        planner_sources = [
            item
            for item in planner_sources
            if str(item.get("module_guid") or "").strip() in candidate_module_guids
        ]
    else:
        planner_sources = [
            item
            for item in planner_sources
            if str(item.get("module_guid") or "").strip() == module_guid
            or any(
                needle
                in str(
                    item.get("_source_text_casefold")
                    or str(item.get("source_text") or "").casefold()
                )
                for needle in qualified_needles
            )
        ]
    return active, plan_workspace_export_rename(
        planner_sources,
        declaration_module_guid=module_guid,
        cursor_position=position,
        new_name=str(payload.get("new_name") or ""),
        qualifier_names=qualifiers,
        language="mixed",
    )


def _workspace_rename_payload(plan, *, applied: bool = False) -> dict:
    return {
        "declaration_module_guid": plan.declaration_module_guid,
        "old_name": plan.old_name,
        "new_name": plan.new_name,
        "symbol_kind": plan.symbol_kind,
        "qualifier_names": list(plan.qualifier_names),
        "module_count": len(plan.modules),
        "occurrence_count": plan.occurrence_count,
        "applied": bool(applied),
        "modules": [
            {
                "module_guid": item.module_guid,
                "module_name": item.module_name,
                "source_hash": item.source_hash,
                "updated_hash": item.updated_hash,
                "occurrences": [
                    {
                        "start": occurrence.start,
                        "end": occurrence.end,
                        "line": occurrence.line,
                        "col": occurrence.col,
                        "preview": occurrence.preview,
                        "declaration": occurrence.declaration,
                    }
                    for occurrence in item.occurrences
                ],
            }
            for item in plan.modules
        ],
    }


def handle_modules_action(handler, action: str, payload: dict) -> RpcResponse | None:
    if action not in {
        "modules.get_text",
        "modules.list_by_owner",
        "modules.resolve",
        "modules.completion_members",
        "modules.semantic_index_info",
        "modules.semantic_definition",
        "modules.semantic_references",
        "modules.semantic_diagnostics",
        "modules.search_text",
        "modules.rename_symbol_plan",
        "modules.rename_symbol_apply",
        "modules.update_text",
        "modules.normalize_language",
    }:
        return None

    db = handler._require_db(payload)
    if isinstance(db, RpcResponse):
        return db

    try:
        if action == "modules.get_text":
            module_guid = str(payload.get("module_guid") or "").strip()
            if not module_guid:
                return RpcResponse("error", error="module_guid is required")
            return RpcResponse(
                "ok",
                {"module_guid": module_guid, "text": get_module_text(db, module_guid=module_guid)},
            )

        if action == "modules.list_by_owner":
            owner_guid = str(payload.get("owner_guid") or "").strip()
            if not owner_guid:
                return RpcResponse("ok", {"modules": []})
            rows = list_modules_by_owner(db, owner_guid=owner_guid)
            return RpcResponse("ok", {"modules": list(rows or [])})

        if action == "modules.resolve":
            name = str(payload.get("name") or "").strip()
            if not name:
                return RpcResponse("error", error="name is required")
            module = _resolve_common_module_cached(db, payload, name)
            return RpcResponse("ok", {"found": module is not None, "module": module or {}})

        if action == "modules.completion_members":
            name = str(payload.get("name") or "").strip()
            if not name:
                return RpcResponse("error", error="name is required")
            return RpcResponse("ok", _common_module_completion(db, payload, name))

        if action == "modules.semantic_index_info":
            active = _active_db_key(payload)
            if active is None:
                return RpcResponse("error", error="Active database is not available")
            index = STATE_WORKSPACE_SEMANTIC_INDEX.get_if_current(*active)
            if index is None and bool(payload.get("wait", False)):
                index = _workspace_semantic_index(db, payload)
            if index is None:
                schedule_workspace_semantic_index_warmup(active[0], delay=0.0)
                return RpcResponse(
                    "ok",
                    {
                        "ready": False,
                        "building": workspace_semantic_index_warmup_pending(active[0]),
                        "generation": 0,
                        "modules": 0,
                        "symbols": 0,
                        "exported_symbols": 0,
                        "references": 0,
                        "ambiguous_aliases": 0,
                        "diagnostics": 0,
                        "unresolved_references": 0,
                        "source_gaps": 0,
                        "ambiguous_references": 0,
                        "form_shadow_diagnostics_filtered": 0,
                        "partial_modules": 0,
                    },
                )
            return RpcResponse(
                "ok",
                {
                    "ready": True,
                    "building": False,
                    "generation": int(index.generation),
                    **index.stats(),
                },
            )

        if action == "modules.semantic_definition":
            qualifier = str(payload.get("qualifier") or "").strip()
            name = str(payload.get("name") or "").strip()
            if not qualifier or not name:
                return RpcResponse("error", error="qualifier and name are required")
            completion = _common_module_completion(db, payload, qualifier)
            target = next(
                (
                    dict(item)
                    for item in list(completion.get("members") or [])
                    if isinstance(item, dict)
                    and str(item.get("name") or "").casefold() == name.casefold()
                ),
                None,
            )
            if target is None:
                return RpcResponse("ok", {"found": False, "target": {}})
            target.update(
                {
                    "symbol_id": workspace_symbol_id(
                        str(completion.get("module_guid") or ""),
                        str(target.get("kind") or ""),
                        str(target.get("name") or ""),
                    ),
                    "module_guid": str(completion.get("module_guid") or ""),
                    "owner_guid": str(completion.get("owner_guid") or ""),
                    "owner_name": str(completion.get("owner_name") or ""),
                    "owner_title": str(completion.get("owner_title") or ""),
                    "owner_type": "common_module",
                }
            )
            active = _active_db_key(payload)
            index = (
                STATE_WORKSPACE_SEMANTIC_INDEX.get_if_current(*active)
                if active is not None
                else None
            )
            return RpcResponse(
                "ok",
                {
                    "found": True,
                    "generation": int(index.generation) if index is not None else 0,
                    "target": target,
                },
            )

        if action == "modules.semantic_references":
            qualifier = str(payload.get("qualifier") or "").strip()
            name = str(payload.get("name") or "").strip()
            if not qualifier or not name:
                return RpcResponse("error", error="qualifier and name are required")
            index = _workspace_semantic_index(db, payload)
            hits = index.find_references(
                qualifier,
                name,
                limit=int(payload.get("limit") or 500),
                include_declaration=bool(payload.get("include_declaration", True)),
            )
            return RpcResponse(
                "ok",
                {"generation": int(index.generation), "hits": hits},
            )

        if action == "modules.semantic_diagnostics":
            index = _workspace_semantic_index(db, payload)
            diagnostics = index.list_diagnostics(
                module_guid=str(payload.get("module_guid") or "").strip(),
                code=str(payload.get("code") or "").strip(),
                limit=int(payload.get("limit") or 500),
            )
            return RpcResponse(
                "ok",
                {
                    "generation": int(index.generation),
                    "diagnostics": diagnostics,
                },
            )

        if action == "modules.search_text":
            term = str(payload.get("term") or "").strip()
            if not term:
                return RpcResponse("ok", {"hits": []})
            active = _active_db_key(payload)
            if active is None:
                return RpcResponse("error", error="Active database is not available")
            sources = STATE_MODULE_SOURCE_CACHE.get_or_build(active[0], active[1], db)
            hits = search_module_sources(
                sources,
                term=term,
                match_case=bool(payload.get("match_case", False)),
                whole_word=bool(payload.get("whole_word", False)),
                module_guid=str(payload.get("module_guid") or "").strip(),
                limit=int(payload.get("limit") or 500),
            )
            return RpcResponse("ok", {"hits": hits})

        if action in {"modules.rename_symbol_plan", "modules.rename_symbol_apply"}:
            active, plan = _workspace_rename_plan(db, payload)
            if action == "modules.rename_symbol_plan":
                return RpcResponse("ok", _workspace_rename_payload(plan))

            expected_rows = payload.get("modules")
            if not isinstance(expected_rows, list) or not expected_rows:
                return RpcResponse("error", error="Workspace rename preview is required")
            expected = {
                str(item.get("module_guid") or "").strip(): (
                    str(item.get("source_hash") or "").strip(),
                    str(item.get("updated_hash") or "").strip(),
                )
                for item in expected_rows
                if isinstance(item, dict)
                and str(item.get("module_guid") or "").strip()
            }
            actual = {
                item.module_guid: (item.source_hash, item.updated_hash)
                for item in plan.modules
            }
            if expected != actual:
                return RpcResponse(
                    "error",
                    error="Workspace rename preview is stale; build a new preview",
                )
            result = apply_module_text_updates_atomic(
                db,
                [
                    {
                        "module_guid": item.module_guid,
                        "source_hash": item.source_hash,
                        "updated_hash": item.updated_hash,
                        "text": item.updated_source,
                    }
                    for item in plan.modules
                ],
                updated_by=str(payload.get("updated_by") or "workspace_rename"),
            )
            STATE_MODULE_RESOLUTION_CACHE.invalidate(active[0])
            STATE_MODULE_COMPLETION_CACHE.invalidate(active[0])
            STATE_MODULE_SOURCE_CACHE.invalidate(active[0])
            STATE_WORKSPACE_SEMANTIC_INDEX.invalidate(active[0])
            response = _workspace_rename_payload(plan, applied=True)
            response.update(result)
            return RpcResponse("ok", response)

        if action == "modules.update_text":
            module_guid = str(payload.get("module_guid") or "").strip()
            if not module_guid:
                return RpcResponse("error", error="module_guid is required")
            update_module_text(
                db,
                module_guid=module_guid,
                text=str(payload.get("text") or ""),
                updated_by=str(payload.get("updated_by") or "user"),
            )
            active = _active_db_key(payload)
            if active is not None:
                STATE_MODULE_RESOLUTION_CACHE.invalidate(active[0])
                STATE_MODULE_COMPLETION_CACHE.invalidate(active[0])
                STATE_MODULE_SOURCE_CACHE.invalidate(active[0])
                STATE_WORKSPACE_SEMANTIC_INDEX.invalidate(active[0])
            return RpcResponse("ok", {"module_guid": module_guid, "updated": True})

        language = str(payload.get("language") or "").strip().lower()
        if language not in {"uk", "en"}:
            return RpcResponse("error", error="language must be 'uk' or 'en'")
        stats = normalize_modules_language(db, language=language, updated_by="normalize")
        active = _active_db_key(payload)
        if active is not None:
            STATE_MODULE_RESOLUTION_CACHE.invalidate(active[0])
            STATE_MODULE_COMPLETION_CACHE.invalidate(active[0])
            STATE_MODULE_SOURCE_CACHE.invalidate(active[0])
            STATE_WORKSPACE_SEMANTIC_INDEX.invalidate(active[0])
        return RpcResponse("ok", dict(stats or {}))
    except Exception as e:
        return RpcResponse("error", error=f"{action}: {e}")
