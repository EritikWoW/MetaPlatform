"""Canonical manifest persistence layer.

All manifest storage, migration, batch update and payload externalization logic
must live here. ``src.configurator.manifest_io`` is a compatibility shim only
and must not grow its own behavior.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.mpdb.mpdb import ASSETS_TABLE, Mpdb
from src.core.object_policies import (
    SECTIONS,
    get_object_policy,
    ordered_object_sections,
    section_kind,
    should_create_object_folders,
)
from src.platform.logging_setup import get_logger

from ..manifest_schema import MANIFEST_TABLE, ManifestObject, NodeKind, ObjectType


MANIFEST_PAYLOAD_PREFIX = "manifest-payload/"
_EXTERNALIZED_PAYLOAD_KEYS = {
    "attributes",
    "command_interface",
    "content_refs",
    "dimensions",
    "dump_info_children",
    "enum_values",
    "form_model",
    "form_module",
    "help_contents",
    "layout_model",
    "metadata_structure",
    "objects",
    "requisites",
    "restriction_templates",
    "resources",
    "rights",
    "storage_profile",
    "tabular_parts",
}

# Payload collections required to build the Configurator metadata tree. They
# are stored as independent assets, so runtime can load this index without
# hydrating forms, modules, layouts and other heavy object payloads.
SCHEMA_TREE_PAYLOAD_KEYS = (
    "attributes",
    "dimensions",
    "enum_values",
    "requisites",
    "resources",
    "tabular_parts",
)


_log = get_logger("configurator.manifest_io")


# ------------------------------------------------------------
# GUID helpers
# ------------------------------------------------------------

# Namespace for deterministic UUIDv5 generation of SYSTEM/seed objects.
# Do not change once released, otherwise system GUIDs will drift.
_SYS_GUID_NS_HEX = "1f8e4b8c2c6f4a3c9a2a3b7c9d2a1b10"  # 16 bytes


def _fmt_uuid(b: bytes) -> str:
    """Format 16-byte UUID to canonical string."""
    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _new_guid() -> str:
    """UUIDv4 without stdlib uuid (project has 'platform' package that shadows stdlib)."""
    b = bytearray(os.urandom(16))
    b[6] = (b[6] & 0x0F) | 0x40  # version 4
    b[8] = (b[8] & 0x3F) | 0x80  # variant
    return _fmt_uuid(bytes(b))


def _sys_guid(key: str) -> str:
    """Deterministic UUIDv5 (SHA1) without stdlib uuid."""
    ns = bytes.fromhex(_SYS_GUID_NS_HEX)
    name = (key or "").encode("utf-8")
    digest = hashlib.sha1(ns + name).digest()[:16]
    b = bytearray(digest)
    b[6] = (b[6] & 0x0F) | 0x50  # version 5
    b[8] = (b[8] & 0x3F) | 0x80
    return _fmt_uuid(bytes(b))



def sys_object_folder_guid(*, parent_guid: str, section_key: str) -> str:
    """Return deterministic GUID for a system folder inside an object.

    The folder GUID is stable across rebuilds and is derived from
    (parent_guid, section_key). This is used by UI and storage integration.
    """
    return _sys_guid(f"objfolder:{(parent_guid or '').strip()}:{(section_key or '').strip()}")

# ------------------------------------------------------------
# Table lifecycle / migration
# ------------------------------------------------------------


def ensure_manifest_table(db: Mpdb) -> None:
    """Ensure manifest table exists with GUID-based schema.

    If an old UID-based manifest exists, migrate it in-place to GUID schema.
    """

    # If table exists, detect schema version.
    try:
        t = db.table(MANIFEST_TABLE)
        schema = getattr(db, "_meta", {}).get("tables", {}).get(MANIFEST_TABLE, {}).get("schema", {})  # type: ignore[attr-defined]
        if isinstance(schema, dict) and "guid" in schema:
            return
        # Old schema (uid-based) -> migrate.
        _migrate_uid_manifest_to_guid(db)
        return
    except Exception:
        pass

    schema: Dict[str, Dict[str, Any]] = {
        "guid": {"type": "str", "unique": True, "indexed": True},
        "type": {"type": "str"},
        "name": {"type": "str"},
        "title": {"type": "str"},
        "kind": {"type": "str"},
        "parent_guid": {"type": "str", "indexed": True},
        "payload": {"type": "json"},
    }
    db.create_table(MANIFEST_TABLE, schema=schema)


def ensure_manifest(
    db: Mpdb,
    seed_defaults: bool = False,
    *,
    seed_defaults_if_empty: bool = False,
    **_kwargs,
) -> None:
    """Ensure manifest exists; optionally seed default SYSTEM structure.

    Compatibility notes:
      - seed_defaults: always run seed upsert logic (idempotent).
      - seed_defaults_if_empty: run seed only when manifest is empty.
      - **_kwargs: ignore unknown future/legacy kwargs to avoid crashes.
    """
    ensure_manifest_table(db)

    # If requested, seed only when manifest is empty.
    if seed_defaults_if_empty:
        try:
            if list_objects(db):
                return
        except Exception:
            # If we can't reliably determine emptiness, don't seed.
            return
        seed_defaults = True

    if not seed_defaults:
        _ensure_configuration_root_module_refs(db)
        return

    # Важно: seed должен быть ИДЕМПОТЕНТНЫМ.
    # Ранее логика "if list_objects(db): return" приводила к тому, что базы,
    # созданные на старой версии, никогда не получали новые системные ветки.
    _seed_system_tree_upsert(db)
    _ensure_guids(db)
    _ensure_default_folders_for_objects(db)
    _ensure_module_stubs_for_objects(db)
    _ensure_configuration_root_module_refs(db)


# ------------------------------------------------------------
# Seed structure (SYSTEM)
# ------------------------------------------------------------


def _seed_system_tree_upsert(db: Mpdb) -> None:
    """Create/ensure root "Конфигурация" and standard branches as SYSTEM/PROTECTED.

    Создаёт недостающие системные узлы, не трогая существующие.
    GUID у системных узлов детерминированный, поэтому мы можем безопасно
    "upsert" без миграций.
    """

    try:
        rows = db.table(MANIFEST_TABLE).select() or []
    except Exception:
        rows = []
    existing: set[str] = {str(r.get("guid") or "") for r in rows}

    root_guid = _sys_guid("root:configuration")
    _insert_raw_if_missing(
        db,
        {
            "guid": root_guid,
            "type": "configuration",
            "name": "Configuration",
            "title": "Конфигурация",
            "kind": "root",
            "parent_guid": "",
            "payload": {"system": True, "protected": True, "seed": True, "order": 0},
        },
    )

    def add_group(type_code: str, title: str, order: int) -> str:
        g = _sys_guid(f"group:{type_code}")
        _insert_raw_if_missing(
            db,
            {
                "guid": g,
                "type": type_code,
                "name": type_code,
                "title": title,
                "kind": "group",
                "parent_guid": root_guid,
                "payload": {
                    "system": True,
                    "protected": True,
                    "seed": True,
                    "menu": "add_only",
                    "order": order,
                },
            },
        )
        return g

    # Порядок как в 1С (по скрину)
    common = add_group("common", "Общие", 10)
    add_group("constants", "Константы", 20)
    add_group("catalog", "Справочники", 30)
    add_group("document", "Документы", 40)
    add_group("journal", "Журналы документов", 50)
    add_group("enumeration", "Перечисления", 60)
    add_group("report", "Отчеты", 70)
    add_group("data_processor", "Обработки", 80)
    add_group("chart_of_characteristic_types", "Планы видов характеристик", 90)
    add_group("chart_of_accounts", "Планы счетов", 100)
    add_group("chart_of_calculation_types", "Планы видов расчета", 110)
    add_group("register_info", "Регистры сведений", 120)
    add_group("register_accum", "Регистры накопления", 130)
    add_group("register_accounting", "Регистры бухгалтерии", 140)
    add_group("register_calc", "Регистры расчета", 150)
    add_group("business_process", "Бизнес-процессы", 160)
    add_group("task", "Задачи", 170)
    add_group("external_sources", "Внешние источники данных", 180)

    # Common default folders (like 1C)
    for idx, (key, title) in enumerate([
        ("subsystems", "Подсистемы"),
        ("common_modules", "Общие модули"),
        ("session_params", "Параметры сеанса"),
        ("roles", "Роли"),
        ("common_attributes", "Общие реквизиты"),
        ("exchange_plans", "Планы обмена"),
        ("selection_criteria", "Критерии отбора"),
        ("event_subscriptions", "Подписки на события"),
        ("scheduled_jobs", "Регламентные задания"),
        ("bots", "Боты"),
        ("functional_options", "Функциональные опции"),
        ("functional_options_params", "Параметры функциональных опций"),
        ("defined_types", "Определяемые типы"),
        ("settings_storages", "Хранилища настроек"),
        ("common_commands", "Общие команды"),
        ("command_groups", "Группы команд"),
        ("common_forms", "Общие формы"),
        ("common_layouts", "Общие макеты"),
        ("common_pictures", "Общие картинки"),
        ("xdto_packages", "XDTO-пакеты"),
        ("web_services", "Web-сервисы"),
        ("http_services", "HTTP-сервисы"),
        ("ws_links", "WS-ссылки"),
        ("websocket_clients", "WebSocket-клиенты"),
        ("integration_services", "Сервисы интеграции"),
        ("style_elements", "Элементы стиля"),
        ("styles", "Стили"),
        ("languages", "Языки"),
        ("document_numerators", "Нумераторы документов"),
        ("sequences", "Последовательности"),
    ]):
        _insert_raw_if_missing(
            db,
            {
                "guid": _sys_guid(f"common:{key}"),
                "type": "common",
                "name": key,
                "title": title,
                "kind": "folder",
                "parent_guid": common,
                "payload": {
                    "system": True,
                    "protected": True,
                    "seed": True,
                    "menu": "add_only",
                    "order": 1000 + idx,
                },
            },
        )

def _insert_raw_if_missing(db: Mpdb, row: Dict[str, Any]) -> None:
    guid = str(row.get("guid") or "").strip()
    if not guid:
        return
    table = db.table(MANIFEST_TABLE)
    try:
        if table.select(where={"guid": guid}):
            return
    except Exception:
        pass
    try:
        table.insert(row)
    except Exception as e:
        try:
            if table.select(where={"guid": guid}):
                return
        except Exception:
            pass
        raise RuntimeError(f"manifest seed insert failed: {e}") from e

def _insert_raw(db: Mpdb, row: Dict[str, Any]) -> None:
    """
    Строгая вставка строки в manifest.
    В отличие от _insert_raw_if_missing — должна падать при ошибке,
    чтобы UI показал реальную проблему.
    """
    try:
        db.table(MANIFEST_TABLE).insert(row)
    except Exception as e:
        # Делаем ошибку читаемой, чтобы она показалась в UI
        raise RuntimeError(f"manifest insert failed: {e}") from e


def _manifest_payload_asset_key(*, guid: str, key: str) -> str:
    guid = str(guid or "").strip()
    key = str(key or "").strip()
    return f"{MANIFEST_PAYLOAD_PREFIX}{guid}/{key}.json"


def _put_manifest_payload_asset(db: Mpdb, *, guid: str, key: str, value: Any) -> str:
    asset_key = _manifest_payload_asset_key(guid=guid, key=key)
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    db.put_asset(asset_key, data, mime="application/json")
    return asset_key


def _put_manifest_payload_asset_ref(db: Mpdb, *, ref: str, value: Any) -> None:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    db.put_asset(ref, data, mime="application/json")


def _load_manifest_payload_asset(db: Mpdb, *, ref: str) -> Any:
    data, _mime = db.get_asset(ref)
    return json.loads(data.decode("utf-8"))


def _prefetch_manifest_payload_assets(
    db: Mpdb,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    refs: set[str] = set()
    for row in rows:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        for key in sorted(_EXTERNALIZED_PAYLOAD_KEYS):
            if key in payload:
                continue
            ref = str(payload.get(f"{key}_ref") or "").strip()
            if ref:
                refs.add(ref)
    if not refs:
        return {}

    prefetched: Dict[str, Any] = {}
    try:
        asset_rows = db.table(ASSETS_TABLE).select() or []
        locators: Dict[str, Tuple[int, int]] = {}
        for row in asset_rows:
            key = str(row.get("key") or "").strip()
            if key not in refs:
                continue
            first_page = int(row.get("first_page") or 0)
            size = int(row.get("size") or 0)
            if first_page > 0:
                locators[key] = (first_page, size)
        read_blob_chain = getattr(db, "_read_blob_chain", None)
        if callable(read_blob_chain):
            for ref, (first_page, size) in locators.items():
                try:
                    data = read_blob_chain(first_page, expected_size=size)
                    prefetched[ref] = json.loads(data.decode("utf-8"))
                except Exception:
                    continue
    except Exception:
        prefetched = {}

    missing = sorted(ref for ref in refs if ref not in prefetched)
    for ref in missing:
        try:
            prefetched[ref] = _load_manifest_payload_asset(db, ref=ref)
        except Exception:
            continue
    return prefetched


def build_manifest_schema_index(
    db: Mpdb,
    rows: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Load only schema collections required by the Configurator tree.

    A raw manifest scan is intentional here: slim/cache rows do not contain
    external payload refs.  Only refs that are actually stored in manifest
    are read afterwards.  Never probe synthesized asset names because a miss
    on historical MPDB asset indexes falls back to an expensive table scan.
    """

    raw_rows = list_object_rows(db)
    requested_guids = {
        str(row.get("guid") or "").strip()
        for row in list(rows or [])
        if isinstance(row, dict) and str(row.get("guid") or "").strip()
    }
    source_rows = [
        row for row in raw_rows
        if not requested_guids or str(row.get("guid") or "").strip() in requested_guids
    ]
    row_order: List[str] = []
    payloads_by_guid: Dict[str, Dict[str, Any]] = {}
    valid_guids: set[str] = set()

    for row in source_rows:
        if not isinstance(row, dict) or str(row.get("kind") or "").strip().lower() != "object":
            continue
        guid = str(row.get("guid") or "").strip()
        if not guid:
            continue
        valid_guids.add(guid)
        row_order.append(guid)
        source_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        inline = {
            key: source_payload[key]
            for key in SCHEMA_TREE_PAYLOAD_KEYS
            if isinstance(source_payload.get(key), list)
        }
        if inline:
            payloads_by_guid[guid] = inline

    if not valid_guids:
        return []

    section_payload_keys = {
        "attributes": ("requisites", "attributes"),
        "dimensions": ("dimensions",),
        "resources": ("resources",),
        "tabular_parts": ("tabular_parts",),
        "values": ("enum_values",),
    }
    for row in source_rows:
        if not isinstance(row, dict) or str(row.get("kind") or "").strip().lower() != "object":
            continue
        guid = str(row.get("guid") or "").strip()
        if guid not in valid_guids:
            continue
        source_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        payload_keys: set[str] = set()
        for section in ordered_object_sections(str(row.get("type") or ""), source_payload):
            payload_keys.update(section_payload_keys.get(str(section or ""), ()))
        for payload_key in sorted(payload_keys):
            if payload_key in payloads_by_guid.get(guid, {}):
                continue
            ref = str(source_payload.get(f"{payload_key}_ref") or "").strip()
            if not ref:
                continue
            try:
                value = _load_manifest_payload_asset(db, ref=ref)
            except Exception:
                continue
            if isinstance(value, list):
                payloads_by_guid.setdefault(guid, {})[payload_key] = value

    return [
        {"guid": guid, "payload": payloads_by_guid[guid]}
        for guid in row_order
        if guid in payloads_by_guid
    ]


