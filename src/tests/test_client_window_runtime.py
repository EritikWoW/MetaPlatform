from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTabWidget, QTableWidget, QTreeWidget, QWidget
import threading
from types import SimpleNamespace

from src.client.client_window_ui import ClientWindowUiMixin
from src.client.client_window_runtime import ClientWindowRuntimeMixin, _MetadataProxy
from src.client.forms.structure_inspector import StructureInspectorWidget
from src.client.forms.form_runtime_window import FormRuntimeWindow
from src.configurator.persistence.manifest_io import _sys_guid
from src.runtime.gateway import GatewayDb
from src.runtime.script.debugger import DebugSession


def test_posting_requires_saved_form_and_never_autosaves(monkeypatch):
    import src.client.client_window_runtime as runtime
    warnings, calls = [], []
    monkeypatch.setattr(runtime.QMessageBox, 'warning', lambda *args: warnings.append(args))
    widget = SimpleNamespace(collect=lambda: {'_guid': 'rec'}, set_record=lambda rec: None)
    window = SimpleNamespace(is_dirty=True)
    host = ClientWindowRuntimeMixin.__new__(ClientWindowRuntimeMixin)
    host._db = SimpleNamespace(document_post=lambda **kw: calls.append(kw) or SimpleNamespace(ok=True))
    host._form_windows = {'view': window}
    host._runtime_form_widget = lambda view: widget
    host._form_save = lambda *args: (_ for _ in ()).throw(AssertionError('Must not autosave'))
    host.statusBar = lambda: SimpleNamespace(showMessage=lambda *args: None)
    ctx = SimpleNamespace(rec_guid='rec', obj_name='Invoice')
    assert not host._form_post(ctx, 'view', post=True)
    assert warnings and not calls
    window.is_dirty = False
    assert host._form_post(ctx, 'view', post=True)
    assert calls == [{'doc_name': 'Invoice', 'doc_guid': 'rec', 'post': True}]


def test_failed_posting_returns_false_without_changing_ui_flag(monkeypatch):
    import src.client.client_window_runtime as runtime
    updates = []
    monkeypatch.setattr(runtime.QMessageBox, 'warning', lambda *args: None)
    host = ClientWindowRuntimeMixin.__new__(ClientWindowRuntimeMixin)
    host._db = SimpleNamespace(document_post=lambda **kw: SimpleNamespace(ok=False, messages=['cancelled']))
    host._form_windows = {}
    host._runtime_form_widget = lambda view: SimpleNamespace(set_record=updates.append, collect=lambda: {})
    assert not host._form_post(SimpleNamespace(rec_guid='rec', obj_name='Invoice'), 'view', post=True)
    assert not updates


def test_direct_save_and_close_keeps_form_open_when_save_fails(monkeypatch):
    import src.client.client_window_runtime as runtime
    monkeypatch.setattr(runtime.QMessageBox, 'warning', lambda *args: None)
    host = ClientWindowRuntimeMixin.__new__(ClientWindowRuntimeMixin)
    closed = []
    host._close_presented_form = closed.append
    host._db = SimpleNamespace(table=lambda name: SimpleNamespace(update=lambda *args: 0))
    form = SimpleNamespace(collect=lambda: {'_guid': 'rec', '_number': '1'})
    assert host._dispatch_runtime_command('saveandclose', form_guid='form', form_widget=form, doc_name='Invoice') is False
    assert closed == []


def _form_model(**props) -> dict:
    return {
        "schema_version": 1,
        "id": "form-1",
        "title": "Form",
        "root": {
            "id": "root",
            "type": "Container",
            "props": {"layout": "vertical", **props},
            "children": [],
        },
    }


def test_form_open_mode_resolves_explicit_and_automatic_placement() -> None:
    resolve = ClientWindowRuntimeMixin._resolve_form_open_mode

    assert resolve(_form_model(), "document") == "workspace"
    assert resolve(_form_model(), "data_processor") == "window"
    assert resolve(_form_model(), "common_form") == "window"
    assert resolve(_form_model(open_mode="workspace"), "data_processor") == "workspace"
    assert resolve(_form_model(open_mode="window"), "document") == "window"
    assert resolve(_form_model(window_lock_mode="LockOwnerWindow"), "document") == "window"


def test_new_object_mode_uses_object_form_without_record_guid() -> None:
    resolve = ClientWindowRuntimeMixin._form_kind_for_open_mode

    assert resolve("list") == "list_form"
    assert resolve("object") == "object_form"
    assert resolve("object:") == "object_form"
    assert resolve("object:record-guid") == "object_form"
    assert resolve("list", "data_processor") == "object_form"
    assert resolve("list", "common_form") == "object_form"


