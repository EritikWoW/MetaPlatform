from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication

from .launcher_window import LauncherWindow


def run() -> int:
    app = QApplication(sys.argv)

    w = LauncherWindow()
    w.show()

    return app.exec()
