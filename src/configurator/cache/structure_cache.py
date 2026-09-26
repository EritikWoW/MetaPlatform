from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from src.configurator.manifest_schema import ManifestObject

CACHE_SUFFIX = ".structure_cache.json"
CACHE_META_SUFFIX = ".meta.json"
STRUCTURE_CACHE_VERSION = 2
_EXTERNALIZED_KEYS = (
    "attributes",
    "command_interface",
    "content_refs",
    "dimensions",
    "dump_info_children",
    "enum_values",
    "form_model",
    "help_contents",
    "layout_model",
    "metadata_structure",
    "objects",
    "requisites",
    "resources",
    "restriction_templates",
    "rights",
    "storage_profile",
    "tabular_parts",
)


def _count_unresolved_externalized_rows(objs: list[dict[str, Any]]) -> int:
    count = 0
    for row in objs:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            continue
        for key in _EXTERNALIZED_KEYS:
            if payload.get(f"{key}_ref") and key not in payload:
                count += 1
                break
    return count


@dataclass
class StructureCacheMeta:
    cache_version: int
    db_uid: str
    structure_hash: str
    object_count: int
    generated_at: int
    db_mtime_ns: int
    db_size: int


@dataclass
class StructureCachePayload:
    meta: StructureCacheMeta
    objects: list[dict[str, Any]]


def cache_path_for_db(db_path: str | Path) -> Path:
    p = Path(db_path)
    return p.with_suffix(p.suffix + CACHE_SUFFIX)


def cache_meta_path_for_db(db_path: str | Path) -> Path:
    return _meta_path_for_cache_file(cache_path_for_db(db_path))


def _meta_path_for_cache_file(path: Path) -> Path:
    return path.with_name(path.name + CACHE_META_SUFFIX)


def _db_stat_dict(db_path: str | Path) -> dict[str, int]:
    p = Path(db_path)
    try:
        st = p.stat()
        return {"db_mtime_ns": int(st.st_mtime_ns), "db_size": int(st.st_size)}
    except OSError:
        return {"db_mtime_ns": 0, "db_size": 0}


def _mo_to_dict(o: ManifestObject) -> dict[str, Any]:
    return {
        "guid": str(o.guid),
        "parent_guid": str(o.parent_guid),
        "type": str(o.type),
        "name": str(o.name),
        "title": str(o.title),
        "kind": str(o.kind),
        "payload": o.payload if isinstance(o.payload, dict) else {},
    }


def _obj_to_dict(o: ManifestObject | dict[str, Any]) -> dict[str, Any]:
    if isinstance(o, ManifestObject):
        return _mo_to_dict(o)
    if isinstance(o, dict):
        return {
            "guid": str(o.get("guid") or ""),
            "parent_guid": str(o.get("parent_guid") or ""),
            "type": str(o.get("type") or ""),
            "name": str(o.get("name") or ""),
            "title": str(o.get("title") or ""),
            "kind": str(o.get("kind") or "object"),
            "payload": o.get("payload") if isinstance(o.get("payload"), dict) else {},
        }
    raise TypeError(f"Unsupported object type for structure cache: {type(o)!r}")


def _dict_to_mo(row: dict[str, Any]) -> ManifestObject:
    return ManifestObject(
        guid=str(row.get("guid") or ""),
        parent_guid=str(row.get("parent_guid") or ""),
        type=str(row.get("type") or ""),
        name=str(row.get("name") or ""),
        title=str(row.get("title") or ""),
        payload=row.get("payload") or {},
        kind=str(row.get("kind") or "object"),
    )


