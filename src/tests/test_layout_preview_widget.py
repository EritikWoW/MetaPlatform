from pathlib import Path

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QScrollArea, QTabWidget, QTableWidgetSelectionRange

from src.ui_qt.widgets.layout_preview_widget import (
    LayoutPreviewWidget,
    _load_layout_model_from_workspace,
    _workspace_layout_candidate_paths,
)


class _LayoutModelAssetVmStub:
    def get_text_asset(self, asset_key: str) -> tuple[str, str, str]:
        if str(asset_key) == "manifest-payload/layout-guid/layout_model.json":
            return (
                """{"kind":"spreadsheet_document","row_count":1,"column_count":1,"formats":[{"index":0,"width":40,"height":20}],"fonts":[],"rows":[],"cells":[{"row":0,"col":0,"text":"Ref cell"}],"parameters":[],"merges":[],"named_areas":[],"column_sets":[]}""",
                "application/json",
                "manifest-payload/layout-guid/layout_model.json",
            )
        return "", "text/plain", str(asset_key)


def test_workspace_layout_candidate_paths_include_xmlconf_root(tmp_path, monkeypatch) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    rel = "Documents/Test/Templates/Layout/Ext/Template.xml"

    candidates = _workspace_layout_candidate_paths(rel)

    assert tmp_path / "XMLConf" / Path(rel) in candidates


def test_load_layout_model_from_workspace_reads_xmlconf_template(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rel = "Documents/Test/Templates/Layout/Ext/Template.xml"
    target = tmp_path / "XMLConf" / Path(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        b"""<?xml version='1.0' encoding='utf-8'?>
<document xmlns='http://v8.1c.ru/8.2/data/spreadsheet' xmlns:v8='http://v8.1c.ru/8.1/data/core'>
  <templateMode>false</templateMode>
  <defaultFormatIndex>0</defaultFormatIndex>
  <height>1</height>
  <columns>
    <id>cols</id>
    <size>1</size>
    <columnsItem>
      <index>0</index>
      <column>
        <formatIndex>0</formatIndex>
      </column>
    </columnsItem>
  </columns>
  <rowsItem>
    <index>0</index>
    <row>
      <formatIndex>0</formatIndex>
      <columnsID>cols</columnsID>
      <c>
        <c>
          <f>0</f>
          <tl>
            <item>
              <lang>uk</lang>
              <content>Hello</content>
            </item>
          </tl>
        </c>
      </c>
    </row>
  </rowsItem>
</document>"""
    )

    model = _load_layout_model_from_workspace(
        body_origin=rel,
        body_mime="application/xml",
    )

    assert model["kind"] == "spreadsheet_document"
    assert model["cells"][0]["text"] == "Hello"


def test_layout_preview_applies_range_formatting_and_persists_layout_model() -> None:
    app = QApplication.instance() or QApplication([])

    class _FakeVm:
        def __init__(self) -> None:
            self.saved: list[tuple[str, dict, bool]] = []

        def save_object_payload(self, guid: str, payload: dict, *, reload: bool = True) -> bool:
            self.saved.append((guid, dict(payload), bool(reload)))
            return True

    vm = _FakeVm()
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model": {
            "kind": "spreadsheet_document",
            "row_count": 2,
            "column_count": 2,
            "formats": [{"index": 0, "width": 40, "height": 20}],
            "fonts": [],
            "rows": [],
            "cells": [],
            "parameters": [],
            "merges": [],
            "named_areas": [],
            "column_sets": [],
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=vm, obj_guid="layout-guid")
    table = widget._table

    assert table is not None
    assert table.item(1, 1) is None
    for row in range(2):
        for col in range(2):
            idx = table.model().index(row, col)
            table.selectionModel().select(idx, QItemSelectionModel.SelectionFlag.Select)
    table.setCurrentCell(0, 0)
    widget._selected_anchors = lambda: [(0, 0), (0, 1), (1, 0), (1, 1)]  # type: ignore[method-assign]

    widget._on_cell_property_changed("fill_type", "Parameter")
    widget._on_cell_property_changed("border_style", "solid")
    widget._on_cell_property_changed("horizontal_alignment", "Center")
    widget._on_cell_property_changed("vertical_alignment", "Bottom")
    widget._on_cell_property_changed("font_bold", True)
    widget._on_cell_property_changed("font_underline", True)
    widget._on_cell_property_changed("font_height", 14)
    widget._flush_pending_save()

    expected = {(0, 0), (0, 1), (1, 0), (1, 1)}
    assert set(widget._sheet_cells) == expected
    assert widget.findChildren(QTabWidget) == []
    for anchor in expected:
        cell = widget._sheet_cells[anchor]
        assert cell["fill_type"] == "Parameter"
        assert cell["horizontal_alignment"] == "Center"
        assert cell["vertical_alignment"] == "Bottom"
        assert cell["font_bold"] is True
        assert cell["font_underline"] is True
        assert cell["font_height"] == 14
        assert cell["border"] == 1
        assert cell["top_border"] == 1
        assert cell["bottom_border"] == 1
        assert cell["left_border"] == 1
        assert cell["right_border"] == 1

    assert vm.saved
    guid, saved_payload, reload = vm.saved[-1]
    assert guid == "layout-guid"
    assert reload is False
    saved_cells = {
        (int(cell["row"]), int(cell["col"])): cell
        for cell in saved_payload["layout_model"]["cells"]
    }
    assert set(saved_cells) == expected
    assert saved_payload["layout_model"]["cells"][0]["fill_type"] == "Parameter"
    assert app is not None


