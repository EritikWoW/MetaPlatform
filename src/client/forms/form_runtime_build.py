from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QSortFilterProxyModel
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QStyle, QTableView, QTabWidget, QTextEdit, QVBoxLayout, QWidget
from PySide6.QtGui import QPixmap, QStandardItem, QStandardItemModel

from src.configurator.domain.form_model import FormNode, coerce_form_bool, form_node_is_visible
from src.ui_qt.i18n import t

from src.client.data_tables import data_table_name as _data_table

from .form_runtime_types import _tp_table


class _ResponsiveAbsoluteFrame(QFrame):
    """Absolute form surface that scales horizontally into its viewport."""

    def __init__(self, *, design_width: int, design_height: int) -> None:
        super().__init__()
        self._design_width = max(1, int(design_width))
        self._design_height = max(1, int(design_height))
        self._absolute_children: list[tuple[QWidget, int, int, int, int]] = []
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(0)
        self.setMinimumHeight(self._design_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def add_absolute_child(self, widget: QWidget, *, x: int, y: int, width: int, height: int) -> None:
        x = max(0, min(int(x), self._design_width - 1))
        y = max(0, min(int(y), self._design_height - 1))
        width = max(1, min(int(width), self._design_width - x))
        height = max(1, min(int(height), self._design_height - y))
        widget.setMinimumWidth(0)
        widget.setParent(self)
        self._absolute_children.append((widget, x, y, width, height))
        self._relayout_absolute_children()

    def _relayout_absolute_children(self) -> None:
        available_width = max(1, int(self.contentsRect().width()))
        scale_x = min(1.0, available_width / float(self._design_width))
        for widget, x, y, width, height in self._absolute_children:
            scaled_x = max(0, int(round(x * scale_x)))
            scaled_width = max(1, int(round(width * scale_x)))
            scaled_width = min(scaled_width, max(1, available_width - scaled_x))
            widget.setGeometry(scaled_x, y, scaled_width, height)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout_absolute_children()


class FormRuntimeBuildMixin:
    def _node_visible_in_surface(self, node: FormNode) -> bool:
        if bool(getattr(self, "_show_hidden_controls", False)):
            return True
        return form_node_is_visible(node)

    def _surface_children(self, node: FormNode) -> list[FormNode]:
        return [child for child in node.children if self._node_visible_in_surface(child)]

    def _object_form_write_locked(self) -> bool:
        ctx = getattr(self, "_ctx", None)
        return str(getattr(ctx, "form_kind", "") or "").strip().lower() == "object_form" and not self._is_action_allowed("save")

    def _build_node(self, node: FormNode) -> QWidget:
        t_ = str(node.type or "").strip()
        if t_ in {"TextBox", "NumberBox"}:
            binding = str(node.binding or node.name or "")
            meta = self._binding_schema_meta(binding)
            if meta.get("standard_document_number"):
                t_ = "NumberBox" if meta.get("type") == "number" else "TextBox"
        if t_ == "Container":
            built = self._build_container(node)
            return self._wrap_built_node(node, built)
        if t_ == "Tabs":
            built = self._build_tabs(node)
            return self._wrap_built_node(node, built)
        if t_ == "Label":
            built = self._build_label(node)
            return self._wrap_built_node(node, built)
        if t_ == "Picture":
            built = self._build_picture(node)
            return self._wrap_built_node(node, built)
        if t_ == "TextBox":
            built = self._build_textbox(node)
            return self._wrap_built_node(node, built)
        if t_ == "TextArea":
            built = self._build_textarea(node)
            return self._wrap_built_node(node, built)
        if t_ == "NumberBox":
            built = self._build_numberbox(node)
            return self._wrap_built_node(node, built)
        if t_ == "DateBox":
            built = self._build_datebox(node)
            return self._wrap_built_node(node, built)
        if t_ == "CheckBox":
            built = self._build_checkbox(node)
            return self._wrap_built_node(node, built)
        if t_ == "ComboBox":
            built = self._build_combobox(node)
            return self._wrap_built_node(node, built)
        if t_ == "Button":
            built = self._build_button(node)
            return self._wrap_built_node(node, built)
        if t_ == "Table":
            built = self._build_table(node)
            return self._wrap_built_node(node, built)
        if t_ == "CommandBar":
            built = self._build_command_bar(node)
            return self._wrap_built_node(node, built)
        if t_ == "TablePanel":
            built = self._build_table_panel(node)
            return self._wrap_built_node(node, built)
        if t_ == "StatusBar":
            built = self._build_status_bar(node)
            return self._wrap_built_node(node, built)
        if t_ == "Separator":
            fr = QFrame(); fr.setFrameShape(QFrame.Shape.HLine)
            return self._wrap_built_node(node, fr)
        fr = QFrame(); fr.setFrameShape(QFrame.Shape.StyledPanel)
        QVBoxLayout(fr).addWidget(QLabel(f"[{t_}]"))
        return self._wrap_built_node(node, fr)


    def _build_label(self, node: FormNode) -> QWidget:
        props = node.props if isinstance(node.props, dict) else {}
        is_decoration = coerce_form_bool(props.get("is_decoration"), default=False)
        text = str(node.title or "") if is_decoration else str(node.title or node.name or "")
        lbl = QLabel(text)
        lbl.setWordWrap(coerce_form_bool(props.get("wrap"), default=True))

        horizontal = str(props.get("horizontal_alignment") or props.get("horizontal_position") or "left").strip().lower()
        vertical = str(props.get("vertical_alignment") or props.get("vertical_position") or "center").strip().lower()
        hflag = {
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
            "end": Qt.AlignmentFlag.AlignRight,
        }.get(horizontal, Qt.AlignmentFlag.AlignLeft)
        vflag = {
            "top": Qt.AlignmentFlag.AlignTop,
            "bottom": Qt.AlignmentFlag.AlignBottom,
            "end": Qt.AlignmentFlag.AlignBottom,
        }.get(vertical, Qt.AlignmentFlag.AlignVCenter)
        lbl.setAlignment(hflag | vflag)
        lbl.setProperty("mp_form_caption_label", True)
        lbl.setProperty("mp_form_decoration", is_decoration)
        is_spacer = is_decoration and not text.strip()
        lbl.setProperty("mp_form_decoration_spacer", is_spacer)
        lbl.setEnabled(coerce_form_bool(props.get("enabled"), default=True))
        tooltip = str(props.get("tooltip") or props.get("tool_tip") or "").strip()
        if tooltip:
            lbl.setToolTip(tooltip)

        width_chars = int(props.get("width_chars") or props.get("width") or 0)
        height_rows = int(props.get("height_rows") or props.get("height") or 0)
        if width_chars > 0:
            lbl.setMinimumWidth(max(1, width_chars * max(7, lbl.fontMetrics().horizontalAdvance("0"))))
        elif is_spacer:
            lbl.setMinimumWidth(8)
        if height_rows > 0:
            lbl.setMinimumHeight(max(1, height_rows * max(18, lbl.fontMetrics().lineSpacing())))

        h_policy = QSizePolicy.Policy.Expanding if coerce_form_bool(props.get("horizontal_stretch"), default=False) else QSizePolicy.Policy.Preferred
        v_policy = QSizePolicy.Policy.Expanding if coerce_form_bool(props.get("vertical_stretch"), default=False) else QSizePolicy.Policy.Preferred
        lbl.setSizePolicy(h_policy, v_policy)
        return lbl


    def _build_picture(self, node: FormNode) -> QWidget:
        props = node.props if isinstance(node.props, dict) else {}
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("mp_form_picture", True)
        label.setMinimumSize(int(props.get("min_w") or 96), int(props.get("min_h") or 72))

        pixmap = QPixmap()
        encoded = str(props.get("image_base64") or "").strip()
        source = str(props.get("source") or props.get("image_path") or "").strip()
        if encoded:
            try:
                if encoded.startswith("data:") and "," in encoded:
                    encoded = encoded.split(",", 1)[1]
                pixmap.loadFromData(base64.b64decode(encoded, validate=False))
            except Exception:
                pixmap = QPixmap()
        elif source:
            try:
                path = Path(source).expanduser()
                if path.is_file():
                    pixmap.load(str(path))
            except Exception:
                pixmap = QPixmap()

        if pixmap.isNull():
            label.setText(str(node.title or node.name or t("form_picture_placeholder")))
            label.setProperty("mp_form_picture_empty", True)
        else:
            label.setPixmap(pixmap)
            label.setScaledContents(bool(props.get("stretch", True)))
        return label


    def _build_textbox(self, node: FormNode) -> QWidget:
        binding = str(node.binding or node.name or "")
        props   = node.props if isinstance(node.props, dict) else {}
        ed = QLineEdit()
        self._mark_form_editor(ed)
        if self._normalize_title_location(props.get("title_location")) == "none":
            ed.setPlaceholderText(str(node.title or binding))
        ed.setReadOnly(bool(props.get("read_only") or props.get("readonly") or self._object_form_write_locked()))
        self._apply_field_sizing(ed, node, default_chars=20)
        if binding:
            self._bound_inputs[binding] = ed
            ed.textChanged.connect(self._on_field_changed)
        return self._wrap_field_actions(node, ed)


    def _build_textarea(self, node: FormNode) -> QWidget:
        binding = str(node.binding or node.name or "")
        props   = node.props if isinstance(node.props, dict) else {}
        ed = QTextEdit()
        self._mark_form_editor(ed)
        ed.setAcceptRichText(False)
        ed.setReadOnly(bool(props.get("read_only") or props.get("readonly") or self._object_form_write_locked()))
        ed.setMinimumHeight(int(props.get("min_h") or 96))
        self._apply_field_sizing(ed, node, default_chars=30)
        if binding:
            self._bound_inputs[binding] = ed
            ed.textChanged.connect(self._on_field_changed)
        return ed


    def _build_numberbox(self, node: FormNode) -> QWidget:
        binding = str(node.binding or node.name or "")
        props   = node.props if isinstance(node.props, dict) else {}
        sp = QDoubleSpinBox()
        self._mark_form_editor(sp)
        sp.setDecimals(int(props.get("decimals", 2)))
        sp.setMinimum(float(props.get("min", -999_999_999)))
        sp.setMaximum(float(props.get("max",  999_999_999)))
        sp.setReadOnly(bool(props.get("read_only") or props.get("readonly") or self._object_form_write_locked()))
        self._apply_field_sizing(sp, node, default_chars=12)
        if binding:
            self._bound_inputs[binding] = sp
            sp.valueChanged.connect(self._on_field_changed)
        return self._wrap_field_actions(node, sp)


    def _build_datebox(self, node: FormNode) -> QWidget:
        from PySide6.QtCore import QDate
        binding = str(node.binding or node.name or "")
        de = QDateEdit(); de.setCalendarPopup(True)
        self._mark_form_editor(de)
        de.setMinimumDate(QDate(100, 1, 1))
        # Qt treats an empty specialValueText as "disabled"; a zero-width
        # space keeps the nullable state visually empty.
        de.setSpecialValueText("\u200b")
        de.setDate(de.minimumDate())
        de.setDisplayFormat("dd.MM.yyyy")
        if props := (node.props if isinstance(node.props, dict) else {}):
            if bool(props.get("read_only") or props.get("readonly") or self._object_form_write_locked()):
                de.setEnabled(False)
        self._apply_field_sizing(de, node, default_chars=14)
        if binding:
            self._bound_inputs[binding] = de
            de.dateChanged.connect(self._on_field_changed)
        return self._wrap_field_actions(node, de)


    def _build_checkbox(self, node: FormNode) -> QWidget:
        binding = str(node.binding or node.name or "")
        cb = QCheckBox(str(node.title or node.name or ""))
        if self._object_form_write_locked():
            cb.setEnabled(False)
        if binding:
            self._bound_inputs[binding] = cb
            cb.stateChanged.connect(self._on_field_changed)
        return cb


    def _build_combobox(self, node: FormNode) -> QWidget:
        binding = str(node.binding or node.name or "")
        props   = node.props if isinstance(node.props, dict) else {}
        cb = QComboBox()
        self._mark_form_editor(cb)
        self._apply_field_sizing(cb, node, default_chars=20)

        # Populate enum values from field metadata
        enum_values: list = list(props.get("enum_values") or [])
        if not enum_values and binding:
            meta = self._binding_schema_meta(binding)
            enum_values = list(meta.get("enum_values") or [])
        if enum_values:
            cb.setEditable(False)
            cb.addItem("")
            for v in enum_values:
                if isinstance(v, dict):
                    label = str(v.get("synonym") or v.get("title") or v.get("name") or "")
                else:
                    label = str(v)
                if label:
                    cb.addItem(label)
        else:
            cb.setEditable(True)
        if self._object_form_write_locked():
            cb.setEnabled(False)

        if binding:
            self._bound_inputs[binding] = cb
            cb.currentTextChanged.connect(self._on_field_changed)
        return self._wrap_field_actions(node, cb)


    def _build_button(self, node: FormNode) -> QWidget:
        props = node.props if isinstance(node.props, dict) else {}
        cmd   = str(props.get("command") or "").strip()
        role  = str(props.get("role") or props.get("variant") or "").strip().lower()
        btn   = QPushButton(str(node.title or node.name or ""))
        btn.setProperty("mp_form_standalone_button", True)
        self._mark_command_button(
            btn,
            primary=role in {"", "primary"},
            variant="ghost" if role == "ghost" else ("outline" if role in {"outline", "secondary"} else "primary"),
        )
        self._apply_command_icon(btn, command=cmd, title=str(node.title or node.name or ""))
        if cmd:
            allowed = self._is_action_allowed(cmd)
            btn.setEnabled(allowed)
            if not allowed:
                btn.setToolTip(t("client_err_access_denied").format(title=str(node.title or node.name or "")))
            btn.clicked.connect(lambda _=False, c=cmd: self._emit_command(c))
        return btn


    def _build_table(self, node: FormNode) -> QWidget:
        """Таблиця — або список об'єктів (list_form) або табчастина (object_form)."""
        props   = node.props if isinstance(node.props, dict) else {}
        binding = str(node.binding or node.name or "")

        # Визначаємо колонки з props
        cols_raw = props.get("columns") if isinstance(props.get("columns"), list) else []
        headers: List[str] = []
        col_bindings: List[str] = []
        for c in cols_raw:
            if isinstance(c, dict):
                headers.append(self._resolve_col_title(c.get("title"), c.get("name") or ""))
                col_bindings.append(str(c.get("binding") or c.get("name") or ""))

        # list_form: binding="items" → головна таблиця списку
        is_list = (binding == "items" and self._ctx.form_kind == "list_form")

        tv = QTableView()
        self._mark_form_table(tv)
        tv.setAlternatingRowColors(True)
        tv.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tv.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tv.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tv.verticalHeader().setVisible(False)
        tv.setMinimumHeight(200)
        tv.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        if is_list:
            # Proxy model for search + sorting
            proxy = QSortFilterProxyModel()
            proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            proxy.setFilterKeyColumn(-1)

            # Зберігаємо посилання для reload та команд
            self._list_table = tv
            self._list_col_bindings = col_bindings
            tv._filter_proxy = proxy  # type: ignore[attr-defined]
            tv.setSortingEnabled(True)
            tv.doubleClicked.connect(lambda _: self._emit_command("Edit"))
            warning = QLabel()
            warning.setWordWrap(True)
            warning.setObjectName("importDataWarning")
            warning.setStyleSheet("color: #92400E; background: #FFFBEB; padding: 8px;")
            warning.hide()
            tv._import_warning = warning
            self._fill_list_table(tv, col_bindings, headers)
            self._install_list_context_menu(tv, self._emit_command)

            # Клавіатурні скорочення для списку
            _self = self
            def _key_press(event, _orig=tv.keyPressEvent):
                key  = event.key()
                mods = event.modifiers()
                no_mod = mods == Qt.KeyboardModifier.NoModifier
                ctrl   = mods == Qt.KeyboardModifier.ControlModifier
                if key == Qt.Key.Key_F5:
                    _self._emit_command("refresh")
                elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and no_mod:
                    _self._emit_command("Edit")
                elif key == Qt.Key.Key_Delete and no_mod:
                    _self._emit_command("delete")
                elif key == Qt.Key.Key_N and ctrl:
                    _self._emit_command("create")
                else:
                    _orig(event)
            tv.keyPressEvent = _key_press  # type: ignore[method-assign]

            # Статистика: filtered + total
            def _on_sel_changed(*_):
                px = getattr(tv, "_filter_proxy", None)
                if px is not None:
                    src = px.sourceModel()
                    total   = src.rowCount() if src else 0
                    visible = px.rowCount()
                else:
                    m = tv.model()
                    total = visible = m.rowCount() if m else 0
                sel = len(tv.selectionModel().selectedRows()) if tv.selectionModel() else 0
                if hasattr(self, "list_stats_changed"):
                    self.list_stats_changed.emit(visible if visible != total else total, sel)
            sel_model = tv.selectionModel()
            if sel_model is not None:
                sel_model.selectionChanged.connect(_on_sel_changed)
            proxy.rowsInserted.connect(_on_sel_changed)
            proxy.rowsRemoved.connect(_on_sel_changed)
            QTimer = __import__("PySide6.QtCore", fromlist=["QTimer"]).QTimer
            QTimer.singleShot(50, _on_sel_changed)

            # Контейнер з пошуком
            host = QFrame()
            host.setFrameShape(QFrame.Shape.NoFrame)
            vl = QVBoxLayout(host)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(4)

            search = QLineEdit()
            search.setPlaceholderText(t("client_form_search_hint"))
            search.setClearButtonEnabled(True)
            search.setMaximumHeight(32)
            search.textChanged.connect(proxy.setFilterWildcard)
            search.textChanged.connect(_on_sel_changed)
            vl.addWidget(search)
            vl.addWidget(warning)

            # Empty state label (shown when no records)
            empty_lbl = QLabel(t("client_form_empty"))
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setWordWrap(True)
            empty_lbl.setStyleSheet("color: #94A3B8; font-size: 11pt; padding: 32px;")
            empty_lbl.setVisible(False)
            tv._empty_label = empty_lbl  # type: ignore[attr-defined]
            vl.addWidget(empty_lbl)

            vl.addWidget(tv, 1)
            return host
        else:
            # Табчастина документа — зберігаємо посилання для TP-команд і збереження
            self._tp_tables[binding] = tv
            self._tp_col_bindings[binding] = col_bindings
            self._fill_tp_table(tv, binding, col_bindings, headers)

        return tv


    def _build_command_bar(self, node: FormNode) -> QWidget:
        """Командна панель — горизонтальний рядок кнопок (аналог командної панелі 1С).

        props.buttons — список:
            {"title": "Провести і закрити", "command": "post_and_close",
             "role": "primary"|"danger"|"",
             "icon": "save"|"close"|"add"|"delete"|"print"|"",
             "separator_after": bool}
        Якщо buttons порожній — генерується стандартний набір документа.
        """
        props       = node.props if isinstance(node.props, dict) else {}
        btns_raw    = props.get("buttons") if isinstance(props.get("buttons"), list) else []
        if not btns_raw and getattr(node, "children", None):
            btns_raw = [
                ch.to_dict()
                for ch in self._surface_children(node)
                if isinstance(ch, FormNode) and str(ch.type or "").strip() == "Button"
            ]
        show_all    = bool(props.get("show_all_actions", True))

        bar = QFrame()
        bar.setProperty("mp_form_cmdbar", True)
        bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        hl = QHBoxLayout(bar)
        hl.setContentsMargins(8, 8, 8, 8)
        hl.setSpacing(6)

        if not btns_raw:
            obj_type  = str(getattr(getattr(self, "_ctx", None), "obj_type",  "") or "").lower()
            form_kind = str(getattr(getattr(self, "_ctx", None), "form_kind", "") or "").lower()
            if form_kind == "list_form":
                btns_raw = [
                    {"title": "Створити",  "command": "create",  "role": "primary", "icon": "add"},
                    {"title": "Відкрити",  "command": "edit",    "icon": "edit"},
                    {"title": "Копіювати", "command": "copy"},
                    {"separator_after": True},
                    {"title": "Видалити",  "command": "delete",  "icon": "delete"},
                ]
            elif obj_type in ("document", "business_process", "task"):
                btns_raw = [
                    {"title": "Провести і закрити", "command": "post_and_close",
                     "role": "primary", "icon": "save"},
                    {"separator_after": True},
                    {"title": "Провести",   "command": "post"},
                    {"title": "Записати",   "command": "save",   "icon": "save"},
                    {"title": "Закрити",    "command": "close",  "icon": "close"},
                ]
            else:
                # Catalog / register / other
                btns_raw = [
                    {"title": "Записати і закрити", "command": "saveandclose",
                     "role": "primary", "icon": "save"},
                    {"title": "Записати",  "command": "save"},
                    {"separator_after": True},
                    {"title": "Копіювати", "command": "copy"},
                    {"title": "Видалити",  "command": "delete"},
                    {"title": "Закрити",   "command": "close",  "icon": "close"},
                ]

        for bdef in btns_raw:
            if not isinstance(bdef, dict):
                continue
            if not bool(getattr(self, "_show_hidden_controls", False)) and not coerce_form_bool(
                bdef.get("visible"), default=True
            ):
                continue
            # Pure separator
            if bdef.get("separator_after") and not bdef.get("title"):
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setFrameShadow(QFrame.Shadow.Sunken)
                sep.setFixedSize(1, 18)
                hl.addWidget(sep)
                continue

            title  = str(bdef.get("title") or "")
            cmd    = str(bdef.get("command") or "")
            role   = str(bdef.get("role") or "").lower()
            icon_k = str(bdef.get("icon") or "")

            if not title:
                continue

            btn = QPushButton(title)
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            allowed = self._is_action_allowed(cmd or title)
            self._mark_command_button(
                btn,
                primary=(role == "primary"),
                variant="primary" if role == "primary" else "ghost",
            )
            btn.setProperty("mp_form_cmdbar_action", True)
            btn.setEnabled(allowed)
            if not allowed:
                btn.setToolTip(t("client_err_access_denied").format(title=title))
            if icon_k or cmd:
                self._apply_command_icon(btn, command=icon_k or cmd, title=title)
            if cmd:
                btn.clicked.connect(lambda _=False, c=cmd: self._emit_command(c))
            hl.addWidget(btn)

            if bdef.get("separator_after"):
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setFrameShadow(QFrame.Shadow.Sunken)
                sep.setFixedSize(1, 18)
                hl.addWidget(sep)

        hl.addStretch(1)

        if show_all:
            all_btn = QPushButton(t("client_all_actions") + " ▾")
            all_btn.setMinimumWidth(0)
            all_btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self._mark_command_button(all_btn, variant="ghost")
            all_btn.setProperty("mp_form_cmdbar_action", True)
            all_btn.setEnabled(self._is_action_allowed("all_actions"))
            all_btn.clicked.connect(lambda: self._emit_command("all_actions"))
            hl.addWidget(all_btn)

        return bar


    def _build_table_panel(self, node: FormNode) -> QWidget:
        """Таблична частина зі вбудованою тулбар-панеллю (аналог ТабличноїЧастини 1С).

        props успадковує все що є у Table (columns, binding…), плюс:
          can_add        bool — кнопка «Додати» (default True)
          can_delete     bool — кнопка «Видалити» (default True)
          can_move_up    bool — кнопка вгору
          can_move_down  bool — кнопка вниз
          fill_by_stock  str  — текст кнопки «Заповнити за залишками» (якщо є)
          extra_commands list — [{"title":…,"command":…}] — додаткові кнопки
        """
        props    = node.props if isinstance(node.props, dict) else {}
        binding  = str(node.binding or node.name or "")

        # In imported 1C forms a list's main data area is also represented as
        # TablePanel.  It is not a tabular part: the ``items`` binding means
        # the object's list and must use the paged list-data path (including
        # search, selection and open-on-double-click).
        if binding == "items" and self._ctx.form_kind == "list_form":
            return self._build_table(node)

        can_add  = bool(props.get("can_add", True))
        can_del  = bool(props.get("can_delete", True))
        can_up   = bool(props.get("can_move_up",  False))
        can_dn   = bool(props.get("can_move_down", False))
        fill_lbl = str(props.get("fill_by_stock") or "")
        extra    = props.get("extra_commands") if isinstance(props.get("extra_commands"), list) else []

        host = QFrame()
        host.setFrameShape(QFrame.Shape.NoFrame)
        host.setProperty("mp_form_table_panel", True)
        vl = QVBoxLayout(host)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── toolbar ──────────────────────────────────────────────────
        tb = QFrame()
        tb.setProperty("mp_form_cmdbar", True)
        tb.setProperty("mp_form_table_toolbar", True)
        tb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        th = QHBoxLayout(tb)
        th.setContentsMargins(8, 8, 8, 8)
        th.setSpacing(6)

        def _tp_btn(title: str, cmd: str, icon_key: str = "") -> QPushButton:
            b = QPushButton(title)
            b.setProperty("mp_tp_action", True)
            self._mark_command_button(b, variant="ghost")
            allowed = self._is_action_allowed(cmd)
            b.setEnabled(allowed)
            if not allowed:
                b.setToolTip(t("client_err_access_denied").format(title=title))
            if icon_key or cmd:
                self._apply_command_icon(b, command=icon_key or cmd, title=title)
            if cmd:
                b.clicked.connect(lambda _=False, c=cmd, bind=binding:
                    self._emit_command(f"{c}:{bind}"))
            return b

        if can_add:
            th.addWidget(_tp_btn("Додати",   "tp_add",    "add"))
        if can_del:
            th.addWidget(_tp_btn("Видалити", "tp_delete", "delete"))
        if can_up:
            sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine)
            sep.setFixedSize(2, 18); th.addWidget(sep)
            th.addWidget(_tp_btn("↑", "tp_up", "up"))
        if can_dn:
            th.addWidget(_tp_btn("↓", "tp_down", "down"))

        if fill_lbl:
            sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine)
            sep.setFixedSize(2, 18); th.addWidget(sep)
            th.addWidget(_tp_btn(fill_lbl, "tp_fill"))

        for ec in extra:
            if isinstance(ec, dict):
                ec_title = str(ec.get("title") or "")
                ec_cmd   = str(ec.get("command") or "")
                if ec_title:
                    th.addWidget(_tp_btn(ec_title, ec_cmd))

        th.addStretch(1)

        # «Всі дії» справа
        all_b = QPushButton(t("client_all_actions") + " ▾")
        all_b.setProperty("mp_tp_action", True)
        self._mark_command_button(all_b, variant="ghost")
        all_b.setEnabled(self._is_action_allowed("tp_all_actions"))
        all_b.clicked.connect(lambda: self._emit_command(f"tp_all_actions:{binding}"))
        th.addWidget(all_b)

        vl.addWidget(tb)

        # ── table ─────────────────────────────────────────────────────
        tv = QTableView()
        self._mark_form_table(tv)
        tv.setAlternatingRowColors(True)
        tv.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tv.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tv.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tv.verticalHeader().setVisible(False)
        tv.setMinimumHeight(180)
        tv.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Колонки: номер рядка + задані
        cols_raw = props.get("columns") if isinstance(props.get("columns"), list) else []
        headers: List[str] = []
        col_bindings: List[str] = []
        for c in cols_raw:
            if isinstance(c, dict):
                headers.append(self._resolve_col_title(c.get("title"), c.get("name") or ""))
                col_bindings.append(str(c.get("binding") or c.get("name") or ""))

        self._tp_tables[binding] = tv
        self._tp_col_bindings[binding] = col_bindings
        self._fill_tp_table(tv, binding, col_bindings, headers)
        vl.addWidget(tv, 1)

        return host


    def _build_status_bar(self, node: FormNode) -> QWidget:
        """Рядок підсумків внизу форми (аналог підвалу документа 1С).

        props.fields — список:
            {"label": "Перевитрата:", "binding": "overspend",
             "decimals": 2, "read_only": True}
        Якщо fields порожній — стандартні три поля документа.
        """
        props  = node.props if isinstance(node.props, dict) else {}
        fields = props.get("fields") if isinstance(props.get("fields"), list) else []

        bar = QFrame()
        bar.setProperty("mp_form_statusbar", True)
        bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        hl = QHBoxLayout(bar)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(12)
        hl.addStretch(1)

        if not fields:
            fields = [
                {"label": "Перевитрата:",  "binding": "overspend",      "decimals": 2, "read_only": True},
                {"label": "Витрачено:",    "binding": "total_spent",     "decimals": 2, "read_only": True},
                {"label": "Отримано:",     "binding": "total_received",  "decimals": 2, "read_only": True},
            ]

        for fdef in fields:
            if not isinstance(fdef, dict):
                continue
            lbl_text  = str(fdef.get("label") or "")
            binding   = str(fdef.get("binding") or "")
            decimals  = int(fdef.get("decimals", 2))
            read_only = bool(fdef.get("read_only", True))

            if lbl_text:
                lbl = QLabel(lbl_text)
                hl.addWidget(lbl)

            sp = QDoubleSpinBox()
            sp.setDecimals(decimals)
            sp.setMinimum(-999_999_999)
            sp.setMaximum(999_999_999)
            sp.setValue(0)
            sp.setReadOnly(read_only)
            sp.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
            sp.setFixedWidth(100)
            sp.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._mark_form_editor(sp)
            if binding:
                self._bound_inputs[binding] = sp
                if not read_only:
                    sp.valueChanged.connect(self._on_field_changed)
            hl.addWidget(sp)

        return bar


    def _build_tabs(self, node: FormNode) -> QWidget:
        tabs = QTabWidget()
        tabs.setProperty("mp_form_tabs", True)
        tabs.setDocumentMode(True)
        tabs.setTabPosition(QTabWidget.TabPosition.North)

        for idx, ch in enumerate(self._surface_children(node), start=1):
            page = self._build_node(ch)
            title = str(ch.title or ch.name or f"Tab {idx}")
            tabs.addTab(page, title)

        return tabs


    @staticmethod
    def _resolve_col_title(raw_title: Any, fallback: str = "") -> str:
        """Resolve column title respecting current app locale."""
        from src.ui_qt.i18n import get_lang
        lang = get_lang()  # "uk" or "en"
        fallback_langs = (lang, "uk", "en", "ru")  # preferred first

        if isinstance(raw_title, dict):
            for l in fallback_langs:
                v = str(raw_title.get(l) or "").strip()
                if v:
                    return v
            # last resort: first non-empty value
            for v in raw_title.values():
                s = str(v or "").strip()
                if s:
                    return s
            return fallback
        s = str(raw_title or "").strip()
        return s if s else fallback

    def _fill_list_table(
        self,
        tv: QTableView,
        col_bindings: List[str],
        headers: Optional[List[str]] = None,
    ) -> None:
        """Завантажити рядки з data_catalog_* або data_document_*."""
        ctx = self._ctx
        if not ctx.obj_name or self._db is None:
            if not headers:
                headers = col_bindings[:] if col_bindings else ["—"]
            m = QStandardItemModel(0, len(headers))
            m.setHorizontalHeaderLabels(headers)
            tv.setModel(m)
            self._configure_table_view(tv, len(headers))
            return

        try:
            # Lists are paged at the runtime boundary. Loading the complete
            # business table here made opening one object proportional to the
            # whole database and transferred every row through RPC.
            all_rows = self._db.table(_data_table(ctx.obj_type, ctx.obj_name)).select(limit=500) or []
        except Exception as _exc:
            import logging as _log
            _log = _log.getLogger("client.form")
            _log.warning("table.select failed (%s/%s): %s — deploying schema and retrying",
                         ctx.obj_type, ctx.obj_name, _exc)
            try:
                _gw = getattr(self._db, "_gw", None)
                if _gw is not None:
                    _gw.schema_deploy()
                all_rows = self._db.table(_data_table(ctx.obj_type, ctx.obj_name)).select(limit=500) or []
            except Exception as _exc2:
                _log.error("Still failed after schema deploy (%s/%s): %s",
                           ctx.obj_type, ctx.obj_name, _exc2)
                all_rows = []

        rows = [r for r in all_rows if not r.get("_deleted")]
        warning = getattr(tv, "_import_warning", None)
        if warning is not None:
            gateway = getattr(self._db, "_gw", None)
            status = getattr(gateway, "last_table_status", {}).get(_data_table(ctx.obj_type, ctx.obj_name), {})
            messages = []
            if status.get("limited"):
                messages.append(t("client_import_limited").format(
                    count=status.get("imported_rows", 0), limit=status.get("limit_per_table", 0)))
            if status.get("binding_error"):
                messages.append(t("client_import_bindings_missing"))
            warning.setText("\n".join(messages))
            warning.setVisible(bool(messages))

        # Автоматичні колонки якщо не задано
        if not col_bindings:
            # Спробуємо взяти з payload об'єкта
            owner_row = next(
                (r for r in (self._mrows or [])
                 if str(r.get("guid") or "") == ctx.obj_guid),
                None,
            )
            if owner_row is None and hasattr(self, "_manifest_row_by_guid"):
                try:
                    owner_row = self._manifest_row_by_guid(ctx.obj_guid)  # type: ignore[misc]
                except Exception:
                    owner_row = None
            attrs = []
            if isinstance(owner_row, dict):
                pay = owner_row.get("payload") or {}
                if isinstance(pay, dict):
                    attrs = pay.get("attributes") or pay.get("requisites") or []

            if attrs:
                for a in attrs[:6]:
                    if not isinstance(a, dict):
                        continue
                    nm = str(a.get("name") or a.get("code") or "").strip()
                    if not nm:
                        continue
                    raw_title = a.get("title")
                    lbl = self._resolve_col_title(raw_title, nm[:1].upper() + nm[1:])
                    col_bindings.append(nm)
                    headers.append(lbl) if headers is not None else headers
                    if headers is None:
                        headers = [lbl]
                    else:
                        headers.append(lbl)
            elif ctx.obj_type == "document":
                col_bindings = ["_number", "_date", "_posted"]
                headers = ["№", "Дата", "Проведено"]
            else:
                if rows:
                    col_bindings = [k for k in rows[0] if not k.startswith("_")][:4]
                else:
                    col_bindings = ["_guid"]
                if not headers:
                    headers = col_bindings[:]

        if not headers:
            headers = col_bindings[:]

        m = QStandardItemModel(len(rows), len(headers))
        m.setHorizontalHeaderLabels(headers)
        for ri, row in enumerate(rows):
            for ci, col in enumerate(col_bindings):
                val = self._record_value_for_binding(row, col)
                val = self._format_cell_value(col, val)
                item = QStandardItem("" if val is None else str(val))
                item.setEditable(False)
                if ci == 0:
                    item.setData(str(row.get("_guid") or ""), Qt.ItemDataRole.UserRole)
                m.setItem(ri, ci, item)

        proxy = getattr(tv, "_filter_proxy", None)
        if proxy is not None:
            proxy.setSourceModel(m)
            if tv.model() is not proxy:
                tv.setModel(proxy)
        else:
            tv.setModel(m)
        tv.resizeColumnsToContents()
        # Cap column widths so very wide columns don't overflow
        for ci in range(tv.model().columnCount() if tv.model() else 0):
            if tv.columnWidth(ci) > 320:
                tv.setColumnWidth(ci, 320)
        self._configure_table_view(tv, len(headers))

        # Empty state hint
        _empty_lbl = getattr(tv, "_empty_label", None)
        if _empty_lbl is not None:
            _empty_lbl.setVisible(not rows)


    @staticmethod
    def _format_cell_value(col: str, val: object) -> object:
        """Format a cell value for display in the list table."""
        if val is None or val == "":
            return val
        col_lower = col.lower()
        # Boolean → checkmark
        if col_lower in ("_posted", "_deleted", "_predefined", "_is_folder",
                          "posted", "deleted", "predefined"):
            return "✓" if val else ""
        # Date fields → dd.MM.yyyy
        if "date" in col_lower or col_lower in ("_date", "_period"):
            s = str(val).strip()
            if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
                try:
                    from datetime import date as _dt
                    d = _dt.fromisoformat(s[:10])
                    return d.strftime("%d.%m.%Y")
                except Exception:
                    pass
        # Numbers with thousand separators
        if col_lower in ("_number",) or "amount" in col_lower or "price" in col_lower or "sum" in col_lower:
            try:
                n = float(val)
                if n == int(n):
                    return f"{int(n):,}".replace(",", " ")
                return f"{n:,.2f}".replace(",", " ")
            except (TypeError, ValueError):
                pass
        return val


    def _install_list_context_menu(self, tv, emit_cmd) -> None:
        """Attach right-click context menu to the list QTableView."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction

        tv.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def _show_menu(pos):
            idx = tv.indexAt(pos)
            has_sel = idx.isValid()
            menu = QMenu(tv)
            menu.setStyleSheet(
                "QMenu { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; }"
                "QMenu::item { padding: 6px 24px 6px 12px; }"
                "QMenu::item:selected { background: #EFF6FF; color: #1D4ED8; }"
            )
            act_create = QAction(f"{t('client_btn_create')}       Ctrl+N", tv)
            act_create.setEnabled(self._is_action_allowed("create"))
            act_create.triggered.connect(lambda: emit_cmd("create"))
            menu.addAction(act_create)

            if has_sel:
                act_edit = QAction(f"{t('act_open')}       Enter", tv)
                act_edit.setEnabled(self._is_action_allowed("edit"))
                act_edit.triggered.connect(lambda: emit_cmd("Edit"))
                menu.addAction(act_edit)

                act_copy = QAction(t("act_copy"), tv)
                act_copy.setEnabled(self._is_action_allowed("copy"))
                act_copy.triggered.connect(lambda: emit_cmd("copy"))
                menu.addAction(act_copy)

                menu.addSeparator()

                act_del = QAction(f"{t('client_mark_delete')}   Del", tv)
                act_del.setEnabled(self._is_action_allowed("delete"))
                act_del.triggered.connect(lambda: emit_cmd("delete"))
                menu.addAction(act_del)

            menu.addSeparator()
            act_ref = QAction(f"{t('act_refresh')}        F5", tv)
            act_ref.triggered.connect(lambda: emit_cmd("refresh"))
            menu.addAction(act_ref)

            menu.exec(tv.viewport().mapToGlobal(pos))

        tv.customContextMenuRequested.connect(_show_menu)


    def _fill_tp_table(
        self,
        tv: QTableView,
        binding: str,
        col_bindings: List[str],
        headers: List[str],
    ) -> None:
        """Завантажити табчастину для object_form."""
        if not headers:
            headers = ["—"]
            col_bindings = ["_"]

        m = QStandardItemModel(0, len(headers))
        m.setHorizontalHeaderLabels(headers)

        doc_guid = str(self._record.get("_guid") or "")
        if self._db and self._ctx.obj_name and binding and doc_guid:
            try:
                rows = self._db.table(_tp_table(self._ctx.obj_name, binding)).select(
                    where={"_doc_guid": doc_guid}, order_by="_line_no") or []
                for row in rows:
                    items = [QStandardItem(str(self._record_value_for_binding(row, cb) or "")) for cb in col_bindings]
                    m.appendRow(items)
            except Exception:
                pass

        if m.rowCount() == 0:
            m.appendRow([QStandardItem("") for _ in headers])

        tv.setModel(m)
        tv.resizeColumnsToContents()
        self._configure_table_view(tv, len(headers))


    def _build_container(self, node: FormNode) -> QWidget:
        props  = node.props if isinstance(node.props, dict) else {}
        layout = str(props.get("layout") or "vertical").strip().lower()
        chrome, level = self._container_chrome(node, layout)
        # Скидаємо прапорець — наступні вкладені контейнери вже не є root
        self._is_root_build = False
        title = str(node.title or "").strip()
        if layout == "absolute":
            host = _ResponsiveAbsoluteFrame(
                design_width=int(props.get("w") or 900),
                design_height=int(props.get("h") or 650),
            )
        elif chrome == "groupbox":
            host: QWidget = QGroupBox(title)
            try:
                host.setProperty("mp_form_group", True)
                host.setProperty("mp_form_group_chrome", "groupbox")
                host.setProperty("mp_form_group_level", str(level or "usual"))
            except Exception:
                pass
        else:
            host = QFrame()
            cast_frame = host
            cast_frame.setFrameShape(QFrame.Shape.NoFrame)
            cast_frame.setFrameShadow(QFrame.Shadow.Plain)
            try:
                cast_frame.setProperty("mp_form_group_chrome", "frame" if chrome == "frame" else "layout")
                cast_frame.setProperty("mp_form_group_level", str(level or "usual"))
            except Exception:
                pass

        if layout == "absolute":
            assert isinstance(host, _ResponsiveAbsoluteFrame)
            for ch in self._surface_children(node):
                cw = self._build_node(ch)
                cp = ch.props if isinstance(ch.props, dict) else {}
                host.add_absolute_child(
                    cw,
                    x=int(cp.get("x", 0)),
                    y=int(cp.get("y", 0)),
                    width=int(cp.get("w", 160)),
                    height=int(cp.get("h", 28)),
                )
                cw.show()
            return host

        if layout == "horizontal":
            margins = (8, 8, 8, 8) if chrome in {"groupbox", "frame"} else (0, 0, 0, 0)
            l = QHBoxLayout(host); l.setContentsMargins(*margins); l.setSpacing(8)
            for ch in self._surface_children(node):
                child = self._build_node(ch)
                # Imported empty label decorations are real layout spacers.
                # Do not erase their explicit width while making regular
                # controls responsive inside a horizontal group.
                if not bool(child.property("mp_form_decoration_spacer")):
                    child.setMinimumWidth(0)
                if self._field_title_mode(ch) != "none":
                    child = self._decorate_field(ch, child)
                alignment = self._layout_alignment_for_parent(ch, layout, child)
                if self._node_prefers_horizontal_stretch(ch):
                    child.setSizePolicy(QSizePolicy.Policy.Expanding, child.sizePolicy().verticalPolicy())
                if self._node_prefers_vertical_stretch(ch):
                    child.setSizePolicy(child.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Expanding)
                if alignment is None:
                    l.addWidget(child, 1 if self._node_prefers_horizontal_stretch(ch) else 0)
                else:
                    l.addWidget(child, 1 if self._node_prefers_horizontal_stretch(ch) else 0, alignment)
            l.addStretch(1); return host

        if layout == "vertical":
            margins = (8, 8, 8, 8) if chrome in {"groupbox", "frame"} else (0, 0, 0, 0)
            l = QGridLayout(host); l.setContentsMargins(*margins); l.setHorizontalSpacing(8); l.setVerticalSpacing(6)
            visible_children = self._surface_children(node)
            title_col_width = self._group_left_title_width(visible_children)
            row = 0
            stretch_rows: list[int] = []
            for ch in visible_children:
                child = self._build_node(ch)
                mode = self._field_title_mode(ch)
                alignment = self._layout_alignment_for_parent(ch, layout, child)
                if self._node_prefers_vertical_stretch(ch):
                    child.setSizePolicy(
                        QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Expanding,
                    )
                    stretch_rows.append(row)
                if mode == "left":
                    l.addWidget(
                        self._make_field_title_label(ch, with_colon=True, fixed_width=title_col_width),
                        row, 0, 1, 1,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    )
                    if self._field_prefers_expanding_width(ch):
                        child.setSizePolicy(QSizePolicy.Policy.Expanding, child.sizePolicy().verticalPolicy())
                        l.addWidget(child, row, 1)
                    elif alignment is None:
                        l.addWidget(child, row, 1)
                    else:
                        l.addWidget(child, row, 1, 1, 1, alignment)
                    row += 1
                    continue
                if mode == "top":
                    l.addWidget(
                        self._make_field_title_label(ch, with_colon=False),
                        row, 0, 1, 2,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    )
                    row += 1
                    if self._field_prefers_expanding_width(ch):
                        child.setSizePolicy(QSizePolicy.Policy.Expanding, child.sizePolicy().verticalPolicy())
                        l.addWidget(child, row, 0, 1, 2)
                    elif alignment is None:
                        l.addWidget(child, row, 0, 1, 2)
                    else:
                        l.addWidget(child, row, 0, 1, 2, alignment)
                    row += 1
                    continue
                if self._field_prefers_expanding_width(ch):
                    child.setSizePolicy(QSizePolicy.Policy.Expanding, child.sizePolicy().verticalPolicy())
                    l.addWidget(child, row, 0, 1, 2)
                elif alignment is None:
                    l.addWidget(child, row, 0, 1, 2)
                else:
                    l.addWidget(child, row, 0, 1, 2, alignment)
                row += 1
            # Keep the shared title width as a size hint from the labels, but
            # allow the column to shrink in a narrow client viewport.
            l.setColumnMinimumWidth(0, 0)
            l.setColumnStretch(1, 1)
            for stretch_row in stretch_rows:
                l.setRowStretch(stretch_row, 1)
            if not stretch_rows:
                l.setRowStretch(row, 1)
            return host

        if layout == "grid":
            margins = (8, 8, 8, 8) if chrome in {"groupbox", "frame"} else (0, 0, 0, 0)
            l = QGridLayout(host); l.setContentsMargins(*margins)
            l.setHorizontalSpacing(8); l.setVerticalSpacing(8)
            for ch in self._surface_children(node):
                cp = ch.props if isinstance(ch.props, dict) else {}
                grid = cp.get("grid") if isinstance(cp.get("grid"), dict) else {}
                child = self._build_node(ch)
                if self._field_title_mode(ch) != "none":
                    child = self._decorate_field(ch, child)
                alignment = self._layout_alignment_for_parent(ch, layout, child)
                row = int(grid.get("row", cp.get("row", 0)))
                col = int(grid.get("col", cp.get("col", 0)))
                rowspan = int(grid.get("rowspan", cp.get("rowspan", 1)))
                colspan = int(grid.get("colspan", cp.get("colspan", 1)))
                if self._node_prefers_horizontal_stretch(ch):
                    child.setSizePolicy(QSizePolicy.Policy.Expanding, child.sizePolicy().verticalPolicy())
                    try:
                        l.setColumnStretch(col, max(1, l.columnStretch(col)))
                    except Exception:
                        pass
                if self._node_prefers_vertical_stretch(ch):
                    child.setSizePolicy(child.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Expanding)
                    try:
                        l.setRowStretch(row, max(1, l.rowStretch(row)))
                    except Exception:
                        pass
                if alignment is None:
                    l.addWidget(child, row, col, rowspan, colspan)
                else:
                    l.addWidget(child, row, col, rowspan, colspan, alignment)
            l.setRowStretch(999,1); l.setColumnStretch(999,1); return host

        margins = (8, 8, 8, 8) if chrome in {"groupbox", "frame"} else (12, 12, 12, 12)
        l = QGridLayout(host); l.setContentsMargins(*margins); l.setHorizontalSpacing(8); l.setVerticalSpacing(6)
        visible_children = self._surface_children(node)
        title_col_width = self._group_left_title_width(visible_children)
        row = 0
        _stretch_rows: list[int] = []
        for ch in visible_children:
            child = self._build_node(ch)
            mode = self._field_title_mode(ch)
            alignment = self._layout_alignment_for_parent(ch, layout, child)
            # Вертикальне розтягування для таблиць/вкладок
            if self._node_prefers_vertical_stretch(ch):
                child.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                _stretch_rows.append(row)
            if mode == "left":
                l.addWidget(
                    self._make_field_title_label(ch, with_colon=True, fixed_width=title_col_width),
                    row, 0, 1, 1,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
                if self._field_prefers_expanding_width(ch):
                    child.setSizePolicy(QSizePolicy.Policy.Expanding, child.sizePolicy().verticalPolicy())
                    l.addWidget(child, row, 1)
                elif alignment is None:
                    l.addWidget(child, row, 1)
                else:
                    l.addWidget(child, row, 1, 1, 1, alignment)
                row += 1
                continue
            if mode == "top":
                l.addWidget(self._make_field_title_label(ch, with_colon=False), row, 0, 1, 2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                row += 1
                if self._field_prefers_expanding_width(ch):
                    child.setSizePolicy(QSizePolicy.Policy.Expanding, child.sizePolicy().verticalPolicy())
                    l.addWidget(child, row, 0, 1, 2)
                elif alignment is None:
                    l.addWidget(child, row, 0, 1, 2)
                else:
                    l.addWidget(child, row, 0, 1, 2, alignment)
                row += 1
                continue
            if self._field_prefers_expanding_width(ch):
                child.setSizePolicy(QSizePolicy.Policy.Expanding, child.sizePolicy().verticalPolicy())
                l.addWidget(child, row, 0, 1, 2)
            elif alignment is None:
                l.addWidget(child, row, 0, 1, 2)
            else:
                l.addWidget(child, row, 0, 1, 2, alignment)
            row += 1
        l.setColumnMinimumWidth(0, 0)
        l.setColumnStretch(1, 1)
        # Рядки з таблицями/вкладками розтягуємо вертикально
        for r in _stretch_rows:
            l.setRowStretch(r, 1)
        if not _stretch_rows:
            l.setRowStretch(row, 1)  # fallback — порожній рядок знизу
        return host
