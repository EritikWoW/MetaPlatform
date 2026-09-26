from __future__ import annotations

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QWidget

from src.configurator.configurator_editors import ConfiguratorEditorsMixin, _TimingMdiSubWindow
from src.configurator.ui.widgets import NodeInfo
from src.ui_qt.widgets.constant_properties import ConstantPropertiesWidget
from src.ui_qt.widgets.meta_object_editor_base import MetaObjectEditorBase
from src.ui_qt.widgets.meta_object_shell import EditorSection


class _SignalStub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def connect(self, _slot) -> None:
        return None

    def emit(self, *args, **kwargs) -> None:
        self.calls.append("emit")


class _CodeEditorStub(QWidget):
    def __init__(self, *, vm, asset_key: str, title: str) -> None:
        super().__init__()
        self.vm = vm
        self.asset_key = str(asset_key or "")
        self.title = str(title or "")
        self.closeRequested = _SignalStub()


class _SubsystemEditorStub(QWidget):
    def __init__(self, *, title: str, payload: dict | None = None, vm=None, obj_guid: str = "") -> None:
        super().__init__()
        self.title = str(title or "")
        self.payload = dict(payload or {})
        self.vm = vm
        self.obj_guid = str(obj_guid or "")
        self.applyRequested = _SignalStub()
        self.closeRequested = _SignalStub()


class _CatalogEditorStub(_SubsystemEditorStub):
    def __init__(
        self,
        *,
        title: str,
        payload: dict | None = None,
        obj_type: str = "",
        available_subsystems=None,
        vm=None,
        obj_guid: str = "",
    ) -> None:
        super().__init__(title=title, payload=payload, vm=vm, obj_guid=obj_guid)
        self.obj_type = str(obj_type or "")
        self.available_subsystems = list(available_subsystems or [])


class _RegisterEditorStub(_SubsystemEditorStub):
    def __init__(
        self,
        *,
        title: str,
        payload: dict | None = None,
        obj_type: str = "",
        vm=None,
        obj_guid: str = "",
    ) -> None:
        super().__init__(title=title, payload=payload, vm=vm, obj_guid=obj_guid)
        self.obj_type = str(obj_type or "")


class _EnumerationEditorStub(_SubsystemEditorStub):
    pass


class _RoleEditorStub(_SubsystemEditorStub):
    pass


class _ScheduledJobEditorStub(_SubsystemEditorStub):
    pass


class _EventSubscriptionEditorStub(_SubsystemEditorStub):
    pass


class _AccessRestrictionsStub(QWidget):
    def __init__(self, *, vm=None, title: str = "") -> None:
        super().__init__()
        self.vm = vm
        self.title = str(title or "")
        self.openRoleRequested = _SignalStub()


class _VmStub:
    def __init__(self) -> None:
        self.resolve_calls: list[str] = []
        self._payload_module_asset_key = ""
        self.updated_payloads: list[tuple[str, dict]] = []

    def get_meta_by_guid(self, guid: str):
        payload = {
            "imported": {
                "source": "1c",
                "origin": "CommonModules/АвтономнаяРабота.xml",
            }
        }
        if self._payload_module_asset_key:
            payload["module"] = {"asset_key": self._payload_module_asset_key}
        return {
            "guid": guid,
            "title": "АвтономнаяРабота",
            "payload": payload,
        }

    def resolve_module_asset_key_for_owner(self, owner_guid: str) -> str:
        self.resolve_calls.append(str(owner_guid or ""))
        return "module://resolved-common-module-guid"

    def update_object_payload(self, guid: str, patch: dict) -> bool:
        self.updated_payloads.append((str(guid or ""), dict(patch or {})))
        return True


class _EditorsStub(ConfiguratorEditorsMixin):
    def __init__(self, vm) -> None:
        self._vm = vm
        self.refreshRequested = _SignalStub()


class _MetaEditorVmStub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_meta_by_guid(self, guid: str):
        self.calls.append(str(guid or ""))
        return {
            "guid": guid,
            "title": "Reloaded Title",
            "name": "ReloadedName",
            "payload": {"value": 2},
        }


