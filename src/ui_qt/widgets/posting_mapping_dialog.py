"""Movement mapping editor. Accept returns a draft, never writes a module/DB."""
from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView, QLabel,
    QListWidget, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.configurator.domain.posting_mapping import compatible, generate_mapped_posting, code_field, validate_mapping_shape
from src.ui_qt.i18n import t
from .code_editor_widget import create_metascript_code_edit


class PostingMappingDialog(QDialog):
    def __init__(self, schema, *, plan=None, language="uk", parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("posting_map_title"))
        self.resize(1040, 720)
        self.schema, self.language = schema, language
        if plan is not None:
            validate_mapping_shape(plan)
        saved = {e["register"]: deepcopy(e) for e in (plan or {}).get("entries", [])}
        self.entries = [saved.get(ref, {"register": ref, "source": "", "direction": "", "fields": {}})
                        for ref in schema.registers]
        self._active = -1
        layout = QVBoxLayout(self)
        hint = QLabel(t("posting_map_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.registers = QListWidget()
        self.registers.setMinimumWidth(180)
        self.registers.addItems(list(schema.registers))
        splitter.addWidget(self.registers)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.source = QComboBox()
        self.source.addItem(t("posting_map_header"), "")
        for name in schema.tabular_parts:
            self.source.addItem(name, name)
        self.direction = QComboBox()
        self.direction.addItem(t("posting_map_choose"), "")
        self.direction.addItem(t("posting_map_receipt"), "receipt")
        self.direction.addItem(t("posting_map_expense"), "expense")
        form.addRow(t("posting_map_source"), self.source)
        form.addRow(t("posting_map_direction"), self.direction)
        right_layout.addLayout(form)
        self.fields = QTableWidget(0, 3)
        self.fields.setHorizontalHeaderLabels([t("posting_map_target"), t("posting_map_type"), t("posting_map_value")])
        self.fields.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.fields.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.fields.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.fields.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        right_layout.addWidget(self.fields, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 3)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.error)
        self.preview, self._highlighter = create_metascript_code_edit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 2)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("btn_cancel"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.registers.currentRowChanged.connect(self._select_register)
        self.source.currentIndexChanged.connect(self._source_changed)
        self.direction.currentIndexChanged.connect(self._direction_changed)
        self.registers.setCurrentRow(0)
        self._refresh_preview()

    def plan(self):
        return {"version": 1, "entries": deepcopy(self.entries)}

    def _select_register(self, index):
        self._active = index
        if index < 0:
            return
        entry = self.entries[index]
        for combo, value in ((self.source, entry.get("source", "")), (self.direction, entry.get("direction", ""))):
            blocked = combo.blockSignals(True)
            target = combo.findData(value)
            if target < 0:
                combo.addItem(t("posting_map_missing") + str(value), value)
                target = combo.count() - 1
            combo.setCurrentIndex(target)
            combo.blockSignals(blocked)
        self.direction.setEnabled(entry["register"].startswith("AccumulationRegister."))
        self._populate_fields()

    def _source_changed(self, _index):
        if self._active >= 0:
            self.entries[self._active]["source"] = self.source.currentData()
            # Keep stale bindings visible. They must be corrected explicitly.
            self._populate_fields()
            self._refresh_preview()

    def _direction_changed(self, _index):
        if self._active >= 0:
            self.entries[self._active]["direction"] = self.direction.currentData()
            self._refresh_preview()

    def _populate_fields(self):
        entry = self.entries[self._active]
        fields = self.schema.registers[entry["register"]]
        self.fields.setRowCount(0)
        choices = [("document", f) for f in self.schema.document]
        choices += [("row", f) for f in self.schema.tabular_parts.get(entry.get("source"), [])]
        for index, target in enumerate(fields):
            self.fields.insertRow(index)
            self.fields.setItem(index, 0, QTableWidgetItem(code_field(target, uk=self.language == "uk") + (" *" if target.required else "")))
            self.fields.setItem(index, 1, QTableWidgetItem(target.value_type))
            combo = QComboBox()
            combo.addItem(t("posting_map_choose"), None)
            for scope, field in choices:
                if compatible(field.value_type, target.value_type):
                    prefix = t("posting_map_document") if scope == "document" else entry["source"]
                    combo.addItem(f"{prefix}.{code_field(field, uk=self.language == 'uk')}", {"scope": scope, "field": field.name})
            value = entry.get("fields", {}).get(target.name)
            selected = next((i for i in range(combo.count()) if combo.itemData(i) == value), -1)
            if selected < 0:
                combo.addItem(t("posting_map_missing") + str(value), value)
                selected = combo.count() - 1
            combo.setCurrentIndex(selected)
            combo.currentIndexChanged.connect(lambda _i, c=combo, name=target.name: self._binding_changed(name, c.currentData()))
            self.fields.setCellWidget(index, 2, combo)

    def _binding_changed(self, name, value):
        fields = self.entries[self._active].setdefault("fields", {})
        if value is None:
            fields.pop(name, None)
        else:
            fields[name] = value
        self._refresh_preview()

    def _refresh_preview(self):
        try:
            code = generate_mapped_posting(self.plan(), self.schema, language=self.language)
        except ValueError as exc:
            self.error.setText(t("posting_map_incomplete") + str(exc))
            self.preview.clear()
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        else:
            self.error.setText(t("posting_map_ready"))
            self.preview.setPlainText(code)
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def accept(self):
        self._refresh_preview()
        if self.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled():
            super().accept()
