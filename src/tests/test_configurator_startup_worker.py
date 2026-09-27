import threading
import time

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src.configurator import configurator_app


def test_startup_open_worker_runs_runtime_open_off_gui_thread(monkeypatch):
    app = QApplication.instance() or QApplication([])
    gui_thread_id = threading.get_ident()
    called_from = []
    result = object()
    ticks = []

    class FakeService:
        def open_db(self, runtime_url, db_uid, *, db_path):
            called_from.append((threading.get_ident(), runtime_url, db_uid, db_path))
            time.sleep(0.15)
            return result

    monkeypatch.setattr(configurator_app, "ConfiguratorService", FakeService)
    worker = configurator_app._StartupOpenWorker(
        "http://127.0.0.1:8875", "db-uid", "F:/TestBD/MetaDB/metabase.mpdb"
    )
    opened = []
    worker.opened.connect(lambda service, open_result: opened.append((service, open_result)))
    loop = QEventLoop()
    worker.opened.connect(lambda *_: loop.quit())
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()

    worker.start()
    loop.exec()
    assert worker.wait(5000)
    timer.stop()

    assert len(called_from) == 1
    thread_id, runtime_url, db_uid, db_path = called_from[0]
    assert thread_id != gui_thread_id
    assert len(ticks) >= 2
    assert (runtime_url, db_uid, db_path) == (
        "http://127.0.0.1:8875",
        "db-uid",
        "F:/TestBD/MetaDB/metabase.mpdb",
    )
    assert opened and opened[0][1] is result