def test_layout_preview_loads_layout_model_from_externalized_ref_when_direct_payload_is_missing() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model_ref": "manifest-payload/layout-guid/layout_model.json",
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=_LayoutModelAssetVmStub(), obj_guid="layout-guid")

    assert widget._layout_model["kind"] == "spreadsheet_document"
    assert widget._layout_model["cells"][0]["text"] == "Ref cell"
    assert app is not None


def test_layout_preview_reload_from_vm_rebuilds_preview_from_latest_payload() -> None:
    app = QApplication.instance() or QApplication([])

    class _FakeVm:
        def __init__(self) -> None:
            self.title = "Layout"
            self.payload = {
                "layout_kind": "spreadsheet_document",
                "layout_model": {
                    "kind": "spreadsheet_document",
                    "row_count": 1,
                    "column_count": 1,
                    "formats": [{"index": 0, "width": 40, "height": 20}],
                    "fonts": [],
                    "rows": [],
                    "cells": [{"row": 0, "col": 0, "text": "Initial"}],
                    "parameters": [],
                    "merges": [],
                    "named_areas": [],
                    "column_sets": [],
                },
            }

        def get_meta_by_guid(self, guid: str) -> dict:
            return {"guid": guid, "title": self.title, "payload": dict(self.payload)}

    vm = _FakeVm()
    widget = LayoutPreviewWidget(title="Layout", payload=dict(vm.payload), vm=vm, obj_guid="layout-guid")
    assert widget._table is not None
    assert widget._table.item(0, 0).text() == "Initial"

    vm.payload["layout_model"]["cells"][0]["text"] = "Updated"
    vm.title = "Updated Layout"
    widget.reload_from_vm()

    assert widget._table is not None
    assert widget._table.item(0, 0).text() == "Updated"
    assert widget._layout_model["cells"][0]["text"] == "Updated"
    assert widget._title_lbl.text() == "Updated Layout"
    assert app is not None


def test_layout_preview_shows_binary_excerpt_for_ole_template() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "layout_kind": "binary_ole_template",
        "layout_model": {
            "kind": "binary_ole_template",
            "size_bytes": 40,
            "container": "ole_compound",
            "signature": "D0 CF 11 E0 A1 B1 1A E1",
            "preview_head_ascii": "........OLE",
            "preview_head_hex": "D0 CF 11 E0 A1 B1 1A E1 00 00 4F 4C 45",
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=None, obj_guid="layout-guid")
    text = widget.findChild(QPlainTextEdit)

    assert text is not None
    plain = text.toPlainText()
    assert "template" in plain.lower()
    assert "D0 CF 11 E0 A1 B1 1A E1" in plain
    assert "ole_compound" in plain
    assert "ASCII" in plain or "ASCII" in plain.upper()
    assert app is not None


