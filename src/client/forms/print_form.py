"""src.client.forms.print_form — Print preview widget.

PrintPreviewForm  — renders HTML preview with toolbar (Print / Save PDF)
                    Uses QWebEngineView if available, falls back to QTextBrowser.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t


class PrintPreviewForm(QWidget):
    """HTML print preview with Print and Save PDF buttons.

    Usage:
        form = PrintPreviewForm(db=db, manifest_rows=rows)
        html = engine.render_document("Invoice", guid)
        form.load_html(html, title="Invoice #001")
        # Dock or open as sub-window
    """

    def __init__(self, *, db=None, manifest_rows: list,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db    = db
        self._mrows = manifest_rows
        self._html  = ""
        self._title = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Toolbar
        bar = QHBoxLayout()
        btn_print = QPushButton(t("print_btn_print"))
        btn_print.clicked.connect(self._on_print)
        bar.addWidget(btn_print)

        btn_pdf = QPushButton(t("print_btn_save_pdf"))
        btn_pdf.clicked.connect(self._on_save_pdf)
        bar.addWidget(btn_pdf)

        btn_refresh = QPushButton(t("client_btn_refresh"))
        btn_refresh.clicked.connect(self._on_refresh)
        bar.addWidget(btn_refresh)

        bar.addStretch()
        root.addLayout(bar)

        # View — try WebEngine, fall back to TextBrowser
        self._view_widget = self._create_view()
        root.addWidget(self._view_widget, 1)

    # ── public ──────────────────────────────────────────────────────────────

    def load_html(self, html_text: str, title: str = "") -> None:
        self._html  = html_text
        self._title = title
        self._render()

    def load_document(self, doc_name: str, doc_guid: str) -> None:
        """Load and render a document using PrintEngine."""
        try:
            from src.runtime.print_engine import PrintEngine
            engine = PrintEngine(self._db, self._mrows)
            html_text = engine.render_document(doc_name, doc_guid)
            self.load_html(html_text, title=f"{doc_name} {doc_guid[:8]}")
        except Exception as e:
            self.load_html(
                f"<html><body><p style='color:red'>Error: {e}</p></body></html>"
            )

    def load_form(self, form_name: str,
                  context: Optional[Dict[str, Any]] = None) -> None:
        """Render a named print form with the given context."""
        try:
            from src.runtime.print_engine import PrintEngine
            engine = PrintEngine(self._db, self._mrows)
            html_text = engine.render(form_name, context or {})
            self.load_html(html_text, title=form_name)
        except Exception as e:
            self.load_html(
                f"<html><body><p style='color:red'>Error: {e}</p></body></html>"
            )

    # ── private ─────────────────────────────────────────────────────────────

    def _create_view(self) -> QWidget:
        """Create QWebEngineView if available, else QTextBrowser."""
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            view = QWebEngineView()
            view.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self._use_webengine = True
            return view
        except ImportError:
            from PySide6.QtWidgets import QTextBrowser
            view = QTextBrowser()
            view.setOpenLinks(False)
            self._use_webengine = False
            return view

    def _render(self) -> None:
        if self._use_webengine:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            assert isinstance(self._view_widget, QWebEngineView)
            self._view_widget.setHtml(self._html,
                                      QUrl("about:blank"))
        else:
            from PySide6.QtWidgets import QTextBrowser
            assert isinstance(self._view_widget, QTextBrowser)
            self._view_widget.setHtml(self._html)

    def _on_print(self) -> None:
        if self._use_webengine:
            try:
                from PySide6.QtPrintSupport import QPrintDialog, QPrinter
                from PySide6.QtWebEngineWidgets import QWebEngineView
                printer  = QPrinter(QPrinter.PrinterMode.HighResolution)
                dialog   = QPrintDialog(printer, self)
                if dialog.exec() == QPrintDialog.DialogCode.Accepted:
                    page = self._view_widget.page()
                    page.print(printer, lambda ok: None)
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))
        else:
            try:
                from PySide6.QtPrintSupport import QPrintDialog, QPrinter
                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                dialog  = QPrintDialog(printer, self)
                if dialog.exec() == QPrintDialog.DialogCode.Accepted:
                    from PySide6.QtWidgets import QTextBrowser
                    assert isinstance(self._view_widget, QTextBrowser)
                    self._view_widget.print_(printer)
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))

    def _on_save_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, t("print_save_pdf"), self._title or "document", "PDF (*.pdf)"
        )
        if not path:
            return
        if not path.endswith(".pdf"):
            path += ".pdf"
        if self._use_webengine:
            try:
                page = self._view_widget.page()
                page.printToPdf(path)
                QMessageBox.information(self, t("print_save_ok"), path)
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))
        else:
            try:
                from PySide6.QtPrintSupport import QPrinter
                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                printer.setOutputFileName(path)
                from PySide6.QtWidgets import QTextBrowser
                assert isinstance(self._view_widget, QTextBrowser)
                self._view_widget.print_(printer)
                QMessageBox.information(self, t("print_save_ok"), path)
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))

    def _on_refresh(self) -> None:
        if self._html:
            self._render()
