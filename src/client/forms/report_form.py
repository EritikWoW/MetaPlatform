"""src.client.forms.report_form — Report UI forms.

ReportListForm   — tree/list of available reports
ReportParamsForm — parameter input before generation
ReportResultForm — grid with result + Export toolbar
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal, QSortFilterProxyModel
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t


# ─────────────────────────────────── helpers ───────────────────────────────

def _col_key(col) -> str:
    return str(getattr(col, "key", None) or col.get("key", ""))

def _col_title(col) -> str:
    return str(getattr(col, "title", None) or col.get("title", ""))


# ─────────────────────────────────── ReportListForm ────────────────────────

class ReportListForm(QWidget):
    """Sidebar-style list of available reports.

    Emits open_report_requested(report_name) when user double-clicks or
    clicks the Run button.
    """

    open_report_requested = Signal(str)  # report_name

    def __init__(self, *, db=None, manifest_rows: list,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db    = db
        self._mrows = manifest_rows

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # Toolbar
        bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(t("client_search_placeholder"))
        self._search.textChanged.connect(self._on_search)
        bar.addWidget(self._search, 1)
        btn_run = QPushButton(t("report_btn_run"))
        btn_run.clicked.connect(self._on_run)
        bar.addWidget(btn_run)
        root.addLayout(bar)

        # List
        self._model = QStandardItemModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self._view = QTableView()
        self._view.setModel(self._proxy)
        self._view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.setAlternatingRowColors(True)
        self._view.verticalHeader().setVisible(False)
        self._view.doubleClicked.connect(self._on_run)
        root.addWidget(self._view, 1)

        self._status = QLabel()
        root.addWidget(self._status)

        self._populate()

    def _populate(self) -> None:
        try:
            from src.runtime.report_engine import ReportEngine
            reports = ReportEngine(self._db, self._mrows).list_reports()
        except Exception:
            reports = []

        self._model.clear()
        self._model.setHorizontalHeaderLabels([
            t("report_col_name"), t("report_col_title"),
        ])

        for r in reports:
            name_item  = QStandardItem(str(r.get("name") or ""))
            title_item = QStandardItem(str(r.get("title") or ""))
            name_item.setData(str(r.get("name") or ""), Qt.ItemDataRole.UserRole)
            self._model.appendRow([name_item, title_item])

        self._view.resizeColumnsToContents()
        n = self._model.rowCount()
        self._status.setText(f"{n} {t('report_status_count')}")

    def _on_search(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)

    def _on_run(self, *_) -> None:
        idx = self._view.currentIndex()
        if not idx.isValid():
            return
        src_idx = self._proxy.mapToSource(idx)
        item = self._model.item(src_idx.row(), 0)
        if item:
            name = item.data(Qt.ItemDataRole.UserRole)
            if name:
                self.open_report_requested.emit(name)

    def refresh(self) -> None:
        self._populate()


# ─────────────────────────────────── ReportParamsForm ──────────────────────

class ReportParamsForm(QDialog):
    """Modal dialog for entering report parameters before generation."""

    def __init__(self, *, report_name: str, report_title: str,
                 param_defs: list, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{t('report_params_title')} — {report_title}")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._values: Dict[str, Any] = {}

        root = QVBoxLayout(self)

        if param_defs:
            grp = QGroupBox(t("report_params_group"))
            form = QFormLayout(grp)
            form.setSpacing(8)
            self._editors: dict[str, QWidget] = {}

            for pdef in param_defs:
                name = str(pdef.get("name") or "").strip()
                if not name:
                    continue
                pay  = pdef.get("payload") or {}
                if isinstance(pay, dict):
                    ptype   = str(pay.get("type") or "str").strip().lower()
                    default = pay.get("default")
                    label   = str(pay.get("title") or name)
                else:
                    ptype, default, label = "str", None, name

                if ptype in ("date", "дата"):
                    w = QDateEdit()
                    w.setCalendarPopup(True)
                    w.setDisplayFormat("dd.MM.yyyy")
                    if default:
                        try:
                            from datetime import datetime
                            from PySide6.QtCore import QDate
                            d = datetime.strptime(str(default), "%Y-%m-%d").date()
                            w.setDate(QDate(d.year, d.month, d.day))
                        except Exception:
                            w.setDate(w.minimumDate())
                    else:
                        from PySide6.QtCore import QDate
                        w.setDate(QDate.currentDate())
                elif ptype in ("int", "integer", "ціле"):
                    w = QSpinBox()
                    w.setRange(-2_147_483_648, 2_147_483_647)
                    if default is not None:
                        try:
                            w.setValue(int(default))
                        except Exception:
                            pass
                elif ptype in ("choice",):
                    w = QComboBox()
                    choices = pay.get("choices") if isinstance(pay, dict) else []
                    if isinstance(choices, list):
                        for c in choices:
                            w.addItem(str(c))
                    if default:
                        idx = w.findText(str(default))
                        if idx >= 0:
                            w.setCurrentIndex(idx)
                else:
                    w = QLineEdit()
                    if default is not None:
                        w.setText(str(default))

                self._editors[name] = w
                form.addRow(label, w)

            root.addWidget(grp)
        else:
            root.addWidget(QLabel(t("report_no_params")))

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._collect_and_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _collect_and_accept(self) -> None:
        from PySide6.QtCore import QDate
        for name, w in self._editors.items():
            if isinstance(w, QDateEdit):
                d = w.date()
                self._values[name] = f"{d.year():04d}-{d.month():02d}-{d.day():02d}"
            elif isinstance(w, QSpinBox):
                self._values[name] = w.value()
            elif isinstance(w, QComboBox):
                self._values[name] = w.currentText()
            else:
                self._values[name] = w.text()
        self.accept()

    def get_params(self) -> Dict[str, Any]:
        return dict(self._values)


# ─────────────────────────────────── ReportResultForm ──────────────────────

class ReportResultForm(QWidget):
    """Displays report result in a sortable grid with export toolbar.

    The form is stateless — call display(result) to show a new result.
    Supports export to CSV and XLSX.
    """

    def __init__(self, *, db=None, manifest_rows: list,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db    = db
        self._mrows = manifest_rows
        self._current_result = None

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)

        btn_run = QPushButton(t("report_btn_run"))
        btn_run.clicked.connect(self._on_rerun)
        toolbar.addWidget(btn_run)
        toolbar.addSeparator()

        btn_csv = QPushButton(t("report_btn_export_csv"))
        btn_csv.clicked.connect(self._export_csv)
        toolbar.addWidget(btn_csv)

        btn_xlsx = QPushButton(t("report_btn_export_xlsx"))
        btn_xlsx.clicked.connect(self._export_xlsx)
        toolbar.addWidget(btn_xlsx)

        root.addWidget(toolbar)

        # Result title
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        root.addWidget(self._title_lbl)

        # Grid
        self._model = QStandardItemModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        root.addWidget(self._table, 1)

        # Status bar
        self._status = QLabel()
        root.addWidget(self._status)

        # Report name (for re-run)
        self._report_name: Optional[str] = None
        self._last_params: Dict[str, Any] = {}

    # ── public ──────────────────────────────────────────────────────────────

    def display(self, result) -> None:
        """Show a ReportResult object in the grid."""
        self._current_result = result
        self._report_name    = result.report_name
        self._last_params    = dict(result.params_used or {})
        self._title_lbl.setText(result.title or result.report_name)
        self._fill_model(result)

    # ── private ─────────────────────────────────────────────────────────────

    def _fill_model(self, result) -> None:
        self._model.clear()
        if not result or not result.ok:
            msg = "\n".join(result.messages) if result else "No data"
            self._model.setHorizontalHeaderLabels([t("report_col_error")])
            self._model.appendRow([QStandardItem(msg)])
            self._status.setText(t("report_status_error"))
            return

        headers = [_col_title(c) for c in result.columns]
        self._model.setHorizontalHeaderLabels(headers)

        for row in result.rows:
            items = []
            for col in result.columns:
                val = row.get(_col_key(col), "")
                item = QStandardItem(str(val) if val is not None else "")
                item.setData(val, Qt.ItemDataRole.UserRole)
                items.append(item)
            self._model.appendRow(items)

        self._table.resizeColumnsToContents()
        n = len(result.rows)
        self._status.setText(f"{n} {t('report_status_rows')}")
        if result.messages:
            self._status.setText(
                self._status.text() + " | " + "; ".join(result.messages)
            )

    def _on_rerun(self) -> None:
        if not self._report_name or self._db is None:
            return
        try:
            from src.runtime.report_engine import ReportEngine
            engine = ReportEngine(self._db, self._mrows)
            result = engine.run(self._report_name, params=self._last_params)
            self.display(result)
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), str(e))

    def _export_csv(self) -> None:
        if self._current_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, t("report_save_csv"), "", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(self._current_result.to_csv())
            QMessageBox.information(self, t("report_export_ok"), path)
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), str(e))

    def _export_xlsx(self) -> None:
        if self._current_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, t("report_save_xlsx"), "", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            data = self._current_result.to_xlsx_bytes()
            with open(path, "wb") as f:
                f.write(data)
            QMessageBox.information(self, t("report_export_ok"), path)
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), str(e))