def test_object_form_selection_prefers_document_form_over_first_object_form() -> None:
    host = ClientWindowRuntimeMixin.__new__(ClientWindowRuntimeMixin)
    host._db = None

    def form(name: str) -> dict:
        model = _form_model()
        model["title"] = name
        return {
            "name": name,
            "payload": {
                "subtype": "object_form",
                "form_model": model,
            },
        }

    selected = host._find_form_model_for_owner_guid(
        "owner-guid",
        "object_form",
        context={"forms": [form("VoprosOSmeneStatusa"), form("FormaDokumenta")]},
    )

    assert selected is not None
    assert selected["title"] == "FormaDokumenta"


def test_fieldless_processor_form_is_not_replaced_by_autogeneration() -> None:
    empty_form = _form_model()

    assert ClientWindowRuntimeMixin._should_auto_generate_form(
        empty_form, "object_form", "data_processor"
    ) is False
    assert ClientWindowRuntimeMixin._should_auto_generate_form(
        empty_form, "object_form", "document"
    ) is True
    assert ClientWindowRuntimeMixin._should_auto_generate_form(
        None, "object_form", "data_processor"
    ) is True


def test_form_runtime_window_is_resizable_and_applies_modality() -> None:
    app = QApplication.instance() or QApplication([])
    content = QWidget()
    form_widget = QWidget()
    content._form_widget = form_widget  # type: ignore[attr-defined]
    window = FormRuntimeWindow(
        view_id="form:1",
        title="Processor",
        content_widget=content,
        model=_form_model(w=640, h=480),
        lock_mode="owner",
    )

    assert window.form_widget is form_widget
    assert window.windowModality() == Qt.WindowModality.WindowModal
    assert bool(window.windowFlags() & Qt.WindowType.WindowMinMaxButtonsHint)
    assert window.size().width() == 640
    assert window.size().height() == 480
    window.set_dirty()
    assert window.is_dirty is True
    assert window.windowTitle() == "* Processor"
    window.clear_dirty()
    assert window.is_dirty is False
    assert window.windowTitle() == "Processor"
    window.close()
    app.processEvents()


class _FormPresentationStub(ClientWindowRuntimeMixin, QWidget):
    def __init__(self) -> None:
        QWidget.__init__(self)
        self._views: dict[str, QWidget] = {}
        self._titles: dict[str, str] = {}
        self._form_windows: dict[str, FormRuntimeWindow] = {}
        self._tab_widget = QTabWidget(self)

    def _register_view(self, view_id: str, widget: QWidget) -> None:
        self._views[view_id] = widget
        self._tab_widget.addTab(widget, self._titles.get(view_id, view_id))

    def _select_view(self, view_id: str) -> None:
        widget = self._views.get(view_id)
        if widget is not None:
            self._tab_widget.setCurrentWidget(widget)


def test_present_form_routes_workspace_and_separate_window() -> None:
    app = QApplication.instance() or QApplication([])
    host = _FormPresentationStub()

    workspace_widget = QWidget()
    host._present_form(
        view_id="form:workspace",
        widget=workspace_widget,
        title="Workspace form",
        model=_form_model(open_mode="workspace"),
        owner_type="data_processor",
    )
    assert host._views["form:workspace"] is workspace_widget
    assert "form:workspace" not in host._form_windows
    assert host._tab_widget.currentWidget() is workspace_widget

    window_widget = QWidget()
    host._present_form(
        view_id="form:window",
        widget=window_widget,
        title="Processor form",
        model=_form_model(),
        owner_type="data_processor",
    )
    app.processEvents()
    assert "form:window" not in host._views
    assert host._form_windows["form:window"].content_widget is window_widget
    assert host._form_windows["form:window"].isVisible()

    host._close_presented_form("form:window")
    app.processEvents()
    host.close()


def test_metadata_proxy_loads_each_collection_lazily() -> None:
    calls: list[str] = []

    def resolve(type_name: str) -> list[dict]:
        calls.append(type_name)
        return [
            {
                "guid": "attr-1",
                "type": "common_attribute",
                "name": "DataArea",
                "title": "ОбластьДанных",
            }
        ]

    metadata = _MetadataProxy(
        [],
        {"name": "Configuration", "payload": {"version": "3.1.0"}},
        resolver=resolve,
    )

    first = metadata.ОбщиеРеквизиты
    second = metadata.CommonAttributes

    assert first is second
    assert first.Найти("ОбластьДанных")["guid"] == "attr-1"
    assert calls == ["common_attribute"]
    assert metadata.Версия == "3.1.0"
    assert (
        metadata.СвойстваОбъектов.РазделениеДанныхОбщегоРеквизита.Разделять
        == "Разделять"
    )


