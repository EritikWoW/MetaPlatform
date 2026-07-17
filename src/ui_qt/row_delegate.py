# src/ui_qt/row_delegate.py
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle


class WholeRowHoverDelegate(QStyledItemDelegate):
    """
    Рисует hover/selected фон явно через painter.fillRect().
    Текст НЕ инвертируется и НЕ выделяется — подсвечивается только фон строки.
    """

    _HOVER_COLOR = QColor(91, 91, 214, 40)
    _SEL_COLOR   = QColor(219, 234, 254)   # #DBEAFE — светло-синий фон, текст остаётся тёмным
    _TEXT_COLOR  = QColor(15, 23, 42)      # #0F172A

    def paint(self, painter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)

        # Убираем фокус-рамку
        opt.state &= ~QStyle.State_HasFocus

        is_selected = bool(opt.state & QStyle.State_Selected)

        # hover row
        hovered_row = -1
        try:
            w = opt.widget
            view = w.parent() if w is not None else None
            if view is not None and hasattr(view, "hovered_row"):
                hovered_row = int(getattr(view, "hovered_row"))
        except Exception:
            pass

        is_hover = (index.row() == hovered_row)

        # Рисуем фон сами — выделение имеет приоритет над hover
        if is_selected:
            painter.fillRect(opt.rect, QBrush(self._SEL_COLOR))
        elif is_hover:
            painter.fillRect(opt.rect, QBrush(self._HOVER_COLOR))

        # КЛЮЧЕВОЕ: снимаем State_Selected до вызова super().paint()
        # Это мешает Qt красить фон и инвертировать цвет текста
        opt.state &= ~QStyle.State_Selected
        opt.backgroundBrush = Qt.NoBrush

        # Фиксируем цвет текста — всегда тёмный, без инверсии
        opt.palette.setColor(opt.palette.ColorRole.Text, self._TEXT_COLOR)
        opt.palette.setColor(opt.palette.ColorRole.HighlightedText, self._TEXT_COLOR)

        super().paint(painter, opt, index)
