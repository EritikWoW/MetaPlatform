from __future__ import annotations

from typing import Any, Dict, List, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t


def build_access_restrictions_projection(vm: Any | None) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    restrictions: List[Dict[str, str]] = []
    templates: List[Dict[str, str]] = []
    if vm is None:
        return restrictions, templates

    try:
        objects = vm.list_objects() or []
    except Exception:
        return restrictions, templates

    for obj in objects:
        if str(getattr(obj, "kind", "") or "") != "object":
            continue
        if str(getattr(obj, "type", "") or "").strip().lower() != "role":
            continue

        role_guid = str(getattr(obj, "guid", "") or "").strip()
        role_name = str(getattr(obj, "title", "") or getattr(obj, "name", "") or role_guid).strip()
        role_code = str(getattr(obj, "name", "") or "").strip()
        try:
            meta = vm.get_meta_by_guid(role_guid) or {}
        except Exception:
            meta = {}
        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}

        for entry in payload.get("rights") or []:
            if not isinstance(entry, dict):
                continue
            object_ref = str(entry.get("object") or "").strip()
            for restriction in entry.get("restrictions") or []:
                if not isinstance(restriction, dict):
                    continue
                right_name = str(restriction.get("right") or "").strip()
                condition = str(restriction.get("condition") or "").strip()
                field_name = str(restriction.get("field") or "").strip()
                if not right_name or not condition:
                    continue
                restrictions.append(
                    {
                        "role_guid": role_guid,
                        "role_name": role_name,
                        "role_code": role_code,
                        "object_ref": object_ref,
                        "right_name": right_name,
                        "field_name": field_name,
                        "condition": condition,
                    }
                )

        for item in payload.get("restriction_templates") or []:
            if not isinstance(item, dict):
                continue
            template_name = str(item.get("name") or "").strip()
            condition = str(item.get("condition") or "").strip()
            if not template_name and not condition:
                continue
            templates.append(
                {
                    "role_guid": role_guid,
                    "role_name": role_name,
                    "role_code": role_code,
                    "template_name": template_name,
                    "condition": condition,
                }
            )

    restrictions.sort(
        key=lambda item: (
            str(item.get("role_name") or "").casefold(),
            str(item.get("object_ref") or "").casefold(),
            str(item.get("field_name") or item.get("right_name") or "").casefold(),
            str(item.get("condition") or "").casefold(),
        )
    )
    templates.sort(
        key=lambda item: (
            str(item.get("role_name") or "").casefold(),
            str(item.get("template_name") or "").casefold(),
            str(item.get("condition") or "").casefold(),
        )
    )
    return restrictions, templates


