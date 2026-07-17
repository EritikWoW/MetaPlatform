from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QSortFilterProxyModel
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel,
    QTreeView, QTextEdit, QSplitter, QMessageBox
)

from .i18n import t, bind


@dataclass(frozen=True)
class DbObject:
    kind: str   # "table" | "view" | "index" | "trigger"
    name: str
    sql: str


def _open_sqlite(db_path: str) -> sqlite3.Connection:
    # mpdb у тебя сейчас по факту SQLite-файл (раз ты читаешь его как файл БД)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _load_db_objects(con: sqlite3.Connection) -> list[DbObject]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT type, name, COALESCE(sql,'') AS sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    )
    out: list[DbObject] = []
    for r in cur.fetchall():
        out.append(DbObject(kind=str(r["type"]), name=str(r["name"]), sql=str(r["sql"] or "")))
    return out


def _table_columns(con: sqlite3.Connection, table_name: str) -> list[str]:
    cur = con.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    cols = []
    for r in cur.fetchall():
        # cid, name, type, notnull, dflt_value, pk
        cols.append(f"{r[1]}  {r[2]}{'  PK' if r[5] else ''}{'  NOT NULL' if r[3] else ''}")
    return cols


class _RecursiveFilterProxy(QSortFilterProxyModel):
    """
    Proxy с рекурсивным фильтром для дерева.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setRecursiveFilteringEnabled(True)
        self.setFilterKeyColumn(0)


class ConfiguratorWindow(QMainWindow):
    def __init__(self, db_path: str) -> None:
        super().__init__()

        self._db_path = db_path
        self._con: sqlite3.Connection | None = None

        self.setWindowTitle("MetaPlatform — Configurator")
        self.resize(980, 560)
        self.setMinimumSize(860, 520)

        root = QWidget(self)
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(10)

        # Top: title + search
        top = QHBoxLayout()
        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet("font-size: 12pt; font-weight: 650;")
        top.addWidget(self.lbl_title, 0)

        top.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск...")
        self.search.setFixedWidth(320)
        top.addWidget(self.search, 0)

        outer.addLayout(top)

        # Splitter: tree (left) + details (right)
        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split, 1)

        # Left panel (tree)
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(8)

        self.lbl_db = QLabel()
        self.lbl_db.setStyleSheet("color: #9AA4B2;")
        left_l.addWidget(self.lbl_db, 0)

        self.tree = QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QTreeView.NoEditTriggers)
        self.tree.setSelectionBehavior(QTreeView.SelectRows)
        self.tree.setSelectionMode(QTreeView.SingleSelection)
        self.tree.setAnimated(True)

        # Без “рамок” и сеток, но с нормальным выделением строки
        self.tree.setStyleSheet("""
        QTreeView {
            background: #0F172A;
            color: #E7EAF0;
            border: none;
            outline: 0;
        }
        QTreeView::item {
            padding: 6px 8px;
        }
        QTreeView::item:selected {
            background: #5B5BD6;
            color: white;
        }
        QTreeView::item:hover {
            background: rgba(91, 91, 214, 0.22);
        }
        """)

        left_l.addWidget(self.tree, 1)
        split.addWidget(left)

        # Right panel (details)
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(8)

        self.lbl_obj = QLabel()
        self.lbl_obj.setStyleSheet("font-size: 11pt; font-weight: 650;")
        right_l.addWidget(self.lbl_obj, 0)

        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setStyleSheet("""
        QTextEdit {
            background: #0F172A;
            color: #E7EAF0;
            border: none;
            padding: 10px;
        }
        """)
        right_l.addWidget(self.details, 1)

        split.addWidget(right)
        split.setSizes([340, 640])

        # Model: дерево из sqlite_master
        self._src_model = QStandardItemModel(self)
        self._proxy = _RecursiveFilterProxy(self)
        self._proxy.setSourceModel(self._src_model)
        self.tree.setModel(self._proxy)

        # Signals
        self.search.textChanged.connect(self._proxy.setFilterFixedString)
        self.tree.selectionModel().selectionChanged.connect(self._on_select)

        # i18n live update
        bind(self.apply_i18n, widget=self)
        self.apply_i18n()

        # Load DB
        self._reload_tree()

    def apply_i18n(self) -> None:
        self.lbl_title.setText(t("btn_config") if "btn_config" else "Configurator")
        self.lbl_db.setText(f"{t('col_path')}: {self._db_path}")
        self.search.setPlaceholderText(t("ph_search"))
        # не трогаем selection, только тексты

    def _reload_tree(self) -> None:
        try:
            if not Path(self._db_path).exists():
                raise FileNotFoundError(self._db_path)

            self._con = _open_sqlite(self._db_path)
            objs = _load_db_objects(self._con)

        except Exception as e:
            QMessageBox.critical(self, "DB", f"Не удалось открыть БД:\n{e}")
            return

        self._src_model.clear()

        # Группы строго из БД: table/view/index/trigger
        root = self._src_model.invisibleRootItem()

        g_tables = QStandardItem("Таблицы")
        g_views = QStandardItem("Представления")
        g_indexes = QStandardItem("Индексы")
        g_triggers = QStandardItem("Триггеры")

        for g in (g_tables, g_views, g_indexes, g_triggers):
            g.setEditable(False)
            root.appendRow(g)

        def add_item(parent: QStandardItem, o: DbObject):
            it = QStandardItem(o.name)
            it.setEditable(False)
            # храним payload в UserRole
            it.setData(o, Qt.UserRole + 1)
            parent.appendRow(it)

        for o in objs:
            if o.kind == "table":
                add_item(g_tables, o)
            elif o.kind == "view":
                add_item(g_views, o)
            elif o.kind == "index":
                add_item(g_indexes, o)
            elif o.kind == "trigger":
                add_item(g_triggers, o)

        self.tree.expand(self._proxy.mapFromSource(g_tables.index()))
        self.tree.expand(self._proxy.mapFromSource(g_views.index()))

        self.lbl_obj.setText("")
        self.details.setPlainText("")

    def _selected_db_object(self) -> DbObject | None:
        sm = self.tree.selectionModel()
        if sm is None:
            return None
        idxs = sm.selectedRows()
        if not idxs:
            return None

        idx = idxs[0]
        src_idx = self._proxy.mapToSource(idx)
        item = self._src_model.itemFromIndex(src_idx)
        if item is None:
            return None

        o = item.data(Qt.UserRole + 1)
        return o if isinstance(o, DbObject) else None

    def _on_select(self, *_args) -> None:
        o = self._selected_db_object()
        if not o:
            self.lbl_obj.setText("")
            self.details.setPlainText("")
            return

        self.lbl_obj.setText(f"{o.name} ({o.kind})")

        lines: list[str] = []
        if self._con and o.kind == "table":
            cols = _table_columns(self._con, o.name)
            if cols:
                lines.append("Колонки:")
                lines.extend([f"  - {c}" for c in cols])
                lines.append("")

        if o.sql.strip():
            lines.append("SQL:")
            lines.append(o.sql.strip())

        self.details.setPlainText("\n".join(lines).strip())
