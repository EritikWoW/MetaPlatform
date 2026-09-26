from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _tag_name(tag: str) -> str:
    return str(tag or "").split("}")[-1]


def _child_text(parent: ET.Element | None, name: str, default: str = "") -> str:
    if parent is None:
        return default
    child = parent.find(f"./{{*}}{name}")
    if child is None or child.text is None:
        return default
    return str(child.text).strip()


def _int_text(parent: ET.Element | None, name: str, default: int = 0) -> int:
    try:
        return int(float(_child_text(parent, name, str(default)) or default))
    except Exception:
        return int(default)


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin1"):
        try:
            return (data or b"").decode(enc)
        except Exception:
            continue
    return (data or b"").decode("utf-8", errors="replace")


def _binary_preview_excerpt(data: bytes, *, limit: int = 192) -> Dict[str, str]:
    head = bytes(data or b"")[: max(0, int(limit))]
    hex_pairs = [f"{byte:02X}" for byte in head]
    hex_lines = [" ".join(hex_pairs[i : i + 16]) for i in range(0, len(hex_pairs), 16)]
    ascii_line = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in head)
    return {
        "head_hex": "\n".join(hex_lines),
        "head_ascii": ascii_line,
        "signature_hex": " ".join(f"{byte:02X}" for byte in head[:8]),
    }


def _local_string_value(node: ET.Element | None) -> str:
    if node is None:
        return ""

    values: list[tuple[str, str]] = []
    for item in node.findall(".//{*}item"):
        lang = _child_text(item, "lang", "")
        content = _child_text(item, "content", "")
        values.append((lang.lower(), content))

    if not values:
        return (node.text or "").strip()

    for preferred in ("uk", "en"):
        for lang, content in values:
            if lang == preferred and content:
                return content

    for _lang, content in values:
        if content:
            return content
    return ""


def _parse_font(node: ET.Element, index: int) -> Dict[str, Any]:
    return {
        "index": int(index),
        "face_name": str(node.attrib.get("faceName") or "").strip(),
        "height": str(node.attrib.get("height") or "").strip(),
        "bold": str(node.attrib.get("bold") or "").strip().lower() == "true",
        "italic": str(node.attrib.get("italic") or "").strip().lower() == "true",
        "underline": str(node.attrib.get("underline") or "").strip().lower() == "true",
    }


def _parse_format(node: ET.Element, index: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"index": int(index)}
    for child in list(node):
        name = _tag_name(child.tag)
        text = (child.text or "").strip()
        if not text:
            continue
        if name in {"font", "width", "height", "border", "topBorder", "bottomBorder", "leftBorder", "rightBorder"}:
            try:
                out[name] = int(float(text))
            except Exception:
                out[name] = text
        else:
            out[name] = text
    return out


def _column_width_from_format(formats: list[Dict[str, Any]], format_index: int) -> int:
    if 0 <= int(format_index) < len(formats):
        raw = formats[int(format_index)].get("width")
        try:
            return int(raw)
        except Exception:
            return 80
    return 80


def _row_height_from_format(formats: list[Dict[str, Any]], format_index: int) -> int:
    if 0 <= int(format_index) < len(formats):
        raw = formats[int(format_index)].get("height")
        try:
            return int(raw)
        except Exception:
            return 22
    return 22


