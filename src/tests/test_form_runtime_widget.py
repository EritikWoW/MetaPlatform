from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGroupBox, QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QTableView, QTabWidget, QToolButton, QWidget

from src.client.forms.form_runtime_widget import FormRuntimeWidget, ObjContext
from src.configurator.manifest_schema import ManifestObject
from src.ui_qt.widgets.form_designer_canvas import FORM_CONTROL_MIME
from src.ui_qt.widgets.form_designer_support import _DesignerRuntimeSurface
import pytest


@pytest.mark.parametrize("number_type,node_type,numeric", [("string", "NumberBox", False), ("number", "TextBox", True)])
def test_document_number_uses_metadata_not_imported_name_heuristics(number_type, node_type, numeric):
    from PySide6.QtWidgets import QDoubleSpinBox
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={"schema_version": 1, "root": {"id": "root", "type": "Container", "children": [
            {"id": "number", "type": node_type, "binding": "Number"}]}},
        ctx=ObjContext(obj_guid="doc", obj_type="document", form_kind="object_form"),
        manifest_rows=[{"guid": "doc", "payload": {"number_type": number_type}}],
    )
    value = 15 if numeric else "INV-000001"
    widget.set_record({"_number": value})
    assert isinstance(widget._bound_inputs["Number"], QDoubleSpinBox if numeric else QLineEdit)
    assert widget.collect()["_number"] == value
    widget.close()
    widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("timestamp", ["2015-11-03 14:07:02", "2015-11-03T14:07:02.123+03:00"])
def test_date_editor_preserves_imported_time_on_collection(timestamp):
    from PySide6.QtCore import QDate
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(model={"schema_version": 1, "root": {"id": "root", "type": "Container", "children": [
        {"id": "date", "type": "DateBox", "binding": "Date"}]}})
    widget.set_record({"_date": timestamp})
    date = widget._bound_inputs["Date"]
    assert date.date() == QDate(2015, 11, 3)
    assert widget.collect()["_date"] == timestamp
    date.setDate(QDate(2015, 11, 4))
    assert widget.collect()["_date"] == "2015-11-04" + timestamp[10:]
    widget._clear_bound_field("Date", date)
    assert widget.collect()["_date"] == ""
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_table_panel_registers_its_binding_for_commands():
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(model={"schema_version": 1, "root": {"id": "root", "type": "Container", "children": [
        {"id": "goods", "type": "TablePanel", "binding": "Goods", "props": {"columns": [{"name": "Quantity"}]}}]}})
    assert "Goods" in widget._tp_tables
    assert widget._tp_col_bindings["Goods"] == ["Quantity"]
    initial_rows = widget._tp_tables["Goods"].model().rowCount()
    widget._handle_tp_command("tp_add", "Goods")
    assert widget._tp_tables["Goods"].model().rowCount() == initial_rows + 1
    assert widget._record_value_for_binding({"_line_no": 3}, "LineNumber") == 3
    widget.close()
    widget.deleteLater()
    app.processEvents()


def _visibility_form_model() -> dict:
    return {
        "schema_version": 1,
        "id": "visibility-form",
        "name": "Form",
        "title": "Form",
        "root": {
            "id": "root",
            "type": "Container",
            "props": {"layout": "vertical"},
            "children": [
                {
                    "id": "hidden-field",
                    "type": "TextBox",
                    "title": "Hidden field",
                    "binding": "HiddenField",
                    "props": {"visible": False, "title_location": "left"},
                    "children": [],
                },
                {
                    "id": "visible-field",
                    "type": "TextBox",
                    "title": "Visible field",
                    "binding": "VisibleField",
                    "props": {"title_location": "left"},
                    "children": [],
                },
            ],
        },
    }


def test_form_runtime_widget_omits_client_hidden_control_and_caption() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(model=_visibility_form_model())
    widget.show()
    app.processEvents()

    edits = widget.findChildren(QLineEdit)
    labels = [label.text() for label in widget.findChildren(QLabel)]

    assert len(edits) == 1
    assert "VisibleField" in widget._bound_inputs
    assert "HiddenField" not in widget._bound_inputs
    assert any(text.startswith("Visible field") for text in labels)
    assert not any(text.startswith("Hidden field") for text in labels)


def test_designer_runtime_surface_keeps_client_hidden_control_editable() -> None:
    app = QApplication.instance() or QApplication([])
    surface = _DesignerRuntimeSurface(model=_visibility_form_model())
    surface.show()
    app.processEvents()

    hidden_wrap = surface.widget_for_node("hidden-field")

    assert len(surface.findChildren(QLineEdit)) == 2
    assert hidden_wrap is not None
    assert hidden_wrap.isVisible()
    assert hidden_wrap.property("form_hidden_in_client") is True


