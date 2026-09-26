from __future__ import annotations

from .posting_engine import PostingEngine
from .server_state import RpcResponse


def handle_posting_action(handler, action: str, payload: dict) -> RpcResponse | None:
    if action not in {"document.post", "document.unpost"}:
        return None
    db = handler._require_db(payload)
    if isinstance(db, RpcResponse):
        return db
    name = str(payload.get("doc_name") or "").strip()
    guid = str(payload.get("doc_guid") or "").strip()
    if not name or not guid:
        return RpcResponse("error", error="doc_name and doc_guid are required")
    engine = PostingEngine(db)
    method = engine.post if action == "document.post" else engine.unpost
    result = method(doc_name=name, doc_guid=guid)
    return RpcResponse("ok", result.to_dict())