class AccessRestrictionsProjectionWidget(QWidget):
    openRoleRequested = Signal(str, str)

    def __init__(self, *, vm: Any | None = None, title: str = "") -> None:
        super().__init__()
        self._vm = vm
        self._restrictions_rows: List[Dict[str, str]] = []
        self._template_rows: List[Dict[str, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self._hint = QLabel(t("access_restrictions.hint"))
        self._hint.setWordWrap(True)
        self._hint.setObjectName("metaHint")
        root.addWidget(self._hint)

        bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(t("access_restrictions.search_placeholder"))
        self._search.textChanged.connect(self._apply_filter)
        self._summary = QLabel("")
        self._summary.setObjectName("metaHint")
        self._btn_refresh = QPushButton(t("act_refresh"))
        self._btn_refresh.clicked.connect(self.refresh_data)
        self._btn_open_role = QPushButton(t("access_restrictions.open_role"))
        self._btn_open_role.clicked.connect(self._open_selected_role)
        bar.addWidget(self._search, 1)
        bar.addWidget(self._summary, 0)
        bar.addWidget(self._btn_refresh, 0)
        bar.addWidget(self._btn_open_role, 0)
        root.addLayout(bar)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, 1)

        self._restrictions_table = self._build_table(
            [
                t("access_restrictions.col_role"),
                t("access_restrictions.col_object"),
                t("access_restrictions.col_scope"),
                t("role.restriction_condition"),
            ]
        )
        self._restrictions_table.itemSelectionChanged.connect(self._on_selection_changed)
        self._restrictions_table.itemDoubleClicked.connect(lambda *_args: self._open_selected_role())
        self._tabs.addTab(self._restrictions_table, t("access_restrictions.tab_restrictions"))

        self._templates_table = self._build_table(
            [
                t("access_restrictions.col_role"),
                t("access_restrictions.col_template"),
                t("role.col_template_text"),
            ]
        )
        self._templates_table.itemSelectionChanged.connect(self._on_selection_changed)
        self._templates_table.itemDoubleClicked.connect(lambda *_args: self._open_selected_role())
        self._tabs.addTab(self._templates_table, t("access_restrictions.tab_templates"))

        self._details_label = QLabel(t("access_restrictions.details"))
        self._details_label.setObjectName("metaHint")
        root.addWidget(self._details_label)

        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        self._details.setMinimumHeight(120)
        root.addWidget(self._details, 0)

        self._tabs.currentChanged.connect(lambda _idx: self._on_selection_changed())

        self.refresh_data()
        if title:
            self.setWindowTitle(title)

    def _build_table(self, headers: List[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def refresh_data(self) -> None:
        self._restrictions_rows, self._template_rows = build_access_restrictions_projection(self._vm)
        self._populate_restrictions_table()
        self._populate_templates_table()
        self._apply_filter()
        self._on_selection_changed()

    def _populate_restrictions_table(self) -> None:
        self._restrictions_table.setRowCount(len(self._restrictions_rows))
        for row, item in enumerate(self._restrictions_rows):
            scope = str(item.get("field_name") or item.get("right_name") or "")
            values = [
                str(item.get("role_name") or ""),
                str(item.get("object_ref") or ""),
                scope,
                str(item.get("condition") or ""),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, dict(item))
                if col == 2 and str(item.get("field_name") or "").strip() and str(item.get("right_name") or "").strip():
                    cell.setToolTip(str(item.get("right_name") or ""))
                self._restrictions_table.setItem(row, col, cell)
        self._restrictions_table.resizeColumnsToContents()

    def _populate_templates_table(self) -> None:
        self._templates_table.setRowCount(len(self._template_rows))
        for row, item in enumerate(self._template_rows):
            values = [
                str(item.get("role_name") or ""),
                str(item.get("template_name") or ""),
                str(item.get("condition") or ""),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, dict(item))
                self._templates_table.setItem(row, col, cell)
        self._templates_table.resizeColumnsToContents()

    def _active_table(self) -> QTableWidget:
        return self._restrictions_table if self._tabs.currentWidget() is self._restrictions_table else self._templates_table

    def _row_payload(self, table: QTableWidget, row: int) -> Dict[str, str]:
        item = table.item(row, 0)
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return dict(data) if isinstance(data, dict) else {}

    def _apply_filter(self) -> None:
        needle = str(self._search.text() or "").strip().casefold()
        for table in (self._restrictions_table, self._templates_table):
            for row in range(table.rowCount()):
                hay = " ".join(
                    str((table.item(row, col).text() if table.item(row, col) is not None else "") or "")
                    for col in range(table.columnCount())
                ).casefold()
                table.setRowHidden(row, bool(needle) and needle not in hay)
        self._summary.setText(
            t(
                "access_restrictions.summary",
                restrictions=self._visible_rows(self._restrictions_table),
                templates=self._visible_rows(self._templates_table),
            )
        )

    @staticmethod
    def _visible_rows(table: QTableWidget) -> int:
        return sum(0 if table.isRowHidden(row) else 1 for row in range(table.rowCount()))

    def _on_selection_changed(self) -> None:
        payload = self._selected_payload()
        condition = str(payload.get("condition") or "").strip()
        self._details.setPlainText(condition)
        self._btn_open_role.setEnabled(bool(str(payload.get("role_guid") or "").strip()))

    def _selected_payload(self) -> Dict[str, str]:
        table = self._active_table()
        row = table.currentRow()
        if row < 0:
            return {}
        return self._row_payload(table, row)

    def _open_selected_role(self) -> None:
        payload = self._selected_payload()
        role_guid = str(payload.get("role_guid") or "").strip()
        role_name = str(payload.get("role_name") or payload.get("role_code") or role_guid).strip()
        if not role_guid:
            return
        self.openRoleRequested.emit(role_guid, role_name)