def test_metadata_roles_collection_is_available_lazily() -> None:
    metadata = _MetadataProxy(
        [],
        resolver=lambda type_name: [
            {"guid": "role-1", "type": "role", "name": "FullAccess", "title": "ПолныеПрава"}
        ] if type_name == "role" else [],
    )

    assert metadata.Роли.ПолныеПрава["guid"] == "role-1"


def test_metadata_proxy_builds_subsystem_hierarchy_from_parent_guids() -> None:
    rows = [
        {
            "guid": "root-sub",
            "type": "subsystem",
            "name": "Administration",
            "title": "Администрирование",
            "parent_guid": "configuration",
            "payload": {"include_in_command_interface": True},
        },
        {
            "guid": "child-sub",
            "type": "subsystem",
            "name": "Integration",
            "title": "НастройкаИнтеграции",
            "parent_guid": "root-sub",
            "payload": {},
        },
    ]
    metadata = _MetadataProxy([], resolver=lambda type_name: rows if type_name == "subsystem" else [])

    root = metadata.Подсистемы.Найти("Администрирование")
    child = root.Подсистемы.Найти("НастройкаИнтеграции")

    assert metadata.Подсистемы.Кількість() == 1
    assert root.ВключатьВКомандныйИнтерфейс is True
    assert child.Имя == "НастройкаИнтеграции"
    assert child.Подсистемы.Кількість() == 0


class _FakeGw:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def manifest_get_payload(self, guid: str) -> dict:
        self.requests.append(str(guid))
        return {
            "form_model": {
                "schema_version": 1,
                "id": "form-1",
                "root": {"type": "Container", "props": {"layout": "vertical"}, "children": []},
            },
            "layout_model": {
                "kind": "spreadsheet_document",
                "cells": [{"row": 0, "col": 0, "text": "Layout cell"}],
            },
            "module": {"asset_key": "module-src/form-guid.bsl", "lang": "uk"},
        }


class _FakeDb:
    def __init__(self) -> None:
        self._gw = _FakeGw()
        self.assets = {
            "module-src/form-guid.bsl": (b"Procedure Test()\nEndProcedure", "text/plain"),
        }

    def get_asset(self, key: str):
        return self.assets[key]


class _RuntimeStub(ClientWindowRuntimeMixin):
    def __init__(self, row: dict) -> None:
        self._db = _FakeDb()
        self._manifest_rows_cache = [dict(row)]
        self._manifest_by_guid_cache = {str(row.get("guid") or ""): dict(row)}
        self._manifest_refresh_fingerprint = ""
        self._views = {}
        self._titles = {}

    def _manifest_row_by_guid(self, guid: str):
        row = self._manifest_by_guid_cache.get(str(guid).strip())
        return dict(row) if isinstance(row, dict) else None


class _NavRuntimeStub(ClientWindowRuntimeMixin, ClientWindowUiMixin):
    def __init__(self, rows: list[dict]) -> None:
        self._db = _FakeDb()
        self._manifest_rows_cache = [dict(row) for row in rows]
        self._manifest_by_guid_cache = {
            str(row.get("guid") or ""): dict(row) for row in rows if str(row.get("guid") or "")
        }
        self._manifest_refresh_fingerprint = ""
        self._views = {}
        self._titles = {}
        self._icon_provider = None
        self._nav = QTreeWidget()

    def _manifest_row_by_guid(self, guid: str):
        row = self._manifest_by_guid_cache.get(str(guid).strip())
        return dict(row) if isinstance(row, dict) else None


class _RefreshRuntimeStub(ClientWindowRuntimeMixin):
    def __init__(self) -> None:
        self._db = _FakeDb()
        self._manifest_rows_cache = []
        self._manifest_by_guid_cache = {}
        self._views = {}
        self._titles = {}
        self._manifest_rows_lock = threading.Lock()
        self._manifest_rows_lock.acquire()
        self.populate_calls = 0

    def _populate_nav_tree(self) -> None:
        self.populate_calls += 1

    def _manifest_refresh_key(self) -> str:
        raise AssertionError("refresh should not query manifest state while loading")


class _FingerprintRuntimeStub(ClientWindowRuntimeMixin):
    def __init__(self, info: dict) -> None:
        self._db = _FakeDb()
        self._info = info

    def _manifest_refresh_key(self) -> str:
        return ClientWindowRuntimeMixin._manifest_refresh_key(self)

    def _db_info(self) -> dict:
        return dict(self._info)


