from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QListWidgetItem, QSizePolicy, QWidget

from src.configurator.domain.form_model import FormNode
from src.ui_qt.i18n import t
from src.ui_qt.theme import BG, BORDER, FG, PANEL, PANEL_2, SUBTLE


class FormDesignerStylingMixin:
    def _apply_designer_chrome(self) -> None:
        """Apply a coherent visual language for the form designer."""

        try:
            self.setStyleSheet(
                f"""
                QWidget#FormDesignerRoot {{
                    background: {BG};
                }}

                QSplitter#FormDesignerWorkbenchSplit::handle,
                QSplitter#FormDesignerTopSplit::handle {{
                    background: {BORDER};
                }}

                QTabWidget#FormDesignerLeftTabs::pane,
                QTabWidget#FormDesignerObjectTabs::pane,
                QTabWidget#FormDesignerCommandScopeTabs::pane,
                QTabWidget#FormDesignerCenterTabs::pane,
                QWidget#FormDesignerProps {{
                    border: 1px solid {BORDER};
                    border-radius: 6px;
                    background: {PANEL};
                }}

                QTabWidget#FormDesignerLeftTabs QTabBar::tab,
                QTabWidget#FormDesignerObjectTabs QTabBar::tab,
                QTabWidget#FormDesignerCommandScopeTabs QTabBar::tab,
                QTabWidget#FormDesignerCenterTabs QTabBar::tab {{
                    background: transparent;
                    color: {SUBTLE};
                    border: none;
                    padding: 7px 10px;
                    margin: 2px 2px 0 0;
                    border-top-left-radius: 5px;
                    border-top-right-radius: 5px;
                }}

                QTabWidget#FormDesignerLeftTabs QTabBar::tab:selected,
                QTabWidget#FormDesignerObjectTabs QTabBar::tab:selected,
                QTabWidget#FormDesignerCommandScopeTabs QTabBar::tab:selected,
                QTabWidget#FormDesignerCenterTabs QTabBar::tab:selected {{
                    color: {FG};
                    background: {PANEL_2};
                }}

                QWidget#FormDesignerCenterHost {{
                    background: transparent;
                }}

                QStackedWidget#FormDesignerCenterStack {{
                    border: 1px solid {BORDER};
                    border-radius: 6px;
                    background: {PANEL};
                }}

                QFrame#FormDesignerModeBar {{
                    background: {PANEL};
                    border: 1px solid {BORDER};
                    border-radius: 6px;
                }}

                QTabBar#FormDesignerModeTabs::tab {{
                    background: transparent;
                    color: {SUBTLE};
                    border: 1px solid transparent;
                    border-radius: 5px;
                    padding: 6px 14px;
                    min-width: 96px;
                }}

                QTabBar#FormDesignerModeTabs::tab:hover {{
                    color: {FG};
                    background: {PANEL_2};
                    border-color: {BORDER};
                }}

                QTabBar#FormDesignerModeTabs::tab:selected {{
                    color: {FG};
                    background: rgba(91, 91, 214, 0.20);
                    border-color: rgba(91, 91, 214, 0.55);
                }}

                QToolButton#FormDesignerPaneToggle {{
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 5px;
                    padding: 5px;
                }}

                QToolButton#FormDesignerPaneToggle:hover {{
                    background: {PANEL_2};
                    border-color: {BORDER};
                }}

                QLabel#FormDesignerHint {{
                    color: {FG};
                    background: {PANEL};
                    border: 1px solid {BORDER};
                    border-radius: 6px;
                    padding: 7px 10px;
                }}

                QLabel#FormDesignerPanelTitle {{
                    color: {FG};
                    font-size: 14px;
                    font-weight: 600;
                    padding: 2px 0 6px 2px;
                }}

                QListWidget#FormDesignerToolbox,
                QTreeWidget#FormDesignerRequisites,
                QTreeWidget#FormDesignerCommandInterface,
                QTabWidget#FormDesignerObjectTabs QTreeWidget,
                QTreeWidget#FormDesignerStructure,
                QWidget#FormDesignerProps QTableWidget,
                QWidget#FormDesignerProps QLineEdit,
                QWidget#FormDesignerProps QComboBox,
                QWidget#FormDesignerProps QSpinBox,
                QWidget#FormDesignerProps QPlainTextEdit {{
                    background: {PANEL_2};
                    color: {FG};
                    border: 1px solid {BORDER};
                    border-radius: 5px;
                }}

                QWidget#FormDesignerPropsBody QLabel,
                QWidget#FormDesignerPropsBody QGroupBox {{
                    color: {FG};
                }}

                QListWidget#FormDesignerToolbox::item,
                QTreeWidget#FormDesignerRequisites::item,
                QTreeWidget#FormDesignerCommandInterface::item,
                QTabWidget#FormDesignerObjectTabs QTreeWidget::item,
                QTreeWidget#FormDesignerStructure::item {{
                    min-height: 18px;
                    border-radius: 3px;
                    padding: 2px 6px;
                    margin: 0 2px;
                }}

                QListWidget#FormDesignerToolbox::item:selected,
                QTreeWidget#FormDesignerRequisites::item:selected,
                QTreeWidget#FormDesignerCommandInterface::item:selected,
                QTabWidget#FormDesignerObjectTabs QTreeWidget::item:selected,
                QTreeWidget#FormDesignerStructure::item:selected {{
                    background: rgba(91, 91, 214, 0.22);
                    color: {FG};
                }}

                QToolBar#FormDesignToolbar {{
                    background: {PANEL};
                    border: 1px solid {BORDER};
                    border-radius: 6px;
                    spacing: 6px;
                    padding: 4px;
                }}

                QToolBar#FormElementsToolbar {{
                    background: {PANEL};
                    border: none;
                    border-bottom: 1px solid {BORDER};
                    spacing: 4px;
                    padding: 4px;
                }}

                QToolBar#FormDesignToolbar QLabel {{
                    color: {SUBTLE};
                    padding: 0 6px;
                }}

                QToolBar#FormDesignToolbar QToolButton {{
                    background: transparent;
                    color: {FG};
                    border: 1px solid transparent;
                    border-radius: 5px;
                    padding: 5px 8px;
                }}

                QToolBar#FormDesignToolbar QToolButton:hover {{
                    background: {PANEL_2};
                    border-color: {BORDER};
                }}

                QToolBar#FormDesignToolbar QToolButton:checked {{
                    background: rgba(91, 91, 214, 0.18);
                    border-color: rgba(91, 91, 214, 0.55);
                }}

                QWidget#FormDesignerProps QLabel,
                QWidget#FormDesignerProps QGroupBox {{
                    color: {FG};
                }}

                QWidget#FormDesignerProps QGroupBox {{
                    border: 1px solid {BORDER};
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 10px;
                    background: {PANEL};
                }}

                QWidget#FormDesignerProps QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 6px;
                    color: {SUBTLE};
                }}

                QWidget#FormDesignerProps QHeaderView::section {{
                    background: {PANEL};
                    color: {SUBTLE};
                    border: none;
                    border-bottom: 1px solid {BORDER};
                    padding: 8px;
                }}

                QScrollArea#CanvasScroll {{
                    background: transparent;
                    border: none;
                }}

                QGraphicsView#FormCanvas {{
                    background: rgba(255,255,255,0.96);
                    border: 1px solid rgba(255,255,255,0.10);
                    border-radius: 6px;
                }}
                """
            )
        except Exception:
            pass

    def _node_type_i18n_key(self, node_type: str) -> str:
        return {
            "Label": "form_ctl_label",
            "Picture": "form_ctl_picture",
            "TextBox": "form_ctl_textbox",
            "TextArea": "form_ctl_textarea",
            "NumberBox": "form_ctl_numberbox",
            "DateBox": "form_ctl_datebox",
            "ComboBox": "form_ctl_combobox",
            "CheckBox": "form_ctl_checkbox",
            "Button": "form_ctl_button",
            "Table": "form_ctl_table",
            "Container": "form_ctl_container",
            "Tabs": "form_ctl_tabs",
            "CommandBar": "form_ctl_command_bar",
            "TablePanel": "form_ctl_table_panel",
            "StatusBar": "form_ctl_status_bar",
        }.get(str(node_type or "").strip(), "")

    def _node_type_caption(self, node_type: str) -> str:
        key = self._node_type_i18n_key(node_type)
        return t(key) if key else str(node_type or "").strip()

    def _normalize_group_anchor(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"", "auto"}:
            return ""
        if raw in {"start", "left", "top", "початок", "слева", "верх", "ліворуч", "зверху"}:
            return "start"
        if raw in {"center", "centre", "центр"}:
            return "center"
        if raw in {"end", "right", "bottom", "кінець", "справа", "праворуч", "низ", "знизу"}:
            return "end"
        if raw in {"stretch", "fill", "розтягнути", "растянуть"}:
            return "stretch"
        return ""

    def _normalize_title_location(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"none", "нет"}:
            return "none"
        if raw in {"top", "верх"}:
            return "top"
        return "left"

    def _form_surface_stylesheet(self) -> str:
        return """
        QLineEdit[mp_form_editor="true"],
        QTextEdit[mp_form_editor="true"],
        QPlainTextEdit[mp_form_editor="true"],
        QComboBox[mp_form_editor="true"],
        QDateEdit[mp_form_editor="true"],
        QAbstractSpinBox[mp_form_editor="true"] {
            border: 1px solid rgba(255,255,255,0.18);
            border-radius: 4px;
            padding: 2px 6px;
            min-height: 24px;
        }
        QLineEdit[mp_form_editor="true"]:focus,
        QTextEdit[mp_form_editor="true"]:focus,
        QPlainTextEdit[mp_form_editor="true"]:focus,
        QComboBox[mp_form_editor="true"]:focus,
        QDateEdit[mp_form_editor="true"]:focus,
        QAbstractSpinBox[mp_form_editor="true"]:focus {
            border: 1px solid #5B5BD6;
        }
        QAbstractSpinBox[mp_form_editor="true"]::up-button,
        QAbstractSpinBox[mp_form_editor="true"]::down-button {
            width: 0; border: none; background: transparent;
        }
        QToolButton[mp_form_field_action="true"] {
            border: 1px solid rgba(255,255,255,0.18);
            border-radius: 3px;
            min-width: 22px; max-width: 22px;
            min-height: 24px;
            padding: 0;
        }
        QToolButton[mp_form_field_action="true"]:hover {
            border-color: #5B5BD6;
        }
        QPushButton[mp_form_command="true"] {
            border-radius: 4px;
            padding: 4px 10px;
            min-height: 24px;
        }
        QPushButton[mp_form_command="true"][mp_primary_command="true"] {
            font-weight: 600;
        }
        QTabWidget[mp_form_tabs="true"]::pane {
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 0px;
            top: -1px;
        }
        QTabWidget[mp_form_tabs="true"] QTabBar::tab {
            border: 1px solid rgba(255,255,255,0.12);
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            padding: 4px 14px;
            margin-right: 2px;
        }
        QTabWidget[mp_form_tabs="true"] QTabBar::tab:selected {
            border-bottom: 1px solid transparent;
        }
        QTableView[mp_form_table="true"],
        QTableWidget[mp_form_table="true"] {
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 0px;
            gridline-color: rgba(255,255,255,0.08);
            selection-background-color: #5B5BD6;
            selection-color: #ffffff;
        }
        QTableView[mp_form_table="true"] QHeaderView::section,
        QTableWidget[mp_form_table="true"] QHeaderView::section {
            border: none;
            border-right: 1px solid rgba(255,255,255,0.08);
            border-bottom: 1px solid rgba(255,255,255,0.12);
            padding: 4px 8px;
            font-weight: 600;
        }
        QFrame[mp_form_cmdbar="true"] {
            border: none;
            border-bottom: 1px solid rgba(255,255,255,0.10);
        }
        QFrame[mp_form_statusbar="true"] {
            border: none;
            border-top: 1px solid rgba(255,255,255,0.10);
        }
        """

    def _layout_alignment_for_parent(
        self,
        node: FormNode,
        parent_layout: str,
        widget: QWidget,
    ) -> Optional[Qt.AlignmentFlag]:
        props = node.props if isinstance(node.props, dict) else {}
        anchor = self._normalize_group_anchor(props.get("group_anchor") or props.get("anchor"))

        if parent_layout == "vertical":
            if anchor == "stretch":
                widget.setSizePolicy(QSizePolicy.Policy.Expanding, widget.sizePolicy().verticalPolicy())
                return None
            if anchor == "center":
                return Qt.AlignmentFlag.AlignHCenter
            if anchor == "end":
                return Qt.AlignmentFlag.AlignRight
            if anchor == "start":
                return Qt.AlignmentFlag.AlignLeft
            if bool(props.get("horizontal_stretch")):
                return None
            return Qt.AlignmentFlag.AlignLeft

        if parent_layout == "horizontal":
            if anchor == "stretch":
                widget.setSizePolicy(widget.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Expanding)
                return None
            if anchor == "center":
                return Qt.AlignmentFlag.AlignVCenter
            if anchor == "end":
                return Qt.AlignmentFlag.AlignBottom
            if anchor == "start":
                return Qt.AlignmentFlag.AlignTop
            if bool(props.get("vertical_stretch")):
                return None
            return Qt.AlignmentFlag.AlignVCenter

        return None

    def _field_title_mode(self, node: FormNode) -> str:
        if str(node.type or "").strip() not in {"TextBox", "TextArea", "NumberBox", "ComboBox", "DateBox", "Table"}:
            return "none"
        title = str(node.title or node.name or node.binding or "").strip()
        if not title:
            return "none"
        raw = str((node.props or {}).get("title_location") or "left")
        return self._normalize_title_location(raw)

    def _field_prefers_expanding_width(self, node: FormNode) -> bool:
        props = node.props if isinstance(node.props, dict) else {}
        if bool(props.get("horizontal_stretch")):
            return True
        return str(node.type or "").strip() in {
            "TextBox",
            "TextArea",
            "ComboBox",
            "Table",
            "CommandBar",
            "TablePanel",
            "StatusBar",
        }

    def _group_left_title_width(self, children: list[FormNode]) -> int:
        widths: list[int] = []
        for child in children:
            if self._field_title_mode(child) != "left":
                continue
            text = str(child.title or child.name or child.binding or "").strip() + ":"
            if not text.strip(":"):
                continue
            sample = QLabel(text)
            widths.append(max(96, min(320, sample.fontMetrics().horizontalAdvance(text) + 12)))
        return max(widths, default=96)

    def _make_field_title_label(
        self,
        node: FormNode,
        *,
        with_colon: bool,
        fixed_width: Optional[int] = None,
    ) -> QLabel:
        title = str(node.title or node.name or node.binding or "").strip()
        lbl = QLabel(title + (":" if with_colon else ""))
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if with_colon:
            label_w = int(fixed_width or max(96, min(320, lbl.fontMetrics().horizontalAdvance(lbl.text()) + 12)))
            lbl.setFixedWidth(label_w)
        return lbl

    def _reset_combo_items(self, combo: QComboBox, items: list[tuple[str, object]]) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        try:
            combo.clear()
            for text, data in items:
                combo.addItem(str(text), data)
            idx = combo.findData(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def _retranslate_ui(self) -> None:
        current_id = ""
        try:
            node = self._current_node()
            current_id = str(node.id or "") if node is not None else ""
        except Exception:
            current_id = ""

        try:
            self._left_tabs.setTabText(0, t("form_tab_elements"))
            self._left_tabs.setTabText(1, t("form_tab_command_interface"))
            self._object_tabs.setTabText(0, t("form_tab_requisites"))
            self._object_tabs.setTabText(1, t("form_tab_commands"))
            self._object_tabs.setTabText(2, t("form_tab_parameters"))
            self._command_scope_tabs.setTabText(0, t("form_commands_form"))
            self._command_scope_tabs.setTabText(1, t("form_commands_standard"))
            self._command_scope_tabs.setTabText(2, t("form_commands_global"))
        except Exception:
            pass

        try:
            self._center_stack.setTabText(0, t("form_tab_design"))
            self._center_stack.setTabText(1, t("form_tab_module"))
            self.requisites.setHeaderLabels(
                [
                    t("form_col_requisite"),
                    t("form_col_use_always"),
                    t("form_col_type"),
                ]
            )
            for tree in (self._form_commands_tree, self._standard_commands_tree, self._global_commands_tree):
                tree.setHeaderLabels([t("form_col_command"), t("form_col_action")])
            self._parameters_tree.setHeaderLabels([t("form_col_parameter"), t("form_col_type")])
        except Exception:
            pass

        try:
            self._act_snap_grid.setText(t("form_snap_to_grid"))
            self._act_align_left.setText(t("form_align_left"))
            self._act_align_right.setText(t("form_align_right"))
            self._act_align_top.setText(t("form_align_top"))
            self._act_align_bottom.setText(t("form_align_bottom"))
            self._lbl_design_grid.setText(t("form_grid_size"))
            self._module_editor.setPlaceholderText(t("form_module_placeholder"))
            self._props_title.setText(t("form_properties"))
            left_key = "form_hide_structure" if self._left_tabs.isVisible() else "form_show_structure"
            props_key = "form_hide_properties" if self._props_widget.isVisible() else "form_show_properties"
            self._btn_toggle_left.setToolTip(t(left_key))
            self._btn_toggle_left.setAccessibleName(t(left_key))
            self._btn_toggle_props.setToolTip(t(props_key))
            self._btn_toggle_props.setAccessibleName(t(props_key))
            for button, key in (
                (self._btn_add_field, "form_add_text_field"),
                (self._btn_add_selected, "form_add_selected_tool"),
                (self._btn_add_label, "form_add_label"),
                (self._btn_delete_node, "form_delete_selected"),
                (self._btn_duplicate_node, "form_duplicate_selected"),
                (self._btn_move_up, "form_move_selected_up"),
                (self._btn_move_down, "form_move_selected_down"),
            ):
                button.setToolTip(t(key))
                button.setAccessibleName(t(key))
        except Exception:
            pass

        row_labels = [
            (self._ed_form_title, "form_window_title"),
            (self._ed_name, "lbl_name"),
            (self._ed_title, "lbl_title"),
            (self._ed_binding, "form_binding"),
            (self._cb_open_mode, "form_prop_open_mode"),
            (self._cb_window_lock_mode, "form_prop_window_lock_mode"),
            (self._cb_layout, "form_layout"),
            (self._sp_grid_cols, "form_grid_columns"),
            (self._cb_representation, "form_prop_representation"),
            (self._chk_show_title, "form_prop_show_title"),
            (self._cb_title_location, "form_prop_title_location"),
            (self._cb_group_anchor, "form_prop_group_anchor"),
            (self._sp_width_chars, "form_prop_width_chars"),
            (self._sp_height_rows, "form_prop_height_rows"),
            (self._chk_visible, "form_prop_visible_client"),
            (self._cb_decoration_kind, "form_prop_decoration_kind"),
            (self._chk_enabled, "form_prop_enabled"),
            (self._ed_tooltip, "form_prop_tooltip"),
            (self._cb_decoration_halign, "form_prop_horizontal_alignment"),
            (self._cb_decoration_valign, "form_prop_vertical_alignment"),
            (self._chk_hstretch, "form_prop_hstretch"),
            (self._chk_vstretch, "form_prop_vstretch"),
            (self._ed_command, "form_prop_command"),
        ]
        for field, key in row_labels:
            try:
                label = self._form_layout.labelForField(field)
                if isinstance(label, QLabel):
                    label.setText(t(key))
            except Exception:
                continue

        try:
            decoration_kind = self._cb_decoration_kind.currentData()
            self._cb_decoration_kind.setItemText(0, t("form_decoration_label"))
            self._cb_decoration_kind.setItemText(1, t("form_decoration_picture"))
            idx = self._cb_decoration_kind.findData(decoration_kind)
            self._cb_decoration_kind.setCurrentIndex(idx if idx >= 0 else 0)
            for combo in (self._cb_decoration_halign, self._cb_decoration_valign):
                current = combo.currentData()
                combo.setItemText(0, t("form_align_start"))
                combo.setItemText(1, t("form_align_center"))
                combo.setItemText(2, t("form_align_end"))
                idx = combo.findData(current)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
        except Exception:
            pass

        try:
            self._grp_canvas.setTitle(t("form_canvas_size"))
            canvas_layout = self._grp_canvas.layout()
            if isinstance(canvas_layout, QFormLayout):
                for field, key in ((self._sp_canvas_w, "form_canvas_w"), (self._sp_canvas_h, "form_canvas_h")):
                    label = canvas_layout.labelForField(field)
                    if isinstance(label, QLabel):
                        label.setText(t(key))

            self._grp_geom.setTitle(t("form_geometry"))
            geom_layout = self._grp_geom.layout()
            if isinstance(geom_layout, QFormLayout):
                for field, key in (
                    (self._sp_x, "form_pos_x"),
                    (self._sp_y, "form_pos_y"),
                    (self._sp_w, "form_size_w"),
                    (self._sp_h, "form_size_h"),
                ):
                    label = geom_layout.labelForField(field)
                    if isinstance(label, QLabel):
                        label.setText(t(key))

            self._grp_gridpos.setTitle(t("form_grid_position"))
            grid_layout = self._grp_gridpos.layout()
            if isinstance(grid_layout, QFormLayout):
                for field, key in (
                    (self._sp_row, "form_row"),
                    (self._sp_col, "form_col"),
                    (self._sp_rowspan, "form_rowspan"),
                    (self._sp_colspan, "form_colspan"),
                ):
                    label = grid_layout.labelForField(field)
                    if isinstance(label, QLabel):
                        label.setText(t(key))

            self._lbl_table_columns.setText(t("form_table_columns"))
            self._tbl_columns.setHorizontalHeaderLabels([t("form_column")])
        except Exception:
            pass

        self._reset_combo_items(
            self._cb_open_mode,
            [
                (t("form_open_mode_auto"), "auto"),
                (t("form_open_mode_workspace"), "workspace"),
                (t("form_open_mode_window"), "window"),
            ],
        )
        self._reset_combo_items(
            self._cb_window_lock_mode,
            [
                (t("form_window_lock_none"), "none"),
                (t("form_window_lock_owner"), "owner"),
                (t("form_window_lock_interface"), "interface"),
            ],
        )
        try:
            self._props_help_map[self._cb_open_mode] = t("form_prop_open_mode_help")
            self._props_help_map[self._cb_window_lock_mode] = t("form_prop_window_lock_mode_help")
        except Exception:
            pass
        self._reset_combo_items(
            self._cb_representation,
            [
                (t("form_repr_auto"), ""),
                (t("form_repr_none"), "none"),
                (t("form_repr_weak"), "weak"),
                (t("form_repr_usual"), "usual"),
                (t("form_repr_strong"), "strong"),
            ],
        )
        self._reset_combo_items(
            self._cb_title_location,
            [
                (t("form_title_loc_left"), "left"),
                (t("form_title_loc_top"), "top"),
                (t("form_title_loc_none"), "none"),
            ],
        )
        self._reset_combo_items(
            self._cb_group_anchor,
            [
                (t("form_anchor_auto"), ""),
                (t("form_anchor_start"), "start"),
                (t("form_anchor_center"), "center"),
                (t("form_anchor_end"), "end"),
                (t("form_anchor_stretch"), "stretch"),
            ],
        )

        self._populate_toolbox()
        self._sync_toolbox_combo()
        self._rebuild_tree(keep_selected_id=current_id or self._model.root.id)
        self._refresh_design_surface()
        self._sync_toolbox_hint()
