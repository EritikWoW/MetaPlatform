from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.ui_qt.widgets.module_browser import ModuleBrowserWidget


def test_module_browser_reload_from_vm_aliases_refresh() -> None:
    app = QApplication.instance() or QApplication([])

    class _Browser(ModuleBrowserWidget):
        def __init__(self) -> None:
            self.refresh_calls = 0
            super().__init__(vm=None)

        def _populate(self) -> None:
            self.refresh_calls += 1

    widget = _Browser()
    widget.reload_from_vm()

    assert widget.refresh_calls >= 2
    assert app is not None
