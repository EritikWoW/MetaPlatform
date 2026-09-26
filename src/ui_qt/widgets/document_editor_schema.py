from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QObject

from src.ui_qt.i18n import t

from .document_editor_payload import (
    _SCHEMA_REF_OBJECT_TYPES,
    _as_bool,
    _as_int,
    _localized_enum_label,
    _localized_text,
)


_REF_TARGET_GROUP_I18N: dict[str, str] = {
    "Catalog": "schema.ref_group.catalog",
    "Document": "schema.ref_group.document",
    "Enum": "schema.ref_group.enumeration",
    "BusinessProcess": "schema.ref_group.business_process",
    "Task": "schema.ref_group.task",
    "ChartOfCharacteristicTypes": "schema.ref_group.chart_of_characteristic_types",
    "ChartOfAccounts": "schema.ref_group.chart_of_accounts",
    "ExchangePlan": "schema.ref_group.exchange_plan",
}

_SCHEMA_ICON_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"
_SCHEMA_REQ_ICON_PATH = _SCHEMA_ICON_DIR / "schema_requisite.svg"
_SCHEMA_TABLE_ICON_PATH = _SCHEMA_ICON_DIR / "schema_table.svg"


def _reference_target_group_title(prefix: str) -> str:
    key = _REF_TARGET_GROUP_I18N.get(str(prefix or "").strip())
    return t(key) if key else str(prefix or "").strip()