def test_layout_preview_context_focus_preserves_existing_multi_selection() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model": {
            "kind": "spreadsheet_document",
            "row_count": 2,
            "column_count": 2,
            "formats": [{"index": 0, "width": 40, "height": 20}],
            "fonts": [],
            "rows": [],
            "cells": [],
            "parameters": [],
            "merges": [],
            "named_areas": [],
            "column_sets": [],
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=None, obj_guid="layout-guid")
    table = widget._table

    assert table is not None
    sel_model = table.selectionModel()
    assert sel_model is not None
    for row, col in ((0, 0), (0, 1), (1, 0), (1, 1)):
        idx = table.model().index(row, col)
        sel_model.select(idx, QItemSelectionModel.SelectionFlag.Select)
    widget._focus_context_cell(1, 1)

    selected = {(idx.row(), idx.column()) for idx in table.selectedIndexes()}
    assert selected == {(0, 0), (0, 1), (1, 0), (1, 1)}
    assert (table.currentRow(), table.currentColumn()) == (1, 1)
    assert app is not None


def test_layout_preview_prepare_for_close_skips_save_when_clean_and_drops_table() -> None:
    app = QApplication.instance() or QApplication([])

    class _FakeVm:
        def __init__(self) -> None:
            self.saved: list[tuple[str, dict, bool]] = []

        def save_object_payload(self, guid: str, payload: dict, *, reload: bool = True) -> bool:
            self.saved.append((guid, dict(payload), bool(reload)))
            return True

    vm = _FakeVm()
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model": {
            "kind": "spreadsheet_document",
            "row_count": 1,
            "column_count": 1,
            "formats": [{"index": 0, "width": 40, "height": 20}],
            "fonts": [],
            "rows": [],
            "cells": [{"row": 0, "col": 0, "text": "x"}],
            "parameters": [],
            "merges": [],
            "named_areas": [],
            "column_sets": [],
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=vm, obj_guid="layout-guid")
    assert widget._table is not None

    widget.prepare_for_close()

    assert widget._table is None
    assert vm.saved == []
    assert app is not None


def test_layout_preview_prepare_for_close_flushes_dirty_layout_and_clears_dirty_flag() -> None:
    app = QApplication.instance() or QApplication([])

    class _FakeVm:
        def __init__(self) -> None:
            self.saved: list[tuple[str, dict, bool]] = []

        def save_object_payload(self, guid: str, payload: dict, *, reload: bool = True) -> bool:
            self.saved.append((guid, dict(payload), bool(reload)))
            return True

    vm = _FakeVm()
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model": {
            "kind": "spreadsheet_document",
            "row_count": 1,
            "column_count": 1,
            "formats": [{"index": 0, "width": 40, "height": 20}],
            "fonts": [],
            "rows": [],
            "cells": [{"row": 0, "col": 0, "text": "x"}],
            "parameters": [],
            "merges": [],
            "named_areas": [],
            "column_sets": [],
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=vm, obj_guid="layout-guid")
    assert widget._table is not None

    widget._layout_model["cells"][0]["text"] = "changed"
    widget._dirty = True
    assert widget._dirty is True
    widget.prepare_for_close()

    assert widget._table is None
    assert vm.saved
    assert vm.saved[-1][0] == "layout-guid"
    assert vm.saved[-1][2] is False
    assert widget._dirty is False
    assert app is not None


