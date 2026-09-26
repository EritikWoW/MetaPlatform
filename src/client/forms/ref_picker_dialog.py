"""Reference picker dialog — select a record from a catalog/document list."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QSortFilterProxyModel
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QTableView,
    QVBoxLayout,
)

from src.ui_qt.i18n import t


class RefPickerDialog(QDialog):
    """Modal dialog for picking a single record from a list."""

    def __init__(
        self,
        *,
        title: str | None = None,
        rows: list[dict],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or t("dlg_select_title"))
        self.setMinimumSize(500, 380)
        self.resize(600, 440)
        self._selected: Optional[dict] = None
        self._build_ui(rows)

    def _build_ui(self, rows: list[dict]) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(8)
        vl.setContentsMargins(12, 12, 12, 12)

        search = QLineEdit()
        search.setPlaceholderText(t("client_search_placeholder"))
        search.setClearButtonEnabled(True)
        vl.addWidget(search)

        # Determine columns from first non-empty row
        _SKIP = {"_guid", "_deleted", "_predefined", "_is_folder", "_posted"}
        col_keys: list[str] = []
        if rows:
            for k in rows[0]:
                if k not in _SKIP and not k.startswith("__"):
                    col_keys.append(k)
        if not col_keys:
            col_keys = ["_guid"]

        self._model = QStandardItemModel(0, len(col_keys))
        self._model.setHorizontalHeaderLabels(col_keys)

        for row in rows:
            items = []
            for ci, key in enumerate(col_keys):
                val = row.get(key)
                item = QStandardItem("" if val is None else str(val))
                item.setEditable(False)
                if ci == 0:
                    item.setData(row, Qt.ItemDataRole.UserRole)
                items.append(item)
            self._model.appendRow(items)

        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)
        search.textChanged.connect(self._proxy.setFilterWildcard)

        tv = QTableView()
        tv.setModel(self._proxy)
        tv.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        tv.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        tv.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        tv.verticalHeader().setVisible(False)
        tv.horizontalHeader().setStretchLastSection(True)
        tv.setSortingEnabled(True)
        tv.doubleClicked.connect(self._accept_selection)
        self._tv = tv
        vl.addWidget(tv, 1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._accept_selection)
        btns.rejected.connect(self.reject)
        vl.addWidget(btns)

    def _accept_selection(self, *_) -> None:
        idx = self._tv.currentIndex()
        if not idx.isValid():
            self.reject()
            return
        src = self._proxy.mapToSource(idx)
        item = self._model.item(src.row(), 0)
        if item:
            self._selected = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    @property
    def selected_row(self) -> Optional[dict]:
        return self._selected

    def selected_value(self, *field_candidates: str) -> str:
        """Return first non-empty value from selected row's field candidates."""
        if not self._selected:
            return ""
        for f in field_candidates:
            v = str(self._selected.get(f) or "").strip()
            if v:
                return v
        return ""

    @property
    def selected_guid(self) -> str:
        return self.selected_value("_guid")

    @property
    def selected_title(self) -> str:
        return self.selected_value(
            "_description", "description", "_name", "name", "title", "_title", "_guid"
        )
