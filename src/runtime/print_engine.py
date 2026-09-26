"""src.runtime.print_engine — HTML-based print form engine.

A Print Form (Зовнішня друкована форма) in MetaPlatform is a MetaScript
module that returns an HTML string ready for browser/printer rendering.

Architecture:
    1. PrintEngine.render(form_name, context_data) → HTML string
    2. The HTML is displayed in a QWebEngineView (or QTextBrowser fallback)
    3. User can Print or Save as PDF from the preview

MetaScript context:
    - Data:    dict of passed context (document record, TP rows, params)
    - Helpers: FormatDate, FormatNumber, T (i18n), TableRow
    - Result:  the script must call SetHtml(html_text) or return an HTML string

"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ─────────────────────────────────── helpers ───────────────────────────────

_TPL_PLACEHOLDER_RE = re.compile(r"\[([^\[\]]+)\]")

def _esc(val: Any) -> str:
    """HTML-escape and stringify a value."""
    return html.escape(str(val) if val is not None else "")


def _format_date(iso: str, fmt: str = "dd.MM.yyyy") -> str:
    """Format ISO date string to display format."""
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d")
        fmt = fmt.replace("dd", f"{d.day:02d}")
        fmt = fmt.replace("MM", f"{d.month:02d}")
        fmt = fmt.replace("yyyy", f"{d.year:04d}")
        return fmt
    except Exception:
        return str(iso)


def _format_number(val: Any, decimals: int = 2,
                   decimal_sep: str = ".", thousand_sep: str = " ") -> str:
    """Format a number with separators."""
    try:
        n = float(val)
        parts = f"{n:,.{decimals}f}".split(".")
        int_part = parts[0].replace(",", thousand_sep)
        frac_part = parts[1] if len(parts) > 1 else ""
        return f"{int_part}{decimal_sep}{frac_part}" if frac_part else int_part
    except Exception:
        return str(val)


# ─────────────────────────────────── base template ─────────────────────────

_BASE_CSS = """
    body { font-family: Roboto, Arial, sans-serif; font-size: 11pt; margin: 10mm; }
    h1   { font-size: 14pt; text-align: center; margin-bottom: 4pt; }
    h2   { font-size: 12pt; margin-top: 12pt; }
    table { border-collapse: collapse; width: 100%; margin-top: 8pt; }
    th, td { border: 1px solid #888; padding: 3pt 5pt; font-size: 10pt; }
    th { background: #e8e8e8; font-weight: bold; text-align: center; }
    .right  { text-align: right; }
    .center { text-align: center; }
    .bold   { font-weight: bold; }
    .total  { background: #f0f0f0; font-weight: bold; }
    @media print { body { margin: 0; } }
"""


def _wrap_html(title: str, body: str) -> str:
    return (
        f"<!DOCTYPE html><html lang='uk'>\n"
        f"<head><meta charset='utf-8'>"
        f"<title>{_esc(title)}</title>"
        f"<style>{_BASE_CSS}</style></head>\n"
        f"<body>{body}</body></html>"
    )


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return getattr(row, key)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _layout_placeholder_context(doc_name: str, header: dict) -> Dict[str, str]:
    number = str(header.get("_number") or "")
    iso_date = str(header.get("_date") or "")
    short_date = _format_date(iso_date) if iso_date else ""
    out: Dict[str, str] = {
        "НомерДокумента": number,
        "Date": short_date,
        "Дата": short_date,
        "ДатаКоротко": short_date,
        "DocName": str(doc_name or ""),
    }
    for key, value in header.items():
        if str(key).startswith("_"):
            continue
        out[str(key)] = "" if value is None else str(value)
    return out


def _stringify_layout_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _merge_layout_values(target: Dict[str, str], extra: Any) -> None:
    if not isinstance(extra, dict):
        return
    for key, value in extra.items():
        key_s = str(key or "").strip()
        if not key_s:
            continue
        target[key_s] = _stringify_layout_value(value)


def _build_layout_render_context(
    *,
    doc_name: str = "",
    context_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    raw = dict(context_data or {})
    out: Dict[str, str] = {}

    header = raw.get("Header")
    if isinstance(header, dict):
        out.update(_layout_placeholder_context(doc_name, header))
        _merge_layout_values(out, {k: v for k, v in header.items() if not str(k).startswith("_")})

    for key in ("LayoutParams", "layout_params", "Parameters", "Params"):
        _merge_layout_values(out, raw.get(key))

    for key, value in raw.items():
        if key in {"Header", "TabParts", "LayoutParams", "layout_params", "Parameters", "Params", "LayoutAreas", "layout_areas", "Areas"}:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            continue
        key_s = str(key or "").strip()
        if not key_s or key_s.startswith("_"):
            continue
        out[key_s] = _stringify_layout_value(value)

    return out


def _layout_context_value(context: Dict[str, str], key: str, default: str = "") -> str:
    key_s = str(key or "").strip()
    if not key_s:
        return default
    if key_s in context:
        return str(context.get(key_s, default))
    key_cf = key_s.casefold()
    for raw_key, raw_value in context.items():
        if str(raw_key).casefold() == key_cf:
            return str(raw_value)
    return default


def _normalize_area_names(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        return [part for part in parts if part]
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            name = str(item or "").strip()
            if name:
                out.append(name)
        return out
    return []


def _single_placeholder_name(text: str) -> str:
    match = _TPL_PLACEHOLDER_RE.fullmatch(str(text or "").strip())
    if match is None:
        return ""
    return str(match.group(1) or "").strip()


def _resolve_layout_cell_text(cell: Dict[str, Any], fmt: Dict[str, Any], context: Dict[str, str]) -> str:
    raw_text = str(cell.get("text") or "")
    parameter_name = str(cell.get("parameter") or "").strip()
    fill_type = str(cell.get("fill_type") or fmt.get("fillType") or "").strip().lower()

    def replace_placeholders(text: str) -> str:
        if not text:
            return ""

        def repl(match: re.Match[str]) -> str:
            key = str(match.group(1) or "").strip()
            return _layout_context_value(context, key, match.group(0))

        return _TPL_PLACEHOLDER_RE.sub(repl, text)

    if fill_type == "parameter":
        parameter_key = parameter_name or _single_placeholder_name(raw_text)
        if parameter_key:
            return _layout_context_value(context, parameter_key, "")
        return replace_placeholders(raw_text)

    if fill_type == "template":
        return replace_placeholders(raw_text)

    if fill_type in {"text", "value"}:
        if raw_text:
            return raw_text
        if parameter_name:
            return _layout_context_value(context, parameter_name, "")
        return ""

    if parameter_name and not raw_text:
        return _layout_context_value(context, parameter_name, "")
    return replace_placeholders(raw_text)


def _resolve_layout_area_rects(model: Dict[str, Any], area_names: Optional[List[str]] = None) -> list[dict[str, Any]]:
    row_count = max(0, _safe_int(model.get("row_count"), 0))
    col_count = max(0, _safe_int(model.get("column_count"), 0))
    if row_count <= 0 or col_count <= 0:
        return []

    normalized_names = _normalize_area_names(area_names)
    if not normalized_names:
        return [
            {
                "name": "",
                "top": 0,
                "left": 0,
                "bottom": row_count - 1,
                "right": col_count - 1,
            }
        ]

    named_areas = model.get("named_areas") if isinstance(model.get("named_areas"), list) else []
    area_index: Dict[str, Dict[str, Any]] = {}
    for area in named_areas:
        if not isinstance(area, dict):
            continue
        name = str(area.get("name") or "").strip()
        if not name:
            continue
        area_index[name.casefold()] = dict(area)

    resolved: list[dict[str, Any]] = []
    for name in normalized_names:
        area = area_index.get(name.casefold())
        if not isinstance(area, dict):
            continue
        top = max(0, _safe_int(area.get("begin_row"), -1))
        left = max(0, _safe_int(area.get("begin_column"), -1))
        bottom = min(row_count - 1, _safe_int(area.get("end_row"), -1))
        right = min(col_count - 1, _safe_int(area.get("end_column"), -1))
        if top < 0 or left < 0 or bottom < top or right < left:
            continue
        resolved.append(
            {
                "name": name,
                "top": top,
                "left": left,
                "bottom": bottom,
                "right": right,
            }
        )
    return resolved or [
        {
            "name": "",
            "top": 0,
            "left": 0,
            "bottom": row_count - 1,
            "right": col_count - 1,
        }
    ]


def _render_spreadsheet_layout_html(
    title: str,
    model: Dict[str, Any],
    context: Optional[Dict[str, str]] = None,
    *,
    area_names: Optional[List[str]] = None,
) -> str:
    context = {str(k): str(v) for k, v in dict(context or {}).items()}
    row_count = max(0, _safe_int(model.get("row_count"), 0))
    col_count = max(0, _safe_int(model.get("column_count"), 0))
    cells_raw = model.get("cells") if isinstance(model.get("cells"), list) else []
    merges_raw = model.get("merges") if isinstance(model.get("merges"), list) else []
    formats = {
        _safe_int(fmt.get("index"), idx): dict(fmt)
        for idx, fmt in enumerate(model.get("formats") or [])
        if isinstance(fmt, dict)
    }
    fonts = {
        _safe_int(font.get("index"), idx): dict(font)
        for idx, font in enumerate(model.get("fonts") or [])
        if isinstance(font, dict)
    }

    cell_map: Dict[tuple[int, int], Dict[str, Any]] = {}
    for cell in cells_raw:
        if not isinstance(cell, dict):
            continue
        row = _safe_int(cell.get("row"), -1)
        col = _safe_int(cell.get("col"), -1)
        if row < 0 or col < 0:
            continue
        cell_map[(row, col)] = dict(cell)

    merge_map: Dict[tuple[int, int], Dict[str, int]] = {}
    covered: set[tuple[int, int]] = set()
    for merge in merges_raw:
        if not isinstance(merge, dict):
            continue
        row = _safe_int(merge.get("row"), -1)
        col = _safe_int(merge.get("col"), -1)
        rowspan = max(1, _safe_int(merge.get("rowspan"), 1))
        colspan = max(1, _safe_int(merge.get("colspan"), 1))
        if row < 0 or col < 0:
            continue
        merge_map[(row, col)] = {"rowspan": rowspan, "colspan": colspan}
        for rr in range(row, row + rowspan):
            for cc in range(col, col + colspan):
                if rr == row and cc == col:
                    continue
                covered.add((rr, cc))

    def cell_style(fmt_idx: int) -> str:
        fmt = formats.get(int(fmt_idx), {})
        style_parts: list[str] = []
        width = fmt.get("width")
        try:
            if width is not None:
                style_parts.append(f"min-width:{max(12, int(width))}px")
        except Exception:
            pass

        h = str(fmt.get("horizontalAlignment") or "").strip().lower()
        if h == "center":
            style_parts.append("text-align:center")
        elif h == "right":
            style_parts.append("text-align:right")
        elif h == "left":
            style_parts.append("text-align:left")

        v = str(fmt.get("verticalAlignment") or "").strip().lower()
        if v == "top":
            style_parts.append("vertical-align:top")
        elif v == "bottom":
            style_parts.append("vertical-align:bottom")
        else:
            style_parts.append("vertical-align:middle")

        if str(fmt.get("textPlacement") or "").strip().lower() == "wrap":
            style_parts.append("white-space:pre-wrap")
        else:
            style_parts.append("white-space:pre-line")

        font_idx = _safe_int(fmt.get("font"), -1) if fmt else -1
        if font_idx in fonts:
            font = fonts[font_idx]
            face = str(font.get("face_name") or "").strip()
            if face:
                style_parts.append(f"font-family:{face}")
            try:
                size = float(font.get("height") or 0)
                if size > 0:
                    style_parts.append(f"font-size:{size}pt")
            except Exception:
                pass
            if font.get("bold"):
                style_parts.append("font-weight:bold")
            if font.get("italic"):
                style_parts.append("font-style:italic")
            if font.get("underline"):
                style_parts.append("text-decoration:underline")

        return "; ".join(style_parts)

    def render_segment(segment: Dict[str, Any]) -> str:
        top = _safe_int(segment.get("top"), 0)
        left = _safe_int(segment.get("left"), 0)
        bottom = min(row_count - 1, _safe_int(segment.get("bottom"), row_count - 1))
        right = min(col_count - 1, _safe_int(segment.get("right"), col_count - 1))
        if bottom < top or right < left:
            return ""

        segment_merge_map: Dict[tuple[int, int], Dict[str, int]] = {}
        segment_merge_source: Dict[tuple[int, int], tuple[int, int]] = {}
        segment_covered: set[tuple[int, int]] = set()
        for merge in merges_raw:
            if not isinstance(merge, dict):
                continue
            row = _safe_int(merge.get("row"), -1)
            col = _safe_int(merge.get("col"), -1)
            rowspan = max(1, _safe_int(merge.get("rowspan"), 1))
            colspan = max(1, _safe_int(merge.get("colspan"), 1))
            if row < 0 or col < 0:
                continue
            merge_bottom = row + rowspan - 1
            merge_right = col + colspan - 1
            clip_top = max(top, row)
            clip_left = max(left, col)
            clip_bottom = min(bottom, merge_bottom)
            clip_right = min(right, merge_right)
            if clip_bottom < clip_top or clip_right < clip_left:
                continue
            anchor = (clip_top, clip_left)
            segment_merge_map[anchor] = {
                "rowspan": clip_bottom - clip_top + 1,
                "colspan": clip_right - clip_left + 1,
            }
            segment_merge_source[anchor] = (row, col)
            for rr in range(clip_top, clip_bottom + 1):
                for cc in range(clip_left, clip_right + 1):
                    if rr == clip_top and cc == clip_left:
                        continue
                    segment_covered.add((rr, cc))

        table_rows: list[str] = []
        for row in range(top, bottom + 1):
            cells_html: list[str] = []
            for col in range(left, right + 1):
                if (row, col) in segment_covered:
                    continue
                source_anchor = segment_merge_source.get((row, col), (row, col))
                cell = cell_map.get(source_anchor) or cell_map.get((row, col))
                merge = segment_merge_map.get((row, col), {"rowspan": 1, "colspan": 1})
                fmt_idx = _safe_int((cell or {}).get("format_index"), -1)
                fmt = formats.get(fmt_idx, {})
                attrs = []
                if _safe_int(merge.get("rowspan"), 1) > 1:
                    attrs.append(f"rowspan='{_safe_int(merge.get('rowspan'), 1)}'")
                if _safe_int(merge.get("colspan"), 1) > 1:
                    attrs.append(f"colspan='{_safe_int(merge.get('colspan'), 1)}'")
                style = cell_style(fmt_idx)
                if style:
                    attrs.append(f"style=\"{style}\"")
                text = _resolve_layout_cell_text(cell or {}, fmt, context)
                cells_html.append(f"<td {' '.join(attrs)}>{_esc(text)}</td>")
            table_rows.append(f"<tr>{''.join(cells_html)}</tr>")
        area_name = str(segment.get("name") or "").strip()
        data_attr = f" data-area='{_esc(area_name)}'" if area_name else ""
        return f"<table class='mp-layout-table'{data_attr}>{''.join(table_rows)}</table>"

    segments = _resolve_layout_area_rects(model, area_names)
    rendered_tables = [html for html in (render_segment(segment) for segment in segments) if html]
    body = f"<h1>{_esc(title)}</h1>{''.join(rendered_tables)}"
    html_doc = _wrap_html(title, body)
    extra_css = """
    .mp-layout-table { border-collapse: collapse; width: auto; margin-bottom: 8pt; background: #fff; }
    .mp-layout-table td { border: 1px solid #666; padding: 3px 4px; background: #fff; color: #111; }
    """
    return html_doc.replace("</style>", f"{extra_css}</style>")


def _table_html(columns: List[dict], rows: List[dict],
                totals: Optional[Dict[str, Any]] = None) -> str:
    """Generate HTML table from column defs + data rows."""
    th_cells = "".join(
        f"<th>{_esc(c.get('title', c.get('key', '')))}</th>"
        for c in columns
    )
    tr_rows = ""
    for row in rows:
        cells = ""
        for c in columns:
            val  = row.get(c.get("key", ""), "")
            css  = ""
            ctype = c.get("type", "str")
            if ctype in ("number", "float", "int"):
                css  = " class='right'"
                if isinstance(val, (int, float)):
                    val = _format_number(val)
            elif ctype == "date":
                val = _format_date(str(val))
            cells += f"<td{css}>{_esc(val)}</td>"
        tr_rows += f"<tr>{cells}</tr>\n"

    totals_row = ""
    if totals:
        cells = ""
        for c in columns:
            key = c.get("key", "")
            val = totals.get(key, "")
            css = " class='total right'" if val else " class='total'"
            if val and isinstance(val, (int, float)):
                val = _format_number(val)
            cells += f"<td{css}>{_esc(val)}</td>"
        totals_row = f"<tr>{cells}</tr>"

    return (
        f"<table>\n<thead><tr>{th_cells}</tr></thead>\n"
        f"<tbody>{tr_rows}{totals_row}</tbody>\n</table>"
    )


# ─────────────────────────────────── engine ────────────────────────────────

class PrintEngine:
    """Render print forms defined in the manifest to HTML.

    Parameters
    ----------
    db : Mpdb
        Open database handle.
    manifest_rows : list
        Pre-loaded manifest rows.
    """

    def __init__(self, db, manifest_rows: list) -> None:
        self._db    = db
        self._mrows = manifest_rows

    # ── public ──────────────────────────────────────────────────────────────

    def render(self, form_name: str,
               context_data: Optional[Dict[str, Any]] = None) -> str:
        """Render a named print form to HTML.

        Returns a complete, self-contained HTML document string.
        Falls back to a generic document view if no custom form found.
        """
        context_data = dict(context_data or {})
        obj = self._find_form(form_name)
        if obj is None:
            return self._generic_html(form_name, context_data)

        title = self._i18n(
            obj.get("payload") or {}, "title", form_name
        )
        script_spec = self._load_module(str(obj.get("guid") or ""))

        if not script_spec:
            return self._generic_html(title, context_data)
        script, module_guid = script_spec

        html_out: list[str] = []

        def _set_html(text: str) -> None:
            html_out.clear()
            html_out.append(str(text))

        ctx: Dict[str, Any] = {
            "Data":         context_data,
            "SetHtml":      _set_html,
            "FormatDate":   _format_date,
            "FormatNumber": _format_number,
            "Escape":       _esc,
            "TableHtml":    _table_html,
            "WrapHtml":     _wrap_html,
            "Title":        title,
            "RenderLayout": lambda layout_name="", params=None, areas=None, layout_title="": self.render_layout(
                layout_name,
                doc_name=str(context_data.get("DocName") or ""),
                context_data=self._merge_layout_context(
                    context_data,
                    extra_params=params,
                    extra_areas=areas,
                ),
                title_override=str(layout_title or ""),
            ),
            "RenderLayoutArea": lambda area_name, layout_name="", params=None, layout_title="": self.render_layout(
                layout_name,
                doc_name=str(context_data.get("DocName") or ""),
                context_data=self._merge_layout_context(
                    context_data,
                    extra_params=params,
                    extra_areas=[area_name] if area_name else [],
                ),
                title_override=str(layout_title or ""),
            ),
            "GetLayoutAreas": lambda layout_name="": self.get_layout_areas(
                layout_name,
                doc_name=str(context_data.get("DocName") or ""),
            ),
        }

        try:
            from src.runtime.script.vm import execute_script
            execute_script(script, context=ctx, module_name=f"module://{module_guid}" if module_guid else "")
        except Exception as e:
            return _wrap_html(
                f"Error: {form_name}",
                f"<h2>Print form execution error</h2><pre>{_esc(str(e))}</pre>",
            )

        if html_out:
            result = html_out[0]
            # If script returned bare body — wrap it
            if not result.strip().lower().startswith("<!doctype"):
                result = _wrap_html(title, result)
            return result

        return self._generic_html(title, context_data)

    def render_document(
        self,
        doc_name: str,
        doc_guid: str,
        context_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Render a document to HTML using its default print form.

        Auto-generates a fallback form if no custom form exists.
        """
        context_data = dict(context_data or {})
        # Load document header
        try:
            header_rows = self._db.table(
                f"data_document_{doc_name.lower()}"
            ).select(where={"_guid": doc_guid}) or []
            header = header_rows[0] if header_rows else {}
        except Exception:
            header = {}

        # Load tabular parts
        tp_data: Dict[str, list] = {}
        doc_obj = next(
            (r for r in self._mrows
             if str(r.get("name") or "").lower() == doc_name.lower()
             and str(r.get("type") or "") == "document"),
            None,
        )
        if doc_obj:
            for r in self._mrows:
                if str(r.get("type") or "").lower() != "tabular_part_item":
                    continue
                tp_name = str(r.get("name") or "").strip()
                if tp_name:
                    try:
                        rows = self._db.table(
                            f"data_tp_{doc_name.lower()}_{tp_name.lower()}"
                        ).select(where={"_doc_guid": doc_guid}) or []
                        tp_data[tp_name] = rows
                    except Exception:
                        pass

        ctx = {
            "DocName":    doc_name,
            "Header":     header,
            "TabParts":   tp_data,
        }
        ctx.update(context_data)

        # Try named print form matching document name
        form_obj = self._find_form(doc_name)
        if form_obj:
            return self.render(doc_name, ctx)

        layout_html = self.render_layout(
            "",
            doc_name=doc_name,
            context_data=ctx,
        )
        if layout_html:
            return layout_html

        # Fallback: generic
        return self._generic_document_html(doc_name, header, tp_data)

    def render_layout(
        self,
        layout_name: str = "",
        *,
        doc_name: str = "",
        context_data: Optional[Dict[str, Any]] = None,
        title_override: str = "",
    ) -> str:
        ctx = dict(context_data or {})
        layout_obj = self._find_layout(layout_name, doc_name=doc_name or str(ctx.get("DocName") or ""))
        if layout_obj is None:
            return ""

        payload = _row_get(layout_obj, "payload", {}) or {}
        if not isinstance(payload, dict):
            return ""
        layout_model = payload.get("layout_model")
        if not isinstance(layout_model, dict) or str(layout_model.get("kind") or "") != "spreadsheet_document":
            return ""

        render_context = _build_layout_render_context(
            doc_name=doc_name or str(ctx.get("DocName") or ""),
            context_data=ctx,
        )
        area_names = _normalize_area_names(
            ctx.get("LayoutAreas") or ctx.get("layout_areas") or ctx.get("Areas")
        )
        title = str(title_override or _row_get(layout_obj, "title", "") or _row_get(layout_obj, "name", "") or doc_name or "Layout")
        return _render_spreadsheet_layout_html(
            title,
            layout_model,
            render_context,
            area_names=area_names,
        )

    def get_layout_areas(self, layout_name: str = "", *, doc_name: str = "") -> list[str]:
        layout_obj = self._find_layout(layout_name, doc_name=doc_name)
        if layout_obj is None:
            return []
        payload = _row_get(layout_obj, "payload", {}) or {}
        model = payload.get("layout_model") if isinstance(payload, dict) else {}
        named_areas = model.get("named_areas") if isinstance(model, dict) and isinstance(model.get("named_areas"), list) else []
        out: list[str] = []
        seen: set[str] = set()
        for item in named_areas:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            out.append(name)
        return out

    # ── private ─────────────────────────────────────────────────────────────

    @staticmethod
    def _merge_layout_context(
        context_data: Dict[str, Any],
        *,
        extra_params: Any = None,
        extra_areas: Any = None,
    ) -> Dict[str, Any]:
        out = dict(context_data or {})
        if isinstance(extra_params, dict):
            merged = dict(out.get("LayoutParams") or {})
            merged.update(extra_params)
            out["LayoutParams"] = merged
        if extra_areas is not None:
            out["LayoutAreas"] = extra_areas
        return out

    def _find_form(self, name: str) -> Optional[dict]:
        name_l = name.strip().lower()
        for r in self._mrows:
            t_low = str(_row_get(r, "type", "") or "").strip().lower()
            if t_low not in ("print_form", "external_report", "external_processing"):
                continue
            if str(_row_get(r, "kind", "") or "") != "object":
                continue
            if str(_row_get(r, "name", "") or "").strip().lower() == name_l:
                return dict(r) if isinstance(r, dict) else {
                    "guid": _row_get(r, "guid", ""),
                    "type": _row_get(r, "type", ""),
                    "name": _row_get(r, "name", ""),
                    "title": _row_get(r, "title", ""),
                    "kind": _row_get(r, "kind", ""),
                    "parent_guid": _row_get(r, "parent_guid", ""),
                    "payload": _row_get(r, "payload", {}),
                }
        return None

    def _find_layout(self, layout_name: str, *, doc_name: str = "") -> Optional[Any]:
        name_l = str(layout_name or "").strip().lower()
        if name_l:
            candidates = [
                r for r in self._mrows
                if str(_row_get(r, "kind", "") or "") == "object"
                and str(_row_get(r, "type", "") or "").strip().lower() in ("layout", "common_layout")
                and (
                    str(_row_get(r, "name", "") or "").strip().lower() == name_l
                    or str(_row_get(r, "title", "") or "").strip().lower() == name_l
                )
            ]
            if candidates:
                return sorted(candidates, key=self._layout_score)[0]
        if doc_name:
            return self._find_document_layout(doc_name)
        return None

    def _find_document_layout(self, doc_name: str) -> Optional[Any]:
        doc_name_l = str(doc_name or "").strip().lower()
        doc_obj = next(
            (
                r for r in self._mrows
                if str(_row_get(r, "type", "") or "").strip().lower() == "document"
                and str(_row_get(r, "name", "") or "").strip().lower() == doc_name_l
                and str(_row_get(r, "kind", "") or "") == "object"
            ),
            None,
        )
        if doc_obj is None:
            return None

        doc_guid = str(_row_get(doc_obj, "guid", "") or "")
        layouts_folder = next(
            (
                r for r in self._mrows
                if str(_row_get(r, "parent_guid", "") or "") == doc_guid
                and str(_row_get(r, "kind", "") or "") == "folder"
                and str(_row_get(r, "name", "") or "").strip().lower() == "layouts"
            ),
            None,
        )
        if layouts_folder is None:
            return None

        folder_guid = str(_row_get(layouts_folder, "guid", "") or "")
        candidates = [
            r for r in self._mrows
            if str(_row_get(r, "parent_guid", "") or "") == folder_guid
            and str(_row_get(r, "kind", "") or "") == "object"
            and str(_row_get(r, "type", "") or "").strip().lower() in ("layout", "common_layout")
        ]
        if not candidates:
            return None

        return sorted(candidates, key=self._layout_score)[0]

    def _load_module(self, owner_guid: str) -> Optional[tuple[str, str]]:
        modules_folder = next(
            (str(_row_get(r, "guid", "") or "")
             for r in self._mrows
             if str(_row_get(r, "parent_guid", "") or "") == owner_guid
             and str(_row_get(r, "type", "") or "").lower() in (
                 "modules", "modules_folder")),
            None,
        )
        if not modules_folder:
            return None
        module_guid = next(
            (str(_row_get(r, "guid", "") or "")
             for r in self._mrows
             if str(_row_get(r, "parent_guid", "") or "") == modules_folder),
            None,
        )
        if not module_guid:
            return None
        try:
            from src.configurator.persistence.modules_dao import get_module_text
            return get_module_text(self._db, module_guid=module_guid), module_guid
        except Exception:
            return None

    def _generic_html(self, title: str,
                      context_data: Dict[str, Any]) -> str:
        rows_html = "".join(
            f"<tr><td><b>{_esc(k)}</b></td>"
            f"<td>{_esc(json.dumps(v, ensure_ascii=False, default=str))}</td></tr>"
            for k, v in context_data.items()
            if not str(k).startswith("_")
        )
        body = (
            f"<h1>{_esc(title)}</h1>"
            f"<table><thead><tr><th>Field</th><th>Value</th></tr></thead>"
            f"<tbody>{rows_html}</tbody></table>"
        )
        return _wrap_html(title, body)

    def _generic_document_html(self, doc_name: str,
                               header: dict,
                               tp_data: Dict[str, list]) -> str:
        number   = str(header.get("_number") or "—")
        doc_date = _format_date(str(header.get("_date") or ""))
        posted   = "✓" if header.get("_posted") else "✗"

        # Header info table
        info_rows = ""
        for k, v in header.items():
            if k.startswith("_"):
                continue
            info_rows += (
                f"<tr><td><b>{_esc(k)}</b></td>"
                f"<td>{_esc(str(v) if v is not None else '')}</td></tr>"
            )

        header_html = (
            f"<table style='width:50%;margin-bottom:8pt'>"
            f"<tr><td><b>Number</b></td><td>{_esc(number)}</td></tr>"
            f"<tr><td><b>Date</b></td><td>{_esc(doc_date)}</td></tr>"
            f"<tr><td><b>Posted</b></td><td>{posted}</td></tr>"
            f"{info_rows}</table>"
        )

        # Tabular parts
        tp_html = ""
        for tp_name, rows in tp_data.items():
            if not rows:
                continue
            keys = [k for k in rows[0] if not k.startswith("_")]
            cols = [{"key": k, "title": k} for k in keys]
            tp_html += (
                f"<h2>{_esc(tp_name)}</h2>"
                + _table_html(cols, rows)
            )

        body = (
            f"<h1>{_esc(doc_name)} № {_esc(number)} від {_esc(doc_date)}</h1>"
            f"{header_html}"
            f"{tp_html}"
        )
        return _wrap_html(f"{doc_name} {number}", body)

    @staticmethod
    def _i18n(payload: dict, key: str, fallback: str = "") -> str:
        val = payload.get(key, {})
        if isinstance(val, dict):
            return str(val.get("uk") or val.get("en") or fallback)
        return str(val or fallback)

    @staticmethod
    def _layout_score(row: Any) -> tuple[int, str]:
        payload = _row_get(row, "payload", {}) or {}
        model = payload.get("layout_model") if isinstance(payload, dict) else {}
        kind = str((model or {}).get("kind") or payload.get("layout_kind") or "")
        title = str(_row_get(row, "title", "") or "")
        name = str(_row_get(row, "name", "") or "")
        primary = 0
        if kind == "spreadsheet_document":
            primary -= 50
        if "ПФ_MXL" in title or "ПФ_MXL" in name:
            primary -= 20
        if "ПФ_" in title or "ПФ_" in name:
            primary -= 10
        return (primary, title or name)
