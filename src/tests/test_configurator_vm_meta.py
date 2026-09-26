from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

import src.ui_qt.viewmodels.configurator_viewmodel as configurator_viewmodel_module
import src.ui_qt.viewmodels.configurator_vm_runtime as configurator_vm_runtime_module
from src.ui_qt.viewmodels.configurator_vm import ConfiguratorViewModel
from src.configurator.manifest_schema import ManifestObject
from src.ui_qt.i18n import get_lang
from src.ui_qt.viewmodels.configurator_vm_editor_actions import ConfiguratorVmEditorActionsMixin


@dataclass
class _SignalStub:
    sink: Callable[[Any], None] | None = None

    def emit(self, value: Any) -> None:
        if self.sink is not None:
            self.sink(value)


@dataclass
class _DialogsStub:
    warnings: list[tuple[str, str]] = field(default_factory=list)

    def show_warning(self, title: Any, text: Any) -> None:
        self.warnings.append((str(title), str(text)))

    def show_info(self, *_args, **_kwargs) -> None:
        return None

    def confirm(self, *_args, **_kwargs) -> bool:
        return True


@dataclass
class _PayloadRef:
    payload: dict[str, Any]


@dataclass
class _ManifestPayloadServiceStub:
    payload_by_guid: dict[str, dict[str, Any]] = field(default_factory=dict)
    objects_by_guid: dict[str, list[str]] = field(default_factory=dict)

    def manifest_get_payload(self, guid: str) -> dict[str, Any]:
        return dict(self.payload_by_guid.get(str(guid) or "") or {})

    def manifest_get_objects(self, guid: str) -> list[str]:
        return list(self.objects_by_guid.get(str(guid) or "") or [])


@dataclass
class _MetaByGuidVmStub:
    _meta_by_guid: dict[str, dict[str, Any]]
    _objects_by_guid: dict[str, _PayloadRef]
    _full_payload_by_guid: dict[str, dict[str, Any]]

    def _payload_for_guid(self, guid: str) -> dict[str, Any]:
        return dict(self._full_payload_by_guid.get(guid) or {})


@dataclass
class _SavePayloadServiceStub:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    asset_calls: list[tuple[str, object]] = field(default_factory=list)
    error: Exception | None = None

    def update_object_payload(self, guid: str, payload: dict[str, Any]) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append((str(guid), dict(payload)))

    def put_json_asset(self, key: str, value: object) -> None:
        if self.error is not None:
            raise self.error
        self.asset_calls.append((str(key), value))


@dataclass
class _SavePayloadVmStub:
    _service: _SavePayloadServiceStub
    _dialogs: _DialogsStub
    _payload_overrides_by_guid: dict[str, dict[str, Any]] = field(default_factory=dict)
    _meta_by_guid: dict[str, dict[str, Any]] = field(default_factory=dict)
    _objects_by_guid: dict[str, Any] = field(default_factory=dict)
    statuses: list[str] = field(default_factory=list)
    reloads: list[bool] = field(default_factory=list)
    statusChanged: _SignalStub = field(init=False)

    def __post_init__(self) -> None:
        self.statusChanged = _SignalStub(lambda text: self.statuses.append(str(text)))

    @staticmethod
    def _tree_payload_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        return ConfiguratorViewModel._tree_payload_snapshot(payload)

    def reload(self) -> None:
        self.reloads.append(True)

    def _remember_payload_override(self, guid: str, payload: dict[str, Any]) -> None:
        ConfiguratorViewModel._remember_payload_override(self, guid, payload)

    def _payload_for_guid(self, guid: str) -> dict[str, Any]:
        return dict(self._payload_overrides_by_guid.get(str(guid) or "") or {})

    def save_object_payload(self, guid: str, payload: dict[str, Any], *, reload: bool = True) -> bool:
        return ConfiguratorViewModel.save_object_payload(self, guid, payload, reload=reload)


@dataclass
class _UpdatePayloadVmStub:
    _dialogs: _DialogsStub
    calls: list[tuple[str, dict[str, Any], bool]] = field(default_factory=list)

    def save_object_payload_patch(self, guid: str, payload_patch: dict[str, Any], *, reload: bool = True) -> bool:
        self.calls.append((str(guid), dict(payload_patch), bool(reload)))
        return True


@dataclass
class _NoServiceListObjectsStub:
    def list_objects(self):
        raise RuntimeError("should not call service")


@dataclass
class _MembershipVmStub:
    _service: Any
    _objects_snapshot: list[ManifestObject]
    reopened: int = 0
    refreshed: int = 0
    background_refreshed: int = 0

    def list_objects(self):
        return list(self._objects_snapshot)

    def manifest_get_payload(self, guid: str) -> dict[str, Any]:
        return dict(self._service.manifest_get_payload(guid))

    def reopen_db(self) -> None:
        self.reopened += 1

    def refresh_from_runtime(self) -> None:
        self.refreshed += 1

    def start_background_runtime_refresh(self) -> None:
        self.background_refreshed += 1


@dataclass
class _ListSnapshotVmStub:
    _service: _NoServiceListObjectsStub
    _objects_snapshot: list[ManifestObject]
    _subsystems_cache: list[dict[str, Any]] = field(default_factory=list)

    def _rebuild_subsystems_cache(self) -> None:
        ConfiguratorViewModel._rebuild_subsystems_cache(self)


@dataclass
class _EditorStub:
    loaded: list[str]

    def load(self, obj: ManifestObject) -> dict[str, str]:
        self.loaded.append(str(obj.guid))
        return {"guid": str(obj.guid)}