class _StartupRuntimeStub(ClientWindowRuntimeMixin):
    def __init__(self) -> None:
        self._db = object()
        self._manifest_refresh_fingerprint = "fp-1"
        self._startup_modules_fingerprints: dict[str, str] = {}
        self._calls: list[str] = []
        self._config_row = {
            "guid": "cfg-1",
            "type": "configuration",
            "kind": "object",
            "name": "Configuration",
            "title": "Configuration",
            "payload": {
                "startup_modules": ["module://mod-1"],
            },
        }
        self._module_row = {
            "guid": "mod-1",
            "type": "common_module",
            "kind": "object",
            "name": "AppModule",
            "title": "AppModule",
            "payload": {},
        }
        self._manifest_rows_cache: list[dict] = [dict(self._module_row)]
        self._manifest_by_guid_cache: dict[str, dict] = {"mod-1": dict(self._module_row)}

    def _manifest_rows(self) -> list[dict]:
        self._calls.append("manifest_rows")
        raise AssertionError("startup must not load the complete manifest")

    def _configuration_manifest_row(self) -> dict | None:
        return dict(self._config_row)

    def _module_text_for_owner(self, owner_guid: str, module_name: str = "", *, module_kind: str = "") -> tuple[str, str, str]:
        if str(owner_guid).strip() != "mod-1":
            return "", "uk", ""
        return (
            "Змін Cancel;\n"
            "Процедура ПередНачаломРаботыСистемы()\n"
            "    Cancel = Істина\n"
            "КінецьПроцедури",
            "uk",
            "mod-1",
        )

    def _manifest_refresh_key(self) -> str:
        return self._manifest_refresh_fingerprint


class _DirectModuleTable:
    def select(self, where=None, order_by=None):
        if where == {"module_guid": "module-direct-1"}:
            return [
                {
                    "module_guid": "module-direct-1",
                    "owner_guid": "owner-1",
                    "owner_kind": "common_module",
                    "module_kind": "ManagedApplicationModule",
                    "name": "AppModule",
                    "lang": "uk",
                    "text": (
                        "Процедура ПередНачаломРаботыСистемы()\n"
                        "    ВнешнийСервис.Проверить()\n"
                        "    Cancel = Істина\n"
                        "КінецьПроцедури"
                    ),
                    "storage_kind": "inline",
                    "content_ref": "",
                }
            ]
        return []


class _DirectModuleDb:
    def table(self, name: str):
        return _DirectModuleTable()


class _DirectModuleStartupStub(ClientWindowRuntimeMixin):
    def __init__(self) -> None:
        self._db = _DirectModuleDb()
        self._manifest_refresh_fingerprint = "fp-direct"
        self._startup_modules_fingerprints: dict[str, str] = {}
        self._calls: list[str] = []
        self._config_row = {
            "guid": "cfg-1",
            "type": "configuration",
            "kind": "object",
            "name": "Configuration",
            "title": "Configuration",
            "payload": {
                "startup_modules": ["module://module-direct-1"],
            },
        }
        self._owner_row = {
            "guid": "owner-1",
            "type": "common_module",
            "kind": "object",
            "name": "AppModule",
            "title": "AppModule",
            "payload": {},
        }
        self._manifest_rows_cache: list[dict] = [dict(self._owner_row)]
        self._manifest_by_guid_cache: dict[str, dict] = {"owner-1": dict(self._owner_row)}

    def _manifest_rows(self) -> list[dict]:
        self._calls.append("manifest_rows")
        raise AssertionError("startup must not load the complete manifest")

    def _configuration_manifest_row(self) -> dict | None:
        return dict(self._config_row)

    def _manifest_refresh_key(self) -> str:
        return self._manifest_refresh_fingerprint


class _PersistentStartupStub(_StartupRuntimeStub):
    def __init__(self) -> None:
        super().__init__()
        self._manifest_refresh_fingerprint = "fp-persistent"

    def _module_text_for_owner(self, owner_guid: str, module_name: str = "", *, module_kind: str = "") -> tuple[str, str, str]:
        if str(owner_guid).strip() != "mod-1":
            return "", "uk", ""
        return (
            "Змін глФормаНачальнойНастройкиПрограммы, Cancel Експорт;\n"
            "Процедура ПередНачаломРаботыСистемы()\n"
            "    глФормаНачальнойНастройкиПрограммы = 42\n"
            "КінецьПроцедури\n"
            "Процедура ПриНачалеРаботыСистемы()\n"
            "    Якщо глФормаНачальнойНастройкиПрограммы <> 42 Тоді\n"
            "        Cancel = Істина\n"
            "    КінецьЯкщо\n"
            "КінецьПроцедури",
            "uk",
            "mod-1",
        )


class _ParameterizedCancelStartupStub(_StartupRuntimeStub):
    def _module_text_for_owner(self, owner_guid: str, module_name: str = "", *, module_kind: str = "") -> tuple[str, str, str]:
        return (
            "Процедура ПередНачаломРаботыСистемы(Отказ)\n"
            "    Отказ = Істина\n"
            "КінецьПроцедури",
            "uk",
            "mod-1",
        )


