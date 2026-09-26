from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QStackedWidget, QWidget


class CurrentPageStackedWidget(QStackedWidget):
    """Stack that reports geometry based on the active page only.

    Default QStackedWidget aggregates minimumSizeHint/sizeHint across all pages.
    That is a poor fit for shared dock panels where one oversized page can make
    the whole dock impossible to shrink even after switching back to a compact
    page.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def sizeHint(self) -> QSize:
        page = self.currentWidget()
        if page is None:
            return super().sizeHint()
        minimum = page.minimumSizeHint()
        if minimum.isValid():
            return minimum
        hint = page.sizeHint()
        return hint if hint.isValid() else super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        page = self.currentWidget()
        if page is None:
            return super().minimumSizeHint()
        hint = page.minimumSizeHint()
        return hint if hint.isValid() else super().minimumSizeHint()