@dataclass
class _SelectVmStub:
    _service: _NoServiceListObjectsStub
    _objects_by_guid: dict[str, ManifestObject]
    _editor: _EditorStub
    emitted_states: list[object] = field(default_factory=list)
    propertiesRowsChanged: _SignalStub = field(default_factory=_SignalStub)
    editorStateChanged: _SignalStub = field(init=False)

    def __post_init__(self) -> None:
        self.editorStateChanged = _SignalStub(lambda state: self.emitted_states.append(state))

    def _clear_schema_editor(self) -> None:
        self._schema_editor_state = None
        self._schema_editor_context = {}


@dataclass
class _DbHandleStub:
    table_factory: Callable[[str], Any]

    def table(self, name: str) -> Any:
        return self.table_factory(str(name))


@dataclass
class _DbVmStub:
    db: _DbHandleStub


@dataclass
class _OpenDbResultStub:
    db: Any
    objects: list[Any]
    loaded_from_cache: bool
    cache_validated: bool = False


@dataclass
class _OpenDbServiceStub:
    result: _OpenDbResultStub

    def open_db(
        self,
        runtime_url: str,
        db_uid: str,
        *,
        db_path: str = "",
        seed_defaults_if_empty: bool = True,
    ) -> _OpenDbResultStub:
        return self.result


@dataclass
class _ReopenVmStub:
    _service: _OpenDbServiceStub
    runtime_url: str
    db_uid: str
    populated: list[list[Any]] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    statusChanged: _SignalStub = field(init=False)

    def __post_init__(self) -> None:
        self.statusChanged = _SignalStub(lambda text: self.statuses.append(str(text)))

    def _populate_tree(self, objs: list[Any]) -> None:
        self.populated.append(list(objs))

    def start_background_runtime_refresh(self) -> None:
        return None


@dataclass
class _EditorServiceStub:
    pass


@dataclass
class _ImportVmStub:
    runtime_url: str = "http://127.0.0.1:8765"
    db_uid: str = "db-uid"
    reopened: list[bool] = field(default_factory=list)
    reloaded: list[bool] = field(default_factory=list)
    closed: list[bool] = field(default_factory=list)

    def close_db(self) -> None:
        self.closed.append(True)

    def reopen_db(self) -> None:
        self.reopened.append(True)

    def reload(self) -> None:
        self.reloaded.append(True)

    def runtime_session_id(self) -> str:
        return "session-1"


@dataclass
class _NodeInfoStub:
    guid: str
    name: str
    obj_type: str
    kind: str = ""


class _SchemaEditorVmStub(ConfiguratorVmEditorActionsMixin):
    def __init__(self, meta_by_guid: dict[str, dict[str, Any]], payload_by_guid: dict[str, dict[str, Any]]) -> None:
        self._meta_by_guid = deepcopy(meta_by_guid)
        self._payload_by_guid = deepcopy(payload_by_guid)
        self._objects_by_guid = {}
        self._schema_editor_state = None
        self._schema_editor_context = {}
        self.saved: list[tuple[str, dict[str, Any], bool]] = []
        self.emitted_states: list[object] = []
        self.statuses: list[str] = []
        self.propertiesRowsChanged = _SignalStub()
        self.editorStateChanged = _SignalStub(self.emitted_states.append)
        self.statusChanged = _SignalStub(self.statuses.append)

    def get_meta_by_guid(self, guid: str) -> dict[str, Any] | None:
        value = self._meta_by_guid.get(str(guid))
        return deepcopy(value) if isinstance(value, dict) else None

    def _payload_for_guid(self, guid: str) -> dict[str, Any]:
        return deepcopy(self._payload_by_guid.get(str(guid)) or {})

    def save_object_payload(self, guid: str, payload: dict[str, Any], *, reload: bool = True) -> bool:
        normalized = deepcopy(payload)
        self.saved.append((str(guid), normalized, bool(reload)))
        self._payload_by_guid[str(guid)] = normalized
        return True

    def _deploy_schema_bg(self) -> None:
        return None


def test_get_meta_by_guid_merges_full_payload_from_object_snapshot() -> None:
    guid = "form-guid"
    tree_meta = {
        "guid": guid,
        "type": "form",
        "name": "FormaDokumenta",
        "title": "FormaDokumenta",
        "kind": "object",
        "parent_guid": "forms-folder",
        "payload": {"subtype": "object_form"},
    }
    full_payload = {
        "subtype": "object_form",
        "form_model": {"root": {"children": [{"type": "Tabs", "children": []}]}},
        "imported": {"origin": "Documents/AdvanceReport/Forms/FormaDokumenta.xml"},
    }
    vm = _MetaByGuidVmStub(
        _meta_by_guid={guid: tree_meta},
        _objects_by_guid={guid: _PayloadRef(payload=full_payload)},
        _full_payload_by_guid={guid: full_payload},
    )

    meta = ConfiguratorViewModel.get_meta_by_guid(vm, guid)

    assert isinstance(meta, dict)
    assert meta["guid"] == guid
    assert meta["payload"]["subtype"] == "object_form"
    assert meta["payload"]["form_model"]["root"]["children"][0]["type"] == "Tabs"
    assert meta["payload"]["imported"]["origin"].endswith("FormaDokumenta.xml")
    assert "form_model" not in tree_meta["payload"]


