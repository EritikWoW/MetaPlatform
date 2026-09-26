from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.dsl.api import parse_dsl
from src.ui_qt.i18n import t


@dataclass(frozen=True, slots=True)
class DslEditorResult:
    """Result from the DSL editor dialog."""

    text: str
    language: str


class DslEditorDialog(QDialog):
    """Small DSL editor for parsing/validation.

    This is an MVP tool meant to speed up DSL development. It does not apply
    changes to configuration yet.
    """

    def __init__(self, parent=None, initial_text: str = "", initial_language: str = "uk") -> None:
        super().__init__(parent)
        self.setWindowTitle(t("dsl_editor_title"))
        self.setModal(True)
        self.resize(980, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        top = QWidget(self)
        top_l = QGridLayout(top)
        top_l.setContentsMargins(0, 0, 0, 0)
        top_l.setHorizontalSpacing(10)
        top_l.setVerticalSpacing(6)

        lbl_lang = QLabel(t("dsl_editor_language"), top)
        self.cmb_lang = QComboBox(top)
        self.cmb_lang.addItem("UA", "uk")
        self.cmb_lang.addItem("EN", "en")
        idx = 0 if initial_language == "uk" else 1
        self.cmb_lang.setCurrentIndex(idx)

        self.btn_parse = QPushButton(t("dsl_editor_parse"), top)
        self.btn_parse.clicked.connect(self._on_parse)

        self.btn_validate = QPushButton(t("dsl_editor_validate"), top)
        self.btn_validate.clicked.connect(self._on_parse)

        self.btn_apply = QPushButton(t("dsl_editor_apply"), top)
        self.btn_apply.setEnabled(False)
        self.btn_apply.setToolTip(t("dsl_editor_apply_hint"))

        top_l.addWidget(lbl_lang, 0, 0)
        top_l.addWidget(self.cmb_lang, 0, 1)
        top_l.addWidget(self.btn_parse, 0, 2)
        top_l.addWidget(self.btn_validate, 0, 3)
        top_l.addWidget(self.btn_apply, 0, 4)
        top_l.setColumnStretch(5, 1)
        root.addWidget(top)

        # Editor + diagnostics
        mid = QWidget(self)
        mid_l = QHBoxLayout(mid)
        mid_l.setContentsMargins(0, 0, 0, 0)
        mid_l.setSpacing(10)

        self.txt_source = QTextEdit(mid)
        self.txt_source.setAcceptRichText(False)
        self.txt_source.setLineWrapMode(QTextEdit.NoWrap)
        self.txt_source.setPlainText(initial_text)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.txt_source.setFont(mono)
        self.txt_source.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.txt_diag = QPlainTextEdit(mid)
        self.txt_diag.setReadOnly(True)
        self.txt_diag.setFont(mono)
        self.txt_diag.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.txt_diag.setMinimumWidth(360)
        self.txt_diag.setPlaceholderText(t("dsl_editor_diag_placeholder"))

        mid_l.addWidget(self.txt_source, 3)
        mid_l.addWidget(self.txt_diag, 2)
        root.addWidget(mid, 1)

        # Buttons
        bb = QDialogButtonBox(QDialogButtonBox.Close, self)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        # Initial parse (optional)
        if initial_text.strip():
            self._on_parse()

    def result_data(self) -> DslEditorResult:
        """Return current text/language selection."""

        return DslEditorResult(text=self.txt_source.toPlainText(), language=self._language())

    def _language(self) -> str:
        return str(self.cmb_lang.currentData())

    def _on_parse(self) -> None:
        src = self.txt_source.toPlainText()
        lang = self._language()

        try:
            res = parse_dsl(src, language=lang)  # type: ignore[arg-type]
        except Exception as e:
            self.txt_diag.setPlainText(f"{t('dsl_editor_internal_error')}\n\n{e}")
            return

        lines: list[str] = []
        errors = 0
        warnings = 0
        for d in res.diagnostics:
            prefix = "ERROR" if d.severity == "error" else "WARN"
            if d.severity == "error":
                errors += 1
            else:
                warnings += 1
            lines.append(f"{prefix}  L{d.span.line}:C{d.span.col}  {d.message}")

        if not lines:
            lines.append(t("dsl_editor_ok"))

        footer = t("dsl_editor_summary").format(errors=errors, warnings=warnings)
        lines.append("")
        lines.append(footer)
        self.txt_diag.setPlainText("\n".join(lines))