def test_form_runtime_widget_keeps_empty_label_decoration_as_invisible_layout_spacer() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "decoration-form",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "horizontal"},
                "children": [
                    {
                        "id": "spacer",
                        "type": "Label",
                        "name": "Decoration1",
                        "title": "",
                        "props": {
                            "is_decoration": True,
                            "decoration_kind": "label",
                            "layout_spacer": True,
                            "width_chars": 3,
                        },
                        "children": [],
                    }
                ],
            },
        }
    )
    widget.show()
    app.processEvents()

    decorations = [label for label in widget.findChildren(QLabel) if label.property("mp_form_decoration")]

    assert len(decorations) == 1
    assert decorations[0].text() == ""
    assert decorations[0].property("mp_form_decoration_spacer") is True
    assert decorations[0].minimumWidth() > 0
    assert all(label.text() != "Decoration1" for label in widget.findChildren(QLabel))


def test_form_runtime_widget_renders_non_empty_label_decoration_title() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "decoration-form",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "caption",
                        "type": "Label",
                        "name": "TechnicalName",
                        "title": "Visible title",
                        "props": {"is_decoration": True, "decoration_kind": "label"},
                        "children": [],
                    }
                ],
            },
        }
    )
    widget.show()
    app.processEvents()

    decorations = [label for label in widget.findChildren(QLabel) if label.property("mp_form_decoration")]

    assert len(decorations) == 1
    assert decorations[0].text() == "Visible title"
    assert decorations[0].property("mp_form_decoration_spacer") is False


def test_form_runtime_widget_uses_layout_only_groups_and_external_labels() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "f1",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "g1",
                        "type": "Container",
                        "title": "Header",
                        "props": {
                            "layout": "vertical",
                            "representation": "None",
                            "show_title": False,
                        },
                        "children": [
                            {
                                "id": "f_org",
                                "type": "TextBox",
                                "title": "Organization",
                                "binding": "Organization",
                                "props": {
                                    "width_chars": 30,
                                    "title_location": "Left",
                                },
                            }
                        ],
                    }
                ],
            },
        }
    )
    app.processEvents()

    assert widget.findChildren(QGroupBox) == []
    line = widget.findChild(QLineEdit)
    assert line is not None
    assert line.placeholderText() == ""
    assert line.maximumWidth() >= 200 or line.width() >= 200
    labels = [lab.text() for lab in widget.findChildren(QLabel)]
    assert any(text.startswith("Organization") for text in labels)

    org_label = next(lab for lab in widget.findChildren(QLabel) if lab.text().startswith("Organization"))
    assert org_label.alignment() & Qt.AlignmentFlag.AlignLeft

    root_widget = widget._host_l.itemAt(0).widget()
    assert root_widget is not None
    group_widget = root_widget.layout().itemAt(0).widget()
    assert group_widget is not None
    group_layout = group_widget.layout()
    assert group_layout is not None
    label_item = group_layout.itemAtPosition(0, 0)
    field_item = group_layout.itemAtPosition(0, 1)
    assert label_item is not None
    assert field_item is not None
    assert isinstance(label_item.widget(), QLabel)
    assert isinstance(field_item.widget(), QLineEdit)
    assert line.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding


def test_form_runtime_widget_does_not_render_groupbox_for_title_only_container() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "f2",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "g1",
                        "type": "Container",
                        "title": "Header",
                        "props": {"layout": "vertical"},
                        "children": [
                            {
                                "id": "f_org",
                                "type": "TextBox",
                                "title": "Organization",
                                "binding": "Organization",
                                "props": {"width_chars": 30, "title_location": "Left"},
                            }
                        ],
                    }
                ],
            },
        }
    )
    app.processEvents()

    assert widget.findChildren(QGroupBox) == []


def test_form_runtime_widget_renders_picture_decoration_placeholder() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "picture-form",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "picture-1",
                        "type": "Picture",
                        "title": "Company logo",
                        "props": {},
                    }
                ],
            },
        }
    )
    app.processEvents()

    pictures = [
        label for label in widget.findChildren(QLabel)
        if bool(label.property("mp_form_picture"))
    ]
    assert len(pictures) == 1
    assert pictures[0].text() == "Company logo"
    assert pictures[0].property("mp_form_picture_empty") is True


