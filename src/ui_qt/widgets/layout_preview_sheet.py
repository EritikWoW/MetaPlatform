from __future__ import annotations

from PySide6.QtGui import QBrush, QColor, QPalette, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem


class _LayoutSheetDelegate(QStyledItemDelegate):
    def paint(self, painter, option: QStyleOptionViewItem, index) -> None:  # type: ignore[override]
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        has_focus = bool(opt.state & QStyle.StateFlag.State_HasFocus)
        current = False
        parent = self.parent()
        try:
            current = bool(parent is not None and getattr(parent, "currentIndex")().row() == index.row() and getattr(parent, "currentIndex")().column() == index.column())
        except Exception:
            current = False

        owner = None
        try:
            parent = self.parent()
            owner = parent.parentWidget() if parent is not None else None
        except Exception:
            owner = None

        base_brush = QBrush(QColor("#FFFFFF"))
        border_pen = QPen(QColor("#E5E7EB"))
        border_pen.setWidth(1)
        if owner is not None and hasattr(owner, "_cell_paint_state"):
            try:
                base_color, border_color, border_width = owner._cell_paint_state(  # type: ignore[attr-defined]
                    index.row(),
                    index.column(),
                    selected=selected,
                    current=current or has_focus,
                )
                base_brush = QBrush(base_color)
                border_pen = QPen(border_color)
                border_pen.setWidth(max(1, int(border_width)))
            except Exception:
                pass

        opt.palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        opt.palette.setColor(QPalette.ColorRole.Text, QColor("#111827"))
        opt.palette.setColor(QPalette.ColorRole.Highlight, QColor("#BBD7FF"))
        opt.palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0B1020"))
        opt.backgroundBrush = base_brush

        super().paint(painter, opt, index)

        painter.save()
        rect = option.rect.adjusted(0, 0, -1, -1)
        painter.setPen(border_pen)
        painter.drawRect(rect)
        painter.restore()
