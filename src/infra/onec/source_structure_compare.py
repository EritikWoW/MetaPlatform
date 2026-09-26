from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Sequence

from .importer import DirectorySource, ZipSource
from .onec_requisites_parser import OneCXmlParser
from .onecd_source import OneCDConfigSource
from .source_compat import resolve_onec_source


_IGNORED_PAYLOAD_KEYS = {"imported"}


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _unique_values(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        text = _norm_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _row_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    try:
        order = int(_norm_text(row.get("order")) or 0)
    except Exception:
        order = 0
    return (
        order,
        _norm_text(row.get("name")).casefold(),
        _norm_text(row.get("guid")).casefold(),
    )


def _build_child_index(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if _norm_text(row.get("type")).lower() != "subsystem":
            continue
        parent_guid = _norm_text(row.get("parent_guid"))
        index.setdefault(parent_guid, []).append(row)
    for parent_guid, children in index.items():
        children.sort(key=_row_sort_key)
    return index


def _title_or_name(row: dict[str, Any]) -> str:
    return _norm_text(row.get("title") or row.get("name") or row.get("guid"))


def _source_title(obj: Any) -> str:
    title = _norm_text(getattr(obj, "title", ""))
    if title:
        return title
    synonyms = getattr(obj, "synonyms", None)
    if isinstance(synonyms, dict):
        for lang in ("uk", "en", "ru"):
            text = _norm_text(synonyms.get(lang))
            if text:
                return text
    return _norm_text(getattr(obj, "name", ""))


def _source_type(obj: Any) -> str:
    for attr in ("obj_type", "family", "type"):
        text = _norm_text(getattr(obj, attr, ""))
        if text:
            return text
    return ""


def _source_payload(obj: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    if hasattr(obj, "to_mp_payload") and callable(getattr(obj, "to_mp_payload")):
        try:
            data = dict(obj.to_mp_payload() or {})
        except Exception:
            data = {}
        payload.update(data)
    else:
        for key in (
            "comment",
            "content_refs",
            "child_subsystems",
            "include_help_in_contents",
            "include_in_command_interface",
            "use_one_command",
            "picture_ref",
            "objects",
        ):
            value = getattr(obj, key, None)
            if value is None:
                continue
            if isinstance(value, list):
                payload[key] = list(value)
            elif isinstance(value, dict):
                payload[key] = dict(value)
            else:
                payload[key] = value

    for key in list(payload.keys()):
        if key in _IGNORED_PAYLOAD_KEYS:
            payload.pop(key, None)

    return payload


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, set):
        return [_normalize_value(item) for item in sorted(value, key=lambda item: repr(item))]
    if isinstance(value, str):
        return value.strip()
    return value


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _IGNORED_PAYLOAD_KEYS:
            continue
        normalized[str(key)] = _normalize_value(value)
    return normalized


def _load_source_objects(source_path: str, source_kind: str) -> tuple[dict[str, Any], list[Any]]:
    resolved = resolve_onec_source(source_path, source_kind)
    effective_path = str(resolved.semantic_path or source_path).strip()
    if not effective_path:
        raise ValueError("source_path is required")

    if resolved.semantic_kind == "1cd":
        source = OneCDConfigSource(effective_path)
        return {"resolved": resolved, "effective_path": effective_path}, list(source.metadata_objects())

    if resolved.semantic_kind == "zip":
        with ZipSource(effective_path) as source:
            return {"resolved": resolved, "effective_path": effective_path}, OneCXmlParser().parse_all(source)

    path = Path(effective_path)
    if path.is_file():
        class _SingleFileSource:
            def __init__(self, file_path: Path) -> None:
                self._path = file_path

            def list_files(self) -> List[str]:
                return [self._path.name]

            def read_bytes(self, rel_path: str) -> bytes:
                if _norm_text(rel_path) not in {"", self._path.name}:
                    raise FileNotFoundError(rel_path)
                return self._path.read_bytes()

        source = _SingleFileSource(path)
        return {"resolved": resolved, "effective_path": effective_path}, OneCXmlParser().parse_all(source)

    source = DirectorySource(effective_path)
    return {"resolved": resolved, "effective_path": effective_path}, OneCXmlParser().parse_all(source)


def _db_object_payload(db_object: Any, payload_getter: Callable[[str], dict[str, Any]] | None) -> dict[str, Any]:
    guid = _norm_text(getattr(db_object, "guid", ""))
    payload: dict[str, Any] = {}
    raw_payload = getattr(db_object, "payload", None)
    if isinstance(raw_payload, dict):
        payload = dict(raw_payload)
    elif is_dataclass(raw_payload):
        payload = dict(asdict(raw_payload))
    if payload_getter is not None and guid:
        try:
            fresh = dict(payload_getter(guid) or {})
        except Exception:
            fresh = {}
        if fresh:
            payload = fresh
    for key in list(payload.keys()):
        if key in _IGNORED_PAYLOAD_KEYS:
            payload.pop(key, None)
    return payload


def _build_db_ref_indexes(db_objects: Sequence[Any], payload_getter: Callable[[str], dict[str, Any]] | None) -> tuple[dict[str, str], dict[str, str]]:
    refs_by_guid: dict[str, str] = {}
    guids_by_ref: dict[str, str] = {}
    for db_object in db_objects:
        if _norm_text(getattr(db_object, "kind", "")).lower() != "object":
            continue
        guid = _norm_text(getattr(db_object, "guid", ""))
        if not guid:
            continue
        payload = _db_object_payload(db_object, payload_getter)
        metadata_ref = _norm_text(payload.get("metadata_ref"))
        if not metadata_ref:
            continue
        refs_by_guid[guid] = metadata_ref
        guids_by_ref.setdefault(metadata_ref, guid)
    return refs_by_guid, guids_by_ref


def build_source_structure_compare_report(
    *,
    source_path: str,
    source_kind: str = "",
    db_objects: Sequence[Any],
    db_payload_getter: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_meta, source_objects = _load_source_objects(source_path, source_kind)
    resolved = source_meta["resolved"]
    effective_path = source_meta["effective_path"]

    source_by_guid: dict[str, dict[str, Any]] = {}
    source_rows: list[dict[str, Any]] = []
    for obj in source_objects:
        guid = _norm_text(getattr(obj, "uuid", ""))
        if not guid:
            continue
        row = {
            "guid": guid,
            "type": _source_type(obj),
            "name": _norm_text(getattr(obj, "name", "")),
            "title": _source_title(obj),
            "origin": _norm_text(getattr(obj, "origin_path", getattr(obj, "origin", ""))),
            "order": _norm_text(getattr(obj, "order", "")),
            "dbname_order": _norm_text(getattr(obj, "dbname_order", "")),
            "parent_guid": _norm_text(getattr(obj, "parent_guid", "")),
            "tree_path": _norm_text(getattr(obj, "tree_path", "")),
            "is_virtual": bool(getattr(obj, "is_virtual", False)),
            "virtual_reason": _norm_text(getattr(obj, "virtual_reason", "")),
            "payload": _normalize_payload(_source_payload(obj)),
        }
        source_rows.append(row)
        source_by_guid[guid] = row

    db_rows: list[dict[str, Any]] = []
    db_by_guid: dict[str, dict[str, Any]] = {}
    for obj in db_objects or []:
        guid = _norm_text(getattr(obj, "guid", ""))
        if not guid:
            continue
        payload = _normalize_payload(_db_object_payload(obj, db_payload_getter))
        row = {
            "guid": guid,
            "type": _norm_text(getattr(obj, "type", "")),
            "name": _norm_text(getattr(obj, "name", "")),
            "title": _norm_text(getattr(obj, "title", "")),
            "kind": _norm_text(getattr(obj, "kind", "")),
            "order": _norm_text(payload.get("order")),
            "parent_guid": _norm_text(getattr(obj, "parent_guid", "")),
            "is_virtual": bool(getattr(obj, "is_virtual", False)),
            "virtual_reason": _norm_text(getattr(obj, "virtual_reason", "")),
            "payload": payload,
        }
        db_rows.append(row)
        db_by_guid[guid] = row

    refs_by_guid, guids_by_ref = _build_db_ref_indexes(db_objects, db_payload_getter)

    items: list[dict[str, Any]] = []
    matched = 0
    mismatched = 0

    def _item_from_rows(source_row: dict[str, Any], db_row: dict[str, Any] | None) -> dict[str, Any]:
        source_payload = dict(source_row.get("payload") or {})
        db_payload = dict(db_row.get("payload") or {}) if db_row else {}
        diffs: dict[str, dict[str, Any]] = {}

        def add_diff(field: str, source_value: Any, db_value: Any) -> None:
            if _normalize_value(source_value) == _normalize_value(db_value):
                return
            diffs[field] = {"source": _normalize_value(source_value), "db": _normalize_value(db_value)}

        add_diff("type", source_row.get("type"), (db_row or {}).get("type"))
        add_diff("name", source_row.get("name"), (db_row or {}).get("name"))
        add_diff("title", source_row.get("title"), (db_row or {}).get("title"))

        source_type = _norm_text(source_row.get("type")).lower()
        source_is_virtual = bool(source_row.get("is_virtual"))
        if source_type == "subsystem":
            source_content_refs = _unique_values(source_payload.get("content_refs") or [])
            source_child_subsystems = _unique_values(source_payload.get("child_subsystems") or [])
            source_parent_guid = _norm_text(source_row.get("parent_guid"))
            source_tree_path = _norm_text(source_row.get("tree_path"))
            source_order = _norm_text(source_row.get("order"))
            source_dbname_order = _norm_text(source_row.get("dbname_order"))
            source_is_virtual_text = "true" if source_is_virtual else "false"
            source_virtual_reason = _norm_text(source_row.get("virtual_reason"))
            db_content_refs = _unique_values(db_payload.get("content_refs") or [])
            db_child_subsystems = _unique_values(db_payload.get("child_subsystems") or [])
            db_objects_list = _unique_values(db_payload.get("objects") or [])
            db_order = _norm_text(db_row.get("order") if db_row else db_payload.get("order"))
            db_parent_guid = _norm_text(db_row.get("parent_guid") if db_row else "")
            db_tree_path = _norm_text(db_row.get("tree_path") if db_row else "")
            db_virtual_reason = _norm_text(db_row.get("virtual_reason") if db_row else "")
            resolved_objects = [
                guids_by_ref.get(ref, "")
                for ref in source_content_refs
                if not ref.startswith("FunctionalOption.") and not ref.startswith("FunctionalOptionsParameter.")
            ]
            resolved_objects = [guid for guid in resolved_objects if guid]
            unresolved_refs = [
                ref for ref in source_content_refs
                if ref not in guids_by_ref and not ref.startswith("FunctionalOption.") and not ref.startswith("FunctionalOptionsParameter.")
            ]

            add_diff("content_refs", source_content_refs, db_content_refs)
            add_diff("child_subsystems", source_child_subsystems, db_child_subsystems)
            add_diff("objects", resolved_objects, db_objects_list)
            add_diff("order", source_order, db_order)
            add_diff("dbname_order", source_dbname_order, db_order)
            add_diff("parent_guid", source_parent_guid, db_parent_guid)
            add_diff("tree_path", source_tree_path, db_tree_path)
            add_diff("is_virtual", source_is_virtual_text, "true" if bool(db_row and db_row.get("is_virtual")) else "false")
            if source_virtual_reason:
                add_diff("virtual_reason", source_virtual_reason, db_virtual_reason)

            if unresolved_refs:
                diffs["unresolved_content_refs"] = {"source": unresolved_refs, "db": []}
            if db_content_refs and not source_content_refs:
                diffs.setdefault("content_refs", {"source": [], "db": db_content_refs})

        elif source_payload and db_payload:
            for key in sorted(set(source_payload) & set(db_payload)):
                if key in {"content_refs", "child_subsystems"}:
                    continue
                source_value = source_payload.get(key)
                db_value = db_payload.get(key)
                if _normalize_value(source_value) != _normalize_value(db_value):
                    diffs[key] = {"source": _normalize_value(source_value), "db": _normalize_value(db_value)}

        has_mismatch = bool(diffs)
        if db_row is None:
            status = "missing_in_db"
        elif has_mismatch:
            status = "mismatch"
            nonlocal_mismatched[0] += 1
        else:
            status = "matched"
            nonlocal_matched[0] += 1

        item = {
            "guid": source_row["guid"],
            "type": source_row["type"],
            "name": source_row["name"],
            "title": source_row["title"],
            "is_virtual": source_is_virtual,
            "source": source_row,
            "db": db_row,
            "status": status,
            "has_mismatch": has_mismatch or db_row is None,
        }
        if diffs:
            item["diffs"] = diffs
        return item

    nonlocal_matched = [0]
    nonlocal_mismatched = [0]

    for source_row in source_rows:
        db_row = db_by_guid.get(source_row["guid"])
        item = _item_from_rows(source_row, db_row)
        items.append(item)

    source_guids = set(source_by_guid.keys())
    for db_row in db_rows:
        if db_row["guid"] in source_guids:
            continue
        items.append(
            {
                "guid": db_row["guid"],
                "type": db_row["type"],
                "name": db_row["name"],
                "title": db_row["title"],
                "source": None,
                "db": db_row,
                "status": "extra_in_db",
                "has_mismatch": True,
                "diffs": {"missing_in_source": {"source": [], "db": [db_row["guid"]]}},
            }
        )
        nonlocal_mismatched[0] += 1

    def _missing_parent_links(rows: Sequence[dict[str, Any]], known_guids: set[str]) -> int:
        count = 0
        for row in rows:
            if _norm_text(row.get("type")).lower() != "subsystem":
                continue
            parent_guid = _norm_text(row.get("parent_guid"))
            if not parent_guid:
                continue
            if parent_guid not in known_guids:
                count += 1
        return count

    source_subsystems = sum(1 for row in source_rows if _norm_text(row.get("type")).lower() == "subsystem")
    db_subsystems = sum(1 for row in db_rows if _norm_text(row.get("type")).lower() == "subsystem")
    source_virtual_subsystems = sum(1 for row in source_rows if _norm_text(row.get("type")).lower() == "subsystem" and bool(row.get("is_virtual")))
    db_virtual_subsystems = sum(1 for row in db_rows if _norm_text(row.get("type")).lower() == "subsystem" and bool(row.get("is_virtual")))
    source_real_subsystems = source_subsystems - source_virtual_subsystems
    db_real_subsystems = db_subsystems - db_virtual_subsystems
    source_real_rows = sum(1 for row in source_rows if not bool(row.get("is_virtual")))
    db_real_rows = sum(1 for row in db_rows if not bool(row.get("is_virtual")))
    source_missing_parent_links = _missing_parent_links(source_rows, set(source_by_guid.keys()))
    db_missing_parent_links = _missing_parent_links(db_rows, set(db_by_guid.keys()))
    source_child_index = _build_child_index(source_rows)
    db_child_index = _build_child_index(db_rows)
    parent_child_mismatches: list[dict[str, Any]] = []
    for parent_guid in sorted(set(source_child_index) | set(db_child_index)):
        source_children = source_child_index.get(parent_guid, [])
        db_children = db_child_index.get(parent_guid, [])
        source_child_guids = [str(row.get("guid") or "") for row in source_children if str(row.get("guid") or "").strip()]
        db_child_guids = [str(row.get("guid") or "") for row in db_children if str(row.get("guid") or "").strip()]
        if source_child_guids == db_child_guids:
            continue
        source_child_names = [str(row.get("name") or row.get("title") or row.get("guid") or "") for row in source_children]
        db_child_names = [str(row.get("name") or row.get("title") or row.get("guid") or "") for row in db_children]
        source_child_titles = [str(row.get("title") or row.get("name") or row.get("guid") or "") for row in source_children]
        db_child_titles = [str(row.get("title") or row.get("name") or row.get("guid") or "") for row in db_children]
        parent_child_mismatches.append(
            {
                "parent_guid": parent_guid,
                "source_count": len(source_child_guids),
                "db_count": len(db_child_guids),
                "source_children": source_child_guids,
                "db_children": db_child_guids,
                "source_child_names": source_child_names,
                "db_child_names": db_child_names,
                "source_child_titles": source_child_titles,
                "db_child_titles": db_child_titles,
                "missing_in_db": [guid for guid in source_child_guids if guid not in db_child_guids],
                "missing_in_source": [guid for guid in db_child_guids if guid not in source_child_guids],
            }
        )
    flattened_subtrees: list[dict[str, Any]] = []
    for parent_guid in sorted(source_child_index.keys()):
        source_parent = source_by_guid.get(parent_guid)
        source_children = source_child_index.get(parent_guid, [])
        relocated_children: list[dict[str, Any]] = []
        for child_row in source_children:
            child_guid = _norm_text(child_row.get("guid"))
            if not child_guid:
                continue
            child_db_row = db_by_guid.get(child_guid)
            if child_db_row is None:
                continue
            child_db_parent = _norm_text(child_db_row.get("parent_guid"))
            if child_db_parent == parent_guid:
                continue
            relocated_children.append(
                {
                    "guid": child_guid,
                    "title": _title_or_name(child_row),
                    "db_parent_guid": child_db_parent,
                    "db_parent_title": _title_or_name(db_by_guid.get(child_db_parent, {})) if child_db_parent else "",
                    "source_parent_guid": parent_guid,
                    "source_parent_title": _title_or_name(source_parent or {}),
                }
            )
        parent_missing_in_db = source_parent is not None and parent_guid not in db_by_guid
        if relocated_children or parent_missing_in_db:
            flattened_subtrees.append(
                {
                    "parent_guid": parent_guid,
                    "parent_title": _title_or_name(source_parent or {}),
                    "tree_path": _norm_text((source_parent or {}).get("tree_path", "")),
                    "source_child_count": len(source_children),
                    "relocated_child_count": len(relocated_children),
                    "source_children": [str(row.get("guid") or "") for row in source_children if str(row.get("guid") or "").strip()],
                    "source_child_names": [str(row.get("name") or row.get("guid") or "") for row in source_children if str(row.get("guid") or "").strip()],
                    "relocated_children": relocated_children,
                }
            )

    return {
        "source": {
            "path": effective_path,
            "requested_kind": _norm_text(resolved.requested_kind),
            "detected_kind": _norm_text(resolved.detected_kind),
            "semantic_kind": _norm_text(resolved.semantic_kind),
        },
        "summary": {
            "source_count": len(source_rows),
            "db_count": len(db_rows),
            "source_subsystems": source_subsystems,
            "db_subsystems": db_subsystems,
            "source_real_subsystems": source_real_subsystems,
            "db_real_subsystems": db_real_subsystems,
            "source_virtual_subsystems": source_virtual_subsystems,
            "db_virtual_subsystems": db_virtual_subsystems,
            "source_real_rows": source_real_rows,
            "db_real_rows": db_real_rows,
            "matched": nonlocal_matched[0],
            "mismatched": nonlocal_mismatched[0],
            "missing_in_db": sum(1 for item in items if item["status"] == "missing_in_db"),
            "extra_in_db": sum(1 for item in items if item["status"] == "extra_in_db"),
            "coverage_ratio": round(nonlocal_matched[0] / len(source_rows), 3) if source_rows else 0.0,
            "coverage_ratio_real": round(nonlocal_matched[0] / source_real_rows, 3) if source_real_rows else 0.0,
            "missing_parent_links_source": source_missing_parent_links,
            "missing_parent_links_db": db_missing_parent_links,
            "db_missing_parent_links": db_missing_parent_links,
            "source_missing_parent_links": source_missing_parent_links,
            "parent_child_mismatch_count": len(parent_child_mismatches),
            "flattened_subtree_count": len(flattened_subtrees),
        },
        "items": items,
        "parent_child_mismatches": parent_child_mismatches,
        "flattened_subtrees": flattened_subtrees,
        "db_ref_index": {
            "refs_by_guid": refs_by_guid,
            "guids_by_ref": guids_by_ref,
        },
    }


__all__ = ["build_source_structure_compare_report"]
