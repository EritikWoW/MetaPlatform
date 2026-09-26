from PySide6.QtWidgets import QApplication

from src.client.client_window import ClientWindow


def test_client_window_shim_import_and_init() -> None:
    app = QApplication.instance() or QApplication([])
    win = ClientWindow(runtime=None, db_path=None)

    assert win.centralWidget() is not None
    assert win.windowTitle()
    assert app is not None