def test_get_meta_by_guid_hydrates_common_module_payload_from_service() -> None:
    guid = "owner-guid"
    tree_meta = {
        "guid": guid,
        "type": "common_module",
        "name": "AppModule",
        "title": "AppModule",
        "kind": "object",
        "parent_guid": "common-modules-folder",
        "payload": {},
    }
    service = _ManifestPayloadServiceStub(
        payload_by_guid={
            guid: {
                "module": {"asset_key": "module://real-module-guid", "mime": "text/plain"},
                "imported": {"origin": "Ext/ManagedApplicationModule.bsl"},
            }
        }
    )
    vm = type("HydrationVmStub", (), {})()
    vm._service = service
    vm._dialogs = _DialogsStub()
    vm._payload_overrides_by_guid = {}
    vm._meta_by_guid = {guid: tree_meta}
    vm._objects_by_guid = {
        guid: _PayloadRef(payload={}),
    }
    vm._objects_snapshot = []
    vm._subsystems_cache = []
    vm._tree_payload_snapshot = ConfiguratorViewModel._tree_payload_snapshot
    vm._manifest_payload_for_guid = ConfiguratorViewModel._manifest_payload_for_guid.__get__(vm, type(vm))
    vm._remember_payload_override = ConfiguratorViewModel._remember_payload_override.__get__(vm, type(vm))
    vm._payload_for_guid = ConfiguratorViewModel._payload_for_guid.__get__(vm, type(vm))

    meta = ConfiguratorViewModel.get_meta_by_guid(vm, guid)

    assert isinstance(meta, dict)
    assert meta["payload"]["module"]["asset_key"] == "module://real-module-guid"
    assert meta["payload"]["imported"]["origin"].endswith("ManagedApplicationModule.bsl")


def test_get_meta_by_guid_hydrates_subsystem_objects_from_service() -> None:
    guid = "subsystem-guid"
    tree_meta = {
        "guid": guid,
        "type": "subsystem",
        "name": "Integration",
        "title": "Integration",
        "kind": "object",
        "parent_guid": "subsystems-folder",
        "payload": {"imported": {"origin": "Subsystems/Integration.xml"}, "metadata_ref": "Subsystem.Integration"},
    }
    service = _ManifestPayloadServiceStub(
        payload_by_guid={guid: {"imported": {"origin": "Subsystems/Integration.xml"}}},
        objects_by_guid={guid: ["dp-guid-1", "dp-guid-2"]},
    )
    vm = type("HydrationVmStub", (), {})()
    vm._service = service
    vm._dialogs = _DialogsStub()
    vm._payload_overrides_by_guid = {}
    vm._meta_by_guid = {guid: tree_meta}
    vm._objects_by_guid = {
        guid: _PayloadRef(payload={"imported": {"origin": "Subsystems/Integration.xml"}}),
    }
    vm._objects_snapshot = []
    vm._subsystems_cache = []
    vm._tree_payload_snapshot = ConfiguratorViewModel._tree_payload_snapshot
    vm._manifest_payload_for_guid = ConfiguratorViewModel._manifest_payload_for_guid.__get__(vm, type(vm))
    vm._remember_payload_override = ConfiguratorViewModel._remember_payload_override.__get__(vm, type(vm))
    vm._payload_for_guid = ConfiguratorViewModel._payload_for_guid.__get__(vm, type(vm))

    payload = ConfiguratorViewModel._payload_for_guid(vm, guid)

    assert payload["objects"] == ["dp-guid-1", "dp-guid-2"]


def test_get_meta_by_guid_hydrates_form_payload_from_service() -> None:
    guid = "form-guid"
    tree_meta = {
        "guid": guid,
        "type": "form",
        "name": "AdvanceReportForm",
        "title": "AdvanceReportForm",
        "kind": "object",
        "parent_guid": "forms-folder",
        "payload": {"subtype": "object_form"},
    }
    service = _ManifestPayloadServiceStub(
        payload_by_guid={
            guid: {
                "subtype": "object_form",
                "form_model": {"root": {"children": [{"type": "Tabs", "children": []}]}},
                "form_module": "Процедура Тест()\nКонецПроцедури",
                "imported": {"origin": "Documents/AdvanceReport/Forms/AdvanceReportForm.xml"},
            }
        }
    )
    vm = type("HydrationVmStub", (), {})()
    vm._service = service
    vm._dialogs = _DialogsStub()
    vm._payload_overrides_by_guid = {}
    vm._meta_by_guid = {guid: tree_meta}
    vm._objects_by_guid = {
        guid: _PayloadRef(payload={}),
    }
    vm._objects_snapshot = []
    vm._subsystems_cache = []
    vm._tree_payload_snapshot = ConfiguratorViewModel._tree_payload_snapshot
    vm._manifest_payload_for_guid = ConfiguratorViewModel._manifest_payload_for_guid.__get__(vm, type(vm))
    vm._remember_payload_override = ConfiguratorViewModel._remember_payload_override.__get__(vm, type(vm))
    vm._payload_for_guid = ConfiguratorViewModel._payload_for_guid.__get__(vm, type(vm))

    meta = ConfiguratorViewModel.get_meta_by_guid(vm, guid)

    assert isinstance(meta, dict)
    assert meta["payload"]["form_model"]["root"]["children"][0]["type"] == "Tabs"
    assert "Процедура Тест" in meta["payload"]["form_module"]
    assert meta["payload"]["imported"]["origin"].endswith("AdvanceReportForm.xml")


def test_save_object_payload_without_reload_updates_override_cache() -> None:
    calls: list[tuple[str, dict]] = []
    statuses: list[str] = []
    reloads: list[bool] = []
    warnings: list[tuple[str, str]] = []

    service = _SavePayloadServiceStub(calls=calls)
    dialogs = _DialogsStub(warnings=warnings)
    vm = _SavePayloadVmStub(
        _service=service,
        _dialogs=dialogs,
        _meta_by_guid={"layout-guid": {"payload": {}}},
        statuses=statuses,
        reloads=reloads,
    )

    ok = ConfiguratorViewModel.save_object_payload(
        vm,
        "layout-guid",
        {"layout_model": {"kind": "spreadsheet_document"}, "layout_kind": "spreadsheet_document"},
        reload=False,
    )

    assert ok is True
    assert calls == [
        (
            "layout-guid",
            {"layout_model": {"kind": "spreadsheet_document"}, "layout_kind": "spreadsheet_document"},
        )
    ]
    assert vm._payload_overrides_by_guid["layout-guid"]["layout_kind"] == "spreadsheet_document"
    assert vm._meta_by_guid["layout-guid"]["payload"] == {}
    assert reloads == []
    assert warnings == []
    assert statuses