class _StartupGateway:
    def __init__(self) -> None:
        self.root_guid = _sys_guid("root:configuration")
        self.row_requests: list[str] = []
        self.payload_requests: list[str] = []
        self.table_requests: list[tuple[str, dict | None]] = []
        self.asset_requests: list[str] = []
        self.manifest_list_calls = 0
        self.sources = {
            "managed-guid": (
                "Змін SharedStartupValue, PostManagedValue;\n"
                "InitCount = 1\n"
                "Процедура ПередНачаломРаботыСистемы()\n"
                "    SharedStartupValue = 41\n"
                "КінецьПроцедури\n"
                "Процедура ПриНачалеРаботыСистемы()\n"
                "    PostManagedValue = SharedStartupValue + InitCount\n"
                "КінецьПроцедури"
            ),
            "session-guid": (
                "Змін SessionSawManaged, SessionPostValue;\n"
                "Процедура ПередНачаломРаботыСистемы()\n"
                "    SessionSawManaged = SharedStartupValue\n"
                "КінецьПроцедури\n"
                "Процедура ПриНачалеРаботыСистемы()\n"
                "    SessionPostValue = PostManagedValue + 1\n"
                "КінецьПроцедури"
            ),
            "ordinary-guid": (
                "Змін OrdinarySawSession, OrdinaryPostValue;\n"
                "Процедура ПередНачаломРаботыСистемы()\n"
                "    OrdinarySawSession = SessionSawManaged\n"
                "КінецьПроцедури\n"
                "Процедура ПриНачалеРаботыСистемы()\n"
                "    OrdinaryPostValue = SessionPostValue + 1\n"
                "КінецьПроцедури"
            ),
        }

    def manifest_get_row(self, guid: str) -> dict:
        self.row_requests.append(str(guid))
        if str(guid) == self.root_guid:
            return {
                "guid": self.root_guid,
                "type": "configuration",
                "kind": "object",
                "name": "Configuration",
                "title": "Configuration",
                "payload": {"imported": {"origin": "Configuration.xml"}},
            }
        return {}

    def manifest_get_payload(self, guid: str) -> dict:
        self.payload_requests.append(str(guid))
        assert str(guid) == self.root_guid
        return {
            "managed_application_module": "module://managed-guid",
            "session_module": "module://session-guid",
            "ordinary_application_module": "module://ordinary-guid",
            # Duplicates from the compatibility aggregate must not run twice.
            "startup_modules": [
                "module://managed-guid",
                "module://session-guid",
                "module://ordinary-guid",
            ],
        }

    def manifest_list(self, *, slim: bool = True) -> list[dict]:
        self.manifest_list_calls += 1
        raise AssertionError("startup must not request manifest.list")

    def table_select(self, table: str, where: dict | None, order_by: str | None = None) -> list[dict]:
        self.table_requests.append((str(table), dict(where or {})))
        if str(table) != "cfg_modules":
            return []
        module_guid = str((where or {}).get("module_guid") or "")
        if module_guid not in self.sources:
            return []
        row = {
            "module_guid": module_guid,
            "owner_guid": "configuration-owner",
            "owner_kind": "configuration",
            "module_kind": "BuiltInModule",
            "name": module_guid,
            "lang": "uk",
            "storage_kind": "inline",
            "content_ref": "",
            "text": self.sources[module_guid],
        }
        if module_guid == "managed-guid":
            row.update({
                "storage_kind": "asset",
                "content_ref": "module-src/managed-guid.bsl",
                "text": "",
            })
        return [row]

    def asset_get(self, key: str) -> tuple[bytes, str]:
        self.asset_requests.append(str(key))
        assert str(key) == "module-src/managed-guid.bsl"
        return self.sources["managed-guid"].encode("utf-8"), "text/plain"


class _GatewayStartupStub(ClientWindowRuntimeMixin):
    def __init__(self, gateway: _StartupGateway, debugger: DebugSession) -> None:
        self._db = GatewayDb(gateway)
        self._manifest_rows_cache: list[dict] = []
        self._manifest_by_guid_cache: dict[str, dict] = {}
        self._manifest_nav_rows_cache: list[dict] = []
        self._manifest_refresh_fingerprint = "gateway-startup"
        self._startup_modules_fingerprints: dict[str, str] = {}
        self._debugger = debugger

    def _manifest_refresh_key(self) -> str:
        return self._manifest_refresh_fingerprint

    def _startup_debug_session(self):
        return self._debugger


