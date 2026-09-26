from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QWidget

from src.ui_qt.widgets.current_page_stacked_widget import CurrentPageStackedWidget


class _SizedPage(QWidget):
    def __init__(self, width: int, height: int = 240) -> None:
        super().__init__()
        self._hint = QSize(width, height)

    def sizeHint(self) -> QSize:
        return self._hint

    def minimumSizeHint(self) -> QSize:
        return self._hint


def test_current_page_stacked_widget_uses_active_page_size_only() -> None:
    app = QApplication.instance() or QApplication([])
    stack = CurrentPageStackedWidget()
    small = _SizedPage(240)
    large = _SizedPage(960)
    stack.addWidget(small)
    stack.addWidget(large)

    stack.setCurrentWidget(small)
    app.processEvents()
    assert stack.minimumSizeHint().width() == 240
    assert stack.sizeHint().width() == 240

    stack.setCurrentWidget(large)
    app.processEvents()
    assert stack.minimumSizeHint().width() == 960
    assert stack.sizeHint().width() == 960

    stack.setCurrentWidget(small)
    app.processEvents()
    assert stack.minimumSizeHint().width() == 240
    assert stack.sizeHint().width() == 240