def test_save_object_payload_shows_underlying_error_text() -> None:
    warnings: list[tuple[str, str]] = []

    service = _SavePayloadServiceStub(error=RuntimeError("manifest.update_payload: timed out"))
    dialogs = _DialogsStub(warnings=warnings)
    vm = _SavePayloadVmStub(
        _service=service,
        _dialogs=dialogs,
    )

    ok = ConfiguratorViewModel.save_object_payload(
        vm,
        "layout-guid",
        {"layout_kind": "spreadsheet_document"},
        reload=False,
    )

    assert ok is False
    assert warnings
    assert "timed out" in warnings[-1][1]


def test_save_object_payload_failure_does_not_reload_and_discard_editor_state() -> None:
    service = _SavePayloadServiceStub(error=RuntimeError("manifest.update_payload: timed out"))
    vm = _SavePayloadVmStub(
        _service=service,
        _dialogs=_DialogsStub(),
    )

    ok = ConfiguratorViewModel.save_object_payload(
        vm,
        "form-guid",
        {"form_module": "unsaved text"},
        reload=True,
    )

    assert ok is False
    assert vm.reloads == []


def test_save_externalized_payload_asset_updates_asset_without_manifest_update() -> None:
    service = _SavePayloadServiceStub()
    dialogs = _DialogsStub()
    vm = _SavePayloadVmStub(
        _service=service,
        _dialogs=dialogs,
        _meta_by_guid={"layout-guid": {"payload": {}}},
    )

    ok = ConfiguratorViewModel.save_externalized_payload_asset(
        vm,
        "layout-guid",
        {
            "layout_kind": "spreadsheet_document",
            "layout_model_ref": "manifest-payload/layout-guid/layout_model.json",
            "layout_model": {"kind": "spreadsheet_document", "cells": [{"row": 0, "col": 0, "text": "x"}]},
        },
        key="layout_model",
        reload=False,
    )

    assert ok is True
    assert service.calls == []
    assert service.asset_calls == [
        (
            "manifest-payload/layout-guid/layout_model.json",
            {"kind": "spreadsheet_document", "cells": [{"row": 0, "col": 0, "text": "x"}]},
        )
    ]
    assert vm._payload_overrides_by_guid["layout-guid"]["layout_model_ref"].endswith("layout_model.json")
    assert vm._payload_overrides_by_guid["layout-guid"]["layout_model"]["cells"][0]["text"] == "x"


def test_payload_for_guid_hydrates_partial_externalized_override() -> None:
    guid = "form-guid"
    service = _ManifestPayloadServiceStub(
        payload_by_guid={
            guid: {
                "form_model_ref": "manifest-payload/form-guid/form_model.json",
                "form_model": {"root": {"children": [{"id": "persisted"}]}},
                "form_module": "persisted module",
            }
        }
    )
    vm = type("HydrationVmStub", (), {})()
    vm._service = service
    vm._payload_overrides_by_guid = {
        guid: {
            "form_model_ref": "manifest-payload/form-guid/form_model.json",
            "form_module": "local module",
        }
    }
    vm._meta_by_guid = {guid: {"type": "form", "payload": {}}}
    vm._objects_by_guid = {guid: _PayloadRef(payload={})}
    vm._tree_payload_snapshot = ConfiguratorViewModel._tree_payload_snapshot
    vm._manifest_payload_for_guid = ConfiguratorViewModel._manifest_payload_for_guid.__get__(vm, type(vm))
    vm._remember_payload_override = ConfiguratorViewModel._remember_payload_override.__get__(vm, type(vm))

    payload = ConfiguratorViewModel._payload_for_guid(vm, guid)

    assert payload["form_model"]["root"]["children"][0]["id"] == "persisted"
    assert payload["form_module"] == "local module"
    assert vm._payload_overrides_by_guid[guid] == payload


def test_update_object_payload_uses_non_reload_patch_path() -> None:
    vm = _UpdatePayloadVmStub(_dialogs=_DialogsStub())

    ConfiguratorViewModel.update_object_payload(vm, "form-guid", {"explanation": "abc"})

    assert vm.calls == [("form-guid", {"explanation": "abc"}, False)]


def test_save_object_payload_patch_strips_hydrated_externalized_keys_from_base() -> None:
    service = _SavePayloadServiceStub()
    dialogs = _DialogsStub()
    vm = _SavePayloadVmStub(
        _service=service,
        _dialogs=dialogs,
    )
    vm._payload_overrides_by_guid["form-guid"] = {
        "form_model_ref": "manifest-payload/form-guid/form_model.json",
        "form_model": {"root": {"children": [{"id": "x"}]}},
        "form_module": "old",
    }

    ok = ConfiguratorViewModel.save_object_payload_patch(
        vm,
        "form-guid",
        {"form_module": "new"},
        reload=False,
    )

    assert ok is True
    assert service.calls
    guid, payload = service.calls[-1]
    assert guid == "form-guid"
    assert payload["form_model_ref"].endswith("form_model.json")
    assert "form_model" not in payload
    assert payload["form_module"] == "new"


def test_save_object_payload_patch_aborts_when_authoritative_read_fails() -> None:
    class FailingReadService(_SavePayloadServiceStub):
        def manifest_get_payload(self, guid: str) -> dict[str, Any]:
            raise TimeoutError(f"payload timeout: {guid}")

    service = FailingReadService()
    vm = _SavePayloadVmStub(
        _service=service,
        _dialogs=_DialogsStub(),
    )
    vm._payload_overrides_by_guid["form-guid"] = {"form_module": "local"}

    ok = ConfiguratorViewModel.save_object_payload_patch(
        vm,
        "form-guid",
        {"form_module": "new"},
        reload=False,
    )

    assert ok is False
    assert service.calls == []
    assert vm._dialogs.warnings


