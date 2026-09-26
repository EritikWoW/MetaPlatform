from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .runtime_admin_window import RuntimeAdminWindow
from .theme import apply_dark_theme, set_app_icon


def run() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    apply_dark_theme(app)
    set_app_icon(app)

    w = RuntimeAdminWindow()
    w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    w.show()

    code = app.exec()
    raise SystemExit(code)