def _normalize_manifest_payload(db: Mpdb, *, guid: str, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    normalized = dict(payload or {})
    for key in sorted(_EXTERNALIZED_PAYLOAD_KEYS):
        ref_key = f"{key}_ref"
        if key not in normalized:
            continue
        if ref_key in normalized and not normalized.get(key):
            normalized.pop(key, None)
            continue
        try:
            normalized[ref_key] = _put_manifest_payload_asset(
                db,
                guid=guid,
                key=key,
                value=normalized[key],
            )
            normalized.pop(key, None)
        except Exception:
            continue
    return normalized


def _hydrate_manifest_payload(
    db: Mpdb,
    payload: Optional[Dict[str, Any]],
    *,
    prefetched_assets: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    hydrated = dict(payload or {})
    for key in sorted(_EXTERNALIZED_PAYLOAD_KEYS):
        if key in hydrated:
            continue
        ref = str(hydrated.get(f"{key}_ref") or "").strip()
        if not ref:
            continue
        try:
            if prefetched_assets is not None and ref in prefetched_assets:
                hydrated[key] = prefetched_assets[ref]
            else:
                hydrated[key] = _load_manifest_payload_asset(db, ref=ref)
        except Exception:
            continue
    return hydrated


def _normalize_manifest_payload_bulk(
    *,
    guid: str,
    payload: Optional[Dict[str, Any]],
    asset_batch: Dict[str, Tuple[bytes, str]],
) -> Dict[str, Any]:
    normalized = dict(payload or {})
    for key in sorted(_EXTERNALIZED_PAYLOAD_KEYS):
        ref_key = f"{key}_ref"
        if key not in normalized:
            continue
        if ref_key in normalized and not normalized.get(key):
            normalized.pop(key, None)
            continue
        ref = str(normalized.get(ref_key) or "").strip() or _manifest_payload_asset_key(guid=guid, key=key)
        data = json.dumps(normalized[key], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        asset_batch[ref] = (data, "application/json")
        normalized[ref_key] = ref
        normalized.pop(key, None)
    return normalized


def _manifest_row_from_object(
    db: Mpdb,
    obj: ManifestObject | Dict[str, Any],
    *,
    bulk_asset_batch: Optional[Dict[str, Tuple[bytes, str]]] = None,
) -> Dict[str, Any]:
    if isinstance(obj, ManifestObject):
        guid = str(obj.guid or "").strip()
        obj_type = str(obj.type or "common")
        name = str(obj.name or "")
        title = str(obj.title or "")
        kind = str(obj.kind or "object")
        parent_guid = str(obj.parent_guid or "")
        payload = obj.payload if isinstance(obj.payload, dict) else {}
    else:
        guid = str(obj.get("guid") or "").strip()
        obj_type = str(obj.get("type") or "common")
        name = str(obj.get("name") or "")
        title = str(obj.get("title") or "")
        kind = str(obj.get("kind") or "object")
        parent_guid = str(obj.get("parent_guid") or "")
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    normalized_payload = (
        _normalize_manifest_payload_bulk(guid=guid, payload=payload, asset_batch=bulk_asset_batch)
        if bulk_asset_batch is not None
        else _normalize_manifest_payload(db, guid=guid, payload=payload)
    )
    return {
        "guid": guid,
        "type": obj_type,
        "name": name,
        "title": title,
        "kind": kind,
        "parent_guid": parent_guid,
        "payload": normalized_payload,
    }


def make_object(
    *,
    obj_type: ObjectType,
    name: str,
    title: str,
    parent_guid: str,
    payload: Optional[Dict[str, Any]] = None,
    kind: NodeKind = "object",
    guid: str | None = None,
) -> ManifestObject:
    return ManifestObject(
        guid=str(guid or _new_guid()),
        type=obj_type,
        name=str(name or ""),
        title=str(title or ""),
        kind=kind,
        parent_guid=str(parent_guid or ""),
        payload=dict(payload or {}),
    )

# ------------------------------------------------------------
# CRUD
# ------------------------------------------------------------


def _manifest_sort_key_from_row(row: Dict[str, Any]) -> Tuple[int, str, int, str, str]:
    kind_order = {"root": 0, "group": 1, "folder": 2, "object": 3}
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    try:
        order = int(payload.get("order", 1000))
    except Exception:
        order = 1000
    return (
        kind_order.get(str(row.get("kind") or "object"), 9),
        str(row.get("parent_guid") or ""),
        order,
        str(row.get("title") or "").lower(),
        str(row.get("name") or "").lower(),
    )


def _manifest_rows_to_objects(
    db: Mpdb,
    rows: List[Dict[str, Any]],
    *,
    hydrate_payload: bool = True,
) -> List[ManifestObject]:
    prefetched_assets = _prefetch_manifest_payload_assets(db, rows) if hydrate_payload else {}
    out: List[ManifestObject] = []
    for r in rows:
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        if hydrate_payload:
            payload = _hydrate_manifest_payload(db, payload, prefetched_assets=prefetched_assets)
        out.append(
            ManifestObject(
                guid=str(r.get("guid") or ""),
                type=str(r.get("type") or "common"),
                name=str(r.get("name") or ""),
                title=str(r.get("title") or ""),
                kind=str(r.get("kind") or "object"),
                parent_guid=str(r.get("parent_guid") or ""),
                payload=payload,
            )
        )
    return out


def list_object_rows(db: Mpdb) -> List[Dict[str, Any]]:
    """Read manifest rows without hydrating externalized payload assets."""
    try:
        rows = db.table(MANIFEST_TABLE).select() or []
    except Exception as exc:
        # Historical large imports can leave a stale ``data_pages`` scan list
        # while the primary rowid locator index remains complete.  Returning
        # an empty manifest here is data loss at the API boundary: runtime then
        # overwrites a valid structure cache with ``object_count=0``.  Recover
        # point-by-point through the independent rowid index instead.
        table = db.table(MANIFEST_TABLE)
        try:
            table_info = db._meta.get("tables", {}).get(MANIFEST_TABLE, {})  # noqa: SLF001
            next_rowid = int(table_info.get("next_rowid") or 1)
        except Exception:
            next_rowid = 1
        rows = []
        failed = 0
        for rowid in range(1, max(1, next_rowid)):
            try:
                recovered = table.select(where={"rowid": rowid}) or []
            except Exception:
                failed += 1
                continue
            rows.extend(item for item in recovered if isinstance(item, dict))
        _log.warning(
            "manifest full scan failed; rowid recovery returned %s rows (%s failed): %s",
            len(rows),
            failed,
            exc,
        )
        if not rows and next_rowid > 1:
            raise RuntimeError(f"Manifest scan and rowid recovery failed: {exc}") from exc
    out = [dict(r) for r in rows if isinstance(r, dict)]
    out.sort(key=_manifest_sort_key_from_row)
    return out


def list_objects(db: Mpdb, *, hydrate_payload: bool = True) -> List[ManifestObject]:
    """Read all objects from manifest."""
    rows = list_object_rows(db)
    return _manifest_rows_to_objects(db, rows, hydrate_payload=hydrate_payload)


def add_objects_bulk(
    db: Mpdb,
    objects: List[ManifestObject],
    *,
    progress: Optional[Callable[[int, int, str], None]] = None,
    update_existing: bool = False,
) -> int:
    ensure_manifest_table(db)
    if not objects:
        return 0

    def _emit_progress(current: int, total: int, message: str) -> None:
        if progress is None:
            return
        try:
            progress(int(current), int(total), str(message or ""))
        except Exception:
            pass

    table = db.table(MANIFEST_TABLE)
    existing_rows = [dict(row) for row in (table.select() or []) if isinstance(row, dict)]
    existing_by_guid = {
        str(row.get("guid") or ""): row
        for row in existing_rows
        if str(row.get("guid") or "")
    }
    prepared: List[Dict[str, Any]] = []
    replacements: Dict[str, Dict[str, Any]] = {}
    asset_batch: Dict[str, Tuple[bytes, str]] = {}
    seen: set[str] = set()
    for obj in objects:
        guid = str(getattr(obj, "guid", "") or "").strip()
        if not guid or guid in seen:
            continue
        seen.add(guid)
        row = _manifest_row_from_object(db, obj, bulk_asset_batch=asset_batch)
        if guid in existing_by_guid:
            if update_existing and row != existing_by_guid[guid]:
                replacements[guid] = row
            continue
        prepared.append(row)

    if not prepared and not replacements:
        return 0

    total_work = len(prepared) + len(replacements) + len(asset_batch)
    done_work = 0

    if asset_batch:
        db.put_assets_bulk(
            [(key, data, mime) for key, (data, mime) in asset_batch.items()],
            progress=lambda current, total: _emit_progress(
                current,
                total_work,
                "Import manifest: Writing manifest payload assets",
            ),
        )
        done_work += len(asset_batch)

    if replacements:
        rebuilt = [replacements.get(str(row.get("guid") or ""), row) for row in existing_rows]
        rebuilt.extend(prepared)
        _rebuild_manifest(db, rebuilt)
        _emit_progress(total_work, total_work, "Import manifest: Updating manifest rows")
        return len(prepared) + len(replacements)

    with db.transaction() as tx:
        row_total = len(prepared)
        for index, row in enumerate(prepared, start=1):
            table.insert_tx(tx, row, set_meta=False)
            if index == row_total or index % 250 == 0:
                _emit_progress(
                    done_work + index,
                    total_work,
                    "Import manifest: Writing manifest rows",
                )
        tx.set_meta(db._meta)
    return len(prepared)


def add_objects_bulk_with_system_children(db: Mpdb, objects: List[ManifestObject]) -> int:
    if not objects:
        return 0

    table = db.table(MANIFEST_TABLE)
    existing = {
        str(row.get("guid") or "")
        for row in (table.select() or [])
        if str(row.get("guid") or "")
    }
    seen = set(existing)
    expanded: List[ManifestObject] = list(objects)

    for obj in objects:
        guid = str(getattr(obj, "guid", "") or "").strip()
        if guid:
            seen.add(guid)

    for obj in objects:
        if str(getattr(obj, "kind", "") or "") != "object":
            continue
        folders = _default_object_folder_objects(obj)
        modules_folder_guid = _sys_guid(f"objfolder:{obj.guid}:modules")
        for folder in folders:
            if folder.guid and folder.guid not in seen:
                expanded.append(folder)
                seen.add(folder.guid)
        if any(folder.guid == modules_folder_guid for folder in folders):
            for stub in _module_stub_objects(obj):
                if stub.guid and stub.guid not in seen:
                    expanded.append(stub)
                    seen.add(stub.guid)

    return add_objects_bulk(db, expanded)


def add_object(
    db: Mpdb,
    obj_type: ObjectType,
    name: str,
    title: str,
    parent_guid: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    kind: NodeKind = "object",
) -> ManifestObject:
    mo = make_object(
        obj_type=obj_type,
        name=name,
        title=title,
        parent_guid=parent_guid,
        payload=payload,
        kind=kind,
    )
    _insert_raw(db, _manifest_row_from_object(db, mo))

    # Автосоздание системных подузлов объекта (как в 1С)
    if kind == "object":
        _create_default_object_folders(db, mo)
        # Immediately create module stubs so they appear in the editor
        try:
            _ensure_module_stubs_for_single_object(db, mo)
        except Exception:
            pass
    return mo


def bulk_update_payloads(db: Mpdb, payloads_by_guid: Dict[str, Dict[str, Any]]) -> int:
    if not payloads_by_guid:
        return 0

    rows = db.table(MANIFEST_TABLE).select() or []
    updated = 0
    out_rows: List[Dict[str, Any]] = []
    asset_batch: Dict[str, Tuple[bytes, str]] = {}
    for row in rows:
        rr = dict(row)
        guid = str(rr.get("guid") or "").strip()
        new_payload = payloads_by_guid.get(guid)
        if new_payload is not None:
            rr["payload"] = _normalize_manifest_payload_bulk(
                guid=guid,
                payload=new_payload,
                asset_batch=asset_batch,
            )
            updated += 1
        out_rows.append(rr)
    if updated:
        if asset_batch:
            db.put_assets_bulk(
                [(key, data, mime) for key, (data, mime) in asset_batch.items()],
            )
        _rebuild_manifest(db, out_rows)
    return updated


def _create_default_object_folders(db: Mpdb, parent: ManifestObject) -> None:
    """Создаёт стандартные папки внутри объекта (Реквизиты, Формы, ...).

    Эти узлы являются системными и не удаляются пользователем.
    """

    if not should_create_object_folders(str(parent.type), parent.payload):
        return

    # Вся логика того, *какие* секции/папки нужны объекту, теперь живёт в policies.
    # Создаём только folder-секции. Schema-секции визуализируются отдельно (дерево/формы).
    folder_sections: List[str] = list(
        ordered_object_sections(str(parent.type), parent.payload, kind="folder")
    )
    if not folder_sections:
        return

    # Пишем title = key (не RU). UI обязан показывать локализованное название.
    # order: 10,20,30...
    for idx, key in enumerate(folder_sections, start=1):
        title = key
        order = idx * 10
        _insert_raw_if_missing(
            db,
            {
                "guid": _sys_guid(f"objfolder:{parent.guid}:{key}"),
                "type": parent.type,
                "name": key,
                "title": title,
                "kind": "folder",
                "parent_guid": parent.guid,
                "payload": {
                    "system": True,
                    "protected": True,
                    "auto": True,
                    "menu": "add_only",
                    "order": order,
                },
            },
        )


def _default_object_folder_objects(parent: ManifestObject) -> List[ManifestObject]:
    if not should_create_object_folders(str(parent.type), parent.payload):
        return []

    folder_sections: List[str] = list(
        ordered_object_sections(str(parent.type), parent.payload, kind="folder")
    )
    if not folder_sections:
        return []

    out: List[ManifestObject] = []
    for idx, key in enumerate(folder_sections, start=1):
        out.append(
            make_object(
                guid=_sys_guid(f"objfolder:{parent.guid}:{key}"),
                obj_type=parent.type,
                name=key,
                title=key,
                kind="folder",
                parent_guid=parent.guid,
                payload={
                    "system": True,
                    "protected": True,
                    "auto": True,
                    "menu": "add_only",
                    "order": idx * 10,
                },
            )
        )
    return out


def _ensure_default_folders_for_objects(db: Mpdb) -> None:
    """Ensure standard system subfolders exist for each user object.

    Это нужно для баз, созданных до внедрения автогенерации подпапок,
    а также после частичных обновлений.
    """
    objs = list_objects(db, hydrate_payload=False)
    for o in objs:
        if o.kind != "object":
            continue
        # Не создаём подпапки для системных узлов (группы/корень и т.п.)
        payload = o.payload if isinstance(o.payload, dict) else {}
        if payload.get("system") or payload.get("seed") or payload.get("protected"):
            continue
        _create_default_object_folders(db, o)



# Які стандартні модулі-заглушки створити під кожним типом об'єкта.
_MODULE_STUBS: dict[str, list[tuple[str, str, str]]] = {
    # obj_type → [(name, title_uk, title_en), ...]
    "catalog": [
        ("ObjectModule",  "Модуль об'єкта",    "Object module"),
        ("ManagerModule", "Модуль менеджера",  "Manager module"),
    ],
    "document": [
        ("ObjectModule",  "Модуль об'єкта",    "Object module"),
        ("ManagerModule", "Модуль менеджера",  "Manager module"),
    ],
    "report": [
        ("ObjectModule",  "Модуль об'єкта",    "Object module"),
        ("ManagerModule", "Модуль менеджера",  "Manager module"),
    ],
    "data_processor": [
        ("ObjectModule",  "Модуль об'єкта",    "Object module"),
        ("ManagerModule", "Модуль менеджера",  "Manager module"),
    ],
    "register_info": [
        ("RecordSetModule", "Модуль набору записів", "Record-set module"),
        ("ManagerModule",   "Модуль менеджера",      "Manager module"),
    ],
    "register_accum": [
        ("RecordSetModule", "Модуль набору записів", "Record-set module"),
        ("ManagerModule",   "Модуль менеджера",      "Manager module"),
    ],
    "common_module": [
        ("Module",  "Модуль", "Module"),
    ],
    "common_command": [
        ("CommandModule", "Модуль команди", "Command module"),
    ],
    "form": [
        ("FormModule", "Модуль форми", "Form module"),
    ],
    "common_form": [
        ("FormModule", "Модуль форми", "Form module"),
    ],
}
# Aliases (plural forms from tree root type strings)
_MODULE_STUBS["catalogs"]       = _MODULE_STUBS["catalog"]
_MODULE_STUBS["documents"]      = _MODULE_STUBS["document"]
_MODULE_STUBS["reports"]        = _MODULE_STUBS["report"]
_MODULE_STUBS["data_processors"]= _MODULE_STUBS["data_processor"]
_MODULE_STUBS["info_registers"]  = _MODULE_STUBS["register_info"]
_MODULE_STUBS["accumulation_registers"] = _MODULE_STUBS["register_accum"]
_MODULE_STUBS["common_modules"] = _MODULE_STUBS["common_module"]


def _ensure_module_stubs_for_single_object(db: Mpdb, o: "ManifestObject") -> None:
    """Create module stub nodes for a single newly-created object.
    Called immediately after add_object so stubs appear right away.
    """
    obj_type = str(o.type or "").strip().lower()
    payload = o.payload if isinstance(o.payload, dict) else {}
    if obj_type == "common":
        obj_type = str(payload.get("subtype") or "").strip().lower()

    if payload.get("system") or payload.get("seed") or payload.get("protected"):
        return

    stubs = _MODULE_STUBS.get(obj_type)
    if not stubs:
        return

    modules_folder_guid = _sys_guid(f"objfolder:{o.guid}:modules")

    # Ensure the folder exists (it should after _create_default_object_folders)
    folder_rows = db.table(MANIFEST_TABLE).select(where={"guid": modules_folder_guid}) or []
    if not folder_rows:
        return

    for name, title_uk, title_en in stubs:
        stub_guid = _sys_guid(f"module_stub:{o.guid}:{name}")
        _insert_raw_if_missing(
            db,
            {
                "guid":        stub_guid,
                "type":        "module",
                "name":        name,
                "title":       title_uk,
                "kind":        "object",
                "parent_guid": modules_folder_guid,
                "payload": {
                    "system":      True,
                    "auto":        True,
                    "title_uk":    title_uk,
                    "title_en":    title_en,
                    "module_kind": name,
                    "owner_guid":  str(o.guid),
                    "owner_type":  obj_type,
                },
            },
        )


def _module_stub_objects(o: "ManifestObject") -> List[ManifestObject]:
    obj_type = str(o.type or "").strip().lower()
    payload = o.payload if isinstance(o.payload, dict) else {}
    if obj_type == "common":
        obj_type = str(payload.get("subtype") or "").strip().lower()

    if payload.get("system") or payload.get("seed") or payload.get("protected"):
        return []

    stubs = _MODULE_STUBS.get(obj_type)
    if not stubs:
        return []

    modules_folder_guid = _sys_guid(f"objfolder:{o.guid}:modules")
    out: List[ManifestObject] = []
    for name, title_uk, title_en in stubs:
        out.append(
            make_object(
                guid=_sys_guid(f"module_stub:{o.guid}:{name}"),
                obj_type="module",
                name=name,
                title=title_uk,
                kind="object",
                parent_guid=modules_folder_guid,
                payload={
                    "system": True,
                    "auto": True,
                    "title_uk": title_uk,
                    "title_en": title_en,
                    "module_kind": name,
                    "owner_guid": str(o.guid),
                    "owner_type": obj_type,
                },
            )
        )
    return out


def _ensure_module_stubs_for_objects(db: Mpdb) -> None:
    """Create default module stub nodes under the 'modules' folder of each object.

    Idempotent — uses _insert_raw_if_missing so safe to call repeatedly.
    Only creates stubs for object types that have a known module list.
    """
    objs = list_objects(db, hydrate_payload=False)
    obj_map = {str(o.guid): o for o in objs}

    for o in objs:
        if o.kind != "object":
            continue
        payload = o.payload if isinstance(o.payload, dict) else {}
        if payload.get("system") or payload.get("seed") or payload.get("protected"):
            continue

        obj_type = str(o.type or "").strip().lower()
        # Resolve subtype for "common" wrapper type
        if obj_type == "common":
            obj_type = str(payload.get("subtype") or "").strip().lower()

        stubs = _MODULE_STUBS.get(obj_type)
        if not stubs:
            continue

        # modules folder guid (deterministic, same as created by _create_default_object_folders)
        modules_folder_guid = _sys_guid(f"objfolder:{o.guid}:modules")

        # Check folder actually exists — skip if not yet created
        folder_rows = db.table(MANIFEST_TABLE).select(where={"guid": modules_folder_guid}) or []
        if not folder_rows:
            continue

        for name, title_uk, title_en in stubs:
            stub_guid = _sys_guid(f"module_stub:{o.guid}:{name}")
            _insert_raw_if_missing(
                db,
                {
                    "guid":        stub_guid,
                    "type":        "module",
                    "name":        name,
                    "title":       title_uk,
                    "kind":        "object",
                    "parent_guid": modules_folder_guid,
                    "payload": {
                        "system":    True,
                        "auto":      True,
                        "title_uk":  title_uk,
                        "title_en":  title_en,
                        "module_kind": name,
                        "owner_guid":  str(o.guid),
                        "owner_type":  obj_type,
                    },
                },
            )


def _module_ref_value_from_row(db: Mpdb, row: dict[str, Any]) -> str:
    if not isinstance(row, dict):
        return ""
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    if isinstance(payload, dict):
        module = payload.get("module") if isinstance(payload.get("module"), dict) else {}
        if isinstance(module, dict):
            asset_key = str(module.get("asset_key") or "").strip()
            if asset_key.startswith("module://"):
                return asset_key
    try:
        from src.configurator.persistence.modules_dao import list_modules_by_owner

        owner_guid = str(row.get("guid") or "").strip()
        if not owner_guid:
            return ""
        rows = list_modules_by_owner(db, owner_guid=owner_guid) or []
    except Exception:
        rows = []
    if not rows:
        return ""
    preferred = next((item for item in rows if not str(item.get("lang") or "").strip()), rows[0])
    module_guid = str(preferred.get("module_guid") or "").strip()
    return f"module://{module_guid}" if module_guid else ""


def _ensure_configuration_root_module_refs(db: Mpdb) -> None:
    """Populate root configuration module refs from already imported module objects."""

    root_guid = _sys_guid("root:configuration")
    try:
        rows = db.table(MANIFEST_TABLE).select(where={"guid": root_guid}) or []
    except Exception:
        rows = []
    row = next((item for item in rows if isinstance(item, dict)), None)
    if not isinstance(row, dict):
        return

    payload = dict(row.get("payload") or {}) if isinstance(row.get("payload"), dict) else {}

    module_name_map = {
        "managed_application_module": "AppModule",
        "session_module": "SessionModule",
        "external_connection_module": "ExternalConnectionModule",
        "ordinary_application_module": "OrdinaryApplicationModule",
    }
    changed = False
    refs: list[str] = []
    rows_all = []
    try:
        rows_all = list_object_rows(db)
    except Exception:
        rows_all = []
    by_name = {
        str(item.get("name") or "").strip().casefold(): item
        for item in rows_all
        if isinstance(item, dict) and str(item.get("type") or "").strip().lower() == "common_module"
    }

    for field, module_name in module_name_map.items():
        current = str(payload.get(field) or "").strip()
        if current.startswith("module://"):
            if current not in refs:
                refs.append(current)
            continue
        candidate = by_name.get(module_name.casefold())
        ref = _module_ref_value_from_row(db, candidate) if isinstance(candidate, dict) else ""
        if ref:
            payload[field] = ref
            changed = True
            if ref not in refs:
                refs.append(ref)

    if refs:
        current_refs = payload.get("startup_modules")
        normalized_refs = [ref for ref in refs if ref]
        if current_refs != normalized_refs:
            payload["startup_modules"] = normalized_refs
            changed = True

    if changed:
        try:
            db.table(MANIFEST_TABLE).update(where={"guid": root_guid}, set_values={"payload": _normalize_manifest_payload(db, guid=root_guid, payload=payload)})
        except Exception:
            update_payload(db, root_guid, payload)


def update_title(db: Mpdb, guid: str, new_title: str) -> None:
    """Update a manifest object's title.

    mpdb tables are append-only; we update by rebuilding the manifest table.
    """
    update_fields(db, guid, title=new_title)


def update_payload(db: Mpdb, guid: str, payload: dict) -> None:
    """Update a manifest object's payload.

    Payload-only updates should avoid a full manifest rebuild.
    """
    started_at = time.perf_counter()
    guid = (guid or "").strip()
    normalized_payload = payload or {}
    if not guid:
        return
    try:
        rows = db.table(MANIFEST_TABLE).select(where={"guid": guid}) or []
    except Exception:
        rows = []
    if not rows:
        return

    row = rows[0]
    current_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    normalized = _normalize_manifest_payload(db, guid=guid, payload=normalized_payload)
    if normalized == current_payload:
        _log.info(
            "manifest.update_payload.noop guid=%s took=%.3fs",
            guid,
            time.perf_counter() - started_at,
        )
        return

    try:
        db.table(MANIFEST_TABLE).update(where={"guid": guid}, set_values={"payload": normalized})
        _log.info(
            "manifest.update_payload.direct guid=%s took=%.3fs",
            guid,
            time.perf_counter() - started_at,
        )
    except Exception:
        update_fields(db, guid, payload=normalized)
        _log.info(
            "manifest.update_payload.rebuild guid=%s took=%.3fs",
            guid,
            time.perf_counter() - started_at,
        )


def _try_fast_externalized_payload_update(db: Mpdb, guid: str, payload: dict) -> bool:
    """Update heavy externalized payload assets without rebuilding manifest.

    Fast-path is safe only when:
    - target row already exists;
    - changed fields are limited to keys externalized into assets;
    - row payload keeps the same scalar fields / refs after normalization.

    This is the common case for form/layout editors, where only
    ``form_model`` / ``layout_model`` content changes while the manifest row
    itself remains structurally identical.
    """

    if not isinstance(payload, dict):
        return False

    try:
        rows = db.table(MANIFEST_TABLE).select(where={"guid": guid}) or []
    except Exception:
        return False
    if not rows:
        return False

    row = rows[0]
    current_payload = row.get("payload") if isinstance(row.get("payload"), dict) else None
    if not isinstance(current_payload, dict):
        return False

    compare_payload = dict(payload)
    updated_externalized = False

    for key in sorted(_EXTERNALIZED_PAYLOAD_KEYS):
        if key not in compare_payload:
            continue
        ref_key = f"{key}_ref"
        current_ref = str(current_payload.get(ref_key) or "").strip()
        payload_ref = str(compare_payload.get(ref_key) or "").strip()
        target_ref = payload_ref or current_ref
        if not target_ref:
            return False
        try:
            _put_manifest_payload_asset_ref(
                db,
                ref=target_ref,
                value=compare_payload[key],
            )
        except Exception:
            return False
        compare_payload.pop(key, None)
        compare_payload[ref_key] = target_ref
        updated_externalized = True

    if not updated_externalized:
        return False

    return compare_payload == current_payload


def update_fields(
    db: Mpdb,
    guid: str,
    *,
    obj_type: str | None = None,
    name: str | None = None,
    title: str | None = None,
    parent_guid: str | None = None,
    payload: dict | None = None,
) -> None:
    """Update selected fields for a single manifest row.

    Why this exists:
    - mpdb tables are append-only; updates are performed by rebuilding the table.
    - the editor needs to update multiple fields in one rebuild to avoid
      inconsistent intermediate states.

    Parameters
    - guid: target object GUID
    - obj_type/name/title/payload: optional new values; if None, field is kept.

    Notes
    - This function does not implement any business rules; those must be
      enforced by higher-level services (ConfiguratorService / Editor).
    """

    guid = (guid or "").strip()
    if not guid:
        return

    rows = db.table(MANIFEST_TABLE).select() or []
    updated = False
    out_rows: List[Dict[str, Any]] = []

    for r in rows:
        rr = dict(r)
        if str(rr.get("guid") or "") == guid:
            if obj_type is not None:
                rr["type"] = str(obj_type)
            if name is not None:
                rr["name"] = str(name)
            if title is not None:
                rr["title"] = str(title)
            if parent_guid is not None:
                rr["parent_guid"] = str(parent_guid)
            if payload is not None:
                rr["payload"] = _normalize_manifest_payload(
                    db,
                    guid=guid,
                    payload=payload,
                )
            updated = True
        out_rows.append(rr)

    if updated:
        _rebuild_manifest(db, out_rows)



def prune_orphans(db: Mpdb) -> int:
    """Remove orphan manifest rows whose parent_guid does not exist.

    This can happen if a previous buggy delete removed a parent but left
    protected/system descendants behind. Orphan rows must not remain in the tree.
    Returns number of removed rows.
    """
    try:
        rows = db.table(MANIFEST_TABLE).select() or []
    except Exception:
        return 0

    guid_set = {str(r.get("guid") or "") for r in rows}
    # Keep rows with empty parent_guid (roots/groups) and those whose parent exists.
    kept: list[dict] = []
    removed = 0
    for r in rows:
        pg = str(r.get("parent_guid") or "")
        if pg and pg not in guid_set:
            removed += 1
            continue
        kept.append(dict(r))

    if removed:
        _rebuild_manifest(db, kept)
    return removed



def delete_object(db: Mpdb, guid: str) -> None:
    """Delete object (and its descendants) unless protected/system."""
    guid = (guid or "").strip()
    if not guid:
        return

    rows = db.table(MANIFEST_TABLE).select() or []

    by_guid: Dict[str, Dict[str, Any]] = {}
    children: Dict[str, List[str]] = {}
    for r in rows:
        g = str(r.get("guid") or "")
        by_guid[g] = r
        pg = str(r.get("parent_guid") or "")
        children.setdefault(pg, []).append(g)

    def is_protected(row: Dict[str, Any]) -> bool:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        return bool(payload.get("system") or payload.get("protected") or payload.get("seed"))

    target = by_guid.get(guid)
    if not target:
        return
    if is_protected(target):
        raise ValueError("SYSTEM/PROTECTED object cannot be deleted")

    to_delete: set[str] = set()

    def walk(g: str) -> None:
        row = by_guid.get(g)
        if not row:
            return
        # NOTE:
        # Even if a descendant node is marked system/protected/seed, it must be
        # removed when its parent (a user object) is deleted. Otherwise we get
        # undeletable orphan nodes in the tree.
        to_delete.add(g)
        for ch in children.get(g, []):
            walk(ch)

    walk(guid)

    out_rows = [dict(r) for r in rows if str(r.get("guid") or "") not in to_delete]
    _rebuild_manifest(db, out_rows)

    # Final sanity pass: ensure no orphans remain (e.g., from older buggy
    # deletes or external edits). Orphans are invalid and must be pruned even
    # if they carry system/protected flags.
    try:
        prune_orphans(db)
    except Exception:
        pass


# ------------------------------------------------------------
# Internal: rebuild / migration
# ------------------------------------------------------------


def _rebuild_manifest(db: Mpdb, rows: List[Dict[str, Any]]) -> None:
    """Rewrite manifest table by dropping its pages and re-inserting rows."""

    # Pre-normalize outside the transaction (no db writes for already-normalized rows).
    prepared = [_manifest_row_from_object(db, r) for r in rows]

    t = db.table(MANIFEST_TABLE)
    with db.transaction() as tx:
        tinfo = db._meta["tables"][MANIFEST_TABLE]

        # Do NOT add old pages to free_pages — mpdb would try to read them
        # before overwriting, hitting stale compression headers and crashing
        # with "Unknown compression type". Just abandon them in-file.
        tinfo["data_pages"] = []
        tinfo["next_rowid"] = 1

        # IMPORTANT:
        # Table.insert() maintains a *unique* primary rowid->locator index
        # stored in tinfo["rowid_index_root"]. When we rebuild a table by
        # resetting the data pages + next_rowid, we MUST also reset the
        # rowid locator index root. Otherwise, the first insert will try to
        # insert rowid=1 into an old index tree that already contains that
        # key, leading to:
        #   "Unique constraint failed (index): key=...\x01"
        #
        # The old index pages remain in the file (append-only storage), but
        # are no longer referenced from META, so they won't affect correctness.
        tinfo.pop("rowid_index_root", None)

        # clear indexes
        idx = db._meta.get("indexes", {})
        if isinstance(idx, dict) and MANIFEST_TABLE in idx:
            idx.pop(MANIFEST_TABLE, None)

        for r in prepared:
            t.insert_tx(tx, r, set_meta=False)
        tx.set_meta(db._meta)


def _ensure_guids(db: Mpdb) -> None:
    """Ensure every row has a GUID. Legacy safety net."""
    rows = db.table(MANIFEST_TABLE).select() or []
    missing = [r for r in rows if not str(r.get("guid") or "").strip()]
    if not missing:
        return

    out: List[Dict[str, Any]] = []
    for r in rows:
        rr = dict(r)
        if not str(rr.get("guid") or "").strip():
            payload = rr.get("payload") if isinstance(rr.get("payload"), dict) else {}
            is_sys = bool(payload.get("system") or payload.get("protected") or payload.get("seed"))
            key = f"{rr.get('kind','object')}:{rr.get('type','common')}:{rr.get('name','')}:" \
                  f"{rr.get('parent_guid','')}"
            rr["guid"] = _sys_guid(key) if is_sys else _new_guid()
        out.append(rr)
    _rebuild_manifest(db, out)


def _migrate_uid_manifest_to_guid(db: Mpdb) -> None:
    """Migrate old manifest schema with uid/parent_uid to guid/parent_guid."""
    # Read old rows
    old_rows = db.table(MANIFEST_TABLE).select() or []

    # ------------------------------------------------------------------
    # IMPORTANT
    # ------------------------------------------------------------------
    # If we migrate UID->GUID by assigning random GUIDs to every old row,
    # the subsequent SYSTEM seed (deterministic GUIDs) will create duplicates
    # of the standard branches ("Общие", "Документы", "Общие реквизиты", ...).
    #
    # To keep migration idempotent and avoid "double trees", we attempt to
    # recognize old system nodes and map them to the same deterministic GUIDs
    # used by the current seeding logic.
    # ------------------------------------------------------------------

    # Build new schema by recreating table meta
    schema: Dict[str, Dict[str, Any]] = {
        "guid": {"type": "str", "unique": True, "indexed": True},
        "type": {"type": "str"},
        "name": {"type": "str"},
        "title": {"type": "str"},
        "kind": {"type": "str"},
        "parent_guid": {"type": "str", "indexed": True},
        "payload": {"type": "json"},
    }

    # Allocate GUIDs for old UID rows.
    # First, try to map known SYSTEM seed nodes to deterministic GUIDs.
    uid_to_guid: Dict[str, str] = {}

    by_uid: Dict[str, Dict[str, Any]] = {}
    for r in old_rows:
        uid = str(r.get("uid") or "").strip()
        if uid:
            by_uid[uid] = r

    # 1) Root "Конфигурация"
    root_uid = ""
    for uid, r in by_uid.items():
        title = str(r.get("title") or "")
        name = str(r.get("name") or "")
        kind = str(r.get("kind") or "")
        parent_uid = str(r.get("parent_uid") or "")
        if (not parent_uid) and (title == "Конфигурация" or name == "Configuration" or kind == "root"):
            root_uid = uid
            break
    if root_uid:
        uid_to_guid[root_uid] = _sys_guid("root:configuration")

    # 2) Standard groups under root
    title_to_group_type: Dict[str, str] = {
        "Общие": "common",
        "Константы": "constants",
        "Справочники": "catalog",
        "Документы": "document",
        "Журналы документов": "journal",
        "Перечисления": "enumeration",
        "Отчеты": "report",
        "Обработки": "data_processor",
        "Планы видов характеристик": "chart_of_characteristic_types",
        "Планы счетов": "chart_of_accounts",
        "Планы видов расчета": "chart_of_calculation_types",
        "Регистры сведений": "register_info",
        "Регистры накопления": "register_accum",
        "Регистры бухгалтерии": "register_accounting",
        "Регистры расчета": "register_calc",
        "Бизнес-процессы": "business_process",
        "Задачи": "task",
        "Внешние источники данных": "external_sources",
    }

    common_group_uid = ""
    if root_uid:
        for uid, r in by_uid.items():
            if str(r.get("parent_uid") or "") != root_uid:
                continue
            if str(r.get("kind") or "") != "group":
                continue
            title = str(r.get("title") or "")
            type_code = title_to_group_type.get(title)
            if not type_code:
                continue
            det = _sys_guid(f"group:{type_code}")
            uid_to_guid.setdefault(uid, det)
            if type_code == "common":
                common_group_uid = uid

    # 3) Default folders under "Общие"
    common_folder_names = {
        "subsystems",
        "common_modules",
        "session_params",
        "roles",
        "common_attributes",
        "exchange_plans",
        "selection_criteria",
        "event_subscriptions",
        "scheduled_jobs",
        "bots",
        "functional_options",
        "functional_options_params",
        "defined_types",
        "settings_storages",
        "common_commands",
        "command_groups",
        "common_forms",
        "common_layouts",
        "common_pictures",
        "xdto_packages",
        "web_services",
        "http_services",
        "ws_links",
        "websocket_clients",
        "integration_services",
        "style_elements",
        "styles",
        "languages",
    }

    if common_group_uid:
        for uid, r in by_uid.items():
            if str(r.get("parent_uid") or "") != common_group_uid:
                continue
            if str(r.get("kind") or "") != "folder":
                continue
            if str(r.get("type") or "") != "common":
                continue
            name = str(r.get("name") or "")
            if name not in common_folder_names:
                continue
            uid_to_guid.setdefault(uid, _sys_guid(f"common:{name}"))

    # Assign random GUIDs to all remaining rows (stable for this migration run).
    used: set[str] = set(uid_to_guid.values())
    for r in old_rows:
        uid = str(r.get("uid") or "")
        if not uid:
            continue
        if uid in uid_to_guid:
            continue
        g = _new_guid()
        while g in used:
            g = _new_guid()
        uid_to_guid[uid] = g
        used.add(g)

    new_rows: List[Dict[str, Any]] = []
    for r in old_rows:
        uid = str(r.get("uid") or "")
        pg_uid = str(r.get("parent_uid") or "")
        new_rows.append(
            {
                "guid": uid_to_guid.get(uid, _new_guid()),
                "type": str(r.get("type") or "common"),
                "name": str(r.get("name") or ""),
                "title": str(r.get("title") or ""),
                "kind": str(r.get("kind") or "object"),
                "parent_guid": uid_to_guid.get(pg_uid, ""),
                "payload": r.get("payload") if isinstance(r.get("payload"), dict) else {},
            }
        )

    # Drop and recreate table definition cleanly
    with db.transaction() as tx:
        tables = db._meta["tables"]
        tinfo = tables.get(MANIFEST_TABLE)
        if tinfo:
            old_pages = list(tinfo.get("data_pages", []))
            free_pages = db._meta.setdefault("free_pages", [])
            for pid in old_pages:
                free_pages.append(int(pid))
            tinfo["data_pages"] = []
            tinfo["next_rowid"] = 1
            tinfo["schema"] = schema

            # Reset primary rowid->locator index.
            # Legacy manifests may have rowid_index_root pointing to an old B+tree;
            # if we keep it, reinserting rows after migration can trip unique
            # constraints on rowid keys.
            old_rowid_root = tinfo.pop("rowid_index_root", None)
            if isinstance(old_rowid_root, int) and old_rowid_root > 0:
                free_pages.append(int(old_rowid_root))
        # clear indexes
        idx = db._meta.get("indexes", {})
        if isinstance(idx, dict) and MANIFEST_TABLE in idx:
            # best-effort: free old secondary index roots to reduce leaks
            try:
                old = idx.get(MANIFEST_TABLE)
                if isinstance(old, dict):
                    free_pages = db._meta.setdefault("free_pages", [])
                    for idef in old.values():
                        if isinstance(idef, dict) and isinstance(idef.get("root"), int):
                            r = int(idef["root"])
                            if r > 0:
                                free_pages.append(r)
            except Exception:
                pass
            idx.pop(MANIFEST_TABLE, None)
        tx.set_meta(db._meta)

    # Reinsert rows
    t = db.table(MANIFEST_TABLE)
    for nr in new_rows:
        t.insert(nr)