def test_manifest_payload_and_membership_proxies_use_service() -> None:
    service = _ManifestPayloadServiceStub(
        payload_by_guid={"obj-guid": {"name": "Object"}},
        objects_by_guid={"sub-guid": ["obj-guid"]},
    )
    vm = type("RuntimeProxyVmStub", (), {"_service": service})()

    assert ConfiguratorViewModel.manifest_get_payload(vm, "obj-guid") == {"name": "Object"}
    assert ConfiguratorViewModel.manifest_get_objects(vm, "sub-guid") == ["obj-guid"]


def test_background_refresh_ignores_snapshot_from_previous_connection_epoch() -> None:
    populated: list[list[str]] = []
    vm = type("RefreshEpochVmStub", (), {})()
    vm._runtime_refresh_epoch = 2
    vm._runtime_refresh_in_flight = True
    vm.statusChanged = _SignalStub()
    vm._populate_tree = lambda rows: populated.append(list(rows))

    ConfiguratorViewModel._on_runtime_refresh_ready(vm, (1, ["old-object"]), 0.1)

    assert populated == []
    assert vm._runtime_refresh_in_flight is True

    ConfiguratorViewModel._on_runtime_refresh_ready(vm, (2, ["new-object"]), 0.1)

    assert populated == [["new-object"]]
    assert vm._runtime_refresh_in_flight is False


def test_list_objects_and_subsystems_use_local_snapshot_without_service_call() -> None:
    objs = [
        ManifestObject(guid="sub-1", type="subsystem", name="ss1", title="Subsystem 1", kind="object", parent_guid="", payload={}),
        ManifestObject(guid="sub-2", type="subsystem", name="ss2", title="Subsystem 2", kind="object", parent_guid="sub-1", payload={}),
        ManifestObject(guid="doc-1", type="document", name="Doc1", title="Document 1", kind="object", parent_guid="", payload={}),
    ]
    vm = _ListSnapshotVmStub(
        _service=_NoServiceListObjectsStub(),
        _objects_snapshot=list(objs),
    )

    listed = ConfiguratorViewModel.list_objects(vm)
    subsystems = ConfiguratorViewModel.list_subsystems(vm)

    assert [o.guid for o in listed] == ["sub-1", "sub-2", "doc-1"]
    assert subsystems == [
        {"guid": "sub-1", "name": "ss1", "title": "Subsystem 1", "path": "Subsystem 1", "parent_guid": ""},
        {"guid": "sub-2", "name": "ss2", "title": "Subsystem 2", "path": "Subsystem 1 / Subsystem 2", "parent_guid": "sub-1"},
    ]


def test_on_select_uses_local_object_snapshot_without_runtime_reload() -> None:
    loaded: list[str] = []
    emitted: list[object] = []
    obj = ManifestObject(guid="obj-1", type="document", name="Doc1", title="Document 1", kind="object", parent_guid="", payload={})
    vm = _SelectVmStub(
        _service=_NoServiceListObjectsStub(),
        _objects_by_guid={"obj-1": obj},
        _editor=_EditorStub(loaded=loaded),
        emitted_states=emitted,
    )

    ConfiguratorViewModel.on_select(vm, _NodeInfoStub(guid="obj-1", name="Document 1", obj_type="document"))

    assert loaded == ["obj-1"]
    assert emitted == [{"guid": "obj-1"}]


def test_schema_requisite_selection_edits_in_memory_and_saves_owner_payload() -> None:
    owner_guid = "owner-guid"
    virtual_guid = f"virtual:{owner_guid}:attributes:Organization"
    source_item = {
        "name": "Organization",
        "title": {"ru": "Организация", "uk": "Організація"},
        "type": "ref",
        "required": True,
        "read_only": False,
        "imported": {"src_uuid": "source-uuid", "raw_type": "cfg:CatalogRef.Organizations"},
        "ref_name": "Organizations",
        "fill_checking": "ShowError",
    }
    sibling = {"name": "Warehouse", "title": {"uk": "Склад"}, "type": "ref"}
    meta = {
        "guid": virtual_guid,
        "type": "document",
        "name": "Organization",
        "title": "Організація",
        "kind": "schema",
        "payload": {
            "section": "attributes",
            "schema_item_kind": "attribute",
            "schema_item": deepcopy(source_item),
        },
    }
    vm = _SchemaEditorVmStub(
        {virtual_guid: meta},
        {owner_guid: {"requisites": [source_item, sibling], "custom_owner_value": 7}},
    )

    vm.on_select(_NodeInfoStub(virtual_guid, "Організація", "document", kind="schema"))

    state = vm.emitted_states[-1]
    assert state.current["type"] == "schema_requisite"
    assert state.current["payload"]["source_type"] == "cfg:CatalogRef.Organizations"
    assert state.current["payload"]["required"] is True

    vm.on_editor_field_changed("title", "Організація-покупець")
    edited_payload = deepcopy(vm._schema_editor_state.current["payload"])
    edited_payload["read_only"] = True
    vm.on_editor_payload_changed(edited_payload)

    assert vm.saved == []
    assert vm.on_save() is True
    assert len(vm.saved) == 1
    saved_guid, saved_payload, reload = vm.saved[0]
    assert saved_guid == owner_guid
    assert reload is True
    assert saved_payload["custom_owner_value"] == 7
    assert saved_payload["requisites"][1] == sibling
    saved_item = saved_payload["requisites"][0]
    assert saved_item["title"]["ru"] == "Организация"
    assert saved_item["title"][get_lang()] == "Організація-покупець"
    assert saved_item["read_only"] is True
    assert saved_item["imported"] == source_item["imported"]


