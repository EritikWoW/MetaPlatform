from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QMessageBox,
)

from src.ui_qt.i18n import t


def _as_str(x: Any) -> str:
    return str(x or "").strip()


def _as_bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    s = str(x or "").strip().lower()
    return s in ("1", "true", "yes", "y", "да", "так")


def normalize_fields(value: Any) -> list[dict]:
    """Normalize fields list to a canonical list[dict].

    Each field dict has:
        name: str
        type: str
        required: bool
        comment: str
    """

    items = value if isinstance(value, list) else []
    out: list[dict] = []
    seen: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        name = _as_str(it.get("name"))
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "name": name,
                "type": _as_str(it.get("type")) or "string",
                "required": bool(_as_bool(it.get("required"))),
                "comment": _as_str(it.get("comment")),
            }
        )
    return out


def normalize_tabular_parts(value: Any) -> list[dict]:
    """Normalize tabular parts list to a canonical list[dict]."""

    items = value if isinstance(value, list) else []
    out: list[dict] = []
    seen: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        name = _as_str(it.get("name"))
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "name": name,
                "title": _as_str(it.get("title")) or name,
                "comment": _as_str(it.get("comment")),
                "columns": normalize_fields(it.get("columns")),
            }
        )
    return out


class FieldsTableWidget(QTableWidget):
    """Generic schema table for fields (attributes/columns)."""

    changed = Signal()

    COL_NAME = 0
    COL_TYPE = 1
    COL_REQUIRED = 2
    COL_COMMENT = 3

    def __init__(self, parent: QWidget | None = None):
        super().__init__(0, 4, parent)

        self.setObjectName("schemaFieldsTable")
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)

        self.setHorizontalHeaderLabels(
            [
                t("schema.col.name"),
                t("schema.col.type"),
                t("schema.col.required"),
                t("schema.col.comment"),
            ]
        )
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(self.COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(self.COL_REQUIRED, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(self.COL_COMMENT, QHeaderView.ResizeMode.Stretch)

        self.itemChanged.connect(lambda _it: self.changed.emit())

    def set_fields(self, fields: list[dict]) -> None:
        self.blockSignals(True)
        try:
            self.setRowCount(0)
            for f in normalize_fields(fields):
                r = self.rowCount()
                self.insertRow(r)
                self._set_cell(r, self.COL_NAME, f.get("name", ""))
                self._set_cell(r, self.COL_TYPE, f.get("type", "string"))
                self._set_cell(r, self.COL_REQUIRED, "1" if f.get("required") else "0")
                self._set_cell(r, self.COL_COMMENT, f.get("comment", ""))
        finally:
            self.blockSignals(False)
        self.changed.emit()

    def fields(self) -> list[dict]:
        out: list[dict] = []
        for r in range(self.rowCount()):
            name = _as_str(self.item(r, self.COL_NAME).text() if self.item(r, self.COL_NAME) else "")
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "type": _as_str(self.item(r, self.COL_TYPE).text() if self.item(r, self.COL_TYPE) else "")
                    or "string",
                    "required": _as_bool(self.item(r, self.COL_REQUIRED).text() if self.item(r, self.COL_REQUIRED) else ""),
                    "comment": _as_str(self.item(r, self.COL_COMMENT).text() if self.item(r, self.COL_COMMENT) else ""),
                }
            )
        return normalize_fields(out)

    def add_row(self) -> None:
        r = self.rowCount()
        self.insertRow(r)
        self._set_cell(r, self.COL_NAME, "")
        self._set_cell(r, self.COL_TYPE, "string")
        self._set_cell(r, self.COL_REQUIRED, "0")
        self._set_cell(r, self.COL_COMMENT, "")
        self.setCurrentCell(r, self.COL_NAME)
        self.editItem(self.item(r, self.COL_NAME))
        self.changed.emit()

    def remove_current_row(self) -> None:
        r = self.currentRow()
        if r < 0:
            return
        self.removeRow(r)
        self.changed.emit()

    def _set_cell(self, row: int, col: int, text: str) -> None:
        it = QTableWidgetItem(str(text or ""))
        if col == self.COL_REQUIRED:
            it.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
        self.setItem(row, col, it)


