from __future__ import annotations

import hashlib
import json
import os
import re
import time
from contextlib import nullcontext as _nullcontext
from pathlib import Path
from typing import Any, Callable, Iterable

from src.mpdb.mpdb import ASSETS_TABLE, META_ASSETS, Mpdb
from src.mpdb.table_storage import reset_table_storage

from .backend import Parse1CDBackend, load_backend


ONECD_DATA_MIGRATION_ASSET_KEY = "onec_data_migration/manifest.json"
ONECD_PACKED_DATA_TABLE = "data_rows"
ONECD_PACKED_ROW_ASSET_PREFIX = "onec_data_rows/"
ONECD_PACKED_INLINE_LIMIT = 1024


def _load_parse1cd_backend() -> Parse1CDBackend:
    return load_backend()


_IDENT_RE = re.compile(r"[^a-z0-9]+")
_TABLE_ORDER_RE = re.compile(
    r"^_(DOCUMENTJOURNAL|SCHEDULEDJOBS|ACCUMRG|INFORG|REFERENCE|DOCUMENT|CONST|ENUM|ACCRG|CRG|BPR|TASK|CHRC|ACC|NODE|SEQ)"
    r"(?:OPT|T|TN|SL|SINF|CHNGR|DLK|BFK|AGGDIMS|AGGDICT\d+H|AGG|TOTALS)?"
    r"(\d+)",
    re.IGNORECASE,
)
_TABLE_PREFIX_KIND = (
    ("_DOCUMENTJOURNAL", "journal"),
    ("_SCHEDULEDJOBS", "scheduled_job"),
    ("_ACCUMRG", "accumulation_register"),
    ("_INFORG", "information_register"),
    ("_REFERENCE", "catalog"),
    ("_DOCUMENT", "document"),
    ("_CONST", "constant"),
    ("_ENUM", "enum"),
    ("_ACCRG", "accounting_register"),
    ("_CRG", "calculation_register"),
    ("_BPR", "business_process"),
    ("_TASK", "task"),
    ("_CHRC", "chart_of_characteristic_types"),
    ("_NODE", "exchange_plan"),
    ("_SEQ", "sequence"),
    ("_ACC", "chart_of_accounts"),
    ("_SYSTEM", "system"),
    ("_CONFIG", "system"),
    ("_REFSINF", "system"),
    ("_COMMONSETTINGS", "system"),
    ("_FRMDTSETTINGS", "system"),
    ("_USERSWORKHISTORY", "system"),
    ("V8USERS", "system"),
)
_WEAK_TABLE_KINDS = {"", "unknown", "other", "service"}


def _identifier_base(value: str, *, fallback: str) -> str:
    raw = str(value or "").strip()
    ascii_value = raw.encode("ascii", errors="ignore").decode("ascii").lower()
    base = _IDENT_RE.sub("_", ascii_value).strip("_")
    if not base:
        digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:8]
        base = f"{fallback}_{digest}"
    if base[0].isdigit():
        base = f"{fallback}_{base}"
    return base


