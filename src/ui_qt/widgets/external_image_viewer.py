from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea, QMessageBox

from src.ui_qt.i18n import t


@dataclass
class ExternalImageState:
    path: Optional[Path] = None


class ExternalImageViewerWidget(QWidget):
    """Very small image viewer for external files."""

    def __init__(self, *, path: Path, title: str = ""):
        super().__init__()
        self._state = ExternalImageState(path=Path(path))
        self._explicit_title = str(title or "").strip()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        sc = QScrollArea(self)
        sc.setWidgetResizable(True)
        sc.setWidget(self._label)
        root.addWidget(sc, 1)

        self.reload()

    def title(self) -> str:
        if self._explicit_title:
            return self._explicit_title
        return self._state.path.name if self._state.path else t("doc_untitled")

    def reload(self) -> None:
        p = self._state.path
        if p is None:
            return
        pm = QPixmap(str(p))
        if pm.isNull():
            QMessageBox.warning(self, t("dlg_error_title"), t("file_open_failed"))
            return
        self._label.setPixmap(pm)

    def reload_from_vm(self) -> None:
        self.reload()