class _CommonModuleStartupStub(_StartupRuntimeStub):
    def __init__(self, debugger: DebugSession) -> None:
        super().__init__()
        self._debugger = debugger
        self.resolve_calls: list[str] = []

    def _startup_debug_session(self):
        return self._debugger

    def _module_text_for_owner(self, owner_guid: str, module_name: str = "", *, module_kind: str = "") -> tuple[str, str, str]:
        return (
            "Змін CommonResult\n"
            "Процедура ПередНачаломРаботыСистемы()\n"
            "    CommonResult = StartupHelper.ReturnValue()\n"
            "КінецьПроцедури",
            "uk",
            "mod-1",
        )

    def _resolve_startup_common_module(self, name: str) -> dict[str, object] | None:
        self.resolve_calls.append(str(name))
        if str(name) != "StartupHelper":
            return None
        return {
            "module_guid": "helper-module-guid",
            "owner_guid": "helper-owner-guid",
            "owner_title": "StartupHelper",
            "lang": "uk",
            "text": (
                "Функція ReturnValue() Експорт\n"
                "    Повернути 42\n"
                "КінецьФункції"
            ),
        }


def test_client_window_runtime_hydrates_form_layout_and_module_payload() -> None:
    row = {
        "guid": "form-guid",
        "type": "form",
        "name": "Form",
        "title": "Form",
        "payload": {
        "form_model_ref": "manifest-payload/form-guid/form_model.json",
        "layout_model_ref": "manifest-payload/form-guid/layout_model.json",
        "module_asset_key": "module-src/form-guid.bsl",
    },
}
    stub = _RuntimeStub(row)

    payload = stub._manifest_payload_for_row(stub._manifest_row_by_guid("form-guid"))
    bundle = stub._form_structure_payload("form-guid")

    assert payload["form_model"]["root"]["props"]["layout"] == "vertical"
    assert payload["layout_model"]["kind"] == "spreadsheet_document"
    assert bundle["module_text"].startswith("Procedure Test()")
    assert bundle["module_lang"] == "uk"
    assert stub._db._gw.requests == ["form-guid"]


def test_client_window_runtime_builds_structure_inspector_tab() -> None:
    app = QApplication.instance() or QApplication([])
    row = {
        "guid": "form-guid",
        "type": "form",
        "name": "Form",
        "title": "Form",
        "payload": {
            "form_model_ref": "manifest-payload/form-guid/form_model.json",
            "layout_model_ref": "manifest-payload/form-guid/layout_model.json",
            "module_asset_key": "module-src/form-guid.bsl",
        },
    }
    stub = _RuntimeStub(row)

    host = stub._build_runtime_form_view(
        title="Form",
        guid="form-guid",
        model={
            "schema_version": 1,
            "id": "form-1",
            "root": {"id": "root", "type": "Container", "props": {"layout": "vertical"}, "children": []},
        },
    )

    tabs = host.findChild(QTabWidget, "ClientFormTabs")
    assert tabs is not None
    assert tabs.count() == 2
    inspector = tabs.widget(1)
    assert isinstance(inspector, StructureInspectorWidget)
    module_text = inspector.findChild(QPlainTextEdit, "StructureInspectorModuleText")
    assert module_text is not None
    assert module_text.toPlainText().startswith("Procedure Test()")
    assert inspector.findChild(type(inspector._tree), "StructureInspectorTree") is not None
    refs = inspector.findChild(type(inspector._refs), "StructureInspectorRefs")
    assert refs is not None
    assert "form_model_ref:" in refs.text()
    assert "layout_model_ref:" in refs.text()
    assert app is not None


def test_structure_inspector_separates_form_and_layout_models() -> None:
    app = QApplication.instance() or QApplication([])
    inspector = StructureInspectorWidget(
        title="Form",
        guid="form-guid",
        payload={
            "form_model_ref": "manifest-payload/form-guid/form_model.json",
            "layout_model_ref": "manifest-payload/form-guid/layout_model.json",
            "module_asset_key": "module-src/form-guid.bsl",
            "form_model": {
                "schema_version": 1,
                "id": "form-1",
                "root": {"id": "root", "type": "Container", "props": {"layout": "vertical"}, "children": []},
            },
            "layout_model": {
                "kind": "spreadsheet_document",
                "cells": [{"row": 0, "col": 0, "text": "Layout cell"}],
            },
            "module_text": "Procedure Test()\nEndProcedure",
        },
    )

    tree = inspector.findChild(type(inspector._tree), "StructureInspectorTree")
    refs = inspector.findChild(type(inspector._refs), "StructureInspectorRefs")
    module_text = inspector.findChild(QPlainTextEdit, "StructureInspectorModuleText")
    layout_cells = inspector.findChild(QTableWidget, "StructureInspectorLayoutCells")
    search = inspector.findChild(QLineEdit, "StructureInspectorSearch")
    diff_text = inspector.findChild(QPlainTextEdit, "StructureInspectorDiffText")

    assert tree is not None
    assert tree.topLevelItemCount() >= 2
    assert tree.topLevelItem(0).text(0) == "form_model"
    assert tree.topLevelItem(1).text(0) == "layout_model"
    assert refs is not None and "module_asset_key:" in refs.text()
    assert module_text is not None and module_text.toPlainText().startswith("Procedure Test()")
    assert layout_cells is not None and layout_cells.rowCount() == 1
    assert layout_cells.item(0, 2).text() == "Layout cell"
    assert search is not None
    search.setText("form_model")
    app.processEvents()
    assert tree.topLevelItem(0).isHidden() is False
    assert tree.topLevelItem(1).isHidden() is True
    assert diff_text is not None
    assert "Only in form_model:" in diff_text.toPlainText()
    assert "Only in layout_model:" in diff_text.toPlainText()
    assert app is not None


