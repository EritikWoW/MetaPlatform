from __future__ import annotations

import json
from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QFormLayout, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget

from src.infra.onec.layout_parser import build_onec_layout_model
from src.ui_qt.i18n import t

from .layout_preview_helpers import _layout_cell_display_text, _load_layout_model_from_workspace
from .layout_preview_sheet import _LayoutSheetDelegate


class LayoutPreviewBuildMixin:
    def _resolve_layout_model(self) -> Dict[str, Any]:
        model = self._payload.get("layout_model")
        if isinstance(model, dict) and model:
            return dict(model)

        asset_candidates = [
            str(self._payload.get("layout_model_ref") or "").strip(),
            str(self._payload.get("layout_ref") or "").strip(),
            str(self._payload.get("layout_model_asset_key") or "").strip(),
        ]
        if self._vm is not None:
            get_text_asset = getattr(self._vm, "get_text_asset", None)
            if callable(get_text_asset):
                for asset_key in asset_candidates:
                    if not asset_key:
                        continue
                    try:
                        text, mime, _resolved = get_text_asset(asset_key)
                    except Exception:
                        continue
                    source = str(text or "").strip()
                    if not source:
                        continue
                    try:
                        parsed = json.loads(source)
                    except Exception:
                        parsed = None
                    if isinstance(parsed, dict) and parsed:
                        return dict(parsed)
                    model = build_onec_layout_model(
                        body_bytes=source.encode("utf-8"),
                        mime=str(mime or "text/plain"),
                        origin=asset_key,
                    )
                    if isinstance(model, dict) and model:
                        return model

        imported = self._payload.get("imported") if isinstance(self._payload.get("imported"), dict) else {}
        body_origin = str(imported.get("layout_body_origin") or "").strip()
        body_mime = str(imported.get("layout_body_mime") or "").strip()
        asset_candidates = [
            str(imported.get("layout_body_asset") or "").strip(),
            f"onec_raw/{body_origin}" if body_origin else "",
        ]

        if self._vm is None:
            return {}

        for asset_key in asset_candidates:
            if not asset_key:
                continue
            try:
                data, mime = self._vm.get_picture_asset(asset_key)
            except Exception:
                data = b""
                mime = ""
            if data:
                model = build_onec_layout_model(
                    body_bytes=data,
                    mime=str(mime or body_mime or "application/octet-stream"),
                    origin=body_origin or asset_key,
                )
                if isinstance(model, dict) and model:
                    return model
            try:
                text, mime, _resolved = self._vm.get_text_asset(asset_key)
            except Exception:
                continue
            model = build_onec_layout_model(
                body_bytes=str(text or "").encode("utf-8"),
                mime=str(mime or body_mime or "text/plain"),
                origin=body_origin or asset_key,
            )
            if isinstance(model, dict) and model:
                return model

        if body_origin:
            model = _load_layout_model_from_workspace(
                body_origin=body_origin,
                body_mime=body_mime,
            )
            if isinstance(model, dict) and model:
                return model

        return {}


    def _build_preview_page(self) -> QWidget:
        model = self._layout_model
        kind = str(model.get("kind") or "").strip()
        if kind == "spreadsheet_document":
            return self._build_spreadsheet_preview(model)
        if kind == "text_template":
            return self._build_text_preview(str(model.get("text") or ""))
        if kind == "data_composition_schema":
            return self._build_message_preview(t("layout_preview_dcs"))
        if kind == "binary_ole_template":
            return self._build_binary_preview(model, ole=True)
        if kind == "binary_template":
            return self._build_binary_preview(model, ole=False)
        if kind == "xml_template":
            root_tag = str(model.get("root_tag") or "")
            return self._build_message_preview(t("layout_preview_xml").format(tag=root_tag or "?"))
        return self._build_message_preview(t("layout_preview_missing"))


    def _build_message_preview(self, text: str) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(16, 16, 16, 16)
        l.setSpacing(8)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        l.addWidget(lbl, 0)
        l.addStretch(1)
        return w


    def _build_text_preview(self, text: str) -> QWidget:
        ed = QPlainTextEdit()
        ed.setReadOnly(True)
        ed.setPlainText(str(text or ""))
        return ed

    def _build_binary_preview(self, model: Dict[str, Any], *, ole: bool) -> QWidget:
        size = self._safe_int(model.get("size_bytes"), 0)
        signature = str(model.get("signature") or model.get("preview_signature_hex") or "").strip()
        head_ascii = str(model.get("preview_head_ascii") or "").strip()
        head_hex = str(model.get("preview_head_hex") or "").strip()

        lines: list[str] = []
        lines.append(t("layout_preview_binary_summary").format(size=size))
        if ole:
            lines.append(t("layout_preview_binary_container").format(container=str(model.get("container") or "ole_compound")))
        if signature:
            lines.append(t("layout_preview_binary_signature").format(signature=signature))
        if head_ascii:
            lines.append(t("layout_preview_binary_ascii"))
            lines.append(head_ascii)
        if head_hex:
            lines.append(t("layout_preview_binary_hex"))
            lines.append(head_hex)

        return self._build_text_preview("\n".join(lines))


    def _build_spreadsheet_preview(self, model: Dict[str, Any]) -> QWidget:
        row_count = max(1, self._safe_int(model.get("row_count"), 0))
        col_count = max(1, self._safe_int(model.get("column_count"), 0))
        table = QTableWidget(row_count, col_count)
        self._table = table
        table.setItemDelegate(_LayoutSheetDelegate(table))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)
        table.setWordWrap(True)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.verticalHeader().setDefaultSectionSize(18)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.currentCellChanged.connect(self._on_current_cell_changed)
        table.itemSelectionChanged.connect(self._on_selection_changed)
        table.customContextMenuRequested.connect(self._show_cell_context_menu)
        table.setStyleSheet(
            """
            QTableWidget {
                background: #FFFFFF;
                color: #111827;
                gridline-color: #E5E7EB;
                selection-background-color: #CFE3FF;
                selection-color: #0B1020;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
            }
            QTableWidget::item {
                background: #FFFFFF;
                color: #111827;
            }
            QTableWidget::item:selected {
                background: #CFE3FF;
                color: #0B1020;
            }
            QTableCornerButton::section {
                background: #F3F4F6;
                border: 1px solid #E2E8F0;
            }
            QHeaderView::section {
                background: #F8FAFC;
                color: #111827;
                border: 1px solid #E2E8F0;
                padding: 2px 4px;
                font-weight: 600;
            }
            """
        )

        table.setHorizontalHeaderLabels([str(i + 1) for i in range(col_count)])
        table.setUpdatesEnabled(False)
        formats = {
            self._safe_int(fmt.get("index"), idx): dict(fmt)
            for idx, fmt in enumerate(model.get("formats") or [])
            if isinstance(fmt, dict)
        }
        self._sheet_formats = formats
        fonts = {
            self._safe_int(font.get("index"), idx): dict(font)
            for idx, font in enumerate(model.get("fonts") or [])
            if isinstance(font, dict)
        }

        column_sets = model.get("column_sets") if isinstance(model.get("column_sets"), list) else []
        default_columns: dict[int, int] = {}
        self._sheet_column_sets: dict[str, dict[str, Any]] = {}
        for block_index, block in enumerate(column_sets):
            if not isinstance(block, dict):
                continue
            block_id = str(block.get("id") or "").strip() or ("__default__" if block_index == 0 else "")
            block_size = self._safe_int(block.get("size"), 0)
            block_widths: dict[int, int] = {}
            for col in block.get("columns") or []:
                if not isinstance(col, dict):
                    continue
                col_index = self._safe_int(col.get("index"), 0)
                width = self._safe_int(col.get("width"), 80)
                default_columns[col_index] = max(default_columns.get(col_index, 0), width)
                block_widths[col_index] = width
            if block_id:
                self._sheet_column_sets[block_id] = {
                    "id": block_id,
                    "size": max(block_size, max(block_widths.keys(), default=-1) + 1),
                    "widths": block_widths,
                }
        self._sheet_default_columns = dict(default_columns)

        rows = model.get("rows") if isinstance(model.get("rows"), list) else []
        self._sheet_row_columns: dict[int, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_index = self._safe_int(row.get("index"), -1)
            if 0 <= row_index < row_count:
                height = self._safe_int(row.get("height"), 24)
                table.setRowHeight(row_index, max(18, min(140, height)))
                self._sheet_row_columns[row_index] = str(row.get("columns_id") or "")

        self._apply_row_headers(table, model, row_count)
        self._apply_column_scheme_for_row(0)

        cells = model.get("cells") if isinstance(model.get("cells"), list) else []
        self._sheet_cells = {}
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            row = self._safe_int(cell.get("row"), -1)
            col = self._safe_int(cell.get("col"), -1)
            if not (0 <= row < row_count and 0 <= col < col_count):
                continue
            cell_copy = dict(cell)
            self._sheet_cells[(row, col)] = cell_copy
            self._refresh_cell_item(row=row, col=col, fonts=fonts)

        merges = model.get("merges") if isinstance(model.get("merges"), list) else []
        self._sheet_merges = {}
        for merge in merges:
            if not isinstance(merge, dict):
                continue
            row = self._safe_int(merge.get("row"), -1)
            col = self._safe_int(merge.get("col"), -1)
            rowspan = max(1, self._safe_int(merge.get("rowspan"), 1))
            colspan = max(1, self._safe_int(merge.get("colspan"), 1))
            if not (0 <= row < row_count and 0 <= col < col_count):
                continue
            table.setSpan(row, col, rowspan, colspan)
            merge_info = {
                "row": row,
                "col": col,
                "rowspan": rowspan,
                "colspan": colspan,
            }
            for r in range(row, row + rowspan):
                for c in range(col, col + colspan):
                    self._sheet_merges[(r, c)] = dict(merge_info)

        table.setUpdatesEnabled(True)
        self._sheet_props.set_cell(None)
        self._sync_toolbar_from_selection()

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_sheet_tools(), 0)
        layout.addWidget(table, 1)
        return page

    def _apply_row_headers(self, table: QTableWidget, model: Dict[str, Any], row_count: int) -> None:
        labels = [str(i + 1) for i in range(row_count)]
        tooltips = [""] * row_count
        for area in model.get("named_areas") or []:
            if not isinstance(area, dict):
                continue
            if str(area.get("type") or "").strip().lower() != "rows":
                continue
            name = str(area.get("name") or "").strip()
            begin_row = self._safe_int(area.get("begin_row"), -1)
            end_row = self._safe_int(area.get("end_row"), -1)
            if not name or begin_row < 0:
                continue
            begin_row = max(0, min(row_count - 1, begin_row))
            end_row = max(begin_row, min(row_count - 1, end_row if end_row >= 0 else begin_row))
            labels[begin_row] = name
            for row in range(begin_row, end_row + 1):
                tooltips[row] = name
        for row_index, label in enumerate(labels):
            item = QTableWidgetItem(label)
            if tooltips[row_index]:
                item.setToolTip(tooltips[row_index])
            table.setVerticalHeaderItem(row_index, item)

    def _apply_column_scheme_for_row(self, row: int) -> None:
        table = self._table
        if table is None:
            return
        active_id = str(getattr(self, "_sheet_row_columns", {}).get(int(row), "") or "")
        schemes = getattr(self, "_sheet_column_sets", {})
        scheme = schemes.get(active_id) if active_id else None
        if scheme is None:
            scheme = schemes.get("__default__")
        widths = dict(getattr(self, "_sheet_default_columns", {}) or {})
        visible_size = table.columnCount()
        if isinstance(scheme, dict):
            widths.update({int(key): int(value) for key, value in (scheme.get("widths") or {}).items()})
            visible_size = max(1, self._safe_int(scheme.get("size"), table.columnCount()))
        for col_index in range(table.columnCount()):
            width = self._safe_int(widths.get(col_index), 80)
            table.setColumnWidth(col_index, self._sheet_width_to_px(width))
            header_item = table.horizontalHeaderItem(col_index)
            if header_item is None:
                header_item = QTableWidgetItem()
                table.setHorizontalHeaderItem(col_index, header_item)
            header_item.setText(str(col_index + 1) if col_index < visible_size else "")


    def _build_sheet_tools(self) -> QWidget:
        panel = QWidget()
        root = QVBoxLayout(panel)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        text_row = QHBoxLayout()
        text_row.setContentsMargins(0, 0, 0, 0)
        text_row.setSpacing(6)
        text_row.addWidget(QLabel(t("layout_tool_range")), 0)
        self._tool_range = QLineEdit()
        self._tool_range.setReadOnly(True)
        self._tool_range.setFixedWidth(120)
        text_row.addWidget(self._tool_range, 0)
        text_row.addWidget(QLabel(t("layout_tool_text")), 0)
        self._tool_text = QLineEdit()
        self._tool_text.setPlaceholderText(t("layout_tool_text_placeholder"))
        self._tool_text.editingFinished.connect(self._apply_toolbar_text)
        text_row.addWidget(self._tool_text, 1)
        root.addLayout(text_row, 0)

        tools = QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(6)

        self._tool_bold = QToolButton()
        self._tool_bold.setText("B")
        self._tool_bold.setCheckable(True)
        self._tool_bold.setToolTip(t("layout_tool_bold"))
        self._tool_bold.clicked.connect(lambda checked: self._apply_toolbar_toggle("font_bold", bool(checked)))
        tools.addWidget(self._tool_bold, 0)

        self._tool_italic = QToolButton()
        self._tool_italic.setText("I")
        self._tool_italic.setCheckable(True)
        self._tool_italic.setToolTip(t("layout_tool_italic"))
        self._tool_italic.clicked.connect(lambda checked: self._apply_toolbar_toggle("font_italic", bool(checked)))
        tools.addWidget(self._tool_italic, 0)

        self._tool_underline = QToolButton()
        self._tool_underline.setText("U")
        self._tool_underline.setCheckable(True)
        self._tool_underline.setToolTip(t("layout_tool_underline"))
        self._tool_underline.clicked.connect(lambda checked: self._apply_toolbar_toggle("font_underline", bool(checked)))
        tools.addWidget(self._tool_underline, 0)

        self._tool_font_size = QComboBox()
        self._tool_font_size.setEditable(False)
        self._tool_font_size.addItem(t("layout_tool_font_auto"), "")
        for size in (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28):
            self._tool_font_size.addItem(str(size), size)
        self._tool_font_size.currentIndexChanged.connect(self._apply_toolbar_font_size)
        tools.addWidget(self._tool_font_size, 0)

        self._tool_fill = QComboBox()
        self._tool_fill.setEditable(False)
        for value, label_key in (
            ("", "layout_fill_auto"),
            ("Template", "layout_fill_template"),
            ("Parameter", "layout_fill_parameter"),
            ("Value", "layout_fill_value"),
            ("Text", "layout_fill_text"),
        ):
            self._tool_fill.addItem(t(label_key), value)
        self._tool_fill.currentIndexChanged.connect(
            lambda _idx: self._apply_toolbar_choice("fill_type", self._tool_fill)
        )
        tools.addWidget(self._tool_fill, 0)

        self._tool_border = QComboBox()
        self._tool_border.setEditable(False)
        for value, label_key in (
            ("", "layout_border_auto"),
            ("none", "layout_border_none"),
            ("solid", "layout_border_solid"),
            ("thick", "layout_border_thick"),
        ):
            self._tool_border.addItem(t(label_key), value)
        self._tool_border.currentIndexChanged.connect(
            lambda _idx: self._apply_toolbar_choice("border_style", self._tool_border)
        )
        tools.addWidget(self._tool_border, 0)

        self._tool_h_align = QComboBox()
        self._tool_h_align.setEditable(False)
        for value, label_key in (
            ("", "layout_align_auto"),
            ("Left", "layout_align_left"),
            ("Center", "layout_align_center"),
            ("Right", "layout_align_right"),
        ):
            self._tool_h_align.addItem(t(label_key), value)
        self._tool_h_align.currentIndexChanged.connect(
            lambda _idx: self._apply_toolbar_choice("horizontal_alignment", self._tool_h_align)
        )
        tools.addWidget(self._tool_h_align, 0)

        self._tool_v_align = QComboBox()
        self._tool_v_align.setEditable(False)
        for value, label_key in (
            ("", "layout_align_auto"),
            ("Top", "layout_align_top"),
            ("Center", "layout_align_middle"),
            ("Bottom", "layout_align_bottom"),
        ):
            self._tool_v_align.addItem(t(label_key), value)
        self._tool_v_align.currentIndexChanged.connect(
            lambda _idx: self._apply_toolbar_choice("vertical_alignment", self._tool_v_align)
        )
        tools.addWidget(self._tool_v_align, 0)

        self._tool_merge = QToolButton()
        self._tool_merge.setText(t("layout_tool_merge"))
        self._tool_merge.clicked.connect(self._merge_selected_cells)
        tools.addWidget(self._tool_merge, 0)

        self._tool_unmerge = QToolButton()
        self._tool_unmerge.setText(t("layout_tool_unmerge"))
        self._tool_unmerge.clicked.connect(self._unmerge_selected_cells)
        tools.addWidget(self._tool_unmerge, 0)

        tools.addStretch(1)
        root.addLayout(tools, 0)

        area_row = QHBoxLayout()
        area_row.setContentsMargins(0, 0, 0, 0)
        area_row.setSpacing(6)
        area_row.addWidget(QLabel(t("layout_tool_area")), 0)
        self._tool_area = QComboBox()
        self._tool_area.setEditable(True)
        self._tool_area.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._tool_area.setMinimumWidth(220)
        self._tool_area.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._tool_area.lineEdit().setPlaceholderText(t("layout_tool_area_placeholder"))
        self._tool_area.activated.connect(lambda _idx: self._goto_selected_area())
        area_row.addWidget(self._tool_area, 1)

        self._tool_area_assign = QToolButton()
        self._tool_area_assign.setText(t("layout_tool_area_assign"))
        self._tool_area_assign.clicked.connect(self._assign_selected_area)
        area_row.addWidget(self._tool_area_assign, 0)

        self._tool_area_goto = QToolButton()
        self._tool_area_goto.setText(t("layout_tool_area_goto"))
        self._tool_area_goto.clicked.connect(self._goto_selected_area)
        area_row.addWidget(self._tool_area_goto, 0)

        self._tool_area_remove = QToolButton()
        self._tool_area_remove.setText(t("layout_tool_area_remove"))
        self._tool_area_remove.clicked.connect(self._remove_selected_area)
        area_row.addWidget(self._tool_area_remove, 0)

        root.addLayout(area_row, 0)
        self._refresh_area_tools()
        self._sync_toolbar_from_selection()
        return panel


    def _build_info_page(self) -> QWidget:
        model = self._layout_model
        imported = self._payload.get("imported") if isinstance(self._payload.get("imported"), dict) else {}

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        form.addRow(t("layout_info_kind"), QLabel(str(model.get("kind") or self._payload.get("layout_kind") or "—")))
        form.addRow(t("layout_info_origin"), QLabel(str(imported.get("origin") or "—")))
        form.addRow(t("layout_info_body_origin"), QLabel(str(imported.get("layout_body_origin") or "—")))
        form.addRow(t("layout_info_body_mime"), QLabel(str(imported.get("layout_body_mime") or "—")))

        if str(model.get("kind") or "") == "spreadsheet_document":
            dims = f'{self._safe_int(model.get("row_count"), 0)} x {self._safe_int(model.get("column_count"), 0)}'
            form.addRow(t("layout_info_dimensions"), QLabel(dims))
            form.addRow(t("layout_info_named_areas"), QLabel(str(len(model.get("named_areas") or []))))
            params = model.get("parameters") if isinstance(model.get("parameters"), list) else []
            form.addRow(t("layout_info_parameters"), QLabel(str(len(params))))
        elif str(model.get("kind") or "") == "data_composition_schema":
            form.addRow(t("layout_info_data_sets"), QLabel(str(len(model.get("data_sets") or []))))
            form.addRow(t("layout_info_parameters"), QLabel(str(len(model.get("parameters") or []))))

        layout.addLayout(form, 0)

        if str(model.get("kind") or "") == "spreadsheet_document":
            params = model.get("parameters") if isinstance(model.get("parameters"), list) else []
            if params:
                param_names: list[str] = []
                seen: set[str] = set()
                for item in params:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    param_names.append(name)
                if param_names:
                    lbl = QLabel(t("layout_info_parameter_list"))
                    layout.addWidget(lbl, 0)
                    param_box = QPlainTextEdit()
                    param_box.setReadOnly(True)
                    param_box.setMaximumHeight(140)
                    param_box.setPlainText("\n".join(param_names))
                    layout.addWidget(param_box, 0)

        summary = QPlainTextEdit()
        summary.setReadOnly(True)
        summary.setPlainText(json.dumps(model or self._payload, ensure_ascii=False, indent=2))
        layout.addWidget(summary, 1)
        return page


    def _refresh_cell_item(self, *, row: int, col: int, fonts: dict[int, dict[str, Any]] | None = None) -> None:
        table = self._table
        if table is None:
            return
        cell = self._sheet_cells.get((row, col))
        if cell is None:
            return
        item = table.item(row, col)
        if item is None:
            item = QTableWidgetItem("")
            table.setItem(row, col, item)

        item.setText(_layout_cell_display_text(cell))
        parameter_name = str(cell.get("parameter") or "").strip()
        if not str(cell.get("text") or "").strip() and parameter_name:
            item.setForeground(QColor("#475569"))
        else:
            item.setForeground(QColor("#111827"))

        fmt = self._format_for_cell(cell)
        item.setTextAlignment(self._cell_alignment(fmt))
        fonts_map = fonts or {}
        font_idx = self._safe_int(fmt.get("font"), -1) if fmt else -1
        qfont = QFont(item.font())
        if font_idx in fonts_map:
            font_spec = fonts_map[font_idx]
            face_name = str(font_spec.get("face_name") or "").strip()
            if face_name:
                qfont.setFamily(face_name)
            qfont.setBold(bool(font_spec.get("bold")))
            qfont.setItalic(bool(font_spec.get("italic")))
            qfont.setUnderline(bool(font_spec.get("underline")))
            try:
                size = float(font_spec.get("height") or 0)
                if size > 0:
                    qfont.setPointSizeF(size)
            except Exception:
                pass
        if "font_face" in cell and str(cell.get("font_face") or "").strip():
            qfont.setFamily(str(cell.get("font_face") or "").strip())
        if "font_bold" in cell:
            qfont.setBold(bool(cell.get("font_bold")))
        if "font_italic" in cell:
            qfont.setItalic(bool(cell.get("font_italic")))
        if "font_underline" in cell:
            qfont.setUnderline(bool(cell.get("font_underline")))
        if "font_height" in cell:
            try:
                size = float(cell.get("font_height") or 0)
                if size > 0:
                    qfont.setPointSizeF(size)
            except Exception:
                pass
        item.setFont(qfont)
        tooltip_parts = []
        text = str(cell.get("text") or "").strip()
        if text:
            tooltip_parts.append(text)
        if parameter_name:
            tooltip_parts.append(f"Parameter: {parameter_name}")
        fill_type = str(cell.get("fill_type") or fmt.get("fillType") or "").strip()
        if fill_type:
            tooltip_parts.append(f"Fill type: {fill_type}")
        if tooltip_parts:
            item.setToolTip("\n".join(tooltip_parts))
        else:
            item.setToolTip("")


    def _format_for_cell(self, cell: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(cell, dict):
            return {}
        fmt = self._sheet_formats.get(self._safe_int(cell.get("format_index"), -1), {})
        out = dict(fmt or {})
        fill_type = str(cell.get("fill_type") or "").strip()
        if fill_type:
            out["fillType"] = fill_type
        for src_key, dst_key in (
            ("horizontal_alignment", "horizontalAlignment"),
            ("vertical_alignment", "verticalAlignment"),
            ("border", "border"),
            ("top_border", "topBorder"),
            ("bottom_border", "bottomBorder"),
            ("left_border", "leftBorder"),
            ("right_border", "rightBorder"),
        ):
            if src_key in cell:
                out[dst_key] = cell.get(src_key)
        return out
