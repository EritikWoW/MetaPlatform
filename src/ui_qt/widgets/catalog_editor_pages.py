from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QPlainTextEdit,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t
from src.ui_qt.viewmodels.configurator_vm_state import _subsystem_tree_parents

from .catalog_editor_payload import _parse_subsystems
from .schema_editors import AttributesEditorWidget, TabularPartsEditorWidget


class _SubsystemsPageMixin:
    """GUID-based membership selector shared by catalog and document editors."""

    def _build_subsystems_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        hint = QLabel(t("obj.subsystems_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        self.lst_subsystems = QTreeWidget()
        self.lst_subsystems.setObjectName("metaSubsystemsList")
        self.lst_subsystems.setHeaderHidden(True)
        self.lst_subsystems.setIndentation(18)
        self.lst_subsystems.setUniformRowHeights(True)
        layout.addWidget(self.lst_subsystems, 1)

        self._subsystems_empty_label = QLabel(t("obj.subsystems_empty"))
        self._subsystems_empty_label.setWordWrap(True)
        self._subsystems_empty_label.setObjectName("metaHint")
        layout.addWidget(self._subsystems_empty_label)

        self._rebuild_subsystems_list()
        self.lst_subsystems.itemChanged.connect(self._on_subsystem_item_changed)
        setattr(widget, "_on_section_shown", self._rebuild_subsystems_list)
        return widget

    def _rebuild_subsystems_list(self) -> None:
        selected = set(_parse_subsystems(
            self._shell.pending_patch().get("subsystems", self._model.subsystems)
        ))
        entries: dict[str, dict] = {}
        for subsystem in self._available_subsystems or []:
            if not isinstance(subsystem, dict):
                continue
            guid = str(subsystem.get("guid") or "").strip()
            if guid:
                entries[guid] = subsystem
        # Keep unresolved selections visible and removable, never silently drop
        # them when a partial snapshot does not contain the referenced object.
        for guid in selected:
            entries.setdefault(guid, {"guid": guid, "name": guid})
        parents = _subsystem_tree_parents({
            guid: str(entry.get("parent_guid") or "").strip()
            for guid, entry in entries.items()
        })
        ordered = sorted(entries, key=lambda guid: (
            str(entries[guid].get("name") or entries[guid].get("title") or guid).casefold(),
            guid,
        ))

        was_loading = getattr(self, "_loading_subsystems", False)
        was_blocked = self.lst_subsystems.blockSignals(True)
        self._loading_subsystems = True
        try:
            self.lst_subsystems.clear()
            items: dict[str, QTreeWidgetItem] = {}
            for guid in ordered:
                entry = entries[guid]
                item = QTreeWidgetItem([str(entry.get("name") or entry.get("title") or guid)])
                item.setData(0, Qt.ItemDataRole.UserRole, guid)
                item.setToolTip(0, str(entry.get("path") or entry.get("title") or guid))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if guid in selected else Qt.CheckState.Unchecked)
                items[guid] = item
            for guid in ordered:
                parent = parents[guid]
                if parent:
                    items[parent].addChild(items[guid])
                else:
                    self.lst_subsystems.addTopLevelItem(items[guid])
            for item in items.values():
                if item.childCount():
                    item.setExpanded(True)
            self.lst_subsystems.setEnabled(bool(items))
            self._subsystems_empty_label.setVisible(not items)
        finally:
            self._loading_subsystems = was_loading
            self.lst_subsystems.blockSignals(was_blocked)

    def _iter_subsystem_items(self):
        stack = [
            self.lst_subsystems.topLevelItem(index)
            for index in reversed(range(self.lst_subsystems.topLevelItemCount()))
        ]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.child(index) for index in reversed(range(item.childCount())))

    def _on_subsystem_item_changed(self, _item, _column: int = 0) -> None:
        if getattr(self, "_loading_subsystems", False):
            return
        selected = [
            str(item.data(0, Qt.ItemDataRole.UserRole))
            for item in self._iter_subsystem_items()
            if item.checkState(0) == Qt.CheckState.Checked
        ]
        self._payload_raw["subsystems"] = selected
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({"subsystems": selected})