def _localized_text_map(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        out: dict[str, str] = {}
        for lang in ("uk", "en"):
            text = str(value.get(lang) or "").strip()
            if text:
                out[lang] = text
        return out
    text = str(value or "").strip()
    return {"uk": text} if text else {}


class _LocalizedTextDialog(QDialog):
    def __init__(self, *, current_value: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("localized_text.dialog_title"))
        self.resize(420, 170)

        current = _localized_text_map(current_value)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(form)

        self.ed_uk = QLineEdit(self)
        self.ed_en = QLineEdit(self)
        self.ed_uk.setText(current.get("uk", ""))
        self.ed_en.setText(current.get("en", ""))
        self.ed_uk.setPlaceholderText(t("localized_text.placeholder_uk"))
        self.ed_en.setPlaceholderText(t("localized_text.placeholder_en"))
        form.addRow(QLabel(t("localized_text.lang_uk")), self.ed_uk)
        form.addRow(QLabel(t("localized_text.lang_en")), self.ed_en)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def value(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for lang, widget in (("uk", self.ed_uk), ("en", self.ed_en)):
            text = str(widget.text() or "").strip()
            if text:
                out[lang] = text
        return out


class _LocalizedTextPicker(QWidget):
    valueChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value: dict[str, str] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.ed_value = QLineEdit(self)
        self.ed_value.setReadOnly(True)
        layout.addWidget(self.ed_value, 1)

        self.btn_pick = QPushButton("...", self)
        self.btn_pick.setObjectName("LocalizedTextPickerButton")
        self.btn_pick.setFixedWidth(34)
        self.btn_pick.clicked.connect(self._pick)
        layout.addWidget(self.btn_pick)

        self._refresh_display()

    def set_value(self, value: Any, *, emit_signal: bool = False) -> None:
        self._value = _localized_text_map(value)
        self._refresh_display()
        if emit_signal:
            self.valueChanged.emit(dict(self._value))

    def current_value(self) -> dict[str, str]:
        return dict(self._value)

    def currentText(self) -> str:
        return str(self.ed_value.text() or "").strip()

    def _refresh_display(self) -> None:
        self.ed_value.setText(_localized_text(self._value))
        tooltip_lines: list[str] = []
        if self._value.get("uk"):
            tooltip_lines.append(f"UK: {self._value['uk']}")
        if self._value.get("en"):
            tooltip_lines.append(f"EN: {self._value['en']}")
        self.ed_value.setToolTip("\n".join(tooltip_lines))

    def _pick(self) -> None:
        dlg = _LocalizedTextDialog(current_value=self._value, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.set_value(dlg.value(), emit_signal=True)


class _ReferenceTargetDialog(QDialog):
    def __init__(
        self,
        *,
        targets: list[tuple[str, str]],
        current_value: str = "",
        current_values: list[str] | None = None,
        allowed_prefixes: set[str] | None = None,
        multi_select: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("schema.ref_target_dialog_title"))
        self.resize(720, 520)
        self._targets = list(targets)
        self._allowed_prefixes = {str(item or "").strip() for item in (allowed_prefixes or set()) if str(item or "").strip()}
        self._multi_select = bool(multi_select)
        self._selected_value = str(current_value or "").strip()
        self._selected_values = [
            str(item or "").strip()
            for item in (current_values or [])
            if str(item or "").strip()
        ]
        if self._selected_value and self._selected_value not in self._selected_values:
            self._selected_values.insert(0, self._selected_value)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.chk_compound_type = QCheckBox(t("schema.compound_type"), self)
        self.chk_compound_type.setChecked(self._multi_select)
        root.addWidget(self.chk_compound_type)

        self.ed_search = QLineEdit(self)
        self.ed_search.setPlaceholderText(t("schema.ref_target_search_placeholder"))
        root.addWidget(self.ed_search)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setUniformRowHeights(True)
        root.addWidget(self.tree, 1)

        self.bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.bb.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        root.addWidget(self.bb)

        self.ed_search.textChanged.connect(self._reload)
        self.chk_compound_type.stateChanged.connect(self._on_compound_type_toggled)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.bb.accepted.connect(self._accept_selected)
        self.bb.rejected.connect(self.reject)

        self._reload()

    def selected_value(self) -> str:
        return str(self._selected_value or "").strip()

    def selected_values(self) -> list[str]:
        return list(self._selected_values)

    def multi_select_enabled(self) -> bool:
        return bool(self._multi_select)

    def _normalize_targets(self) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        for label, value in self._targets:
            raw = str(value or "").strip()
            if not raw:
                continue
            prefix = raw.split(".", 1)[0] if "." in raw else ""
            if self._allowed_prefixes and prefix not in self._allowed_prefixes:
                continue
            out.append((prefix, str(label or raw), raw))
        return out

    def _reload(self) -> None:
        filter_text = str(self.ed_search.text() or "").strip().casefold()
        current_value = self.selected_value()
        current_values = {str(item or "").strip() for item in self.selected_values()}
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        selection_item: QTreeWidgetItem | None = None

        for prefix, label, value in self._normalize_targets():
            haystack = f"{label} {value}".casefold()
            if filter_text and filter_text not in haystack:
                continue
            group = groups.get(prefix)
            if group is None:
                group = QTreeWidgetItem([_reference_target_group_title(prefix)])
                group.setData(0, Qt.ItemDataRole.UserRole, "")
                group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.tree.addTopLevelItem(group)
                groups[prefix] = group
            child = QTreeWidgetItem([label])
            child.setToolTip(0, value)
            child.setData(0, Qt.ItemDataRole.UserRole, value)
            if self._multi_select:
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(
                    0,
                    Qt.CheckState.Checked if value in current_values else Qt.CheckState.Unchecked,
                )
            group.addChild(child)
            if current_value and value == current_value:
                selection_item = child

        self.tree.expandAll()
        if selection_item is not None:
            self.tree.setCurrentItem(selection_item)
        elif self.tree.topLevelItemCount() > 0:
            first_group = self.tree.topLevelItem(0)
            if first_group is not None and first_group.childCount() > 0:
                self.tree.setCurrentItem(first_group.child(0))
        self._update_ok_enabled()

    def _update_ok_enabled(self) -> None:
        if self._multi_select:
            self.bb.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self._checked_values()))
            return
        current = self.tree.currentItem()
        value = str(current.data(0, Qt.ItemDataRole.UserRole) or "").strip() if current is not None else ""
        self.bb.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(value))

    def _checked_values(self) -> list[str]:
        values: list[str] = []
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            if group is None:
                continue
            for j in range(group.childCount()):
                child = group.child(j)
                if child is None:
                    continue
                if child.checkState(0) != Qt.CheckState.Checked:
                    continue
                value = str(child.data(0, Qt.ItemDataRole.UserRole) or "").strip()
                if value:
                    values.append(value)
        return values

    def _on_current_item_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        self._update_ok_enabled()
        if self._multi_select:
            return
        if current is None:
            return
        value = str(current.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        if value:
            self._selected_value = value

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if not self._multi_select:
            return
        value = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        if not value:
            return
        self._selected_values = self._checked_values()
        if self._selected_values:
            self._selected_value = self._selected_values[0]
        else:
            self._selected_value = ""
        self._update_ok_enabled()

    def _accept_selected(self) -> None:
        if self._multi_select:
            self._selected_values = self._checked_values()
            self._selected_value = self._selected_values[0] if self._selected_values else ""
            if not self._selected_values:
                return
            self.accept()
            return
        current = self.tree.currentItem()
        if current is None:
            return
        value = str(current.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        if not value:
            return
        self._selected_value = value
        self.accept()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._multi_select:
            value = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
            if not value:
                return
            item.setCheckState(
                0,
                Qt.CheckState.Unchecked
                if item.checkState(0) == Qt.CheckState.Checked
                else Qt.CheckState.Checked,
            )
            return
        if str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip():
            self._accept_selected()

    def _on_compound_type_toggled(self, _state: int) -> None:
        enabled = self.chk_compound_type.isChecked()
        if enabled == self._multi_select:
            return
        self._multi_select = enabled
        if self._multi_select:
            current = str(self._selected_value or "").strip()
            if current and current not in self._selected_values:
                self._selected_values.insert(0, current)
        else:
            if self._selected_values:
                self._selected_value = str(self._selected_values[0] or "").strip()
            self._selected_values = [self._selected_value] if self._selected_value else []
        self._reload()


class _ReferenceTargetPicker(QWidget):
    valueChanged = Signal(str)
    selectionChanged = Signal(object)
    modeChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._targets: list[tuple[str, str]] = []
        self._allowed_prefixes: set[str] = set()
        self._current_value = ""
        self._current_values: list[str] = []
        self._multi_select = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.ed_value = QLineEdit(self)
        self.ed_value.setReadOnly(True)
        self.ed_value.setPlaceholderText(t("schema.ref_target_empty"))
        layout.addWidget(self.ed_value, 1)

        self.btn_pick = QPushButton("...", self)
        self.btn_pick.setObjectName("RefTargetPickerButton")
        self.btn_pick.setFixedWidth(34)
        self.btn_pick.clicked.connect(self._pick)
        layout.addWidget(self.btn_pick)

    def set_targets(self, targets: list[tuple[str, str]]) -> None:
        self._targets = list(targets)
        self._refresh_display()

    def set_allowed_prefixes(self, prefixes: set[str] | None) -> None:
        self._allowed_prefixes = {str(item or "").strip() for item in (prefixes or set()) if str(item or "").strip()}
        self._refresh_display()

    def set_multi_select(self, enabled: bool, *, emit_signal: bool = False) -> None:
        changed = bool(enabled) != self._multi_select
        self._multi_select = bool(enabled)
        self._refresh_display()
        if changed and emit_signal:
            self.modeChanged.emit(self._multi_select)

    def set_value(self, value: str, *, emit_signal: bool = False) -> None:
        self.set_values([str(value or "").strip()] if str(value or "").strip() else [], emit_signal=emit_signal)

    def set_values(self, values: list[str], *, emit_signal: bool = False) -> None:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in values or []:
            text = str(item or "").strip()
            if not text or text.casefold() in seen:
                continue
            cleaned.append(text)
            seen.add(text.casefold())
        self._current_values = cleaned
        self._current_value = cleaned[0] if cleaned else ""
        self._refresh_display()
        if emit_signal:
            self.valueChanged.emit(self._current_value)
            self.selectionChanged.emit(self.currentValues() if self._multi_select else self.currentValue())

    def currentValue(self) -> str:
        return str(self._current_value or "").strip()

    def currentValues(self) -> list[str]:
        return list(self._current_values)

    def currentText(self) -> str:
        return str(self.ed_value.text() or "").strip()

    def multi_select_enabled(self) -> bool:
        return bool(self._multi_select)

    def _allowed_target_entries(self) -> list[tuple[str, str]]:
        if not self._allowed_prefixes:
            return list(self._targets)
        out: list[tuple[str, str]] = []
        for label, value in self._targets:
            prefix = str(value or "").split(".", 1)[0]
            if prefix in self._allowed_prefixes:
                out.append((label, value))
        return out

    def _refresh_display(self) -> None:
        raw_values = self.currentValues()
        display = ""
        labels: list[str] = []
        for raw in raw_values:
            for label, value in self._targets:
                plain = str(value or "").split(".", 1)[-1] if "." in str(value or "") else str(value or "")
                if raw in {str(value or ""), plain, str(label or "")}:
                    labels.append(str(label or value or raw))
                    break
            else:
                labels.append(raw)
        if self._multi_select:
            if len(labels) <= 3:
                display = ", ".join(labels)
            elif labels:
                display = f"{len(labels)} {t('schema.ref_target_selected_count')}"
        else:
            display = labels[0] if labels else self.currentValue()
        self.ed_value.setText(display)
        self.ed_value.setToolTip("\n".join(raw_values))
        self.btn_pick.setEnabled(bool(self._allowed_target_entries()))

    def _pick(self) -> None:
        dlg = _ReferenceTargetDialog(
            targets=self._allowed_target_entries(),
            current_value=self.currentValue(),
            current_values=self.currentValues(),
            allowed_prefixes=self._allowed_prefixes,
            multi_select=self._multi_select,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.set_multi_select(dlg.multi_select_enabled(), emit_signal=True)
        if self._multi_select:
            self.set_values(dlg.selected_values(), emit_signal=True)
        else:
            self.set_value(dlg.selected_value(), emit_signal=True)


class _DocumentSchemaPropertiesWidget(QWidget):
    itemFieldChanged = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._block = False
        self._mode = ""
        self._title = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.lbl_target = QLabel(t("doc.data_selection_hint"))
        self.lbl_target.setWordWrap(True)
        self.lbl_target.setStyleSheet("font-weight: 600;")
        root.addWidget(self.lbl_target)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(8)
        root.addLayout(form)

        self.ed_name = QLineEdit()
        self.ed_synonym = _LocalizedTextPicker()
        self.cb_type = QComboBox()
        for key in (
            "string",
            "number",
            "bool",
            "date",
            "datetime",
            "ref",
            "enum_ref",
            "any_ref",
            "unknown",
        ):
            self.cb_type.addItem(_localized_enum_label("schema_type", key), key)
        self.cb_ref_name = _ReferenceTargetPicker()
        self.chk_required = QCheckBox()
        self.chk_read_only = QCheckBox()
        self.sp_string_length = QSpinBox()
        self.sp_string_length.setRange(0, 4096)
        self.sp_number_digits = QSpinBox()
        self.sp_number_digits.setRange(0, 38)
        self.sp_number_fraction_digits = QSpinBox()
        self.sp_number_fraction_digits.setRange(0, 15)
        self.cb_fill_checking = QComboBox()
        self.cb_fill_checking.setEditable(True)
        for key in ("", "DontCheck", "ShowError", "ShowWarning"):
            self.cb_fill_checking.addItem(_localized_enum_label("fill_checking", key), key)
        self.ed_comment = QPlainTextEdit()
        self.ed_comment.setMinimumHeight(90)

        self._rows: dict[str, tuple[QLabel, QWidget]] = {
            "name": (QLabel(t("prop_name")), self.ed_name),
            "synonym": (QLabel(t("prop_synonym")), self.ed_synonym),
            "type": (QLabel(t("schema.col.type")), self.cb_type),
            "ref_name": (QLabel(t("prop_ref_name")), self.cb_ref_name),
            "string_length": (QLabel(t("schema.string_length")), self.sp_string_length),
            "number_digits": (QLabel(t("schema.number_digits")), self.sp_number_digits),
            "number_fraction_digits": (
                QLabel(t("schema.number_fraction_digits")),
                self.sp_number_fraction_digits,
            ),
            "required": (QLabel(t("schema.col.required")), self.chk_required),
            "read_only": (QLabel(t("prop_read_only")), self.chk_read_only),
            "fill_checking": (QLabel(t("prop_fill_check")), self.cb_fill_checking),
            "comment": (QLabel(t("prop_comment")), self.ed_comment),
        }
        for label, widget in self._rows.values():
            form.addRow(label, widget)

        self.ed_field_help = QPlainTextEdit(self)
        self.ed_field_help.setReadOnly(True)
        self.ed_field_help.setMinimumHeight(56)
        self.ed_field_help.setMaximumHeight(80)
        root.addWidget(self.ed_field_help)
        root.addStretch(1)

        self.ed_name.editingFinished.connect(lambda: self._emit_field("name", self.ed_name.text()))
        self.ed_synonym.valueChanged.connect(lambda value: self._emit_field("title", value))
        self.cb_type.currentIndexChanged.connect(self._on_type_changed)
        self.cb_ref_name.selectionChanged.connect(self._on_reference_targets_changed)
        self.cb_ref_name.modeChanged.connect(self._on_compound_type_changed)
        self.sp_string_length.valueChanged.connect(
            lambda value: self._emit_field("string_length", int(value))
        )
        self.sp_number_digits.valueChanged.connect(
            lambda value: self._emit_field("number_digits", int(value))
        )
        self.sp_number_fraction_digits.valueChanged.connect(
            lambda value: self._emit_field("number_fraction_digits", int(value))
        )
        self.chk_required.stateChanged.connect(
            lambda _s: self._emit_field("required", self.chk_required.isChecked())
        )
        self.chk_read_only.stateChanged.connect(
            lambda _s: self._emit_field("read_only", self.chk_read_only.isChecked())
        )
        self.cb_fill_checking.currentTextChanged.connect(
            lambda text: self._emit_field("fill_checking", text)
        )
        self.ed_comment.textChanged.connect(
            lambda: self._emit_field("comment", self.ed_comment.toPlainText())
        )

        self._help_keys: dict[QObject, str] = {}
        for key, (_label, widget) in self._rows.items():
            self._register_help_widget(key, widget)
        self._set_help_for_key("name")

        self.clear_target()

    def clear_target(self) -> None:
        self.set_target("", "", {})

    def set_target(self, mode: str, title: str, item: dict[str, Any]) -> None:
        self._block = True
        try:
            self._mode = str(mode or "")
            self._title = str(title or "")
            if not self._mode:
                self.lbl_target.setText(t("doc.data_selection_hint"))
                self._set_enabled(False)
                for _, widget in self._rows.values():
                    if isinstance(widget, QLineEdit):
                        widget.clear()
                    elif isinstance(widget, QPlainTextEdit):
                        widget.clear()
                    elif isinstance(widget, QCheckBox):
                        widget.setChecked(False)
                    elif isinstance(widget, QComboBox):
                        widget.setCurrentIndex(0)
                    elif isinstance(widget, _ReferenceTargetPicker):
                        widget.set_multi_select(False, emit_signal=False)
                        widget.set_values([], emit_signal=False)
                    elif isinstance(widget, _LocalizedTextPicker):
                        widget.set_value({}, emit_signal=False)
                self._set_help_for_key("name")
                return

            self.lbl_target.setText(title)
            self._set_enabled(True)
            self.ed_name.setText(str(item.get("name") or ""))
            self.ed_synonym.set_value(item.get("title"), emit_signal=False)
            self._set_combo_data(self.cb_type, str(item.get("type") or "string"), "string")
            compound_type = bool(item.get("compound_type"))
            ref_targets = item.get("ref_targets") if isinstance(item.get("ref_targets"), list) else []
            if not ref_targets:
                single_ref = str(item.get("ref_name") or "").strip()
                ref_targets = [single_ref] if single_ref else []
            if len(ref_targets) > 1:
                compound_type = True
            self.cb_ref_name.set_multi_select(compound_type, emit_signal=False)
            self._set_reference_values(ref_targets)
            string_q = (
                item.get("string_qualifiers")
                if isinstance(item.get("string_qualifiers"), dict)
                else {}
            )
            number_q = (
                item.get("number_qualifiers")
                if isinstance(item.get("number_qualifiers"), dict)
                else {}
            )
            self.sp_string_length.setValue(_as_int(string_q.get("length"), 0))
            self.sp_number_digits.setValue(_as_int(number_q.get("digits"), 0))
            self.sp_number_fraction_digits.setValue(
                _as_int(number_q.get("fraction_digits"), 0)
            )
            self.chk_required.setChecked(_as_bool(item.get("required")))
            self.chk_read_only.setChecked(_as_bool(item.get("read_only")))
            fill = str(item.get("fill_checking") or "")
            idx = self.cb_fill_checking.findText(fill)
            if idx < 0 and fill:
                self.cb_fill_checking.addItem(fill, fill)
                idx = self.cb_fill_checking.findText(fill)
            self.cb_fill_checking.setCurrentIndex(idx if idx >= 0 else 0)
            self.ed_comment.setPlainText(str(item.get("comment") or ""))

            show_schema_fields = self._mode in {"requisite", "column"}
            self._set_row_visible("type", show_schema_fields)
            self._set_row_visible("required", show_schema_fields)
            self._set_row_visible("read_only", show_schema_fields)
            self._set_row_visible("fill_checking", show_schema_fields)
            self._update_type_specific_rows(str(self.cb_type.currentData() or ""))
            self._set_help_for_key("name")
        finally:
            self._block = False

    def _set_enabled(self, enabled: bool) -> None:
        for _, widget in self._rows.values():
            widget.setEnabled(enabled)

    def _set_row_visible(self, key: str, visible: bool) -> None:
        label, widget = self._rows[key]
        label.setVisible(visible)
        widget.setVisible(visible)

    def _set_combo_data(self, combo: QComboBox, value: str, default: str = "") -> None:
        target = str(value or default or "").strip().lower()
        idx = combo.findData(target)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def set_reference_targets(self, targets: list[tuple[str, str]]) -> None:
        self.cb_ref_name.set_targets(targets)
        self._set_reference_values(self.cb_ref_name.currentValues() or ([self.cb_ref_name.currentValue()] if self.cb_ref_name.currentValue() else []))

    def _set_reference_values(self, values: list[str]) -> None:
        self.cb_ref_name.set_values(values, emit_signal=False)

    def _on_type_changed(self, _index: int) -> None:
        type_name = str(self.cb_type.currentData() or "")
        self._update_type_specific_rows(type_name)
        self._emit_field("type", type_name)

    def _on_compound_type_changed(self, enabled: bool) -> None:
        self._emit_field("compound_type", enabled)
        self._on_reference_targets_changed(self.cb_ref_name.currentValues() if enabled else self.cb_ref_name.currentValue())

    def _on_reference_targets_changed(self, value: object) -> None:
        if self._block:
            return
        if self.cb_ref_name.multi_select_enabled():
            if isinstance(value, list):
                targets = [str(item or "").strip() for item in value if str(item or "").strip()]
            else:
                text = str(value or "").strip()
                targets = [text] if text else []
            self.itemFieldChanged.emit("ref_targets", targets)
            return
        self.itemFieldChanged.emit("ref_name", str(self.cb_ref_name.currentValue() or "").strip())

    def _update_type_specific_rows(self, type_name: str) -> None:
        type_key = str(type_name or "").strip().lower()
        show_schema_fields = self._mode in {"requisite", "column"}
        show_ref = show_schema_fields and type_key in {"ref", "enum_ref", "any_ref"}
        self._set_row_visible("ref_name", show_ref)
        if type_key == "enum_ref":
            self.cb_ref_name.set_allowed_prefixes({"Enum"})
        else:
            self.cb_ref_name.set_allowed_prefixes(set())
        self._set_row_visible("string_length", show_schema_fields and type_key == "string")
        self._set_row_visible("number_digits", show_schema_fields and type_key == "number")
        self._set_row_visible(
            "number_fraction_digits",
            show_schema_fields and type_key == "number",
        )

    def _emit_field(self, key: str, value: object) -> None:
        if self._block or not self._mode:
            return
        self.itemFieldChanged.emit(key, value)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FocusIn:
            key = self._help_keys.get(watched)
            if key:
                self._set_help_for_key(key)
        return super().eventFilter(watched, event)

    def _register_help_widget(self, key: str, widget: QWidget) -> None:
        self._help_keys[widget] = key
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            self._help_keys[child] = key
            child.installEventFilter(self)

    def _set_help_for_key(self, key: str) -> None:
        self.ed_field_help.setPlainText(t(f"schema.help.{key}"))


class DocumentEditorSchemaMixin:
    def _meta_int(self, meta: dict[str, Any], key: str, default: int = 0) -> int:
        try:
            raw = meta.get(key, default)
            return int(default if raw is None else raw)
        except Exception:
            return int(default)

    def _schema_icon(self, kind: str) -> QIcon:
        cache = getattr(self, "_schema_icon_cache", None)
        if cache is None:
            cache = {
                "requisite": QIcon(str(_SCHEMA_REQ_ICON_PATH)),
                "column": QIcon(str(_SCHEMA_REQ_ICON_PATH)),
                "tabular_part": QIcon(str(_SCHEMA_TABLE_ICON_PATH)),
            }
            self._schema_icon_cache = cache
        return cache.get(str(kind or "").strip(), QIcon())

    def _schema_unique_name(self, existing: list[dict[str, Any]], prefix: str) -> str:
        used = {
            str(item.get("name") or "").strip().casefold()
            for item in existing
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        base = str(prefix or "").strip() or "Item"
        if base.casefold() not in used:
            return base
        index = 2
        while True:
            candidate = f"{base}{index}"
            if candidate.casefold() not in used:
                return candidate
            index += 1

    def _set_schema_selection_meta(self, meta: dict[str, Any] | None) -> None:
        self._schema_selection = dict(meta) if isinstance(meta, dict) else None

    def _update_schema_buttons(self) -> None:
        req_meta = (
            self.tree_requisites.currentItem().data(0, Qt.ItemDataRole.UserRole)
            if hasattr(self, "tree_requisites") and self.tree_requisites.currentItem() is not None
            else None
        )
        tp_meta = (
            self.tree_tabular_parts.currentItem().data(0, Qt.ItemDataRole.UserRole)
            if hasattr(self, "tree_tabular_parts") and self.tree_tabular_parts.currentItem() is not None
            else None
        )
        req_kind = str(req_meta.get("kind") or "") if isinstance(req_meta, dict) else ""
        tp_kind = str(tp_meta.get("kind") or "") if isinstance(tp_meta, dict) else ""
        if hasattr(self, "btn_req_delete"):
            self.btn_req_delete.setEnabled(req_kind == "requisite")
        if hasattr(self, "btn_tp_add_column"):
            self.btn_tp_add_column.setEnabled(tp_kind in {"tabular_part", "column"})
        if hasattr(self, "btn_tp_delete"):
            self.btn_tp_delete.setEnabled(tp_kind in {"tabular_part", "column"})

    def _on_add_requisite(self) -> None:
        items = [dict(item) for item in self._model.requisites if isinstance(item, dict)]
        name = self._schema_unique_name(items, "НовийРеквізит")
        items.append({"name": name, "title": {"uk": name, "en": name}, "type": "string"})
        self._payload_raw["requisites"] = items
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({"requisites": items})
        self._set_schema_selection_meta({"kind": "requisite", "index": len(items) - 1})
        self._reload_data_tree()

    def _on_delete_selected_requisite(self) -> None:
        current = self.tree_requisites.currentItem() if hasattr(self, "tree_requisites") else None
        meta = current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        if not isinstance(meta, dict) or str(meta.get("kind") or "") != "requisite":
            return
        index = self._meta_int(meta, "index", -1)
        items = [dict(item) for item in self._model.requisites if isinstance(item, dict)]
        if not (0 <= index < len(items)):
            return
        items.pop(index)
        self._payload_raw["requisites"] = items
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({"requisites": items})
        next_index = min(index, len(items) - 1)
        self._set_schema_selection_meta({"kind": "requisite", "index": next_index} if next_index >= 0 else None)
        self._reload_data_tree()

    def _on_add_tabular_part(self) -> None:
        parts = self._clone_tabular_parts()
        name = self._schema_unique_name(parts, "НоваТабличнаЧастина")
        parts.append({"name": name, "title": {"uk": name, "en": name}, "columns": []})
        self._payload_raw["tabular_parts"] = parts
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({"tabular_parts": parts})
        self._set_schema_selection_meta({"kind": "tabular_part", "index": len(parts) - 1})
        self._reload_data_tree()

    def _on_add_tabular_part_column(self) -> None:
        current = self.tree_tabular_parts.currentItem() if hasattr(self, "tree_tabular_parts") else None
        meta = current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        if not isinstance(meta, dict):
            return
        kind = str(meta.get("kind") or "")
        if kind not in {"tabular_part", "column"}:
            return
        tp_index = self._meta_int(meta, "index" if kind == "tabular_part" else "tp_index", -1)
        parts = self._clone_tabular_parts()
        if not (0 <= tp_index < len(parts)):
            return
        columns = parts[tp_index].get("columns")
        if not isinstance(columns, list):
            columns = []
            parts[tp_index]["columns"] = columns
        name = self._schema_unique_name([dict(col) for col in columns if isinstance(col, dict)], "НовийРеквізитТЧ")
        columns.append({"name": name, "title": {"uk": name, "en": name}, "type": "string"})
        self._payload_raw["tabular_parts"] = parts
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({"tabular_parts": parts})
        self._set_schema_selection_meta({"kind": "column", "tp_index": tp_index, "col_index": len(columns) - 1})
        self._reload_data_tree()

    def _on_delete_selected_tabular_item(self) -> None:
        current = self.tree_tabular_parts.currentItem() if hasattr(self, "tree_tabular_parts") else None
        meta = current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        if not isinstance(meta, dict):
            return
        kind = str(meta.get("kind") or "")
        parts = self._clone_tabular_parts()
        next_meta: dict[str, Any] | None = None
        if kind == "tabular_part":
            index = self._meta_int(meta, "index", -1)
            if not (0 <= index < len(parts)):
                return
            parts.pop(index)
            if parts:
                next_index = min(index, len(parts) - 1)
                next_meta = {"kind": "tabular_part", "index": next_index}
        elif kind == "column":
            tp_index = self._meta_int(meta, "tp_index", -1)
            col_index = self._meta_int(meta, "col_index", -1)
            if not (0 <= tp_index < len(parts)):
                return
            columns = parts[tp_index].get("columns")
            if not isinstance(columns, list) or not (0 <= col_index < len(columns)):
                return
            columns.pop(col_index)
            if columns:
                next_index = min(col_index, len(columns) - 1)
                next_meta = {"kind": "column", "tp_index": tp_index, "col_index": next_index}
            else:
                next_meta = {"kind": "tabular_part", "index": tp_index}
        else:
            return
        self._payload_raw["tabular_parts"] = parts
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({"tabular_parts": parts})
        self._set_schema_selection_meta(next_meta)
        self._reload_data_tree()

    def _reload_data_tree(self) -> None:
        if not hasattr(self, "tree_requisites") or not hasattr(self, "tree_tabular_parts"):
            return
        self.tree_requisites.clear()
        self.tree_tabular_parts.clear()

        for idx, req in enumerate(self._model.requisites):
            if not isinstance(req, dict):
                continue
            title = _localized_text(req.get("title")) or str(req.get("name") or "")
            if title:
                item = QTreeWidgetItem([title])
                item.setData(0, Qt.ItemDataRole.UserRole, {"kind": "requisite", "index": idx})
                item.setIcon(0, self._schema_icon("requisite"))
                self.tree_requisites.addTopLevelItem(item)

        for tp_idx, tp in enumerate(self._model.tabular_parts):
            if not isinstance(tp, dict):
                continue
            title = _localized_text(tp.get("title")) or str(tp.get("name") or "")
            if not title:
                continue
            tp_item = QTreeWidgetItem([title])
            tp_item.setData(0, Qt.ItemDataRole.UserRole, {"kind": "tabular_part", "index": tp_idx})
            tp_item.setIcon(0, self._schema_icon("tabular_part"))
            for col_idx, col in enumerate(tp.get("columns") or []):
                if not isinstance(col, dict):
                    continue
                col_title = _localized_text(col.get("title")) or str(col.get("name") or "")
                if col_title:
                    col_item = QTreeWidgetItem([col_title])
                    col_item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        {"kind": "column", "tp_index": tp_idx, "col_index": col_idx},
                    )
                    col_item.setIcon(0, self._schema_icon("column"))
                    tp_item.addChild(col_item)
            self.tree_tabular_parts.addTopLevelItem(tp_item)
        self.tree_tabular_parts.expandAll()

        self._restore_schema_selection()
        self._update_schema_buttons()

    def _clear_other_tree_selection(self, other: QTreeWidget) -> None:
        other.blockSignals(True)
        try:
            other.clearSelection()
            other.setCurrentItem(None)
        finally:
            other.blockSignals(False)

    def _on_requisite_selected(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is not None:
            self._clear_other_tree_selection(self.tree_tabular_parts)
        self._apply_schema_selection(current)
        self._update_schema_buttons()

    def _on_tabular_part_selected(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is not None:
            self._clear_other_tree_selection(self.tree_requisites)
        self._apply_schema_selection(current)
        self._update_schema_buttons()

    def _apply_schema_selection(self, item: QTreeWidgetItem | None) -> None:
        meta = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(meta, dict):
            self._schema_selection = None
            self._schema_props.clear_target()
            self._update_schema_buttons()
            return

        kind = str(meta.get("kind") or "")
        if kind == "requisite":
            index = int(meta.get("index") or 0)
            data = (
                dict(self._model.requisites[index])
                if 0 <= index < len(self._model.requisites)
                else {}
            )
        elif kind == "tabular_part":
            index = int(meta.get("index") or 0)
            data = (
                dict(self._model.tabular_parts[index])
                if 0 <= index < len(self._model.tabular_parts)
                else {}
            )
        elif kind == "column":
            tp_index = int(meta.get("tp_index") or 0)
            col_index = int(meta.get("col_index") or 0)
            cols = (
                self._model.tabular_parts[tp_index].get("columns")
                if 0 <= tp_index < len(self._model.tabular_parts)
                else []
            )
            data = (
                dict(cols[col_index])
                if isinstance(cols, list)
                and 0 <= col_index < len(cols)
                and isinstance(cols[col_index], dict)
                else {}
            )
        else:
            data = {}
        title = _localized_text(data.get("title")) or str(data.get("name") or "")
        self._schema_selection = dict(meta)
        self._schema_props.set_target(kind, title, data)
        self._update_schema_buttons()

    def _restore_schema_selection(self) -> None:
        meta = self._schema_selection or {}
        if not meta:
            self._schema_props.clear_target()
            self._update_schema_buttons()
            return
        kind = str(meta.get("kind") or "")
        target_tree = self.tree_requisites if kind == "requisite" else self.tree_tabular_parts
        for i in range(target_tree.topLevelItemCount()):
            top = target_tree.topLevelItem(i)
            if top is None:
                continue
            if dict(top.data(0, Qt.ItemDataRole.UserRole) or {}) == meta:
                target_tree.setCurrentItem(top)
                return
            for j in range(top.childCount()):
                child = top.child(j)
                if child is not None and dict(child.data(0, Qt.ItemDataRole.UserRole) or {}) == meta:
                    target_tree.setCurrentItem(child)
                    return
        self._schema_props.clear_target()
        self._update_schema_buttons()

    def _schema_display_name(self, item: dict[str, Any]) -> str:
        return _localized_text(item.get("title")) or str(item.get("name") or "")

    def _clone_tabular_parts(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for tp in self._model.tabular_parts:
            if not isinstance(tp, dict):
                continue
            row = dict(tp)
            row["columns"] = [
                dict(col) for col in (tp.get("columns") or []) if isinstance(col, dict)
            ]
            out.append(row)
        return out

    def _on_schema_field_changed(self, key: str, value: object) -> None:
        meta = dict(self._schema_selection or {})
        if not meta:
            return

        kind = str(meta.get("kind") or "")
        pending_patch: dict[str, Any] = {}
        current_item = None
        if kind == "requisite":
            items = [dict(item) for item in self._model.requisites if isinstance(item, dict)]
            index = int(meta.get("index") or 0)
            if not (0 <= index < len(items)):
                return
            self._apply_schema_item_change(items[index], key, value)
            self._payload_raw["requisites"] = items
            pending_patch["requisites"] = items
            current_item = self.tree_requisites.currentItem()
        elif kind == "tabular_part":
            parts = self._clone_tabular_parts()
            index = int(meta.get("index") or 0)
            if not (0 <= index < len(parts)):
                return
            self._apply_schema_item_change(parts[index], key, value)
            self._payload_raw["tabular_parts"] = parts
            pending_patch["tabular_parts"] = parts
            current_item = self.tree_tabular_parts.currentItem()
        elif kind == "column":
            parts = self._clone_tabular_parts()
            tp_index = int(meta.get("tp_index") or 0)
            col_index = int(meta.get("col_index") or 0)
            if not (0 <= tp_index < len(parts)):
                return
            cols = parts[tp_index].get("columns") if isinstance(parts[tp_index].get("columns"), list) else []
            if not (0 <= col_index < len(cols)):
                return
            self._apply_schema_item_change(cols[col_index], key, value)
            self._payload_raw["tabular_parts"] = parts
            pending_patch["tabular_parts"] = parts
            current_item = self.tree_tabular_parts.currentItem()
        else:
            return

        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch(pending_patch)

        if current_item is not None and key in {"name", "title"}:
            if kind == "requisite":
                item = self._model.requisites[int(meta.get("index") or 0)]
            elif kind == "tabular_part":
                item = self._model.tabular_parts[int(meta.get("index") or 0)]
            else:
                tp_index = int(meta.get("tp_index") or 0)
                col_index = int(meta.get("col_index") or 0)
                item = self._model.tabular_parts[tp_index]["columns"][col_index]
            current_item.setText(0, self._schema_display_name(item))

    def _apply_schema_item_change(self, item: dict[str, Any], key: str, value: object) -> None:
        if key == "title":
            if isinstance(value, dict):
                localized = {
                    lang: str(text or "").strip()
                    for lang, text in value.items()
                    if str(text or "").strip()
                }
                if localized:
                    item["title"] = localized
                else:
                    item.pop("title", None)
                return
            text = str(value or "").strip()
            if text:
                item["title"] = {"uk": text}
            else:
                item.pop("title", None)
            return
        if key in {"required", "read_only"}:
            item[key] = bool(value)
            return
        if key == "type":
            text = str(value or "").strip()
            if text:
                item["type"] = text
            else:
                item.pop("type", None)
            if text not in {"ref", "enum_ref", "any_ref"}:
                item.pop("ref_name", None)
                item.pop("ref_targets", None)
                item.pop("compound_type", None)
            if text != "string":
                item.pop("string_qualifiers", None)
            if text != "number":
                item.pop("number_qualifiers", None)
            return
        if key == "compound_type":
            enabled = bool(value)
            if enabled:
                item["compound_type"] = True
                if isinstance(item.get("ref_targets"), list):
                    targets = [str(v or "").strip() for v in item.get("ref_targets") or [] if str(v or "").strip()]
                else:
                    targets = []
                if not targets:
                    single = str(item.get("ref_name") or "").strip()
                    if single:
                        targets = [single]
                if targets:
                    item["ref_targets"] = targets
                    item["ref_name"] = targets[0]
                return
            item.pop("compound_type", None)
            targets = item.get("ref_targets") if isinstance(item.get("ref_targets"), list) else []
            first = str(targets[0] or "").strip() if targets else str(item.get("ref_name") or "").strip()
            item.pop("ref_targets", None)
            if first:
                item["ref_name"] = first
            else:
                item.pop("ref_name", None)
            return
        if key == "ref_targets":
            values = value if isinstance(value, list) else []
            targets: list[str] = []
            seen: set[str] = set()
            for item_value in values:
                text = str(item_value or "").strip()
                if not text or text.casefold() in seen:
                    continue
                targets.append(text)
                seen.add(text.casefold())
            if targets:
                item["ref_targets"] = targets
                item["ref_name"] = targets[0]
                if len(targets) > 1:
                    item["compound_type"] = True
                else:
                    item.pop("compound_type", None)
            else:
                item.pop("ref_targets", None)
                item.pop("ref_name", None)
                item.pop("compound_type", None)
            return
        if key == "string_length":
            length = max(0, _as_int(value, 0))
            if length > 0:
                sq = dict(item.get("string_qualifiers") or {})
                sq["length"] = length
                item["string_qualifiers"] = sq
            else:
                item.pop("string_qualifiers", None)
            return
        if key in {"number_digits", "number_fraction_digits"}:
            nq = dict(item.get("number_qualifiers") or {})
            if key == "number_digits":
                digits = max(0, _as_int(value, 0))
                if digits > 0:
                    nq["digits"] = digits
                else:
                    nq.pop("digits", None)
            else:
                fraction = max(0, _as_int(value, 0))
                nq["fraction_digits"] = fraction
            if nq.get("digits") or nq.get("fraction_digits"):
                item["number_qualifiers"] = nq
            else:
                item.pop("number_qualifiers", None)
            return
        text = str(value or "").strip()
        if key == "fill_checking":
            if text:
                item[key] = text
            else:
                item.pop(key, None)
            return
        if key == "name":
            item[key] = text
            return
        if text:
            item[key] = text
        else:
            item.pop(key, None)

    def _collect_reference_targets(self) -> list[tuple[str, str]]:
        if self._vm is None:
            return []
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        try:
            for obj in self._vm.list_objects() or []:
                obj_type = str(getattr(obj, "type", "") or "").strip().lower()
                prefix = _SCHEMA_REF_OBJECT_TYPES.get(obj_type)
                if not prefix:
                    continue
                if str(getattr(obj, "kind", "") or "").strip().lower() != "object":
                    continue
                name = str(getattr(obj, "name", "") or "").strip()
                if not name:
                    continue
                ref_value = f"{prefix}.{name}"
                if ref_value.casefold() in seen:
                    continue
                title = str(getattr(obj, "title", "") or "").strip()
                label = title or name
                if title and title != name:
                    label = f"{title} ({name})"
                out.append((label, ref_value))
                seen.add(ref_value.casefold())
        except Exception:
            return []
        out.sort(key=lambda item: item[0].casefold())
        return out
