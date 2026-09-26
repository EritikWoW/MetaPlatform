from __future__ import annotations

from collections.abc import Callable
import threading
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QHeaderView,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t


class _DiagnosticsLoadThread(QObject):
    loaded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, loader: Callable[[], object], parent=None) -> None:
        super().__init__(parent)
        self._loader = loader

    def run(self) -> None:
        try:
            data = self._loader()
        except Exception as exc:
            try:
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            except RuntimeError:
                pass
        else:
            try:
                self.loaded.emit(data)
            except RuntimeError:
                pass  # Owner was deleted while the RPC was in progress.
        finally:
            try:
                self.finished.emit()
            except RuntimeError:
                pass

    def start(self) -> None:
        # No parent-owned running QThread to destroy or wait for on close.
        threading.Thread(target=self.run, name="MetaDiagnostics", daemon=True).start()


class WorkspaceProblemsPanel(QWidget):
    openRequested = Signal(str, str, int)
    diagnosticsChanged = Signal(object)

    _ROLE_DIAGNOSTIC = int(Qt.ItemDataRole.UserRole) + 1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loader: Callable[[], object] | None = None
        self._thread: _DiagnosticsLoadThread | None = None
        self._diagnostics: list[dict[str, Any]] = []
        self._generation = 0
        self._loading = False
        self._last_error = ""
        self._pending_navigation = 0
        self._navigation_row = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 5, 6, 5)
        root.setSpacing(5)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)
        self.summary = QLabel(t("workspace_problems_empty"))
        self.summary.setObjectName("workspaceProblemsSummary")
        toolbar.addWidget(self.summary)
        toolbar.addStretch(1)

        self.severity_filter = QComboBox()
        self.severity_filter.addItem(t("workspace_problems_all"), "")
        self.severity_filter.addItem(t("workspace_problems_errors"), "error")
        self.severity_filter.addItem(t("workspace_problems_warnings"), "warning")
        self.severity_filter.currentIndexChanged.connect(self._apply_filters)
        toolbar.addWidget(self.severity_filter)

        self.search = QLineEdit()
        self.search.setPlaceholderText(t("workspace_problems_search"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filters)
        toolbar.addWidget(self.search)

        self.refresh_button = QPushButton(t("btn_reload"))
        self.refresh_button.clicked.connect(self.refresh_async)
        toolbar.addWidget(self.refresh_button)
        root.addLayout(toolbar)

        self.model = QStandardItemModel(0, 5, self)
        self.model.setHorizontalHeaderLabels(
            [
                t("workspace_problems_severity"),
                t("workspace_problems_message"),
                t("workspace_problems_module"),
                t("workspace_problems_line"),
                t("workspace_problems_code"),
            ]
        )
        self.table = QTableView()
        self.table.setObjectName("workspaceProblemsTable")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._open_index)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)

    def set_loader(self, loader: Callable[[], object] | None) -> None:
        self._loader = loader

    def set_diagnostics(
        self,
        diagnostics: list[dict[str, Any]],
        *,
        generation: int = 0,
    ) -> None:
        self._diagnostics = [
            dict(item)
            for item in list(diagnostics or [])
            if isinstance(item, dict)
        ]
        self._generation = int(generation or self._generation)
        self._last_error = ""
        self._apply_filters()
        self.diagnosticsChanged.emit(
            [dict(item) for item in self._diagnostics]
        )

    def refresh_async(self) -> bool:
        if self._loading or self._loader is None:
            return False
        self._loading = True
        self._last_error = ""
        self.refresh_button.setEnabled(False)
        self.summary.setText(t("workspace_problems_loading"))
        thread = _DiagnosticsLoadThread(self._loader, self)
        self._thread = thread
        thread.loaded.connect(self._loaded)
        thread.failed.connect(self._failed)
        thread.finished.connect(self._thread_finished)
        thread.start()
        return True

    def state(self, *, include_diagnostics: bool = True) -> dict[str, Any]:
        current = self.table.currentIndex()
        result = {
            "loading": bool(self._loading),
            "generation": int(self._generation),
            "count": len(self._diagnostics),
            "visible_count": int(self.model.rowCount()),
            "error_count": sum(
                1 for item in self._diagnostics if item.get("severity") == "error"
            ),
            "warning_count": sum(
                1 for item in self._diagnostics if item.get("severity") == "warning"
            ),
            "last_error": self._last_error,
            "current_row": int(current.row()) if current.isValid() else -1,
        }
        if current.isValid():
            item = self.model.item(current.row(), 0)
            diagnostic = (
                item.data(self._ROLE_DIAGNOSTIC)
                if item is not None
                else None
            )
            if isinstance(diagnostic, dict):
                result["current_diagnostic"] = dict(diagnostic)
        if include_diagnostics:
            result["diagnostics"] = [
                dict(item) for item in self._diagnostics
            ]
        return result

    def _loaded(self, payload: object) -> None:
        if isinstance(payload, dict):
            rows = payload.get("diagnostics")
            self.set_diagnostics(
                rows if isinstance(rows, list) else [],
                generation=int(payload.get("generation") or 0),
            )
            return
        rows = payload if isinstance(payload, list) else []
        self.set_diagnostics(rows)

    def _failed(self, error: str) -> None:
        self._last_error = str(error or "")
        self.summary.setText(
            t("workspace_problems_failed").format(error=self._last_error)
        )

    def _thread_finished(self) -> None:
        self._loading = False
        self.refresh_button.setEnabled(True)
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.deleteLater()
        if not self._last_error:
            self._update_summary()
        pending = self._pending_navigation
        self._pending_navigation = 0
        if pending:
            self.navigate(pending, refresh_if_empty=False)

    def navigate(self, delta: int = 1, *, refresh_if_empty: bool = True) -> bool:
        """Select and open the next or previous visible diagnostic."""
        step = -1 if int(delta) < 0 else 1
        row_count = self.model.rowCount()
        if row_count <= 0:
            if refresh_if_empty and self._loader is not None:
                self._pending_navigation = step
                if not self._loading:
                    self.refresh_async()
            return False
        if 0 <= self._navigation_row < row_count:
            row = (self._navigation_row + step) % row_count
        else:
            row = 0 if step > 0 else row_count - 1
        self._navigation_row = row
        index = self.model.index(row, 0)
        self.table.setCurrentIndex(index)
        self.table.selectRow(row)
        self.table.scrollTo(index, QTableView.ScrollHint.PositionAtCenter)
        self._open_index(index)
        return True

    def _apply_filters(self) -> None:
        severity = str(self.severity_filter.currentData() or "")
        term = self.search.text().strip().casefold()
        self.table.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        self._navigation_row = -1
        for diagnostic in self._diagnostics:
            if severity and str(diagnostic.get("severity") or "") != severity:
                continue
            searchable = " ".join(
                str(diagnostic.get(key) or "")
                for key in (
                    "message",
                    "code",
                    "qualifier",
                    "name",
                    "owner_name",
                    "owner_title",
                    "module_guid",
                )
            ).casefold()
            if term and term not in searchable:
                continue
            severity_name = t(
                "workspace_problems_error"
                if diagnostic.get("severity") == "error"
                else (
                    "workspace_problems_warning"
                    if diagnostic.get("severity") == "warning"
                    else "workspace_problems_info"
                )
            )
            module_title = str(
                diagnostic.get("owner_title")
                or diagnostic.get("owner_name")
                or diagnostic.get("module_guid")
                or ""
            )
            from src.ui_qt.module_titles import localized_module_title

            module_title = localized_module_title(
                diagnostic.get("module_kind"),
                fallback=module_title,
            )
            items = [
                QStandardItem(severity_name),
                QStandardItem(self._display_message(diagnostic)),
                QStandardItem(module_title),
                QStandardItem(str(int(diagnostic.get("line") or 0) or "")),
                QStandardItem(str(diagnostic.get("code") or "")),
            ]
            items[0].setData(dict(diagnostic), self._ROLE_DIAGNOSTIC)
            self.model.appendRow(items)
        self.table.setSortingEnabled(True)
        self._update_summary()

    def _update_summary(self) -> None:
        errors = sum(
            1 for item in self._diagnostics if item.get("severity") == "error"
        )
        warnings = sum(
            1 for item in self._diagnostics if item.get("severity") == "warning"
        )
        info = sum(
            1 for item in self._diagnostics if item.get("severity") == "info"
        )
        self.summary.setText(
            t("workspace_problems_summary").format(
                total=len(self._diagnostics),
                errors=errors,
                warnings=warnings,
                info=info,
            )
        )

    @staticmethod
    def _display_message(diagnostic: dict[str, Any]) -> str:
        code = str(diagnostic.get("code") or "")
        candidates = [
            str(item or "")
            for item in list(diagnostic.get("candidates") or [])
            if str(item or "").strip()
        ]
        suffix = (
            " "
            + t("workspace_problem_suggestions").format(
                candidates=", ".join(candidates)
            )
            if candidates and code != "ambiguous_qualifier"
            else ""
        )
        if code == "unresolved_member":
            return t("workspace_problem_unresolved_member").format(
                qualifier=str(diagnostic.get("qualifier") or ""),
                name=str(diagnostic.get("name") or ""),
            ) + suffix
        if code == "unresolved_module":
            return t("workspace_problem_unresolved_module").format(
                qualifier=str(diagnostic.get("qualifier") or "")
            ) + suffix
        if code == "unresolved_callable":
            return t("workspace_problem_unresolved_callable").format(
                name=str(diagnostic.get("name") or "")
            ) + suffix
        if code == "unresolved_requisite":
            return t("workspace_problem_unresolved_requisite").format(
                name=str(diagnostic.get("name") or "")
            ) + suffix
        if code == "ambiguous_qualifier":
            return t("workspace_problem_ambiguous_qualifier").format(
                qualifier=str(diagnostic.get("qualifier") or "")
            )
        if code == "lexer_partial":
            return t("workspace_problem_lexer_partial").format(
                count=int(diagnostic.get("unknown_count") or 0)
            )
        if code == "lexer_failed":
            return t("workspace_problem_lexer_failed").format(
                error=str(diagnostic.get("message") or "")
            )
        return str(diagnostic.get("message") or code)

    def _open_index(self, index) -> None:
        self._navigation_row = int(index.row())
        item = self.model.item(index.row(), 0)
        diagnostic = item.data(self._ROLE_DIAGNOSTIC) if item is not None else None
        if not isinstance(diagnostic, dict):
            return
        module_guid = str(diagnostic.get("module_guid") or "").strip()
        if not module_guid:
            return
        title = str(
            diagnostic.get("owner_title")
            or diagnostic.get("owner_name")
            or module_guid
        )
        self.openRequested.emit(
            module_guid,
            title,
            max(1, int(diagnostic.get("line") or 1)),
        )