def test_client_window_runtime_builds_dedicated_structure_view() -> None:
    app = QApplication.instance() or QApplication([])
    row = {
        "guid": "form-guid",
        "type": "form",
        "name": "Form",
        "title": "Form",
        "payload": {
            "form_model_ref": "manifest-payload/form-guid/form_model.json",
            "layout_model_ref": "manifest-payload/form-guid/layout_model.json",
            "module_asset_key": "module-src/form-guid.bsl",
        },
    }
    stub = _RuntimeStub(row)

    host = stub._build_structure_inspector_view(title="Form", guid="form-guid")
    inspector = host.findChild(StructureInspectorWidget)
    assert inspector is not None
    module_text = inspector.findChild(QPlainTextEdit, "StructureInspectorModuleText")
    refs = inspector.findChild(type(inspector._refs), "StructureInspectorRefs")
    assert module_text is not None and module_text.toPlainText().startswith("Procedure Test()")
    assert refs is not None and "layout_model_ref:" in refs.text()
    assert stub._titles["struct:form-guid"] == "Form"
    assert app is not None


def test_client_window_runtime_opens_structure_for_guid() -> None:
    app = QApplication.instance() or QApplication([])
    row = {
        "guid": "form-guid",
        "type": "form",
        "name": "Form",
        "title": "Form",
        "payload": {
            "form_model_ref": "manifest-payload/form-guid/form_model.json",
            "layout_model_ref": "manifest-payload/form-guid/layout_model.json",
            "module_asset_key": "module-src/form-guid.bsl",
        },
    }
    stub = _RuntimeStub(row)

    stub._open_structure_for_guid("form-guid")

    assert "struct:form-guid" in stub._views
    assert stub._titles["struct:form-guid"] == "Form"
    assert app is not None


def test_nav_population_uses_inline_subsystem_objects_without_full_payload() -> None:
    app = QApplication.instance() or QApplication([])

    rows = [
        {
            "guid": "sub-guid",
            "type": "subsystem",
            "kind": "object",
            "name": "Subsystem",
            "title": "Subsystem",
            "payload": {"synonym": {"uk": "Підсистема"}},
            "objects": ["catalog-guid"],
        },
        {
            "guid": "catalog-guid",
            "type": "catalog",
            "kind": "object",
            "name": "Catalog",
            "title": "Catalog",
            "payload": {"synonym": {"uk": "Каталог"}},
        },
    ]
    stub = _NavRuntimeStub(rows)

    calls = {"get_objects": 0, "get_payload": 0}

    def _boom_objects(guid: str) -> list[str]:
        calls["get_objects"] += 1
        raise AssertionError(f"manifest_get_objects should not be called for {guid}")

    def _boom_payload(guid: str) -> dict:
        calls["get_payload"] += 1
        raise AssertionError(f"manifest_get_payload should not be called for {guid}")

    stub._db._gw.manifest_get_objects = _boom_objects
    stub._db._gw.manifest_get_payload = _boom_payload

    assert stub._populate_nav_tree_from_manifest() is True
    assert calls == {"get_objects": 0, "get_payload": 0}
    assert stub._nav.topLevelItemCount() >= 5
    assert app is not None


def test_refresh_runtime_data_skips_when_manifest_load_is_active() -> None:
    stub = _RefreshRuntimeStub()

    stub._refresh_runtime_data()

    assert stub.populate_calls == 0


def test_refresh_runtime_data_does_not_cold_load_when_cache_empty() -> None:
    class _EmptyStub(ClientWindowRuntimeMixin):
        def __init__(self) -> None:
            self._db = _FakeDb()
            self._manifest_rows_cache = []
            self._manifest_by_guid_cache = {}
            self._views = {}
            self._titles = {}
            self.bootstrap_calls = 0

        def _load_manifest_structure(self, *, force: bool = False) -> None:
            self.bootstrap_calls += 1

        def _manifest_refresh_key(self) -> str:
            return "db-1|hash-1|10"

    stub = _EmptyStub()
    stub._refresh_runtime_data()

    assert stub.bootstrap_calls == 0