class _ConstantVmStub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_meta_by_guid(self, guid: str):
        self.calls.append(str(guid or ""))
        return {
            "guid": guid,
            "title": "Reloaded Constant",
            "payload": {
                "title": "Reloaded Constant",
                "constant": {
                    "synonym": "Syn",
                    "comment": "Comment",
                    "data_type": "boolean",
                    "length": 42,
                    "unlimited_length": True,
                },
            },
        }


class _MetaEditorStub(MetaObjectEditorBase):
    def __init__(self, **kwargs) -> None:
        self.rebuild_calls = 0
        self.load_calls = 0
        self.reload_calls = 0
        super().__init__(**kwargs)

    def _rebuild_model_from_payload(self, payload: dict) -> None:
        self.rebuild_calls += 1
        self.payload = dict(payload or {})

    def _load_to_ui(self) -> None:
        self.load_calls += 1

    def _build_sections(self) -> None:
        self._shell.set_sections(
            [
                EditorSection(
                    key="main",
                    title_i18n="obj.section.main",
                    build=lambda: QWidget(),
                )
            ]
        )

    def _reload_from_vm(self) -> None:
        self.reload_calls += 1
        super()._reload_from_vm()


class _CloseGuardWidget(QWidget):
    def __init__(self, result: bool) -> None:
        super().__init__()
        self.result = bool(result)
        self.calls = 0

    def confirm_close(self) -> bool:
        self.calls += 1
        return self.result


def test_mdi_subwindow_honors_editor_close_guard() -> None:
    app = QApplication.instance() or QApplication([])
    widget = _CloseGuardWidget(False)
    sub = _TimingMdiSubWindow(timing_key="module-guid", timing_title="Module")
    sub.setWidget(widget)
    event = QCloseEvent()

    sub.closeEvent(event)
    app.processEvents()

    assert widget.calls == 1
    assert not event.isAccepted()


