from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QTabWidget,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

from src.ui_qt.i18n import t


@dataclass(frozen=True)
class GlobalSearchOptions:
    match_case: bool = False
    whole_word: bool = False
    module_guid: str = ""
    limit: int = 500


@dataclass(frozen=True)
class GlobalSearchHit:
    title: str
    where: str
    line: int
    col: int
    preview: str
    payload: dict


class GlobalSearchDialog(QDialog):
    """1C-like "Global search in texts" dialog (MVP).

    - UI close to 1C
    - actual searching is delegated to search_fn

    search_fn(term, opts) -> list[GlobalSearchHit]
    open_hit_fn(hit) -> None
    """

    searchFinished = Signal(int, object, str)

    def __init__(
        self,
        parent=None,
        *,
        search_fn: Callable[[str, GlobalSearchOptions], List[GlobalSearchHit]],
        open_hit_fn: Callable[[GlobalSearchHit], None],
        initial_term: str = "",
        initial_options: GlobalSearchOptions | None = None,
        auto_start: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(t("dlg_global_search_title"))
        self.setModal(True)
        self.resize(900, 560)

        self._search_fn = search_fn
        self._open_hit_fn = open_hit_fn
        self._initial_options = initial_options or GlobalSearchOptions()
        self._search_generation = 0

        root = QVBoxLayout(self)

        # Top panel
        top = QHBoxLayout()
        top.addWidget(QLabel(t("lbl_find"), self))
        self.ed_find = QLineEdit(self)
        top.addWidget(self.ed_find, 1)
        self.btn_find = QPushButton(t("btn_search"), self)
        top.addWidget(self.btn_find)
        root.addLayout(top)
        self.lbl_status = QLabel("", self)
        root.addWidget(self.lbl_status)

        opt = QHBoxLayout()
        self.cb_case = QCheckBox(t("search_match_case"), self)
        self.cb_word = QCheckBox(t("search_whole_word"), self)
        self.cb_case.setChecked(bool(self._initial_options.match_case))
        self.cb_word.setChecked(bool(self._initial_options.whole_word))
        opt.addWidget(self.cb_case)
        opt.addWidget(self.cb_word)
        opt.addStretch(1)
        root.addLayout(opt)

        # Tabs (MVP: keep placeholders to match 1C look)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(QWidget(self), t("global_search_tab_texts"))
        self.tabs.addTab(QWidget(self), t("global_search_tab_config"))
        self.tabs.addTab(QWidget(self), t("global_search_tab_files"))
        root.addWidget(self.tabs)

        # Results table
        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            t("col_object"),
            t("col_place"),
            t("col_line"),
            t("col_preview"),
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        root.addWidget(self.table, 1)

        self.btn_find.clicked.connect(self._run_search)
        self.ed_find.returnPressed.connect(self._run_search)
        self.table.cellDoubleClicked.connect(self._open_current)
        self.searchFinished.connect(self._apply_search_results)
        self.ed_find.setText(str(initial_term or ""))
        if auto_start and str(initial_term or "").strip():
            QTimer.singleShot(0, self._run_search)

    def _opts(self) -> GlobalSearchOptions:
        return GlobalSearchOptions(
            match_case=self.cb_case.isChecked(),
            whole_word=self.cb_word.isChecked(),
            module_guid=str(self._initial_options.module_guid or ""),
            limit=int(self._initial_options.limit or 500),
        )

    def _run_search(self) -> None:
        term = str(self.ed_find.text() or "").strip()
        if not term:
            return
        self._search_generation += 1
        generation = self._search_generation
        options = self._opts()
        self.btn_find.setEnabled(False)
        self.lbl_status.setText(t("global_search_running"))
        self.table.setRowCount(0)

        def _worker() -> None:
            try:
                hits = list(self._search_fn(term, options) or [])
                error = ""
            except Exception as exc:
                hits = []
                error = f"{type(exc).__name__}: {exc}"
            self.searchFinished.emit(generation, hits, error)

        threading.Thread(target=_worker, name="MetaGlobalSearch", daemon=True).start()

    def _apply_search_results(self, generation: int, raw_hits: object, error: str) -> None:
        if int(generation) != self._search_generation:
            return
        self.btn_find.setEnabled(True)
        hits = list(raw_hits or [])
        if error:
            self.lbl_status.setText(t("global_search_failed").format(error=error))
        else:
            self.lbl_status.setText(t("global_search_found").format(count=len(hits)))
        self.table.setRowCount(0)
        for h in hits:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(h.title))
            self.table.setItem(r, 1, QTableWidgetItem(h.where))
            self.table.setItem(r, 2, QTableWidgetItem(str(h.line)))
            self.table.setItem(r, 3, QTableWidgetItem(h.preview))
            # stash payload
            for c in range(4):
                it = self.table.item(r, c)
                if it is not None:
                    it.setData(Qt.ItemDataRole.UserRole, h)

        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def _current_hit(self) -> Optional[GlobalSearchHit]:
        r = self.table.currentRow()
        if r < 0:
            return None
        it = self.table.item(r, 0)
        if it is None:
            return None
        h = it.data(Qt.ItemDataRole.UserRole)
        if isinstance(h, GlobalSearchHit):
            return h
        return None

    def _open_current(self) -> None:
        h = self._current_hit()
        if h is None:
            return
        try:
            self._open_hit_fn(h)
        except Exception:
            pass