def test_layout_preview_flush_uses_asset_save_when_layout_ref_exists() -> None:
    app = QApplication.instance() or QApplication([])

    class _FakeVm:
        def __init__(self) -> None:
            self.saved: list[tuple[str, dict, bool]] = []
            self.asset_saved: list[tuple[str, dict, str, bool]] = []

        def save_object_payload(self, guid: str, payload: dict, *, reload: bool = True) -> bool:
            self.saved.append((guid, dict(payload), bool(reload)))
            return True

        def save_externalized_payload_asset(self, guid: str, payload: dict, *, key: str, reload: bool = False) -> bool:
            self.asset_saved.append((guid, dict(payload), str(key), bool(reload)))
            return True

    vm = _FakeVm()
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model_ref": "manifest-payload/layout-guid/layout_model.json",
        "layout_model": {
            "kind": "spreadsheet_document",
            "row_count": 1,
            "column_count": 1,
            "formats": [{"index": 0, "width": 40, "height": 20}],
            "fonts": [],
            "rows": [],
            "cells": [{"row": 0, "col": 0, "text": "x"}],
            "parameters": [],
            "merges": [],
            "named_areas": [],
            "column_sets": [],
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=vm, obj_guid="layout-guid")
    widget._layout_model["cells"][0]["text"] = "changed"
    widget._dirty = True

    widget._flush_pending_save()

    assert vm.saved == []
    assert vm.asset_saved
    guid, saved_payload, key, reload = vm.asset_saved[-1]
    assert guid == "layout-guid"
    assert key == "layout_model"
    assert reload is False
    assert saved_payload["layout_model_ref"].endswith("layout_model.json")
    assert widget._dirty is False
    assert app is not None


def test_layout_preview_flush_skips_when_layout_signature_matches_last_save() -> None:
    app = QApplication.instance() or QApplication([])

    class _FakeVm:
        def __init__(self) -> None:
            self.saved: list[tuple[str, dict, bool]] = []

        def save_object_payload(self, guid: str, payload: dict, *, reload: bool = True) -> bool:
            self.saved.append((guid, dict(payload), bool(reload)))
            return True

    vm = _FakeVm()
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model": {
            "kind": "spreadsheet_document",
            "row_count": 1,
            "column_count": 1,
            "formats": [{"index": 0, "width": 40, "height": 20}],
            "fonts": [],
            "rows": [],
            "cells": [{"row": 0, "col": 0, "text": "x"}],
            "parameters": [],
            "merges": [],
            "named_areas": [],
            "column_sets": [],
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=vm, obj_guid="layout-guid")
    widget._dirty = True

    widget._flush_pending_save(force=True)

    assert vm.saved == []
    assert widget._dirty is False
    assert app is not None


def test_layout_preview_merge_and_unmerge_selection_updates_layout_model() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model": {
            "kind": "spreadsheet_document",
            "row_count": 3,
            "column_count": 3,
            "formats": [{"index": 0, "width": 40, "height": 20}],
            "fonts": [],
            "rows": [],
            "cells": [],
            "parameters": [],
            "merges": [],
            "named_areas": [],
            "column_sets": [],
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=None, obj_guid="layout-guid")
    table = widget._table

    assert table is not None
    widget._selected_rect = lambda: (0, 0, 1, 1)  # type: ignore[method-assign]
    widget._merge_selected_cells()

    assert widget._layout_model["merges"] == [{"row": 0, "col": 0, "rowspan": 2, "colspan": 2}]
    assert table.rowSpan(0, 0) == 2
    assert table.columnSpan(0, 0) == 2

    widget._unmerge_selected_cells()

    assert widget._layout_model["merges"] == []
    assert table.rowSpan(0, 0) == 1
    assert table.columnSpan(0, 0) == 1
    assert app is not None


def test_layout_preview_assigns_goto_and_removes_named_area() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model": {
            "kind": "spreadsheet_document",
            "row_count": 3,
            "column_count": 3,
            "formats": [{"index": 0, "width": 40, "height": 20}],
            "fonts": [],
            "rows": [],
            "cells": [],
            "parameters": [],
            "merges": [],
            "named_areas": [],
            "column_sets": [],
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=None, obj_guid="layout-guid")
    table = widget._table

    assert table is not None
    assert widget._tool_area is not None
    table.setCurrentCell(0, 0)
    table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 1, 1), True)
    widget._set_area_editor_text("Шапка")
    widget._assign_selected_area()

    assert widget._layout_model["named_areas"] == [
        {
            "name": "Шапка",
            "type": "area",
            "begin_row": 0,
            "end_row": 1,
            "begin_column": 0,
            "end_column": 1,
        }
    ]

    widget._goto_selected_area()
    selected = {(idx.row(), idx.column()) for idx in table.selectedIndexes()}
    assert selected == {(0, 0), (0, 1), (1, 0), (1, 1)}

    widget._remove_selected_area()
    assert widget._layout_model["named_areas"] == []
    assert app is not None


