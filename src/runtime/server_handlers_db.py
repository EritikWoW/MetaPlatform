from __future__ import annotations

from .server_state import RpcResponse, STATE_DBS, STATE_REGISTRY, STATE_SESSIONS


def handle_db_action(_handler, action: str, payload: dict) -> RpcResponse | None:
    if action == "session.create":
        return RpcResponse("ok", {"session_id": STATE_SESSIONS.create()})

    if action == "session.close":
        sid = str(payload.get("session_id") or "")
        if not sid:
            return RpcResponse("error", error="session_id is required")
        return RpcResponse("ok", {"closed": STATE_SESSIONS.close(sid)})

    if action == "db.open_by_path":
        sid = str(payload.get("session_id") or "")
        path = str(payload.get("path") or "")
        if not sid or not path:
            return RpcResponse("error", error="session_id and path are required")
        uid, name = STATE_DBS.open_by_path(path)
        STATE_SESSIONS.set_active_db_uid(sid, uid)
        from .server_handlers_modules import schedule_workspace_semantic_index_warmup

        schedule_workspace_semantic_index_warmup(uid)
        return RpcResponse("ok", {"db_uid": uid, "name": name})

    if action == "db.open":
        sid = str(payload.get("session_id") or "")
        uid = str(payload.get("db_uid") or "")
        if not sid or not uid:
            return RpcResponse("error", error="session_id and db_uid are required")
        try:
            STATE_DBS.get(uid)
        except KeyError:
            item = STATE_REGISTRY.get(uid)
            if not item or not item.enabled:
                return RpcResponse("error", error="DB is not opened on server and not registered or disabled")
            try:
                STATE_DBS.open_by_path(item.path)
            except Exception as exc:
                # Opening a registered database is read-preserving. Repair or
                # replacement must be an explicit backup/staging operation.
                return RpcResponse("error", error=f"Cannot open DB: {exc}")
        STATE_SESSIONS.set_active_db_uid(sid, uid)
        from .server_handlers_modules import schedule_workspace_semantic_index_warmup

        schedule_workspace_semantic_index_warmup(uid)
        return RpcResponse("ok", {"db_uid": uid})

    if action == "db.list":
        return RpcResponse(
            "ok",
            {"databases": [{"db_uid": x.db_uid, "name": x.name} for x in STATE_REGISTRY.list_enabled()]},
        )

    if action == "db.list_open":
        return RpcResponse("ok", {"databases": STATE_DBS.list_open()})

    return None