def test_common_module_editor_resolves_module_asset_key_from_owner(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    editors = _EditorsStub(vm)

    monkeypatch.setattr("src.configurator.configurator_editors.CodeEditorWidget", _CodeEditorStub)

    widget = editors._create_editor_for_node(
        NodeInfo(
            kind="object",
            guid="owner-guid",
            name="АвтономнаяРабота",
            obj_type="common_module",
        )
    )
    app.processEvents()

    assert isinstance(widget, _CodeEditorStub)
    assert widget.asset_key == "module://resolved-common-module-guid"
    assert vm.resolve_calls == ["owner-guid"]


def test_common_module_editor_replaces_stale_manifest_guid_module_key(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    vm._payload_module_asset_key = "module://owner-guid"
    editors = _EditorsStub(vm)

    monkeypatch.setattr("src.configurator.configurator_editors.CodeEditorWidget", _CodeEditorStub)

    widget = editors._create_editor_for_node(
        NodeInfo(
            kind="object",
            guid="owner-guid",
            name="АвтономнаяРабота",
            obj_type="common_module",
        )
    )
    app.processEvents()

    assert isinstance(widget, _CodeEditorStub)
    assert widget.asset_key == "module://resolved-common-module-guid"
    assert vm.resolve_calls == ["owner-guid"]


def test_subsystem_editor_uses_profile_widget_instead_of_generic_structure(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    editors = _EditorsStub(vm)

    monkeypatch.setattr("src.configurator.configurator_editors.SubsystemEditorWidget", _SubsystemEditorStub)

    widget = editors._create_editor_for_node(
        NodeInfo(
            kind="object",
            guid="subsystem-guid",
            name="Продажі",
            obj_type="subsystem",
        )
    )
    app.processEvents()

    assert isinstance(widget, _SubsystemEditorStub)
    assert widget.obj_guid == "subsystem-guid"
    assert widget.title == "Продажі"


def test_register_editor_uses_profile_widget_instead_of_generic_structure(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    editors = _EditorsStub(vm)

    monkeypatch.setattr("src.configurator.configurator_editors.RegisterEditorWidget", _RegisterEditorStub)

    widget = editors._create_editor_for_node(
        NodeInfo(
            kind="object",
            guid="register-guid",
            name="Продажі",
            obj_type="register_info",
        )
    )
    app.processEvents()

    assert isinstance(widget, _RegisterEditorStub)
    assert widget.obj_guid == "register-guid"
    assert widget.obj_type == "register_info"
    assert widget.title == "Продажі"


def test_chart_of_accounts_uses_catalog_like_editor_instead_of_generic_structure(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    editors = _EditorsStub(vm)

    monkeypatch.setattr("src.configurator.configurator_editors.CatalogEditorWidget", _CatalogEditorStub)

    widget = editors._create_editor_for_node(
        NodeInfo(
            kind="object",
            guid="chart-guid",
            name="ПланСчетов1",
            obj_type="chart_of_accounts",
        )
    )
    app.processEvents()

    assert isinstance(widget, _CatalogEditorStub)
    assert widget.obj_guid == "chart-guid"
    assert widget.obj_type == "chart_of_accounts"
    assert widget.title == "ПланСчетов1"


def test_chart_of_characteristic_types_uses_catalog_like_editor_instead_of_generic_structure(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    editors = _EditorsStub(vm)

    monkeypatch.setattr("src.configurator.configurator_editors.CatalogEditorWidget", _CatalogEditorStub)

    widget = editors._create_editor_for_node(
        NodeInfo(
            kind="object",
            guid="chart-char-guid",
            name="ДополнительныеРеквизитыИСведения",
            obj_type="chart_of_characteristic_types",
        )
    )
    app.processEvents()

    assert isinstance(widget, _CatalogEditorStub)
    assert widget.obj_guid == "chart-char-guid"
    assert widget.obj_type == "chart_of_characteristic_types"
    assert widget.title == "ДополнительныеРеквизитыИСведения"


def test_meta_object_editor_base_reloads_from_vm_after_apply(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _MetaEditorVmStub()
    emitted: list[dict] = []

    monkeypatch.setattr(
        "src.ui_qt.widgets.meta_object_editor_base.QTimer.singleShot",
        lambda _ms, callback: callback(),
    )

    editor = _MetaEditorStub(title="Initial", payload={"value": 1}, vm=vm, obj_guid="obj-1", obj_type="catalog")
    editor.applyRequested.connect(emitted.append)
    app.processEvents()

    editor._shell._on_apply_clicked()
    app.processEvents()

    assert emitted == [{}]
    assert editor.reload_calls == 1
    assert vm.calls == ["obj-1"]
    assert editor._shell.title_text() == "ReloadedName"


def test_meta_object_editor_base_public_reload_alias() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _MetaEditorVmStub()
    editor = _MetaEditorStub(title="Initial", payload={"value": 1}, vm=vm, obj_guid="obj-1", obj_type="catalog")

    editor.reload_from_vm()

    assert editor.reload_calls == 1
    assert vm.calls == ["obj-1"]
    assert editor._shell.title_text() == "ReloadedName"
    assert app is not None


def test_meta_object_editor_keeps_pending_patch_when_runtime_save_fails() -> None:
    app = QApplication.instance() or QApplication([])

    class _FailingVm(_MetaEditorVmStub):
        def __init__(self) -> None:
            super().__init__()
            self.save_calls: list[tuple[str, dict, bool]] = []

        def save_object_payload_patch(self, guid: str, patch: dict, *, reload: bool = False) -> bool:
            self.save_calls.append((str(guid), dict(patch), bool(reload)))
            return False

    vm = _FailingVm()
    editor = _MetaEditorStub(title="Initial", payload={"value": 1}, vm=vm, obj_guid="obj-1", obj_type="catalog")
    editor._shell.set_pending_patch({"value": 2})

    assert editor.save() is False
    assert editor._shell.pending_patch() == {"value": 2}
    assert editor.reload_calls == 0
    assert vm.save_calls == [("obj-1", {"value": 2}, False)]
    assert app is not None


def test_configurator_editors_apply_helper_triggers_reload(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    editors = _EditorsStub(vm)
    reloaded: list[int] = []

    monkeypatch.setattr(
        "src.configurator.configurator_editors.QTimer.singleShot",
        lambda _ms, callback: callback(),
    )

    class _Widget(QWidget):
        def reload_from_vm(self) -> None:
            reloaded.append(1)

    widget = _Widget()
    editors._apply_object_patch_and_reload(widget, "guid-1", {"name": "Reload"})
    app.processEvents()

    assert vm.updated_payloads == [("guid-1", {"name": "Reload"})]
    assert reloaded == [1]
    assert editors.refreshRequested.calls == ["emit"]


def test_constant_properties_widget_reload_from_vm() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _ConstantVmStub()
    widget = ConstantPropertiesWidget(
        "Initial",
        payload={"title": "Initial", "constant": {"synonym": "", "comment": "", "data_type": "string", "length": 1}},
        vm=vm,
        obj_guid="const-1",
    )
    widget.reload_from_vm()
    app.processEvents()

    assert vm.calls == ["const-1"]
    assert widget.ed_title.text() == "Reloaded Constant"
    assert widget.ed_syn.text() == "Syn"
    assert widget.ed_comment.text() == "Comment"


def test_configurator_editors_form_designer_save_triggers_reload(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    editors = _EditorsStub(vm)
    reloaded: list[int] = []

    monkeypatch.setattr(
        "src.configurator.configurator_editors.QTimer.singleShot",
        lambda _ms, callback: callback(),
    )

    class _FormWidget(QWidget):
        def reload_from_vm(self) -> None:
            reloaded.append(1)

    widget = _FormWidget()
    editors._apply_object_patch_and_reload(widget, "form-guid", {"form_module": "test"})
    app.processEvents()

    assert vm.updated_payloads == [("form-guid", {"form_module": "test"})]
    assert reloaded == [1]


def test_enumeration_editor_uses_profile_widget_instead_of_generic_structure(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    editors = _EditorsStub(vm)

    monkeypatch.setattr("src.configurator.configurator_editors.EnumerationEditorWidget", _EnumerationEditorStub)

    widget = editors._create_editor_for_node(
        NodeInfo(
            kind="object",
            guid="enum-guid",
            name="Статуси",
            obj_type="enumeration",
        )
    )
    app.processEvents()

    assert isinstance(widget, _EnumerationEditorStub)
    assert widget.obj_guid == "enum-guid"
    assert widget.title == "Статуси"


def test_role_editor_uses_profile_widget_instead_of_generic_structure(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    editors = _EditorsStub(vm)

    monkeypatch.setattr("src.configurator.configurator_editors.RoleEditorWidget", _RoleEditorStub)

    widget = editors._create_editor_for_node(
        NodeInfo(
            kind="object",
            guid="role-guid",
            name="Администратор",
            obj_type="role",
        )
    )
    app.processEvents()

    assert isinstance(widget, _RoleEditorStub)
    assert widget.obj_guid == "role-guid"
    assert widget.title == "Администратор"


def test_scheduled_job_editor_uses_profile_widget_instead_of_generic_structure(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    editors = _EditorsStub(vm)

    monkeypatch.setattr("src.configurator.configurator_editors.ScheduledJobEditorWidget", _ScheduledJobEditorStub)

    widget = editors._create_editor_for_node(
        NodeInfo(
            kind="object",
            guid="job-guid",
            name="Синхронизация",
            obj_type="scheduled_job",
        )
    )
    app.processEvents()

    assert isinstance(widget, _ScheduledJobEditorStub)
    assert widget.obj_guid == "job-guid"
    assert widget.title == "Синхронизация"


def test_event_subscription_editor_uses_profile_widget_instead_of_generic_structure(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    editors = _EditorsStub(vm)

    monkeypatch.setattr("src.configurator.configurator_editors.EventSubscriptionEditorWidget", _EventSubscriptionEditorStub)

    widget = editors._create_editor_for_node(
        NodeInfo(
            kind="object",
            guid="subscr-guid",
            name="ПриЗаписи",
            obj_type="event_subscription",
        )
    )
    app.processEvents()

    assert isinstance(widget, _EventSubscriptionEditorStub)
    assert widget.obj_guid == "subscr-guid"
    assert widget.title == "ПриЗаписи"


def test_access_restrictions_projection_uses_dedicated_widget(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    vm = _VmStub()
    editors = _EditorsStub(vm)

    monkeypatch.setattr(
        "src.configurator.configurator_editors.AccessRestrictionsProjectionWidget",
        _AccessRestrictionsStub,
    )

    widget = editors._create_editor_for_node(
        NodeInfo(
            kind="object",
            guid="virtual:access_restrictions",
            name="Всі обмеження доступу",
            obj_type="access_restrictions",
        )
    )
    app.processEvents()

    assert isinstance(widget, _AccessRestrictionsStub)
    assert widget.vm is vm
    assert widget.title == "Всі обмеження доступу"
