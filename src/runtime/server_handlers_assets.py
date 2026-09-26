from __future__ import annotations

import base64

from .server_state import RpcResponse


def handle_asset_action(handler, action: str, payload: dict) -> RpcResponse | None:
    if action == "asset.get":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        key = str(payload.get("key") or "")
        if not key:
            return RpcResponse("error", error="key required")
        try:
            data, mime = db.get_asset(key)
            return RpcResponse(
                "ok",
                {
                    "key": key,
                    "mime": mime,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            )
        except Exception as e:
            return RpcResponse("error", error=f"asset.get: {e}")

    if action == "asset.put":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        key = str(payload.get("key") or "")
        mime = str(payload.get("mime") or "application/octet-stream")
        b64data = payload.get("data") or ""
        if not key:
            return RpcResponse("error", error="key required")
        try:
            data = base64.b64decode(b64data) if b64data else b""
            db.put_asset(key, data, mime=mime)
            return RpcResponse("ok", {"key": key})
        except Exception as e:
            return RpcResponse("error", error=f"asset.put: {e}")

    if action == "asset.list":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        prefix = str(payload.get("prefix") or "")
        try:
            return RpcResponse("ok", {"keys": db.list_assets(prefix)})
        except Exception as e:
            return RpcResponse("error", error=f"asset.list: {e}")

    if action == "asset.delete":
        db = handler._require_db(payload)
        if isinstance(db, RpcResponse):
            return db
        key = str(payload.get("key") or "")
        if not key:
            return RpcResponse("error", error="key required")
        try:
            return RpcResponse("ok", {"deleted": db.delete_asset(key)})
        except Exception as e:
            return RpcResponse("error", error=f"asset.delete: {e}")

    return None
