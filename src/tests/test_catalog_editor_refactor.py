from PySide6.QtWidgets import QApplication

from src.configurator.manifest_schema import ManifestObject
from src.ui_qt.widgets.catalog_editor import (
    CatalogEditorWidget,
    CatalogPayload,
    _parse_subsystems,
)


def test_catalog_editor_shim_exports_payload_helpers() -> None:
    assert _parse_subsystems("a;b, c") == ["a", "b", "c"]
    model = CatalogPayload.from_payload({"name": "Partners", "subsystems": "s1 s2"})
    assert model.name == "Partners"
    assert model.subsystems == ["s1", "s2"]


def test_catalog_editor_load_to_ui_refreshes_child_lists() -> None:
    app = QApplication.instance() or QApplication([])

    class VmStub:
        def __init__(self, objs):
            self._objs = list(objs)

        def list_objects(self):
            return list(self._objs)

        def list_subsystems(self):
            return []

        def create_object_quick(self, *args, **kwargs):
            return ""

        def request_open_new(self, *args, **kwargs):
            return None

        def on_open(self, *args, **kwargs):
            return None

        def get_meta_by_guid(self, guid):
            for obj in self._objs:
                if str(getattr(obj, "guid", "")) == str(guid):
                    return {
                        "guid": obj.guid,
                        "name": obj.name,
                        "title": obj.title,
                        "type": obj.type,
                        "payload": obj.payload,
                    }
            return None

        def delete_object(self, *args, **kwargs):
            return False

    owner_guid = "catalog-guid"
    forms_guid = "forms-guid"
    commands_guid = "commands-guid"
    layouts_guid = "layouts-guid"
    objs = [
        ManifestObject(
            guid=owner_guid,
            parent_guid="",
            type="catalog",
            name="Partners",
            title="Контрагенти",
            kind="object",
            payload={},
        ),
        ManifestObject(
            guid=forms_guid,
            parent_guid=owner_guid,
            type="catalog",
            name="forms",
            title="forms",
            kind="folder",
            payload={"system": True},
        ),
        ManifestObject(
            guid=commands_guid,
            parent_guid=owner_guid,
            type="catalog",
            name="commands",
            title="commands",
            kind="folder",
            payload={"system": True},
        ),
        ManifestObject(
            guid=layouts_guid,
            parent_guid=owner_guid,
            type="catalog",
            name="layouts",
            title="layouts",
            kind="folder",
            payload={"system": True},
        ),
        ManifestObject(
            guid="form-guid",
            parent_guid=forms_guid,
            type="form",
            name="ObjectForm",
            title="ФормаЕлемента",
            kind="object",
            payload={},
        ),
        ManifestObject(
            guid="command-guid",
            parent_guid=commands_guid,
            type="command",
            name="Command1",
            title="Команда1",
            kind="object",
            payload={},
        ),
        ManifestObject(
            guid="layout-guid",
            parent_guid=layouts_guid,
            type="layout",
            name="Layout1",
            title="Макет1",
            kind="object",
            payload={},
        ),
    ]

    widget = CatalogEditorWidget(
        "Контрагенти",
        payload={"name": "Partners"},
        vm=VmStub(objs),
        obj_guid=owner_guid,
        available_subsystems=[],
    )

    widget.lst_forms.clear()
    widget.lst_commands.clear()
    widget.lst_layouts.clear()

    widget._load_to_ui()
    app.processEvents()

    assert widget.lst_forms.count() == 1
    assert widget.lst_commands.count() == 1
    assert widget.lst_layouts.count() == 1


def test_catalog_editor_opens_existing_child_with_reuse_path() -> None:
    app = QApplication.instance() or QApplication([])

    class VmStub:
        def __init__(self, objs):
            self._objs = list(objs)
            self.open_calls = []
            self.new_calls = []

        def list_objects(self):
            return list(self._objs)

        def list_subsystems(self):
            return []

        def create_object_quick(self, *args, **kwargs):
            return ""

        def request_open_new(self, info):
            self.new_calls.append(info)

        def on_open(self, info):
            self.open_calls.append(info)

        def get_meta_by_guid(self, guid):
            for obj in self._objs:
                if str(getattr(obj, "guid", "")) == str(guid):
                    return {
                        "guid": obj.guid,
                        "name": obj.name,
                        "title": obj.title,
                        "type": obj.type,
                        "payload": obj.payload,
                    }
            return None

        def delete_object(self, *args, **kwargs):
            return False

    owner_guid = "catalog-guid"
    forms_guid = "forms-guid"
    objs = [
        ManifestObject(
            guid=owner_guid,
            parent_guid="",
            type="catalog",
            name="Partners",
            title="Контрагенти",
            kind="object",
            payload={},
        ),
        ManifestObject(
            guid=forms_guid,
            parent_guid=owner_guid,
            type="catalog",
            name="forms",
            title="forms",
            kind="folder",
            payload={"system": True},
        ),
        ManifestObject(
            guid="form-guid",
            parent_guid=forms_guid,
            type="form",
            name="ObjectForm",
            title="ФормаЕлемента",
            kind="object",
            payload={},
        ),
    ]

    vm = VmStub(objs)
    widget = CatalogEditorWidget(
        "Контрагенти",
        payload={"name": "Partners"},
        vm=vm,
        obj_guid=owner_guid,
        available_subsystems=[],
    )
    widget.lst_forms.setCurrentRow(0)
    widget._on_open_selected_form()
    app.processEvents()

    assert len(vm.open_calls) == 1
    assert len(vm.new_calls) == 0
    assert vm.open_calls[0].guid == "form-guid"
