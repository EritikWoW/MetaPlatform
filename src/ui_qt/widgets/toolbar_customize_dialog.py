from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QDialogButtonBox,
    QPushButton,
)

from src.ui_qt.i18n import t


@dataclass(frozen=True)
class ToolbarItem:
    id: str
    title: str
    checked: bool


class ToolbarCustomizeDialog(QDialog):
    """A simple toolbar customization dialog (1C-like)."""

    def __init__(
        self,
        parent=None,
        *,
        items_provider: Callable[[], List[ToolbarItem]],
        set_checked: Callable[[str, bool], None],
        reset_fn: Callable[[], None],
    ):
        super().__init__(parent)
        self.setWindowTitle(t("dlg_toolbar_customize_title"))
        self.setModal(True)
        self.resize(420, 460)

        self._items_provider = items_provider
        self._set_checked = set_checked
        self._reset_fn = reset_fn

        root = QVBoxLayout(self)

        self.list = QListWidget(self)
        root.addWidget(self.list, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        btn_reset = QPushButton(t("btn_reset"), self)
        bb.addButton(btn_reset, QDialogButtonBox.ButtonRole.ResetRole)
        root.addWidget(bb)

        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        btn_reset.clicked.connect(self._reset)

        self._rebuild()
        self.list.itemChanged.connect(self._on_changed)

    def _rebuild(self) -> None:
        self.list.blockSignals(True)
        try:
            self.list.clear()
            for it in self._items_provider() or []:
                w = QListWidgetItem(it.title)
                w.setData(Qt.ItemDataRole.UserRole, it.id)
                w.setFlags(w.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                w.setCheckState(Qt.CheckState.Checked if it.checked else Qt.CheckState.Unchecked)
                self.list.addItem(w)
        finally:
            self.list.blockSignals(False)

    def _on_changed(self, item: QListWidgetItem) -> None:
        tid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        checked = item.checkState() == Qt.CheckState.Checked
        try:
            self._set_checked(tid, checked)
        except Exception:
            pass

    def _reset(self) -> None:
        try:
            self._reset_fn()
        except Exception:
            pass
        self._rebuild()
