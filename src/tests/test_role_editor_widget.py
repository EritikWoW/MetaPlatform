from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ui_qt.widgets.simple_object_editor import RoleEditorWidget


def test_role_editor_widget_loads_and_collects_rights_payload() -> None:
    app = QApplication.instance() or QApplication([])
    emitted: list[dict] = []

    widget = RoleEditorWidget(
        title="АдминистраторСистемы",
        payload={
            "name": "АдминистраторСистемы",
            "rights": [
                {
                    "object": "Catalog.Products",
                    "rights": {"Read": True, "Update": False},
                    "restrictions": [{"right": "Read", "condition": "ГДЕ Истина"}],
                }
            ],
            "restriction_templates": [{"name": "ByValue", "condition": "ГДЕ Т.Склад = &Склад"}],
            "set_for_new_objects": False,
            "set_for_attributes_by_default": True,
            "independent_rights_of_child_objects": False,
        },
    )
    widget.applyRequested.connect(emitted.append)
    app.processEvents()

    assert widget._tabs.count() == 2
    assert widget._templates_model.rowCount() == 1

    widget._select_role_object_ref("Catalog.Products")
    app.processEvents()

    assert widget._current_object_ref == "Catalog.Products"
    rights_by_name = {
        str(widget._rights_list.item(index).data(Qt.ItemDataRole.UserRole) or ""): widget._rights_list.item(index)
        for index in range(widget._rights_list.count())
    }
    assert "Read" in rights_by_name
    assert rights_by_name["Read"].checkState() == Qt.CheckState.Checked

    rights_by_name["Update"].setCheckState(Qt.CheckState.Checked)
    widget._restrictions_model.item(0, 1).setText("ГДЕ НовыйОтбор")
    app.processEvents()
    widget._shell._on_apply_clicked()

    assert emitted
    patch = emitted[-1]
    assert patch["set_for_attributes_by_default"] is True
    assert patch["restriction_templates"][0]["name"] == "ByValue"
    role_entry = next(item for item in patch["rights"] if item["object"] == "Catalog.Products")
    assert role_entry["rights"]["Read"] is True
    assert role_entry["rights"]["Update"] is True
    assert role_entry["restrictions"][0]["condition"] == "ГДЕ НовыйОтбор"


def test_role_editor_widget_can_add_and_remove_restrictions() -> None:
    app = QApplication.instance() or QApplication([])

    widget = RoleEditorWidget(
        title="АдминистраторСистемы",
        payload={
            "name": "АдминистраторСистемы",
            "rights": [
                {
                    "object": "Catalog.Products",
                    "rights": {"Read": True, "Update": False},
                    "restrictions": [],
                }
            ],
        },
    )
    app.processEvents()

    widget._select_role_object_ref("Catalog.Products")
    app.processEvents()

    widget._add_restriction()
    app.processEvents()

    assert widget._restrictions_model.rowCount() == 1
    assert widget._restrictions_model.item(0, 0).data(Qt.ItemDataRole.UserRole) == "Read"

    widget._restrictions_model.item(0, 1).setText("ГДЕ Истина")
    app.processEvents()

    role_entry = next(item for item in widget._collect_rights() if item["object"] == "Catalog.Products")
    assert role_entry["restrictions"] == [{"right": "Read", "condition": "ГДЕ Истина"}]

    widget._restrictions_view.selectRow(0)
    widget._remove_restrictions()
    app.processEvents()

    role_entry = next(item for item in widget._collect_rights() if item["object"] == "Catalog.Products")
    assert role_entry["restrictions"] == []
