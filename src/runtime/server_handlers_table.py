from __future__ import annotations

from contextlib import nullcontext

from .server_state import RpcResponse
from .onec_virtual_tables import get_virtual_data_tables


def _guard_document_mutation(db, virtual, action, table, where, values):
    """Generic table RPCs cannot forge posting state or edit posted records."""
    if not table.casefold().startswith("data_document_"):
        return None
    if "_posted" in values and not isinstance(values["_posted"], bool):
        return RpcResponse("error", error="Posted must be Boolean")
    if action == "insert":
        if values.get("_posted", False) is not False or values.get("_posting_registers"):
            return RpcResponse("error", error="Create an unposted document, then use document.post")
        return None
    if not where:
        return RpcResponse("error", error="Document mutation requires a non-empty where clause")
    rows = []
    if table in db._meta.get("tables", {}):
        rows = db.table(table).select(where)
    if not rows:
        # A partially materialized imported table can still have virtual rows.
        _handled, rows = virtual.handle_select(table, where, None)
    for row in rows or []:
        if row.get("_posted"):
            return RpcResponse("error", error="Unpost the document before editing or deleting it")
        if action == "update":
            for key, default in (("_posted", False), ("_posting_registers", []), ("_guid", None)):
                if key in values and values[key] != row.get(key, default):
                    return RpcResponse("error", error=f"{key} cannot be changed through table.update")
    return None


def handle_table_action(handler, action: str, payload: dict) -> RpcResponse | None:
    if action == "table.select":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        tbl = str(payload.get("table") or "")
        where = payload.get("where") or None
        order = payload.get("order_by") or None
        limit = payload.get("limit")
        offset = max(0, int(payload.get("offset") or 0))
        if not tbl:
            return RpcResponse("error", error="table required")
        try:
            # Metadata/system reads must not initialise the business import
            # adapter (which loads the migration catalog and manifest).
            if tbl.casefold().startswith("data_"):
                virtual = get_virtual_data_tables(db)
                handled, rows = virtual.handle_select(
                    tbl, where, order,
                    limit=(max(1, min(int(limit), 5000)) if limit is not None else None),
                    offset=offset,
                )
                if handled:
                    return RpcResponse("ok", {"rows": rows or [], "import_status": virtual.import_status(tbl)})
            rows = db.table(tbl).select(
                where,
                order_by=order,
                limit=(max(1, min(int(limit), 5000)) if limit is not None else None),
                offset=offset,
            )
            return RpcResponse("ok", {"rows": rows or []})
        except Exception as e:
            return RpcResponse("error", error=f"table.select: {e}")

    if action == "table.insert":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        tbl = str(payload.get("table") or "")
        row = payload.get("row") or {}
        if not tbl:
            return RpcResponse("error", error="table required")
        try:
            with (db._lock if tbl.casefold().startswith("data_document_") else nullcontext()):
                virtual = get_virtual_data_tables(db)
                guard = _guard_document_mutation(db, virtual, "insert", tbl, {}, row)
                if guard is not None:
                    return guard
                handled, rowid = virtual.handle_insert(tbl, row)
                if handled:
                    return RpcResponse("ok", {"rowid": rowid})
                rowid = db.table(tbl).insert(row)
                return RpcResponse("ok", {"rowid": rowid})
        except Exception as e:
            return RpcResponse("error", error=f"table.insert: {e}")

    if action == "table.update":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        tbl = str(payload.get("table") or "")
        where = payload.get("where") or {}
        values = payload.get("values") or {}
        if not tbl:
            return RpcResponse("error", error="table required")
        try:
            with (db._lock if tbl.casefold().startswith("data_document_") else nullcontext()):
                virtual = get_virtual_data_tables(db)
                guard = _guard_document_mutation(db, virtual, "update", tbl, where, values)
                if guard is not None:
                    return guard
                handled, updated = virtual.handle_update(tbl, where, values)
                if handled:
                    return RpcResponse("ok", {"updated": updated})
                n = db.table(tbl).update(where, values)
                return RpcResponse("ok", {"updated": n})
        except Exception as e:
            return RpcResponse("error", error=f"table.update: {e}")

    if action == "table.delete":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        tbl = str(payload.get("table") or "")
        where = payload.get("where") or {}
        if not tbl:
            return RpcResponse("error", error="table required")
        try:
            with (db._lock if tbl.casefold().startswith("data_document_") else nullcontext()):
                virtual = get_virtual_data_tables(db)
                guard = _guard_document_mutation(db, virtual, "delete", tbl, where, {})
                if guard is not None:
                    return guard
                handled, deleted = virtual.handle_delete(tbl, where)
                if handled:
                    return RpcResponse("ok", {"deleted": deleted})
                n = db.table(tbl).delete(where)
                return RpcResponse("ok", {"deleted": n})
        except Exception as e:
            return RpcResponse("error", error=f"table.delete: {e}")

    if action == "schema.deploy":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        try:
            from src.configurator.persistence.schema_deployment import SchemaDeploymentService

            report = SchemaDeploymentService(db).deploy_all()
            return RpcResponse(
                "ok",
                {
                    "created": int(report.created),
                    "existing": int(report.existing),
                    "skipped": int(report.skipped),
                    "errors": list(report.errors),
                },
            )
        except Exception as e:
            return RpcResponse("error", error=f"schema.deploy: {e}")

    return None
