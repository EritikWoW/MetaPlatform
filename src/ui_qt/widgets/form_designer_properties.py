from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QTableWidgetItem, QWidget

from src.configurator.domain.form_model import (
    FormNode,
    coerce_form_bool,
    form_node_is_visible,
    normalize_form_open_mode,
    normalize_form_window_lock_mode,
)


class FormDesignerPropertiesMixin:
    def _set_props_help_text(self, text: str) -> None:
        help_box = getattr(self, "_props_help", None)
        if help_box is None:
            return
        try:
            help_box.setPlainText(str(text or ""))
        except Exception:
            pass

    def _register_props_help(self, field: QWidget, text: str) -> None:
        mapping = getattr(self, "_props_help_map", None)
        if not isinstance(mapping, dict):
            mapping = {}
            self._props_help_map = mapping
        mapping[field] = str(text or "")
        try:
            field.installEventFilter(self)
        except Exception:
            pass

    def eventFilter(self, watched: object, event: object) -> bool:
        mapping = getattr(self, "_props_help_map", None)
        if isinstance(mapping, dict) and watched in mapping and isinstance(event, QEvent):
            if event.type() == QEvent.Type.FocusIn:
                self._set_props_help_text(str(mapping.get(watched) or ""))
        return super().eventFilter(watched, event)

    def _set_form_row_visible(self, field: QWidget, visible: bool) -> None:
        try:
            label = self._form_layout.labelForField(field)
            if isinstance(label, QWidget):
                label.setVisible(bool(visible))
        except Exception:
            pass
        field.setVisible(bool(visible))

    def _on_tree_selection(self, current: Optional[object], _prev: Optional[object]) -> None:
        if self._ui_guard:
            return
        node = self._current_node()
        if node is None:
            self._set_props_help_text("")
            return

        try:
            self.canvas.select_node(node.id)
        except Exception:
            pass
        self._highlight_design_preview(node.id)
        self._set_props_help_text("")

        self._ui_guard = True
        try:
            self._ed_form_title.setText(str(self._model.title or ""))
            self._ed_name.setText(node.name)
            self._ed_title.setText(node.title)
            self._ed_binding.setText(node.binding)

            is_container = node.type == "Container"
            is_table = node.type == "Table"
            is_button = node.type == "Button"
            is_decoration = node.type == "Label" and coerce_form_bool(
                (node.props or {}).get("is_decoration"), default=False
            )
            is_root = node.id == self._model.root.id
            supports_binding = node.type in {"TextBox", "TextArea", "NumberBox", "CheckBox", "ComboBox", "DateBox", "Table"}
            supports_group_display = is_container
            supports_title_location = node.type in {"TextBox", "TextArea", "NumberBox", "ComboBox", "DateBox", "Table"}
            supports_width_chars = node.type in {"TextBox", "TextArea", "NumberBox", "ComboBox", "DateBox"} or is_decoration
            supports_height_rows = node.type in {"TextArea"} or is_decoration
            supports_stretch = node.type in {"TextBox", "TextArea", "NumberBox", "ComboBox", "DateBox", "Table"} or is_decoration
            parent = self._parent_node(node.id)
            parent_layout = str((parent.props or {}).get("layout") or "vertical").strip().lower() if parent else ""
            supports_group_anchor = not is_root and parent_layout in {"vertical", "horizontal"}

            self._set_form_row_visible(self._ed_form_title, is_root)
            self._set_form_row_visible(self._ed_binding, supports_binding)
            self._set_form_row_visible(self._cb_open_mode, is_root)
            self._set_form_row_visible(self._cb_window_lock_mode, is_root)
            self._set_form_row_visible(self._cb_layout, is_container)
            self._set_form_row_visible(self._cb_representation, supports_group_display)
            self._set_form_row_visible(self._chk_show_title, supports_group_display)
            self._set_form_row_visible(self._cb_title_location, supports_title_location)
            self._set_form_row_visible(self._cb_group_anchor, supports_group_anchor)
            self._set_form_row_visible(self._sp_width_chars, supports_width_chars)
            self._set_form_row_visible(self._sp_height_rows, supports_height_rows)
            self._set_form_row_visible(self._chk_visible, not is_root)
            self._set_form_row_visible(self._cb_decoration_kind, is_decoration)
            self._set_form_row_visible(self._chk_enabled, is_decoration)
            self._set_form_row_visible(self._ed_tooltip, is_decoration)
            self._set_form_row_visible(self._cb_decoration_halign, is_decoration)
            self._set_form_row_visible(self._cb_decoration_valign, is_decoration)
            self._set_form_row_visible(self._chk_hstretch, supports_stretch)
            self._set_form_row_visible(self._chk_vstretch, supports_stretch)
            self._set_form_row_visible(self._ed_command, is_button)

            self._cb_layout.setEnabled(is_container)
            open_mode = normalize_form_open_mode((node.props or {}).get("open_mode"))
            open_mode_idx = self._cb_open_mode.findData(open_mode)
            self._cb_open_mode.setCurrentIndex(open_mode_idx if open_mode_idx >= 0 else 0)
            lock_mode = normalize_form_window_lock_mode((node.props or {}).get("window_lock_mode"))
            lock_mode_idx = self._cb_window_lock_mode.findData(lock_mode)
            self._cb_window_lock_mode.setCurrentIndex(lock_mode_idx if lock_mode_idx >= 0 else 0)
            self._cb_window_lock_mode.setEnabled(is_root and open_mode == "window")
            layout = str((node.props or {}).get("layout") or "vertical").strip().lower()
            idx = self._cb_layout.findText(layout)
            self._cb_layout.setCurrentIndex(idx if idx >= 0 else 0)

            grid_cols = int((node.props or {}).get("grid_columns") or 2)
            self._sp_grid_cols.setValue(grid_cols)
            self._set_form_row_visible(self._sp_grid_cols, is_container and layout == "grid")
            self._lbl_table_columns.setVisible(is_table)
            self._tbl_columns.setVisible(is_table)
            rep = str((node.props or {}).get("representation") or "").strip().lower()
            rep_idx = self._cb_representation.findData(rep)
            self._cb_representation.setCurrentIndex(rep_idx if rep_idx >= 0 else 0)
            self._chk_show_title.setChecked(bool((node.props or {}).get("show_title", True)))
            title_location = str((node.props or {}).get("title_location") or "left").strip().lower()
            tl_idx = self._cb_title_location.findData(title_location)
            self._cb_title_location.setCurrentIndex(tl_idx if tl_idx >= 0 else 0)
            group_anchor = self._normalize_group_anchor((node.props or {}).get("group_anchor"))
            ga_idx = self._cb_group_anchor.findData(group_anchor)
            self._cb_group_anchor.setCurrentIndex(ga_idx if ga_idx >= 0 else 0)
            self._sp_width_chars.setValue(int((node.props or {}).get("width_chars") or 0))
            self._sp_height_rows.setValue(int((node.props or {}).get("height_rows") or 0))
            self._chk_visible.setChecked(form_node_is_visible(node))
            decoration_kind = str((node.props or {}).get("decoration_kind") or "label").strip().lower()
            decoration_idx = self._cb_decoration_kind.findData(decoration_kind)
            self._cb_decoration_kind.setCurrentIndex(decoration_idx if decoration_idx >= 0 else 0)
            self._chk_enabled.setChecked(coerce_form_bool((node.props or {}).get("enabled"), default=True))
            self._ed_tooltip.setText(str((node.props or {}).get("tooltip") or (node.props or {}).get("tool_tip") or ""))
            halign = str((node.props or {}).get("horizontal_alignment") or (node.props or {}).get("horizontal_position") or "left").strip().lower()
            halign_idx = self._cb_decoration_halign.findData(halign)
            self._cb_decoration_halign.setCurrentIndex(halign_idx if halign_idx >= 0 else 0)
            valign = str((node.props or {}).get("vertical_alignment") or (node.props or {}).get("vertical_position") or "center").strip().lower()
            valign_idx = self._cb_decoration_valign.findData(valign)
            self._cb_decoration_valign.setCurrentIndex(valign_idx if valign_idx >= 0 else 1)
            self._chk_hstretch.setChecked(bool((node.props or {}).get("horizontal_stretch")))
            self._chk_vstretch.setChecked(bool((node.props or {}).get("vertical_stretch")))
            self._ed_command.setText(str((node.props or {}).get("command") or ""))

            self._grp_canvas.setVisible(is_root)
            if is_root:
                rw = int((node.props or {}).get("w") or 1000)
                rh = int((node.props or {}).get("h") or 700)
                self._sp_canvas_w.setValue(rw)
                self._sp_canvas_h.setValue(rh)

            parent = self._parent_node(node.id)
            parent_layout = str((parent.props or {}).get("layout") or "vertical").strip().lower() if parent else ""
            self._grp_geom.setVisible(bool(parent and parent_layout == "absolute"))
            self._sync_geometry_to_ui(node)
            self._grp_gridpos.setVisible(bool(parent and parent_layout == "grid"))
            self._sync_gridpos_to_ui(node)
            self._load_columns(node)
        finally:
            self._ui_guard = False

    def _sync_geometry_to_ui(self, node: FormNode) -> None:
        if not self._grp_geom.isVisible():
            return
        props = node.props or {}
        self._sp_x.setValue(int(props.get("x") or 0))
        self._sp_y.setValue(int(props.get("y") or 0))
        self._sp_w.setValue(int(props.get("w") or 10))
        self._sp_h.setValue(int(props.get("h") or 10))

    def _sync_gridpos_to_ui(self, node: FormNode) -> None:
        if not self._grp_gridpos.isVisible():
            return
        gp = node.props.get("grid") if isinstance(node.props.get("grid"), dict) else {}
        self._sp_row.setValue(int(gp.get("row") or 0))
        self._sp_col.setValue(int(gp.get("col") or 0))
        self._sp_rowspan.setValue(int(gp.get("rowspan") or 1))
        self._sp_colspan.setValue(int(gp.get("colspan") or 1))

    def _focus_properties_for_node(self, node_id: str) -> None:
        nid = str(node_id or "").strip()
        if not nid:
            return
        node = self._node_by_id.get(nid)
        if node is None:
            return

        try:
            self.properties_widget()
        except Exception:
            pass

        target = None
        if node.id == self._model.root.id:
            target = self._ed_form_title
        elif node.type == "Container":
            target = self._cb_layout if self._cb_layout.isVisible() else self._ed_name
        elif node.type in {"TextBox", "TextArea", "NumberBox", "ComboBox", "DateBox", "Table"}:
            target = self._ed_binding if self._ed_binding.isVisible() else self._ed_title
        elif node.type == "Button":
            target = self._ed_command if self._ed_command.isVisible() else self._ed_title
        else:
            target = self._ed_name if self._ed_name.isVisible() else self._ed_title

        try:
            if target is not None:
                props_widget = getattr(self, "_props_widget", None)
                if props_widget is not None:
                    try:
                        props_widget.setFocusProxy(target)
                    except Exception:
                        pass
                def _apply_focus() -> None:
                    try:
                        target.setFocus(Qt.FocusReason.ShortcutFocusReason)
                        if hasattr(target, "selectAll"):
                            target.selectAll()
                    except Exception:
                        pass

                QTimer.singleShot(0, _apply_focus)
        except Exception:
            pass

    def _on_prop_changed(self) -> None:
        if self._ui_guard or not self._is_edit_enabled():
            return
        node = self._current_node()
        if node is None:
            return

        node.name = self._ed_name.text()
        node.title = self._ed_title.text()
        node.binding = self._ed_binding.text()
        props = node.props if isinstance(node.props, dict) else {}

        if node.id == self._model.root.id:
            props.pop("visible", None)
            open_mode = normalize_form_open_mode(self._cb_open_mode.currentData())
            if open_mode == "auto":
                props.pop("open_mode", None)
            else:
                props["open_mode"] = open_mode

            lock_mode = normalize_form_window_lock_mode(self._cb_window_lock_mode.currentData())
            if open_mode != "window" or lock_mode == "none":
                props.pop("window_lock_mode", None)
            else:
                props["window_lock_mode"] = lock_mode
            self._cb_window_lock_mode.setEnabled(open_mode == "window")
        else:
            props["visible"] = bool(self._chk_visible.isChecked())

        is_decoration = node.type == "Label" and coerce_form_bool(props.get("is_decoration"), default=False)
        if is_decoration:
            props["decoration_kind"] = str(self._cb_decoration_kind.currentData() or "label")
            props["layout_spacer"] = not bool(node.title.strip()) and props["decoration_kind"] == "label"
            props["enabled"] = bool(self._chk_enabled.isChecked())
            tooltip = str(self._ed_tooltip.text() or "").strip()
            if tooltip:
                props["tooltip"] = tooltip
            else:
                props.pop("tooltip", None)
                props.pop("tool_tip", None)
            props["horizontal_alignment"] = str(self._cb_decoration_halign.currentData() or "left")
            props["vertical_alignment"] = str(self._cb_decoration_valign.currentData() or "center")

        rep = self._cb_representation.currentData()
        if node.type == "Container":
            if rep:
                props["representation"] = str(rep)
            else:
                props.pop("representation", None)
            props["show_title"] = bool(self._chk_show_title.isChecked())
        else:
            props.pop("representation", None)

        if node.type in {"TextBox", "TextArea", "NumberBox", "ComboBox", "DateBox", "Table"}:
            title_location = str(self._cb_title_location.currentData() or "left")
            if title_location == "left":
                props.pop("title_location", None)
            else:
                props["title_location"] = title_location
        else:
            props.pop("title_location", None)

        parent = self._parent_node(node.id)
        parent_layout = str((parent.props or {}).get("layout") or "vertical").strip().lower() if parent else ""
        if parent_layout in {"vertical", "horizontal"} and node.id != self._model.root.id:
            group_anchor = self._normalize_group_anchor(self._cb_group_anchor.currentData())
            if group_anchor:
                props["group_anchor"] = group_anchor
            else:
                props.pop("group_anchor", None)
        else:
            props.pop("group_anchor", None)

        if node.type in {"TextBox", "TextArea", "NumberBox", "ComboBox", "DateBox"} or is_decoration:
            width_chars = int(self._sp_width_chars.value())
            if width_chars > 0:
                props["width_chars"] = width_chars
            else:
                props.pop("width_chars", None)
        else:
            props.pop("width_chars", None)

        if node.type == "TextArea" or is_decoration:
            height_rows = int(self._sp_height_rows.value())
            if height_rows > 0:
                props["height_rows"] = height_rows
            else:
                props.pop("height_rows", None)
        else:
            props.pop("height_rows", None)

        if node.type in {"TextBox", "TextArea", "NumberBox", "ComboBox", "DateBox", "Table"} or is_decoration:
            props["horizontal_stretch"] = bool(self._chk_hstretch.isChecked())
            props["vertical_stretch"] = bool(self._chk_vstretch.isChecked())
        else:
            props.pop("horizontal_stretch", None)
            props.pop("vertical_stretch", None)

        if node.type == "Button":
            command = str(self._ed_command.text() or "").strip()
            if command:
                props["command"] = command
            else:
                props.pop("command", None)
        else:
            props.pop("command", None)

        if node.type == "Container":
            new_layout = self._cb_layout.currentText()
            props["layout"] = new_layout
            if new_layout == "grid":
                props["grid_columns"] = int(self._sp_grid_cols.value())
            else:
                props.pop("grid_columns", None)

        self._set_dirty(True)
        self._rebuild_tree(keep_selected_id=node.id)
        self._refresh_canvas()
        self._render_preview()

    def _on_form_title_changed(self) -> None:
        if self._ui_guard or not self._is_edit_enabled():
            return
        self._model.title = str(self._ed_form_title.text() or "")
        self._set_dirty(True)
        self._update_window_frames()

    def _update_window_frames(self) -> None:
        try:
            root_props = self._model.root.props or {}
            w = int(root_props.get("w") or 1000)
            h = int(root_props.get("h") or 700)
            title = str(self._model.title or "")

            try:
                self._design_window_frame.set_window_title(title)
                self._design_window_frame.set_client_size(w, h)
            except Exception:
                pass
            try:
                self._preview_window_frame.set_window_title(title)
                self._preview_window_frame.set_client_size(w, h)
            except Exception:
                pass
            try:
                self._design_stack.setMinimumWidth(0)
                self._design_stack.setMaximumWidth(w)
                self._design_stack.setFixedHeight(h)
                self._design_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            except Exception:
                pass
            try:
                self.preview_scroll.setMinimumWidth(0)
                self.preview_scroll.setMaximumWidth(w)
                self.preview_scroll.setFixedHeight(h)
                self.preview_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            except Exception:
                pass
            try:
                self.canvas.setMinimumWidth(0)
                self.canvas.setMaximumWidth(w)
                self.canvas.setFixedHeight(h)
                self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.canvas.update_responsive_transform()
            except Exception:
                pass
        except Exception:
            pass

    def _on_canvas_size_changed(self) -> None:
        if self._ui_guard or not self._is_edit_enabled():
            return
        root = self._model.root
        root.props["w"] = int(self._sp_canvas_w.value())
        root.props["h"] = int(self._sp_canvas_h.value())
        self._set_dirty(True)
        self._update_window_frames()
        self._refresh_canvas()
        self._render_preview()

    def _on_canvas_root_size_changed(self, w: int, h: int, finalize: bool) -> None:
        if self._ui_guard or not self._is_edit_enabled():
            return
        w = int(w)
        h = int(h)
        self._ui_guard = True
        try:
            self._sp_canvas_w.setValue(w)
            self._sp_canvas_h.setValue(h)
        finally:
            self._ui_guard = False

        root = self._model.root
        root.props["w"] = w
        root.props["h"] = h
        self._update_window_frames()

        if finalize:
            self._set_dirty(True)
            self._refresh_canvas()
            self._render_preview()

    def _on_geometry_spin_changed(self) -> None:
        if self._ui_guard or not self._is_edit_enabled() or not self._grp_geom.isVisible():
            return
        node = self._current_node()
        if node is None:
            return
        node.props["x"] = int(self._sp_x.value())
        node.props["y"] = int(self._sp_y.value())
        node.props["w"] = int(self._sp_w.value())
        node.props["h"] = int(self._sp_h.value())
        self._set_dirty(True)
        self._refresh_canvas()
        self._render_preview()

    def _on_gridpos_spin_changed(self) -> None:
        if self._ui_guard or not self._is_edit_enabled() or not self._grp_gridpos.isVisible():
            return
        node = self._current_node()
        if node is None:
            return
        node.props["grid"] = {
            "row": int(self._sp_row.value()),
            "col": int(self._sp_col.value()),
            "rowspan": int(self._sp_rowspan.value()),
            "colspan": int(self._sp_colspan.value()),
        }
        self._set_dirty(True)
        self._render_preview()

    def _load_columns(self, node: FormNode) -> None:
        self._tbl_columns.blockSignals(True)
        try:
            self._tbl_columns.setRowCount(0)
            if node.type != "Table":
                self._tbl_columns.setEnabled(False)
                return
            self._tbl_columns.setEnabled(self._is_edit_enabled())
            cols = node.props.get("columns") if isinstance(node.props.get("columns"), list) else []
            for col in cols:
                row = self._tbl_columns.rowCount()
                self._tbl_columns.insertRow(row)
                self._tbl_columns.setItem(row, 0, QTableWidgetItem(str(col)))
            row = self._tbl_columns.rowCount()
            self._tbl_columns.insertRow(row)
            self._tbl_columns.setItem(row, 0, QTableWidgetItem(""))
        finally:
            self._tbl_columns.blockSignals(False)

    def _on_columns_changed(self) -> None:
        if self._ui_guard:
            return
        node = self._current_node()
        if node is None or node.type != "Table" or not self._is_edit_enabled():
            return
        cols: list[str] = []
        for row in range(self._tbl_columns.rowCount()):
            it = self._tbl_columns.item(row, 0)
            val = str(it.text() if it else "").strip()
            if val:
                cols.append(val)
        node.props["columns"] = cols
        self._set_dirty(True)
        self._render_preview()