def test_form_runtime_widget_renders_groupbox_for_titled_container_with_visible_title() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "f2b",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "g1",
                        "type": "Container",
                        "title": "Header",
                        "props": {
                            "layout": "vertical",
                            "representation": "usual",
                            "show_title": True,
                        },
                        "children": [
                            {
                                "id": "f_org",
                                "type": "TextBox",
                                "title": "Organization",
                                "binding": "Organization",
                                "props": {"width_chars": 30, "title_location": "Left"},
                            }
                        ],
                    }
                ],
            },
        }
    )
    widget.show()
    app.processEvents()

    groups = widget.findChildren(QGroupBox)
    assert len(groups) == 1
    assert groups[0].title() == "Header"


def test_form_runtime_widget_aligns_input_column_to_longest_left_title() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "f3",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "g1",
                        "type": "Container",
                        "title": "Header",
                        "props": {"layout": "vertical", "representation": "None", "show_title": False},
                        "children": [
                            {
                                "id": "f_short",
                                "type": "TextBox",
                                "title": "N",
                                "binding": "N",
                                "props": {"title_location": "Left"},
                            },
                            {
                                "id": "f_long",
                                "type": "TextBox",
                                "title": "Very long title",
                                "binding": "Long",
                                "props": {"title_location": "Left"},
                            },
                            {
                                "id": "tbl_rows",
                                "type": "Table",
                                "title": "Rows",
                                "binding": "Rows",
                                "props": {"title_location": "Left", "columns": ["A", "B"]},
                            },
                        ],
                    }
                ],
            },
        }
    )
    widget.resize(800, 500)
    widget.show()
    app.processEvents()

    root_widget = widget._host_l.itemAt(0).widget()
    assert root_widget is not None
    group_widget = root_widget.layout().itemAt(0).widget()
    assert group_widget is not None
    group_layout = group_widget.layout()
    assert group_layout is not None

    short_field = group_layout.itemAtPosition(0, 1).widget()
    long_field = group_layout.itemAtPosition(1, 1).widget()
    title_widget = group_layout.itemAtPosition(2, 0).widget()
    table_widget = group_layout.itemAtPosition(3, 0).widget()
    assert isinstance(short_field, QLineEdit)
    assert isinstance(long_field, QLineEdit)
    assert isinstance(title_widget, QLabel)
    assert table_widget is not None
    assert short_field.geometry().x() == long_field.geometry().x()
    assert table_widget.sizePolicy().horizontalPolicy() == table_widget.sizePolicy().Policy.Expanding


def test_form_runtime_widget_renders_field_action_buttons_from_props() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "f4",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "f_ref",
                        "type": "TextBox",
                        "title": "Organization",
                        "binding": "Organization",
                        "props": {"title_location": "Left", "open_button": True, "choice_button": True},
                    }
                ],
            },
        }
    )
    widget.show()
    app.processEvents()

    buttons = widget.findChildren(QToolButton)
    assert [btn.property("mp_action_kind") for btn in buttons] == ["choice", "open"]
    assert all(not btn.icon().isNull() for btn in buttons)


def test_form_runtime_widget_infers_ref_action_button_from_manifest_schema() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "f5",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "f_org",
                        "type": "TextBox",
                        "title": "Organization",
                        "binding": "Organization",
                        "props": {"title_location": "Left"},
                    }
                ],
            },
        },
        manifest_rows=[
            {
                "guid": "doc-guid",
                "payload": {
                    "requisites": [
                        {"name": "Organization", "type": "ref", "ref_name": "Catalog.Organizations"},
                    ]
                },
            }
        ],
        ctx=ObjContext(obj_guid="doc-guid", obj_type="document", obj_name="AdvanceReport", form_kind="object_form"),
    )
    widget.show()
    app.processEvents()

    buttons = widget.findChildren(QToolButton)
    assert [btn.property("mp_action_kind") for btn in buttons] == ["choice", "clear", "open"]
    assert all(not btn.icon().isNull() for btn in buttons)
    host = next(item for item in widget.findChildren(QWidget) if item.property("mp_form_inline_actions"))
    assert host.layout().spacing() == 0

    widget.set_record({"Organization": "Acme", "Organization_guid": "record-guid"})
    opened = []
    widget.reference_open_requested.connect(lambda ref, guid: opened.append((ref, guid)))
    next(btn for btn in buttons if btn.property("mp_action_kind") == "open").click()
    assert opened == [("Catalog.Organizations", "record-guid")]
    next(btn for btn in buttons if btn.property("mp_action_kind") == "clear").click()
    assert widget.collect().get("Organization") == ""
    assert "Organization_guid" not in widget.collect()


