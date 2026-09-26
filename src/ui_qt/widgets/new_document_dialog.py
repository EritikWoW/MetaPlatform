from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QDialogButtonBox,
)

from src.ui_qt.i18n import t


@dataclass(frozen=True)
class NewDocType:
    id: str
    title_key: str
    icon: str | None = None


_DEFAULT_TYPES: list[NewDocType] = [
    NewDocType("text", "newdoc_text", "file-text"),
    NewDocType("picture", "newdoc_picture", "file-image"),
    NewDocType("table", "newdoc_table", "table"),
    NewDocType("ext_proc", "newdoc_ext_proc", "package"),
    NewDocType("ext_report", "newdoc_ext_report", "file-bar-chart"),
    NewDocType("html", "newdoc_html", "file-code"),
    NewDocType("graph", "newdoc_graph", "workflow"),
    NewDocType("geo", "newdoc_geo", "map"),
    NewDocType("templates", "newdoc_templates", "braces"),
]


class NewDocumentDialog(QDialog):
    """1C-like "Select document type" dialog.

    MVP: only returns a selected doc type id.
    """

    def __init__(self, parent=None, *, types: Optional[list[NewDocType]] = None):
        super().__init__(parent)
        self.setWindowTitle(t("dlg_newdoc_title"))
        self.setModal(True)
        self.resize(520, 360)

        self.selected_type_id: str = ""

        root = QVBoxLayout(self)

        self.list = QListWidget(self)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.setUniformItemSizes(True)

        for tp in (types or _DEFAULT_TYPES):
            it = QListWidgetItem(t(tp.title_key))
            it.setData(Qt.ItemDataRole.UserRole, tp.id)
            # icons are injected by the caller if desired
            self.list.addItem(it)

        if self.list.count() > 0:
            self.list.setCurrentRow(0)

        self.list.itemDoubleClicked.connect(lambda _it: self.accept())
        root.addWidget(self.list, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def accept(self) -> None:
        it = self.list.currentItem()
        if it is not None:
            self.selected_type_id = str(it.data(Qt.ItemDataRole.UserRole) or "")
        super().accept()
