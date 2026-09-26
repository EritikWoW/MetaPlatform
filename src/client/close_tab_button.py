"""close_tab_button.py — кнопка закрытия вкладки с иконкой ✕ нарисованной через QPainter."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QToolButton, QWidget

from src.ui_qt.i18n import t


def _make_x_pixmap(size: int, color: QColor) -> QPixmap:
    """Рисует иконку ✕ программно — никаких файлов, никакого PNG."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)

    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(color)
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)

    m = size * 0.22          # отступ от края
    e = size - m             # правый/нижний край
    p.drawLine(int(m), int(m), int(e), int(e))
    p.drawLine(int(e), int(m), int(m), int(e))
    p.end()
    return px


def make_close_button(parent: QWidget | None = None) -> QToolButton:
    """QToolButton с нарисованной иконкой ✕ для вкладки."""
    SZ = 14

    px_normal = _make_x_pixmap(SZ, QColor("#94A3B8"))   # серая
    px_hover  = _make_x_pixmap(SZ, QColor("#0F172A"))   # тёмная при hover

    icon = QIcon()
    icon.addPixmap(px_normal, QIcon.Mode.Normal)
    icon.addPixmap(px_hover,  QIcon.Mode.Active)

    btn = QToolButton(parent)
    btn.setIcon(icon)
    btn.setIconSize(QSize(SZ, SZ))
    btn.setFixedSize(20, 20)
    btn.setAutoRaise(True)
    btn.setToolTip(t("btn_close"))
    btn.setStyleSheet("""
        QToolButton {
            border: none;
            border-radius: 4px;
            background: transparent;
            padding: 0;
            margin: 2px;
        }
        QToolButton:hover  { background: rgba(0,0,0,0.10); }
        QToolButton:pressed { background: rgba(0,0,0,0.20); }
    """)
    return btn