def test_form_runtime_widget_accepts_manifest_object_rows_for_ref_detection() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "f5b",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "f_org",
                        "type": "TextBox",
                        "title": "Organization",
                        "binding": "Organization",
                        "props": {"title_location": "Left"},
                    }
                ],
            },
        },
        manifest_rows=[
            ManifestObject(
                guid="doc-guid",
                type="document",
                name="AdvanceReport",
                title="Advance Report",
                kind="object",
                parent_guid="",
                payload={
                    "requisites": [
                        {"name": "Organization", "type": "ref", "ref_name": "Catalog.Organizations"},
                    ]
                },
            )
        ],
        ctx=ObjContext(obj_guid="doc-guid", obj_type="document", obj_name="AdvanceReport", form_kind="object_form"),
    )
    widget.show()
    app.processEvents()

    buttons = widget.findChildren(QToolButton)
    assert [btn.property("mp_action_kind") for btn in buttons] == ["choice", "clear", "open"]


def test_form_runtime_widget_date_field_has_integrated_clear_action() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "date-actions",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "date",
                        "type": "DateBox",
                        "title": "Date",
                        "binding": "Date",
                        "props": {"title_location": "Left"},
                    }
                ],
            },
        }
    )
    widget.show()
    app.processEvents()

    buttons = widget.findChildren(QToolButton)
    assert [btn.property("mp_action_kind") for btn in buttons] == ["clear"]
    widget.set_record({"_date": "2026-07-22"})
    buttons[0].click()
    assert widget.collect()["_date"] == ""


def test_form_runtime_widget_explicitly_disables_inferred_reference_actions() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "disabled-ref-actions",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "organization",
                        "type": "TextBox",
                        "title": "Organization",
                        "binding": "Organization",
                        "props": {
                            "choice_button": False,
                            "clear_button": False,
                            "open_button": False,
                        },
                    }
                ],
            },
        },
        manifest_rows=[
            {
                "guid": "doc-guid",
                "payload": {
                    "requisites": [
                        {"name": "Organization", "type": "ref", "ref_name": "Catalog.Organizations"},
                    ]
                },
            }
        ],
        ctx=ObjContext(obj_guid="doc-guid", obj_type="document", obj_name="AdvanceReport"),
    )
    widget.show()
    app.processEvents()

    assert widget.findChildren(QToolButton) == []


def test_form_runtime_widget_table_stretches_main_column_and_keeps_aux_columns_compact() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "f6",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "tp_rows",
                        "type": "TablePanel",
                        "title": "Rows",
                        "binding": "Rows",
                        "props": {
                            "columns": [
                                {"name": "LineNo", "title": "N"},
                                {"name": "Doc", "title": "Документ аванса"},
                                {"name": "Amount", "title": "Сумма"},
                            ]
                        },
                    }
                ],
            },
        }
    )
    widget.resize(900, 520)
    widget.show()
    app.processEvents()

    table = widget.findChild(QTableView)
    assert table is not None
    header = table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.ResizeToContents
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(2) == QHeaderView.ResizeMode.ResizeToContents


def test_form_runtime_widget_list_table_panel_uses_list_data_path() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [{
                    "id": "items",
                    "type": "TablePanel",
                    "title": "Items",
                    "binding": "items",
                    "props": {"columns": [
                        {"name": "Number", "title": "Number"},
                        {"name": "Date", "title": "Date"},
                    ]},
                }],
            },
        },
        ctx=ObjContext(
            obj_type="document",
            obj_name="Sales",
            form_kind="list_form",
        ),
    )
    widget.show()
    app.processEvents()

    assert widget._list_table is not None
    assert widget._tp_tables == {}
    assert widget._list_col_bindings == ["Number", "Date"]
    assert widget._list_table.model().columnCount() == 2


def test_form_runtime_widget_plain_table_uses_top_title_mode_not_left_label_mode() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "f7",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "tbl_rows",
                        "type": "Table",
                        "title": "ПолученныеАвансы",
                        "binding": "Rows",
                        "props": {
                            "title_location": "Left",
                            "columns": [
                                {"name": "Doc", "title": "Документ"},
                                {"name": "Amount", "title": "Сумма"},
                            ],
                        },
                    }
                ],
            },
        }
    )
    widget.resize(900, 520)
    widget.show()
    app.processEvents()

    root_widget = widget._host_l.itemAt(0).widget()
    assert root_widget is not None
    root_layout = root_widget.layout()
    assert root_layout is not None
    title_item = root_layout.itemAtPosition(0, 0)
    table_item = root_layout.itemAtPosition(1, 0)
    assert title_item is not None
    assert table_item is not None
    assert isinstance(title_item.widget(), QLabel)
    assert isinstance(table_item.widget(), QTableView)