def _clip_identifier(value: str, *, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    digest = hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"{value[: max_length - 9].rstrip('_')}_{digest}"


def sanitize_table_name(table_name: str, *, prefix: str = "onec", max_length: int = 96) -> str:
    prefix_base = _identifier_base(prefix, fallback="onec")
    table_base = _identifier_base(table_name, fallback="table")
    return _clip_identifier(f"{prefix_base}__{table_base}", max_length=max_length)


def _fallback_table_kind(table_name: str) -> str:
    upper = str(table_name or "").upper()
    for prefix, kind in _TABLE_PREFIX_KIND:
        if upper.startswith(prefix):
            return kind
    return "unknown"


def _physical_table_order(table_name: str) -> int:
    match = _TABLE_ORDER_RE.search(str(table_name or "").upper())
    if not match:
        return 0
    try:
        return int(match.group(2))
    except Exception:
        return 0


def _physical_table_role(table_name: str, kind: str) -> str:
    upper = str(table_name or "").upper()
    if "_VT" in upper:
        return "tabular_part"
    if upper.startswith("_BPRPOINTS"):
        return "route_points"
    if upper.startswith("_ACCUMRGT"):
        return "totals"
    if "OPT" in upper:
        return "options"
    if any(token in upper for token in ("SINF", "CHNGR", "DLK", "BFK", "AGG", "DICT", "TOTALS")):
        return "auxiliary"
    if upper.startswith("_INFORGSL"):
        return "slice"
    if kind == "constant":
        return "constant_value"
    if kind == "journal":
        return "journal"
    if kind == "scheduled_job":
        return "scheduled_job"
    if kind in {"accumulation_register", "information_register", "accounting_register", "calculation_register"}:
        return "register_data"
    if kind in {"catalog", "document", "business_process", "task", "exchange_plan", "chart_of_accounts", "chart_of_characteristic_types"}:
        return "object"
    return "data"


def _load_metadata_by_kind_order(source: Path) -> dict[tuple[str, int], list[dict[str, Any]]]:
    try:
        from .onecd_source import OneCDConfigSource

        objects = OneCDConfigSource(source).metadata_objects()
    except Exception:
        return {}

    out: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for obj in objects:
        try:
            order = int(getattr(obj, "dbname_order", 0) or 0)
        except Exception:
            order = 0
        family = str(getattr(obj, "family", "") or "").strip()
        if not family or order <= 0:
            continue
        item = {
            "family": family,
            "name": str(getattr(obj, "name", "") or ""),
            "title": str(getattr(obj, "title", "") or ""),
            "uuid": str(getattr(obj, "uuid", "") or ""),
            "dbname_kind": str(getattr(obj, "dbname_kind", "") or ""),
            "order": order,
            "semantic_order": int(getattr(obj, "order", 0) or 0),
            "origin": str(getattr(obj, "origin", "") or ""),
        }
        out.setdefault((family, order), []).append(item)
    return out


def _describe_physical_table(
    table_name: str,
    schema_reader_cls: Any,
    metadata_by_kind_order: dict[tuple[str, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    try:
        guessed = str(schema_reader_cls.guess_table_kind(table_name) or "").strip()
    except Exception:
        guessed = ""
    fallback = _fallback_table_kind(table_name)
    order = _physical_table_order(table_name)
    kind = fallback if guessed.lower() in _WEAK_TABLE_KINDS or fallback == "journal" else guessed
    if kind.lower() in _WEAK_TABLE_KINDS:
        kind = "unknown"

    candidates = metadata_by_kind_order.get((kind, order), []) if order > 0 else []
    meta = candidates[0] if candidates else {}
    if meta:
        kind = str(meta.get("family") or kind or "unknown")

    return {
        "kind": kind,
        "table_role": _physical_table_role(table_name, kind),
        "metadata_order": order,
        "metadata_name": str(meta.get("name") or ""),
        "metadata_title": str(meta.get("title") or ""),
        "metadata_uuid": str(meta.get("uuid") or ""),
        "dbname_kind": str(meta.get("dbname_kind") or ""),
        "metadata_origin": str(meta.get("origin") or ""),
        "kind_source": "dbnames" if meta else ("prefix" if fallback != "unknown" and guessed.lower() in _WEAK_TABLE_KINDS else "schema_reader"),
    }


def sanitize_column_name(column_name: str, used: set[str] | None = None) -> str:
    used = used if used is not None else set()
    reserved = {"rowid", "__deleted__", "__source_table", "__source_row_index"}
    base = _identifier_base(column_name, fallback="field")
    if base in reserved or base.startswith("__"):
        base = f"f_{base.strip('_') or 'field'}"
    candidate = _clip_identifier(base, max_length=96)
    index = 2
    while candidate in used:
        suffix = f"_{index}"
        candidate = _clip_identifier(f"{base}{suffix}", max_length=96)
        index += 1
    used.add(candidate)
    return candidate


def _field_raw_type(field: Any) -> str:
    value = getattr(field, "type", "")
    return str(getattr(value, "value", value) or "").strip().upper()


def _field_schema(field: Any, *, rich_refs: bool) -> dict[str, Any]:
    raw_type = _field_raw_type(field)
    name = str(getattr(field, "name", "") or "")
    upper_name = name.upper()
    length = int(getattr(field, "length", 0) or 0)
    precision = int(getattr(field, "precision", 0) or 0)

    if upper_name.endswith("RREF") and raw_type == "B" and length == 16:
        return {"type": "json" if rich_refs else "uuid", "source_type": raw_type, "source_length": length}
    if upper_name.endswith(("TREF", "TRREF", "TYPE")):
        return {"type": "str", "source_type": raw_type, "source_length": length}
    if raw_type == "L":
        return {"type": "bool", "source_type": raw_type}
    if raw_type == "N":
        return {
            "type": "decimal" if precision else "int",
            "source_type": raw_type,
            "source_length": length,
            "source_precision": precision,
        }
    if raw_type == "DT":
        return {"type": "datetime", "source_type": raw_type}
    if raw_type in {"NC", "NVC", "NT", "RV", "B"}:
        return {"type": "str", "source_type": raw_type, "source_length": length}
    if raw_type == "I":
        return {"type": "json", "source_type": raw_type}
    return {"type": "json", "source_type": raw_type or "unknown"}


def _build_table_schema(table: Any, *, field_map: dict[str, str], rich_refs: bool) -> dict[str, Any]:
    fields: dict[str, dict[str, Any]] = {
        "__source_table": {"type": "str"},
        "__source_row_index": {"type": "int"},
        "__deleted__": {"type": "bool"},
    }
    for field in list(getattr(table, "fields", []) or []):
        source_name = str(getattr(field, "name", "") or "")
        target_name = field_map.get(source_name)
        if not target_name:
            continue
        field_schema = _field_schema(field, rich_refs=rich_refs)
        field_schema["source_name"] = source_name
        fields[target_name] = field_schema
    return {
        "fields": fields,
        "source": {
            "system": "1c",
            "physical_table": str(getattr(table, "name", "") or ""),
        },
    }


def _build_packed_rows_schema() -> dict[str, Any]:
    return {
        "fields": {
            "__source_table": {"type": "str"},
            "__source_row_index": {"type": "int"},
            "__deleted__": {"type": "bool"},
            "data": {"type": "json"},
            "data_asset": {"type": "str"},
            "data_offset": {"type": "int"},
            "data_size": {"type": "int"},
            "data_inline": {"type": "bool"},
        },
        "source": {
            "system": "1c",
            "storage": "packed_rows",
        },
    }


def _packed_batch_asset_key(source_table: str, first_row_index: int, last_row_index: int) -> str:
    raw_table = str(source_table or "").strip()
    base = _clip_identifier(_identifier_base(raw_table, fallback="table"), max_length=64)
    digest = hashlib.sha1(raw_table.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return (
        f"{ONECD_PACKED_ROW_ASSET_PREFIX}{base}-{digest}/"
        f"rows-{int(first_row_index):012d}-{int(last_row_index):012d}.jsonl"
    )


def _pack_data_row(
    row: dict[str, Any],
    *,
    inline_data_limit: int = ONECD_PACKED_INLINE_LIMIT,
) -> tuple[dict[str, Any], bytes | None]:
    source_table = str(row.get("__source_table") or "")
    source_row_index = int(row.get("__source_row_index") or 0)
    data_payload = {
        key: value
        for key, value in row.items()
        if key not in {"__source_table", "__source_row_index", "__deleted__"}
    }
    data_bytes = json.dumps(data_payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    data_asset = ""
    data_offset = 0
    stored_data: dict[str, Any] = data_payload
    offloaded_data: bytes | None = None

    if len(data_bytes) > max(0, int(inline_data_limit or 0)):
        stored_data = {}
        offloaded_data = data_bytes

    return {
        "__source_table": source_table,
        "__source_row_index": source_row_index,
        "__deleted__": bool(row.get("__deleted__", False)),
        "data": stored_data,
        "data_asset": data_asset,
        "data_offset": data_offset,
        "data_size": len(data_bytes),
        "data_inline": offloaded_data is None,
    }, offloaded_data


def _table_exists(db: Mpdb, table_name: str) -> bool:
    try:
        return table_name in dict(getattr(db, "_meta", {}).get("tables", {}) or {})
    except Exception:
        return False


def _drop_empty_target_table(db: Mpdb, table_name: str) -> bool:
    """Drop a just-created target table if it has no rows/data pages.

    The 1CD data importer is best-effort per physical table. Some source tables
    can fail on decoding or oversized rows after the mpdb table has been created.
    Keeping thousands of empty failed tables in META can overflow the meta page.
    """
    name = str(table_name or "").strip()
    if not name:
        return False
    schema_ref = ""
    with getattr(db, "_lock", None) or _nullcontext():
        tables = getattr(db, "_meta", {}).get("tables", {})
        if not isinstance(tables, dict):
            return False
        tinfo = tables.get(name)
        if not isinstance(tinfo, dict):
            return False
        if int(tinfo.get("next_rowid") or 1) > 1:
            return False
        if list(tinfo.get("data_pages") or []):
            return False
        schema_ref = str(tinfo.get("schema_ref") or "").strip()

    with db.transaction() as tx:
        tables = db._meta.get("tables", {})
        tinfo = tables.get(name) if isinstance(tables, dict) else None
        if not isinstance(tinfo, dict):
            return False
        if int(tinfo.get("next_rowid") or 1) > 1 or list(tinfo.get("data_pages") or []):
            return False
        schema_ref = str(tinfo.get("schema_ref") or schema_ref or "").strip()
        tables.pop(name, None)
        indexes = db._meta.get("indexes", {})
        if isinstance(indexes, dict):
            indexes.pop(name, None)
        cache = getattr(db, "_table_schema_cache", None)
        if isinstance(cache, dict):
            cache.pop(name, None)
        tx.set_meta(db._meta)

    if schema_ref:
        try:
            db.delete_asset(schema_ref)
        except Exception:
            pass
    return True


def _reset_target_table(db: Mpdb, table_name: str) -> bool:
    """Remove a previous migration target and all of its storage metadata."""
    name = str(table_name or "").strip()
    if not name or not _table_exists(db, name):
        return False
    schema_ref = ""
    try:
        schema_ref = str(
            (getattr(db, "_meta", {}).get("tables", {}).get(name, {}) or {}).get("schema_ref")
            or ""
        ).strip()
    except Exception:
        schema_ref = ""
    changed = bool(reset_table_storage(db, name, drop_table=True))
    if changed and schema_ref:
        try:
            db.delete_asset(schema_ref)
        except Exception:
            pass
    return changed


def _delete_assets_by_prefix(db: Mpdb, prefix: str) -> int:
    deleted = 0
    try:
        keys = list(db.list_assets(prefix=str(prefix or "")) or [])
    except Exception:
        keys = []
    for key in keys:
        try:
            if db.delete_asset(str(key)):
                deleted += 1
        except Exception:
            continue
    return deleted


def _json_safe_converter(backend: Parse1CDBackend):
    converter = getattr(backend.value_decoder, "to_json_safe", None)
    if callable(converter):
        return converter

    def _fallback(value: Any) -> Any:
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).hex()
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except Exception:
                pass
        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

    return _fallback


def _normalize_row(
    row: dict[str, Any],
    *,
    source_table: str,
    source_row_index: int,
    field_map: dict[str, str],
    json_safe: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "__source_table": source_table,
        "__source_row_index": int(source_row_index),
        "__deleted__": bool(row.get("__deleted__", False)),
    }
    for source_name, target_name in field_map.items():
        out[target_name] = json_safe(row.get(source_name))
    return out


def _select_table_names(
    database: Any,
    schema_reader_cls: Any,
    *,
    table_names: Iterable[str] | None,
    include_service: bool,
    force_include: Iterable[str] | None = None,
) -> list[str]:
    available = list(database.get_table_names())
    available_by_lower = {str(n).lower(): str(n) for n in available}
    if table_names:
        selected: list[str] = []
        for requested in table_names:
            key = str(requested or "").strip().lower()
            if not key:
                continue
            selected.append(available_by_lower.get(key, str(requested)))
        return selected
    if include_service:
        return available
    base = [name for name in available if not bool(schema_reader_cls.is_service_table(name))]
    if force_include:
        base_set = {str(n).lower() for n in base}
        for forced in force_include:
            key = str(forced or "").strip().lower()
            if not key or key in base_set:
                continue
            original = available_by_lower.get(key)
            if original:
                base.append(original)
                base_set.add(key)
    return base


def _insert_rows(db: Mpdb, table_name: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    table = db.table(table_name)
    with db.transaction() as tx:
        for row in rows:
            table.insert_tx(tx, row, set_meta=False)
        tx.set_meta(db._meta)


def _insert_rows_tx(db: Mpdb, tx: Any, table_name: str, rows: list[dict[str, Any]], *, set_meta: bool = True) -> None:
    if not rows:
        return
    table = db.table(table_name)
    for row in rows:
        table.insert_tx(tx, row, set_meta=False)
    if set_meta:
        tx.set_meta(db._meta)


def _put_asset_tx(
    db: Mpdb,
    tx: Any,
    key: str,
    data: bytes,
    *,
    mime: str = "application/octet-stream",
    old_info: tuple[dict[str, Any] | None, dict[str, Any] | None] | None = None,
) -> None:
    key = str(key).replace("\\", "/").strip()
    if not key:
        raise ValueError("Empty asset key")

    if data is None:
        data = b""

    if old_info is None:
        old_table, old_meta = db._lookup_asset_info(key)
    else:
        old_table, old_meta = old_info

    db._ensure_assets_table_tx(tx)
    tbl = db.table(ASSETS_TABLE)

    # Free old chains early to maximize page reuse.
    for old in (old_table, old_meta):
        if isinstance(old, dict):
            first = int(old.get("first_page") or 0)
            if first > 0:
                try:
                    db._free_blob_chain(tx, first)
                except Exception:
                    pass

    # Remove old locator entries (table + legacy META).
    try:
        tbl.delete_tx(tx, {"key": key}, set_meta=False)
    except Exception:
        pass
    db._drop_unique_index_key_tx(tx, ASSETS_TABLE, "key", key)

    with db._lock:
        assets = db._meta.get(META_ASSETS, {})
        if isinstance(assets, dict) and key in assets:
            assets.pop(key, None)
            db._meta[META_ASSETS] = assets

    stored = db._encode_asset_payload(key, data, mime)
    first_pid = db._write_blob_chain(tx, stored)
    tbl.insert_tx(
        tx,
        {
            "key": key,
            "first_page": int(first_pid),
            "size": int(len(stored)),
            "mime": str(mime or "application/octet-stream"),
        },
        set_meta=False,
    )


def migrate_onecd_data_to_mpdb(
    db: Mpdb,
    source_path: str,
    *,
    table_names: Iterable[str] | None = None,
    limit_per_table: int | None = None,
    include_service: bool = False,
    include_deleted: bool = False,
    build_refs: bool = True,
    read_blobs: bool = False,
    target_prefix: str = "onec",
    batch_size: int = 5000,
    storage_mode: str = "packed",
    replace_existing: bool = True,
    fail_on_table_errors: bool = False,
    force_include_table_names: Iterable[str] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Import physical .1CD table rows into mpdb tables.

    This is intentionally separate from the synthetic XMLConf metadata loader:
    it uses the bundled Parse1CD reader for business data rows and keeps the
    source-to-target mapping as a JSON asset in mpdb.
    """
    source = Path(source_path)
    if source.suffix.lower() != ".1cd":
        raise ValueError("1CD data migration requires a .1CD file")
    if not source.exists():
        raise FileNotFoundError(str(source))

    # Fast-mode: skip per-commit fsync and auto-checkpoint during migration.
    # 1CD data is always re-importable, so durability during migration is not
    # critical.  A single checkpoint() at the end makes everything durable.
    _acp_orig_commits = getattr(db, "_acp_commits", 200)
    _acp_orig_wal = getattr(db, "_acp_wal_bytes", 16 * 1024 * 1024)
    _fast_mode_orig = getattr(db, "_migration_fast_mode", False)
    try:
        db._migration_fast_mode = True
        db._acp_commits = 10_000_000
        db._acp_wal_bytes = 512 * 1024 * 1024
    except Exception:
        pass

    backend = _load_parse1cd_backend()
    db_cls = backend.database_parser.OneCDatabase
    schema_reader_cls = backend.schema_reader.SchemaReader
    resolver_cls = backend.reference_resolver.ReferenceResolver
    json_safe = _json_safe_converter(backend)
    started_at = time.time()
    storage_mode_normalized = str(storage_mode or "packed").strip().lower()
    if storage_mode_normalized not in {"packed", "per_table"}:
        storage_mode_normalized = "packed"
    packed_table = sanitize_table_name(ONECD_PACKED_DATA_TABLE, prefix=target_prefix)
    try:
        packed_inline_limit = int(os.environ.get("META_ONEC_PACKED_INLINE_LIMIT") or ONECD_PACKED_INLINE_LIMIT)
    except Exception:
        packed_inline_limit = ONECD_PACKED_INLINE_LIMIT
    packed_inline_limit = max(0, int(packed_inline_limit))
    try:
        progress_row_step = int(os.environ.get("META_ONEC_IMPORT_PROGRESS_ROWS") or 250)
    except Exception:
        progress_row_step = 250
    progress_row_step = max(1, int(progress_row_step))
    try:
        progress_time_step = float(os.environ.get("META_ONEC_IMPORT_PROGRESS_SECONDS") or 2.0)
    except Exception:
        progress_time_step = 2.0
    progress_time_step = max(0.5, float(progress_time_step))

    manifest: dict[str, Any] = {
        "source_path": str(source),
        "parser_root": str(backend.parser_root),
        "asset_key": ONECD_DATA_MIGRATION_ASSET_KEY,
        "started_at": started_at,
        "finished_at": None,
        "limit_per_table": limit_per_table,
        "include_service": bool(include_service),
        "force_include_table_names": sorted(str(n) for n in (force_include_table_names or [])),
        "include_deleted": bool(include_deleted),
        "build_refs": bool(build_refs),
        "read_blobs": bool(read_blobs),
        "target_prefix": str(target_prefix or "onec"),
        "storage_mode": storage_mode_normalized,
        "packed_table": packed_table if storage_mode_normalized == "packed" else "",
        "packed_inline_limit": packed_inline_limit if storage_mode_normalized == "packed" else None,
        "tables": [],
        "errors": [],
        "summary": {
            "tables_seen": 0,
            "tables_imported": 0,
            "tables_skipped_empty": 0,
            "rows_imported": 0,
            "rows_offloaded": 0,
            "bytes_offloaded": 0,
            "reference_index_entries": 0,
            "source_rows": 0,
            "active_rows_scanned": 0,
            "tables_limited": 0,
            "tables_failed": 0,
            "reset_tables": 0,
            "reset_assets": 0,
        },
        "replace_existing": bool(replace_existing),
        "complete": False,
        "sampled": limit_per_table is not None,
    }
    metadata_by_kind_order = _load_metadata_by_kind_order(source)
    # Persist the UUID join, not guessed field positions or translated names.
    from .storage_bindings import load_storage_bindings
    try:
        manifest["storage_bindings"] = load_storage_bindings(str(source))
    except Exception as exc:
        manifest["mapping_warnings"] = [f"DBNames bindings unavailable: {exc}"]
    manifest["metadata_mapping_objects"] = sum(len(items) for items in metadata_by_kind_order.values())

    # A migration is a replacement, not an append. Packed mode shares one
    # physical table across all source tables, so a new run replaces the packed
    # projection and its offloaded row assets inside the staging DB.
    if replace_existing and storage_mode_normalized == "packed":
        if _reset_target_table(db, packed_table):
            manifest["summary"]["reset_tables"] += 1
        manifest["summary"]["reset_assets"] += _delete_assets_by_prefix(
            db, ONECD_PACKED_ROW_ASSET_PREFIX
        )

    progress_started = time.monotonic()
    last_progress_at = 0.0

    def _emit_progress(stage: str, *, force: bool = False, **fields: Any) -> None:
        nonlocal last_progress_at
        if progress is None:
            return
        now = time.monotonic()
        if not force and now - last_progress_at < 0.75:
            return
        last_progress_at = now
        event = {
            "stage": str(stage or ""),
            "elapsed_sec": round(now - progress_started, 3),
            "summary": dict(manifest.get("summary") or {}),
        }
        event.update(fields)
        try:
            progress(event)
        except Exception:
            pass

    with db_cls(str(source)) as onecd:
        selected_tables = _select_table_names(
            onecd,
            schema_reader_cls,
            table_names=table_names,
            include_service=include_service,
            force_include=force_include_table_names,
        )
        manifest["summary"]["tables_seen"] = len(selected_tables)
        _emit_progress(
            "selected_tables",
            force=True,
            message=f"Selected 1CD data tables: {len(selected_tables)}",
            current_table=0,
            total_tables=len(selected_tables),
            rows_imported=0,
        )

        resolver = None
        if build_refs:
            try:
                _emit_progress(
                    "reference_index",
                    force=True,
                    message="Building 1CD reference index...",
                    current_table=0,
                    total_tables=len(selected_tables),
                    rows_imported=0,
                )
                resolver = resolver_cls(onecd)
                manifest["summary"]["reference_index_entries"] = int(resolver.build_index(selected_tables) or 0)
            except Exception as exc:
                manifest["errors"].append({"stage": "reference_index", "error": str(exc)})
                resolver = None

        # In packed mode, accumulate rows from ALL tables into one cross-table
        # batch before flushing.  This reduces the transaction count from
        # ~N_tables to ~total_rows/batch_size, giving 5-20x faster writes.
        _global_packed_rows: list[dict[str, Any]] = []
        _global_packed_assets: list[tuple[int, int, bytes, str]] = []  # (pos, row_idx, data, src_table)
        _pending_stats: list[tuple[Any, int, int, int]] = []  # (table_entry, rows, offload_rows, offload_bytes)
        _global_batch_source_table: str = ""

        def _flush_global_packed_batch(force: bool = False) -> None:
            nonlocal _global_packed_rows, _global_packed_assets, _pending_stats
            if not _global_packed_rows:
                return
            if not force and len(_global_packed_rows) < max(1, int(batch_size)):
                return
            rows_to_flush = _global_packed_rows
            assets_to_flush = _global_packed_assets
            stats_to_flush = _pending_stats
            _global_packed_rows = []
            _global_packed_assets = []
            _pending_stats = []

            table_name = packed_table
            with db.transaction() as tx:
                if assets_to_flush:
                    # Group assets by source table for keying
                    from itertools import groupby as _groupby
                    for src_tbl, grp in _groupby(assets_to_flush, key=lambda x: x[3]):
                        grp_list = list(grp)
                        first_row_index = min(int(item[1]) for item in grp_list)
                        last_row_index = max(int(item[1]) for item in grp_list)
                        data_asset = _packed_batch_asset_key(src_tbl, first_row_index, last_row_index)
                        old_info = db._lookup_asset_info(data_asset)
                        packed_payload = bytearray()
                        for row_pos, _row_index, data_bytes, _st in grp_list:
                            offset = len(packed_payload)
                            packed_payload.extend(data_bytes)
                            packed_payload.extend(b"\n")
                            rows_to_flush[int(row_pos)]["data_asset"] = data_asset
                            rows_to_flush[int(row_pos)]["data_offset"] = int(offset)
                            rows_to_flush[int(row_pos)]["data_size"] = int(len(data_bytes))
                        _put_asset_tx(
                            db, tx, data_asset, bytes(packed_payload),
                            mime="application/x-jsonlines", old_info=old_info,
                        )
                _insert_rows_tx(db, tx, table_name, rows_to_flush, set_meta=False)
                tx.set_meta(db._meta)

            # Credit rows back to their source table_entry
            for te, n_rows, n_offload, b_offload in stats_to_flush:
                te["imported_rows"] += n_rows
                te["offloaded_rows"] += n_offload
                te["offloaded_bytes"] += b_offload

        total_tables = len(selected_tables)
        for table_index, physical_name in enumerate(selected_tables, start=1):
            table_started = time.time()
            table = onecd.get_table_info(physical_name)
            if table is None:
                manifest["errors"].append({"table": physical_name, "error": "table not found"})
                manifest["summary"]["tables_failed"] += 1
                continue
            source_rows = int(onecd.get_total_rows(physical_name) or 0)
            manifest["summary"]["source_rows"] += max(0, source_rows)
            if source_rows <= 0:
                manifest["summary"]["tables_skipped_empty"] += 1
                _emit_progress(
                    "table_skipped_empty",
                    force=(table_index == total_tables or table_index % 100 == 0),
                    message=f"Skipping empty 1CD data table {table_index}/{total_tables}: {physical_name}",
                    current_table=table_index,
                    total_tables=total_tables,
                    table=physical_name,
                    table_rows=0,
                    table_total=0,
                    rows_imported=manifest["summary"]["rows_imported"],
                    tables_skipped_empty=manifest["summary"]["tables_skipped_empty"],
                )
                continue

            used_columns: set[str] = set()
            field_map = {
                str(getattr(field, "name", "") or ""): sanitize_column_name(str(getattr(field, "name", "") or ""), used_columns)
                for field in list(getattr(table, "fields", []) or [])
            }
            target_table = sanitize_table_name(physical_name, prefix=target_prefix)
            table_meta = _describe_physical_table(physical_name, schema_reader_cls, metadata_by_kind_order)
            table_entry: dict[str, Any] = {
                "source_table": physical_name,
                "target_table": packed_table if storage_mode_normalized == "packed" else target_table,
                "logical_table": target_table,
                "kind": str(table_meta.get("kind") or "unknown"),
                "table_role": str(table_meta.get("table_role") or ""),
                "logical_name": str(table_meta.get("metadata_name") or ""),
                "logical_title": str(table_meta.get("metadata_title") or ""),
                "metadata_uuid": str(table_meta.get("metadata_uuid") or ""),
                "metadata_order": int(table_meta.get("metadata_order") or 0),
                "dbname_kind": str(table_meta.get("dbname_kind") or ""),
                "metadata_origin": str(table_meta.get("metadata_origin") or ""),
                "kind_source": str(table_meta.get("kind_source") or ""),
                "source_rows": source_rows,
                "imported_rows": 0,
                "offloaded_rows": 0,
                "offloaded_bytes": 0,
                "created_table": False,
                "field_map": dict(field_map),
                "errors": [],
                "duration_sec": 0.0,
            }
            _emit_progress(
                "table_start",
                force=True,
                message=f"Importing 1CD data table {table_index}/{total_tables}: {physical_name}",
                current_table=table_index,
                total_tables=total_tables,
                table=physical_name,
                table_rows=0,
                table_total=table_entry["source_rows"],
                rows_imported=manifest["summary"]["rows_imported"],
            )

            try:
                if (
                    replace_existing
                    and storage_mode_normalized == "per_table"
                    and _reset_target_table(db, target_table)
                ):
                    manifest["summary"]["reset_tables"] += 1

                if storage_mode_normalized == "packed":
                    if not _table_exists(db, packed_table):
                        db.create_table(
                            packed_table,
                            _build_packed_rows_schema(),
                            external_schema=True,
                        )
                        table_entry["created_table"] = True
                elif not _table_exists(db, target_table):
                    db.create_table(
                        target_table,
                        _build_table_schema(table, field_map=field_map, rich_refs=True),
                        external_schema=True,
                    )
                    table_entry["created_table"] = True

                # Per-table state for per_table mode (packed mode uses global batch)
                batch: list[dict[str, Any]] = []
                asset_batch: list[tuple[int, int, bytes]] = []
                batch_offloaded_rows = 0
                batch_offloaded_bytes = 0
                # Track pending global-batch contribution for this table
                _table_pending_rows = 0
                _table_pending_offload_rows = 0
                _table_pending_offload_bytes = 0
                last_row_heartbeat_at = time.monotonic()
                last_row_heartbeat_rows = 0

                def _flush_batch() -> tuple[int, int, int]:
                    nonlocal batch, asset_batch, batch_offloaded_rows, batch_offloaded_bytes
                    if not batch:
                        return 0, 0, 0
                    table_name = target_table
                    with db.transaction() as tx:
                        if asset_batch:
                            first_row_index = min(int(item[1]) for item in asset_batch)
                            last_row_index = max(int(item[1]) for item in asset_batch)
                            data_asset = _packed_batch_asset_key(physical_name, first_row_index, last_row_index)
                            old_info = db._lookup_asset_info(data_asset)
                            packed_payload = bytearray()
                            for row_pos, _row_index, data_bytes in asset_batch:
                                offset = len(packed_payload)
                                packed_payload.extend(data_bytes)
                                packed_payload.extend(b"\n")
                                batch[int(row_pos)]["data_asset"] = data_asset
                                batch[int(row_pos)]["data_offset"] = int(offset)
                                batch[int(row_pos)]["data_size"] = int(len(data_bytes))
                            _put_asset_tx(
                                db, tx, data_asset, bytes(packed_payload),
                                mime="application/x-jsonlines", old_info=old_info,
                            )
                        _insert_rows_tx(db, tx, table_name, batch, set_meta=False)
                        tx.set_meta(db._meta)
                    inserted = len(batch)
                    offloaded_rows = int(batch_offloaded_rows)
                    offloaded_bytes = int(batch_offloaded_bytes)
                    batch = []
                    asset_batch = []
                    batch_offloaded_rows = 0
                    batch_offloaded_bytes = 0
                    return inserted, offloaded_rows, offloaded_bytes

                source_row_index = 0
                for row in onecd.iter_table_rows(
                    physical_name,
                    limit=limit_per_table,
                    read_blobs=read_blobs,
                    include_deleted=include_deleted,
                    decode=True,
                    rich_refs=True,
                    resolver=resolver,
                ):
                    # Enforce the sampling contract in our own loop as well.
                    # Keep the Runtime limit authoritative even if a parser
                    # implementation returns more rows than requested.
                    if (
                        limit_per_table is not None
                        and source_row_index >= max(0, int(limit_per_table))
                    ):
                        break
                    source_row_index += 1
                    normalized_row = _normalize_row(
                        dict(row),
                        source_table=physical_name,
                        source_row_index=source_row_index,
                        field_map=field_map,
                        json_safe=json_safe,
                    )
                    if storage_mode_normalized == "packed":
                        packed_row, offloaded_data = _pack_data_row(
                            normalized_row,
                            inline_data_limit=packed_inline_limit,
                        )
                        # In packed mode, push to the global cross-table batch
                        row_pos_in_global = len(_global_packed_rows)
                        _global_packed_rows.append(packed_row)
                        _table_pending_rows += 1
                        if offloaded_data is not None:
                            _global_packed_assets.append((row_pos_in_global, source_row_index, offloaded_data, physical_name))
                            _table_pending_offload_rows += 1
                            _table_pending_offload_bytes += len(offloaded_data)
                        # Flush when global batch is full
                        if len(_global_packed_rows) >= max(1, int(batch_size)):
                            # Credit pending stats before flush
                            _pending_stats.append((table_entry, _table_pending_rows, _table_pending_offload_rows, _table_pending_offload_bytes))
                            _table_pending_rows = 0
                            _table_pending_offload_rows = 0
                            _table_pending_offload_bytes = 0
                            _flush_global_packed_batch(force=True)
                    else:
                        batch.append(normalized_row)

                    current_batch_rows = (
                        source_row_index
                        if storage_mode_normalized == "packed"
                        else int(table_entry["imported_rows"] or 0) + len(batch)
                    )
                    now = time.monotonic()
                    if (
                        current_batch_rows == 1
                        or current_batch_rows >= table_entry["source_rows"]
                        or current_batch_rows - last_row_heartbeat_rows >= progress_row_step
                        or now - last_row_heartbeat_at >= progress_time_step
                    ):
                        last_row_heartbeat_at = now
                        last_row_heartbeat_rows = current_batch_rows
                        _emit_progress(
                            "rows",
                            force=(
                                current_batch_rows == 1
                                or current_batch_rows >= int(table_entry["source_rows"] or 0)
                            ),
                            message=f"Importing 1CD data table {table_index}/{total_tables}: {physical_name}",
                            current_table=table_index,
                            total_tables=total_tables,
                            table=physical_name,
                            table_rows=current_batch_rows,
                            table_total=table_entry["source_rows"],
                            rows_imported=(
                                int(manifest["summary"]["rows_imported"] or 0)
                                + current_batch_rows
                            ),
                            rows_offloaded=table_entry["offloaded_rows"] + batch_offloaded_rows,
                            bytes_offloaded=table_entry["offloaded_bytes"] + batch_offloaded_bytes,
                        )
                    if len(batch) >= max(1, int(batch_size or 1)):
                        inserted, offloaded_rows, offloaded_bytes = _flush_batch()
                        table_entry["imported_rows"] += inserted
                        table_entry["offloaded_rows"] += offloaded_rows
                        table_entry["offloaded_bytes"] += offloaded_bytes
                        _emit_progress(
                            "rows",
                            message=f"Importing 1CD data table {table_index}/{total_tables}: {physical_name}",
                            current_table=table_index,
                            total_tables=total_tables,
                            table=physical_name,
                            table_rows=table_entry["imported_rows"],
                            table_total=table_entry["source_rows"],
                            rows_imported=(
                                int(manifest["summary"]["rows_imported"] or 0)
                                + int(table_entry["imported_rows"] or 0)
                            ),
                            rows_offloaded=table_entry["offloaded_rows"],
                            bytes_offloaded=table_entry["offloaded_bytes"],
                        )
                if storage_mode_normalized == "packed":
                    # Register pending stats for this table (rows sitting in global batch)
                    if _table_pending_rows > 0:
                        _pending_stats.append((table_entry, _table_pending_rows, _table_pending_offload_rows, _table_pending_offload_bytes))
                    # In packed mode the real row count is credited by _flush_global_packed_batch
                    # via `te["imported_rows"] += n_rows`.  Do NOT set imported_rows here — that
                    # would double-count because the flush adds on top of whatever value is already
                    # in the field.  Store source_row_index in a private field for progress events.
                    table_entry["_source_row_index"] = source_row_index
                elif batch:
                    inserted, offloaded_rows, offloaded_bytes = _flush_batch()
                    table_entry["imported_rows"] += inserted
                    table_entry["offloaded_rows"] += offloaded_rows
                    table_entry["offloaded_bytes"] += offloaded_bytes
                    _emit_progress(
                        "rows",
                        force=True,
                        message=f"Importing 1CD data table {table_index}/{total_tables}: {physical_name}",
                        current_table=table_index,
                        total_tables=total_tables,
                        table=physical_name,
                        table_rows=table_entry["imported_rows"],
                        table_total=table_entry["source_rows"],
                        rows_imported=(
                            int(manifest["summary"]["rows_imported"] or 0)
                            + int(table_entry["imported_rows"] or 0)
                        ),
                        rows_offloaded=table_entry["offloaded_rows"],
                        bytes_offloaded=table_entry["offloaded_bytes"],
                    )
            except Exception as exc:
                table_entry["errors"].append(str(exc))
                manifest["errors"].append({"table": physical_name, "error": str(exc)})
                manifest["summary"]["tables_failed"] += 1
                dropped_empty = False
                if (
                    storage_mode_normalized == "per_table"
                    and bool(table_entry.get("created_table"))
                    and int(table_entry.get("imported_rows") or 0) <= 0
                ):
                    dropped_empty = _drop_empty_target_table(db, target_table)
                    if dropped_empty:
                        table_entry["dropped_empty_target"] = True
                _emit_progress(
                    "table_error",
                    force=True,
                    message=f"1CD data table import warning {table_index}/{total_tables}: {physical_name}",
                    current_table=table_index,
                    total_tables=total_tables,
                    table=physical_name,
                    table_rows=table_entry["imported_rows"],
                    table_total=table_entry["source_rows"],
                    dropped_empty_target=dropped_empty,
                    error=str(exc),
                    rows_imported=manifest["summary"]["rows_imported"],
                )

            table_entry["duration_sec"] = round(time.time() - table_started, 3)
            scanned_rows = int(
                table_entry.get("_source_row_index")
                if storage_mode_normalized == "packed"
                else table_entry.get("imported_rows")
                or 0
            )
            manifest["summary"]["active_rows_scanned"] += max(0, scanned_rows)
            table_entry["limited"] = bool(
                limit_per_table is not None
                and scanned_rows >= int(limit_per_table or 0)
                and int(table_entry.get("source_rows") or 0) > scanned_rows
            )
            if table_entry["limited"]:
                manifest["summary"]["tables_limited"] += 1
            manifest["tables"].append(table_entry)
            # In packed mode the summary is recalculated after the final batch flush
            # to avoid double-counting (imported_rows is credited by _flush_global_packed_batch).
            if storage_mode_normalized != "packed" and int(table_entry["imported_rows"] or 0) > 0:
                manifest["summary"]["tables_imported"] += 1
                manifest["summary"]["rows_imported"] += int(table_entry["imported_rows"] or 0)
                manifest["summary"]["rows_offloaded"] += int(table_entry.get("offloaded_rows") or 0)
                manifest["summary"]["bytes_offloaded"] += int(table_entry.get("offloaded_bytes") or 0)
            _table_done_rows = (
                int(table_entry.get("_source_row_index") or 0)
                if storage_mode_normalized == "packed"
                else int(table_entry["imported_rows"] or 0)
            )
            _emit_progress(
                "table_done",
                force=True,
                message=f"Imported 1CD data table {table_index}/{total_tables}: {physical_name}",
                current_table=table_index,
                total_tables=total_tables,
                table=physical_name,
                table_rows=_table_done_rows,
                table_total=table_entry["source_rows"],
                rows_imported=manifest["summary"]["rows_imported"],
                tables_imported=manifest["summary"]["tables_imported"],
                rows_offloaded=manifest["summary"]["rows_offloaded"],
                bytes_offloaded=manifest["summary"]["bytes_offloaded"],
            )

    # Flush any remaining rows in the cross-table packed global batch and recalculate summary.
    if storage_mode_normalized == "packed":
        if _global_packed_rows:
            _flush_global_packed_batch(force=True)
        # Always recalculate packed-mode summary from credited table entries to avoid
        # double-counting from the per-table estimate set above.
        manifest["summary"]["tables_imported"] = sum(
            1 for t in manifest["tables"] if int(t.get("imported_rows") or 0) > 0
        )
        manifest["summary"]["rows_imported"] = sum(
            int(t.get("imported_rows") or 0) for t in manifest["tables"]
        )
        manifest["summary"]["rows_offloaded"] = sum(
            int(t.get("offloaded_rows") or 0) for t in manifest["tables"]
        )
        manifest["summary"]["bytes_offloaded"] = sum(
            int(t.get("offloaded_bytes") or 0) for t in manifest["tables"]
        )

    manifest["complete"] = bool(
        limit_per_table is None
        and not manifest.get("errors")
        and int(manifest["summary"].get("tables_limited") or 0) == 0
    )
    manifest["finished_at"] = time.time()
    try:
        db.put_assets_bulk(
            [
                (
                    ONECD_DATA_MIGRATION_ASSET_KEY,
                    json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"),
                    "application/json",
                )
            ]
        )
    except Exception as exc:
        manifest["asset_error"] = str(exc)
        manifest["asset_key"] = ""
        manifest.setdefault("errors", []).append(
            {
                "stage": "store_migration_manifest",
                "asset_key": ONECD_DATA_MIGRATION_ASSET_KEY,
                "error": str(exc),
            }
        )
    _emit_progress(
        "done",
        force=True,
        message="1CD data migration completed",
        current_table=manifest["summary"]["tables_seen"],
        total_tables=manifest["summary"]["tables_seen"],
        rows_imported=manifest["summary"]["rows_imported"],
        tables_imported=manifest["summary"]["tables_imported"],
        rows_offloaded=manifest["summary"]["rows_offloaded"],
        bytes_offloaded=manifest["summary"]["bytes_offloaded"],
    )

    # Restore settings and do a single durable checkpoint.
    try:
        db._migration_fast_mode = _fast_mode_orig
        db._acp_commits = _acp_orig_commits
        db._acp_wal_bytes = _acp_orig_wal
        db.checkpoint(durable=True)
    except Exception:
        pass

    if fail_on_table_errors and manifest.get("errors"):
        first = manifest["errors"][0]
        raise RuntimeError(
            "1CD data migration completed with "
            f"{len(manifest['errors'])} error(s); first={first!r}"
        )

    return manifest