def _parse_spreadsheet_document(root: ET.Element, *, origin: str = "") -> Dict[str, Any]:
    formats = [_parse_format(node, idx) for idx, node in enumerate(root.findall("./{*}format"))]
    fonts = [_parse_font(node, idx) for idx, node in enumerate(root.findall("./{*}font"))]

    column_sets: list[Dict[str, Any]] = []
    max_columns = 0
    for node in root.findall("./{*}columns"):
        block: Dict[str, Any] = {
            "id": _child_text(node, "id", ""),
            "size": _int_text(node, "size", 0),
            "columns": [],
        }
        for item in node.findall("./{*}columnsItem"):
            col_index = _int_text(item, "index", 0)
            col = item.find("./{*}column")
            format_index = _int_text(col, "formatIndex", -1)
            block["columns"].append(
                {
                    "index": int(col_index),
                    "format_index": int(format_index),
                    "width": _column_width_from_format(formats, format_index),
                }
            )
        max_columns = max(max_columns, int(block["size"] or 0), len(block["columns"]))
        column_sets.append(block)

    rows: list[Dict[str, Any]] = []
    cells: list[Dict[str, Any]] = []
    parameter_cells: list[Dict[str, Any]] = []
    max_row_index = -1
    max_cell_col = -1
    for rows_item in root.findall("./{*}rowsItem"):
        row_index = _int_text(rows_item, "index", 0)
        row = rows_item.find("./{*}row")
        if row is None:
            continue
        row_format_index = _int_text(row, "formatIndex", -1)
        row_meta = {
            "index": int(row_index),
            "format_index": int(row_format_index),
            "columns_id": _child_text(row, "columnsID", ""),
            "height": _row_height_from_format(formats, row_format_index),
        }
        rows.append(row_meta)
        max_row_index = max(max_row_index, int(row_index))

        col_index = 0
        for cell_outer in row.findall("./{*}c"):
            explicit_col_index = _int_text(cell_outer, "i", -1)
            if explicit_col_index >= 0:
                col_index = int(explicit_col_index)
            cell = cell_outer.find("./{*}c")
            if cell is None:
                col_index += 1
                continue
            format_index = _int_text(cell, "f", -1)
            text = _local_string_value(cell.find("./{*}tl"))
            cell_data: Dict[str, Any] = {
                "row": int(row_index),
                "col": int(col_index),
                "format_index": int(format_index),
            }
            if text:
                cell_data["text"] = text
            parameter = _child_text(cell, "parameter", "")
            if parameter:
                cell_data["parameter"] = parameter
                parameter_cells.append(
                    {
                        "name": parameter,
                        "row": int(row_index),
                        "col": int(col_index),
                        "format_index": int(format_index),
                        "fill_type": str(formats[int(format_index)].get("fillType") or "")
                        if 0 <= int(format_index) < len(formats)
                        else "",
                    }
                )
            cells.append(cell_data)
            max_cell_col = max(max_cell_col, int(col_index))
            col_index += 1

    merges: list[Dict[str, int]] = []
    for node in root.findall("./{*}merge"):
        row = _int_text(node, "r", 0)
        col = _int_text(node, "c", 0)
        rowspan = _int_text(node, "h", 0) + 1
        colspan = _int_text(node, "w", 0) + 1
        merges.append(
            {
                "row": int(row),
                "col": int(col),
                "rowspan": max(1, int(rowspan)),
                "colspan": max(1, int(colspan)),
            }
        )
        max_row_index = max(max_row_index, int(row) + max(1, int(rowspan)) - 1)
        max_cell_col = max(max_cell_col, int(col) + max(1, int(colspan)) - 1)

    named_areas: list[Dict[str, Any]] = []
    for node in root.findall("./{*}namedItem"):
        area = node.find("./{*}area")
        named_areas.append(
            {
                "name": _child_text(node, "name", ""),
                "type": _child_text(area, "type", ""),
                "begin_row": _int_text(area, "beginRow", -1),
                "end_row": _int_text(area, "endRow", -1),
                "begin_column": _int_text(area, "beginColumn", -1),
                "end_column": _int_text(area, "endColumn", -1),
                "columns_id": _child_text(area, "columnsID", ""),
            }
        )

    model = {
        "schema_version": 1,
        "kind": "spreadsheet_document",
        "origin": str(origin or ""),
        "template_mode": _child_text(root, "templateMode", "").lower() == "true",
        "default_format_index": _int_text(root, "defaultFormatIndex", -1),
        "row_count": max(_int_text(root, "height", 0), max_row_index + 1, len(rows)),
        "column_count": max(max_columns, max_cell_col + 1),
        "column_sets": column_sets,
        "rows": rows,
        "cells": cells,
        "parameters": parameter_cells,
        "merges": merges,
        "named_areas": named_areas,
        "formats": formats,
        "fonts": fonts,
    }
    return model


def _parse_dcs(root: ET.Element, *, origin: str = "") -> Dict[str, Any]:
    data_sources = [_child_text(node, "name", "") for node in root.findall("./{*}dataSource")]
    data_sets = [_child_text(node, "name", "") for node in root.findall("./{*}dataSet")]
    parameters = [_child_text(node, "name", "") for node in root.findall("./{*}parameter")]
    variants = [_child_text(node, "name", "") for node in root.findall("./{*}settingsVariant")]
    return {
        "schema_version": 1,
        "kind": "data_composition_schema",
        "origin": str(origin or ""),
        "data_sources": [x for x in data_sources if x],
        "data_sets": [x for x in data_sets if x],
        "parameters": [x for x in parameters if x],
        "settings_variants": [x for x in variants if x],
    }


def build_onec_layout_model(
    *,
    body_bytes: bytes,
    mime: str = "",
    origin: str = "",
) -> Optional[Dict[str, Any]]:
    """Build a normalized layout model from a 1C template body."""

    raw_mime = str(mime or "").strip().lower()
    raw_origin = str(origin or "").strip()
    ext = raw_origin.lower()

    if not body_bytes:
        return None

    is_xml_like = raw_mime in {"application/xml", "text/xml"} or ext.endswith(".xml")
    if is_xml_like:
        try:
            root = ET.fromstring(body_bytes)
        except Exception:
            text = _decode_text(body_bytes)
            return {
                "schema_version": 1,
                "kind": "text_template",
                "origin": raw_origin,
                "text": text,
            }

        ns = root.tag.partition("}")[0].strip("{")
        tag = _tag_name(root.tag)
        if tag == "document" and "spreadsheet" in ns:
            return _parse_spreadsheet_document(root, origin=raw_origin)
        if tag == "DataCompositionSchema":
            return _parse_dcs(root, origin=raw_origin)
        return {
            "schema_version": 1,
            "kind": "xml_template",
            "origin": raw_origin,
            "root_tag": tag,
            "namespace": ns,
        }

    if raw_mime.startswith("text/") or ext.endswith(".txt"):
        return {
            "schema_version": 1,
            "kind": "text_template",
            "origin": raw_origin,
            "text": _decode_text(body_bytes),
        }

    if (body_bytes or b"").startswith(_OLE_MAGIC):
        preview = _binary_preview_excerpt(body_bytes)
        return {
            "schema_version": 1,
            "kind": "binary_ole_template",
            "origin": raw_origin,
            "size_bytes": len(body_bytes),
            "container": "ole_compound",
            "signature": "D0 CF 11 E0 A1 B1 1A E1",
            "preview_head_hex": preview["head_hex"],
            "preview_head_ascii": preview["head_ascii"],
            "preview_signature_hex": preview["signature_hex"],
        }

    preview = _binary_preview_excerpt(body_bytes)
    return {
        "schema_version": 1,
        "kind": "binary_template",
        "origin": raw_origin,
        "size_bytes": len(body_bytes),
        "preview_head_hex": preview["head_hex"],
        "preview_head_ascii": preview["head_ascii"],
        "preview_signature_hex": preview["signature_hex"],
    }
