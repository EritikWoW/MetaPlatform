from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QStackedLayout, QWidget

from src.ui_qt.widgets.svg_preview import SvgPreview


class PicturePreview(QWidget):
    """Preview widget that supports SVG (QSvgRenderer) and raster images."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._svg = SvgPreview(self)
        self._img = QLabel(self)
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setMinimumSize(120, 120)
        self._img.setScaledContents(False)

        self._stack = QStackedLayout(self)
        self._stack.addWidget(self._svg)
        self._stack.addWidget(self._img)
        self._stack.setCurrentWidget(self._svg)
        self.setLayout(self._stack)

        self._pix: QPixmap | None = None

    def set_svg_bytes(self, data: bytes) -> None:
        self._stack.setCurrentWidget(self._svg)
        self._svg.set_svg_bytes(data)

    def set_raster_bytes(self, data: bytes) -> None:
        pm = QPixmap()
        pm.loadFromData(data)
        self.set_pixmap(pm)

    def set_pixmap(self, pm: QPixmap | None) -> None:
        self._pix = pm
        self._stack.setCurrentWidget(self._img)
        self._rescale()

    def clear(self) -> None:
        self._pix = None
        self._img.setPixmap(QPixmap())
        self._stack.setCurrentWidget(self._svg)
        self._svg.set_svg_bytes(b"")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._stack.currentWidget() is self._img:
            self._rescale()

    def _rescale(self) -> None:
        if self._pix is None or self._pix.isNull():
            self._img.setPixmap(QPixmap())
            return
        target = self._img.size()
        pm = self._pix.scaled(target, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._img.setPixmap(pm)
