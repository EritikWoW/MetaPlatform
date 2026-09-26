from __future__ import annotations

import shutil
import time
from pathlib import Path

from src.configurator.cache.structure_cache import (
    drop_structure_cache,
    save_structure_cache_meta_only,
    save_structure_cache_snapshot,
)

from .server_state import RpcResponse, STATE_DBS, STATE_IMPORTS, STATE_SESSIONS, _nullctx
from .server_handlers_manifest import (
    STATE_MANIFEST_INFO_CACHE,
    STATE_MANIFEST_LIST_CACHE,
    STATE_MANIFEST_SCHEMA_CACHE,
)
from .server_handlers_modules import (
    STATE_MODULE_COMPLETION_CACHE,
    STATE_MODULE_RESOLUTION_CACHE,
    STATE_MODULE_SOURCE_CACHE,
    STATE_WORKSPACE_SEMANTIC_INDEX,
)


def handle_import_action(handler, action: str, payload: dict) -> RpcResponse | None:
    if action == "onec.import_sessions":
        active_only = bool(payload.get("active_only") or False)
        history_limit = max(0, int(payload.get("history_limit") or 0))
        return RpcResponse(
            "ok",
            {
                "sessions": STATE_IMPORTS.list(
                    active_only=active_only,
                    history_limit=history_limit,
                )
            },
        )

    if action == "onec.import_status":
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            return RpcResponse("error", error="session_id is required")
        history_limit = max(0, int(payload.get("history_limit") or 20))
        return RpcResponse("ok", STATE_IMPORTS.snapshot(session_id, history_limit=history_limit))

    if action != "onec.import":
        return None

    session_id = str(payload.get("session_id") or "").strip()

    def _set_status(
        progress: int,
        message: str,
        *,
        phase: str,
        current: int | None = None,
        total: int | None = None,
        failed: bool = False,
        meta: dict | None = None,
    ) -> None:
        if not session_id:
            return
        state = {
            "progress": max(0, min(100, int(progress))),
            "message": str(message or "").strip(),
            "phase": str(phase or "").strip(),
            "failed": bool(failed),
            "updated_at": time.time(),
        }
        if current is not None:
            state["current"] = int(current)
        if total is not None:
            state["total"] = int(total)
        STATE_IMPORTS.set(session_id, state, meta=meta)

    live_db = handler._require_db(payload)
    if isinstance(live_db, RpcResponse):
        return live_db
    db = live_db
    staging_db = None
    staging_path = ""
    backup_path = ""
    active_db_uid = ""
    active_db_path = ""
    swapped_to_live = False
    source_path = str(payload.get("source_path") or "")
    source_kind = str(payload.get("source_kind") or "zip")
    if not source_path:
        return RpcResponse("error", error="source_path is required")
    try:
        import traceback as _tb2
        import os as _os

        def _log(msg: str) -> None:
            _text = str(msg or "")
            print(f"[onec.import] {_text}", flush=True)
            STATE_IMPORTS.append_event(session_id, "log", message=_text)

        _enriched = 0
        _set_status(
            2,
            "Підготовка імпорту конфігурації...",
            phase="start",
            meta={
                "runtime_session_id": session_id,
                "source_path": source_path,
                "source_kind": source_kind,
                "migrate_data": bool(payload.get("migrate_data", False)),
                "store_raw_asset_keys": bool(payload.get("store_raw_asset_keys", False)),
                "store_binary_assets": bool(payload.get("store_binary_assets", False)),
                "store_modules_in_table": bool(payload.get("store_modules_in_table", True)),
                "data_storage_mode": str(payload.get("data_storage_mode") or "packed"),
            },
        )
        _log(f"START  source_kind={source_kind!r}  path={source_path!r}")
        from src.infra.onec.source_compat import resolve_onec_source

        _resolved = resolve_onec_source(source_path, source_kind)
        _effective_path = str(_resolved.semantic_path or source_path)
        _effective_kind = str(_resolved.semantic_kind or source_kind or "xml")
        _log(
            "  resolved source: "
            f"detected={_resolved.detected_kind!r} -> semantic={_effective_kind!r} "
            f"path={_effective_path!r}"
        )

        sid_for_db = str(payload.get("session_id") or "")
        # The pool/session identity remains stable across staging swaps, while
        # the replacement file has its own internal db_uid. Using the latter
        # loses the registered live path and makes the next import fail.
        active_db_uid = (
            str(STATE_SESSIONS.get_active_db_uid(sid_for_db) or "")
            if sid_for_db
            else ""
        )
        if not active_db_uid:
            active_db_uid = str(getattr(live_db, "db_uid", "") or "")
        active_db_path = str(STATE_DBS.get_path(active_db_uid) or "") if active_db_uid else ""
        if not active_db_uid or not active_db_path:
            raise RuntimeError("Active DB path is required for safe import")

        live_path = Path(active_db_path)
        if not live_path.exists():
            raise FileNotFoundError(f"Active DB file not found: {live_path}")

        _set_status(4, "Підготовка staging DB...", phase="backup")
        _log("safe import — checkpoint, backup live DB, create fresh staging...")
        try:
            live_db.checkpoint(durable=True, keep_wal_bytes=0)
            _log("  live checkpoint OK")
        except Exception as _ce:
            _log(f"  live checkpoint warning: {_ce}")

        _ts = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
        backup_path = str(live_path.with_name(f"{live_path.stem}.backup-{_ts}{live_path.suffix}"))
        staging_path = str(live_path.with_name(f"{live_path.stem}.import-staging-{_ts}{live_path.suffix}"))
        # Backup the current live DB (used for rollback if import fails).
        shutil.copy2(str(live_path), backup_path)
        # Staging is a fresh empty DB — not a copy of live.
        # This prevents old data tables from accumulating across re-imports.
        from src.mpdb.mpdb import Mpdb

        staging_db = Mpdb(staging_path)
        db = staging_db
        _log(f"  backup={backup_path!r}")
        _log(f"  staging={staging_path!r} (fresh empty DB)")

        _set_status(5, "Ініціалізація staging DB...", phase="reset")
        _log("phase 1/4 — seeding fresh staging manifest...")
        from src.configurator.persistence import manifest_io as _mio

        _mio.ensure_manifest(db, seed_defaults=True)  # type: ignore[attr-defined]
        try:
            from src.configurator.persistence.modules_tables import ensure_modules_tables
            ensure_modules_tables(db)
        except Exception as _me:
            _log(f"  modules table init warning: {_me}")
        _objs_after_reset = _mio.list_objects(db, hydrate_payload=False)
        _groups_after_reset = [o for o in _objs_after_reset if o.kind == "group"]
        _log(f"  fresh staging ready  total={len(_objs_after_reset)}  groups={len(_groups_after_reset)}")
        _log(f"  group types: {[o.type for o in _groups_after_reset]}")

        _set_status(18, "Імпорт об'єктів manifest...", phase="manifest")
        _log("phase 2/4 — importing manifest objects (forms/modules/commands)...")
        from src.infra.onec.importer import ZipSource, make_directory_source, import_manifest_objects
        from src.infra.onec.onecd_source import OneCDConfigSource

        if _effective_kind.lower() == "zip":
            _src_ctx = ZipSource(_effective_path)
        elif _effective_kind.lower() == "1cd":
            _src_ctx = OneCDConfigSource(_effective_path)
        else:
            root_dir = _effective_path
            if _os.path.isfile(root_dir):
                root_dir = _os.path.dirname(root_dir)
            _src_ctx = make_directory_source(root_dir)
            _log(f"  source type: {type(_src_ctx).__name__}")

        with _src_ctx if hasattr(_src_ctx, "__enter__") else _nullctx(_src_ctx) as _src:
            _paths = _src.list_files()
            _log(f"  files in dump: {len(_paths)}")
            _log(f"  first 10 paths: {_paths[:10]}")

            def _manifest_progress(current: int, total: int, message: str) -> None:
                _message = str(message or "Імпорт об'єктів manifest...")
                _msg_lc = _message.lower()
                _ratio = int(current) / max(int(total), 1)
                if (
                    "writing manifest payload assets" in _msg_lc
                    or "writing manifest rows" in _msg_lc
                    or "finalizing manifest batch" in _msg_lc
                ):
                    _percent = 36 + int(3 * _ratio)
                elif (
                    "writing module assets" in _msg_lc
                    or "writing module rows" in _msg_lc
                    or "finalizing modules batch" in _msg_lc
                ):
                    _percent = 39 + int(2 * _ratio)
                elif "payload updates" in _msg_lc:
                    _percent = 41 + int(1 * _ratio)
                else:
                    _percent = 18 + int(18 * _ratio)
                _set_status(
                    _percent,
                    _message,
                    phase="manifest",
                    current=current,
                    total=total,
                )

            import_manifest_objects(
                db,
                _src,
                _paths,
                raw_prefix="onec_raw/",
                store_raw_asset_keys=bool(payload.get("store_raw_asset_keys", False)),
                store_picture_assets=bool(payload.get("store_binary_assets", False)),
                store_modules_in_table=bool(payload.get("store_modules_in_table", True)),
                progress=_manifest_progress,
            )
            _objs_after = _mio.list_objects(db, hydrate_payload=False)
            _log(f"  manifest objects after import: {len(_objs_after)}")
            _log(f"  manifest objects after import: {len(_objs_after)}")

            _set_status(42, "Парсинг XML-об'єктів...", phase="parse")
            _log("phase 3/4 — enriching objects with requisites/tabular-parts...")
            from src.infra.onec.onec_requisites_enrich import (
                metadata_ref_for_manifest_object,
                resolve_subsystem_payload,
            )
            from src.infra.onec.onec_requisites_parser import OneCXmlParser, enrich_manifest_payload
            from src.infra.onec.importer import to_ascii_identifier as _tr

            _parser = OneCXmlParser()
            def _parse_progress(current: int, total: int, message: str) -> None:
                _set_status(
                    42 + int(18 * (int(current) / max(int(total), 1))),
                    str(message or "Парсинг XML-об'єктів..."),
                    phase="parse",
                    current=current,
                    total=total,
                )

            _parsed = _parser.parse_all(_src, progress=_parse_progress)
            _log(f"  parsed XML objects: {len(_parsed)}")
            if _parsed:
                _log(f"  sample parsed: {[(o.obj_type, o.name, o.uuid[:8]) for o in _parsed[:5]]}")

            _by_uuid = {o.uuid: o for o in _parsed if o.uuid}
            _by_name = {(_o.obj_type, _tr(_o.name)): _o for _o in _parsed if _o.name}
            _log(f"  UUID index size: {len(_by_uuid)}  name index: {len(_by_name)}")
            _parsed_types = {str(o.obj_type or "").strip() for o in _parsed if str(o.obj_type or "").strip()}

            _payloads_by_guid: dict[str, dict] = {}
            _processed = 0
            _missed = 0
            _manifest_objects = [o for o in _objs_after if o.kind == "object" and o.type in _parsed_types]
            _total_objects = len(_manifest_objects)
            _meta_ref_to_guid: dict[str, str] = {}
            for _manifest_obj in _objs_after:
                if _manifest_obj.kind != "object":
                    continue
                _imp_ref = _manifest_obj.payload.get("imported", {}) if isinstance(_manifest_obj.payload, dict) else {}
                _meta_ref = metadata_ref_for_manifest_object(
                    obj_type=_manifest_obj.type,
                    name=_manifest_obj.name,
                    origin_path=str(_imp_ref.get("origin") or ""),
                )
                if _meta_ref:
                    _meta_ref_to_guid.setdefault(_meta_ref, _manifest_obj.guid)
            _log(f"  enrich scope objects={_total_objects} types={sorted(_parsed_types)}")
            for _mo in _manifest_objects:
                _processed += 1
                if _mo.kind != "object":
                    continue
                _imp = _mo.payload.get("imported", {}) if isinstance(_mo.payload, dict) else {}
                _uid = str(_imp.get("src_uid") or "").strip()
                _p = _by_uuid.get(_uid) or _by_name.get((_mo.type, _mo.name))
                if _p is None:
                    _missed += 1
                    if _processed == _total_objects or _processed % 25 == 0:
                        _set_status(
                            60 + int(34 * (_processed / max(_total_objects, 1))),
                            f"Збагачення об'єктів: {_processed}/{_total_objects}",
                            phase="enrich",
                            current=_processed,
                            total=_total_objects,
                        )
                    continue
                try:
                    _enriched_payload = enrich_manifest_payload(_mo.payload or {}, _p)
                    _payloads_by_guid[_mo.guid] = resolve_subsystem_payload(
                        _enriched_payload,
                        meta_ref_to_guid=_meta_ref_to_guid,
                    )
                except Exception as _ee:
                    _log(f"  enrich error for {_mo.name!r}: {_ee}")
                if _processed == _total_objects or _processed % 25 == 0:
                    _set_status(
                        60 + int(34 * (_processed / max(_total_objects, 1))),
                        f"Збагачення об'єктів: {_processed}/{_total_objects}",
                        phase="enrich",
                        current=_processed,
                        total=_total_objects,
                    )
            _set_status(94, "Запис batch-оновлень manifest...", phase="enrich")
            _enriched = _mio.bulk_update_payloads(db, _payloads_by_guid)
            _log(f"  enriched={_enriched}  no_match={_missed}")

        _set_status(97, "Аналіз структури 1C...", phase="finalize")
        _log("phase 4/4 — done")
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

        _source_snapshot = None
        _source_snapshot_asset = ""
        _source_snapshot_error = ""
        _storage_alignment = None
        _storage_alignment_asset = ""
        _storage_alignment_error = ""
        _physical_mapping = None
        _physical_mapping_asset = ""
        _physical_mapping_error = ""
        _structural_metadata_enriched = 0
        _data_migration = None
        _data_migration_error = ""
        _com_data_audit = None
        _com_data_audit_asset = ""
        _com_data_audit_error = ""
        try:
            _source_snapshot = build_onec_compatibility_snapshot(source_path, source_kind)
            _source_snapshot_asset = store_source_snapshot_asset(
                db,
                _source_snapshot,
                asset_key=SOURCE_SNAPSHOT_ASSET_KEY,
            )
        except Exception as _snapshot_exc:
            _source_snapshot_error = str(_snapshot_exc)
            _log(f"  source snapshot warning: {_snapshot_exc}")

        try:
            if _source_snapshot is not None:
                _storage_alignment = build_storage_alignment_report_from_snapshot(
                    _source_snapshot,
                    source_path=source_path,
                )
                _storage_alignment_asset = store_storage_alignment_asset(
                    db,
                    _storage_alignment,
                    asset_key=STORAGE_ALIGNMENT_ASSET_KEY,
                )
            _log(
                "  source snapshot saved "
                f"asset={_source_snapshot_asset!r} "
                f"available={(_source_snapshot or {}).get('available_sources', [])!r}"
            )
            _log(
                "  storage alignment saved "
                f"asset={_storage_alignment_asset!r} "
                f"score={((_storage_alignment or {}).get('coverage') or {}).get('overall_score')!r}"
            )
        except Exception as _alignment_exc:
            _storage_alignment_error = str(_alignment_exc)
            _log(f"  storage alignment warning: {_alignment_exc}")

        try:
            _physical_mapping = build_physical_mapping_report(
                source_path,
                source_kind,
                snapshot=_source_snapshot,
            )
            _physical_mapping_asset = store_physical_mapping_asset(
                db,
                _physical_mapping,
                asset_key=PHYSICAL_MAPPING_ASSET_KEY,
            )
            _log(
                "  physical mapping saved "
                f"asset={_physical_mapping_asset!r} "
                f"objects={((_physical_mapping or {}).get('summary') or {}).get('object_blueprint_count')!r}"
            )
        except Exception as _mapping_exc:
            _physical_mapping_error = str(_mapping_exc)
            _log(f"  physical mapping warning: {_mapping_exc}")

        if _physical_mapping:
            try:
                _set_status(98, "Синхронізація структур метаданих...", phase="finalize")
                _structural_metadata_enriched = int(
                    apply_onec_structural_metadata(db, _physical_mapping) or 0
                )
                _log(
                    "  structural metadata synced "
                    f"objects={_structural_metadata_enriched!r}"
                )
            except Exception as _structural_exc:
                _log(f"  structural metadata warning: {_structural_exc}")

        if bool(payload.get("migrate_data", False)):
            try:
                if _effective_kind.lower() != "1cd":
                    raise ValueError("Business-data migration is available only for .1CD sources")
                _set_status(97, "Міграція даних 1CD...", phase="data")
                from src.infra.onec.data_migration import migrate_onecd_data_to_mpdb

                _data_limit_raw = payload.get("data_limit_per_table")
                _data_limit = None
                if _data_limit_raw not in (None, "", 0, "0"):
                    _data_limit = max(1, int(_data_limit_raw))
                _data_last_log = {"at": 0.0}

                def _data_progress(event: dict) -> None:
                    _total_tables = max(1, int(event.get("total_tables") or 0))
                    _current_table = max(0, int(event.get("current_table") or 0))
                    _table_rows = max(0, int(event.get("table_rows") or 0))
                    _table_total = max(0, int(event.get("table_total") or 0))
                    _rows_imported = max(0, int(event.get("rows_imported") or 0))
                    _table_ratio = 0.0
                    if _table_total > 0:
                        _table_ratio = min(1.0, _table_rows / max(_table_total, 1))
                    _overall_ratio = min(
                        1.0,
                        max(0.0, ((_current_table - 1) + _table_ratio) / _total_tables),
                    )
                    _percent = 97 + int(2 * _overall_ratio)
                    _table_name = str(event.get("table") or "").strip()
                    _stage = str(event.get("stage") or "").strip()
                    if _table_name:
                        if _table_total > 0:
                            _msg = (
                                f"Міграція даних 1CD: {_current_table}/{_total_tables} "
                                f"{_table_name} ({_table_rows}/{_table_total}, всього рядків: {_rows_imported})"
                            )
                        else:
                            _msg = (
                                f"Міграція даних 1CD: {_current_table}/{_total_tables} "
                                f"{_table_name} (всього рядків: {_rows_imported})"
                            )
                    else:
                        _msg = str(event.get("message") or "Міграція даних 1CD...")
                    _set_status(
                        _percent,
                        _msg,
                        phase="data",
                        current=_current_table,
                        total=_total_tables,
                    )
                    _now = time.perf_counter()
                    if _stage in {"selected_tables", "reference_index", "done"} or _now - _data_last_log["at"] >= 10.0:
                        _data_last_log["at"] = _now
                        _error = str(event.get("error") or "").strip()
                        _log(
                            "  data migration progress "
                            f"stage={_stage!r} table={_current_table}/{_total_tables} "
                            f"rows={_rows_imported} current={_table_rows}/{_table_total} "
                            f"name={_table_name!r}"
                            + (f" error={_error!r}" if _error else "")
                        )

                _data_migration = migrate_onecd_data_to_mpdb(
                    db,
                    _effective_path,
                    table_names=payload.get("data_tables") or None,
                    limit_per_table=_data_limit,
                    include_service=bool(payload.get("data_include_service", False)),
                    include_deleted=bool(payload.get("data_include_deleted", False)),
                    build_refs=not bool(payload.get("data_no_ref_index", False)),
                    read_blobs=bool(payload.get("data_read_blobs", False)),
                    target_prefix=str(payload.get("data_target_prefix") or "onec"),
                    batch_size=max(1, int(payload.get("data_batch_size") or 5000)),
                    storage_mode=str(payload.get("data_storage_mode") or "packed"),
                    force_include_table_names=tuple(payload.get("data_force_include_tables") or ("v8users",)),
                    progress=_data_progress,
                )
                _log(
                    "  data migration completed "
                    f"storage_mode={(_data_migration or {}).get('storage_mode')!r} "
                    f"packed_table={(_data_migration or {}).get('packed_table')!r} "
                    f"summary={(_data_migration or {}).get('summary')!r}"
                )
            except Exception as _data_exc:
                _data_migration_error = str(_data_exc)
                raise RuntimeError(f"1CD data migration failed: {_data_exc}") from _data_exc

        if bool(
            payload.get("com_data_audit", False)
            or payload.get("com_probe_data", False)
            or payload.get("com_diagnostics", False)
        ):
            try:
                _set_status(99, "COM-аудит повноти даних 1C...", phase="data_com_audit")
                from src.infra.onec.com_data_audit import (
                    build_com_data_audit,
                    store_com_data_audit_asset,
                )
                from src.infra.onec.com_source import OneCCOMConnection

                _com_db_path = str(
                    payload.get("com_db_path")
                    or payload.get("db_path")
                    or _effective_path
                    or source_path
                ).strip()
                _com_user = str(payload.get("com_user") or payload.get("db_user") or "").strip()
                _com_password = str(
                    payload.get("com_password") or payload.get("db_password") or ""
                )
                _com_connector = str(payload.get("com_connector") or "V83.COMConnector").strip()
                _com_include_samples = bool(payload.get("com_include_samples", False))
                _com_sample_limit = max(0, int(payload.get("com_sample_limit") or 3))
                _com_types_raw = payload.get("com_include_types") or []
                _com_include_types = list(_com_types_raw) if isinstance(_com_types_raw, (list, tuple)) else []
                _last_com_log = {"at": 0.0}

                def _com_progress(event: dict) -> None:
                    _stage = str(event.get("stage") or "").strip()
                    _current = int(event.get("current") or 0)
                    _total = int(event.get("total") or event.get("total_objects") or 0)
                    _name = str(event.get("object") or "").strip()
                    if _total > 0 and _current > 0:
                        _msg = f"COM-аудит даних 1C: {_current}/{_total} {_name}".strip()
                    else:
                        _msg = "COM-аудит даних 1C..."
                    _set_status(99, _msg, phase="data_com_audit", current=_current, total=_total)
                    _now = time.perf_counter()
                    if _stage == "metadata" or _now - _last_com_log["at"] >= 10.0:
                        _last_com_log["at"] = _now
                        _log(
                            "  COM data audit progress "
                            f"stage={_stage!r} current={_current}/{_total} object={_name!r}"
                        )

                with OneCCOMConnection.connect(
                    _com_db_path,
                    user=_com_user,
                    password=_com_password,
                    connector_name=_com_connector,
                ) as _com_conn:
                    _com_data_audit = build_com_data_audit(
                        _com_conn,
                        direct_migration=_data_migration if isinstance(_data_migration, dict) else None,
                        include_samples=_com_include_samples,
                        sample_limit=_com_sample_limit,
                        include_types=_com_include_types,
                        progress=_com_progress,
                    )
                _com_data_audit_asset = store_com_data_audit_asset(db, _com_data_audit)
                _log(
                    "  COM data audit saved "
                    f"asset={_com_data_audit_asset!r} "
                    f"summary={(_com_data_audit or {}).get('summary')!r}"
                )
            except Exception as _com_exc:
                _com_data_audit_error = str(_com_exc)
                _log(f"  COM data audit warning: {_com_exc}")

        # Schema deployment is deferred until after swap so it does not block
        # the import from completing. Tables are created lazily on first use.

        _set_status(98, "Фіналізація імпорту...", phase="finalize")

        stats = {
            "imported_files": len(_paths),
            "enriched": _enriched,
            "structural_metadata_enriched": _structural_metadata_enriched,
            "wiped": 0,
            "pruned_raw": 0,
            "pruned_sem": 0,
            "mode": str(payload.get("mode") or "hard"),
            "store_raw": bool(payload.get("store_raw_assets", False)),
            "store_modules": bool(payload.get("store_modules_in_table", True)),
            "requested_source_kind": _resolved.requested_kind,
            "detected_source_kind": _resolved.detected_kind,
            "semantic_source_kind": _resolved.semantic_kind,
            "semantic_source_path": _resolved.semantic_path,
            "source_analysis": dict(_resolved.analysis or {}),
            "source_snapshot": _source_snapshot,
            "source_snapshot_asset": _source_snapshot_asset,
            "source_snapshot_error": _source_snapshot_error,
            "storage_alignment": _storage_alignment,
            "storage_alignment_asset": _storage_alignment_asset,
            "storage_alignment_error": _storage_alignment_error,
            "physical_mapping_summary": (_physical_mapping or {}).get("summary")
            if isinstance(_physical_mapping, dict) else None,
            "physical_mapping_asset": _physical_mapping_asset,
            "physical_mapping_error": _physical_mapping_error,
            "data_migration_summary": (_data_migration or {}).get("summary")
            if isinstance(_data_migration, dict) else None,
            "data_migration_asset": (_data_migration or {}).get("asset_key")
            if isinstance(_data_migration, dict) else "",
            "data_migration_storage_mode": (_data_migration or {}).get("storage_mode")
            if isinstance(_data_migration, dict) else "",
            "data_migration_packed_table": (_data_migration or {}).get("packed_table")
            if isinstance(_data_migration, dict) else "",
            "data_migration_error": _data_migration_error,
            "com_data_audit_summary": (_com_data_audit or {}).get("summary")
            if isinstance(_com_data_audit, dict) else None,
            "com_data_audit_comparison": (_com_data_audit or {}).get("comparison")
            if isinstance(_com_data_audit, dict) else None,
            "com_data_audit_asset": _com_data_audit_asset,
            "com_data_audit_error": _com_data_audit_error,
            "safe_import": True,
            "safe_import_mode": "backup-staging-validate-swap",
            "backup_path": backup_path,
            "staging_path": staging_path,
        }
        _set_status(99, "Перевірка staging DB...", phase="finalize")
        try:
            db.checkpoint(durable=True, keep_wal_bytes=0)
            _validation_rows = _mio.list_object_rows(db)
            if not _validation_rows:
                raise RuntimeError("Staging manifest is empty after import")
            stats["validated_manifest_rows"] = len(_validation_rows)
            # This in-process pass validates every referenced page while the
            # staging handle is still open.  An offline scan is performed after
            # close below so a healthy cache cannot hide damaged disk bytes.
            db.verify_integrity()
            stats["validated_full_integrity"] = True
            _log(
                "  staging validation OK  "
                f"manifest_rows={len(_validation_rows)} "
                f"full_integrity={bool(stats['validated_full_integrity'])}"
            )
        except Exception as _validation_exc:
            raise RuntimeError(f"Staging validation failed: {_validation_exc}") from _validation_exc

        if staging_db is not None:
            try:
                staging_db.close()
            finally:
                staging_db = None
        from src.mpdb.doctor import check as check_mpdb

        _offline_report = check_mpdb(staging_path)
        if not _offline_report.ok:
            _issues = "; ".join(
                f"{issue.code} page={issue.page_id}: {issue.message}"
                for issue in _offline_report.issues[:10]
            )
            raise RuntimeError(
                "Staging offline integrity validation failed: "
                f"bad_pages={_offline_report.pages_bad}; {_issues}"
            )
        stats["validated_offline_pages"] = int(_offline_report.pages_checked)
        _set_status(99, "Активація staging DB...", phase="finalize")
        db = STATE_DBS.replace_with_file(active_db_uid, staging_path, backup_path=backup_path)
        swapped_to_live = True
        active_db_path = str(STATE_DBS.get_path(active_db_uid) or active_db_path)
        # The replacement can preserve a similar file size/mtime, so stat-based
        # cache validation alone cannot prove that cached GUIDs still exist.
        STATE_MANIFEST_INFO_CACHE.invalidate(active_db_uid)
        STATE_MANIFEST_LIST_CACHE.invalidate(active_db_uid)
        STATE_MANIFEST_SCHEMA_CACHE.invalidate(active_db_uid)
        STATE_MODULE_RESOLUTION_CACHE.invalidate(active_db_uid)
        # The staging swap changes both module text and the manifest.  Do not
        # leave source/completion/semantic caches pointing at the old database
        # contents even when the replacement preserves file size or mtime.
        STATE_MODULE_COMPLETION_CACHE.invalidate(active_db_uid)
        STATE_MODULE_SOURCE_CACHE.invalidate(active_db_uid)
        STATE_WORKSPACE_SEMANTIC_INDEX.invalidate(active_db_uid)
        _log("  staging swapped into live DB")
        try:
            db_uid = active_db_uid or str(getattr(db, "db_uid", "") or "")
            db_path = active_db_path or (str(STATE_DBS.get_path(db_uid) or "") if db_uid else "")
            if db_uid and db_path:
                _set_status(99, "Збереження structure cache...", phase="finalize")
                _cache_started = time.perf_counter()
                try:
                    # hydrate_payload=False: skip 9k+ external asset reads — tree view
                    # only needs guid/type/kind/name/title/parent_guid
                    _final_objects = _mio.list_objects(db, hydrate_payload=False)
                    _meta = save_structure_cache_snapshot(
                        db_path,
                        db_uid=db_uid,
                        generated_at=int(time.time()),
                        objects=_final_objects,
                    )
                    _cache_log = (
                        f"  structure cache saved objects={_meta.object_count} "
                        f"took={time.perf_counter() - _cache_started:.3f}s"
                    )
                except Exception:
                    _final_rows = _mio.list_object_rows(db)
                    from src.configurator.cache.structure_cache import compute_structure_hash

                    _meta = save_structure_cache_meta_only(
                        db_path,
                        db_uid=db_uid,
                        structure_hash=compute_structure_hash(_final_rows),
                        object_count=len(_final_rows),
                        generated_at=int(time.time()),
                    )
                    _cache_log = (
                        f"  structure cache meta saved objects={_meta.object_count} "
                        f"took={time.perf_counter() - _cache_started:.3f}s"
                    )
                STATE_MANIFEST_INFO_CACHE.put(
                    db_uid,
                    {
                        "db_uid": db_uid,
                        "db_path": db_path,
                        "structure_hash": _meta.structure_hash,
                        "object_count": _meta.object_count,
                        "generated_at": _meta.generated_at,
                        "db_mtime_ns": _meta.db_mtime_ns,
                        "db_size": _meta.db_size,
                    },
                )
                _log(_cache_log)
            else:
                if db_uid:
                    STATE_MANIFEST_INFO_CACHE.invalidate(db_uid)
                if db_path:
                    drop_structure_cache(db_path)
        except Exception:
            try:
                if db_uid:
                    STATE_MANIFEST_INFO_CACHE.invalidate(db_uid)
                if db_path:
                    drop_structure_cache(db_path)
            except Exception:
                pass
        _set_status(100, "Імпорт конфігурації завершено.", phase="done")
        _log(f"DONE  stats={stats}")
        return RpcResponse("ok", stats)
    except Exception as e:
        try:
            if staging_db is not None:
                staging_db.close()
        except Exception:
            pass
        if staging_path and not swapped_to_live:
            try:
                Path(staging_path).unlink(missing_ok=True)
            except Exception:
                pass
        _set_status(0, f"Помилка імпорту: {e}", phase="failed", failed=True)
        STATE_IMPORTS.append_event(session_id, "error", message=str(e))
        print(f"[onec.import] ERROR: {e}", flush=True)
        print(_tb2.format_exc(), flush=True)
        return RpcResponse("error", error=f"onec.import: {e}")
