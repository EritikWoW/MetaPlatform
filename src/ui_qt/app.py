from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .launcher_window import LauncherWindow

def run(debug_ui: bool = False) -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    w = LauncherWindow(debug_ui=debug_ui)
    w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    w.show()

    code = app.exec()
    raise SystemExit(code)