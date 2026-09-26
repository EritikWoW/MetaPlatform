from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from src.mpdb.mpdb import Mpdb

from .server_handlers_assets import handle_asset_action
from .server_handlers_debug import handle_debug_action
from .server_handlers_db import handle_db_action
from .server_handlers_import import handle_import_action
from .server_handlers_manifest import (
    STATE_MANIFEST_INFO_CACHE,
    handle_manifest_action,
)
from .server_handlers_com import handle_com_action
from .server_handlers_modules import handle_modules_action
from .server_handlers_table import handle_table_action
from .server_handlers_posting import handle_posting_action
from .server_state import (
    DbPool,
    RpcResponse,
    SessionStore,
    STATE_DBS,
    STATE_IMPORTS,
    STATE_REGISTRY,
    STATE_SESSIONS,
    _nullctx,
)


class RuntimeHandler(BaseHTTPRequestHandler):
    server_version = "MetaRuntime/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _send_json(self, payload: dict[str, Any], code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json({"status": "ok", "ts": time.time()})
            return
        self._send_json({"status": "error", "error": "Not found"}, code=404)

    def do_POST(self) -> None:
        if self.path != "/rpc":
            self._send_json({"status": "error", "error": "Not found"}, code=404)
            return
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length") or "0"))
            req = json.loads(raw.decode("utf-8")) if raw else {}
            action = str(req.get("action") or "").strip()
            payload = req.get("payload") or {}
            rid = req.get("id")
            res = self._handle(action, payload)
            self._send_json({"id": rid, "status": res.status, "data": res.data, "error": res.error})
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return
        except Exception as e:
            try:
                self._send_json({"status": "error", "error": f"{type(e).__name__}: {e}"})
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return

    def _require_db(self, payload: dict) -> Mpdb | RpcResponse:
        sid = str(payload.get("session_id") or "")
        if not sid:
            return RpcResponse("error", error="session_id is required")
        db_uid = STATE_SESSIONS.get_active_db_uid(sid)
        if not db_uid:
            return RpcResponse("error", error="No active database for this session")
        try:
            return STATE_DBS.get(db_uid)
        except KeyError:
            return RpcResponse("error", error="Active DB not found in pool")

    def _handle(self, action: str, payload: dict[str, Any]) -> RpcResponse:
        for dispatcher in (
            handle_db_action,
            handle_manifest_action,
            handle_table_action,
            handle_posting_action,
            handle_asset_action,
            handle_debug_action,
            handle_modules_action,
            handle_import_action,
            handle_com_action,
        ):
            res = dispatcher(self, action, payload)
            if res is not None:
                return res
        return RpcResponse("error", error=f"Unknown action: {action}")


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import socketserver

    class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    httpd = ThreadedHTTPServer((host, port), RuntimeHandler)
    print(f"[runtime] listening on http://{host}:{port}")
    httpd.serve_forever()


__all__ = [
    "DbPool",
    "RpcResponse",
    "RuntimeHandler",
    "STATE_DBS",
    "STATE_IMPORTS",
    "STATE_MANIFEST_INFO_CACHE",
    "STATE_REGISTRY",
    "STATE_SESSIONS",
    "SessionStore",
    "_nullctx",
    "serve",
]
