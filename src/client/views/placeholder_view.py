from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.ui_qt.i18n import t


class PlaceholderView(QWidget):
    def __init__(self, *, title: str) -> None:
        super().__init__()
        self.title = title

        l = QVBoxLayout(self)
        l.setContentsMargins(16, 16, 16, 16)
        l.setSpacing(12)

        h = QLabel(self.title, self)
        h.setStyleSheet("font-size: 12pt; font-weight: 700;")
        l.addWidget(h)

        msg = QLabel(t("client_view_not_implemented"), self)
        msg.setWordWrap(True)
        msg.setStyleSheet("color: rgba(15,23,42,0.70);")
        msg.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        l.addWidget(msg)
        l.addStretch(1)
