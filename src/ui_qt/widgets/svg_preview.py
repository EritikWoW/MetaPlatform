from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget


class SvgPreview(QWidget):
    """Lightweight SVG preview based on QSvgRenderer.

    - No WebEngine dependency.
    - Renders on a subtle checkered background.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._renderer = QSvgRenderer(self)
        self._ok = False
        self._last_error: str = ""
        self.setMinimumSize(240, 160)

    def set_svg_bytes(self, data: bytes) -> None:
        self._last_error = ""
        ba = QByteArray(data)
        self._ok = self._renderer.load(ba)
        if not self._ok:
            self._last_error = "Invalid SVG"
        self.update()

    def last_error(self) -> str:
        return self._last_error

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Checker background
        tile = 12
        pm = QPixmap(tile * 2, tile * 2)
        pm.fill(QColor(245, 245, 245))
        pp = QPainter(pm)
        pp.fillRect(0, 0, tile, tile, QColor(230, 230, 230))
        pp.fillRect(tile, tile, tile, tile, QColor(230, 230, 230))
        pp.end()
        p.fillRect(self.rect(), QBrush(pm))

        if not self._ok:
            p.setPen(QColor(120, 120, 120))
            p.drawText(self.rect().adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._last_error)
            p.end()
            return

        view_box = self._renderer.viewBoxF()
        if view_box.isNull() or view_box.width() <= 0 or view_box.height() <= 0:
            view_box = QRectF(0, 0, 100, 100)

        target = QRectF(self.rect().adjusted(8, 8, -8, -8))
        # Preserve aspect ratio
        scale = min(target.width() / view_box.width(), target.height() / view_box.height())
        w = view_box.width() * scale
        h = view_box.height() * scale
        x = target.x() + (target.width() - w) / 2
        y = target.y() + (target.height() - h) / 2
        dst = QRectF(x, y, w, h)

        self._renderer.render(p, dst)
        p.end()
