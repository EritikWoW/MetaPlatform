from __future__ import annotations

import base64
import json
import threading
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RpcResult:
    status: str
    data: Any = None
    error: str | None = None


class RuntimeGateway:
    """Low-level RPC transport. One instance per runtime URL."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_id: str | None = None
        self._closed = False
        self._session_lock = threading.Lock()
        self._session_create_lock = threading.Lock()

    def health(self, timeout: float = 1.5) -> bool:
        try:
            with urllib.request.urlopen(self.base_url + "/health", timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    def _post(self, action: str, payload: Dict[str, Any], *, timeout: float = 30) -> RpcResult:
        body = json.dumps(
            {"id": None, "action": action, "payload": payload},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/rpc", data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                res = json.loads(r.read().decode("utf-8"))
                return RpcResult(
                    status=res.get("status") or "error",
                    data=res.get("data"),
                    error=res.get("error"),
                )
        except urllib.error.HTTPError as e:
            return RpcResult(status="error", error=f"HTTP {e.code}")
        except Exception as e:
            return RpcResult(status="error", error=f"{type(e).__name__}: {e}")

    def _call(self, action: str, payload: Dict[str, Any], *, timeout: float = 30) -> Any:
        """Call RPC and return data, or raise RuntimeError on failure."""
        res = self._post(action, payload, timeout=timeout)
        if res.status != "ok":
            raise RuntimeError(res.error or f"RPC {action} failed")
        return res.data or {}

    # ── session / db ─────────────────────────────────────────────────────

    def ensure_session(self) -> str:
        with self._session_create_lock:
            with self._session_lock:
                if self._closed:
                    raise RuntimeError("Runtime gateway is closed")
                if self.session_id:
                    return self.session_id
            data = self._call("session.create", {})
            sid = str(data["session_id"])
            with self._session_lock:
                if not self._closed:
                    self.session_id = sid
                    return sid
            # Closing never waits for an in-flight create. Its late response
            # must be disposed of by that worker instead of resurrecting UI state.
            try:
                self._call("session.close", {"session_id": sid}, timeout=1.0)
            except Exception:
                pass
            raise RuntimeError("Runtime gateway is closed")

    def _sid(self) -> str:
        return self.ensure_session()

    def close_session(self) -> bool:
        # Detach before network I/O. Background readers must not resurrect a
        # session while its owner is closing, even if Runtime never responds.
        with self._session_lock:
            sid = str(self.session_id or "")
            self._closed = True
            self.session_id = None
        if not sid:
            return False
        try:
            try:
                data = self._call("session.close", {"session_id": sid}, timeout=1.0)
                return bool(data.get("closed"))
            except Exception:
                return False
        finally:
            self.session_id = None

    def open_by_path(self, path: str) -> dict[str, Any]:
        return self._call("db.open_by_path", {"session_id": self._sid(), "path": path}, timeout=180.0)

    def open_by_uid(self, db_uid: str) -> dict[str, Any]:
        return self._call("db.open", {"session_id": self._sid(), "db_uid": db_uid}, timeout=180.0)

    def list_databases(self) -> list[dict[str, Any]]:
        data = self._call("db.list", {})
        return list(data.get("databases") or [])

    def list_open_databases(self) -> list[dict[str, Any]]:
        data = self._call("db.list_open", {})
        return list(data.get("databases") or [])

    # ── manifest ─────────────────────────────────────────────────────────

    def manifest_info(self) -> dict[str, Any]:
        data = self._call("manifest.info", {"session_id": self._sid()})
        return dict(data or {})

    def manifest_open(self, *, seed_defaults: bool = True) -> list[dict]:
        data = self._call("manifest.open", {
            "session_id": self._sid(), "seed_defaults": seed_defaults}, timeout=300.0)
        return list(data.get("objects") or [])

    def manifest_list(self, *, timeout: float = 120.0, slim: bool = True) -> list[dict]:
        data = self._call(
            "manifest.list",
            {"session_id": self._sid(), "slim": slim},
            timeout=timeout,
        )
        return list(data.get("objects") or [])

    def manifest_nav(self, *, timeout: float = 60.0) -> list[dict]:
        data = self._call(
            "manifest.nav",
            {"session_id": self._sid()},
            timeout=timeout,
        )
        return list(data.get("objects") or [])

    def manifest_schema_index(self, *, timeout: float = 120.0) -> list[dict]:
        """Return the lightweight metadata schema used by Configurator tree."""

        data = self._call(
            "manifest.schema_index",
            {"session_id": self._sid()},
            timeout=timeout,
        )
        return [dict(row) for row in list(data.get("objects") or []) if isinstance(row, dict)]

    def manifest_lookup(
        self,
        *,
        type_name: str = "",
        name: str = "",
        limit: int = 1000,
    ) -> list[dict]:
        data = self._call(
            "manifest.lookup",
            {
                "session_id": self._sid(),
                "type": str(type_name or "").strip(),
                "name": str(name or "").strip(),
                "limit": int(limit),
            },
        )
        return [dict(row) for row in list(data.get("objects") or []) if isinstance(row, dict)]

    def manifest_get_row(self, guid: str) -> dict:
        data = self._call(
            "manifest.get_row",
            {"session_id": self._sid(), "guid": str(guid or "").strip()},
        )
        return dict(data.get("row") or {})

    def manifest_get_payload(self, guid: str) -> dict:
        """Fetch payload for a single object on-demand."""
        data = self._call(
            "manifest.get_payload",
            {"session_id": self._sid(), "guid": guid},
        )
        return dict(data.get("payload") or {})

    def manifest_object_context(self, guid: str) -> dict[str, Any]:
        """Fetch one object plus its forms and module metadata lazily."""
        data = self._call(
            "manifest.object_context",
            {"session_id": self._sid(), "guid": str(guid or "").strip()},
        )
        return dict(data or {})

    def manifest_get_objects(self, guid: str) -> list[str]:
        """Fetch only subsystem membership objects without hydrating full payload."""
        data = self._call(
            "manifest.get_objects",
            {"session_id": self._sid(), "guid": guid},
        )
        return [str(g).strip() for g in (data.get("objects") or []) if str(g).strip()]

    def manifest_get_subtree(self, guid: str, *, timeout: float = 60.0) -> list[dict]:
        """Fetch a manifest row plus all descendants without hydrating payloads."""
        data = self._call(
            "manifest.get_subtree",
            {"session_id": self._sid(), "guid": str(guid or "").strip()},
            timeout=timeout,
        )
        return list(data.get("rows") or [])

    def manifest_add(self, obj: dict) -> dict:
        data = self._call("manifest.add", {"session_id": self._sid(), "object": obj})
        return dict(data.get("object") or {})

    def manifest_update_payload(self, guid: str, payload: dict) -> None:
        self._call("manifest.update_payload", {
            "session_id": self._sid(), "guid": guid, "payload": payload}, timeout=300.0)

    def manifest_bulk_update_payloads(self, payloads: dict[str, dict]) -> int:
        data = self._call(
            "manifest.bulk_update_payloads",
            {"session_id": self._sid(), "payloads": dict(payloads or {})},
            timeout=600.0,
        )
        return int(data.get("updated") or 0)

    def manifest_update_title(self, guid: str, title: str) -> None:
        self._call("manifest.update_title", {
            "session_id": self._sid(), "guid": guid, "title": title})

    def manifest_update_fields(self, guid: str, **fields) -> None:
        self._call("manifest.update_fields", {
            "session_id": self._sid(), "guid": guid, **fields}, timeout=300.0)

    def manifest_delete(self, guid: str) -> None:
        self._call("manifest.delete", {"session_id": self._sid(), "guid": guid})

    # ── table ────────────────────────────────────────────────────────────

    def document_post(self, *, doc_name: str, doc_guid: str, post: bool = True):
        from .posting_engine import PostingResult
        data = self._call("document.post" if post else "document.unpost", {
            "session_id": self._sid(), "doc_name": doc_name, "doc_guid": doc_guid,
        }, timeout=120.0)
        return PostingResult.from_dict(data)

    def table_select(self, table: str, where: dict | None = None,
                     order_by: str | None = None, *,
                     limit: int | None = None, offset: int = 0) -> list[dict]:
        p: dict = {"session_id": self._sid(), "table": table}
        if where is not None:
            p["where"] = where
        if order_by is not None:
            p["order_by"] = order_by
        if limit is not None:
            p["limit"] = max(1, min(int(limit), 5000))
            p["offset"] = max(0, int(offset))
        data = self._call("table.select", p)
        if not hasattr(self, "last_table_status"):
            self.last_table_status: dict[str, dict] = {}
        self.last_table_status[table] = dict(data.get("import_status") or {})
        return list(data.get("rows") or [])

    def table_insert(self, table: str, row: dict) -> int:
        data = self._call("table.insert", {
            "session_id": self._sid(), "table": table, "row": row})
        return int(data.get("rowid") or 0)

    def table_update(self, table: str, where: dict, values: dict) -> int:
        data = self._call("table.update", {
            "session_id": self._sid(), "table": table,
            "where": where, "values": values})
        return int(data.get("updated") or 0)

    def table_delete(self, table: str, where: dict) -> int:
        data = self._call("table.delete", {
            "session_id": self._sid(), "table": table, "where": where})
        return int(data.get("deleted") or 0)

    # ── assets ───────────────────────────────────────────────────────────

    def asset_get(self, key: str) -> tuple[bytes, str]:
        data = self._call("asset.get", {"session_id": self._sid(), "key": key})
        raw = base64.b64decode(data.get("data") or "")
        return raw, str(data.get("mime") or "")

    def asset_put(self, key: str, data: bytes, mime: str = "application/octet-stream") -> None:
        self._call("asset.put", {
            "session_id": self._sid(), "key": key,
            "mime": mime, "data": base64.b64encode(data).decode("ascii"),
        }, timeout=300.0)

    def asset_list(self, prefix: str = "") -> list[str]:
        data = self._call("asset.list", {"session_id": self._sid(), "prefix": prefix})
        return list(data.get("keys") or [])

    def asset_delete(self, key: str) -> bool:
        data = self._call("asset.delete", {"session_id": self._sid(), "key": key})
        return bool(data.get("deleted"))

    # ── schema ───────────────────────────────────────────────────────────

    def schema_deploy(self) -> dict[str, Any]:
        data = self._call("schema.deploy", {"session_id": self._sid()}, timeout=300.0)
        return dict(data or {})

    # ── modules ───────────────────────────────────────────────────────────

    def module_get_text(self, module_guid: str) -> str:
        data = self._call(
            "modules.get_text",
            {"session_id": self._sid(), "module_guid": str(module_guid or "").strip()},
        )
        return str(data.get("text") or "")

    def modules_list_by_owner(self, owner_guid: str) -> list[dict[str, Any]]:
        data = self._call(
            "modules.list_by_owner",
            {"session_id": self._sid(), "owner_guid": str(owner_guid or "").strip()},
        )
        return [dict(row) for row in list(data.get("modules") or []) if isinstance(row, dict)]

    def module_resolve(self, name: str) -> dict[str, Any]:
        data = self._call(
            "modules.resolve",
            {"session_id": self._sid(), "name": str(name or "").strip()},
        )
        module = data.get("module") if isinstance(data, dict) else None
        return dict(module) if isinstance(module, dict) else {}

    def module_completion_members(self, name: str) -> dict[str, Any]:
        data = self._call(
            "modules.completion_members",
            {"session_id": self._sid(), "name": str(name or "").strip()},
        )
        return dict(data or {})

    def workspace_semantic_index_info(self, *, wait: bool = False) -> dict[str, Any]:
        return dict(
            self._call(
                "modules.semantic_index_info",
                {"session_id": self._sid(), "wait": bool(wait)},
                timeout=120.0,
            )
            or {}
        )

    def workspace_semantic_definition(
        self,
        qualifier: str,
        name: str,
    ) -> dict[str, Any]:
        data = self._call(
            "modules.semantic_definition",
            {
                "session_id": self._sid(),
                "qualifier": str(qualifier or "").strip(),
                "name": str(name or "").strip(),
            },
            timeout=120.0,
        )
        target = data.get("target") if isinstance(data, dict) else None
        return dict(target) if isinstance(target, dict) else {}

    def workspace_semantic_references(
        self,
        qualifier: str,
        name: str,
        *,
        limit: int = 500,
        include_declaration: bool = True,
    ) -> list[dict[str, Any]]:
        data = self._call(
            "modules.semantic_references",
            {
                "session_id": self._sid(),
                "qualifier": str(qualifier or "").strip(),
                "name": str(name or "").strip(),
                "limit": int(limit),
                "include_declaration": bool(include_declaration),
            },
            timeout=120.0,
        )
        return [
            dict(row)
            for row in list(data.get("hits") or [])
            if isinstance(row, dict)
        ]

    def workspace_semantic_diagnostics(
        self,
        *,
        module_guid: str = "",
        code: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        data = self._call(
            "modules.semantic_diagnostics",
            {
                "session_id": self._sid(),
                "module_guid": str(module_guid or "").strip(),
                "code": str(code or "").strip(),
                "limit": int(limit),
            },
            timeout=120.0,
        )
        return [
            dict(row)
            for row in list(data.get("diagnostics") or [])
            if isinstance(row, dict)
        ]

    def modules_search_text(
        self,
        term: str,
        *,
        match_case: bool = False,
        whole_word: bool = False,
        module_guid: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        data = self._call(
            "modules.search_text",
            {
                "session_id": self._sid(),
                "term": str(term or ""),
                "match_case": bool(match_case),
                "whole_word": bool(whole_word),
                "module_guid": str(module_guid or "").strip(),
                "limit": int(limit),
            },
            timeout=120.0,
        )
        return [dict(row) for row in list(data.get("hits") or []) if isinstance(row, dict)]

    def modules_rename_symbol_plan(
        self,
        module_guid: str,
        *,
        new_name: str,
        cursor_position: int | None = None,
        symbol_name: str = "",
        module_name: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": self._sid(),
            "module_guid": str(module_guid or "").strip(),
            "new_name": str(new_name or "").strip(),
            "symbol_name": str(symbol_name or "").strip(),
            "module_name": str(module_name or "").strip(),
        }
        if cursor_position is not None:
            payload["cursor_position"] = int(cursor_position)
        data = self._call(
            "modules.rename_symbol_plan",
            payload,
            timeout=120.0,
        )
        return dict(data or {})

    def modules_rename_symbol_apply(
        self,
        module_guid: str,
        *,
        new_name: str,
        modules: list[dict[str, Any]],
        cursor_position: int | None = None,
        symbol_name: str = "",
        module_name: str = "",
        updated_by: str = "workspace_rename",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": self._sid(),
            "module_guid": str(module_guid or "").strip(),
            "new_name": str(new_name or "").strip(),
            "symbol_name": str(symbol_name or "").strip(),
            "module_name": str(module_name or "").strip(),
            "updated_by": str(updated_by or "workspace_rename"),
            "modules": [
                {
                    "module_guid": str(item.get("module_guid") or "").strip(),
                    "source_hash": str(item.get("source_hash") or "").strip(),
                    "updated_hash": str(item.get("updated_hash") or "").strip(),
                }
                for item in list(modules or [])
                if isinstance(item, dict)
            ],
        }
        if cursor_position is not None:
            payload["cursor_position"] = int(cursor_position)
        data = self._call(
            "modules.rename_symbol_apply",
            payload,
            timeout=300.0,
        )
        return dict(data or {})

    def module_update_text(self, module_guid: str, text: str, *, updated_by: str = "user") -> None:
        self._call(
            "modules.update_text",
            {
                "session_id": self._sid(),
                "module_guid": str(module_guid or "").strip(),
                "text": str(text or ""),
                "updated_by": str(updated_by or "user"),
            },
            timeout=300.0,
        )

    def modules_normalize_language(self, language: str) -> dict[str, Any]:
        data = self._call(
            "modules.normalize_language",
            {"session_id": self._sid(), "language": str(language or "").strip().lower()},
            timeout=300.0,
        )
        return dict(data or {})

    def debug_selfcheck(
        self,
        *,
        entry: str = "Main",
        module_id: str = "module://debug-selfcheck",
        breakpoint_line: int = 3,
        strict_entry: bool = True,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        data = self._call(
            "debug.selfcheck",
            {
                "session_id": self._sid(),
                "entry": str(entry or "").strip() or "Main",
                "module_id": str(module_id or "").strip() or "module://debug-selfcheck",
                "breakpoint_line": max(1, int(breakpoint_line or 1)),
                "strict_entry": bool(strict_entry),
            },
            timeout=timeout,
        )
        return dict(data or {})

    def onec_import_sessions(self, *, active_only: bool = False, history_limit: int = 0) -> list[dict[str, Any]]:
        data = self._call(
            "onec.import_sessions",
            {
                "active_only": bool(active_only),
                "history_limit": max(0, int(history_limit)),
            },
            timeout=10.0,
        )
        return list(data.get("sessions") or [])

    def onec_import_status(self, *, session_id: str = "", history_limit: int = 20) -> dict[str, Any]:
        sid = str(session_id or self._sid()).strip()
        data = self._call(
            "onec.import_status",
            {"session_id": sid, "history_limit": max(0, int(history_limit))},
            timeout=10.0,
        )
        return dict(data or {})

    def onec_import_attach(self, *, session_id: str = "", history_limit: int = 20) -> dict[str, Any]:
        sid = str(session_id or "").strip()
        if sid:
            return self.onec_import_status(session_id=sid, history_limit=history_limit)
        sessions = self.onec_import_sessions(active_only=True, history_limit=history_limit)
        return dict(sessions[0]) if sessions else {}


# ── GatewayTable — drop-in replacement for Mpdb.table() ──────────────────

class GatewayTable:
    """Mimics mpdb.Table interface but talks to the runtime server via RPC."""

    def __init__(self, gw: RuntimeGateway, name: str) -> None:
        self._gw   = gw
        self._name = name

    def select(self, where: dict | None = None, *,
               order_by: str | None = None, limit: int | None = None,
               offset: int = 0) -> list[dict]:
        try:
            return self._gw.table_select(
                self._name, where, order_by, limit=limit, offset=offset
            )
        except TypeError as exc:
            # Keep compatibility with lightweight gateways used by embedded
            # clients and older integrations that predate paging arguments.
            if "unexpected keyword argument" not in str(exc):
                raise
            rows = self._gw.table_select(self._name, where, order_by)
            if offset:
                rows = rows[int(offset):]
            if limit is not None:
                rows = rows[:max(1, int(limit))]
            return rows

    def insert(self, row: dict) -> int:
        return self._gw.table_insert(self._name, row)

    def update(self, where: dict, set_values: dict) -> int:
        return self._gw.table_update(self._name, where, set_values)

    def delete(self, where: dict) -> int:
        return self._gw.table_delete(self._name, where)


# ── GatewayDb — drop-in replacement for Mpdb ─────────────────────────────

class GatewayDb:
    """Mimics the Mpdb interface but delegates everything to the runtime server.

    Usage:
        gw = RuntimeGateway("http://localhost:8765")
        gw.open_by_uid(db_uid)            # or open_by_path for local dev
        db = GatewayDb(gw)

    Then pass `db` anywhere that previously received an `Mpdb` instance.
    The `table()`, `get_asset()`, `put_asset()`, `list_assets()`,
    `delete_asset()` methods all work identically.
    """

    def __init__(self, gw: RuntimeGateway) -> None:
        self._gw = gw

    # ── Mpdb-compatible interface ─────────────────────────────────────────

    def table(self, name: str) -> GatewayTable:
        return GatewayTable(self._gw, name)

    def document_post(self, *, doc_name: str, doc_guid: str, post: bool = True):
        return self._gw.document_post(doc_name=doc_name, doc_guid=doc_guid, post=post)

    def get_asset(self, key: str) -> tuple[bytes, str]:
        return self._gw.asset_get(key)

    def put_asset(self, key: str, data: bytes, *,
                  mime: str = "application/octet-stream") -> None:
        self._gw.asset_put(key, data, mime)

    def list_assets(self, prefix: str = "") -> list[str]:
        return self._gw.asset_list(prefix)

    def delete_asset(self, key: str) -> bool:
        return self._gw.asset_delete(key)

    def delete_assets_by_prefixes(self,
                                   prefixes: list[str] | tuple[str, ...] | str) -> int:
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        deleted = 0
        for prefix in prefixes:
            keys = self._gw.asset_list(prefix)
            for k in keys:
                if self._gw.asset_delete(k):
                    deleted += 1
        return deleted

    # db_uid / meta are read-only stubs (used rarely outside server)
    @property
    def db_uid(self) -> str:
        return ""

    def close(self) -> None:
        self._gw.close_session()
