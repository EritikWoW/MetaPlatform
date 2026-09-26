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
    QPushButton,
    QMenu,
)

from PySide6.QtWidgets import QMdiArea

from src.ui_qt.i18n import t


class WindowsListDialog(QDialog):
    """1C-like "Windows" dialog for QMdiArea."""

    def __init__(self, parent=None, *, mdi: QMdiArea):
        super().__init__(parent)
        self.setWindowTitle(t("dlg_windows_title"))
        self.setModal(True)
        self.resize(520, 360)
        self._mdi = mdi

        root = QHBoxLayout(self)

        self.list = QListWidget(self)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        root.addWidget(self.list, 1)

        right = QVBoxLayout()

        self.btn_activate = QPushButton(t("btn_activate"), self)
        self.btn_save = QPushButton(t("btn_save"), self)
        self.btn_close_win = QPushButton(t("btn_close_window"), self)

        self.btn_arrange = QPushButton(t("btn_arrange"), self)
        self._arr_menu = QMenu(self)
        self._arr_menu.addAction(t("win_cascade"), lambda: self._mdi.cascadeSubWindows())
        self._arr_menu.addAction(t("win_tile"), lambda: self._mdi.tileSubWindows())
        self._arr_menu.addSeparator()
        self._arr_menu.addAction(t("win_close_all"), self._close_all)
        self.btn_arrange.setMenu(self._arr_menu)

        for b in (self.btn_activate, self.btn_save, self.btn_close_win, self.btn_arrange):
            b.setMinimumWidth(160)
            right.addWidget(b)

        right.addStretch(1)

        self.btn_close = QPushButton(t("btn_close"), self)
        right.addWidget(self.btn_close)

        root.addLayout(right)

        self.btn_close.clicked.connect(self.reject)
        self.btn_activate.clicked.connect(self._activate)
        self.btn_close_win.clicked.connect(self._close_selected)
        self.btn_save.clicked.connect(self._save_selected)

        self.list.itemDoubleClicked.connect(lambda _it: self._activate())

        self._rebuild()

    def _rebuild(self) -> None:
        self.list.clear()
        wins = self._mdi.subWindowList()
        active = self._mdi.activeSubWindow()
        active_title = active.windowTitle() if active else ""

        for sub in wins:
            it = QListWidgetItem(sub.windowTitle())
            it.setData(Qt.ItemDataRole.UserRole, sub)
            self.list.addItem(it)
            if active_title and sub.windowTitle() == active_title:
                self.list.setCurrentItem(it)

        if self.list.currentRow() < 0 and self.list.count() > 0:
            self.list.setCurrentRow(0)

    def _selected_sub(self):
        it = self.list.currentItem()
        if it is None:
            return None
        return it.data(Qt.ItemDataRole.UserRole)

    def _activate(self) -> None:
        sub = self._selected_sub()
        if sub is None:
            return
        try:
            self._mdi.setActiveSubWindow(sub)
            sub.showNormal()
        except Exception:
            pass

    def _close_selected(self) -> None:
        sub = self._selected_sub()
        if sub is None:
            return
        try:
            sub.close()
        except Exception:
            pass
        self._rebuild()

    def _save_selected(self) -> None:
        sub = self._selected_sub()
        if sub is None:
            return
        try:
            w = sub.widget()
            if w is not None and hasattr(w, "save") and callable(getattr(w, "save")):
                w.save()
        except Exception:
            pass

    def _close_all(self) -> None:
        try:
            self._mdi.closeAllSubWindows()
        except Exception:
            pass
        self._rebuild()
