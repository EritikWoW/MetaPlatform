from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QDialog,
    QDialogButtonBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.mpdb.mpdb import Mpdb
from src.runtime.db_registry import DbRegistry, RegistryDb, get_registry_path
from .i18n import tr


@dataclass
class _Row:
    db_uid: str
    name: str
    path: str
    enabled: bool


class _RegistryTableModel(QAbstractTableModel):
    COLS = ("name", "enabled", "db_uid", "path")

    def __init__(self, rows: list[_Row]) -> None:
        super().__init__()
        self._rows = rows

    def set_rows(self, rows: list[_Row]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return len(self.COLS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            key = self.COLS[section]
            if key == "name":
                return tr("admin_col_name")
            if key == "enabled":
                return tr("admin_col_enabled")
            if key == "db_uid":
                return tr("admin_col_uid")
            if key == "path":
                return tr("admin_col_path")
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        col = self.COLS[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            if col == "name":
                return row.name
            if col == "enabled":
                return tr("admin_enabled_yes") if row.enabled else tr("admin_enabled_no")
            if col == "db_uid":
                return row.db_uid
            if col == "path":
                return row.path
        return None

    def row_at(self, view_row: int) -> Optional[_Row]:
        if 0 <= view_row < len(self._rows):
            return self._rows[view_row]
        return None


class RuntimeAdminWindow(QMainWindow):
    """Server-side GUI for managing runtime DB registry.

    Intended to be run on the server machine.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(tr("admin_title"))

        self._registry_path: Path = get_registry_path()
        self._registry = DbRegistry.load(self._registry_path)

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        # Top bar
        top = QHBoxLayout()
        self.lbl_path = QLabel(self)
        self._update_path_label()
        top.addWidget(self.lbl_path, 1)

        self.btn_change_path = QPushButton(tr("admin_btn_change_path"), self)
        self.btn_change_path.clicked.connect(self._on_change_path)
        top.addWidget(self.btn_change_path)

        self.btn_refresh = QPushButton(tr("admin_btn_refresh"), self)
        self.btn_refresh.clicked.connect(self.reload)
        top.addWidget(self.btn_refresh)
        layout.addLayout(top)

        # Table
        self.table = QTableView(self)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)

        self.model = _RegistryTableModel([])
        self.table.setModel(self.model)
        layout.addWidget(self.table, 1)

        # Buttons
        buttons = QHBoxLayout()
        self.btn_add = QPushButton(tr("admin_btn_add"), self)
        self.btn_add.clicked.connect(self._on_add)
        buttons.addWidget(self.btn_add)

        self.btn_edit = QPushButton(tr("admin_btn_edit"), self)
        self.btn_edit.clicked.connect(self._on_edit)
        buttons.addWidget(self.btn_edit)

        self.btn_enable = QPushButton(tr("admin_btn_enable_disable"), self)
        self.btn_enable.clicked.connect(self._on_toggle_enabled)
        buttons.addWidget(self.btn_enable)

        self.btn_remove = QPushButton(tr("admin_btn_remove"), self)
        self.btn_remove.clicked.connect(self._on_remove)
        buttons.addWidget(self.btn_remove)

        buttons.addStretch(1)
        layout.addLayout(buttons)

        # Status
        self.status = QLabel(self)
        self.status.setText("")
        layout.addWidget(self.status)

        # Menu
        self._build_menu()

        self.reload()

    def _build_menu(self) -> None:
        act_quit = QAction(tr("admin_menu_quit"), self)
        act_quit.triggered.connect(self.close)

        act_open_registry = QAction(tr("admin_menu_open_registry"), self)
        act_open_registry.triggered.connect(self._open_registry_folder)

        m_file = self.menuBar().addMenu(tr("admin_menu_file"))
        m_file.addAction(act_open_registry)
        m_file.addSeparator()
        m_file.addAction(act_quit)

    def _update_path_label(self) -> None:
        self.lbl_path.setText(f"{tr('admin_registry_path')}: {self._registry_path}")

    def reload(self) -> None:
        self._registry = DbRegistry.load(self._registry_path)
        rows = [_Row(x.db_uid, x.name, x.path, x.enabled) for x in self._registry.items]
        # stable order
        rows.sort(key=lambda r: (not r.enabled, r.name.lower(), r.db_uid))
        self.model.set_rows(rows)
        self.status.setText(tr("admin_status_loaded").format(total=len(rows)))

    def _current_row(self) -> Optional[_Row]:
        idx = self.table.currentIndex()
        return self.model.row_at(idx.row()) if idx.isValid() else None

    def _save_registry(self) -> None:
        try:
            self._registry.save(self._registry_path)
        except Exception as e:
            QMessageBox.critical(self, tr("dlg_error_title"), f"{tr('admin_err_save')}\n\n{e}")

    def _on_change_path(self) -> None:
        start = str(self._registry_path)
        file_path, _ = QFileDialog.getSaveFileName(self, tr("admin_pick_registry"), start, "JSON (*.json)")
        if not file_path:
            return
        self._registry_path = Path(file_path).expanduser().resolve()
        self._update_path_label()
        self.reload()

    def _open_registry_folder(self) -> None:
        try:
            p = self._registry_path.parent
            if os.name == "nt":
                os.startfile(str(p))  # type: ignore[attr-defined]
            else:
                # best-effort
                import subprocess

                subprocess.Popen(["xdg-open", str(p)])
        except Exception:
            pass

    def _on_add(self) -> None:
        db_file, _ = QFileDialog.getOpenFileName(self, tr("admin_pick_db"), "", "MetaDB (*.mpdb)")
        if not db_file:
            return

        p = Path(db_file)
        if not p.exists():
            QMessageBox.warning(self, tr("dlg_error_title"), tr("dlg_bad_db_file"))
            return

        try:
            db = Mpdb(str(p))
            db_uid = getattr(db, "db_uid", None) or getattr(db, "_db_uid", None)
            if not db_uid:
                raise RuntimeError("db_uid is empty")
        except Exception as e:
            QMessageBox.critical(self, tr("dlg_error_title"), f"{tr('admin_err_open_db')}\n\n{e}")
            return

        name, ok = QInputDialog.getText(self, tr("admin_name_title"), tr("admin_name_prompt"), text=p.stem)
        if not ok:
            return
        name = (name or p.stem).strip() or p.stem

        self._registry.upsert(RegistryDb(db_uid=str(db_uid), name=name, path=str(p), enabled=True))
        self._save_registry()
        self.reload()
        self.status.setText(tr("admin_status_added").format(name=name))

    def _on_edit(self) -> None:
        row = self._current_row()
        if not row:
            QMessageBox.information(self, tr("admin_title"), tr("dlg_pick_db_first"))
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("admin_edit_title"))
        dlg.setModal(True)
        v = QVBoxLayout(dlg)
        form = QFormLayout()
        v.addLayout(form)

        inp_name = QLineEdit(row.name, dlg)
        inp_path = QLineEdit(row.path, dlg)
        inp_path.setReadOnly(True)

        btn_pick = QPushButton(tr("admin_btn_pick_path"), dlg)

        def pick_path() -> None:
            new_file, _ = QFileDialog.getOpenFileName(self, tr("admin_pick_db"), row.path, "MetaDB (*.mpdb)")
            if new_file:
                inp_path.setText(new_file)

        btn_pick.clicked.connect(pick_path)

        form.addRow(tr("admin_col_name"), inp_name)
        form.addRow(tr("admin_col_uid"), QLabel(row.db_uid, dlg))

        path_row = QHBoxLayout()
        path_row.addWidget(inp_path, 1)
        path_row.addWidget(btn_pick)
        form.addRow(tr("admin_col_path"), path_row)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_name = inp_name.text().strip() or row.name
        new_path = inp_path.text().strip() or row.path

        # optional: verify db_uid matches file
        try:
            db = Mpdb(str(new_path))
            actual = getattr(db, "db_uid", None) or getattr(db, "_db_uid", None)
            if str(actual) != row.db_uid:
                QMessageBox.critical(self, tr("dlg_error_title"), tr("dlg_db_uid_mismatch"))
                return
        except Exception as e:
            QMessageBox.critical(self, tr("dlg_error_title"), f"{tr('admin_err_open_db')}\n\n{e}")
            return

        item = self._registry.get(row.db_uid)
        if not item:
            return
        item.name = new_name
        item.path = new_path
        self._save_registry()
        self.reload()
        self.status.setText(tr("admin_status_updated").format(name=new_name))

    def _on_toggle_enabled(self) -> None:
        row = self._current_row()
        if not row:
            QMessageBox.information(self, tr("admin_title"), tr("dlg_pick_db_first"))
            return
        item = self._registry.get(row.db_uid)
        if not item:
            return
        item.enabled = not item.enabled
        self._save_registry()
        self.reload()
        self.status.setText(tr("admin_status_toggled").format(name=item.name))

    def _on_remove(self) -> None:
        row = self._current_row()
        if not row:
            QMessageBox.information(self, tr("admin_title"), tr("dlg_pick_db_first"))
            return

        confirm = QMessageBox.question(
            self,
            tr("dlg_remove_confirm_title"),
            tr("admin_remove_confirm").format(name=row.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._registry.remove(row.db_uid)
        self._save_registry()
        self.reload()
        self.status.setText(tr("admin_status_removed").format(name=row.name))