def test_schema_column_save_updates_only_selected_tabular_part_column() -> None:
    owner_guid = "owner-guid"
    virtual_guid = f"virtual:{owner_guid}:tabular_parts:Goods:Amount"
    selected_column = {
        "name": "Amount",
        "title": {"uk": "Кількість"},
        "type": "number",
        "number_qualifiers": {"digits": 15, "fraction_digits": 3},
        "imported": {"src_uuid": "column-uuid"},
    }
    owner_payload = {
        "tabular_parts": [
            {
                "name": "Goods",
                "columns": [
                    {"name": "Product", "type": "ref"},
                    selected_column,
                ],
            },
            {"name": "Services", "columns": [{"name": "Amount", "type": "number"}]},
        ]
    }
    meta = {
        "guid": virtual_guid,
        "type": "document",
        "kind": "schema",
        "payload": {
            "section": "tabular_parts",
            "schema_item_kind": "column",
            "tabular_part": "Goods",
            "schema_item": deepcopy(selected_column),
        },
    }
    vm = _SchemaEditorVmStub({virtual_guid: meta}, {owner_guid: owner_payload})

    vm.on_select(_NodeInfoStub(virtual_guid, "Кількість", "document", kind="schema"))
    edited_payload = deepcopy(vm._schema_editor_state.current["payload"])
    edited_payload["number_fraction_digits"] = "2"
    vm.on_editor_payload_changed(edited_payload)
    assert vm.on_save() is True

    saved = vm.saved[0][1]
    assert saved["tabular_parts"][0]["columns"][0] == owner_payload["tabular_parts"][0]["columns"][0]
    assert saved["tabular_parts"][0]["columns"][1]["number_qualifiers"]["fraction_digits"] == 2
    assert saved["tabular_parts"][1] == owner_payload["tabular_parts"][1]


def test_list_users_and_audit_log_smoke_use_runtime_tables() -> None:
    calls: list[tuple[str, object, object]] = []

    class FakeTable:
        def __init__(self, name: str) -> None:
            self._name = name

        def select(self, where=None, order_by=None):
            calls.append((self._name, where, order_by))
            if self._name == "sys_users":
                return [
                    {"login": "u1", "created_at": 10, "is_active": True},
                    {"login": "u2", "created_at": 20, "is_active": False},
                ]
            return [
                {"event": "b", "ts": 5},
                {"event": "a", "ts": 12},
            ]

    vm = _DbVmStub(db=_DbHandleStub(table_factory=lambda name: FakeTable(str(name))))

    users = ConfiguratorViewModel.list_users(vm, active_only=True)
    audit = ConfiguratorViewModel.list_audit_log(vm, limit=1)

    assert users[0]["login"] == "u2"
    assert audit == [{"event": "a", "ts": 12}]
    assert ("sys_users", {"is_active": True}, "created_at") in calls
    assert ("sys_audit_log", None, "ts") in calls


def test_reopen_db_rebinds_manifest_editor_service() -> None:
    statuses: list[str] = []
    populated: list[list[object]] = []
    vm = _ReopenVmStub(
        _service=_OpenDbServiceStub(
            result=_OpenDbResultStub(
                db="db-handle",
                objects=["o1", "o2"],
                loaded_from_cache=False,
            )
        ),
        runtime_url="http://127.0.0.1:8765",
        db_uid="db-uid",
        populated=populated,
        statuses=statuses,
    )

    ConfiguratorViewModel.reopen_db(vm)

    assert vm.db == "db-handle"
    assert hasattr(vm, "_editor")
    assert populated == [["o1", "o2"]]
    assert statuses


def test_diagnose_and_repair_subsystem_membership_round_trip() -> None:
    class _Svc:
        def __init__(self) -> None:
            self.payloads = {
                "sub-1": {"objects": [], "content_refs": ["Catalog.Products"]},
                "obj-1": {"metadata_ref": "Catalog.Products"},
            }
            self.updated: list[tuple[str, dict[str, Any]]] = []

        def manifest_get_payload(self, guid: str) -> dict[str, Any]:
            return dict(self.payloads.get(guid) or {})

        def update_object_payload(self, guid: str, payload: dict[str, Any]) -> None:
            self.updated.append((guid, dict(payload)))
            self.payloads[guid] = dict(payload)

    svc = _Svc()
    vm = _MembershipVmStub(
        _service=svc,
        _objects_snapshot=[
            ManifestObject(guid="sub-1", type="subsystem", name="Administration", title="Адміністрування", kind="object", parent_guid="", payload={}),
            ManifestObject(guid="obj-1", type="catalog", name="Products", title="Товари", kind="object", parent_guid="", payload={"metadata_ref": "Catalog.Products"}),
        ],
    )

    diag = ConfiguratorViewModel.diagnose_subsystem_membership(vm)
    assert diag["scanned"] == 1
    assert diag["mismatched"] == 1
    assert diag["items"][0]["has_mismatch"] is True

    rep = ConfiguratorViewModel.repair_subsystem_membership(vm)
    assert rep["changed"] == 1
    assert svc.updated
    assert vm.reopened == 1
    assert vm.refreshed == 1 or vm.background_refreshed == 1


