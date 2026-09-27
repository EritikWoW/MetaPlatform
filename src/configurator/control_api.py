from __future__ import annotations

import base64
import os
import json
import subprocess
import sys
import threading
import time
import uuid
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget


class _ThreadedHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class ConfiguratorControlBridge(QObject):
    """Main-thread bridge for the configurator control API."""

    request = Signal(str, str, object)

    def __init__(self, view, vm) -> None:
        super().__init__(view)
        self._view = view
        self._vm = vm
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._active_debug_pause: dict[str, Any] | None = None
        self.request.connect(self._execute, Qt.ConnectionType.QueuedConnection)

    def abort_debug_pause(self) -> bool:
        """Release the active debug request before its client is stopped."""

        active = self._active_debug_pause
        if not isinstance(active, dict):
            return False
        command = active.get("command")
        if isinstance(command, dict):
            command["value"] = "continue"
        loop = active.get("loop")
        if isinstance(loop, QEventLoop) and loop.isRunning():
            loop.quit()
        return True

    def call(self, action: str, payload: dict[str, Any] | None = None, *, timeout: float = 5.0) -> Any:
        token = uuid.uuid4().hex
        event = threading.Event()
        with self._lock:
            self._pending[token] = {"event": event, "done": False, "status": "", "data": None, "error": ""}
        self.request.emit(token, str(action or ""), dict(payload or {}))
        if not event.wait(timeout):
            with self._lock:
                self._pending.pop(token, None)
            raise TimeoutError(f"Control API request timed out: {action}")
        with self._lock:
            result = self._pending.pop(token, None) or {}
        if result.get("status") != "ok":
            raise RuntimeError(str(result.get("error") or f"Control API request failed: {action}"))
        return result.get("data")

    @Slot(str, str, object)
    def _execute(self, token: str, action: str, payload: object) -> None:
        started = time.perf_counter()
        try:
            data = self._dispatch(action, dict(payload or {}))
            result = {"status": "ok", "data": data, "error": "", "elapsed": time.perf_counter() - started}
        except Exception as exc:
            result = {
                "status": "error",
                "data": None,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed": time.perf_counter() - started,
            }
        with self._lock:
            pending = self._pending.get(token)
            if pending is not None:
                pending.update(result)
                pending["done"] = True
                event = pending.get("event")
                if isinstance(event, threading.Event):
                    event.set()

    def _dispatch(self, action: str, payload: dict[str, Any]) -> Any:
        action = str(action or "").strip().lower()
        if action in ("health", "ping"):
            return {"status": "ok", "ts": time.time()}
        if action == "close":
            return {"accepted": bool(self._view.close())}
        if action == "state":
            return self._state(include_tree=bool(payload.get("include_tree")))
        if action == "refresh":
            self._vm.reload()
            return self._state(include_tree=bool(payload.get("include_tree")))
        if action == "runtime_refresh":
            self._vm.start_background_runtime_refresh()
            return {"queued": True}
        if action == "reopen_db":
            self._vm.reopen_db()
            return self._state(include_tree=bool(payload.get("include_tree")))
        if action == "sync_runtime":
            self._vm.reopen_db()
            try:
                self._vm.refresh_from_runtime()
            except Exception:
                self._vm.start_background_runtime_refresh()
            return self._state(include_tree=bool(payload.get("include_tree")))
        if action == "import_onec":
            return self._start_import(payload)
        if action == "import_status":
            return self._import_status(payload)
        if action == "verify_subsystem":
            return self._verify_subsystem(payload)
        if action == "diagnose_subsystem_membership":
            vm_diag = getattr(self._vm, "diagnose_subsystem_membership", None)
            if callable(vm_diag):
                return vm_diag(
                    guid=str(payload.get("guid") or "").strip(),
                    name=str(payload.get("name") or "").strip(),
                    title=str(payload.get("title") or "").strip(),
                )
            diag_payload = dict(payload or {})
            diag_payload["dry_run"] = True
            return self._repair_subsystem_membership(diag_payload)
        if action == "repair_subsystem_membership":
            vm_repair = getattr(self._vm, "repair_subsystem_membership", None)
            if callable(vm_repair):
                return vm_repair(
                    guid=str(payload.get("guid") or "").strip(),
                    name=str(payload.get("name") or "").strip(),
                    title=str(payload.get("title") or "").strip(),
                )
            return self._repair_subsystem_membership(payload)
        if action == "sync_subsystem_membership":
            vm_sync = getattr(self._vm, "sync_subsystem_membership", None)
            if callable(vm_sync):
                return vm_sync(
                    guid=str(payload.get("guid") or "").strip(),
                    name=str(payload.get("name") or "").strip(),
                    title=str(payload.get("title") or "").strip(),
                )
            diag_payload = {
                "guid": str(payload.get("guid") or "").strip(),
                "name": str(payload.get("name") or "").strip(),
                "title": str(payload.get("title") or "").strip(),
                "dry_run": True,
            }
            before = self._repair_subsystem_membership(diag_payload)
            repair = {"scanned": int(before.get("scanned") or 0), "changed": 0, "mismatched": int(before.get("changed") or 0), "repaired": []}
            if int(before.get("changed") or 0):
                repair = self._repair_subsystem_membership(
                    {
                        "guid": str(payload.get("guid") or "").strip(),
                        "name": str(payload.get("name") or "").strip(),
                        "title": str(payload.get("title") or "").strip(),
                    }
                )
            after = self._repair_subsystem_membership(diag_payload)
            after["before"] = before
            after["repair"] = repair
            after["auto_repaired"] = bool(int(repair.get("changed") or 0))
            after["changed"] = int(repair.get("changed") or 0)
            after["mismatched_before"] = int(before.get("changed") or 0)
            after["mismatched_after"] = int(after.get("changed") or 0)
            return after
        if action == "compare_source_structure":
            vm_compare = getattr(self._vm, "compare_source_structure", None)
            if callable(vm_compare):
                return vm_compare(
                    source_path=str(payload.get("source_path") or "").strip(),
                    source_kind=str(payload.get("source_kind") or "").strip(),
                )
            return self._compare_source_structure(payload)
        if action == "repair_source_structure":
            vm_repair = getattr(self._vm, "repair_source_structure", None)
            if callable(vm_repair):
                return vm_repair(
                    source_path=str(payload.get("source_path") or "").strip(),
                    source_kind=str(payload.get("source_kind") or "").strip(),
                )
            return self._repair_source_structure(payload)
        if action == "audit_source_structure":
            return self._audit_source_structure(payload)
        if action == "restart_self":
            return self._restart_self(payload)
        if action == "tile_windows":
            mdi = getattr(self._view, "mdi", None)
            tile = getattr(mdi, "tileSubWindows", None)
            if not callable(tile):
                raise RuntimeError("MDI tiling is not available")
            tile()
            return self._state(include_tree=bool(payload.get("include_tree")))
        if action == "maximize_active_window":
            mdi = getattr(self._view, "mdi", None)
            guid = str(payload.get("guid") or "").strip()
            open_windows = getattr(self._view, "_open_windows", {})
            active = open_windows.get(guid) if guid and isinstance(open_windows, dict) else None
            if active is None:
                active = getattr(mdi, "activeSubWindow", lambda: None)()
            if active is None:
                raise RuntimeError("Active MDI window is not available")
            activate = getattr(mdi, "setActiveSubWindow", None)
            if callable(activate):
                activate(active)
            active.showMaximized()
            return self._state(include_tree=bool(payload.get("include_tree")))
        if action == "set_search":
            text = str(payload.get("text") or "")
            self._view.search.setText(text)
            return self._state(include_tree=bool(payload.get("include_tree")))
        if action == "set_subsystem_filter":
            guid = str(payload.get("guid") or "").strip()
            return self._set_subsystem_filter(guid, include_tree=bool(payload.get("include_tree")))
        if action == "select":
            guid = str(payload.get("guid") or "").strip()
            return self._select_guid(guid, open_editor=bool(payload.get("open_editor")), include_tree=bool(payload.get("include_tree")))
        if action == "open":
            guid = str(payload.get("guid") or "").strip()
            return self._open_guid(guid, include_tree=bool(payload.get("include_tree")))
        if action == "properties_state":
            return self._properties_state(include_payload=bool(payload.get("include_payload")))
        if action == "properties_set":
            return self._properties_set(payload)
        if action == "properties_save":
            return self._properties_save()
        if action == "properties_revert":
            return self._properties_revert()
        if action == "form_editor_state":
            return self._form_editor_state(payload)
        if action == "form_editor_tab":
            return self._form_editor_tab(payload)
        if action == "form_editor_completion":
            return self._form_editor_completion(payload)
        if action == "code_editor_completion":
            return self._code_editor_completion(payload)
        if action == "code_editor_diagnostics_state":
            return self._code_editor_diagnostics_state()
        if action == "workspace_semantic_index_info":
            return self._workspace_semantic_index_info()
        if action == "workspace_semantic_diagnostics":
            return self._workspace_semantic_diagnostics(payload)
        if action == "workspace_problems_state":
            return self._workspace_problems_state(payload)
        if action == "workspace_problems_refresh":
            return self._workspace_problems_refresh(payload)
        if action == "workspace_problem_navigate":
            return self._workspace_problem_navigate(payload)
        if action == "workspace_symbol_definition":
            return self._workspace_symbol_definition(payload)
        if action == "code_editor_go_to_definition":
            return self._code_editor_go_to_definition(payload)
        if action == "code_editor_find_usages":
            return self._code_editor_find_usages(payload)
        if action == "code_editor_show_usages":
            return self._code_editor_show_usages(payload)
        if action == "code_editor_usages_state":
            return self._code_editor_usages_state()
        if action == "code_editor_rename_preview":
            return self._code_editor_rename(payload, apply=False)
        if action == "code_editor_rename_apply":
            return self._code_editor_rename(payload, apply=True)
        if action == "code_editor_rename_workspace_preview":
            return self._code_editor_rename_workspace_preview(payload)
        if action == "code_editor_rename_workspace_apply":
            return self._code_editor_rename_workspace_apply(payload)
        if action == "open_debug_module":
            return self._open_debug_module(payload)
        if action == "debug_client_status":
            return self._debug_client_status()
        if action == "launch_debug_client":
            return self._launch_debug_client(restart=bool(payload.get("restart", False)))
        if action == "stop_debug_client":
            return self._stop_debug_client(force=bool(payload.get("force", True)))
        if action == "breakpoints_list":
            return self._breakpoints_list()
        if action == "breakpoint_set":
            return self._breakpoint_set(payload)
        if action == "debug_command":
            return self._debug_command(str(payload.get("command") or "continue"))
        if action == "debug_pause":
            return self._debug_pause(payload)
        if action == "debug_evaluate":
            expression = str(payload.get("expression") or "").strip()
            active = self._active_debug_pause
            pause = active.get("pause") if isinstance(active, dict) else None
            if pause is None:
                raise RuntimeError("Debugger is not paused")
            from src.client.debug_support import evaluate_debug_expression

            result, errors = evaluate_debug_expression(pause, expression)
            safe_result = result
            try:
                json.dumps(result, ensure_ascii=False)
            except Exception:
                safe_result = repr(result)
            return {
                "expression": expression,
                "result": safe_result,
                "type": type(result).__name__,
                "errors": list(errors or []),
            }
        if action == "screenshot":
            return self._screenshot()
        raise RuntimeError(f"Unknown action: {action}")

    def _state(self, *, include_tree: bool = False) -> dict[str, Any]:
        vm = self._vm
        view = self._view
        selected = view.current_selection_info()
        if selected is not None:
            if hasattr(selected, "__dict__"):
                selected = dict(selected.__dict__)
            elif isinstance(selected, tuple) and len(selected) >= 4:
                selected = {
                    "kind": selected[0],
                    "guid": selected[1],
                    "name": selected[2],
                    "obj_type": selected[3],
                }
        state: dict[str, Any] = {
            "runtime_url": str(getattr(view, "runtime_url", "") or getattr(vm, "runtime_url", "") or ""),
            "db_uid": str(getattr(view, "db_uid_str", "") or getattr(vm, "db_uid", "") or ""),
            "db_path": str(getattr(view, "db_path", "") or getattr(vm, "db_path", "") or ""),
            "status": str(view.statusBar().currentMessage() or ""),
            "window_title": str(view.windowTitle() or ""),
            "search": str(view.search.text() or ""),
            "subsystem_filter_guid": str(view.current_subsystem_filter_guid() or ""),
            "is_dirty": bool(getattr(view, "_is_dirty", False)),
            "open_windows": list(getattr(view, "_open_windows", {}).keys()),
            "selected": selected,
            "tree_count": int(view.tree_model.rowCount()),
        }
        debug_editors: list[dict[str, Any]] = []
        try:
            candidates = view.findChildren(QWidget)
        except Exception:
            candidates = []
        for candidate in candidates:
            if not callable(getattr(candidate, "focus_debug_location", None)):
                continue
            editor_state = getattr(candidate, "state", None)
            pause = getattr(candidate, "_current_debug_pause", None)
            edit = getattr(candidate, "_edit", None)
            debug_editors.append(
                {
                    "asset_key": str(getattr(editor_state, "asset_key", "") or ""),
                    "resolved_key": str(getattr(editor_state, "resolved_key", "") or ""),
                    "paused": pause is not None,
                    "module_id": str(getattr(pause, "module_id", "") or ""),
                    "line": int(getattr(edit, "_debug_line", 0) or 0),
                }
            )
        state["debug_editors"] = debug_editors
        if hasattr(vm, "_runtime_refresh_in_flight"):
            state["runtime_refresh_in_flight"] = bool(getattr(vm, "_runtime_refresh_in_flight", False))
        if include_tree:
            state["tree"] = view.tree_snapshot()
        return state

    def _set_subsystem_filter(self, guid: str, *, include_tree: bool = False) -> dict[str, Any]:
        view = self._view
        idx = view.find_subsystem_filter_index(guid)
        if idx >= 0:
            view.cb_subsystem_filter.setCurrentIndex(idx)
        else:
            view.cb_subsystem_filter.setCurrentIndex(0)
        return self._state(include_tree=include_tree)

    def _select_guid(self, guid: str, *, open_editor: bool, include_tree: bool = False) -> dict[str, Any]:
        view = self._view
        info = view.select_guid(guid)
        if info is None:
            raise RuntimeError(f"Guid not found: {guid}")
        if open_editor:
            try:
                opener = getattr(view, "open_object_tab", None)
                if callable(opener):
                    opener(info)
                else:
                    view.treeOpenRequested.emit(info)
                open_windows = getattr(view, "_open_windows", {})
                subwindow = open_windows.get(guid) if isinstance(open_windows, dict) else None
                mdi = getattr(view, "mdi", None)
                activate = getattr(mdi, "setActiveSubWindow", None)
                if subwindow is not None and callable(activate):
                    activate(subwindow)
                try:
                    view.raise_()
                except Exception:
                    pass
                try:
                    view.activateWindow()
                except Exception:
                    pass
            except Exception:
                try:
                    view.treeOpenRequested.emit(info)
                except Exception:
                    pass
        return self._state(include_tree=include_tree)

    def _open_guid(self, guid: str, *, include_tree: bool = False) -> dict[str, Any]:
        return self._select_guid(guid, open_editor=True, include_tree=include_tree)

    def _active_properties_state(self):
        schema_state = getattr(self._vm, "_schema_editor_state", None)
        schema_context = getattr(self._vm, "_schema_editor_context", {})
        if schema_context and getattr(schema_state, "current", None):
            return schema_state
        editor = getattr(self._vm, "_editor", None)
        return getattr(editor, "state", None)

    def _properties_state(self, *, include_payload: bool = False) -> dict[str, Any]:
        state = self._active_properties_state()
        current = dict(getattr(state, "current", None) or {})
        original = dict(getattr(state, "original", None) or {})
        if not include_payload:
            current.pop("payload", None)
            original.pop("payload", None)
        issues = []
        for issue in list(getattr(state, "issues", None) or []):
            issues.append(
                {
                    "field": str(getattr(issue, "field", "") or ""),
                    "message": str(getattr(issue, "message", "") or ""),
                }
            )
        return {
            "guid": str(getattr(state, "guid", "") or current.get("guid") or ""),
            "is_dirty": bool(getattr(state, "is_dirty", False)),
            "current": current,
            "original": original,
            "issues": issues,
        }

    def _properties_set(self, payload: dict[str, Any]) -> dict[str, Any]:
        field = str(payload.get("field") or "").strip()
        payload_key = str(payload.get("payload_key") or "").strip()
        if payload_key:
            state = self._active_properties_state()
            current = getattr(state, "current", None) or {}
            values = dict(current.get("payload") or {})
            values[payload_key] = payload.get("value")
            self._vm.on_editor_payload_changed(values)
        elif field:
            self._vm.on_editor_field_changed(field, payload.get("value"))
        else:
            raise RuntimeError("properties_set requires field or payload_key")
        return self._properties_state(include_payload=bool(payload.get("include_payload", True)))

    def _properties_save(self) -> dict[str, Any]:
        saved = bool(self._vm.on_save())
        result = self._properties_state(include_payload=True)
        result["saved"] = saved
        return result

    def _properties_revert(self) -> dict[str, Any]:
        self._vm.on_editor_revert()
        return self._properties_state(include_payload=True)

    def _active_form_designer(self, guid: str = ""):
        view = self._view

        def _is_designer(candidate) -> bool:
            return all(
                hasattr(candidate, attr)
                for attr in ("_center_tabs", "_left_tabs", "_object_tabs", "_module_editor")
            )

        open_windows = getattr(view, "_open_windows", {})
        target_guid = str(guid or "").strip()
        if target_guid and isinstance(open_windows, dict):
            subwindow = open_windows.get(target_guid)
            if subwindow is not None:
                try:
                    candidate = subwindow.widget()
                    if _is_designer(candidate):
                        return candidate
                except Exception:
                    pass

        mdi = getattr(view, "mdi", None)
        active = getattr(mdi, "activeSubWindow", lambda: None)()
        if active is not None:
            try:
                candidate = active.widget()
                if _is_designer(candidate):
                    return candidate
            except Exception:
                pass

        if isinstance(open_windows, dict):
            for sub in reversed(list(open_windows.values())):
                try:
                    candidate = sub.widget()
                    if _is_designer(candidate):
                        return candidate
                except Exception:
                    continue
        raise RuntimeError("Active form editor is not available")

    @staticmethod
    def _tab_state(tabs) -> dict[str, Any]:
        index = int(tabs.currentIndex())
        return {
            "index": index,
            "text": str(tabs.tabText(index) or "") if index >= 0 else "",
            "count": int(tabs.count()),
        }

    @staticmethod
    def _tree_state(tree) -> list[dict[str, Any]]:
        if tree is None or not hasattr(tree, "topLevelItemCount"):
            return []

        def serialize(item) -> dict[str, Any]:
            column_count = int(getattr(tree, "columnCount", lambda: 1)())
            texts = [str(item.text(column) or "") for column in range(column_count)]
            raw_data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(raw_data, dict):
                data = {
                    key: raw_data.get(key)
                    for key in ("kind", "code", "name", "binding", "type", "system", "tabular_part")
                    if key in raw_data
                }
            elif isinstance(raw_data, (str, int, float, bool)):
                data = raw_data
            else:
                data = None
            check_state = None
            try:
                if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    check_state = int(item.checkState(1).value)
            except Exception:
                check_state = None
            return {
                "texts": texts,
                "data": data,
                "checked": check_state,
                "expanded": bool(item.isExpanded()),
                "children": [serialize(item.child(index)) for index in range(item.childCount())],
            }

        return [serialize(tree.topLevelItem(index)) for index in range(tree.topLevelItemCount())]

    def _form_editor_state(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        editor = self._active_form_designer(str((payload or {}).get("guid") or ""))
        result = {
            "form_guid": str(getattr(editor, "_form_guid", "") or ""),
            "form_title": str(getattr(editor, "_form_title", "") or ""),
            "workspace": self._tab_state(editor._center_tabs),
            "structure": self._tab_state(editor._left_tabs),
            "object_data": self._tab_state(editor._object_tabs),
            "module_length": len(str(editor._module_editor.toPlainText() or "")),
        }
        command_tabs = getattr(editor, "_command_scope_tabs", None)
        if command_tabs is not None:
            result["command_scope"] = self._tab_state(command_tabs)
        result["elements"] = self._tree_state(getattr(editor, "tree", None))
        result["requisites"] = self._tree_state(getattr(editor, "requisites", None))
        return result

    def _form_editor_tab(self, payload: dict[str, Any]) -> dict[str, Any]:
        editor = self._active_form_designer()
        groups = {
            "workspace": (editor._center_tabs, {"form": 0, "design": 0, "module": 1}),
            "structure": (editor._left_tabs, {"elements": 0, "command_interface": 1}),
            "object_data": (editor._object_tabs, {"requisites": 0, "commands": 1, "parameters": 2}),
            "command_scope": (
                getattr(editor, "_command_scope_tabs", None),
                {"form": 0, "standard": 1, "global": 2},
            ),
        }
        group_name = str(payload.get("group") or "workspace").strip().lower()
        value = str(payload.get("tab") or payload.get("value") or "").strip().lower()
        if group_name not in groups:
            raise RuntimeError(f"Unknown form editor tab group: {group_name}")
        tabs, aliases = groups[group_name]
        if tabs is None:
            raise RuntimeError(f"Form editor tab group is not available: {group_name}")
        if value in aliases:
            index = aliases[value]
        else:
            try:
                index = int(value)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"Unknown form editor tab: {value}") from exc
        if index < 0 or index >= int(tabs.count()):
            raise RuntimeError(f"Form editor tab index is out of range: {index}")
        tabs.setCurrentIndex(index)
        return self._form_editor_state()

    def _form_editor_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        from src.dsl.completion import completion_context
        from src.ui_qt.widgets.code_editor_widget import (
            completion_candidates_for_editor,
        )

        editor = self._active_form_designer()._module_editor
        source = str(payload.get("source") if "source" in payload else editor.toPlainText())
        cursor_position = int(payload.get("cursor_position") or len(source))
        context = completion_context(source, cursor_position)
        candidates = completion_candidates_for_editor(
            editor,
            source,
            cursor_position,
        )
        prefix = context.prefix.casefold()
        if prefix:
            candidates = [item for item in candidates if item.casefold().startswith(prefix)]
        return {
            "chain": list(context.chain),
            "prefix": context.prefix,
            "replace_length": int(context.replace_length),
            "line": int(context.line),
            "candidates": candidates,
        }

    def _active_code_editor(self):
        finder = getattr(self._view, "_active_code_editor", None)
        editor = finder() if callable(finder) else None
        if editor is not None:
            return editor
        try:
            designer = self._active_form_designer()
        except RuntimeError:
            designer = None
        if designer is not None:
            editor = getattr(designer, "_module_editor", None)
            if editor is not None:
                return editor
        raise RuntimeError("Active code editor is not available")

    def _code_editor_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        from src.dsl.completion import completion_context
        from src.ui_qt.widgets.code_editor_widget import (
            common_module_completion_members_from_vm,
            completion_candidates_for_editor,
            metadata_completion_objects_from_vm,
        )

        try:
            editor = self._active_code_editor()
        except RuntimeError:
            editor = None
        edit = getattr(editor, "_edit", None)
        text_editor = editor if callable(getattr(editor, "textCursor", None)) else edit
        if text_editor is None:
            if "source" not in payload:
                raise RuntimeError("Active code editor document is not available")
            text_editor = SimpleNamespace(
                _autocomplete_words=set(),
                _autocomplete_metadata_objects=metadata_completion_objects_from_vm(
                    self._vm
                ),
                _autocomplete_namespace_members={},
                _autocomplete_namespace_provider=lambda namespace: (
                    common_module_completion_members_from_vm(self._vm, namespace)
                ),
            )
        source = str(
            payload.get("source")
            if "source" in payload
            else text_editor.toPlainText()
        )
        cursor_position = int(
            payload.get("cursor_position")
            if payload.get("cursor_position") is not None
            else len(source)
        )
        context = completion_context(source, cursor_position)
        candidates = completion_candidates_for_editor(
            text_editor,
            source,
            cursor_position,
        )
        prefix = context.prefix.casefold()
        if prefix:
            candidates = [
                item
                for item in candidates
                if item.casefold().startswith(prefix)
            ]
        return {
            "chain": list(context.chain),
            "prefix": context.prefix,
            "replace_length": int(context.replace_length),
            "line": int(context.line),
            "candidates": candidates,
        }

    def _code_editor_diagnostics_state(self) -> dict[str, Any]:
        editor = self._active_code_editor()
        edit = getattr(editor, "_edit", None)
        grouped = dict(getattr(edit, "_workspace_diagnostics", {}) or {})
        state = getattr(editor, "state", None)
        return {
            "asset_key": str(
                getattr(state, "resolved_key", "")
                or getattr(state, "asset_key", "")
                or ""
            ),
            "lines": sorted(int(line) for line in grouped),
            "diagnostic_count": sum(len(items) for items in grouped.values()),
            "debug_line": int(getattr(edit, "_debug_line", 0) or 0),
        }

    def _workspace_semantic_index_info(self) -> dict[str, Any]:
        service = getattr(self._vm, "_service", None)
        getter = getattr(service, "get_workspace_semantic_index_info", None)
        if not callable(getter):
            raise RuntimeError("Workspace semantic index is not available")
        return dict(getter() or {})

    def _workspace_semantic_diagnostics(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        service = getattr(self._vm, "_service", None)
        getter = getattr(service, "get_workspace_semantic_diagnostics", None)
        if not callable(getter):
            raise RuntimeError("Workspace semantic diagnostics are not available")
        diagnostics = getter(
            module_guid=str(payload.get("module_guid") or "").strip(),
            code=str(payload.get("code") or "").strip(),
            limit=int(payload.get("limit") or 500),
        )
        return {
            "diagnostics": [
                dict(item)
                for item in list(diagnostics or [])
                if isinstance(item, dict)
            ]
        }

    def _workspace_problems_state(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        panel = getattr(self._view, "workspace_problems", None)
        state = getattr(panel, "state", None)
        if not callable(state):
            raise RuntimeError("Workspace problems panel is not available")
        result = dict(
            state(
                include_diagnostics=bool(
                    payload.get("include_diagnostics", False)
                )
            )
            or {}
        )
        dock = getattr(self._view, "dock_problems", None)
        result["visible"] = bool(dock is not None and dock.isVisible())
        return result

    def _workspace_problems_refresh(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        panel = getattr(self._view, "workspace_problems", None)
        refresh = getattr(panel, "refresh_async", None)
        if not callable(refresh):
            raise RuntimeError("Workspace problems panel is not available")
        dock = getattr(self._view, "dock_problems", None)
        if bool(payload.get("show", True)) and dock is not None:
            dock.setVisible(True)
        queued = bool(refresh())
        result = self._workspace_problems_state(payload)
        result["queued"] = bool(queued or result.get("loading"))
        return result

    def _workspace_problem_navigate(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        direction = str(payload.get("direction") or "next").strip().lower()
        delta = -1 if direction in {"previous", "prev", "back", "-1"} else 1
        navigate = getattr(self._view, "_navigate_workspace_problem", None)
        if not callable(navigate):
            raise RuntimeError("Workspace Problems navigation is unavailable")
        moved = bool(navigate(delta))
        result = self._workspace_problems_state(payload)
        result["moved"] = moved
        result["direction"] = "previous" if delta < 0 else "next"
        return result

    def _workspace_symbol_definition(self, payload: dict[str, Any]) -> dict[str, Any]:
        qualifier = str(payload.get("qualifier") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not qualifier or not name:
            raise RuntimeError("qualifier and name are required")
        service = getattr(self._vm, "_service", None)
        resolver = getattr(service, "resolve_workspace_symbol", None)
        if not callable(resolver):
            raise RuntimeError("Workspace symbol resolver is not available")
        target = dict(resolver(qualifier, name) or {})
        return {"found": bool(target), "target": target}

    def _code_editor_go_to_definition(self, payload: dict[str, Any]) -> dict[str, Any]:
        editor = self._active_code_editor()
        edit = getattr(editor, "_edit", None)
        text_editor = editor if callable(getattr(editor, "textCursor", None)) else edit
        if text_editor is None:
            raise RuntimeError("Active code editor document is not available")
        source = str(text_editor.toPlainText() or "")
        if "source" in payload:
            source = str(payload.get("source") or "")
            text_editor.setPlainText(source)

        position_value = payload.get("cursor_position")
        if position_value is None:
            needle = str(payload.get("find") or "").strip()
            if not needle:
                raise RuntimeError("cursor_position or find is required")
            position = source.find(needle)
            if position < 0:
                raise RuntimeError(f"Expression not found in active module: {needle}")
            position += max(0, int(payload.get("find_offset") or 0))
        else:
            position = int(position_value)
        position = max(0, min(position, len(source)))

        cursor = text_editor.textCursor()
        cursor.setPosition(position)
        text_editor.setTextCursor(cursor)

        from src.ui_qt.widgets.code_editor_widget import resolve_definition_target

        refresh = getattr(editor, "_refresh_introspection", None)
        if callable(refresh):
            refresh()
        target = resolve_definition_target(
            source,
            position,
            introspection=getattr(editor, "_module_introspection", None),
            vm=self._vm,
        )
        if target is None:
            raise RuntimeError("Definition was not resolved")

        navigate = getattr(editor, "_go_to_definition", None)
        if not callable(navigate):
            raise RuntimeError("Go to definition is not available")
        navigate()
        QApplication.processEvents()
        QApplication.processEvents()

        mdi = getattr(self._view, "mdi", None)
        active = getattr(mdi, "activeSubWindow", lambda: None)()
        active_widget = None
        if active is not None:
            try:
                active_widget = active.widget()
            except Exception:
                active_widget = None
        active_state = getattr(active_widget, "state", None)
        active_edit = getattr(active_widget, "_edit", None)
        active_line = 0
        if active_edit is not None:
            active_line = int(active_edit.textCursor().blockNumber()) + 1
        return {
            "target": target.as_dict(),
            "active_title": str(getattr(active, "windowTitle", lambda: "")() or ""),
            "active_asset_key": str(getattr(active_state, "asset_key", "") or ""),
            "active_line": active_line,
            "open_windows": list(getattr(self._view, "_open_windows", {}).keys()),
        }

    def _code_editor_find_usages(self, payload: dict[str, Any]) -> dict[str, Any]:
        term = self._usage_term(payload)
        service = getattr(self._vm, "_service", None)
        semantic_search = getattr(service, "find_workspace_references", None)
        use_semantic = (
            bool(payload.get("whole_word", True))
            and not str(payload.get("module_guid") or "").strip()
            and len([part for part in term.split(".") if part.strip()]) >= 2
            and callable(semantic_search)
        )
        search = (
            semantic_search
            if use_semantic
            else getattr(service, "search_module_text", None)
        )
        if not callable(search):
            raise RuntimeError("Runtime module search is not available")
        if use_semantic:
            hits = search(
                term,
                limit=int(payload.get("limit") or 500),
                include_declaration=True,
            )
        else:
            hits = search(
                term,
                match_case=bool(payload.get("match_case", False)),
                whole_word=bool(payload.get("whole_word", True)),
                module_guid=str(payload.get("module_guid") or "").strip(),
                limit=int(payload.get("limit") or 500),
            )
        return {
            "term": term,
            "count": len(hits),
            "semantic": bool(use_semantic),
            "hits": hits,
        }

    def _code_editor_show_usages(self, payload: dict[str, Any]) -> dict[str, Any]:
        term = self._usage_term(payload)
        open_usages = getattr(self._view, "_open_usages_target", None)
        if not callable(open_usages):
            raise RuntimeError("Find usages UI is not available")
        query = {
            "term": term,
            "match_case": bool(payload.get("match_case", False)),
            "whole_word": bool(payload.get("whole_word", True)),
            "module_guid": str(payload.get("module_guid") or "").strip(),
            "limit": int(payload.get("limit") or 500),
        }
        open_usages(query)
        return {
            "term": term,
            "opened": True,
            "window_count": len(getattr(self._view, "_usage_search_dialogs", []) or []),
        }

    def _code_editor_usages_state(self) -> dict[str, Any]:
        windows = []
        for dialog in list(getattr(self._view, "_usage_search_dialogs", []) or []):
            table = getattr(dialog, "table", None)
            status = getattr(dialog, "lbl_status", None)
            editor = getattr(dialog, "ed_find", None)
            rows = []
            if table is not None:
                for row in range(int(table.rowCount())):
                    rows.append(
                        {
                            "title": str(table.item(row, 0).text() if table.item(row, 0) else ""),
                            "where": str(table.item(row, 1).text() if table.item(row, 1) else ""),
                            "line": int(table.item(row, 2).text() if table.item(row, 2) else 0),
                            "preview": str(table.item(row, 3).text() if table.item(row, 3) else ""),
                        }
                    )
            windows.append(
                {
                    "visible": bool(dialog.isVisible()) if callable(getattr(dialog, "isVisible", None)) else False,
                    "term": str(editor.text() if editor is not None else ""),
                    "status": str(status.text() if status is not None else ""),
                    "rows": rows,
                }
            )
        return {"window_count": len(windows), "windows": windows}

    def _usage_term(self, payload: dict[str, Any]) -> str:
        term = str(payload.get("term") or "").strip()
        if term:
            return term
        editor = self._active_code_editor()
        edit = getattr(editor, "_edit", None)
        text_editor = editor if callable(getattr(editor, "textCursor", None)) else edit
        if text_editor is None:
            raise RuntimeError("Active code editor document is not available")
        from src.ui_qt.widgets.code_editor_widget import identifier_chain_at

        term = ".".join(
            identifier_chain_at(
                text_editor.toPlainText(),
                text_editor.textCursor().position(),
            )
        )
        if not term:
            raise RuntimeError("Usage symbol was not resolved")
        return term

    def _code_editor_rename(self, payload: dict[str, Any], *, apply: bool) -> dict[str, Any]:
        editor = None
        text_editor = None
        source = str(payload.get("source") or "")
        if not source or apply:
            editor = self._active_code_editor()
            edit = getattr(editor, "_edit", None)
            text_editor = editor if callable(getattr(editor, "textCursor", None)) else edit
            if text_editor is None:
                raise RuntimeError("Active code editor document is not available")
            if not source:
                source = str(text_editor.toPlainText() or "")

        position_value = payload.get("cursor_position")
        if position_value is None:
            needle = str(payload.get("find") or "").strip()
            if needle:
                position = source.find(needle)
                if position < 0:
                    raise RuntimeError(f"Rename symbol not found: {needle}")
                position += max(0, int(payload.get("find_offset") or 0))
            elif text_editor is not None:
                position = int(text_editor.textCursor().position())
            else:
                raise RuntimeError("cursor_position or find is required")
        else:
            position = int(position_value)

        from src.dsl.semantic_rename import plan_semantic_rename

        plan = plan_semantic_rename(
            source,
            position,
            str(payload.get("new_name") or ""),
            language="mixed",
        )
        if apply:
            from src.ui_qt.widgets.semantic_rename_dialog import apply_semantic_rename_plan

            apply_semantic_rename_plan(text_editor, plan)
            refresh = getattr(editor, "_refresh_module_introspection", None)
            if callable(refresh):
                refresh()
        return {
            "old_name": plan.old_name,
            "new_name": plan.new_name,
            "symbol_kind": plan.symbol_kind,
            "scope_name": plan.scope_name,
            "count": len(plan.occurrences),
            "occurrences": [
                {
                    "start": occurrence.start,
                    "end": occurrence.end,
                    "line": occurrence.line,
                    "col": occurrence.col,
                    "preview": occurrence.preview,
                    "declaration": occurrence.declaration,
                }
                for occurrence in plan.occurrences
            ],
            "updated_source": plan.updated_source,
            "applied": bool(apply),
        }

    def _code_editor_rename_workspace_preview(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        editor = self._active_code_editor()
        edit = getattr(editor, "_edit", None)
        text_editor = editor if callable(getattr(editor, "textCursor", None)) else edit
        if text_editor is None:
            raise RuntimeError("Active code editor document is not available")
        state = getattr(editor, "state", None)
        asset_key = str(
            payload.get("module_guid")
            or getattr(state, "resolved_key", "")
            or getattr(state, "asset_key", "")
            or ""
        ).strip()
        module_guid = asset_key.split("://", 1)[-1].strip()
        if not module_guid:
            raise RuntimeError("Active module GUID is not available")
        source = str(text_editor.toPlainText() or "")
        position_value = payload.get("cursor_position")
        if position_value is None:
            needle = str(payload.get("find") or "").strip()
            if needle:
                position = source.find(needle)
                if position < 0:
                    raise RuntimeError(f"Rename symbol not found: {needle}")
                position += max(0, int(payload.get("find_offset") or 0))
            else:
                position = int(text_editor.textCursor().position())
        else:
            position = int(position_value)
        from src.dsl.semantic_rename import symbol_name_at

        symbol_name = symbol_name_at(source, position, language="mixed")
        if not symbol_name:
            raise RuntimeError("Workspace rename symbol was not resolved")
        service = getattr(self._vm, "_service", None)
        planner = getattr(service, "plan_workspace_symbol_rename", None)
        if not callable(planner):
            raise RuntimeError("Workspace rename service is not available")
        return dict(
            planner(
                module_guid,
                new_name=str(payload.get("new_name") or ""),
                symbol_name=symbol_name,
                module_name=str(payload.get("module_name") or ""),
            )
            or {}
        )

    def _code_editor_rename_workspace_apply(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        editor = self._active_code_editor()
        if bool(getattr(editor, "is_dirty", lambda: False)()):
            raise RuntimeError("Save the active module before workspace rename")
        state = getattr(editor, "state", None)
        asset_key = str(
            payload.get("module_guid")
            or getattr(state, "resolved_key", "")
            or getattr(state, "asset_key", "")
            or ""
        ).strip()
        module_guid = asset_key.split("://", 1)[-1].strip()
        if not module_guid:
            raise RuntimeError("Active module GUID is not available")
        modules = [
            dict(item)
            for item in list(payload.get("modules") or [])
            if isinstance(item, dict)
        ]
        if not modules:
            raise RuntimeError("Workspace rename preview is required")
        affected_guids = {
            str(item.get("module_guid") or "").strip()
            for item in modules
        }
        affected_editors = []
        dirty_titles = []
        for candidate in self._view.findChildren(type(editor)):
            candidate_state = getattr(candidate, "state", None)
            candidate_key = str(
                getattr(candidate_state, "resolved_key", "")
                or getattr(candidate_state, "asset_key", "")
                or ""
            ).strip()
            candidate_guid = candidate_key.split("://", 1)[-1].strip()
            if candidate_guid not in affected_guids:
                continue
            affected_editors.append(candidate)
            if bool(getattr(candidate, "is_dirty", lambda: False)()):
                dirty_titles.append(
                    str(
                        getattr(candidate, "title", "")
                        or getattr(candidate, "windowTitle", lambda: "")()
                        or candidate_guid
                    )
                )
        if dirty_titles:
            raise RuntimeError(
                "Save or discard changes in affected modules: "
                + ", ".join(dirty_titles)
            )
        service = getattr(self._vm, "_service", None)
        applier = getattr(service, "apply_workspace_symbol_rename", None)
        if not callable(applier):
            raise RuntimeError("Workspace rename service is not available")
        result = dict(
            applier(
                module_guid,
                new_name=str(payload.get("new_name") or ""),
                symbol_name=str(payload.get("symbol_name") or ""),
                module_name=str(payload.get("module_name") or ""),
                modules=modules,
                updated_by=str(payload.get("updated_by") or "control_api"),
            )
            or {}
        )
        for candidate in affected_editors:
            reload_editor = getattr(candidate, "reload", None)
            if callable(reload_editor):
                reload_editor()
        return result

    def _open_debug_module(self, payload: dict[str, Any]) -> dict[str, Any]:
        module_ref, module_guid, title, line, _pause = self._open_and_focus_debug_module(payload)
        return {
            "module_ref": module_ref or f"module://{module_guid}",
            "module_guid": module_guid,
            "title": title,
            "line": line,
        }

    def _debug_client_status(self) -> dict[str, Any]:
        view = self._view
        checker = getattr(view, "_debug_client_is_running", None)
        running = bool(checker()) if callable(checker) else False
        proc = getattr(view, "_debug_client_process", None)
        return {
            "running": running,
            "pid": int(getattr(proc, "pid", 0) or 0) if running else 0,
            "paused": isinstance(self._active_debug_pause, dict),
        }

    def _launch_debug_client(self, *, restart: bool) -> dict[str, Any]:
        status = self._debug_client_status()
        if status["running"]:
            if not restart:
                return status
            self._stop_debug_client(force=True)
        launcher = getattr(self._view, "_launch_client", None)
        if not callable(launcher):
            raise RuntimeError("Debug client launcher is not available")
        launcher(debug=True)
        return self._debug_client_status()

    def _stop_debug_client(self, *, force: bool) -> dict[str, Any]:
        stopper = getattr(self._view, "_stop_debug_client", None)
        if not callable(stopper):
            raise RuntimeError("Debug client stopper is not available")
        stopper(force=force, notify=False)
        return self._debug_client_status()

    def _debug_command(self, command: str) -> dict[str, Any]:
        command = str(command or "continue").strip().lower() or "continue"
        if command not in {"continue", "step_into", "step_over", "step_out"}:
            raise RuntimeError(f"Unsupported debug command: {command}")
        finder = getattr(self._view, "_paused_code_editor", None)
        editor = finder() if callable(finder) else None
        request = getattr(editor, "_request_debug_command", None)
        if callable(request):
            request(command)
        else:
            active = self._active_debug_pause
            if not isinstance(active, dict):
                raise RuntimeError("Debugger is not paused")
            command_state = active.get("command")
            if isinstance(command_state, dict):
                command_state["value"] = command
            loop = active.get("loop")
            if isinstance(loop, QEventLoop) and loop.isRunning():
                loop.quit()
        return {"accepted": True, "command": command}

    @staticmethod
    def _breakpoints_list() -> dict[str, Any]:
        from src.runtime.script.debugger import BreakpointStore

        store = BreakpointStore()
        return {
            "enabled": store.breakpoints_enabled(),
            "modules": {
                module_id: [spec.to_raw() for spec in specs]
                for module_id, specs in store.load_specs().items()
            },
        }

    @staticmethod
    def _breakpoint_set(payload: dict[str, Any]) -> dict[str, Any]:
        from src.runtime.script.debugger import BreakpointSpec, BreakpointStore

        module_id = str(payload.get("module_id") or payload.get("module_ref") or "").strip()
        if not module_id:
            module_guid = str(payload.get("module_guid") or "").strip()
            module_id = f"module://{module_guid}" if module_guid else ""
        line = int(payload.get("line") or 0)
        if not module_id or line <= 0:
            raise RuntimeError("module_id and positive line are required")

        store = BreakpointStore()
        data = store.load_specs()
        specs = list(data.get(module_id, []))
        existing = next((item for item in specs if int(item.line) == line), None)
        if bool(payload.get("remove", False)):
            specs = [item for item in specs if int(item.line) != line]
        else:
            spec = existing or BreakpointSpec(line=line)
            for field_name in (
                "enabled",
                "condition",
                "description",
                "hit_operator",
                "hit_target",
                "caller_name",
                "log_message",
                "action_expression",
                "log_call_stack",
                "log_hit_count",
                "continue_execution",
            ):
                if field_name in payload:
                    setattr(spec, field_name, payload[field_name])
            if existing is None:
                specs.append(spec)
        store.set_specs(module_id, specs)
        return ConfiguratorControlBridge._breakpoints_list()

    def _open_and_focus_debug_module(self, payload: dict[str, Any]) -> tuple[str, str, str, int, SimpleNamespace]:
        view = self._view
        module_ref = str(payload.get("module_ref") or payload.get("module_id") or "").strip()
        module_guid = str(payload.get("module_guid") or "").strip()
        if not module_guid and module_ref.startswith("module://"):
            module_guid = module_ref.split("://", 1)[1].strip()
        if not module_guid:
            raise RuntimeError("module_guid is required")
        line = int(payload.get("line") or 0)
        title = str(payload.get("title") or payload.get("code_name") or module_ref or module_guid).strip()

        from src.configurator.ui.widgets import NodeInfo

        opener = getattr(view, "open_object_tab", None)
        if callable(opener):
            opener(NodeInfo(kind="object", name=title, guid=module_guid, obj_type="common_module"))
        else:
            raise RuntimeError("open_object_tab is not available")

        pause = SimpleNamespace(
            module_id=module_ref or f"module://{module_guid}",
            code_name=title,
            line=line,
            depth=int(payload.get("depth") or 0),
            stack=list(payload.get("stack") or []),
            locals=dict(payload.get("locals") or {}),
            globals=dict(payload.get("globals") or {}),
        )

        def _find_widget():
            def _is_debug_editor(candidate) -> bool:
                if candidate is None:
                    return False
                if not callable(getattr(candidate, "focus_debug_location", None)):
                    return False
                asset_key = str(getattr(getattr(candidate, "state", None), "asset_key", "") or "").strip()
                resolved_key = str(getattr(getattr(candidate, "state", None), "resolved_key", "") or "").strip()
                keys = {asset_key, resolved_key}
                return any(
                    key
                    and (
                        key == module_ref
                        or key.endswith(module_guid)
                        or module_ref.endswith(key)
                    )
                    for key in keys
                )

            widget = None
            open_windows = getattr(view, "_open_windows", {})
            if isinstance(open_windows, dict):
                sub = open_windows.get(module_guid)
                if sub is not None:
                    try:
                        candidate = sub.widget()
                        if _is_debug_editor(candidate):
                            widget = candidate
                        elif candidate is not None:
                            for child in candidate.findChildren(QWidget):
                                if _is_debug_editor(child):
                                    widget = child
                                    break
                    except Exception:
                        widget = None
            if widget is None:
                try:
                    for child in view.findChildren(QWidget):
                        if _is_debug_editor(child):
                            widget = child
                            break
                except Exception:
                    widget = None
            return widget

        def _focus_line(remaining_ms: int = 30000) -> None:
            if line <= 0:
                return
            widget = _find_widget()
            if widget is None:
                if remaining_ms > 0:
                    QTimer.singleShot(50, lambda: _focus_line(remaining_ms - 50))
                return
            focus = getattr(widget, "focus_debug_location", None)
            if callable(focus):
                try:
                    focus(line, pause=pause)
                except Exception:
                    pass
            try:
                view.raise_()
                view.activateWindow()
            except Exception:
                pass

        QTimer.singleShot(0, _focus_line)
        pause._find_widget = _find_widget  # type: ignore[attr-defined]
        return module_ref, module_guid, title, line, pause

    def _debug_pause(self, payload: dict[str, Any]) -> dict[str, Any]:
        module_ref, module_guid, title, line, pause = self._open_and_focus_debug_module(payload)
        view = self._view
        command = {"value": ""}
        loop = QEventLoop(view)
        connection: dict[str, Any] = {"signal": None, "handler": None}
        active_pause = {"loop": loop, "command": command, "pause": pause}
        self._active_debug_pause = active_pause

        def _connect_widget(remaining_ms: int = 30000) -> None:
            widget = None
            finder = getattr(pause, "_find_widget", None)
            if callable(finder):
                widget = finder()
            signal = getattr(widget, "debugCommandRequested", None)
            if signal is not None:
                focus = getattr(widget, "focus_debug_location", None)
                if callable(focus):
                    try:
                        focus(line, pause=pause)
                    except Exception:
                        pass
                def _on_command(cmd: str) -> None:
                    command["value"] = str(cmd or "continue").strip().lower() or "continue"
                    try:
                        disconnect = getattr(signal, "disconnect", None)
                        if callable(disconnect):
                            disconnect(_on_command)
                    except Exception:
                        pass
                    loop.quit()

                try:
                    signal.connect(_on_command)
                    connection["signal"] = signal
                    connection["handler"] = _on_command
                    return
                except Exception:
                    pass
            if remaining_ms > 0:
                QTimer.singleShot(50, lambda: _connect_widget(remaining_ms - 50))
            else:
                loop.quit()

        QTimer.singleShot(0, _connect_widget)
        try:
            loop.exec()
        finally:
            signal = connection.get("signal")
            handler = connection.get("handler")
            if signal is not None and handler is not None:
                try:
                    signal.disconnect(handler)
                except Exception:
                    pass
            if self._active_debug_pause is active_pause:
                self._active_debug_pause = None
        return {
            "module_ref": module_ref or f"module://{module_guid}",
            "module_guid": module_guid,
            "title": title,
            "line": line,
            "command": command["value"],
        }

    def _start_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        view = self._view
        vm = self._vm
        source_path = str(payload.get("source_path") or "").strip()
        source_kind = str(payload.get("source_kind") or "auto").strip() or "auto"
        wipe_prefixes = bool(payload.get("wipe_prefixes", True))
        migrate_data = bool(payload.get("migrate_data", False))
        if not source_path:
            try:
                from src.platform.onec_import_state import load_last_onec_import

                last = load_last_onec_import()
                source_path = str(last.get("source_path") or "").strip()
                if not payload.get("source_kind"):
                    source_kind = str(last.get("source_kind") or source_kind).strip() or source_kind
            except Exception:
                source_path = ""
        if not source_path:
            raise RuntimeError("source_path is required")
        starter = getattr(view, "_start_onec_import", None)
        if not callable(starter):
            raise RuntimeError("Import workflow is not available")
        start_result = starter(
            source_path=source_path,
            source_kind=source_kind,
            wipe_prefixes=wipe_prefixes,
            migrate_data=migrate_data,
            interactive=False,
        )
        start_result = dict(start_result or {})
        if not bool(start_result.get("started")):
            raise RuntimeError(str(start_result.get("error") or "Import worker was not started"))
        session_id = str(start_result.get("session_id") or "").strip()
        if not session_id:
            raise RuntimeError("Import worker started without a session id")
        return {
            "queued": True,
            "source_path": source_path,
            "source_kind": source_kind,
            "wipe_prefixes": wipe_prefixes,
            "migrate_data": migrate_data,
            "session_id": session_id,
        }

    def _verify_subsystem(self, payload: dict[str, Any]) -> dict[str, Any]:
        vm = self._vm
        service = getattr(vm, "_service", None)
        guid = str(payload.get("guid") or "").strip()
        name = str(payload.get("name") or "").strip()
        title = str(payload.get("title") or "").strip()

        obj = None
        if hasattr(vm, "list_objects"):
            try:
                for candidate in vm.list_objects() or []:
                    if str(getattr(candidate, "type", "") or "").strip().lower() != "subsystem":
                        continue
                    c_guid = str(getattr(candidate, "guid", "") or "").strip()
                    c_name = str(getattr(candidate, "name", "") or "").strip()
                    c_title = str(getattr(candidate, "title", "") or "").strip()
                    if guid and c_guid == guid:
                        obj = candidate
                        break
                    if name and (c_name == name or c_title == name):
                        obj = candidate
                        break
                    if title and (c_name == title or c_title == title):
                        obj = candidate
                        break
            except Exception:
                obj = None

        if obj is None:
            raise RuntimeError("Subsystem not found")

        sub_guid = str(getattr(obj, "guid", "") or "").strip()
        payload_data: dict[str, Any] = {}
        objects: list[str] = []
        if service is not None:
            try:
                payload_data = dict(service.manifest_get_payload(sub_guid) or {})
            except Exception:
                payload_data = {}
            try:
                objects = list(service.manifest_get_objects(sub_guid) or [])
            except Exception:
                objects = []
        if not objects and isinstance(payload_data.get("objects"), list):
            objects = [str(x).strip() for x in payload_data.get("objects") or [] if str(x).strip()]

        return {
            "guid": sub_guid,
            "name": str(getattr(obj, "name", "") or ""),
            "title": str(getattr(obj, "title", "") or ""),
            "objects_count": len(objects),
            "objects": objects,
            "content_refs_count": len([x for x in list(payload_data.get("content_refs") or []) if str(x).strip()]),
            "payload_keys": sorted(payload_data.keys()),
            "has_objects": bool(objects),
        }

    def _compare_source_structure(self, payload: dict[str, Any]) -> dict[str, Any]:
        vm = self._vm
        source_path = str(payload.get("source_path") or "").strip()
        source_kind = str(payload.get("source_kind") or "auto").strip() or "auto"
        if not source_path:
            try:
                from src.platform.onec_import_state import load_last_onec_import

                last = load_last_onec_import()
                source_path = str(last.get("source_path") or "").strip()
                if not payload.get("source_kind"):
                    source_kind = str(last.get("source_kind") or source_kind).strip() or source_kind
            except Exception:
                source_path = ""
        if not source_path:
            raise RuntimeError("source_path is required")

        vm_compare = getattr(vm, "compare_source_structure", None)
        if callable(vm_compare):
            return vm_compare(source_path=source_path, source_kind=source_kind)
        raise RuntimeError("Source structure comparison is not available")

    def _repair_source_structure(self, payload: dict[str, Any]) -> dict[str, Any]:
        vm = self._vm
        source_path = str(payload.get("source_path") or "").strip()
        source_kind = str(payload.get("source_kind") or "auto").strip() or "auto"
        if not source_path:
            try:
                from src.platform.onec_import_state import load_last_onec_import

                last = load_last_onec_import()
                source_path = str(last.get("source_path") or "").strip()
                if not payload.get("source_kind"):
                    source_kind = str(last.get("source_kind") or source_kind).strip() or source_kind
            except Exception:
                source_path = ""
        if not source_path:
            raise RuntimeError("source_path is required")

        vm_repair = getattr(vm, "repair_source_structure", None)
        if callable(vm_repair):
            return vm_repair(source_path=source_path, source_kind=source_kind)
        raise RuntimeError("Source structure repair is not available")

    def _audit_source_structure(self, payload: dict[str, Any]) -> dict[str, Any]:
        vm = self._vm
        source_path = str(payload.get("source_path") or "").strip()
        source_kind = str(payload.get("source_kind") or "auto").strip() or "auto"
        repair = bool(payload.get("repair", True))
        if not source_path:
            try:
                from src.platform.onec_import_state import load_last_onec_import

                last = load_last_onec_import()
                source_path = str(last.get("source_path") or "").strip()
                if not payload.get("source_kind"):
                    source_kind = str(last.get("source_kind") or source_kind).strip() or source_kind
            except Exception:
                source_path = ""
        if not source_path:
            raise RuntimeError("source_path is required")

        compare_fn = getattr(vm, "compare_source_structure", None)
        repair_fn = getattr(vm, "repair_source_structure", None)
        if not callable(compare_fn):
            raise RuntimeError("Source structure comparison is not available")

        compare_report = compare_fn(source_path=source_path, source_kind=source_kind)
        result: dict[str, Any] = {
            "source_path": source_path,
            "source_kind": source_kind,
            "compare": compare_report,
            "repair": {},
            "final": compare_report,
        }
        if not repair or not callable(repair_fn):
            return result

        summary = dict(compare_report.get("summary") or {})
        has_issues = bool(
            int(summary.get("flattened_subtree_count") or 0)
            or int(summary.get("parent_child_mismatch_count") or 0)
        )
        if not has_issues:
            return result

        repair_result = repair_fn(source_path=source_path, source_kind=source_kind)
        final_report = compare_fn(source_path=source_path, source_kind=source_kind)
        result["repair"] = repair_result
        result["final"] = final_report
        return result

    def _repair_subsystem_membership(self, payload: dict[str, Any]) -> dict[str, Any]:
        vm = self._vm
        service = getattr(vm, "_service", None)
        if service is None:
            raise RuntimeError("Runtime service is not available")

        target_guid = str(payload.get("guid") or "").strip()
        target_name = str(payload.get("name") or "").strip()
        target_title = str(payload.get("title") or "").strip()
        dry_run = bool(payload.get("dry_run", False))

        objects_by_guid: dict[str, str] = {}
        refs_by_guid: dict[str, str] = {}
        for candidate in vm.list_objects() or []:
            if str(getattr(candidate, "kind", "") or "").strip().lower() != "object":
                continue
            c_guid = str(getattr(candidate, "guid", "") or "").strip()
            if not c_guid:
                continue
            payload_dict = getattr(candidate, "payload", None)
            payload_dict = dict(payload_dict or {}) if isinstance(payload_dict, dict) else {}
            metadata_ref = str(payload_dict.get("metadata_ref") or "").strip()
            origin_path = ""
            imported = payload_dict.get("imported")
            if isinstance(imported, dict):
                origin_path = str(imported.get("origin") or "").strip()
            if not metadata_ref:
                try:
                    from src.infra.onec.onec_requisites_enrich import metadata_ref_from_import_origin, metadata_ref_for_manifest_object

                    metadata_ref = metadata_ref_from_import_origin(origin_path) if origin_path else ""
                    if not metadata_ref:
                        metadata_ref = metadata_ref_for_manifest_object(
                            obj_type=str(getattr(candidate, "type", "") or "").strip(),
                            name=str(getattr(candidate, "name", "") or "").strip(),
                            origin_path=origin_path,
                        )
                except Exception:
                    metadata_ref = metadata_ref or ""
            if metadata_ref:
                refs_by_guid[c_guid] = metadata_ref
                objects_by_guid.setdefault(metadata_ref, c_guid)

        repaired: list[dict[str, Any]] = []
        scanned = 0
        changed = 0

        for candidate in vm.list_objects() or []:
            if str(getattr(candidate, "type", "") or "").strip().lower() != "subsystem":
                continue
            c_guid = str(getattr(candidate, "guid", "") or "").strip()
            c_name = str(getattr(candidate, "name", "") or "").strip()
            c_title = str(getattr(candidate, "title", "") or "").strip()
            if target_guid and c_guid != target_guid:
                continue
            if target_name and c_name != target_name and c_title != target_name:
                continue
            if target_title and c_title != target_title and c_name != target_title:
                continue

            scanned += 1
            payload_data: dict[str, Any] = {}
            try:
                payload_data = dict(service.manifest_get_payload(c_guid) or {})
            except Exception:
                payload_data = {}

            current_objects = [str(x).strip() for x in list(payload_data.get("objects") or []) if str(x).strip()]
            current_content_refs = [str(x).strip() for x in list(payload_data.get("content_refs") or []) if str(x).strip()]

            resolved_objects: list[str] = []
            resolved_refs: list[str] = []
            seen_objects: set[str] = set()
            seen_refs: set[str] = set()

            def add_object(guid: str) -> None:
                guid = str(guid or "").strip()
                if not guid or guid in seen_objects:
                    return
                seen_objects.add(guid)
                resolved_objects.append(guid)

            def add_ref(ref: str) -> None:
                ref = str(ref or "").strip()
                if not ref or ref in seen_refs:
                    return
                seen_refs.add(ref)
                resolved_refs.append(ref)

            for guid in current_objects:
                add_object(guid)
                add_ref(refs_by_guid.get(guid, ""))
            for ref in current_content_refs:
                add_ref(ref)
                guid = objects_by_guid.get(ref, "")
                if guid:
                    add_object(guid)

            if not resolved_objects and resolved_refs:
                for ref in resolved_refs:
                    guid = objects_by_guid.get(ref, "")
                    if guid:
                        add_object(guid)

            if not resolved_refs and resolved_objects:
                for guid in resolved_objects:
                    add_ref(refs_by_guid.get(guid, ""))

            # Preserve functional refs even if they cannot be resolved to object guids.
            functional_refs = [
                ref for ref in current_content_refs if ref.startswith("FunctionalOption.") or ref.startswith("FunctionalOptionsParameter.")
            ]
            non_functional_refs = [ref for ref in resolved_refs if ref not in functional_refs]
            final_refs = non_functional_refs + [ref for ref in functional_refs if ref not in non_functional_refs]

            new_payload = dict(payload_data)
            new_payload["objects"] = resolved_objects
            new_payload["content_refs"] = final_refs

            if new_payload != payload_data:
                changed += 1
                repaired.append(
                    {
                        "guid": c_guid,
                        "name": c_name,
                        "title": c_title,
                        "objects_before": current_objects,
                        "objects_after": resolved_objects,
                        "content_refs_before": current_content_refs,
                        "content_refs_after": final_refs,
                    }
                )
                if not dry_run:
                    try:
                        service.update_object_payload(c_guid, new_payload)
                    except Exception as exc:
                        raise RuntimeError(f"Failed to repair subsystem {c_guid}: {exc}") from exc

        if not dry_run and changed:
            try:
                vm.reopen_db()
            except Exception:
                pass
            try:
                vm.refresh_from_runtime()
            except Exception:
                try:
                    vm.start_background_runtime_refresh()
                except Exception:
                    pass

        return {
            "scanned": scanned,
            "changed": changed,
            "dry_run": dry_run,
            "repaired": repaired[:50],
        }

    def _import_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        vm = self._vm
        session_id = str(payload.get("session_id") or getattr(self._view, "_import_session_id", "") or "").strip()
        if not session_id:
            try:
                session_id = str(vm.runtime_session_id() or "").strip()
            except Exception:
                session_id = ""
        if not session_id:
            return {"session_id": "", "state": {}}
        try:
            from src.runtime.gateway import RuntimeGateway

            gw = RuntimeGateway(str(getattr(vm, "runtime_url", "") or getattr(self._view, "runtime_url", "") or ""))
            gw.session_id = session_id
            state = gw.onec_import_status(session_id=session_id, history_limit=int(payload.get("history_limit") or 20))
        except Exception as exc:
            return {"session_id": session_id, "state": {}, "error": f"{type(exc).__name__}: {exc}"}
        return {"session_id": session_id, "state": state}

    def _restart_self(self, payload: dict[str, Any]) -> dict[str, Any]:
        view = self._view
        runtime_url = str(getattr(view, "runtime_url", "") or getattr(self._vm, "runtime_url", "") or "").strip()
        db_uid = str(getattr(view, "db_uid_str", "") or getattr(self._vm, "db_uid", "") or "").strip()
        db_path = str(getattr(view, "db_path", "") or getattr(self._vm, "db_path", "") or "").strip()
        server = getattr(self, "_server", None)
        host, port = ("127.0.0.1", 8766)
        if server is not None:
            try:
                host, port = server.server_address
            except Exception:
                pass

        argv = [
            sys.executable,
            "-m",
            "src.configurator.configurator_app",
            "--runtime",
            runtime_url,
            "--control-api-host",
            str(host),
            "--control-api-port",
            str(int(port)),
        ]
        if db_uid:
            argv.extend(["--db-uid", db_uid])
        if db_path:
            argv.extend(["--db-path", db_path])

        env = os.environ.copy()
        if runtime_url:
            env["META_RUNTIME_URL"] = runtime_url
        if db_uid:
            env["META_DB_UID"] = db_uid
        if db_path:
            env["META_DB_PATH"] = db_path
        env["META_CONTROL_API_HOST"] = str(host)
        env["META_CONTROL_API_PORT"] = str(int(port))

        def _do_restart() -> None:
            # On Windows os.execvpe starts the replacement process before the
            # old HTTP listener is released. Close the service first so the new
            # Configurator can bind the same control endpoint deterministically.
            self.abort_debug_pause()
            if server is not None:
                try:
                    server.shutdown()
                except Exception:
                    pass
                try:
                    server.server_close()
                except Exception:
                    pass
            subprocess.Popen(
                argv,
                cwd=os.getcwd(),
                env=env,
                close_fds=True,
            )
            app = QApplication.instance()
            if app is not None:
                app.quit()

        # Let the request handler send the accepted response before its server
        # is intentionally shut down.
        QTimer.singleShot(150, _do_restart)
        return {"scheduled": True, "argv": argv, "runtime_url": runtime_url, "db_uid": db_uid, "db_path": db_path}

    def _screenshot(self) -> dict[str, Any]:
        pm = self._view.grab()
        if pm.isNull():
            return {"mime": "image/png", "data": ""}
        from PySide6.QtCore import QBuffer, QByteArray

        buf = QBuffer()
        buf.open(QBuffer.OpenModeFlag.ReadWrite)
        pm.save(buf, "PNG")
        raw = bytes(buf.data())
        return {
            "mime": "image/png",
            "data": base64.b64encode(raw).decode("ascii"),
            "width": int(pm.width()),
            "height": int(pm.height()),
        }


class ConfiguratorControlRequestHandler(BaseHTTPRequestHandler):
    server_version = "MetaConfiguratorControl/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    @property
    def _bridge(self) -> ConfiguratorControlBridge:
        return getattr(self.server, "bridge")

    def _send_json(self, payload: dict[str, Any], code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, mime: str = "application/octet-stream", code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"status": "ok", "ts": time.time()})
            return
        if parsed.path == "/state":
            qs = parse_qs(parsed.query)
            include_tree = str(qs.get("tree", ["0"])[0]).strip().lower() in ("1", "true", "yes", "on")
            try:
                data = self._bridge.call("state", {"include_tree": include_tree}, timeout=10.0)
            except Exception as exc:
                self._send_json({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, code=500)
                return
            self._send_json({"status": "ok", "data": data})
            return
        if parsed.path == "/screenshot.png":
            try:
                data = self._bridge.call("screenshot", {}, timeout=10.0)
            except Exception as exc:
                self._send_json({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, code=500)
                return
            raw = base64.b64decode(str(data.get("data") or ""))
            self._send_bytes(raw, mime="image/png")
            return
        self._send_json({"status": "error", "error": "Not found"}, code=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/command":
            self._send_json({"status": "error", "error": "Not found"}, code=404)
            return
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length") or "0"))
            req = json.loads(raw.decode("utf-8")) if raw else {}
            action = str(req.get("action") or "").strip()
            payload = req.get("payload") or {}
            timeout = 86400.0 if action.strip().lower() == "debug_pause" else 20.0
            data = self._bridge.call(action, dict(payload or {}), timeout=timeout)
            self._send_json({"status": "ok", "data": data})
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return
        except Exception as exc:
            self._send_json({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, code=500)


def start_control_api(view, vm, *, host: str = "127.0.0.1", port: int = 8766) -> tuple[HTTPServer, str]:
    bridge = ConfiguratorControlBridge(view, vm)
    httpd = _ThreadedHTTPServer((host, int(port)), ConfiguratorControlRequestHandler)
    httpd.bridge = bridge  # type: ignore[attr-defined]
    bridge._server = httpd  # type: ignore[attr-defined]
    view._control_bridge = bridge  # type: ignore[attr-defined]
    view._control_api_server = httpd  # type: ignore[attr-defined]
    actual_host, actual_port = httpd.server_address

    def _serve() -> None:
        print(f"[control] listening on http://{actual_host}:{actual_port}", flush=True)
        httpd.serve_forever()

    threading.Thread(target=_serve, name="configurator-control-api", daemon=True).start()
    return httpd, f"http://{actual_host}:{actual_port}"
