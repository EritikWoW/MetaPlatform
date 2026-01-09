from __future__ import annotations

from typing import List, Optional, Any

from PySide6.QtCore import QAbstractTableModel, QAbstractListModel, QModelIndex, Qt

from src.platform.db_catalog import DbEntry


class DbTableModel(QAbstractTableModel):
    def __init__(self, rows: Optional[List[DbEntry]] = None, statuses: Optional[List[str]] = None) -> None:
        super().__init__()
        self._rows: List[DbEntry] = rows or []
        self._statuses: List[str] = statuses or []
        self._headers = ["База", "Путь", "Статус"]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return 3

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None

        r = index.row()
        c = index.column()
        if r < 0 or r >= len(self._rows):
            return None

        entry = self._rows[r]

        if role == Qt.DisplayRole:
            if c == 0:
                return entry.name
            if c == 1:
                return entry.path
            if c == 2:
                return self._statuses[r] if 0 <= r < len(self._statuses) else ""
            return ""

        if role == Qt.ToolTipRole:
            status = self._statuses[r] if 0 <= r < len(self._statuses) else ""
            return f"{entry.name}\n{entry.path}\n{status}"

        if role == Qt.TextAlignmentRole:
            if c == 2:
                return int(Qt.AlignVCenter | Qt.AlignLeft)
            return int(Qt.AlignVCenter | Qt.AlignLeft)

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None

    def set_headers(self, headers: List[str]) -> None:
        if len(headers) != 3:
            return
        self._headers = headers
        self.headerDataChanged.emit(Qt.Horizontal, 0, 2)

    def set_data(self, rows: List[DbEntry], statuses: List[str]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._statuses = list(statuses)
        self.endResetModel()


class DbListModel(QAbstractListModel):
    """
    Один элемент = одна база.
    DisplayRole: одна строка: "name    path    status"
    """

    RoleDb = Qt.UserRole + 1
    RoleStatus = Qt.UserRole + 2

    def __init__(self, rows: Optional[List[DbEntry]] = None, statuses: Optional[List[str]] = None) -> None:
        super().__init__()
        self._rows: List[DbEntry] = rows or []
        self._statuses: List[str] = statuses or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None

        r = index.row()
        if r < 0 or r >= len(self._rows):
            return None

        entry = self._rows[r]
        status = self._statuses[r] if 0 <= r < len(self._statuses) else ""

        if role == Qt.DisplayRole:
            return f"{entry.name}    {entry.path}    {status}"

        if role == Qt.ToolTipRole:
            return f"{entry.name}\n{entry.path}\n{status}"

        if role == self.RoleDb:
            return entry

        if role == self.RoleStatus:
            return status

        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignVCenter | Qt.AlignLeft)

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def set_data(self, rows: List[DbEntry], statuses: List[str]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._statuses = list(statuses)
        self.endResetModel()

    def entry_at(self, row: int) -> DbEntry | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None