def test_sync_subsystem_membership_repairs_and_returns_final_report() -> None:
    class _Svc:
        def __init__(self) -> None:
            self.payloads = {
                "sub-1": {"objects": [], "content_refs": ["Catalog.Products"]},
                "obj-1": {"metadata_ref": "Catalog.Products"},
            }
            self.updated: list[tuple[str, dict[str, Any]]] = []

        def manifest_get_payload(self, guid: str) -> dict[str, Any]:
            return dict(self.payloads.get(guid) or {})

        def update_object_payload(self, guid: str, payload: dict[str, Any]) -> None:
            self.updated.append((guid, dict(payload)))
            self.payloads[guid] = dict(payload)

    svc = _Svc()
    vm = _MembershipVmStub(
        _service=svc,
        _objects_snapshot=[
            ManifestObject(guid="sub-1", type="subsystem", name="Administration", title="Адміністрування", kind="object", parent_guid="", payload={}),
            ManifestObject(guid="obj-1", type="catalog", name="Products", title="Товари", kind="object", parent_guid="", payload={"metadata_ref": "Catalog.Products"}),
        ],
    )

    report = ConfiguratorViewModel.sync_subsystem_membership(vm)

    assert report["before"]["mismatched"] == 1
    assert report["mismatched_after"] == 0
    assert report["auto_repaired"] is True
    assert report["changed"] == 1
    assert svc.updated
    assert vm.reopened == 1
    assert vm.refreshed == 1 or vm.background_refreshed == 1


def test_repair_subsystem_membership_uses_one_bulk_write() -> None:
    class _Svc:
        def __init__(self) -> None:
            self.payloads = {
                "sub-1": {"objects": [], "content_refs": ["Catalog.Products"]},
                "sub-2": {"objects": [], "content_refs": ["Catalog.Products"]},
                "obj-1": {"metadata_ref": "Catalog.Products"},
            }
            self.bulk_calls: list[dict[str, dict[str, Any]]] = []

        def manifest_get_payload(self, guid: str) -> dict[str, Any]:
            return dict(self.payloads.get(guid) or {})

        def update_object_payloads(self, payloads: dict[str, dict[str, Any]]) -> int:
            normalized = {guid: dict(payload) for guid, payload in payloads.items()}
            self.bulk_calls.append(normalized)
            self.payloads.update(normalized)
            return len(normalized)

    svc = _Svc()
    vm = _MembershipVmStub(
        _service=svc,
        _objects_snapshot=[
            ManifestObject(guid="sub-1", type="subsystem", name="One", title="One", kind="object", parent_guid="", payload={}),
            ManifestObject(guid="sub-2", type="subsystem", name="Two", title="Two", kind="object", parent_guid="", payload={}),
            ManifestObject(guid="obj-1", type="catalog", name="Products", title="Products", kind="object", parent_guid="", payload={"metadata_ref": "Catalog.Products"}),
        ],
    )

    result = ConfiguratorViewModel.repair_subsystem_membership(vm)

    assert result["changed"] == 2
    assert len(svc.bulk_calls) == 1
    assert set(svc.bulk_calls[0]) == {"sub-1", "sub-2"}


def test_compare_source_structure_detects_subsystem_membership_mismatch(tmp_path) -> None:
    xml_root = tmp_path / "XMLConf"
    (xml_root / "Subsystems").mkdir(parents=True)
    (xml_root / "Subsystems" / "Administration.xml").write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<MetaDataObject xmlns='http://v8.1c.ru/8.3/MDClasses' xmlns:v8='http://v8.1c.ru/8.1/data/core' xmlns:xr='http://v8.1c.ru/8.3/xcf/readable' xmlns:xsi='http://www.w3.org/2001/XMLSchema-instance'>
  <Subsystem uuid='sub-1'>
    <Properties>
      <Name>Administration</Name>
      <Synonym>
        <v8:item><v8:lang>uk</v8:lang><v8:content>Адміністрування</v8:content></v8:item>
      </Synonym>
      <Content>
        <xr:Item xsi:type='xr:MDObjectRef'>Catalog.Products</xr:Item>
      </Content>
    </Properties>
    <ChildObjects>
      <Subsystem>NestedSubsystem</Subsystem>
    </ChildObjects>
  </Subsystem>