class CatalogEditorPagesMixin(_SubsystemsPageMixin):
    def _build_attributes_page(self) -> QWidget:
        widget = AttributesEditorWidget(initial=self._payload_raw.get("attributes"))
        widget.patchChanged.connect(self._shell.set_pending_patch)
        return widget

    def _build_tabular_parts_page(self) -> QWidget:
        widget = TabularPartsEditorWidget(initial=self._payload_raw.get("tabular_parts"))
        widget.patchChanged.connect(self._shell.set_pending_patch)
        return widget

    def _build_main_page(self) -> QWidget:
        widget = QWidget()
        page = QGridLayout(widget)
        page.setContentsMargins(10, 10, 10, 10)
        page.setHorizontalSpacing(12)
        page.setVerticalSpacing(10)
        page.setColumnStretch(1, 1)

        self.ed_name = QLineEdit()
        self.ed_synonym = QLineEdit()
        self.ed_comment = QLineEdit()

        for editor in (self.ed_name, self.ed_synonym, self.ed_comment):
            editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lbl_name = QLabel(t("catalog_field_name"))
        lbl_synonym = QLabel(t("catalog_field_synonym"))
        lbl_comment = QLabel(t("catalog_field_comment"))
        lbl_hint = QLabel(t("catalog_field_hint"))

        for label in (lbl_name, lbl_synonym, lbl_comment):
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        self.ed_hint = QPlainTextEdit()
        self.ed_hint.setPlaceholderText(t("catalog_hint_placeholder"))
        self.ed_hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.ed_hint.setMinimumHeight(160)

        row = 0
        page.addWidget(lbl_name, row, 0)
        page.addWidget(self.ed_name, row, 1)
        row += 1

        page.addWidget(lbl_synonym, row, 0)
        page.addWidget(self.ed_synonym, row, 1)
        row += 1

        page.addWidget(lbl_comment, row, 0)
        page.addWidget(self.ed_comment, row, 1)
        row += 1

        page.addWidget(lbl_hint, row, 0)
        page.addWidget(self.ed_hint, row, 1)
        page.setRowStretch(row, 1)

        for editor, key in (
            (self.ed_name, "name"),
            (self.ed_synonym, "synonym"),
            (self.ed_comment, "comment"),
        ):
            editor.textEdited.connect(lambda _txt, k=key, e=editor: self._on_text_changed(k, e.text()))

        self.ed_hint.textChanged.connect(
            lambda: self._on_text_changed("hint", self.ed_hint.toPlainText())
        )
        return widget

    def _build_data_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        grp_code = QGroupBox(t("catalog_data_code"))
        form_code = QFormLayout(grp_code)
        form_code.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form_code.setHorizontalSpacing(12)

        self.sp_code_len = QSpinBox()
        self.sp_code_len.setRange(1, 64)
        self.cb_code_type = QComboBox()
        self.cb_code_type.addItem(t("catalog_code_type_string"), "string")
        self.cb_code_type.addItem(t("catalog_code_type_number"), "number")

        form_code.addRow(t("catalog_data_code_length"), self.sp_code_len)
        form_code.addRow(t("catalog_data_code_type"), self.cb_code_type)

        grp_name = QGroupBox(t("catalog_data_name"))
        form_name = QFormLayout(grp_name)
        form_name.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form_name.setHorizontalSpacing(12)
        self.sp_name_len = QSpinBox()
        self.sp_name_len.setRange(1, 255)
        form_name.addRow(t("catalog_data_name_length"), self.sp_name_len)

        layout.addWidget(grp_code)
        layout.addWidget(grp_name)

        hint = QLabel(t("catalog_data_mvp_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)
        layout.addStretch(1)

        self.sp_code_len.valueChanged.connect(
            lambda value: self._on_value_changed("code_length", int(value))
        )
        self.sp_name_len.valueChanged.connect(
            lambda value: self._on_value_changed("name_length", int(value))
        )
        self.cb_code_type.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "code_type",
                str(self.cb_code_type.currentData() or "string"),
            )
        )
        return widget


__all__ = ["CatalogEditorPagesMixin"]
