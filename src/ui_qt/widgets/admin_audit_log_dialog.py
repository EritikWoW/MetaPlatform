from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.ui_qt.i18n import t


def _fmt_ts_ms(ts_ms: int | str | None) -> str:
    """Format epoch milliseconds into a human-readable local timestamp."""

    try:
        ms = int(ts_ms or 0)
    except Exception:
        return ""
    if ms <= 0:
        return ""
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class AuditLogDialog(QDialog):
    """Read-only audit log viewer (MVP)."""

    def __init__(self, parent=None, *, title: str, rows: List[Dict], user_map: Dict[str, str]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(1020, 520)

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                t("admin_col_ts"),
                t("admin_col_user"),
                t("admin_col_action"),
                t("admin_col_entity_type"),
                t("admin_col_entity_id"),
                t("admin_col_payload"),
                t("admin_col_event_id"),
            ]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        close_btn = QPushButton(t("act_close"))
        close_btn.clicked.connect(self.accept)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

        self.set_rows(rows, user_map)

    def set_rows(self, rows: List[Dict], user_map: Dict[str, str]) -> None:
        """Populate the table with audit rows."""

        import json

        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)

            ts = _fmt_ts_ms(r.get("ts"))
            uid = str(r.get("user_id") or "")
            user = user_map.get(uid) or uid
            action = str(r.get("action") or "")
            etype = str(r.get("entity_type") or "")
            eid = str(r.get("entity_id") or "")
            payload = r.get("payload")
            try:
                payload_s = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            except Exception:
                payload_s = str(payload)
            event_id = str(r.get("event_id") or "")

            self._set_cell(row, 0, ts)
            self._set_cell(row, 1, user)
            self._set_cell(row, 2, action)
            self._set_cell(row, 3, etype)
            self._set_cell(row, 4, eid)
            self._set_cell(row, 5, payload_s)
            self._set_cell(row, 6, event_id)

        self.table.resizeColumnsToContents()

    def _set_cell(self, row: int, col: int, text: str, *, align: Qt.AlignmentFlag.AlignmentFlag | None = None) -> None:
        it = QTableWidgetItem(text)
        if align is not None:
            it.setTextAlignment(int(align))
        self.table.setItem(row, col, it)