</MetaDataObject>
""",
        encoding="utf-8",
    )

    class _Svc:
        def __init__(self) -> None:
            self.payloads = {
                "sub-1": {"content_refs": [], "objects": []},
                "cat-1": {"metadata_ref": "Catalog.Products"},
            }

        def manifest_get_payload(self, guid: str) -> dict[str, Any]:
            return dict(self.payloads.get(guid) or {})

    class _Vm:
        def __init__(self) -> None:
            self._service = _Svc()
            self._objects_snapshot = [
                ManifestObject(guid="sub-1", type="subsystem", name="Administration", title="Адміністрування", kind="object", parent_guid="", payload={}),
                ManifestObject(guid="cat-1", type="catalog", name="Products", title="Товари", kind="object", parent_guid="", payload={"metadata_ref": "Catalog.Products"}),
            ]

        def list_objects(self):
            return list(self._objects_snapshot)

        def manifest_get_payload(self, guid: str) -> dict[str, Any]:
            return dict(self._service.manifest_get_payload(guid))

    report = ConfiguratorViewModel.compare_source_structure(
        _Vm(),
        source_path=str(xml_root),
        source_kind="xml",
    )

    assert report["summary"]["source_count"] == 1
    assert report["summary"]["db_count"] == 2
    assert report["summary"]["mismatched"] == 2
    assert report["items"][0]["status"] == "mismatch"
    assert report["items"][0]["diffs"]["content_refs"]["source"] == ["Catalog.Products"]
    assert report["items"][0]["diffs"]["child_subsystems"]["db"] == []
    assert report["items"][0]["diffs"]["objects"]["source"] == ["cat-1"]


def test_repair_source_structure_relinks_flattened_subtrees() -> None:
    class _Svc:
        def __init__(self) -> None:
            self.payloads = {
                "sub-root": {"child_subsystems": []},
                "sub-child": {"child_subsystems": [], "objects": []},
            }
            self.updated: list[tuple[str, dict[str, Any]]] = []
            self.field_updates: list[tuple[str, dict[str, Any]]] = []

        def manifest_get_payload(self, guid: str) -> dict[str, Any]:
            return dict(self.payloads.get(guid) or {})

        def update_object_payload(self, guid: str, payload: dict[str, Any]) -> None:
            self.updated.append((guid, dict(payload)))
            self.payloads[guid] = dict(payload)

        def update_object_fields(self, guid: str, **fields) -> None:
            self.field_updates.append((guid, dict(fields)))
            if "payload" in fields:
                self.payloads[guid] = dict(fields["payload"] or {})

    class _Vm(_MembershipVmStub):
        def compare_source_structure(self, *, source_path: str = "", source_kind: str = ""):
            return {
                "summary": {"flattened_subtree_count": 1},
                "flattened_subtrees": [
                    {
                        "parent_guid": "sub-root",
                        "parent_title": "Root",
                        "tree_path": "Root",
                        "source_child_count": 1,
                        "relocated_child_count": 1,
                        "source_children": ["sub-child"],
                        "source_child_names": ["Child"],
                        "relocated_children": [
                            {
                                "guid": "sub-child",
                                "title": "Child",
                                "db_parent_guid": "",
                                "db_parent_title": "",
                                "source_parent_guid": "sub-root",
                                "source_parent_title": "Root",
                            }
                        ],
                    }
                ],
                "items": [],
                "source": {"path": source_path, "semantic_kind": source_kind},
            }

    svc = _Svc()
    vm = _Vm(
        _service=svc,
        _objects_snapshot=[
            ManifestObject(guid="sub-root", type="subsystem", name="Root", title="Root", kind="object", parent_guid="", payload={"child_subsystems": []}),
            ManifestObject(guid="sub-child", type="subsystem", name="Child", title="Child", kind="object", parent_guid="", payload={"objects": []}),
        ],
    )

    report = ConfiguratorViewModel.repair_source_structure(vm, source_path="F:/ConfigFiles", source_kind="xml")

    assert report["changed"] == 2
    assert report["scanned"] == 1
    assert svc.field_updates[0][0] == "sub-root"
    assert svc.field_updates[0][1]["payload"]["child_subsystems"] == ["Child"]
    assert svc.field_updates[1][0] == "sub-child"
    assert svc.field_updates[1][1]["parent_guid"] == "sub-root"


def test_init_skips_runtime_refresh_after_validated_cache(monkeypatch) -> None:
    calls: list[str] = []
    populated: list[list[object]] = []
    scheduled: list[tuple[int, object]] = []

    class FakeService:
        def open_db(self, runtime_url: str, db_uid: str, *, db_path: str = "", seed_defaults_if_empty: bool = True):
            calls.append("open_db")
            return _OpenDbResultStub(
                db="db-handle",
                objects=["cached-object"],
                loaded_from_cache=True,
                cache_validated=True,
            )

        def list_objects(self):
            calls.append("list_objects")
            raise AssertionError("validated cache startup must not fetch manifest again")

    class FakeIconProvider:
        def __init__(self, _palette_cb, *, tree_icon_provider):
            self.tree_icon = tree_icon_provider

    monkeypatch.setattr(configurator_viewmodel_module, "ConfiguratorService", FakeService)
    monkeypatch.setattr(configurator_viewmodel_module, "ManifestEditorService", lambda _service: _EditorServiceStub())
    monkeypatch.setattr(configurator_viewmodel_module, "IconProvider", FakeIconProvider)
    monkeypatch.setattr(
        configurator_viewmodel_module.QTimer,
        "singleShot",
        staticmethod(lambda ms, cb: scheduled.append((int(ms), cb))),
    )
    monkeypatch.setattr(
        configurator_viewmodel_module.ConfiguratorViewModel,
        "_populate_tree",
        lambda self, objs: populated.append(list(objs)),
    )

    dialogs = _DialogsStub()

    configurator_viewmodel_module.ConfiguratorViewModel(
        "http://127.0.0.1:8765",
        "db-uid",
        dialogs=dialogs,
        icon_provider=lambda _meta: None,
        eager_runtime_refresh=True,
    )

    assert calls == ["open_db"]
    assert populated == [["cached-object"]]
    assert scheduled == []


def test_reopen_db_skips_background_refresh_after_validated_cache(monkeypatch) -> None:
    scheduled: list[tuple[int, object]] = []
    vm = _ReopenVmStub(
        _service=_OpenDbServiceStub(
            result=_OpenDbResultStub(
                db="db-handle",
                objects=["cached-object"],
                loaded_from_cache=True,
                cache_validated=True,
            )
        ),
        runtime_url="http://127.0.0.1:8765",
        db_uid="db-uid",
    )
    vm._populate_tree = lambda objs: None
    vm.statusChanged = _SignalStub(lambda _text: None)
    vm.start_background_runtime_refresh = lambda: None
    monkeypatch.setattr(configurator_vm_runtime_module, "ManifestEditorService", lambda _service: _EditorServiceStub())
    monkeypatch.setattr(
        configurator_vm_runtime_module.QTimer,
        "singleShot",
        staticmethod(lambda ms, cb: scheduled.append((int(ms), cb))),
    )

    ConfiguratorViewModel.reopen_db(vm)

    assert vm.db == "db-handle"
    assert scheduled == []


def test_import_onec_dump_reopens_db_without_extra_reload(monkeypatch) -> None:
    vm = _ImportVmStub()

    monkeypatch.setattr(
        "src.tools.onec_import.import_onec_configuration",
        lambda **kwargs: "ok",
    )

    result = ConfiguratorViewModel.import_onec_dump(
        vm,
        source_path="F:/MetaPlatform/WorkedData/1Cv8.dt",
        source_kind="dt",
    )

    assert result == "ok"
    assert vm.closed == [True]
    assert vm.reopened == [True]
    assert vm.reloaded == []