def test_layout_preview_uses_widest_column_definition_from_all_column_sets() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model": {
            "kind": "spreadsheet_document",
            "row_count": 1,
            "column_count": 1,
            "formats": [{"index": 0, "width": 20, "height": 20}],
            "fonts": [],
            "rows": [],
            "cells": [{"row": 0, "col": 0, "text": "x"}],
            "parameters": [],
            "merges": [],
            "named_areas": [],
            "column_sets": [
                {"id": "a", "size": 1, "columns": [{"index": 0, "format_index": 0, "width": 20}]},
                {"id": "b", "size": 1, "columns": [{"index": 0, "format_index": 0, "width": 120}]},
            ],
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=None, obj_guid="layout-guid")

    assert widget._table is not None
    assert widget._table.columnWidth(0) == widget._sheet_width_to_px(120)
    assert app is not None


def test_layout_preview_properties_widget_has_scroll_body_and_pinned_footer() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model": {
            "kind": "spreadsheet_document",
            "row_count": 1,
            "column_count": 1,
            "formats": [{"index": 0, "width": 40, "height": 20}],
            "fonts": [],
            "rows": [],
            "cells": [{"row": 0, "col": 0, "text": "x"}],
            "parameters": [],
            "merges": [],
            "named_areas": [],
            "column_sets": [],
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=None, obj_guid="layout-guid")
    props = widget.properties_widget()

    assert props is not None
    assert props.findChildren(QScrollArea)
    help_boxes = [item for item in props.findChildren(QPlainTextEdit) if item.objectName() == "LayoutCellPropertiesHelp"]
    assert help_boxes
    assert app is not None


def test_layout_preview_switches_active_column_scheme_by_current_row() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model": {
            "kind": "spreadsheet_document",
            "row_count": 2,
            "column_count": 3,
            "formats": [{"index": 0, "width": 20, "height": 20}],
            "fonts": [],
            "rows": [
                {"index": 0, "columns_id": "wide", "height": 20},
                {"index": 1, "columns_id": "narrow", "height": 20},
            ],
            "cells": [
                {"row": 0, "col": 0, "text": "A"},
                {"row": 1, "col": 0, "text": "B"},
            ],
            "parameters": [],
            "merges": [],
            "named_areas": [],
            "column_sets": [
                {"id": "wide", "size": 3, "columns": [{"index": 0, "format_index": 0, "width": 120}]},
                {"id": "narrow", "size": 2, "columns": [{"index": 0, "format_index": 0, "width": 20}]},
            ],
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=None, obj_guid="layout-guid")
    table = widget._table

    assert table is not None
    table.setCurrentCell(0, 0)
    app.processEvents()
    wide_width = table.columnWidth(0)
    assert table.horizontalHeaderItem(2).text() == "3"

    table.setCurrentCell(1, 0)
    app.processEvents()
    narrow_width = table.columnWidth(0)

    assert wide_width > narrow_width
    assert table.horizontalHeaderItem(2).text() == ""
    assert app is not None


def test_layout_preview_shows_named_row_areas_in_vertical_headers() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "layout_kind": "spreadsheet_document",
        "layout_model": {
            "kind": "spreadsheet_document",
            "row_count": 3,
            "column_count": 1,
            "formats": [{"index": 0, "width": 40, "height": 20}],
            "fonts": [],
            "rows": [{"index": 0, "height": 20}, {"index": 1, "height": 20}, {"index": 2, "height": 20}],
            "cells": [{"row": 0, "col": 0, "text": "A"}],
            "parameters": [],
            "merges": [],
            "named_areas": [
                {
                    "name": "Заголовок",
                    "type": "Rows",
                    "begin_row": 0,
                    "end_row": 1,
                    "begin_column": -1,
                    "end_column": -1,
                    "columns_id": "",
                }
            ],
            "column_sets": [],
        },
    }
    widget = LayoutPreviewWidget(title="Layout", payload=payload, vm=None, obj_guid="layout-guid")
    table = widget._table

    assert table is not None
    assert table.verticalHeaderItem(0).text() == "Заголовок"
    assert table.verticalHeaderItem(0).toolTip() == "Заголовок"
    assert table.verticalHeaderItem(2).text() == "3"
    assert app is not None