def test_startup_pre_phase_uses_root_payload_without_loading_full_manifest() -> None:
    stub = _StartupRuntimeStub()

    ok = stub._run_startup_modules(phase="pre")

    assert ok is False
    assert "manifest_rows" not in stub._calls
    assert stub._startup_modules_fingerprints["pre"] == "fp-1"
    assert stub._manifest_rows_cache[0]["type"] == "common_module"


def test_startup_pre_phase_resolves_direct_module_guid_refs() -> None:
    stub = _DirectModuleStartupStub()

    ok = stub._run_startup_modules(phase="pre")

    assert ok is False
    assert "manifest_rows" not in stub._calls
    assert stub._startup_modules_fingerprints["pre"] == "fp-direct"


def test_startup_module_globals_persist_between_pre_and_post_phases() -> None:
    stub = _PersistentStartupStub()

    assert stub._run_startup_modules(phase="pre") is True
    assert stub._run_startup_modules(phase="post") is True
    ctx = stub._startup_module_contexts["module://mod-1"]
    assert ctx["глФормаНачальнойНастройкиПрограммы"] == 42
    assert ctx["Cancel"] is False
    assert ctx["Метаданные"].Find("mod-1")["guid"] == "mod-1"


def test_startup_pre_phase_honors_parameterized_refusal_flag() -> None:
    stub = _ParameterizedCancelStartupStub()

    assert stub._run_startup_modules(phase="pre") is False

    ctx = stub._startup_module_contexts["module://mod-1"]
    assert ctx["Отказ"] is True
    assert stub._startup_modules_fingerprints["pre"] == "fp-1"


def test_startup_runtime_resolves_built_in_module_refs_and_shares_context_with_debugger() -> None:
    pauses = []
    debugger = DebugSession(
        breakpoints={"module://managed-guid": {4}},
        pause_handler=lambda pause: pauses.append(pause) or "continue",
    )
    gateway = _StartupGateway()
    stub = _GatewayStartupStub(gateway, debugger)

    assert stub._run_startup_modules(phase="pre") is True
    shared = stub._startup_shared_context
    assert shared["InitCount"] == 1
    assert shared["SharedStartupValue"] == 41
    assert shared["SessionSawManaged"] == 41
    assert shared["OrdinarySawSession"] == 41
    assert gateway.manifest_list_calls == 0
    assert gateway.payload_requests == [gateway.root_guid]
    assert "module-src/managed-guid.bsl" in gateway.asset_requests
    assert [pause.module_id for pause in pauses] == ["module://managed-guid"]

    # A persistent context must suppress the managed module initializer in the
    # post phase while keeping globals visible to subsequent built-in modules.
    shared["InitCount"] = 7
    assert stub._run_startup_modules(phase="post") is True
    assert shared["PostManagedValue"] == 48
    assert shared["SessionPostValue"] == 49
    assert shared["OrdinaryPostValue"] == 50
    contexts = stub._startup_module_contexts
    assert contexts["module://managed-guid"] is shared
    assert contexts["module://session-guid"] is shared
    assert contexts["module://ordinary-guid"] is shared
    assert stub._startup_modules_fingerprints == {
        "pre": "gateway-startup",
        "post": "gateway-startup",
    }


def test_startup_calls_exported_common_module_and_debugger_enters_its_module() -> None:
    pauses = []
    debugger = DebugSession(
        breakpoints={"module://helper-module-guid": {2}},
        pause_handler=lambda pause: pauses.append(pause) or "continue",
    )
    stub = _CommonModuleStartupStub(debugger)

    assert stub._run_startup_modules(phase="pre") is True

    assert stub._startup_shared_context["CommonResult"] == 42
    assert stub.resolve_calls == ["StartupHelper"]
    assert [(pause.module_id, pause.code_name, pause.line) for pause in pauses] == [
        ("module://helper-module-guid", "ReturnValue", 2),
    ]


def test_manifest_refresh_key_ignores_generated_at() -> None:
    class _KeyStub(ClientWindowRuntimeMixin):
        def __init__(self, info: dict) -> None:
            self._db = _FakeDb()
            self._info = info

    stub1 = _KeyStub({"db_uid": "db-1", "structure_hash": "hash-1", "generated_at": 1, "object_count": 10})
    stub2 = _KeyStub({"db_uid": "db-1", "structure_hash": "hash-1", "generated_at": 2, "object_count": 10})

    def _manifest_info_1():
        return dict(stub1._info)

    def _manifest_info_2():
        return dict(stub2._info)

    stub1._db._gw.manifest_info = _manifest_info_1
    stub2._db._gw.manifest_info = _manifest_info_2

    assert stub1._manifest_refresh_key() == stub2._manifest_refresh_key()
