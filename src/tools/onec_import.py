from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Set, Iterable

from src.configurator.persistence import manifest_io
from src.infra.onec.importer import (
    DirectorySource,
    ZipSource,
    guess_mime,
    import_manifest_objects,
)
from src.infra.onec.onecd_source import OneCDConfigSource
from src.infra.onec.physical_schema import (
    SOURCE_SNAPSHOT_ASSET_KEY,
    build_onec_compatibility_snapshot,
    store_source_snapshot_asset,
)
from src.infra.onec.storage_alignment import (
    STORAGE_ALIGNMENT_ASSET_KEY,
    build_storage_alignment_report_from_snapshot,
    store_storage_alignment_asset,
)
from src.infra.onec.physical_mapping import (
    PHYSICAL_MAPPING_ASSET_KEY,
    build_physical_mapping_report,
    store_physical_mapping_asset,
)
from src.infra.onec.metadata_structure import apply_onec_structural_metadata
from src.infra.onec.source_compat import resolve_onec_source
from src.infra.onec.onec_requisites_parser import (
    OneCXmlParser,
    enrich_manifest_payload,
)


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _backup_db_copy(db_path: str) -> Tuple[bool, str]:
    """Create a timestamped backup copy of the mpdb file (if exists).

    Unlike the early MVP, we do **not** replace/move the DB file anymore.
    Hard import is destructive only for *configuration metadata* and imported
    asset prefixes, but it should not blindly wipe unrelated user data.

    Returns (did_backup, backup_path).
    """
    p = Path(db_path)
    if not p.exists():
        return False, ""

    backup = p.with_name(f"{p.stem}.backup-{_ts()}{p.suffix}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(str(p), str(backup))
        return True, str(backup)
    except Exception:
        return False, ""


def _hard_reset_manifest(db) -> None:
    """Hard-reset manifest (metadata structure) while keeping other tables/data."""
    manifest_io.ensure_manifest_table(db)
    manifest_io._rebuild_manifest(db, [])  # type: ignore[attr-defined]
    # seed_defaults=True обязателен — без него import_manifest_objects не найдёт
    # группы (catalog, document и т.д.) и пропустит все объекты
    manifest_io.ensure_manifest(db, seed_defaults=True)  # type: ignore[attr-defined]


def _put_raw_assets(
    db,
    source,
    paths: List[str],
    *,
    raw_prefix: str = "onec_raw/",
    batch_size: int = 200,
) -> Set[str]:
    """Persist all files from dump as raw assets in mpdb.

    Returns:
        Set of successfully imported *relative paths* (used for pruning).
    """
    imported: Set[str] = set()
    batch: List[Tuple[str, bytes, str]] = []

    for rel in paths:
        rel = str(rel or "").replace("\\", "/").lstrip("/")
        if not rel:
            continue
        key = f"{raw_prefix}{rel}"
        try:
            data = source.read_bytes(rel)
        except Exception:
            continue
        mime = guess_mime(rel)
        batch.append((key, data, mime))
        imported.add(rel)

        if len(batch) >= batch_size:
            db.put_assets_bulk(batch)
            batch.clear()

    if batch:
        db.put_assets_bulk(batch)

    return imported


def _iter_existing_assets(db, prefix: str) -> Iterable[str]:
    try:
        return db.list_assets(prefix=prefix)
    except Exception:
        return []


def _prune_missing_assets(db, *, prefix: str, expected_rel: Set[str]) -> int:
    """Delete assets under prefix that are not present in expected_rel set."""
    expected_keys = {f"{prefix}{rel}" for rel in expected_rel}
    to_delete: List[str] = []
    for k in _iter_existing_assets(db, prefix):
        if k not in expected_keys:
            to_delete.append(k)

    deleted = 0
    for k in to_delete:
        try:
            if db.delete_asset(k):
                deleted += 1
        except Exception:
            continue
    return deleted


def _enrich_objects_with_requisites(db, source) -> int:
    """Parse requisites/tabular-parts from XML dump and write them into manifest payloads.

    Called right after import_manifest_objects() — at that point all objects
    already exist in the manifest, so we just need to update their payload.

    Matching strategy (в порядке приоритета):
      1. payload["imported"]["src_uid"]  == parsed obj UUID  (точное совпадение)
      2. transliterated name             == mo.name          (запасной вариант)

    Returns count of enriched objects.
    """
    from src.infra.onec.importer import to_ascii_identifier
    from src.infra.onec.onec_requisites_enrich import (
        metadata_ref_for_manifest_object,
        resolve_subsystem_payload,
    )

    parser = OneCXmlParser()
    try:
        parsed_objects = parser.parse_all(source)
    except Exception:
        return 0

    if not parsed_objects:
        return 0

    # Индекс 1: UUID -> объект
    by_uuid: dict = {o.uuid: o for o in parsed_objects if o.uuid}
    # Индекс 2: (obj_type, transliterated_name) -> объект
    by_name: dict = {
        (o.obj_type, to_ascii_identifier(o.name)): o
        for o in parsed_objects if o.name
    }

    payloads_by_guid: dict[str, dict] = {}
    try:
        all_manifest = manifest_io.list_objects(db)
    except Exception:
        return 0

    meta_ref_to_guid: dict[str, str] = {}
    for mo in all_manifest:
        if mo.kind != "object":
            continue
        imp = mo.payload.get("imported", {}) if isinstance(mo.payload, dict) else {}
        ref = metadata_ref_for_manifest_object(
            obj_type=mo.type,
            name=mo.name,
            origin_path=str(imp.get("origin") or ""),
        )
        if ref:
            meta_ref_to_guid.setdefault(ref, mo.guid)

    for mo in all_manifest:
        if mo.kind != "object":
            continue

        # Пробуем найти по UUID из payload
        imp = mo.payload.get("imported", {}) if isinstance(mo.payload, dict) else {}
        src_uid = str(imp.get("src_uid") or "").strip()
        parsed = by_uuid.get(src_uid)

        # Запасной вариант — по типу + транслитерированному имени
        if parsed is None:
            parsed = by_name.get((mo.type, mo.name))

        if parsed is None:
            continue

        try:
            enriched_payload = enrich_manifest_payload(mo.payload or {}, parsed)
            payloads_by_guid[mo.guid] = resolve_subsystem_payload(
                enriched_payload,
                meta_ref_to_guid=meta_ref_to_guid,
            )
        except Exception:
            continue

    return manifest_io.bulk_update_payloads(db, payloads_by_guid)


def _put_semantic_ref_assets(
    db,
    *,
    rel_paths: Set[str],
    raw_prefix: str = "onec_raw/",
    semantic_prefix: str = "onec/",
    only_ext: tuple[str, ...] = (".bsl",),
    batch_size: int = 500,
) -> Set[str]:
    """Create/overwrite semantic REF assets for selected file types."""
    out: Set[str] = set()
    batch: List[Tuple[str, bytes, str]] = []

    for rel in sorted(rel_paths):
        rel_l = rel.lower()
        if only_ext and not any(rel_l.endswith(ext) for ext in only_ext):
            continue

        sem_key = f"{semantic_prefix}{rel}"
        raw_key = f"{raw_prefix}{rel}"
        payload = ("{\n"
                   f"\"ref\": \"{raw_key}\"\n"
                   "}").encode("utf-8")
        mime = "application/json"
        batch.append((sem_key, payload, mime))
        out.add(rel)

        if len(batch) >= batch_size:
            db.put_assets_bulk(batch)
            batch.clear()

    if batch:
        db.put_assets_bulk(batch)

    return out


def _create_localized_module_variants(db) -> int:
    """Create batched `uk`/`en` module rows for base language modules.

    Compatibility shim for older import/test contracts.
    """
    from src.configurator.persistence.modules_dao import (
        get_module_text_from_row,
        insert_modules_bulk,
        make_module_row,
    )
    from src.configurator.persistence.modules_tables import MODULES_TABLE, ensure_modules_tables
    from src.infra.onec.module_transform import normalize_module_text

    ensure_modules_tables(db)
    rows = db.table(MODULES_TABLE).select() or []
    existing_langs: dict[str, set[str]] = {}
    for row in rows:
        module_guid = str(row.get("module_guid") or "").strip()
        if not module_guid:
            continue
        existing_langs.setdefault(module_guid, set()).add(str(row.get("lang") or "").strip())

    pending = []
    for row in rows:
        base_lang = str(row.get("lang") or "").strip()
        if base_lang:
            continue
        module_guid = str(row.get("module_guid") or "").strip()
        langs = existing_langs.get(module_guid, set())
        text = get_module_text_from_row(db, row)
        for lang in ("uk", "en"):
            if lang in langs:
                continue
            normalized = normalize_module_text(text, language=lang)
            pending.append(
                make_module_row(
                    owner_guid=str(row.get("owner_guid") or ""),
                    owner_kind=str(row.get("owner_kind") or ""),
                    module_kind=str(row.get("module_kind") or ""),
                    name=str(row.get("name") or ""),
                    text=normalized.text,
                    lang=lang,
                    updated_by=str(row.get("updated_by") or "import"),
                    source_ref=str(row.get("source_ref") or ""),
                    canonical_ref=str(row.get("canonical_ref") or ""),
                    ref_uk=str(row.get("ref_uk") or ""),
                    ref_en=str(row.get("ref_en") or ""),
                )
            )

    return insert_modules_bulk(db, pending)


def _build_and_store_source_snapshot(
    db,
    *,
    source_path: str,
    source_kind: str,
) -> tuple[dict[str, object] | None, str, str]:
    try:
        snapshot = build_onec_compatibility_snapshot(source_path, source_kind)
    except Exception as exc:
        return None, "", str(exc)
    try:
        asset_key = store_source_snapshot_asset(db, snapshot, asset_key=SOURCE_SNAPSHOT_ASSET_KEY)
    except Exception as exc:
        return snapshot, "", str(exc)
    return snapshot, asset_key, ""


def _build_and_store_storage_alignment(
    db,
    *,
    snapshot: dict[str, object] | None,
    source_path: str,
) -> tuple[dict[str, object] | None, str, str]:
    if not snapshot:
        return None, "", "source snapshot is unavailable"
    try:
        report = build_storage_alignment_report_from_snapshot(snapshot, source_path=source_path)
    except Exception as exc:
        return None, "", str(exc)
    try:
        asset_key = store_storage_alignment_asset(db, report, asset_key=STORAGE_ALIGNMENT_ASSET_KEY)
    except Exception as exc:
        return report, "", str(exc)
    return report, asset_key, ""


def _build_and_store_physical_mapping(
    db,
    *,
    source_path: str,
    source_kind: str,
    snapshot: dict[str, object] | None,
) -> tuple[dict[str, object] | None, str, str]:
    try:
        report = build_physical_mapping_report(
            source_path,
            source_kind,
            snapshot=snapshot,
        )
    except Exception as exc:
        return None, "", str(exc)
    try:
        asset_key = store_physical_mapping_asset(db, report, asset_key=PHYSICAL_MAPPING_ASSET_KEY)
    except Exception as exc:
        return report, "", str(exc)
    return report, asset_key, ""


# ---------------------------------------------------------------------------
# Server-side import logic (called directly on the server, has real Mpdb)
# ---------------------------------------------------------------------------

def run_import_on_db(
    db,
    *,
    source_path: str,
    source_kind: str,
    mode: str = "hard",
    wipe_prefixes: bool = True,
    prune_missing_assets: bool = True,
    store_raw_assets: bool = False,
    store_binary_assets: bool = False,
    store_raw_asset_keys: bool = False,
    store_modules_in_table: bool = True,
) -> dict:
    """Execute the full 1C import against an already-open db object.

    This function runs on the SERVER side where db is a real Mpdb instance
    (or any compatible object). It is called by:
      - the RPC handler (server.py  →  action "onec.import")
      - the CLI  (__main__ block below)

    Returns a dict with import statistics.
    """
    from src.mpdb.mpdb import MpdbCorruptionError, MpdbError

    raw_prefix      = "onec_raw/"
    semantic_prefix = "onec/"
    wipe_list       = [raw_prefix, semantic_prefix]

    _hard_reset_manifest(db)

    try:
        from src.configurator.persistence.modules_dao import purge_all_modules
        purge_all_modules(db)
    except Exception:
        pass

    wiped = 0
    if wipe_prefixes and (store_raw_assets or store_binary_assets or store_raw_asset_keys):
        try:
            wiped = int(db.delete_assets_by_prefixes(wipe_list))
        except Exception:
            wiped = 0

    imported_rel: Set[str] = set()
    source_file_count = 0
    enriched = 0
    resolved = resolve_onec_source(source_path, source_kind)
    effective_path = str(resolved.semantic_path or source_path)
    effective_kind = str(resolved.semantic_kind or source_kind or "xml")

    def _maybe_store_raw(source, paths):
        if not store_raw_assets:
            return set()
        return _put_raw_assets(db, source, paths, raw_prefix=raw_prefix)

    if effective_kind.lower() == "zip":
        with ZipSource(effective_path) as src:
            paths = src.list_files()
            source_file_count = len(paths)
            imported_rel = _maybe_store_raw(src, paths)
            import_manifest_objects(
                db, src, paths,
                raw_prefix=raw_prefix,
                store_raw_asset_keys=store_raw_asset_keys,
                store_picture_assets=store_binary_assets,
                store_modules_in_table=store_modules_in_table,
            )
            enriched = _enrich_objects_with_requisites(db, src)
    elif effective_kind.lower() == "1cd":
        with OneCDConfigSource(effective_path) as src:
            paths = src.list_files()
            source_file_count = len(paths)
            imported_rel = _maybe_store_raw(src, paths)
            import_manifest_objects(
                db, src, paths,
                raw_prefix=raw_prefix,
                store_raw_asset_keys=store_raw_asset_keys,
                store_picture_assets=store_binary_assets,
                store_modules_in_table=store_modules_in_table,
            )
            enriched = _enrich_objects_with_requisites(db, src)
    else:
        root_dir = effective_path
        if os.path.isfile(root_dir):
            root_dir = os.path.dirname(root_dir)
        from src.infra.onec.importer import make_directory_source
        src = make_directory_source(root_dir)
        paths = src.list_files()
        source_file_count = len(paths)
        imported_rel = _maybe_store_raw(src, paths)
        import_manifest_objects(
            db, src, paths,
            raw_prefix=raw_prefix,
            store_raw_asset_keys=store_raw_asset_keys,
            store_picture_assets=store_binary_assets,
            store_modules_in_table=store_modules_in_table,
        )
        enriched = _enrich_objects_with_requisites(db, src)

    pruned_raw = 0
    pruned_sem = 0
    if prune_missing_assets and not wipe_prefixes and store_raw_assets:
        try:
            pruned_raw = _prune_missing_assets(db, prefix=raw_prefix, expected_rel=imported_rel)
        except Exception:
            pruned_raw = 0
        try:
            bsl_rel = {p for p in imported_rel if str(p).lower().endswith(".bsl")}
            pruned_sem = _prune_missing_assets(db, prefix=semantic_prefix, expected_rel=bsl_rel)
        except Exception:
            pruned_sem = 0

    source_snapshot, source_snapshot_asset, source_snapshot_error = _build_and_store_source_snapshot(
        db,
        source_path=source_path,
        source_kind=source_kind,
    )
    storage_alignment, storage_alignment_asset, storage_alignment_error = _build_and_store_storage_alignment(
        db,
        snapshot=source_snapshot,
        source_path=source_path,
    )
    physical_mapping, physical_mapping_asset, physical_mapping_error = _build_and_store_physical_mapping(
        db,
        source_path=source_path,
        source_kind=source_kind,
        snapshot=source_snapshot,
    )
    structural_metadata_enriched = 0
    if physical_mapping:
        try:
            structural_metadata_enriched = int(
                apply_onec_structural_metadata(db, physical_mapping) or 0
            )
        except Exception:
            structural_metadata_enriched = 0

    return {
        "imported_files": len(imported_rel) if store_raw_assets else source_file_count,
        "enriched":       enriched,
        "structural_metadata_enriched": structural_metadata_enriched,
        "wiped":          wiped,
        "pruned_raw":     pruned_raw,
        "pruned_sem":     pruned_sem,
        "mode":           mode,
        "store_raw":      store_raw_assets,
        "store_modules":  store_modules_in_table,
        "requested_source_kind": resolved.requested_kind,
        "detected_source_kind": resolved.detected_kind,
        "semantic_source_kind": resolved.semantic_kind,
        "semantic_source_path": resolved.semantic_path,
        "source_analysis": dict(resolved.analysis or {}),
        "source_snapshot": source_snapshot,
        "source_snapshot_asset": source_snapshot_asset,
        "source_snapshot_error": source_snapshot_error,
        "storage_alignment": storage_alignment,
        "storage_alignment_asset": storage_alignment_asset,
        "storage_alignment_error": storage_alignment_error,
        "physical_mapping_summary": (physical_mapping or {}).get("summary") if isinstance(physical_mapping, dict) else None,
        "physical_mapping_asset": physical_mapping_asset,
        "physical_mapping_error": physical_mapping_error,
    }


# ---------------------------------------------------------------------------
# Client-facing entry point — delegates to server via RPC "onec.import"
# ---------------------------------------------------------------------------

def import_onec_configuration(
    *,
    db_path: str,           # kept for CLI/backup only; server resolves its own path
    source_path: str,
    source_kind: str,
    mode: str = "hard",
    wipe_prefixes: bool = True,
    prune_missing_assets: bool = True,
    store_raw_assets: bool = False,
    store_binary_assets: bool = False,
    store_raw_asset_keys: bool = False,
    store_modules_in_table: bool = True,
    migrate_data: bool = False,
    data_tables: list[str] | None = None,
    data_limit_per_table: int | None = None,
    data_include_service: bool = False,
    data_include_deleted: bool = False,
    data_no_ref_index: bool = False,
    data_read_blobs: bool = False,
    data_target_prefix: str = "onec",
    data_batch_size: int = 5000,
    data_storage_mode: str = "packed",
    com_data_audit: bool = False,
    com_db_path: str = "",
    com_user: str = "",
    com_password: str = "",
    com_connector: str = "V83.COMConnector",
    com_include_samples: bool = False,
    com_sample_limit: int = 3,
    com_include_types: list[str] | None = None,
    # client-server params (injected by vm.import_onec_dump)
    runtime_url: str = "",
    db_uid: str = "",
    session_id: str = "",
) -> str:
    """Import 1C/BAS configuration dump into mpdb via the runtime server.

    The heavy lifting (file parsing, manifest reset, module storage) runs
    on the SERVER which has direct Mpdb access.  The client just sends an
    RPC "onec.import" call with the source path and options.

    Falls back to direct local execution when runtime_url is empty
    (CLI / unit-test usage).

    Returns human-readable summary.
    """
    if mode != "hard":
        mode = "hard"

    env_com_audit = str(os.environ.get("META_ONEC_COM_AUDIT") or "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    com_data_audit = bool(com_data_audit or env_com_audit)
    com_db_path = str(com_db_path or os.environ.get("META_ONEC_COM_DB_PATH") or "")
    com_user = str(com_user or os.environ.get("META_ONEC_COM_USER") or "")
    com_password = str(com_password or os.environ.get("META_ONEC_COM_PASSWORD") or "")
    com_connector = str(com_connector or os.environ.get("META_ONEC_COM_CONNECTOR") or "V83.COMConnector")
    if not com_include_samples:
        com_include_samples = str(os.environ.get("META_ONEC_COM_INCLUDE_SAMPLES") or "").strip().lower() in {
            "1", "true", "yes", "on"
        }
    if not com_include_types:
        env_types = str(os.environ.get("META_ONEC_COM_TYPES") or "").strip()
        if env_types:
            com_include_types = [part.strip() for part in env_types.split(",") if part.strip()]

    did_backup, backup_path = False, ""
    corrupt_moved_to = ""

    # ── client-server path ────────────────────────────────────────────────
    if runtime_url and db_uid:
        from src.runtime.gateway import RuntimeGateway
        gw = RuntimeGateway(runtime_url)
        if session_id:
            gw.session_id = str(session_id)
        else:
            gw.ensure_session()
        gw.open_by_uid(db_uid)

        rpc_payload = {
            "session_id":          gw._sid(),     # type: ignore[attr-defined]
            "source_path":         source_path,
            "source_kind":         source_kind,
            "mode":                mode,
            "wipe_prefixes":       wipe_prefixes,
            "prune_missing_assets":prune_missing_assets,
            "store_raw_assets":    store_raw_assets,
            "store_binary_assets": store_binary_assets,
            "store_raw_asset_keys":store_raw_asset_keys,
            "store_modules_in_table": store_modules_in_table,
        }
        if migrate_data:
            rpc_payload.update(
                {
                    "migrate_data": True,
                    "data_tables": data_tables or [],
                    "data_limit_per_table": data_limit_per_table,
                    "data_include_service": data_include_service,
                    "data_include_deleted": data_include_deleted,
                    "data_no_ref_index": data_no_ref_index,
                    "data_read_blobs": data_read_blobs,
                    "data_target_prefix": data_target_prefix,
                    "data_batch_size": data_batch_size,
                    "data_storage_mode": data_storage_mode,
                }
            )
        if com_data_audit:
            rpc_payload.update(
                {
                    "com_data_audit": True,
                    "com_db_path": com_db_path,
                    "com_user": com_user,
                    "com_password": com_password,
                    "com_connector": com_connector,
                    "com_include_samples": com_include_samples,
                    "com_sample_limit": com_sample_limit,
                    "com_include_types": com_include_types or [],
                }
            )
        try:
            rpc_timeout = float(os.environ.get("META_ONEC_IMPORT_RPC_TIMEOUT") or (86400 if migrate_data else 3600))
        except (TypeError, ValueError):
            rpc_timeout = 86400.0 if migrate_data else 3600.0
        stats: dict = gw._call("onec.import", rpc_payload, timeout=rpc_timeout)  # type: ignore[attr-defined]

    # ── local fallback (CLI / tests) ──────────────────────────────────────
    else:
        from src.mpdb.mpdb import Mpdb, MpdbError, MpdbCorruptionError

        db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        did_backup, backup_path = _backup_db_copy(db_path)

        def _open(path: str):
            from src.mpdb.mpdb import Mpdb
            db = Mpdb(path)
            manifest_io.ensure_manifest_table(db)
            try:
                manifest_io.ensure_manifest(db)  # type: ignore[attr-defined]
            except Exception:
                pass
            return db

        try:
            db = _open(db_path)
        except (MpdbCorruptionError, MpdbError) as e:
            p = Path(db_path)
            if p.exists():
                corrupt = p.with_name(f"{p.stem}.corrupt-{_ts()}{p.suffix}")
                try:
                    shutil.move(str(p), str(corrupt))
                    corrupt_moved_to = str(corrupt)
                except Exception:
                    raise MpdbError(f"Cannot open DB and cannot move corrupt file: {e}")
            db = _open(db_path)

        try:
            stats = run_import_on_db(
                db,
                source_path=source_path,
                source_kind=source_kind,
                mode=mode,
                wipe_prefixes=wipe_prefixes,
                prune_missing_assets=prune_missing_assets,
                store_raw_assets=store_raw_assets,
                store_binary_assets=store_binary_assets,
                store_raw_asset_keys=store_raw_asset_keys,
                store_modules_in_table=store_modules_in_table,
            )
            if migrate_data:
                if str(stats.get("semantic_source_kind") or "").lower() != "1cd":
                    raise ValueError("Business-data migration is available only for .1CD sources")
                from src.infra.onec.data_migration import migrate_onecd_data_to_mpdb

                data_manifest = migrate_onecd_data_to_mpdb(
                    db,
                    str(stats.get("semantic_source_path") or source_path),
                    table_names=data_tables or None,
                    limit_per_table=data_limit_per_table,
                    include_service=data_include_service,
                    include_deleted=data_include_deleted,
                    build_refs=not data_no_ref_index,
                    read_blobs=data_read_blobs,
                    target_prefix=data_target_prefix,
                    batch_size=max(1, int(data_batch_size or 1)),
                    storage_mode=data_storage_mode,
                    # Always include v8users so the system has access to user records.
                    force_include_table_names=("v8users",),
                )
                stats["data_migration_summary"] = data_manifest.get("summary")
                stats["data_migration_asset"] = data_manifest.get("asset_key")
                stats["data_migration_error"] = ""
                if com_data_audit:
                    from src.infra.onec.com_data_audit import (
                        build_com_data_audit,
                        store_com_data_audit_asset,
                    )
                    from src.infra.onec.com_source import OneCCOMConnection

                    with OneCCOMConnection.connect(
                        com_db_path or str(stats.get("semantic_source_path") or source_path),
                        user=com_user,
                        password=com_password,
                        connector_name=com_connector,
                    ) as com_conn:
                        com_report = build_com_data_audit(
                            com_conn,
                            direct_migration=data_manifest,
                            include_samples=com_include_samples,
                            sample_limit=com_sample_limit,
                            include_types=com_include_types or [],
                        )
                    stats["com_data_audit_asset"] = store_com_data_audit_asset(db, com_report)
                    stats["com_data_audit_summary"] = com_report.get("summary")
                    stats["com_data_audit_comparison"] = com_report.get("comparison")
                    stats["com_data_audit_error"] = ""
        finally:
            try:
                db.close()
            except Exception:
                pass

    raw_prefix = "onec_raw/"
    wipe_list  = [raw_prefix, "onec/"]
    parts = [
        "1C/BAS configuration import completed.",
        f"Mode: {stats.get('mode', mode)}.",
        "Import scope: metadata structure (forms/modules/etc.), not business data.",
        (
            f"Source resolved: {stats.get('detected_source_kind', source_kind or 'auto')}"
            f" -> {stats.get('semantic_source_kind', source_kind or 'xml')}"
            f" ({stats.get('semantic_source_path', source_path)})."
        ),
        f"Raw files stored as assets under '{raw_prefix}': {bool(stats.get('store_raw'))}.",
        f"Raw asset keys referenced in manifest: {bool(store_raw_asset_keys)}.",
        f"Binary assets imported (pictures, etc.): {bool(store_binary_assets)}.",
        f"Modules stored in table 'cfg_modules': {bool(stats.get('store_modules'))}.",
        f"Assets imported (raw): {stats.get('imported_files', 0)}.",
        f"Objects enriched with requisites/tabular-parts: {stats.get('enriched', 0)}.",
        f"Objects enriched with structural metadata: {stats.get('structural_metadata_enriched', 0)}.",
    ]
    data_summary = stats.get("data_migration_summary")
    if isinstance(data_summary, dict):
        parts.append(
            "1CD business data imported: "
            f"tables={data_summary.get('tables_imported', 0)}, "
            f"rows={data_summary.get('rows_imported', 0)}."
        )
    if stats.get("data_migration_asset"):
        parts.append(f"Data migration manifest saved: {stats['data_migration_asset']}")
    if stats.get("data_migration_error"):
        parts.append(f"Data migration warning: {stats['data_migration_error']}")
    if stats.get("com_data_audit_asset"):
        parts.append(f"COM data audit saved: {stats['com_data_audit_asset']}")
    if stats.get("com_data_audit_summary"):
        parts.append(f"COM data audit summary: {stats['com_data_audit_summary']}")
    if stats.get("com_data_audit_error"):
        parts.append(f"COM data audit warning: {stats['com_data_audit_error']}")
    source_snapshot = stats.get("source_snapshot") or {}
    compatibility = source_snapshot.get("compatibility") if isinstance(source_snapshot, dict) else {}
    if isinstance(compatibility, dict) and compatibility:
        parts.append(
            "1C compatibility snapshot: "
            f"xml={bool(compatibility.get('has_xmlconf'))}, "
            f"dt={bool(compatibility.get('has_dt_container'))}, "
            f"physical_schema={bool(compatibility.get('has_physical_schema'))}."
        )
    if stats.get("source_snapshot_asset"):
        parts.append(f"Source snapshot saved: {stats['source_snapshot_asset']}")
    if stats.get("source_snapshot_error"):
        parts.append(f"Source snapshot warning: {stats['source_snapshot_error']}")
    if stats.get("physical_mapping_asset"):
        parts.append(f"Physical mapping saved: {stats['physical_mapping_asset']}")
    if stats.get("physical_mapping_error"):
        parts.append(f"Physical mapping warning: {stats['physical_mapping_error']}")
    if stats.get("safe_import"):
        parts.append(f"Safe import mode: {stats.get('safe_import_mode') or 'backup-staging-validate-swap'}")
    if stats.get("backup_path"):
        parts.append(f"Runtime backup created: {stats['backup_path']}")
    if stats.get("wiped"):
        parts.append(f"Assets wiped by prefixes: {stats['wiped']} (prefixes: {', '.join(wipe_list)})")
    if stats.get("pruned_raw") or stats.get("pruned_sem"):
        parts.append(f"Assets pruned (raw): {stats.get('pruned_raw', 0)}.")
        parts.append(f"Assets pruned (semantic): {stats.get('pruned_sem', 0)}.")
    if did_backup and backup_path:
        parts.append(f"Backup created: {backup_path}")
    if corrupt_moved_to:
        parts.append(f"Corrupt DB moved to: {corrupt_moved_to}")

    return "\n".join(parts)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Import 1C/BAS configuration dump into mpdb")
    parser.add_argument("--db",   required=True, help="Path to mpdb file")
    parser.add_argument("--src",  required=True, help="Path to XMLConf, ConfigFiles.zip, 1Cv8.dt or 1Cv8.1CD")
    parser.add_argument("--kind", choices=["auto", "zip", "xml", "dt", "1cd"], default="auto")
    parser.add_argument("--mode", choices=["hard"], default="hard")
    parser.add_argument("--wipe-prefixes",    action="store_true")
    parser.add_argument("--no-wipe-prefixes", action="store_true")
    parser.add_argument("--prune-missing",    action="store_true")
    parser.add_argument("--no-prune-missing", action="store_true")
    parser.add_argument("--migrate-data", action="store_true", help="Import physical .1CD business data into mpdb tables")
    parser.add_argument("--data-table", action="append", help="Physical .1CD table to import; can be repeated")
    parser.add_argument("--data-limit", type=int, default=0, help="Max rows per imported .1CD table")
    parser.add_argument("--data-include-service", action="store_true", help="Include service .1CD tables")
    parser.add_argument("--data-include-deleted", action="store_true", help="Include deleted .1CD rows")
    parser.add_argument("--data-no-ref-index", action="store_true", help="Do not build the _IDRRef reference index")
    parser.add_argument("--data-read-blobs", action="store_true", help="Read full BLOB values instead of previews")
    parser.add_argument("--data-target-prefix", default="onec", help="Target mpdb table prefix")
    parser.add_argument("--data-batch-size", type=int, default=5000, help="Batch insert size for migrated data")
    parser.add_argument("--data-storage-mode", choices=["packed", "per_table"], default="packed", help="Storage layout for migrated .1CD rows")
    parser.add_argument("--com-audit", action="store_true", help="Run optional 1C COM data audit after direct .1CD data migration")
    parser.add_argument("--com-db-path", default="", help="1C COM infobase path/connection string; defaults to resolved .1CD parent")
    parser.add_argument("--com-user", default="", help="1C COM username")
    parser.add_argument("--com-password", default="", help="1C COM password")
    parser.add_argument("--com-connector", default="V83.COMConnector", help="1C COM connector ProgID")
    parser.add_argument("--com-include-samples", action="store_true", help="Store small COM sample rows in audit report")
    parser.add_argument("--com-sample-limit", type=int, default=3, help="Sample rows per object for COM audit")
    parser.add_argument("--com-type", action="append", help="Restrict COM audit to MetaPlatform object type; can be repeated")

    args = parser.parse_args()
    wipe  = not args.no_wipe_prefixes  if args.no_wipe_prefixes  else True
    prune = not args.no_prune_missing  if args.no_prune_missing  else True

    print(import_onec_configuration(
        db_path=args.db,
        source_path=args.src,
        source_kind=args.kind,
        mode=args.mode,
        wipe_prefixes=wipe,
        prune_missing_assets=prune,
        migrate_data=bool(args.migrate_data),
        data_tables=args.data_table or None,
        data_limit_per_table=args.data_limit if args.data_limit and args.data_limit > 0 else None,
        data_include_service=bool(args.data_include_service),
        data_include_deleted=bool(args.data_include_deleted),
        data_no_ref_index=bool(args.data_no_ref_index),
        data_read_blobs=bool(args.data_read_blobs),
        data_target_prefix=str(args.data_target_prefix or "onec"),
        data_batch_size=max(1, int(args.data_batch_size or 1)),
        data_storage_mode=str(args.data_storage_mode or "packed"),
        com_data_audit=bool(args.com_audit),
        com_db_path=str(args.com_db_path or ""),
        com_user=str(args.com_user or ""),
        com_password=str(args.com_password or ""),
        com_connector=str(args.com_connector or "V83.COMConnector"),
        com_include_samples=bool(args.com_include_samples),
        com_sample_limit=max(0, int(args.com_sample_limit or 0)),
        com_include_types=args.com_type or None,
        # no runtime_url → local fallback
    ))
