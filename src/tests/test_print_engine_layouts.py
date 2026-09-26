from src.mpdb.mpdb import Mpdb
from src.runtime.print_engine import PrintEngine


def test_print_engine_renders_document_from_spreadsheet_layout(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "print_layout.mpdb"))
    db.create_table(
        "data_document_invoice",
        schema={
            "_guid": {"type": "str", "indexed": True},
            "_number": {"type": "str"},
            "_date": {"type": "str"},
            "Комментарий": {"type": "str"},
        },
    )
    db.table("data_document_invoice").insert(
        {
            "_guid": "doc-1",
            "_number": "INV-001",
            "_date": "2026-03-09",
            "Комментарий": "Тест",
        }
    )

    layout_model = {
        "schema_version": 1,
        "kind": "spreadsheet_document",
        "row_count": 2,
        "column_count": 2,
        "cells": [
            {"row": 0, "col": 0, "format_index": 0, "text": "Документ"},
            {"row": 0, "col": 1, "format_index": 0, "text": "[НомерДокумента]"},
            {"row": 1, "col": 0, "format_index": 1, "text": "Дата"},
            {"row": 1, "col": 1, "format_index": 1, "text": "[ДатаКоротко]"},
        ],
        "merges": [],
        "formats": [
            {"index": 0, "horizontalAlignment": "Center", "font": 0, "width": 120},
            {"index": 1, "horizontalAlignment": "Left", "font": 1, "width": 140},
        ],
        "fonts": [
            {"index": 0, "face_name": "Arial", "height": "10", "bold": True, "italic": False, "underline": False},
            {"index": 1, "face_name": "Arial", "height": "9", "bold": False, "italic": False, "underline": False},
        ],
    }
    manifest = [
        {"guid": "doc-guid", "type": "document", "name": "Invoice", "title": "Invoice", "kind": "object", "parent_guid": "", "payload": {}},
        {"guid": "layouts-folder", "type": "document", "name": "layouts", "title": "layouts", "kind": "folder", "parent_guid": "doc-guid", "payload": {}},
        {
            "guid": "layout-guid",
            "type": "layout",
            "name": "PF_MXL_Invoice",
            "title": "ПФ_MXL_Invoice",
            "kind": "object",
            "parent_guid": "layouts-folder",
            "payload": {
                "layout_kind": "spreadsheet_document",
                "layout_model": layout_model,
            },
        },
    ]

    html = PrintEngine(db, manifest).render_document("Invoice", "doc-1")

    assert "ПФ_MXL_Invoice" in html
    assert "INV-001" in html
    assert "09.03.2026" in html
    assert "mp-layout-table" in html


def test_print_engine_renders_named_areas_and_parameter_template_cells(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "print_layout_areas.mpdb"))
    db.create_table(
        "data_document_invoice",
        schema={
            "_guid": {"type": "str", "indexed": True},
            "_number": {"type": "str"},
            "_date": {"type": "str"},
        },
    )
    db.table("data_document_invoice").insert(
        {
            "_guid": "doc-1",
            "_number": "INV-001",
            "_date": "2026-03-09",
        }
    )

    layout_model = {
        "schema_version": 1,
        "kind": "spreadsheet_document",
        "row_count": 3,
        "column_count": 2,
        "cells": [
            {"row": 0, "col": 0, "format_index": 0, "text": "№ [НомерДок]"},
            {"row": 0, "col": 1, "format_index": 1, "parameter": "Сума"},
            {"row": 1, "col": 0, "format_index": 2, "text": "Не друкувати"},
            {"row": 2, "col": 0, "format_index": 0, "text": "Підпис [ПІБ]"},
        ],
        "merges": [],
        "named_areas": [
            {"name": "Шапка", "begin_row": 0, "end_row": 0, "begin_column": 0, "end_column": 1},
            {"name": "Підпис", "begin_row": 2, "end_row": 2, "begin_column": 0, "end_column": 0},
        ],
        "formats": [
            {"index": 0, "horizontalAlignment": "Left", "font": 0, "width": 100, "fillType": "Template"},
            {"index": 1, "horizontalAlignment": "Right", "font": 0, "width": 80, "fillType": "Parameter"},
            {"index": 2, "horizontalAlignment": "Left", "font": 0, "width": 80, "fillType": "Text"},
        ],
        "fonts": [
            {"index": 0, "face_name": "Arial", "height": "10", "bold": False, "italic": False, "underline": False},
        ],
    }
    manifest = [
        {"guid": "doc-guid", "type": "document", "name": "Invoice", "title": "Invoice", "kind": "object", "parent_guid": "", "payload": {}},
        {"guid": "layouts-folder", "type": "document", "name": "layouts", "title": "layouts", "kind": "folder", "parent_guid": "doc-guid", "payload": {}},
        {
            "guid": "layout-guid",
            "type": "layout",
            "name": "PF_MXL_Invoice",
            "title": "ПФ_MXL_Invoice",
            "kind": "object",
            "parent_guid": "layouts-folder",
            "payload": {
                "layout_kind": "spreadsheet_document",
                "layout_model": layout_model,
            },
        },
    ]

    engine = PrintEngine(db, manifest)
    html = engine.render_document(
        "Invoice",
        "doc-1",
        context_data={
            "LayoutAreas": ["Шапка"],
            "LayoutParams": {
                "НомерДок": "123456789",
                "Сума": "5000",
                "ПІБ": "Іваненко І.І.",
            },
        },
    )

    assert engine.get_layout_areas("PF_MXL_Invoice") == ["Шапка", "Підпис"]
    assert "№ 123456789" in html
    assert "5000" in html
    assert "Не друкувати" not in html
    assert "Підпис Іваненко І.І." not in html
