from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from src.configurator.application.service import ConfiguratorService
from src.configurator.configurator_window import ConfiguratorWindow
from src.runtime.gateway import GatewayDb, RuntimeGateway
from src.ui_qt.viewmodels.configurator_vm_runtime import ConfiguratorVmRuntimeMixin


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "configurator.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(
        "src.configurator.configurator_main_window.QSettings", lambda *_args: settings
    )
    view = ConfiguratorWindow(runtime_url="http://127.0.0.1:1", db_uid="shutdown-test")
    yield view
    view._vm = None
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


class _Vm(ConfiguratorVmRuntimeMixin):
    def __init__(self, service):
        self._service = service
        self.db = service.require_db()
        self._runtime_refresh_epoch = 1
        self._runtime_refresh_in_flight = True


def _service_for(gateway):
    service = ConfiguratorService()
    service._gw = gateway
    service._db = GatewayDb(gateway)
    service._db_uid = "shutdown-test"
    return service


def test_session_close_has_short_timeout_and_invalidates_gateway_first(monkeypatch):
    gateway = RuntimeGateway("http://127.0.0.1:1")
    gateway.session_id = "closing-session"
    calls = []

    def call(action, payload, *, timeout=30):
        calls.append((action, payload, timeout))
        assert timeout <= 1.0
        assert gateway.session_id is None
        with pytest.raises(RuntimeError, match="closed"):
            gateway.ensure_session()
        return {"closed": True}

    monkeypatch.setattr(gateway, "_call", call)
    assert gateway.close_session() is True
    assert gateway.close_session() is False
    assert calls == [("session.close", {"session_id": "closing-session"}, 1.0)]
    with pytest.raises(RuntimeError, match="closed"):
        gateway.manifest_info()


def test_service_detaches_before_close_even_when_cleanup_fails():
    service = ConfiguratorService()

    def close():
        assert service._db is None
        assert service._gw is None
        assert service.db_uid == ""
        raise OSError("close failed")

    service._db = SimpleNamespace(close=close)
    service._gw = object()
    service._db_uid = "shutdown-test"
    with pytest.raises(OSError, match="close failed"):
        service.close()
    service.close()


def test_close_window_does_not_wait_for_stalled_runtime(window):
    received = []
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(request)
            release.wait(3.0)
            body = b'{"status":"ok","data":{"closed":true}}'
            try:
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    server_thread.start()
    gateway = RuntimeGateway(f"http://127.0.0.1:{server.server_port}")
    gateway.session_id = "closing-session"
    service = _service_for(gateway)
    vm = _Vm(service)
    window._vm = vm
    try:
        started = time.monotonic()
        accepted = window.close()
        elapsed = time.monotonic() - started
        assert accepted is True
        assert elapsed < 1.8, f"closeEvent blocked for {elapsed:.3f}s"
        assert vm.db is None
        assert service._db is None
        assert vm._runtime_refresh_epoch == 2
        assert vm._runtime_refresh_in_flight is False
        assert [request["action"] for request in received] == ["session.close"]
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        server_thread.join(2)


@pytest.mark.parametrize("reason", ["import", "editor", "cancel", "failed_save"])
def test_rejected_window_close_preserves_connection(window, monkeypatch, reason):
    calls = []
    window._vm = SimpleNamespace(
        close_db=lambda: calls.append("close"),
        on_save=lambda: calls.append("save"),
        _editor=SimpleNamespace(state=SimpleNamespace(is_dirty=True)),
    )
    if reason == "import":
        window._import_thread = SimpleNamespace(isRunning=lambda: True)
        monkeypatch.setattr(window, "show_warning", lambda *_args: None)
    elif reason == "editor":
        window._open_windows = {
            "dirty": SimpleNamespace(widget=lambda: SimpleNamespace(confirm_close=lambda: False))
        }
    else:
        window._is_dirty = True
        response = (
            QMessageBox.StandardButton.Save if reason == "failed_save"
            else QMessageBox.StandardButton.Cancel
        )
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: response)

    assert window.close() is False
    assert "close" not in calls


def test_closing_parent_with_active_diagnostics_does_not_abort_process():
    code = """
import threading
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QMainWindow
from src.ui_qt.widgets.workspace_problems_panel import WorkspaceProblemsPanel

app = QApplication([])
window = QMainWindow()
window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
panel = WorkspaceProblemsPanel(window)
window.setCentralWidget(panel)
started = threading.Event()
release = threading.Event()
def loader():
    started.set()
    release.wait(20)
    return []
panel.set_loader(loader)
assert panel.refresh_async()
assert started.wait(2)
assert window.close()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
app.processEvents()
print('closed-with-active-diagnostics', flush=True)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=8,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "closed-with-active-diagnostics" in result.stdout

def test_close_does_not_wait_for_or_resurrect_inflight_session_creation(monkeypatch):
    import threading
    from src.runtime.gateway import RuntimeGateway

    gateway = RuntimeGateway("http://not-used")
    entered, release = threading.Event(), threading.Event()
    closed, errors = [], []
    def call(action, payload, **kwargs):
        if action == "session.create":
            entered.set()
            assert release.wait(2)
            return {"session_id": "late-session"}
        closed.append(payload["session_id"])
        assert kwargs["timeout"] == 1.0
        return {"closed": True}
    monkeypatch.setattr(gateway, "_call", call)
    def ensure():
        try:
            gateway.ensure_session()
        except RuntimeError as error:
            errors.append(str(error))
    worker = threading.Thread(target=ensure, daemon=True)
    worker.start()
    assert entered.wait(1)
    try:
        assert gateway.close_session() is False
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    assert gateway.session_id is None
    assert closed == ["late-session"]
    assert errors == ["Runtime gateway is closed"]
