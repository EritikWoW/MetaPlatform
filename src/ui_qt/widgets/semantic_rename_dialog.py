from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.dsl.semantic_rename import (
    SemanticRenameError,
    SemanticRenamePlan,
    plan_semantic_rename,
    symbol_name_at,
)
from src.ui_qt.i18n import t


class SemanticRenameDialog(QDialog):
    def __init__(
        self,
        *,
        source: str,
        cursor_position: int,
        language: str = "mixed",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._source = str(source or "")
        self._cursor_position = int(cursor_position or 0)
        self._language = str(language or "mixed")
        self._plan: SemanticRenamePlan | None = None

        self.setWindowTitle(t("rename_symbol_title"))
        self.resize(760, 480)
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.lbl_old_name = QLabel(
            symbol_name_at(
                self._source,
                self._cursor_position,
                language=self._language,
            ),
            self,
        )
        form.addRow(t("rename_symbol_old_name"), self.lbl_old_name)
        self.ed_new_name = QLineEdit(self)
        self.ed_new_name.setText(self.lbl_old_name.text())
        form.addRow(t("rename_symbol_new_name"), self.ed_new_name)
        root.addLayout(form)

        self.lbl_scope = QLabel("", self)
        root.addWidget(self.lbl_scope)
        self.lbl_error = QLabel("", self)
        self.lbl_error.setStyleSheet("color: #F87171;")
        root.addWidget(self.lbl_error)

        self.table = QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(
            [
                t("rename_symbol_col_line"),
                t("rename_symbol_col_kind"),
                t("rename_symbol_col_preview"),
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(self.table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.btn_apply = QPushButton(t("rename_symbol_apply"), self)
        buttons.addButton(self.btn_apply, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        self.btn_apply.clicked.connect(self._accept_plan)
        root.addWidget(buttons)

        self.ed_new_name.textChanged.connect(self._refresh_preview)
        self.ed_new_name.returnPressed.connect(self._accept_plan)
        QTimer.singleShot(0, self._prepare_input)

    @property
    def plan(self) -> SemanticRenamePlan | None:
        return self._plan

    def _prepare_input(self) -> None:
        self.ed_new_name.setFocus()
        self.ed_new_name.selectAll()
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        try:
            plan = plan_semantic_rename(
                self._source,
                self._cursor_position,
                self.ed_new_name.text(),
                language=self._language,
            )
        except SemanticRenameError as exc:
            self._plan = None
            self.lbl_error.setText(_semantic_error_text(exc))
            self.lbl_scope.clear()
            self.table.setRowCount(0)
            self.btn_apply.setEnabled(False)
            return

        self._plan = plan
        self.lbl_error.clear()
        self.lbl_scope.setText(
            t("rename_symbol_scope").format(
                kind=t(f"rename_symbol_kind_{plan.symbol_kind}"),
                scope=plan.scope_name or t("rename_symbol_module_scope"),
                count=len(plan.occurrences),
            )
        )
        self.table.setRowCount(len(plan.occurrences))
        for row, occurrence in enumerate(plan.occurrences):
            self.table.setItem(row, 0, QTableWidgetItem(str(occurrence.line)))
            self.table.setItem(
                row,
                1,
                QTableWidgetItem(
                    t("rename_symbol_declaration")
                    if occurrence.declaration
                    else t("rename_symbol_usage")
                ),
            )
            self.table.setItem(row, 2, QTableWidgetItem(occurrence.preview))
        self.btn_apply.setEnabled(True)

    def _accept_plan(self) -> None:
        self._refresh_preview()
        if self._plan is not None:
            self.accept()


class WorkspaceRenamePreviewDialog(QDialog):
    def __init__(self, plan: dict, *, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("rename_workspace_preview_title"))
        self.resize(900, 560)
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                t("rename_workspace_preview_summary").format(
                    old=str(plan.get("old_name") or ""),
                    new=str(plan.get("new_name") or ""),
                    modules=int(plan.get("module_count") or 0),
                    count=int(plan.get("occurrence_count") or 0),
                ),
                self,
            )
        )
        note = QLabel(t("rename_workspace_apply_note"), self)
        note.setWordWrap(True)
        root.addWidget(note)
        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            [
                t("rename_workspace_col_module"),
                t("rename_symbol_col_line"),
                t("rename_symbol_col_kind"),
                t("rename_symbol_col_preview"),
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        rows: list[tuple[str, dict]] = []
        for module in list(plan.get("modules") or []):
            if not isinstance(module, dict):
                continue
            module_name = str(
                module.get("module_name")
                or module.get("module_guid")
                or ""
            )
            for occurrence in list(module.get("occurrences") or []):
                if isinstance(occurrence, dict):
                    rows.append((module_name, occurrence))
        self.table.setRowCount(len(rows))
        for row, (module_name, occurrence) in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(module_name))
            self.table.setItem(
                row,
                1,
                QTableWidgetItem(str(occurrence.get("line") or "")),
            )
            self.table.setItem(
                row,
                2,
                QTableWidgetItem(
                    t("rename_symbol_declaration")
                    if bool(occurrence.get("declaration"))
                    else t("rename_symbol_usage")
                ),
            )
            self.table.setItem(
                row,
                3,
                QTableWidgetItem(str(occurrence.get("preview") or "")),
            )
        root.addWidget(self.table, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.btn_apply = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.btn_apply.setText(t("btn_apply"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


def request_semantic_rename(
    *,
    source: str,
    cursor_position: int,
    language: str = "mixed",
    parent=None,
) -> SemanticRenamePlan | None:
    dialog = SemanticRenameDialog(
        source=source,
        cursor_position=cursor_position,
        language=language,
        parent=parent,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.plan


def request_workspace_rename_apply(plan: dict, *, parent=None) -> bool:
    dialog = WorkspaceRenamePreviewDialog(dict(plan or {}), parent=parent)
    return dialog.exec() == QDialog.DialogCode.Accepted


def show_workspace_rename_preview(plan: dict, *, parent=None) -> None:
    WorkspaceRenamePreviewDialog(dict(plan or {}), parent=parent).exec()


def apply_semantic_rename_plan(editor, plan: SemanticRenamePlan) -> None:
    cursor = QTextCursor(editor.document())
    cursor.beginEditBlock()
    try:
        for occurrence in reversed(plan.occurrences):
            cursor.setPosition(int(occurrence.start))
            cursor.setPosition(int(occurrence.end), QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(plan.new_name)
    finally:
        cursor.endEditBlock()
    if plan.occurrences:
        first = plan.occurrences[0]
        cursor.setPosition(int(first.start))
        cursor.setPosition(
            int(first.start) + len(plan.new_name),
            QTextCursor.MoveMode.KeepAnchor,
        )
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()


def _semantic_error_text(error: SemanticRenameError) -> str:
    if not error.code:
        return str(error)
    key = f"rename_symbol_error_{error.code}"
    translated = t(key)
    if translated == key:
        return str(error)
    try:
        return translated.format(**error.details)
    except (KeyError, ValueError):
        return translated
