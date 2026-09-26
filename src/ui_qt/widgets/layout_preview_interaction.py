from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QAbstractItemView, QApplication, QComboBox, QMenu, QTableWidgetSelectionRange

from src.ui_qt.i18n import t


class LayoutPreviewInteractionMixin:
    def _sheet_anchor(self, row: int, col: int) -> tuple[int, int]:
        merge = self._sheet_merges.get((row, col))
        if isinstance(merge, dict):
            return self._safe_int(merge.get("row"), row), self._safe_int(merge.get("col"), col)
        return row, col


    def _selected_anchor(self) -> tuple[int, int] | None:
        table = self._table
        if table is None:
            return None
        row = table.currentRow()
        col = table.currentColumn()
        if row < 0 or col < 0:
            return None
        return self._sheet_anchor(row, col)


    def _selected_anchors(self) -> list[tuple[int, int]]:
        table = self._table
        if table is None:
            return []
        anchors: set[tuple[int, int]] = set()
        for index in table.selectedIndexes():
            anchors.add(self._sheet_anchor(index.row(), index.column()))
        if not anchors:
            anchor = self._selected_anchor()
            if anchor is not None:
                anchors.add(anchor)
        return sorted(anchors)


    def _selected_rect(self) -> tuple[int, int, int, int] | None:
        table = self._table
        if table is None:
            return None
        indexes = list(table.selectedIndexes())
        if not indexes:
            anchor = self._selected_anchor()
            if anchor is None:
                return None
            row, col = anchor
            return row, col, row, col
        rows = [idx.row() for idx in indexes]
        cols = [idx.column() for idx in indexes]
        return min(rows), min(cols), max(rows), max(cols)


    def _selected_rect_label(self) -> str:
        rect = self._selected_rect()
        if rect is None:
            return ""
        top, left, bottom, right = rect
        if top == bottom and left == right:
            return f"R{top + 1}C{left + 1}"
        return f"R{top + 1}C{left + 1}:R{bottom + 1}C{right + 1}"


    def _selected_cell_info(self) -> Dict[str, Any] | None:
        anchor = self._selected_anchor()
        if anchor is None:
            return None
        row, col = anchor
        cell = dict(self._sheet_cells.get((row, col)) or {})
        cell.setdefault("row", row)
        cell.setdefault("col", col)
        fmt = self._format_for_cell(cell)
        fill_type = str(cell.get("fill_type") or fmt.get("fillType") or "")
        merge = self._sheet_merges.get((row, col))
        align = []
        h = str(fmt.get("horizontalAlignment") or "").strip()
        v = str(fmt.get("verticalAlignment") or "").strip()
        if h:
            align.append(h)
        if v:
            align.append(v)
        cell["fill_type"] = fill_type
        cell["horizontal_alignment"] = str(cell.get("horizontal_alignment") or fmt.get("horizontalAlignment") or "")
        cell["vertical_alignment"] = str(cell.get("vertical_alignment") or fmt.get("verticalAlignment") or "")
        cell["border_style"] = self._border_preset_from_fmt(fmt)
        cell["font_bold"] = bool(cell.get("font_bold"))
        cell["font_italic"] = bool(cell.get("font_italic"))
        cell["font_underline"] = bool(cell.get("font_underline"))
        cell["font_height"] = self._cell_font_height(cell)
        cell["alignment"] = " / ".join(align) if align else "—"
        cell["merge"] = (
            f'{self._safe_int(merge.get("rowspan"), 1)} x {self._safe_int(merge.get("colspan"), 1)}'
            if isinstance(merge, dict)
            else "—"
        )
        cell["selection_count"] = self._selected_anchor_count()
        cell["area_name"] = self._matched_area_name(self._selected_rect())
        return cell


    def _ensure_cell_record(self, row: int, col: int) -> Dict[str, Any]:
        cell = self._sheet_cells.get((row, col))
        if cell is None:
            cell = {
                "row": row,
                "col": col,
                "format_index": -1,
            }
            self._sheet_cells[(row, col)] = cell
            cells = self._layout_model.setdefault("cells", [])
            if isinstance(cells, list):
                cells.append(cell)
        return cell


    def _ensure_selected_cell_record(self) -> tuple[int, int, Dict[str, Any]] | None:
        anchor = self._selected_anchor()
        if anchor is None:
            return None
        row, col = anchor
        return row, col, self._ensure_cell_record(row, col)


    def _ensure_selected_cell_records(self) -> list[tuple[int, int, Dict[str, Any]]]:
        out: list[tuple[int, int, Dict[str, Any]]] = []
        for row, col in self._selected_anchors():
            out.append((row, col, self._ensure_cell_record(row, col)))
        return out


    def _rebuild_parameter_index(self) -> None:
        params: list[Dict[str, Any]] = []
        for (row, col), cell in sorted(self._sheet_cells.items()):
            if not isinstance(cell, dict):
                continue
            name = str(cell.get("parameter") or "").strip()
            if not name:
                continue
            fmt = self._format_for_cell(cell)
            params.append(
                {
                    "name": name,
                    "row": row,
                    "col": col,
                    "format_index": self._safe_int(cell.get("format_index"), -1),
                    "fill_type": str(cell.get("fill_type") or fmt.get("fillType") or ""),
                }
            )
        self._layout_model["parameters"] = params


    def _sync_selected_cell_props(self) -> None:
        self._sheet_props.set_cell(self._selected_cell_info())
        self._sync_toolbar_from_selection()


    def _on_current_cell_changed(self, current_row: int, current_col: int, _prev_row: int, _prev_col: int) -> None:
        if current_row < 0 or current_col < 0:
            self._sheet_props.set_cell(None)
            return
        apply_column_scheme = getattr(self, "_apply_column_scheme_for_row", None)
        if callable(apply_column_scheme):
            apply_column_scheme(int(current_row))
        self._sync_selected_cell_props()


    def _selected_anchor_count(self) -> int:
        table = self._table
        if table is None:
            return 0
        anchors: set[tuple[int, int]] = set()
        for index in table.selectedIndexes():
            anchors.add(self._sheet_anchor(index.row(), index.column()))
        return max(0, len(anchors))


    def _on_selection_changed(self) -> None:
        self._sync_selected_cell_props()


    def _merge_selected_cells(self) -> None:
        rect = self._selected_rect()
        table = self._table
        if rect is None or table is None:
            return
        top, left, bottom, right = rect
        if top == bottom and left == right:
            return
        self._remove_merges_intersecting(top=top, left=left, bottom=bottom, right=right)
        merges = self._layout_model.setdefault("merges", [])
        if not isinstance(merges, list):
            merges = []
            self._layout_model["merges"] = merges
        merges.append(
            {
                "row": top,
                "col": left,
                "rowspan": bottom - top + 1,
                "colspan": right - left + 1,
            }
        )
        self._rebuild_spans()
        table.setCurrentCell(top, left)
        self._schedule_persist()
        self._sync_selected_cell_props()


    def _unmerge_selected_cells(self) -> None:
        rect = self._selected_rect()
        if rect is None:
            return
        top, left, bottom, right = rect
        if not self._remove_merges_intersecting(top=top, left=left, bottom=bottom, right=right):
            return
        self._rebuild_spans()
        self._schedule_persist()
        self._sync_selected_cell_props()


    def _remove_merges_intersecting(self, *, top: int, left: int, bottom: int, right: int) -> bool:
        merges = self._layout_model.get("merges")
        if not isinstance(merges, list) or not merges:
            return False
        kept: list[dict[str, Any]] = []
        removed = False
        for merge in merges:
            if not isinstance(merge, dict):
                continue
            mr = self._safe_int(merge.get("row"), -1)
            mc = self._safe_int(merge.get("col"), -1)
            mh = max(1, self._safe_int(merge.get("rowspan"), 1))
            mw = max(1, self._safe_int(merge.get("colspan"), 1))
            mb = mr + mh - 1
            mrgt = mc + mw - 1
            intersects = not (mb < top or mr > bottom or mrgt < left or mc > right)
            if intersects:
                removed = True
                continue
            kept.append(dict(merge))
        if removed:
            self._layout_model["merges"] = kept
        return removed


    def _rebuild_spans(self) -> None:
        table = self._table
        if table is None:
            return
        table.clearSpans()
        self._sheet_merges = {}
        merges = self._layout_model.get("merges") if isinstance(self._layout_model.get("merges"), list) else []
        for merge in merges:
            if not isinstance(merge, dict):
                continue
            row = self._safe_int(merge.get("row"), -1)
            col = self._safe_int(merge.get("col"), -1)
            rowspan = max(1, self._safe_int(merge.get("rowspan"), 1))
            colspan = max(1, self._safe_int(merge.get("colspan"), 1))
            if row < 0 or col < 0:
                continue
            table.setSpan(row, col, rowspan, colspan)
            merge_info = {"row": row, "col": col, "rowspan": rowspan, "colspan": colspan}
            for r in range(row, row + rowspan):
                for c in range(col, col + colspan):
                    self._sheet_merges[(r, c)] = dict(merge_info)


    def _on_cell_property_changed(self, field: str, value: object) -> None:
        range_fields = {
            "fill_type",
            "border_style",
            "horizontal_alignment",
            "vertical_alignment",
            "font_bold",
            "font_italic",
            "font_underline",
            "font_height",
        }
        if field in range_fields:
            updated = self._ensure_selected_cell_records()
        else:
            ensured = self._ensure_selected_cell_record()
            updated = [ensured] if ensured is not None else []
        if not updated:
            return
        changed = False
        for row, col, cell in updated:
            before = dict(cell)
            if field == "fill_type":
                val = str(value or "").strip()
                if val:
                    cell["fill_type"] = val
                else:
                    cell.pop("fill_type", None)
            elif field == "border_style":
                self._apply_border_preset(cell, str(value or "").strip())
            elif field == "horizontal_alignment":
                val = str(value or "").strip()
                if val:
                    cell["horizontal_alignment"] = val
                else:
                    cell.pop("horizontal_alignment", None)
            elif field == "vertical_alignment":
                val = str(value or "").strip()
                if val:
                    cell["vertical_alignment"] = val
                else:
                    cell.pop("vertical_alignment", None)
            elif field == "font_bold":
                cell["font_bold"] = bool(value)
            elif field == "font_italic":
                cell["font_italic"] = bool(value)
            elif field == "font_underline":
                cell["font_underline"] = bool(value)
            elif field == "font_height":
                try:
                    size = int(value) if value not in (None, "") else 0
                except Exception:
                    size = 0
                if size > 0:
                    cell["font_height"] = size
                else:
                    cell.pop("font_height", None)
            elif field == "parameter":
                val = str(value or "").strip()
                if val:
                    cell["parameter"] = val
                else:
                    cell.pop("parameter", None)
            elif field == "text":
                val = str(value or "")
                if val:
                    cell["text"] = val
                else:
                    cell.pop("text", None)
            if cell == before:
                continue
            changed = True
            self._refresh_cell_item(row=row, col=col)
        if not changed:
            return
        self._rebuild_parameter_index()
        if self._table is not None:
            self._table.viewport().update()
        self._schedule_persist()
        self._sync_selected_cell_props()


    def _show_cell_context_menu(self, pos) -> None:
        table = self._table
        if table is None:
            return
        index = table.indexAt(pos)
        if index.isValid():
            self._focus_context_cell(index.row(), index.column())
        cell_info = self._selected_cell_info()
        if not isinstance(cell_info, dict):
            return

        menu = QMenu(table)
        act_props = menu.addAction(t("layout_ctx_properties"))
        act_copy = menu.addAction(t("layout_ctx_copy_text"))
        menu.addSeparator()

        type_menu = menu.addMenu(t("layout_ctx_cell_type"))
        fill_actions = {}
        current_fill = str(cell_info.get("fill_type") or "").strip().lower()
        for raw_value, label_key in (
            ("", "layout_fill_auto"),
            ("Template", "layout_fill_template"),
            ("Parameter", "layout_fill_parameter"),
            ("Value", "layout_fill_value"),
            ("Text", "layout_fill_text"),
        ):
            act = type_menu.addAction(t(label_key))
            act.setCheckable(True)
            act.setChecked(current_fill == raw_value.lower())
            fill_actions[act] = raw_value

        border_menu = menu.addMenu(t("layout_ctx_border"))
        border_actions = {}
        current_border = str(cell_info.get("border_style") or "").strip().lower()
        for raw_value, label_key in (
            ("", "layout_border_auto"),
            ("none", "layout_border_none"),
            ("solid", "layout_border_solid"),
            ("thick", "layout_border_thick"),
        ):
            act = border_menu.addAction(t(label_key))
            act.setCheckable(True)
            act.setChecked(current_border == raw_value.lower())
            border_actions[act] = raw_value

        align_menu = menu.addMenu(t("layout_ctx_alignment"))
        h_menu = align_menu.addMenu(t("layout_prop_h_align"))
        h_actions = {}
        current_h = str(cell_info.get("horizontal_alignment") or "").strip().lower()
        for raw_value, label_key in (
            ("", "layout_align_auto"),
            ("Left", "layout_align_left"),
            ("Center", "layout_align_center"),
            ("Right", "layout_align_right"),
        ):
            act = h_menu.addAction(t(label_key))
            act.setCheckable(True)
            act.setChecked(current_h == raw_value.lower())
            h_actions[act] = raw_value
        v_menu = align_menu.addMenu(t("layout_prop_v_align"))
        v_actions = {}
        current_v = str(cell_info.get("vertical_alignment") or "").strip().lower()
        for raw_value, label_key in (
            ("", "layout_align_auto"),
            ("Top", "layout_align_top"),
            ("Center", "layout_align_middle"),
            ("Bottom", "layout_align_bottom"),
        ):
            act = v_menu.addAction(t(label_key))
            act.setCheckable(True)
            act.setChecked(current_v == raw_value.lower())
            v_actions[act] = raw_value

        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_props:
            self._show_properties_dock()
            return
        if chosen is act_copy:
            QApplication.clipboard().setText(str(cell_info.get("text") or cell_info.get("parameter") or ""))
            return
        if chosen in fill_actions:
            self._on_cell_property_changed("fill_type", fill_actions[chosen])
            self._show_properties_dock()
            return
        if chosen in border_actions:
            self._on_cell_property_changed("border_style", border_actions[chosen])
            self._show_properties_dock()
            return
        if chosen in h_actions:
            self._on_cell_property_changed("horizontal_alignment", h_actions[chosen])
            self._show_properties_dock()
            return
        if chosen in v_actions:
            self._on_cell_property_changed("vertical_alignment", v_actions[chosen])
            self._show_properties_dock()
            return


    def _sync_toolbar_from_selection(self) -> None:
        self._toolbar_block = True
        try:
            cell = self._selected_cell_info() or {}
            enabled = bool(cell)
            for widget in (
                self._tool_range,
                self._tool_text,
                self._tool_fill,
                self._tool_border,
                self._tool_h_align,
                self._tool_v_align,
                self._tool_font_size,
                self._tool_bold,
                self._tool_italic,
                self._tool_underline,
                self._tool_merge,
                self._tool_unmerge,
                self._tool_area,
                self._tool_area_assign,
                self._tool_area_goto,
                self._tool_area_remove,
            ):
                if widget is not None:
                    widget.setEnabled(enabled)
            if not enabled:
                if self._tool_range is not None:
                    self._tool_range.clear()
                if self._tool_text is not None:
                    self._tool_text.clear()
                self._set_combo_data(self._tool_fill, "")
                self._set_combo_data(self._tool_border, "")
                self._set_combo_data(self._tool_h_align, "")
                self._set_combo_data(self._tool_v_align, "")
                self._set_combo_data(self._tool_font_size, "")
                for btn in (self._tool_bold, self._tool_italic, self._tool_underline):
                    if btn is not None:
                        btn.setChecked(False)
                if self._tool_area is not None:
                    self._set_area_editor_text("")
                return

            if self._tool_range is not None:
                self._tool_range.setText(self._selected_rect_label())
            if self._tool_text is not None:
                self._tool_text.setText(str(cell.get("text") or ""))
            self._set_combo_data(self._tool_fill, str(cell.get("fill_type") or ""))
            self._set_combo_data(self._tool_border, str(cell.get("border_style") or ""))
            self._set_combo_data(self._tool_h_align, str(cell.get("horizontal_alignment") or ""))
            self._set_combo_data(self._tool_v_align, str(cell.get("vertical_alignment") or ""))
            self._set_combo_data(self._tool_font_size, cell.get("font_height") or "")
            if self._tool_bold is not None:
                self._tool_bold.setChecked(bool(cell.get("font_bold")))
            if self._tool_italic is not None:
                self._tool_italic.setChecked(bool(cell.get("font_italic")))
            if self._tool_underline is not None:
                self._tool_underline.setChecked(bool(cell.get("font_underline")))
            if self._tool_area is not None:
                area_name = str(cell.get("area_name") or "")
                self._set_area_editor_text(area_name)
        finally:
            self._toolbar_block = False


    def _apply_toolbar_text(self) -> None:
        if self._toolbar_block or self._tool_text is None:
            return
        self._on_cell_property_changed("text", self._tool_text.text())


    def _apply_toolbar_toggle(self, field: str, checked: bool) -> None:
        if self._toolbar_block:
            return
        self._on_cell_property_changed(field, bool(checked))


    def _apply_toolbar_font_size(self, _index: int) -> None:
        if self._toolbar_block or self._tool_font_size is None:
            return
        self._on_cell_property_changed("font_height", self._tool_font_size.currentData())


    def _apply_toolbar_choice(self, field: str, combo: QComboBox | None) -> None:
        if self._toolbar_block or combo is None:
            return
        self._on_cell_property_changed(field, combo.currentData())


    def _focus_context_cell(self, row: int, col: int) -> None:
        table = self._table
        if table is None:
            return
        sel_model = table.selectionModel()
        if sel_model is None:
            table.setCurrentCell(row, col)
            return
        index = table.model().index(row, col)
        if not index.isValid():
            table.setCurrentCell(row, col)
            return
        if index in table.selectedIndexes():
            flags = (
                QItemSelectionModel.SelectionFlag.Current
                | QItemSelectionModel.SelectionFlag.NoUpdate
            )
        else:
            flags = (
                QItemSelectionModel.SelectionFlag.Current
                | QItemSelectionModel.SelectionFlag.ClearAndSelect
            )
        sel_model.setCurrentIndex(index, flags)


    def _show_properties_dock(self) -> None:
        p = self.parentWidget()
        while p is not None:
            set_visible = getattr(p, "set_properties_visible", None)
            route_focus = getattr(p, "_route_properties_by_focus", None)
            if callable(set_visible):
                try:
                    set_visible(True)
                except Exception:
                    pass
            if callable(route_focus):
                try:
                    route_focus(self._table or self)
                except Exception:
                    pass
                break
            p = p.parentWidget()
