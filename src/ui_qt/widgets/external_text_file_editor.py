from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPlainTextEdit,
    QMessageBox,
    QFileDialog,
)

from src.ui_qt.i18n import t


@dataclass
class ExternalTextFileState:
    path: Optional[Path] = None
    is_dirty: bool = False


class ExternalTextFileEditorWidget(QWidget):
    """External text file editor (disk-backed).

    Purpose:
      - support File/Edit actions (Open/Save/Print/Undo/Copy...) in Configurator
        even when user edits plain files, not only mpdb-backed assets.
      - behave like a classic document editor.
    """

    dirtyChanged = Signal(bool)

    def __init__(self, *, path: Optional[Path] = None, title: str = "") -> None:
        super().__init__()
        self._state = ExternalTextFileState(path=path)
        self._explicit_title = str(title or "").strip()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._edit = QPlainTextEdit(self)
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        self._edit.setFont(f)
        self._edit.setTabStopDistance(4 * self._edit.fontMetrics().horizontalAdvance(" "))
        self._edit.textChanged.connect(self._on_text_changed)

        lay.addWidget(self._edit, 1)

        if self._state.path is not None:
            self.reload()

    def title(self) -> str:
        if self._explicit_title:
            return self._explicit_title
        if self._state.path is not None:
            return self._state.path.name
        return t("doc_untitled")

    def file_path(self) -> Optional[Path]:
        return self._state.path

    def editor(self) -> QPlainTextEdit:
        return self._edit

    def is_dirty(self) -> bool:
        return bool(self._state.is_dirty)

    def set_text(self, text: str) -> None:
        self._edit.blockSignals(True)
        self._edit.setPlainText(text or "")
        self._edit.blockSignals(False)
        self._set_dirty(False)

    def text(self) -> str:
        return self._edit.toPlainText()

    def reload(self) -> None:
        p = self._state.path
        if p is None:
            return
        try:
            data = p.read_text(encoding="utf-8")
        except Exception:
            data = p.read_text(encoding="utf-8", errors="replace")
        self.set_text(data)

    def reload_from_vm(self) -> None:
        self.reload()

    def save(self) -> bool:
        """Save to current path. If path is missing -> Save As."""
        if self._state.path is None:
            return self.save_as()
        try:
            self._state.path.write_text(self.text(), encoding="utf-8")
            self._set_dirty(False)
            return True
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), f"{t('file_save_failed')}\n\n{e}")
            return False

    def save_as(self) -> bool:
        path, _flt = QFileDialog.getSaveFileName(
            self,
            t("dlg_save_as_title"),
            str(self._state.path) if self._state.path else "",
            t("file_filter_text"),
        )
        if not path:
            return False
        self._state.path = Path(path)
        self._explicit_title = ""
        return self.save()

    # ---- internals ----

    def _set_dirty(self, dirty: bool) -> None:
        dirty = bool(dirty)
        if self._state.is_dirty == dirty:
            return
        self._state.is_dirty = dirty
        self.dirtyChanged.emit(dirty)

    def _on_text_changed(self) -> None:
        self._set_dirty(True)

    def closeEvent(self, event) -> None:
        if self.is_dirty():
            res = QMessageBox.question(
                self,
                t("dlg_unsaved_title"),
                t("dlg_unsaved_text"),
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if res == QMessageBox.StandardButton.Save:
                if self.save():
                    event.accept()
                else:
                    event.ignore()
                    return
            elif res == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
                return
        super().closeEvent(event)
