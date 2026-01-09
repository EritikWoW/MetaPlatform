# src/ui_qt/row_delegate.py
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle


class WholeRowHoverDelegate(QStyledItemDelegate):
    """
    Рисует hover/selected фон ЯВНО через painter.fillRect().
    Работает стабильно даже при QSS.
    Ожидает, что view (QTableView) имеет поле hovered_row (см. HoverTableView).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._hover_color = QColor(91, 91, 214, 56)   # rgba
        self._sel_color = QColor(91, 91, 214)         # rgb

    def paint(self, painter, option: QStyleOptionViewItem, index) -> None:
        # Копия option, чтобы безопасно править
        opt = QStyleOptionViewItem(option)

        # Убираем фокус-рамку
        opt.state &= ~QStyle.State_HasFocus

        # Определяем selected
        is_selected = bool(opt.state & QStyle.State_Selected)

        # Определяем hovered_row (берём из view)
        hovered_row = -1
        try:
            w = opt.widget  # обычно это viewport()
            view = w.parent() if w is not None else None  # viewport.parent() = QTableView
            if view is not None and hasattr(view, "hovered_row"):
                hovered_row = int(getattr(view, "hovered_row"))
        except Exception:
            hovered_row = -1

        is_hover = (index.row() == hovered_row)

        # Рисуем фон САМИ (так QSS не “съест” подсветку)
        if is_selected:
            painter.fillRect(opt.rect, QBrush(self._sel_color))
        elif is_hover:
            painter.fillRect(opt.rect, QBrush(self._hover_color))

        # Чтобы Qt не рисовал свой фон поверх/вместо нашего:
        opt.backgroundBrush = Qt.NoBrush

        super().paint(painter, opt, index)
