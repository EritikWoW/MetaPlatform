from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from http.server import ThreadingHTTPServer

import pytest
from PySide6.QtCore import QEventLoop, QObject, Qt
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QTreeWidget, QTreeWidgetItem

import src.configurator.control_api as control_api_module
from src.configurator.application.manifest_editor import ManifestEditorState
from src.configurator.control_api import ConfiguratorControlBridge, _ThreadedHTTPServer


@dataclass
class _SubsystemStub:
    guid: str
    kind: str = "object"
    type: str = "subsystem"
    name: str = ""
    title: str = ""


class _ViewStub(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.runtime_url = "http://127.0.0.1:8765"
        self.db_uid_str = "db-uid"
        self.db_path = "F:/TestBD/MetaDB/metabase.mpdb"
        self._status = "ready"
        self._search = ""
        self._subsystem_filter_guid = ""
        self._open_windows: dict[str, object] = {}
        self._is_dirty = False
        self.opened: list[str] = []
        self.debug_editors: list[object] = []
        self.paused_editor = None
        self._debug_client_process = None
        self.debug_launches = 0
        self.debug_stops = 0
        self.usage_queries: list[dict] = []
        self._usage_search_dialogs: list[object] = []
        self.tree_model = type("Model", (), {"rowCount": lambda self: 0})()

    def findChildren(self, *_args, **_kwargs):
        return list(self.debug_editors)

    def statusBar(self):
        status = self._status
        return type("Bar", (), {"currentMessage": lambda _self, _status=status: _status})()

    def windowTitle(self):
        return "MetaPlatform"

    @property
    def search(self):
        search = self._search
        owner = self
        return type(
            "Search",
            (),
            {
                "text": lambda _self, _search=search: _search,
                "setText": lambda _self, value, _owner=owner: setattr(_owner, "_search", value),
            },
        )()

    def current_selection_info(self):
        return None

    def current_subsystem_filter_guid(self) -> str:
        return self._subsystem_filter_guid

    def find_subsystem_filter_index(self, _guid: str) -> int:
        return -1

    def select_guid(self, _guid: str):
        return None

    def tree_snapshot(self) -> list[dict]:
        return []

    def _start_onec_import(self, **kwargs):
        self.started_import = dict(kwargs)
        return {"started": True, "session_id": "import-session-1", "error": ""}

    def open_object_tab(self, info):
        self.opened.append(str(getattr(info, "guid", "") or ""))

    def _debug_client_is_running(self) -> bool:
        return self._debug_client_process is not None

    def _launch_client(self, *, debug: bool) -> None:
        assert debug is True
        self.debug_launches += 1
        self._debug_client_process = SimpleNamespace(pid=4242)

    def _stop_debug_client(self, *, force: bool, notify: bool) -> None:
        assert force is True
        assert notify is False
        self.debug_stops += 1
        self._debug_client_process = None

    def _paused_code_editor(self):
        return self.paused_editor

    def _open_usages_target(self, query: dict) -> None:
        self.usage_queries.append(dict(query))
        self._usage_search_dialogs.append(object())


@dataclass
class _VmStub:
    runtime_url: str = "http://127.0.0.1:8765"
    db_uid: str = "db-uid"
    db_path: str = "F:/TestBD/MetaDB/metabase.mpdb"
    started_refreshes: int = 0
    reopened: int = 0
    listed: list[_SubsystemStub] = field(default_factory=list)
    payload_by_guid: dict[str, dict] = field(default_factory=dict)
    objects_by_guid: dict[str, list[str]] = field(default_factory=dict)
    updated_payloads: list[tuple[str, dict]] = field(default_factory=list)
    updated_fields: list[tuple[str, dict]] = field(default_factory=list)
    module_search_hits: list[dict] = field(default_factory=list)
    workspace_rename_plan: dict = field(default_factory=dict)
    workspace_rename_result: dict = field(default_factory=dict)

    def runtime_session_id(self) -> str:
        return "session-1"

    def reopen_db(self) -> None:
        self.reopened += 1

    def refresh_from_runtime(self) -> None:
        self.started_refreshes += 1

    def start_background_runtime_refresh(self) -> None:
        self.started_refreshes += 1

    def list_objects(self):
        return list(self.listed)

    @property
    def _service(self):
        class _Svc:
            def __init__(self, outer):
                self._outer = outer
                self._payload_by_guid = outer.payload_by_guid
                self._objects_by_guid = outer.objects_by_guid

            def manifest_get_payload(self, guid: str):
                return dict(self._payload_by_guid.get(guid) or {})

            def manifest_get_objects(self, guid: str):
                return list(self._objects_by_guid.get(guid) or [])

            def update_object_payload(self, guid: str, payload: dict):
                payload = dict(payload or {})
                self._outer.updated_payloads.append((guid, payload))
                self._payload_by_guid[guid] = payload

            def update_object_fields(self, guid: str, **fields):
                self._outer.updated_fields.append((guid, dict(fields)))
                payload = dict(self._payload_by_guid.get(guid) or {})
                if "payload" in fields:
                    payload = dict(fields["payload"] or {})
                    self._payload_by_guid[guid] = payload

            def search_module_text(self, term: str, **options):
                self._outer.last_module_search = {"term": term, **options}
                return list(self._outer.module_search_hits)

            def plan_workspace_symbol_rename(self, module_guid: str, **options):
                self._outer.last_workspace_rename = {
                    "module_guid": module_guid,
                    **options,
                }
                return dict(self._outer.workspace_rename_plan)

            def apply_workspace_symbol_rename(self, module_guid: str, **options):
                self._outer.last_workspace_rename_apply = {
                    "module_guid": module_guid,
                    **options,
                }
                return dict(self._outer.workspace_rename_result)

        return _Svc(self)


def test_control_api_import_uses_last_source(monkeypatch) -> None:
    view = _ViewStub()
    vm = _VmStub()
    bridge = ConfiguratorControlBridge(view, vm)

    monkeypatch.setattr(
        "src.platform.onec_import_state.load_last_onec_import",
        lambda: {"source_path": "F:/ConfigFiles", "source_kind": "xml"},
    )

    result = bridge._dispatch("import_onec", {})

    assert result["queued"] is True
    assert result["session_id"] == "import-session-1"
    assert view.started_import["source_path"] == "F:/ConfigFiles"
    assert view.started_import["source_kind"] == "xml"
    assert view.started_import["interactive"] is False


def test_control_api_import_reports_worker_start_failure(monkeypatch) -> None:
    view = _ViewStub()
    view._start_onec_import = lambda **_kwargs: {
        "started": False,
        "session_id": "",
        "error": "runtime session unavailable",
    }
    bridge = ConfiguratorControlBridge(view, _VmStub())
    monkeypatch.setattr(
        "src.platform.onec_import_state.load_last_onec_import",
        lambda: {"source_path": "F:/ConfigFiles", "source_kind": "xml"},
    )

    with pytest.raises(RuntimeError, match="runtime session unavailable"):
        bridge._dispatch("import_onec", {})


def test_control_api_server_handles_requests_concurrently() -> None:
    assert issubclass(_ThreadedHTTPServer, ThreadingHTTPServer)


def test_abort_debug_pause_releases_active_loop_command() -> None:
    bridge = ConfiguratorControlBridge(_ViewStub(), _VmStub())
    command = {"value": ""}
    loop = QEventLoop()
    bridge._active_debug_pause = {"command": command, "loop": loop}

    assert bridge.abort_debug_pause() is True
    assert command["value"] == "continue"


def test_control_api_evaluates_expression_in_active_pause_scope() -> None:
    bridge = ConfiguratorControlBridge(_ViewStub(), _VmStub())
    bridge._active_debug_pause = {
        "pause": SimpleNamespace(
            module_id="module://managed",
            locals={},
            globals={"глФормаНачальнойНастройкиПрограммы": None},
        )
    }

    result = bridge._dispatch(
        "debug_evaluate",
        {"expression": "глФормаНачальнойНастройкиПрограммы"},
    )

    assert result["errors"] == []
    assert result["result"] is None
    assert result["type"] == "NoneType"


def test_control_api_can_inspect_edit_and_revert_schema_properties() -> None:
    vm = _VmStub()
    original = {
        "guid": "virtual:owner:attributes:Organization",
        "type": "schema_requisite",
        "name": "Organization",
        "title": "Організація",
        "payload": {"comment": "", "required": True},
    }
    vm._schema_editor_state = ManifestEditorState(
        guid=original["guid"],
        original={**original, "payload": dict(original["payload"])},
        current={**original, "payload": dict(original["payload"])},
        issues=[],
    )
    vm._schema_editor_context = {"owner_guid": "owner"}

    def set_payload(payload):
        vm._schema_editor_state.current = {
            **vm._schema_editor_state.current,
            "payload": dict(payload),
        }

    def revert():
        vm._schema_editor_state.current = {
            **vm._schema_editor_state.original,
            "payload": dict(vm._schema_editor_state.original["payload"]),
        }

    vm.on_editor_payload_changed = set_payload
    vm.on_editor_field_changed = lambda field, value: vm._schema_editor_state.current.update({field: value})
    vm.on_editor_revert = revert
    vm.on_save = lambda: True
    bridge = ConfiguratorControlBridge(_ViewStub(), vm)

    changed = bridge._dispatch(
        "properties_set",
        {"payload_key": "comment", "value": "control-api", "include_payload": True},
    )
    assert changed["is_dirty"] is True
    assert changed["current"]["payload"]["comment"] == "control-api"

    reverted = bridge._dispatch("properties_revert", {})
    assert reverted["is_dirty"] is False
    assert reverted["current"]["payload"]["comment"] == ""


def test_control_api_verify_subsystem_returns_objects() -> None:
    view = _ViewStub()
    vm = _VmStub(
        listed=[_SubsystemStub(guid="sub-1", name="НастройкаИнтеграции", title="Интеграція")],
        payload_by_guid={"sub-1": {"content_refs": ["a", "b"]}},
        objects_by_guid={"sub-1": ["obj-1", "obj-2"]},
    )
    bridge = ConfiguratorControlBridge(view, vm)

    result = bridge._dispatch("verify_subsystem", {"guid": "sub-1"})

    assert result["guid"] == "sub-1"
    assert result["objects_count"] == 2
    assert result["content_refs_count"] == 2
    assert result["has_objects"] is True


def test_control_api_restart_builds_exec_command(monkeypatch) -> None:
    view = _ViewStub()
    vm = _VmStub()
    bridge = ConfiguratorControlBridge(view, vm)

    scheduled = []
    monkeypatch.setattr(
        control_api_module.QTimer,
        "singleShot",
        lambda _ms, callback: scheduled.append(callback),
    )

    result = bridge._dispatch("restart_self", {})

    assert result["scheduled"] is True
    assert result["argv"][1:3] == ["-m", "src.configurator.configurator_app"]
    assert scheduled, "restart callback was not scheduled"


def test_control_api_restart_releases_server_before_spawning(monkeypatch) -> None:
    view = _ViewStub()
    bridge = ConfiguratorControlBridge(view, _VmStub())
    events: list[str] = []

    class _Server:
        server_address = ("127.0.0.1", 8766)

        def shutdown(self):
            events.append("shutdown")

        def server_close(self):
            events.append("close")

    class _App:
        def quit(self):
            events.append("quit")

    bridge._server = _Server()
    scheduled = []
    monkeypatch.setattr(
        control_api_module.QTimer,
        "singleShot",
        lambda _ms, callback: scheduled.append(callback),
    )
    monkeypatch.setattr(
        control_api_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: events.append("spawn"),
    )
    monkeypatch.setattr(control_api_module.QApplication, "instance", lambda: _App())

    bridge._dispatch("restart_self", {})
    scheduled[0]()

    assert events == ["shutdown", "close", "spawn", "quit"]


def test_control_state_reports_only_current_debug_marker_as_paused() -> None:
    view = _ViewStub()

    def _editor(asset_key: str, *, paused: bool, line: int):
        pause = SimpleNamespace(module_id=asset_key) if paused else None
        return SimpleNamespace(
            state=SimpleNamespace(asset_key=asset_key, resolved_key=asset_key),
            _current_debug_pause=pause,
            _edit=SimpleNamespace(_debug_line=line),
            focus_debug_location=lambda *_args, **_kwargs: None,
        )

    view.debug_editors = [
        _editor("module://managed", paused=False, line=0),
        _editor("module://ordinary", paused=True, line=85),
    ]
    state = ConfiguratorControlBridge(view, _VmStub())._dispatch("state", {})

    assert state["debug_editors"] == [
        {
            "asset_key": "module://managed",
            "resolved_key": "module://managed",
            "paused": False,
            "module_id": "",
            "line": 0,
        },
        {
            "asset_key": "module://ordinary",
            "resolved_key": "module://ordinary",
            "paused": True,
            "module_id": "module://ordinary",
            "line": 85,
        },
    ]


def test_control_api_import_status_reads_runtime_gateway(monkeypatch) -> None:
    view = _ViewStub()
    vm = _VmStub()
    bridge = ConfiguratorControlBridge(view, vm)

    class _Gw:
        def __init__(self, *_args, **_kwargs):
            self.session_id = ""

        def onec_import_status(self, *, session_id: str, history_limit: int):
            return {"session_id": session_id, "history_limit": history_limit, "status": "active"}

    monkeypatch.setattr("src.runtime.gateway.RuntimeGateway", _Gw)

    result = bridge._dispatch("import_status", {"history_limit": 7})

    assert result["session_id"] == "session-1"
    assert result["state"]["history_limit"] == 7


def test_control_api_repair_subsystem_membership_fills_objects_from_content_refs() -> None:
    view = _ViewStub()
    vm = _VmStub(
        listed=[
            _SubsystemStub(guid="sub-1", name="Administration", title="Адміністрування"),
            _SubsystemStub(guid="obj-1", kind="object", type="catalog", name="Products", title="Товари"),
        ],
        payload_by_guid={
            "sub-1": {"content_refs": ["Catalog.Products"], "objects": []},
            "obj-1": {"metadata_ref": "Catalog.Products"},
        },
    )
    bridge = ConfiguratorControlBridge(view, vm)

    result = bridge._dispatch("repair_subsystem_membership", {"guid": "sub-1"})

    assert result["changed"] == 1
    assert vm.updated_payloads
    guid, payload = vm.updated_payloads[-1]
    assert guid == "sub-1"
    assert payload["objects"] == ["obj-1"]
    assert payload["content_refs"] == ["Catalog.Products"]


def test_control_api_sync_subsystem_membership_returns_repaired_report() -> None:
    view = _ViewStub()

    @dataclass
    class _SyncVmStub(_VmStub):
        sync_calls: int = 0

        def sync_subsystem_membership(self, *, guid: str = "", name: str = "", title: str = ""):
            self.sync_calls += 1
            return {
                "scanned": 1,
                "mismatched": 0,
                "mismatched_before": 1,
                "mismatched_after": 0,
                "changed": 1,
                "auto_repaired": True,
                "before": {"mismatched": 1},
                "repair": {"changed": 1},
                "items": [],
            }

    vm = _SyncVmStub()
    bridge = ConfiguratorControlBridge(view, vm)

    result = bridge._dispatch("sync_subsystem_membership", {"guid": "sub-1"})

    assert vm.sync_calls == 1
    assert result["auto_repaired"] is True
    assert result["changed"] == 1


def test_control_api_compare_source_structure_uses_vm_method() -> None:
    view = _ViewStub()

    @dataclass
    class _CompareVmStub(_VmStub):
        compare_calls: int = 0

        def compare_source_structure(self, *, source_path: str = "", source_kind: str = ""):
            self.compare_calls += 1
            return {
                "summary": {"source_count": 1, "db_count": 1, "mismatched": 0},
                "items": [],
                "source": {"path": source_path, "semantic_kind": source_kind},
            }

    vm = _CompareVmStub()
    bridge = ConfiguratorControlBridge(view, vm)

    result = bridge._dispatch("compare_source_structure", {"source_path": "F:/ConfigFiles", "source_kind": "xml"})

    assert vm.compare_calls == 1
    assert result["summary"]["source_count"] == 1
    assert result["source"]["path"] == "F:/ConfigFiles"


def test_control_api_repair_source_structure_uses_vm_method() -> None:
    view = _ViewStub()

    @dataclass
    class _RepairVmStub(_VmStub):
        repair_calls: int = 0

        def repair_source_structure(self, *, source_path: str = "", source_kind: str = ""):
            self.repair_calls += 1
            return {
                "changed": 1,
                "scanned": 1,
                "repaired": [{"kind": "child_parent", "guid": "sub-child"}],
                "unresolved": [],
                "report": {
                    "summary": {"flattened_subtree_count": 1},
                    "flattened_subtrees": [],
                },
            }

    vm = _RepairVmStub()
    bridge = ConfiguratorControlBridge(view, vm)

    result = bridge._dispatch("repair_source_structure", {"source_path": "F:/ConfigFiles", "source_kind": "xml"})

    assert vm.repair_calls == 1
    assert result["changed"] == 1
    assert result["scanned"] == 1


def test_control_api_audit_source_structure_uses_vm_methods() -> None:
    view = _ViewStub()

    @dataclass
    class _AuditVmStub(_VmStub):
        compare_calls: int = 0
        repair_calls: int = 0

        def compare_source_structure(self, *, source_path: str = "", source_kind: str = ""):
            self.compare_calls += 1
            return {
                "summary": {"flattened_subtree_count": 1, "parent_child_mismatch_count": 0},
                "items": [],
                "source": {"path": source_path, "semantic_kind": source_kind},
            }

        def repair_source_structure(self, *, source_path: str = "", source_kind: str = ""):
            self.repair_calls += 1
            return {
                "changed": 1,
                "report": {
                    "summary": {"flattened_subtree_count": 0, "parent_child_mismatch_count": 0},
                    "source": {"path": source_path, "semantic_kind": source_kind},
                },
            }

    vm = _AuditVmStub()
    bridge = ConfiguratorControlBridge(view, vm)

    result = bridge._dispatch("audit_source_structure", {"source_path": "F:/ConfigFiles", "source_kind": "xml"})

    assert vm.compare_calls == 2
    assert vm.repair_calls == 1
    assert result["compare"]["summary"]["flattened_subtree_count"] == 1
    assert result["final"]["summary"]["flattened_subtree_count"] == 1


def test_control_api_open_uses_view_open_object_tab() -> None:
    view = _ViewStub()
    vm = _VmStub(
        listed=[_SubsystemStub(guid="sub-1", name="Administration", title="Адміністрування")],
        payload_by_guid={"sub-1": {"content_refs": []}},
        objects_by_guid={"sub-1": []},
    )
    view.select_guid = lambda guid: _SubsystemStub(guid=str(guid), name="Administration", title="Адміністрування")  # type: ignore[method-assign]
    bridge = ConfiguratorControlBridge(view, vm)

    result = bridge._dispatch("open", {"guid": "sub-1", "include_tree": True})

    assert view.opened == ["sub-1"]
    assert result["tree_count"] == 0


def test_control_api_open_activates_existing_mdi_window() -> None:
    view = _ViewStub()
    expected_window = object()
    activated: list[object] = []
    view._open_windows["form-1"] = expected_window
    view.mdi = SimpleNamespace(setActiveSubWindow=lambda window: activated.append(window))
    view.select_guid = lambda guid: _SubsystemStub(guid=str(guid), name="Form", title="Форма")  # type: ignore[method-assign]
    bridge = ConfiguratorControlBridge(view, _VmStub())

    bridge._dispatch("open", {"guid": "form-1"})

    assert view.opened == ["form-1"]
    assert activated == [expected_window]


def test_control_api_controls_form_editor_tabs_and_semantic_completion(monkeypatch) -> None:
    class _Tabs:
        def __init__(self, labels: list[str]) -> None:
            self.labels = labels
            self.index = 0

        def currentIndex(self) -> int:
            return self.index

        def setCurrentIndex(self, index: int) -> None:
            self.index = int(index)

        def tabText(self, index: int) -> str:
            return self.labels[index]

        def count(self) -> int:
            return len(self.labels)

    module_editor = SimpleNamespace(
        toPlainText=lambda: "Метадані.Довідники.",
        _autocomplete_words={"Метадані", "Повідомити"},
        _autocomplete_metadata_objects={"catalog": ("Контрагенти",)},
    )
    editor = SimpleNamespace(
        _form_guid="form-1",
        _form_title="Форма документа",
        _center_tabs=_Tabs(["Макет", "Модуль"]),
        _left_tabs=_Tabs(["Елементи", "Командний інтерфейс"]),
        _object_tabs=_Tabs(["Реквізити", "Команди", "Параметри"]),
        _command_scope_tabs=_Tabs(["Команди форми", "Стандартні", "Глобальні"]),
        _module_editor=module_editor,
    )
    bridge = ConfiguratorControlBridge(_ViewStub(), _VmStub())
    monkeypatch.setattr(bridge, "_active_form_designer", lambda *_args: editor)

    state = bridge._dispatch("form_editor_tab", {"group": "workspace", "tab": "module"})
    completion = bridge._dispatch(
        "form_editor_completion",
        {"source": "Метадані.Довідники.Ко", "cursor_position": 22},
    )

    assert state["workspace"] == {"index": 1, "text": "Модуль", "count": 2}
    assert state["form_guid"] == "form-1"
    assert state["elements"] == []
    assert state["requisites"] == []
    assert completion["chain"] == ["Метадані", "Довідники"]
    assert completion["prefix"] == "Ко"
    assert "Контрагенти" in completion["candidates"]
    assert "Количество" in completion["candidates"]


def test_control_api_reads_runtime_namespace_completion_from_active_editor() -> None:
    QApplication.instance() or QApplication([])
    edit = QPlainTextEdit()
    edit.setPlainText("SettingsServer.Re")
    edit._autocomplete_words = set()
    edit._autocomplete_metadata_objects = {}
    edit._autocomplete_namespace_members = {}
    calls: list[str] = []
    edit._autocomplete_namespace_provider = lambda name: (
        calls.append(name) or ["ReadSettings", "ResetCache"]
    )
    editor = SimpleNamespace(_edit=edit)
    view = _ViewStub()
    view._active_code_editor = lambda: editor  # type: ignore[attr-defined]
    bridge = ConfiguratorControlBridge(view, _VmStub())

    result = bridge._dispatch("code_editor_completion", {})

    assert result["chain"] == ["SettingsServer"]
    assert result["prefix"] == "Re"
    assert result["candidates"] == ["ReadSettings", "ResetCache"]
    assert calls == ["SettingsServer"]


def test_control_api_reads_runtime_completion_without_active_editor() -> None:
    service = SimpleNamespace(
        get_common_module_completion=lambda name: {
            "members": [
                {"name": "ReadSettings"},
                {"name": "ResetCache"},
            ]
            if name == "SettingsServer"
            else []
        }
    )
    view = _ViewStub()
    view._active_code_editor = lambda: None  # type: ignore[attr-defined]
    bridge = ConfiguratorControlBridge(
        view,
        SimpleNamespace(_service=service, _structure_cache={}),
    )
    source = "SettingsServer.Re"

    result = bridge._dispatch(
        "code_editor_completion",
        {"source": source, "cursor_position": len(source)},
    )

    assert result["chain"] == ["SettingsServer"]
    assert result["prefix"] == "Re"
    assert result["candidates"] == ["ReadSettings", "ResetCache"]


def test_control_api_exposes_workspace_semantic_index_without_active_editor() -> None:
    service = SimpleNamespace(
        get_workspace_semantic_index_info=lambda: {
            "generation": 3,
            "modules": 12,
            "symbols": 40,
        },
        resolve_workspace_symbol=lambda qualifier, name: {
            "module_guid": "module-1",
            "name": name,
            "owner_title": qualifier,
            "line": 7,
        },
    )
    bridge = ConfiguratorControlBridge(
        _ViewStub(),
        SimpleNamespace(_service=service),
    )

    info = bridge._dispatch("workspace_semantic_index_info", {})
    definition = bridge._dispatch(
        "workspace_symbol_definition",
        {"qualifier": "SettingsServer", "name": "ReadSettings"},
    )

    assert info["generation"] == 3
    assert info["modules"] == 12
    assert definition["found"] is True
    assert definition["target"]["module_guid"] == "module-1"
    assert definition["target"]["line"] == 7


def test_control_api_exposes_filtered_workspace_semantic_diagnostics() -> None:
    calls: list[tuple[str, str, int]] = []
    service = SimpleNamespace(
        get_workspace_semantic_diagnostics=(
            lambda *, module_guid, code, limit: (
                calls.append((module_guid, code, limit))
                or [
                    {
                        "module_guid": module_guid,
                        "code": code,
                        "line": 12,
                    }
                ]
            )
        )
    )
    bridge = ConfiguratorControlBridge(
        _ViewStub(),
        SimpleNamespace(_service=service),
    )

    result = bridge._dispatch(
        "workspace_semantic_diagnostics",
        {
            "module_guid": "module-1",
            "code": "unresolved_member",
            "limit": 25,
        },
    )

    assert result["diagnostics"][0]["line"] == 12
    assert calls == [("module-1", "unresolved_member", 25)]


def test_control_api_exposes_workspace_problems_panel_state_and_refresh() -> None:
    panel = SimpleNamespace(
        loading=False,
        refresh_async=lambda: True,
        state=lambda *, include_diagnostics: {
            "loading": False,
            "count": 2,
            "diagnostics": [{"code": "lexer_partial"}]
            if include_diagnostics
            else [],
        },
    )
    dock = SimpleNamespace(
        _visible=False,
        isVisible=lambda: dock._visible,
        setVisible=lambda value: setattr(dock, "_visible", bool(value)),
    )
    view = _ViewStub()
    view.workspace_problems = panel
    view.dock_problems = dock
    navigated: list[int] = []
    view._navigate_workspace_problem = lambda delta: (
        navigated.append(delta) or True
    )
    bridge = ConfiguratorControlBridge(view, _VmStub())

    state = bridge._dispatch(
        "workspace_problems_state",
        {"include_diagnostics": False},
    )
    refreshed = bridge._dispatch(
        "workspace_problems_refresh",
        {"show": True, "include_diagnostics": True},
    )
    previous = bridge._dispatch(
        "workspace_problem_navigate",
        {"direction": "previous", "include_diagnostics": False},
    )

    assert state == {
        "loading": False,
        "count": 2,
        "diagnostics": [],
        "visible": False,
    }
    assert refreshed["queued"] is True
    assert refreshed["visible"] is True
    assert refreshed["diagnostics"] == [{"code": "lexer_partial"}]
    assert previous["moved"] is True
    assert previous["direction"] == "previous"
    assert navigated == [-1]


def test_control_api_exposes_active_editor_diagnostic_markers() -> None:
    editor = SimpleNamespace(
        state=SimpleNamespace(
            asset_key="module://module-a",
            resolved_key="",
        ),
        _edit=SimpleNamespace(
            _workspace_diagnostics={
                12: [{"code": "unresolved_member"}],
                18: [{"code": "lexer_partial"}, {"code": "lexer_partial"}],
            },
            _debug_line=12,
        ),
    )
    view = _ViewStub()
    view._active_code_editor = lambda: editor
    bridge = ConfiguratorControlBridge(view, _VmStub())

    assert bridge._dispatch("code_editor_diagnostics_state", {}) == {
        "asset_key": "module://module-a",
        "lines": [12, 18],
        "diagnostic_count": 3,
        "debug_line": 12,
    }


def test_control_api_goes_to_definition_from_active_editor(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    edit = QPlainTextEdit()
    edit.setPlainText("CommonModule.Run()")
    navigated: list[bool] = []
    editor = SimpleNamespace(
        toPlainText=edit.toPlainText,
        setPlainText=edit.setPlainText,
        _edit=edit,
        _module_introspection=object(),
        _refresh_introspection=lambda: None,
        _go_to_definition=lambda: navigated.append(True),
    )
    active_widget = SimpleNamespace(
        state=SimpleNamespace(asset_key="module://target"),
        _edit=edit,
    )
    active_window = SimpleNamespace(
        widget=lambda: active_widget,
        windowTitle=lambda: "CommonModule",
    )
    view = _ViewStub()
    view._active_code_editor = lambda: editor  # type: ignore[attr-defined]
    view._open_windows = {"target": active_window}
    view.mdi = SimpleNamespace(activeSubWindow=lambda: active_window)
    bridge = ConfiguratorControlBridge(view, _VmStub())

    target = SimpleNamespace(
        as_dict=lambda: {
            "kind": "module",
            "guid": "target",
            "module_guid": "target",
            "line": 7,
            "title": "CommonModule",
        }
    )
    monkeypatch.setattr(
        "src.ui_qt.widgets.code_editor_widget.resolve_definition_target",
        lambda *_args, **_kwargs: target,
    )

    result = bridge._dispatch(
        "code_editor_go_to_definition",
        {"find": "CommonModule", "find_offset": 2},
    )

    assert navigated == [True]
    assert edit.textCursor().position() == 2
    assert result["target"]["module_guid"] == "target"
    assert result["active_asset_key"] == "module://target"
    assert result["active_line"] == 1
    assert result["open_windows"] == ["target"]


def test_control_api_finds_usages_through_runtime_service() -> None:
    vm = _VmStub(
        module_search_hits=[
            {
                "module_guid": "module-1",
                "owner_guid": "owner-1",
                "line": 8,
                "col": 4,
                "preview": "Helper.Run();",
            }
        ]
    )
    bridge = ConfiguratorControlBridge(_ViewStub(), vm)

    result = bridge._dispatch(
        "code_editor_find_usages",
        {"term": "Helper.Run", "whole_word": True, "limit": 25},
    )

    assert result["term"] == "Helper.Run"
    assert result["count"] == 1
    assert result["hits"][0]["line"] == 8
    assert vm.last_module_search == {
        "term": "Helper.Run",
        "match_case": False,
        "whole_word": True,
        "module_guid": "",
        "limit": 25,
    }


def test_control_api_uses_semantic_references_for_qualified_symbol() -> None:
    calls: list[tuple[str, int, bool]] = []
    service = SimpleNamespace(
        find_workspace_references=lambda term, *, limit, include_declaration: (
            calls.append((term, limit, include_declaration))
            or [
                {
                    "module_guid": "module-1",
                    "line": 4,
                    "col": 10,
                    "declaration": True,
                },
                {
                    "module_guid": "module-2",
                    "line": 8,
                    "col": 4,
                    "declaration": False,
                },
            ]
        )
    )
    bridge = ConfiguratorControlBridge(
        _ViewStub(),
        SimpleNamespace(_service=service),
    )

    result = bridge._dispatch(
        "code_editor_find_usages",
        {"term": "Helper.Run", "whole_word": True, "limit": 25},
    )

    assert result["semantic"] is True
    assert result["count"] == 2
    assert calls == [("Helper.Run", 25, True)]


def test_control_api_opens_non_modal_find_usages_ui() -> None:
    view = _ViewStub()
    bridge = ConfiguratorControlBridge(view, _VmStub())

    result = bridge._dispatch(
        "code_editor_show_usages",
        {"term": "Helper.Run", "whole_word": True, "limit": 25},
    )

    assert result == {
        "term": "Helper.Run",
        "opened": True,
        "window_count": 1,
    }
    assert view.usage_queries == [
        {
            "term": "Helper.Run",
            "match_case": False,
            "whole_word": True,
            "module_guid": "",
            "limit": 25,
        }
    ]
    assert bridge._dispatch("code_editor_usages_state", {}) == {
        "window_count": 1,
        "windows": [
            {
                "visible": False,
                "term": "",
                "status": "",
                "rows": [],
            }
        ],
    }


def test_control_api_previews_semantic_rename_without_active_editor() -> None:
    source = (
        "Procedure Run(Value)\n"
        "    Value = Value + 1;\n"
        '    Message("Value");\n'
        "EndProcedure\n"
    )
    bridge = ConfiguratorControlBridge(_ViewStub(), _VmStub())

    result = bridge._dispatch(
        "code_editor_rename_preview",
        {
            "source": source,
            "find": "Value",
            "new_name": "Amount",
        },
    )

    assert result["applied"] is False
    assert result["old_name"] == "Value"
    assert result["new_name"] == "Amount"
    assert result["symbol_kind"] == "parameter"
    assert result["count"] == 3
    assert 'Message("Value")' in result["updated_source"]
    assert result["updated_source"].count("Amount") == 3


def test_control_api_applies_semantic_rename_to_active_buffer_only() -> None:
    QApplication.instance() or QApplication([])
    source = (
        "Procedure Run(Value)\n"
        "    Value = Value + 1;\n"
        "EndProcedure\n"
    )
    edit = QPlainTextEdit()
    edit.setPlainText(source)
    refreshed: list[bool] = []
    editor = SimpleNamespace(
        _edit=edit,
        _refresh_module_introspection=lambda: refreshed.append(True),
    )
    view = _ViewStub()
    view._active_code_editor = lambda: editor  # type: ignore[attr-defined]
    bridge = ConfiguratorControlBridge(view, _VmStub())

    result = bridge._dispatch(
        "code_editor_rename_apply",
        {
            "find": "Value",
            "new_name": "Amount",
        },
    )

    assert result["applied"] is True
    assert edit.toPlainText() == result["updated_source"]
    assert refreshed == [True]
    edit.undo()
    assert edit.toPlainText() == source


def test_control_api_previews_workspace_rename_through_runtime_service() -> None:
    QApplication.instance() or QApplication([])
    source = "Function LoadSettings() Export\nEndFunction\n"
    edit = QPlainTextEdit()
    edit.setPlainText(source)
    editor = SimpleNamespace(
        _edit=edit,
        state=SimpleNamespace(
            asset_key="module://module-1",
            resolved_key="module://module-1",
        ),
    )
    view = _ViewStub()
    view._active_code_editor = lambda: editor  # type: ignore[attr-defined]
    vm = _VmStub(
        workspace_rename_plan={
            "module_count": 2,
            "occurrence_count": 3,
        }
    )
    bridge = ConfiguratorControlBridge(view, vm)

    result = bridge._dispatch(
        "code_editor_rename_workspace_preview",
        {
            "find": "LoadSettings",
            "new_name": "ReadSettings",
            "module_name": "SettingsServer",
        },
    )

    assert result == {"module_count": 2, "occurrence_count": 3}
    assert vm.last_workspace_rename == {
        "module_guid": "module-1",
        "new_name": "ReadSettings",
        "symbol_name": "LoadSettings",
        "module_name": "SettingsServer",
    }


def test_control_api_applies_workspace_preview_and_reloads_open_editor() -> None:
    QApplication.instance() or QApplication([])
    reloaded: list[bool] = []
    editor = SimpleNamespace(
        state=SimpleNamespace(
            asset_key="module://module-1",
            resolved_key="module://module-1",
        ),
        is_dirty=lambda: False,
        reload=lambda: reloaded.append(True),
    )
    view = _ViewStub()
    view._active_code_editor = lambda: editor  # type: ignore[attr-defined]
    view.debug_editors = [editor]
    vm = _VmStub(
        workspace_rename_result={
            "applied": True,
            "updated": 1,
            "occurrence_count": 2,
        }
    )
    bridge = ConfiguratorControlBridge(view, vm)
    modules = [
        {
            "module_guid": "module-1",
            "source_hash": "source-hash",
            "updated_hash": "updated-hash",
        }
    ]

    result = bridge._dispatch(
        "code_editor_rename_workspace_apply",
        {
            "new_name": "ReadSettings",
            "symbol_name": "LoadSettings",
            "module_name": "SettingsServer",
            "modules": modules,
        },
    )

    assert result == {
        "applied": True,
        "updated": 1,
        "occurrence_count": 2,
    }
    assert vm.last_workspace_rename_apply == {
        "module_guid": "module-1",
        "new_name": "ReadSettings",
        "symbol_name": "LoadSettings",
        "module_name": "SettingsServer",
        "modules": modules,
        "updated_by": "control_api",
    }
    assert reloaded == [True]


def test_control_api_serializes_form_editor_trees() -> None:
    QApplication.instance() or QApplication([])
    tree = QTreeWidget()
    tree.setColumnCount(3)
    root = QTreeWidgetItem(["Об'єкт", "", "(ДокументОб'єкт.Тест)"])
    root.setData(0, Qt.ItemDataRole.UserRole, {"kind": "object_root"})
    child = QTreeWidgetItem(["Номер", "", "Рядок"])
    child.setData(0, Qt.ItemDataRole.UserRole, {"code": "Number", "system": True})
    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
    child.setCheckState(1, Qt.CheckState.Checked)
    root.addChild(child)
    tree.addTopLevelItem(root)
    root.setExpanded(True)

    state = ConfiguratorControlBridge._tree_state(tree)

    assert state[0]["texts"] == ["Об'єкт", "", "(ДокументОб'єкт.Тест)"]
    assert state[0]["expanded"] is True
    assert state[0]["children"][0]["data"] == {"code": "Number", "system": True}
    assert state[0]["children"][0]["checked"] == int(Qt.CheckState.Checked.value)


def test_control_api_maximizes_active_mdi_window() -> None:
    class _SubWindow:
        maximized = False

        def showMaximized(self) -> None:
            self.maximized = True

    view = _ViewStub()
    subwindow = _SubWindow()
    view.mdi = SimpleNamespace(activeSubWindow=lambda: subwindow)
    bridge = ConfiguratorControlBridge(view, _VmStub())

    result = bridge._dispatch("maximize_active_window", {})

    assert subwindow.maximized is True
    assert result["window_title"] == "MetaPlatform"


def test_control_api_targets_form_editor_and_mdi_window_by_guid() -> None:
    class _Tabs:
        def currentIndex(self) -> int:
            return 0

        def tabText(self, _index: int) -> str:
            return "Форма"

        def count(self) -> int:
            return 1

    class _SubWindow:
        def __init__(self, widget) -> None:
            self._widget = widget
            self.maximized = False

        def widget(self):
            return self._widget

        def showMaximized(self) -> None:
            self.maximized = True

    editor = SimpleNamespace(
        _form_guid="target-form",
        _form_title="Цільова форма",
        _center_tabs=_Tabs(),
        _left_tabs=_Tabs(),
        _object_tabs=_Tabs(),
        _module_editor=SimpleNamespace(toPlainText=lambda: ""),
    )
    subwindow = _SubWindow(editor)
    activated: list[object] = []
    view = _ViewStub()
    view._open_windows["target-form"] = subwindow
    view.mdi = SimpleNamespace(
        activeSubWindow=lambda: None,
        setActiveSubWindow=lambda window: activated.append(window),
    )
    bridge = ConfiguratorControlBridge(view, _VmStub())

    state = bridge._dispatch("form_editor_state", {"guid": "target-form"})
    bridge._dispatch("maximize_active_window", {"guid": "target-form"})

    assert state["form_guid"] == "target-form"
    assert state["form_title"] == "Цільова форма"
    assert subwindow.maximized is True
    assert activated == [subwindow]


def test_control_api_launches_restarts_and_stops_debug_client() -> None:
    view = _ViewStub()
    bridge = ConfiguratorControlBridge(view, _VmStub())

    launched = bridge._dispatch("launch_debug_client", {})
    unchanged = bridge._dispatch("launch_debug_client", {})
    restarted = bridge._dispatch("launch_debug_client", {"restart": True})
    stopped = bridge._dispatch("stop_debug_client", {"force": True})

    assert launched == {"running": True, "pid": 4242, "paused": False}
    assert unchanged == launched
    assert restarted == launched
    assert stopped == {"running": False, "pid": 0, "paused": False}
    assert view.debug_launches == 2
    assert view.debug_stops == 2


def test_control_api_sets_breakpoint_without_losing_existing_points(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("META_DEBUG_DIR", str(tmp_path))
    bridge = ConfiguratorControlBridge(_ViewStub(), _VmStub())

    bridge._dispatch("breakpoint_set", {"module_id": "module://existing", "line": 7})
    result = bridge._dispatch(
        "breakpoint_set",
        {
            "module_guid": "target-guid",
            "line": 19,
            "condition": "ИмяФормы = \"\"",
            "description": "cross-module startup",
        },
    )

    assert set(result["modules"]) == {"module://existing", "module://target-guid"}
    target = result["modules"]["module://target-guid"][0]
    assert target["line"] == 19
    assert target["condition"] == 'ИмяФормы = ""'
    assert target["description"] == "cross-module startup"


def test_control_api_sends_command_to_paused_editor() -> None:
    commands: list[str] = []
    view = _ViewStub()
    view.paused_editor = SimpleNamespace(_request_debug_command=commands.append)
    bridge = ConfiguratorControlBridge(view, _VmStub())

    result = bridge._dispatch("debug_command", {"command": "step_into"})

    assert result == {"accepted": True, "command": "step_into"}
    assert commands == ["step_into"]


def test_control_api_releases_active_pause_without_loaded_editor() -> None:
    view = _ViewStub()
    bridge = ConfiguratorControlBridge(view, _VmStub())
    command_state = {"value": ""}
    loop = QEventLoop()
    bridge._active_debug_pause = {"command": command_state, "loop": loop}

    result = bridge._dispatch("debug_command", {"command": "continue"})

    assert result == {"accepted": True, "command": "continue"}
    assert command_state["value"] == "continue"


def test_control_api_close_delegates_to_window() -> None:
    view = _ViewStub()
    calls: list[str] = []
    view.close = lambda: calls.append("close") or True  # type: ignore[attr-defined]
    bridge = ConfiguratorControlBridge(view, _VmStub())

    result = bridge._dispatch("close", {})

    assert result == {"accepted": True}
    assert calls == ["close"]