class AttributesEditorWidget(QWidget):
    """Editor for object attributes (fields)."""

    patchChanged = Signal(dict)

    def __init__(self, initial: Any = None, parent: QWidget | None = None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        hint = QLabel(t("obj.attributes_hint"))
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.table = FieldsTableWidget()
        root.addWidget(self.table, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_add = QPushButton(t("btn_add"))
        self.btn_del = QPushButton(t("btn_delete"))
        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_del)
        root.addLayout(btns)

        self.btn_add.clicked.connect(self.table.add_row)
        self.btn_del.clicked.connect(self.table.remove_current_row)
        self.table.changed.connect(self._emit_patch)

        self.set_attributes(initial)

    def set_attributes(self, attrs: Any) -> None:
        self.table.set_fields(normalize_fields(attrs))

    def attributes(self) -> list[dict]:
        return self.table.fields()

    def _emit_patch(self) -> None:
        self.patchChanged.emit({"attributes": self.attributes()})


@dataclass
class _Tp:
    name: str
    title: str
    comment: str
    columns: list[dict]


class TabularPartsEditorWidget(QWidget):
    """Editor for tabular parts (list + columns)."""

    patchChanged = Signal(dict)

    def __init__(self, initial: Any = None, parent: QWidget | None = None):
        super().__init__(parent)

        self._parts: list[_Tp] = []
        self._cur_index: int = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        hint = QLabel(t("obj.tabular_parts_hint"))
        hint.setWordWrap(True)
        root.addWidget(hint)

        body = QHBoxLayout()
        body.setSpacing(12)

        # left: parts list
        left = QVBoxLayout()
        self.lst = QListWidget()
        self.lst.setMinimumWidth(220)
        left.addWidget(self.lst, 1)
        left_btns = QHBoxLayout()
        self.btn_add_tp = QPushButton(t("btn_add"))
        self.btn_del_tp = QPushButton(t("btn_delete"))
        left_btns.addWidget(self.btn_add_tp)
        left_btns.addWidget(self.btn_del_tp)
        left.addLayout(left_btns)
        body.addLayout(left, 0)

        # right: properties + columns
        right = QVBoxLayout()
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)

        grid.addWidget(QLabel(t("schema.tp.name")), 0, 0)
        self.ed_name = QLineEdit()
        grid.addWidget(self.ed_name, 0, 1)

        grid.addWidget(QLabel(t("schema.tp.title")), 1, 0)
        self.ed_title = QLineEdit()
        grid.addWidget(self.ed_title, 1, 1)

        grid.addWidget(QLabel(t("schema.tp.comment")), 2, 0)
        self.ed_comment = QPlainTextEdit()
        self.ed_comment.setMinimumHeight(80)
        grid.addWidget(self.ed_comment, 2, 1)
        right.addLayout(grid)

        self.columns = FieldsTableWidget()
        right.addWidget(QLabel(t("schema.tp.columns")))
        right.addWidget(self.columns, 1)

        cols_btns = QHBoxLayout()
        cols_btns.addStretch(1)
        self.btn_add_col = QPushButton(t("btn_add"))
        self.btn_del_col = QPushButton(t("btn_delete"))
        cols_btns.addWidget(self.btn_add_col)
        cols_btns.addWidget(self.btn_del_col)
        right.addLayout(cols_btns)

        body.addLayout(right, 1)
        root.addLayout(body, 1)

        # wiring
        self.btn_add_tp.clicked.connect(self._add_part)
        self.btn_del_tp.clicked.connect(self._delete_part)
        self.lst.currentRowChanged.connect(self._select_part)

        self.ed_name.textEdited.connect(lambda _t: self._sync_current_from_ui())
        self.ed_title.textEdited.connect(lambda _t: self._sync_current_from_ui())
        self.ed_comment.textChanged.connect(self._sync_current_from_ui)
        self.columns.changed.connect(self._sync_current_from_ui)

        self.btn_add_col.clicked.connect(self.columns.add_row)
        self.btn_del_col.clicked.connect(self.columns.remove_current_row)

        self.set_tabular_parts(initial)

    def set_tabular_parts(self, parts: Any) -> None:
        self._parts = [
            _Tp(
                name=p["name"],
                title=p.get("title") or p["name"],
                comment=p.get("comment") or "",
                columns=normalize_fields(p.get("columns")),
            )
            for p in normalize_tabular_parts(parts)
        ]
        self._rebuild_list()
        self._select_part(0 if self._parts else -1)
        self._emit_patch()

    def tabular_parts(self) -> list[dict]:
        out: list[dict] = []
        for p in self._parts:
            out.append(
                {
                    "name": p.name,
                    "title": p.title or p.name,
                    "comment": p.comment,
                    "columns": normalize_fields(p.columns),
                }
            )
        return normalize_tabular_parts(out)

    # ---- actions ----
    def _rebuild_list(self) -> None:
        self.lst.blockSignals(True)
        try:
            self.lst.clear()
            for p in self._parts:
                it = QListWidgetItem(p.title or p.name)
                it.setData(Qt.ItemDataRole.UserRole, p.name)
                self.lst.addItem(it)
        finally:
            self.lst.blockSignals(False)

    def _add_part(self) -> None:
        base = "Table"
        idx = 1
        names = {p.name.lower() for p in self._parts}
        while f"{base}{idx}".lower() in names:
            idx += 1
        name = f"{base}{idx}"
        self._parts.append(_Tp(name=name, title=name, comment="", columns=[]))
        self._rebuild_list()
        self.lst.setCurrentRow(len(self._parts) - 1)
        self._emit_patch()

    def _delete_part(self) -> None:
        r = self.lst.currentRow()
        if r < 0 or r >= len(self._parts):
            return
        resp = QMessageBox.question(self, t("dlg_confirm"), t("schema.tp.delete_confirm"))
        if resp != QMessageBox.StandardButton.Yes:
            return
        del self._parts[r]
        self._rebuild_list()
        self._select_part(min(r, len(self._parts) - 1))
        self._emit_patch()

    def _select_part(self, row: int) -> None:
        if row < 0 or row >= len(self._parts):
            self._cur_index = -1
            self.ed_name.setText("")
            self.ed_title.setText("")
            self.ed_comment.setPlainText("")
            self.columns.set_fields([])
            return
        self._cur_index = row
        p = self._parts[row]
        self.ed_name.setText(p.name)
        self.ed_title.setText(p.title)
        self.ed_comment.setPlainText(p.comment)
        self.columns.set_fields(p.columns)

    def _sync_current_from_ui(self) -> None:
        if self._cur_index < 0 or self._cur_index >= len(self._parts):
            return
        p = self._parts[self._cur_index]
        p.name = _as_str(self.ed_name.text()) or p.name
        p.title = _as_str(self.ed_title.text()) or p.name
        p.comment = _as_str(self.ed_comment.toPlainText())
        p.columns = self.columns.fields()

        # refresh list item title
        it = self.lst.item(self._cur_index)
        if it is not None:
            it.setText(p.title or p.name)

        self._emit_patch()

    def _emit_patch(self) -> None:
        self.patchChanged.emit({"tabular_parts": self.tabular_parts()})
