from __future__ import annotations

from typing import Callable, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t


class ReportsView(QWidget):
    """Dynamic list of reports from the configuration manifest."""

    def __init__(
        self,
        *,
        db=None,
        manifest_rows: list | None = None,
        on_open: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.title = t("client_nav_reports")
        self._db = db
        self._manifest_rows = manifest_rows or []
        self._on_open = on_open

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        h = QLabel(t("client_nav_reports"), self)
        h.setStyleSheet("font-size: 13pt; font-weight: 700;")
        root.addWidget(h)

        self._list = QListWidget(self)
        self._list.setAlternatingRowColors(True)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.itemDoubleClicked.connect(self._open_selected)
        root.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        self._btn_open = QPushButton(t("report_btn_run"), self)
        self._btn_open.setEnabled(False)
        self._btn_open.clicked.connect(self._open_selected)
        btn_row.addWidget(self._btn_open)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self._list.itemSelectionChanged.connect(
            lambda: self._btn_open.setEnabled(bool(self._list.selectedItems()))
        )

        self._populate()

    def _populate(self) -> None:
        self._list.clear()
        rows = list(self._manifest_rows or [])
        if not rows and self._db is not None:
            try:
                gw = getattr(self._db, "_gw", None)
                if gw is not None and hasattr(gw, "manifest_nav"):
                    rows = [r for r in gw.manifest_nav() if isinstance(r, dict)]
            except Exception:
                rows = []
        reports = [
            r for r in rows
            if str(r.get("type") or "").lower() == "report"
            and str(r.get("kind") or "").lower() == "object"
            and not (isinstance(r.get("payload"), dict) and r["payload"].get("system"))
        ]
        if not reports:
            empty = QListWidgetItem(t("client_view_not_implemented"))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(empty)
            return

        for r in sorted(reports, key=lambda x: str(x.get("title") or x.get("name") or "")):
            title = str(r.get("title") or r.get("name") or r.get("guid") or "")
            it = QListWidgetItem(title)
            it.setData(Qt.ItemDataRole.UserRole, str(r.get("guid") or ""))
            self._list.addItem(it)

    def reload(self, *, manifest_rows: list | None = None) -> None:
        if manifest_rows is not None:
            self._manifest_rows = manifest_rows
        self._populate()

    def _open_selected(self, *_) -> None:
        items = self._list.selectedItems()
        if not items:
            return
        guid = str(items[0].data(Qt.ItemDataRole.UserRole) or "")
        if guid and self._on_open:
            self._on_open(guid)
