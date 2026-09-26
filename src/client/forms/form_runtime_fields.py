from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QSizePolicy, QTableView, QTextEdit, QToolButton, QVBoxLayout, QWidget

from src.configurator.domain.form_model import FormNode
from src.ui_qt.i18n import t


_FIELD_ACTION_ICONS = Path(__file__).resolve().parents[2] / "assets" / "icons" / "svg"


class FormRuntimeFieldsMixin:
    @staticmethod
    def _manifest_row_value(row: Any, key: str, default: Any = None) -> Any:
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    def _container_chrome(self, node: FormNode, layout: str) -> tuple[str, str]:
        # Корневой контейнер никогда не показывает рамку/заголовок
        if getattr(self, "_is_root_build", False):
            return "none", ""
        props = self._node_props(node)
        title = str(node.title or "").strip()
        rep = self._normalize_group_representation(props.get("representation"))
        show_title = bool(props.get("show_title", False))  # за замовчуванням — не показуємо
        if layout == "absolute" or rep == "none":
            return "none", rep
        if not rep:
            return "none", rep
        if title and show_title:
            return "groupbox", rep or "usual"
        return "frame", rep or "usual"


    def _apply_field_sizing(self, widget: QWidget, node: FormNode, *, default_chars: int = 18) -> None:
        props = self._node_props(node)
        anchor = self._normalize_group_anchor(props.get("group_anchor") or props.get("anchor"))
        force_stretch = anchor == "stretch"
        force_expand_w = bool(props.get("horizontal_stretch")) or force_stretch
        force_expand_h = bool(props.get("vertical_stretch")) or force_stretch
        width_chars = int(props.get("width_chars") or 0) or int(default_chars)
        fm = widget.fontMetrics()
        char_px = max(7, fm.horizontalAdvance("0"))
        target_w = max(72, int(width_chars) * char_px + 26)
        if force_expand_w and force_expand_h:
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        elif force_expand_w:
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, widget.sizePolicy().verticalPolicy())
        elif force_expand_h:
            widget.setSizePolicy(widget.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Expanding)
        else:
            # Width from 1C is a preferred upper bound, not permission to
            # expand the whole form beyond its viewport.
            widget.setMinimumWidth(0)
            widget.setMaximumWidth(target_w)
            widget.setSizePolicy(QSizePolicy.Policy.Preferred, widget.sizePolicy().verticalPolicy())

        height_rows = int(props.get("height_rows") or 0)
        if height_rows > 0:
            row_h = max(22, fm.lineSpacing() + 6)
            target_h = max(row_h, height_rows * row_h + 10)
            if force_expand_h:
                widget.setMinimumHeight(target_h)
            else:
                widget.setFixedHeight(target_h)


    def _layout_alignment_for_parent(self, node: FormNode, parent_layout: str, widget: QWidget) -> Optional[Qt.AlignmentFlag]:
        props = self._node_props(node)
        anchor = self._normalize_group_anchor(props.get("group_anchor") or props.get("anchor"))

        if parent_layout == "vertical":
            if anchor == "stretch":
                widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
                widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        node_type = str(node.type or "").strip()
        if node_type in {"TablePanel", "CommandBar", "StatusBar", "Tabs"}:
            return "none"
        if node_type == "Table":
            raw = self._normalize_title_location(self._node_props(node).get("title_location"))
            return "top" if raw == "left" else raw
        if node_type not in {"TextBox", "TextArea", "NumberBox", "ComboBox", "DateBox", "Table"}:
            return "none"
        title = str(node.title or node.name or node.binding or "").strip()
        if not title:
            return "none"
        return self._normalize_title_location(self._node_props(node).get("title_location"))


    def _field_prefers_expanding_width(self, node: FormNode) -> bool:
        props = self._node_props(node)
        if self._normalize_group_anchor(props.get("group_anchor") or props.get("anchor")) == "stretch":
            return True
        if bool(props.get("horizontal_stretch")):
            return True
        return str(node.type or "").strip() in {
            "TextBox", "TextArea", "ComboBox", "Table",
            "CommandBar", "TablePanel", "StatusBar",
        }


    def _wrap_field_actions(self, node: FormNode, editor: QWidget) -> QWidget:
        props = self._node_props(node)
        binding = str(node.binding or node.name or "")
        meta = self._binding_schema_meta(binding)
        meta_type = str(meta.get("type") or "").strip().lower()
        ref_targets = meta.get("ref_targets") if isinstance(meta.get("ref_targets"), list) else []
        is_reference = (
            meta_type in {"ref", "enum_ref", "any_ref"}
            or bool(str(meta.get("ref_name") or "").strip())
            or bool(ref_targets)
        )
        is_read_only = bool(
            props.get("read_only") or props.get("readonly")
            or self._object_form_write_locked()
        )

        def configured(name: str, inferred: bool) -> bool:
            return bool(props.get(name)) if name in props else bool(inferred)

        # Explicit 1C properties win. Otherwise controls are inferred from the
        # requisite type, so the form model does not need synthetic buttons.
        choice_button = configured("choice_button", is_reference)
        open_button = configured("open_button", is_reference)
        clear_button = configured(
            "clear_button",
            is_reference or isinstance(editor, (QDateEdit, QComboBox)),
        )
        if is_read_only:
            choice_button = False
            clear_button = False
        if not open_button and not choice_button and not clear_button:
            return editor

        host = QWidget()
        host.setProperty("mp_form_editor_host", True)
        host.setProperty("mp_form_inline_actions", True)
        host.setSizePolicy(editor.sizePolicy())
        host.setMinimumWidth(0)
        lay = QHBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        editor.setProperty("mp_inline_actions", True)
        lay.addWidget(editor, 1)
        action_buttons: list[QToolButton] = []

        def action_button(kind: str, tooltip_key: str, icon_name: str, fallback: str) -> QToolButton:
            button = QToolButton()
            button.setProperty("mp_form_field_action", True)
            button.setProperty("mp_action_kind", kind)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(t(tooltip_key))
            button.setIcon(QIcon(str(_FIELD_ACTION_ICONS / icon_name)))
            button.setIconSize(QSize(14, 14))
            if button.icon().isNull():
                button.setText(fallback)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            action_buttons.append(button)
            lay.addWidget(button)
            return button

        if choice_button:
            btn_choice = action_button("choice", "form_field_choose", "chevron-down.svg", "▾")
            if is_reference and binding:
                btn_choice.clicked.connect(lambda _=False, b=binding: self._on_ref_choose(b))
            elif isinstance(editor, QComboBox):
                btn_choice.clicked.connect(editor.showPopup)
            else:
                choices = props.get("choice_values") or props.get("choices") or props.get("enum_values") or []
                if isinstance(choices, list) and choices:
                    menu = QMenu(btn_choice)
                    for raw_value in choices:
                        value = str(
                            raw_value.get("synonym") or raw_value.get("title") or raw_value.get("name") or ""
                            if isinstance(raw_value, dict) else raw_value
                        ).strip()
                        if value:
                            menu.addAction(value, lambda _=False, v=value, w=editor, b=binding: self._set_inline_choice(b, w, v))
                    btn_choice.setMenu(menu)
                    btn_choice.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        if clear_button:
            btn_clear = action_button("clear", "form_field_clear", "x.svg", "×")
            btn_clear.clicked.connect(lambda _=False, b=binding, w=editor: self._clear_bound_field(b, w))
        if open_button:
            btn_open = action_button("open", "form_field_open", "ellipsis.svg", "…")
            if binding:
                btn_open.clicked.connect(lambda _=False, b=binding: self._on_ref_open_current(b))
        if action_buttons:
            action_buttons[-1].setProperty("mp_action_last", True)
            editor_max = int(editor.maximumWidth())
            if editor_max < 16_777_215:
                host.setMaximumWidth(max(editor_max, 72 + 30 * len(action_buttons)))
        return host


    def _set_inline_choice(self, binding: str, editor: QWidget, value: Any) -> None:
        self._set_val(editor, value)
        if binding:
            self._record[self._record_key_for_binding(binding)] = self._get_val(editor)
        self.data_changed.emit()


    def _clear_bound_field(self, binding: str, editor: QWidget) -> None:
        self._set_val(editor, None)
        if binding:
            key = self._record_key_for_binding(binding)
            self._record[key] = self._get_val(editor)
            self._record.pop(f"{key}_guid", None)
        self.data_changed.emit()


    def _binding_schema_meta(self, binding: str) -> Dict[str, Any]:
        binding_key = str(binding or "").strip().lower()
        if not binding_key or not self._ctx.obj_guid:
            return {}

        payload: Dict[str, Any] = {}
        row = None
        if self._mrows:
            row = next(
                (
                    r for r in self._mrows
                    if str(self._manifest_row_value(r, "guid") or "") == str(self._ctx.obj_guid or "")
                ),
                None,
            )
        if row is None and hasattr(self, "_manifest_row_by_guid"):
            try:
                row = self._manifest_row_by_guid(self._ctx.obj_guid)  # type: ignore[misc]
            except Exception:
                row = None
        if row is not None:
            row_payload = self._manifest_row_value(row, "payload")
            if isinstance(row_payload, dict):
                payload = row_payload
        if not payload:
            return {}

        if binding_key in {"number", "_number"} and self._ctx.obj_type == "document":
            numeric = str(payload.get("number_type") or "string").casefold() in {"number", "numeric", "int"}
            return {"type": "number" if numeric else "str", "standard_document_number": True}

        for req in payload.get("requisites") or payload.get("attributes") or []:
            if not isinstance(req, dict):
                continue
            name = str(req.get("name") or req.get("code") or "").strip().lower()
            if name == binding_key:
                return req

        for tp in payload.get("tabular_parts") or []:
            if not isinstance(tp, dict):
                continue
            tp_name = str(tp.get("name") or tp.get("code") or "").strip().lower()
            if tp_name == binding_key:
                return tp
            for col in tp.get("columns") or []:
                if not isinstance(col, dict):
                    continue
                col_name = str(col.get("name") or col.get("code") or "").strip().lower()
                if col_name == binding_key:
                    return col
        return {}


    def _configure_table_view(self, tv: QTableView, column_count: int) -> None:
        header = tv.horizontalHeader()
        try:
            header.setStretchLastSection(False)
            header.setMinimumSectionSize(56)
            if column_count <= 1:
                header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
                return
            if column_count == 2:
                header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
                header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
                return

            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            for idx in range(2, column_count):
                header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
        except Exception:
            header.setStretchLastSection(True)


    def _group_left_title_width(self, children: list[FormNode]) -> int:
        widths: list[int] = []
        for ch in children:
            if self._field_title_mode(ch) != "left":
                continue
            text = str(ch.title or ch.name or ch.binding or "").strip() + ":"
            if not text.strip(":"):
                continue
            sample = QLabel(text)
            widths.append(max(96, min(320, sample.fontMetrics().horizontalAdvance(text) + 12)))
        return max(widths, default=96)


    def _make_field_title_label(self, node: FormNode, *, with_colon: bool, fixed_width: Optional[int] = None) -> QLabel:
        title = str(node.title or node.name or node.binding or "").strip()
        lbl = QLabel(title + (":" if with_colon else ""))
        lbl.setProperty("mp_form_field_title", True)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if with_colon:
            label_w = int(fixed_width or max(96, min(320, lbl.fontMetrics().horizontalAdvance(lbl.text()) + 12)))
            lbl.setMinimumWidth(0)
            lbl.setMaximumWidth(label_w)
            lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        return self._register_field_title_label(node, lbl)


    def _decorate_field(self, node: FormNode, widget: QWidget) -> QWidget:
        title = str(node.title or node.name or node.binding or "").strip()
        if not title or isinstance(widget, (QCheckBox, QPushButton, QLabel)):
            return widget
        location = self._normalize_title_location(self._node_props(node).get("title_location"))
        if location == "none":
            return widget
        if location == "top":
            host = QWidget()
            host.setMinimumWidth(0)
            host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            lay = QVBoxLayout(host)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            lbl = QLabel(title)
            lbl.setProperty("mp_form_field_title", True)
            lbl.setWordWrap(True)
            lay.addWidget(self._register_field_title_label(node, lbl))
            lay.addWidget(widget)
            return host
        host = QWidget()
        host.setMinimumWidth(0)
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QHBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lbl = QLabel(title + ":")
        lbl.setProperty("mp_form_field_title", True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label_w = max(96, min(220, lbl.fontMetrics().horizontalAdvance(title + ":") + 12))
        lbl.setMinimumWidth(0)
        lbl.setMaximumWidth(label_w)
        lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        lay.addWidget(self._register_field_title_label(node, lbl))
        lay.addWidget(widget, 1)
        return host


    @staticmethod
    def _set_val(w: QWidget, val: Any) -> None:
        old = w.blockSignals(True)
        try:
            if isinstance(w, QLineEdit):
                w.setText("" if val is None else str(val))
                w.setCursorPosition(0)
            elif isinstance(w, QTextEdit):
                w.setPlainText("" if val is None else str(val))
            elif isinstance(w, QDoubleSpinBox):
                try: w.setValue(float(val or 0))
                except: w.setValue(0.0)
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(val))
            elif isinstance(w, QComboBox):
                text = "" if val is None else str(val)
                idx = w.findText(text)
                if idx >= 0:
                    w.setCurrentIndex(idx)
                else:
                    w.setEditText(text)
            elif isinstance(w, QDateEdit):
                from PySide6.QtCore import QDate
                # Imported timestamps are ISO dates followed by a time. The
                # date-only editor displays the date; collection keeps the time.
                d = QDate.fromString(str(val or "")[:10], "yyyy-MM-dd")
                w.setDate(d if d.isValid() else w.minimumDate())
        finally:
            w.blockSignals(old)


    @staticmethod
    def _get_val(w: QWidget) -> Any:
        if isinstance(w, QLineEdit):      return w.text()
        if isinstance(w, QTextEdit):      return w.toPlainText()
        if isinstance(w, QDoubleSpinBox): return w.value()
        if isinstance(w, QCheckBox):      return w.isChecked()
        if isinstance(w, QComboBox):      return w.currentText()
        if isinstance(w, QDateEdit):
            return "" if w.date() == w.minimumDate() else w.date().toString("yyyy-MM-dd")
        return ""


    def _wrap_built_node(self, node: FormNode, widget: QWidget) -> QWidget:
        return widget


    def _register_field_title_label(self, node: FormNode, label: QLabel) -> QLabel:
        return label
