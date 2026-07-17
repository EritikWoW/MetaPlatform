from __future__ import annotations

from typing import List, Optional, Any

from PySide6.QtCore import QAbstractTableModel, QAbstractListModel, QModelIndex, Qt

from src.platform.db_catalog import DbEntry


class DbTableModel(QAbstractTableModel):
    def __init__(self, rows: Optional[List[DbEntry]] = None, statuses: Optional[List[str]] = None) -> None:
        super().__init__()
        self._rows: List[DbEntry] = rows or []
        self._statuses: List[str] = statuses or []
        self._headers = ["База", "Тип", "Подключение", "Статус"]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return 4

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        r = index.row()
        c = index.column()
        if r < 0 or r >= len(self._rows):
            return None
        entry = self._rows[r]
        status = self._statuses[r] if 0 <= r < len(self._statuses) else ""
        target = entry.path if entry.kind == "local" else entry.runtime_url

        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                return entry.name
            if c == 1:
                return entry.kind
            if c == 2:
                return target
            if c == 3:
                return status
            return ""

        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{entry.name}\n{entry.kind}\n{target}\n{status}"

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if c == 3:
                return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None

    def set_headers(self, headers: List[str]) -> None:
        if len(headers) != 4:
            return
        self._headers = headers
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 3)

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

    RoleDb = int(Qt.ItemDataRole.UserRole) + 1
    RoleStatusCode = int(Qt.ItemDataRole.UserRole) + 2
    RoleStatusTip = int(Qt.ItemDataRole.UserRole) + 3
    RoleTarget = int(Qt.ItemDataRole.UserRole) + 4

    def __init__(
        self,
        rows: Optional[List[DbEntry]] = None,
        status_codes: Optional[List[str]] = None,
        status_tips: Optional[List[str]] = None,
    ) -> None:
        super().__init__()
        self._rows: List[DbEntry] = rows or []
        self._status_codes: List[str] = status_codes or []
        self._status_tips: List[str] = status_tips or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        r = index.row()
        if r < 0 or r >= len(self._rows):
            return None

        entry = self._rows[r]
        code = self._status_codes[r] if 0 <= r < len(self._status_codes) else ""
        tip = self._status_tips[r] if 0 <= r < len(self._status_tips) else ""

        if role == Qt.ItemDataRole.DisplayRole:
            # Keep it as a single line (no table-like split). Detailed connection info is shown below the list.
            return f"{entry.name}    {entry.kind}"

        if role == Qt.ItemDataRole.ToolTipRole:
            # Tooltips are handled in the view for the status indicator only.
            return ""

        if role == self.RoleDb:
            return entry

        if role == self.RoleStatusCode:
            return code

        if role == self.RoleStatusTip:
            return tip

        if role == self.RoleTarget:
            return entry.path if entry.kind == "local" else entry.runtime_url

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def set_data(self, rows: List[DbEntry], status_codes: List[str], status_tips: List[str]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._status_codes = list(status_codes)
        self._status_tips = list(status_tips)
        self.endResetModel()

    def entry_at(self, row: int) -> DbEntry | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None