def compute_structure_hash(objects: Iterable[ManifestObject | dict[str, Any]]) -> str:
    rows = [_obj_to_dict(o) for o in objects]
    rows.sort(key=lambda row: (
        str(row.get("guid") or ""),
        str(row.get("parent_guid") or ""),
        str(row.get("type") or ""),
        str(row.get("name") or ""),
        str(row.get("kind") or ""),
    ))

    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _load_raw_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _load_raw_meta(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def cache_needs_compaction(db_path: str | Path) -> bool:
    path = cache_path_for_db(db_path)
    if not path.exists():
        return False
    try:
        with path.open("rb") as fh:
            prefix = fh.read(8)
    except OSError:
        return False
    return prefix.startswith(b"{\n  \"") or prefix.startswith(b"{\r\n  \"")


def _meta_from_raw(
    meta: dict[str, Any] | None,
    *,
    db_path: str | Path,
    db_uid: str | None = None,
    verify_db_state: bool = True,
) -> Optional[StructureCacheMeta]:
    if not isinstance(meta, dict):
        return None
    if int(meta.get("cache_version") or 0) != STRUCTURE_CACHE_VERSION:
        return None
    if db_uid is not None and str(meta.get("db_uid") or "") != str(db_uid):
        return None

    if verify_db_state:
        expected_stat = _db_stat_dict(db_path)
        if int(meta.get("db_mtime_ns") or 0) != expected_stat["db_mtime_ns"]:
            return None
        if int(meta.get("db_size") or 0) != expected_stat["db_size"]:
            return None

    try:
        return StructureCacheMeta(
            cache_version=STRUCTURE_CACHE_VERSION,
            db_uid=str(meta.get("db_uid") or ""),
            structure_hash=str(meta.get("structure_hash") or ""),
            object_count=int(meta.get("object_count") or 0),
            generated_at=int(meta.get("generated_at") or 0),
            db_mtime_ns=int(meta.get("db_mtime_ns") or 0),
            db_size=int(meta.get("db_size") or 0),
        )
    except Exception:
        return None


def load_structure_cache_meta(
    db_path: str | Path,
    *,
    db_uid: str | None = None,
    verify_db_state: bool = True,
) -> Optional[StructureCacheMeta]:
    meta_path = cache_meta_path_for_db(db_path)
    meta_raw = _load_raw_meta(meta_path)
    meta = _meta_from_raw(
        meta_raw,
        db_path=db_path,
        db_uid=db_uid,
        verify_db_state=verify_db_state,
    )
    if meta is not None:
        return meta

    path = cache_path_for_db(db_path)
    raw = _load_raw_cache(path)
    if raw is None:
        return None

    meta = _meta_from_raw(
        raw.get("meta") or {},
        db_path=db_path,
        db_uid=db_uid,
        verify_db_state=verify_db_state,
    )
    if meta is None:
        return None

    try:
        _write_meta_file(meta_path, meta)
    except Exception:
        pass
    return meta


def load_structure_cache(
    db_path: str | Path,
    *,
    db_uid: str,
    structure_hash: str,
    verify_db_state: bool = True,
) -> Optional[list[ManifestObject]]:
    path = cache_path_for_db(db_path)
    raw = _load_raw_cache(path)
    if raw is None:
        return None

    meta = load_structure_cache_meta(db_path, db_uid=db_uid, verify_db_state=verify_db_state)
    if meta is None:
        return None
    if str(meta.structure_hash or "") != str(structure_hash):
        return None

    objs = raw.get("objects") or []
    if not isinstance(objs, list):
        return None
    unresolved_rows = _count_unresolved_externalized_rows(objs)
    if unresolved_rows:
        total_rows = max(len(objs), 1)
        # Tolerate a sparse tail of unresolved externalized refs in otherwise
        # valid snapshots. Reject only when the cache is materially incomplete.
        if unresolved_rows * 20 >= total_rows:
            return None
    try:
        return [_dict_to_mo(x) for x in objs if isinstance(x, dict)]
    except Exception:
        return None


def load_structure_cache_payload(
    db_path: str | Path,
    *,
    db_uid: str | None = None,
    verify_db_state: bool = True,
) -> Optional[StructureCachePayload]:
    path = cache_path_for_db(db_path)
    raw = _load_raw_cache(path)
    if raw is None:
        return None

    meta_raw = raw.get("meta") or {}
    if int(meta_raw.get("cache_version") or 0) != STRUCTURE_CACHE_VERSION:
        return None
    if db_uid is not None and str(meta_raw.get("db_uid") or "") != str(db_uid):
        return None

    if verify_db_state:
        expected_stat = _db_stat_dict(db_path)
        if int(meta_raw.get("db_mtime_ns") or 0) != expected_stat["db_mtime_ns"]:
            return None
        if int(meta_raw.get("db_size") or 0) != expected_stat["db_size"]:
            return None

    objs = raw.get("objects") or []
    if not isinstance(objs, list):
        return None

    try:
        meta = StructureCacheMeta(
            cache_version=STRUCTURE_CACHE_VERSION,
            db_uid=str(meta_raw.get("db_uid") or ""),
            structure_hash=str(meta_raw.get("structure_hash") or ""),
            object_count=int(meta_raw.get("object_count") or 0),
            generated_at=int(meta_raw.get("generated_at") or 0),
            db_mtime_ns=int(meta_raw.get("db_mtime_ns") or 0),
            db_size=int(meta_raw.get("db_size") or 0),
        )
        rows = [_obj_to_dict(x) for x in objs if isinstance(x, dict)]
        return StructureCachePayload(meta=meta, objects=rows)
    except Exception:
        return None


def _write_cache_file(path: Path, payload: StructureCachePayload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(asdict(payload), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(tmp, path)
    _write_meta_file(_meta_path_for_cache_file(path), payload.meta)


def _write_meta_file(path: Path, meta: StructureCacheMeta) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(asdict(meta), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def drop_structure_cache(db_path: str | Path) -> None:
    cache_path = cache_path_for_db(db_path)
    meta_path = cache_meta_path_for_db(db_path)
    for path in (cache_path, meta_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def save_structure_cache_meta_only(
    db_path: str | Path,
    *,
    db_uid: str,
    structure_hash: str,
    object_count: int,
    generated_at: int,
) -> StructureCacheMeta:
    cache_path = cache_path_for_db(db_path)
    try:
        cache_path.unlink()
    except FileNotFoundError:
        pass

    stat = _db_stat_dict(db_path)
    meta = StructureCacheMeta(
        cache_version=STRUCTURE_CACHE_VERSION,
        db_uid=str(db_uid),
        structure_hash=str(structure_hash),
        object_count=int(object_count),
        generated_at=int(generated_at),
        db_mtime_ns=int(stat["db_mtime_ns"]),
        db_size=int(stat["db_size"]),
    )
    _write_meta_file(cache_meta_path_for_db(db_path), meta)
    return meta


def save_structure_cache(
    db_path: str | Path,
    *,
    db_uid: str,
    structure_hash: str,
    generated_at: int,
    objects: Iterable[ManifestObject | dict[str, Any]],
) -> Path:
    path = cache_path_for_db(db_path)
    obj_list = [_obj_to_dict(o) for o in objects]
    stat = _db_stat_dict(db_path)
    payload = StructureCachePayload(
        meta=StructureCacheMeta(
            cache_version=STRUCTURE_CACHE_VERSION,
            db_uid=str(db_uid),
            structure_hash=str(structure_hash),
            object_count=len(obj_list),
            generated_at=int(generated_at),
            db_mtime_ns=int(stat["db_mtime_ns"]),
            db_size=int(stat["db_size"]),
        ),
        objects=obj_list,
    )
    _write_cache_file(path, payload)
    return path


def save_structure_cache_snapshot(
    db_path: str | Path,
    *,
    db_uid: str,
    generated_at: int,
    objects: Iterable[ManifestObject | dict[str, Any]],
) -> StructureCacheMeta:
    rows = [_obj_to_dict(o) for o in objects]
    structure_hash = compute_structure_hash(rows)
    save_structure_cache(
        db_path,
        db_uid=str(db_uid),
        structure_hash=structure_hash,
        generated_at=int(generated_at),
        objects=rows,
    )
    meta = load_structure_cache_meta(db_path, db_uid=db_uid)
    if meta is None:
        raise RuntimeError("Failed to persist structure cache")
    return meta



def upsert_structure_cache_objects(
    db_path: str | Path,
    *,
    db_uid: str,
    generated_at: int,
    objects: Iterable[ManifestObject | dict[str, Any]],
) -> Optional[StructureCacheMeta]:
    payload = load_structure_cache_payload(db_path, db_uid=db_uid, verify_db_state=False)
    if payload is None:
        return None

    rows_by_guid = {
        str(row.get("guid") or ""): dict(row)
        for row in payload.objects
        if isinstance(row, dict) and str(row.get("guid") or "")
    }
    for obj in objects:
        row = _obj_to_dict(obj)
        guid = str(row.get("guid") or "")
        if guid:
            rows_by_guid[guid] = row

    rows = list(rows_by_guid.values())
    save_structure_cache(
        db_path,
        db_uid=str(db_uid),
        structure_hash=compute_structure_hash(rows),
        generated_at=int(generated_at),
        objects=rows,
    )
    return load_structure_cache_meta(db_path, db_uid=db_uid)



def delete_structure_cache_objects(
    db_path: str | Path,
    *,
    db_uid: str,
    generated_at: int,
    guids: Iterable[str],
) -> Optional[StructureCacheMeta]:
    payload = load_structure_cache_payload(db_path, db_uid=db_uid, verify_db_state=False)
    if payload is None:
        return None

    delete_set = {str(g or "").strip() for g in guids if str(g or "").strip()}
    if not delete_set:
        return load_structure_cache_meta(db_path, db_uid=db_uid)

    rows = [
        dict(row)
        for row in payload.objects
        if isinstance(row, dict) and str(row.get("guid") or "") not in delete_set
    ]
    save_structure_cache(
        db_path,
        db_uid=str(db_uid),
        structure_hash=compute_structure_hash(rows),
        generated_at=int(generated_at),
        objects=rows,
    )
    return load_structure_cache_meta(db_path, db_uid=db_uid)