def test_form_runtime_widget_marks_standalone_buttons_with_own_skin_property() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "f8",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "btn_rows",
                        "type": "Button",
                        "title": "qwe",
                        "props": {},
                    }
                ],
            },
        }
    )
    widget.show()
    app.processEvents()

    buttons = [btn for btn in widget.findChildren(QPushButton) if btn.text() == "qwe"]
    assert buttons
    assert buttons[0].property("mp_form_standalone_button") is True


def test_designer_runtime_surface_allows_tabbing_between_pages() -> None:
    app = QApplication.instance() or QApplication([])
    surface = _DesignerRuntimeSurface(
        model={
            "schema_version": 1,
            "id": "f9",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "tabs-1",
                        "type": "Tabs",
                        "title": "Pages",
                        "props": {"pages_representation": "TabsOnTop"},
                        "children": [
                            {
                                "id": "page-1",
                                "type": "Container",
                                "title": "Page 1",
                                "props": {"layout": "vertical"},
                                "children": [
                                    {
                                        "id": "lbl-1",
                                        "type": "Label",
                                        "title": "First",
                                        "props": {},
                                    }
                                ],
                            },
                            {
                                "id": "page-2",
                                "type": "Container",
                                "title": "Page 2",
                                "props": {"layout": "vertical"},
                                "children": [
                                    {
                                        "id": "lbl-2",
                                        "type": "Label",
                                        "title": "Second",
                                        "props": {},
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
        }
    )
    surface.show()
    app.processEvents()

    tabs = surface.findChild(QTabWidget)
    assert tabs is not None
    tab_bar = tabs.tabBar()
    assert tab_bar is not None
    assert tabs.currentIndex() == 0

    QTest.mouseClick(tab_bar, Qt.MouseButton.LeftButton, pos=tab_bar.tabRect(1).center())
    app.processEvents()

    assert tabs.currentIndex() == 1


def test_designer_runtime_surface_emits_add_control_on_drop() -> None:
    app = QApplication.instance() or QApplication([])
    surface = _DesignerRuntimeSurface(
        model={
            "schema_version": 1,
            "id": "f10",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "group-1",
                        "type": "Container",
                        "title": "Block",
                        "props": {"layout": "vertical"},
                        "children": [],
                    }
                ],
            },
        }
    )
    surface.show()
    app.processEvents()

    received: list[tuple[str, str, int, int]] = []
    surface.addControlRequested.connect(lambda control_type, parent_id, x, y: received.append((control_type, parent_id, x, y)))

    target = surface.widget_for_node("group-1")
    assert target is not None

    mime = QMimeData()
    mime.setData(FORM_CONTROL_MIME, b"TextBox")
    event = QDropEvent(
        QPointF(16.0, 24.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    handled = surface.eventFilter(target, event)
    app.processEvents()

    assert handled is True
    assert received == [("TextBox", "group-1", 0, 0)]


def test_form_runtime_narrow_viewport_does_not_scroll_wide_field_horizontally() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "narrow-form",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "wide-field",
                        "type": "TextBox",
                        "title": "Long field title " * 8,
                        "binding": "WideField",
                        "props": {"width_chars": 200, "title_location": "left"},
                        "children": [],
                    }
                ],
            },
        }
    )
    widget.resize(320, 240)
    widget.show()
    app.processEvents()

    scroll = widget._form_scroll
    field = widget.findChild(QLineEdit)
    assert isinstance(scroll, QScrollArea)
    assert field is not None
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert scroll.horizontalScrollBar().maximum() == 0
    assert field.mapTo(scroll.viewport(), field.rect().topRight()).x() < scroll.viewport().width()


def test_form_runtime_absolute_controls_are_scaled_inside_narrow_viewport() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormRuntimeWidget(
        model={
            "schema_version": 1,
            "id": "absolute-form",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "absolute", "w": 1000, "h": 400},
                "children": [
                    {
                        "id": "right-field",
                        "type": "TextBox",
                        "title": "Field",
                        "binding": "RightField",
                        "props": {
                            "x": 900,
                            "y": 12,
                            "w": 300,
                            "h": 32,
                            "width_chars": 200,
                            "title_location": "none",
                        },
                        "children": [],
                    }
                ],
            },
        }
    )
    widget.resize(320, 240)
    widget.show()
    app.processEvents()

    scroll = widget._form_scroll
    field = widget.findChild(QLineEdit)
    assert isinstance(scroll, QScrollArea)
    assert field is not None
    assert scroll.horizontalScrollBar().maximum() == 0
    assert field.mapTo(scroll.viewport(), field.rect().topRight()).x() < scroll.viewport().width()
