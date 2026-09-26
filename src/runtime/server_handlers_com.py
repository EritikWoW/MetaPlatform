"""Runtime RPC handlers for 1C COM connector operations.

Actions:
    com.test_connection  — verify COM connection is working
    com.counts           — count metadata objects per type in 1C
    com.diagnose         — compare 1C metadata with current manifest
    com.import_metadata  — import all metadata from 1C COM into the DB
    com.query_data       — run a 1C query and return rows
"""
from __future__ import annotations

import json
import time
from typing import Any

from .server_state import RpcResponse, STATE_DBS, STATE_SESSIONS


def _get_db(handler, payload: dict) -> Any:
    """Get the live Mpdb instance from the session, or return RpcResponse error."""
    db = handler._require_db(payload)
    return db


def handle_com_action(handler, action: str, payload: dict) -> "RpcResponse | None":
    if not action.startswith("com."):
        return None

    db_path = str(payload.get("db_path") or "").strip()
    db_user = str(payload.get("db_user") or "").strip()
    db_pass = str(payload.get("db_password") or "").strip()
    connector_name = str(payload.get("connector") or "V83.COMConnector").strip()

    # ------------------------------------------------------------------ #
    # com.test_connection
    # ------------------------------------------------------------------ #
    if action == "com.test_connection":
        if not db_path:
            return RpcResponse("error", error="db_path is required")
        try:
            from src.infra.onec.com_source import OneCCOMConnection
            with OneCCOMConnection.connect(
                db_path, user=db_user, password=db_pass, connector_name=connector_name
            ) as conn:
                return RpcResponse("ok", {
                    "config_name": conn.config_name,
                    "config_version": conn.config_version,
                    "connected": True,
                })
        except Exception as exc:
            return RpcResponse("error", error=f"COM connection failed: {exc}")

    # ------------------------------------------------------------------ #
    # com.counts
    # ------------------------------------------------------------------ #
    if action == "com.counts":
        if not db_path:
            return RpcResponse("error", error="db_path is required")
        try:
            from src.infra.onec.com_source import OneCCOMConnection
            with OneCCOMConnection.connect(
                db_path, user=db_user, password=db_pass, connector_name=connector_name
            ) as conn:
                counts = conn.counts()
                total = sum(v for v in counts.values() if v > 0)
                non_empty = {k: v for k, v in counts.items() if v > 0}
                return RpcResponse("ok", {
                    "config_name": conn.config_name,
                    "total": total,
                    "counts": non_empty,
                })
        except Exception as exc:
            return RpcResponse("error", error=f"COM counts failed: {exc}")

    # ------------------------------------------------------------------ #
    # com.diagnose  — compare 1C with imported manifest
    # ------------------------------------------------------------------ #
    if action == "com.diagnose":
        if not db_path:
            return RpcResponse("error", error="db_path is required")
        live_db = _get_db(handler, payload)
        if isinstance(live_db, RpcResponse):
            return live_db
        try:
            from src.infra.onec.com_source import OneCCOMConnection, diagnose_vs_manifest
            from src.configurator.persistence.manifest_io import list_objects

            with OneCCOMConnection.connect(
                db_path, user=db_user, password=db_pass, connector_name=connector_name
            ) as conn:
                # Quickly list without loading all attrs (faster)
                include_attrs = bool(payload.get("include_attrs", False))
                com_objects = conn.list_all_metadata(include_attrs=include_attrs)

            manifest_objects = list_objects(live_db, hydrate_payload=False)
            report = diagnose_vs_manifest(com_objects, manifest_objects)
            report["config_name"] = ""
            return RpcResponse("ok", report)
        except Exception as exc:
            return RpcResponse("error", error=f"COM diagnose failed: {exc}")

    # ------------------------------------------------------------------ #
    # com.import_metadata  — full metadata import via COM
    # ------------------------------------------------------------------ #
    if action == "com.import_metadata":
        if not db_path:
            return RpcResponse("error", error="db_path is required")
        live_db = _get_db(handler, payload)
        if isinstance(live_db, RpcResponse):
            return live_db
        try:
            from src.infra.onec.com_source import (
                OneCCOMConnection, _TYPE_TO_PARENT, build_com_payload,
            )
            from src.infra.onec.importer import to_ascii_identifier
            from src.configurator.persistence import manifest_io
            from src.configurator.persistence.manifest_schema import ManifestObject
            import uuid as _uuid

            started = time.time()

            with OneCCOMConnection.connect(
                db_path, user=db_user, password=db_pass, connector_name=connector_name
            ) as conn:
                config_name = conn.config_name
                com_objects = conn.list_all_metadata(include_attrs=True)

            # Build parent lookup from manifest
            manifest_objs = manifest_io.list_objects(live_db, hydrate_payload=False)
            group_by_type = {o.type: o.guid for o in manifest_objs if o.kind == "group"}
            common_group_guid = group_by_type.get("common", "")
            common_folder_by_name = {
                o.name: o.guid
                for o in manifest_objs
                if o.kind == "folder" and o.type == "common" and o.parent_guid == common_group_guid
            }

            pending: list = []
            skipped = 0
            created = 0

            for obj in com_objects:
                parent_info = _TYPE_TO_PARENT.get(obj.obj_type)
                if not parent_info:
                    skipped += 1
                    continue
                parent_kind, parent_key = parent_info
                if parent_kind == "group":
                    parent_guid = group_by_type.get(parent_key, "")
                else:
                    parent_guid = common_folder_by_name.get(parent_key, "")
                if not parent_guid:
                    skipped += 1
                    continue

                name_ascii = to_ascii_identifier(obj.name)
                payload = build_com_payload(obj)

                mo = manifest_io.make_object(
                    obj_type=obj.obj_type,
                    name=name_ascii,
                    title=obj.title,
                    parent_guid=parent_guid,
                    payload=payload,
                    kind="object",
                )
                pending.append(mo)
                created += 1

            if pending:
                manifest_io.add_objects_bulk(live_db, pending)

            return RpcResponse("ok", {
                "config_name": config_name,
                "objects_from_com": len(com_objects),
                "created": created,
                "skipped": skipped,
                "elapsed_sec": round(time.time() - started, 2),
            })
        except Exception as exc:
            return RpcResponse("error", error=f"COM import failed: {exc}")

    # ------------------------------------------------------------------ #
    # com.query_data  — run 1C query and return rows
    # ------------------------------------------------------------------ #
    if action == "com.query_data":
        if not db_path:
            return RpcResponse("error", error="db_path is required")
        query_text = str(payload.get("query") or "").strip()
        if not query_text:
            return RpcResponse("error", error="query is required")
        try:
            from src.infra.onec.com_source import OneCCOMConnection
            with OneCCOMConnection.connect(
                db_path, user=db_user, password=db_pass, connector_name=connector_name
            ) as conn:
                rows = conn.query(query_text)
            return RpcResponse("ok", {"rows": rows, "count": len(rows)})
        except Exception as exc:
            return RpcResponse("error", error=f"COM query failed: {exc}")

    # ------------------------------------------------------------------ #
    # com.import_combined  — import data using ConfigDumpInfo + DBNames + Parse1CD
    # ------------------------------------------------------------------ #
    if action == "com.import_combined":
        dump_info_path = str(payload.get("dump_info_path") or "").strip()
        if not db_path:
            return RpcResponse("error", error="db_path (.1CD file) is required")
        if not dump_info_path:
            return RpcResponse("error", error="dump_info_path (ConfigDumpInfo.xml) is required")
        live_db = _get_db(handler, payload)
        if isinstance(live_db, RpcResponse):
            return live_db
        families_raw = payload.get("families")
        families = list(families_raw) if families_raw else None
        limit = payload.get("limit_per_table")
        limit_per_table = int(limit) if limit else None

        try:
            from src.infra.onec.com_1cd_bridge import import_combined
            com_conn = None
            if db_user:
                try:
                    from src.infra.onec.com_source import OneCCOMConnection
                    import os as _os
                    db_dir = str(_os.path.dirname(db_path))
                    com_conn = OneCCOMConnection.connect(
                        db_dir, user=db_user, password=db_pass,
                        connector_name=connector_name,
                    )
                except Exception:
                    pass

            try:
                results = import_combined(
                    dump_info_path, db_path, live_db,
                    com_conn=com_conn,
                    families=families,
                    limit_per_table=limit_per_table,
                )
            finally:
                if com_conn is not None:
                    com_conn.close()

            imported = [r for r in results if not r.skipped and not r.error]
            errors = [r for r in results if r.error]
            return RpcResponse("ok", {
                "tables_imported": len(imported),
                "tables_skipped": len([r for r in results if r.skipped]),
                "tables_errors": len(errors),
                "rows_written": sum(r.rows_written for r in imported),
                "errors": [{"table": r.physical_table, "error": r.error} for r in errors[:10]],
            })
        except Exception as exc:
            return RpcResponse("error", error=f"Combined import failed: {exc}")

    return None
