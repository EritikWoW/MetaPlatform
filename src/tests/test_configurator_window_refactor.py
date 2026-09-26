from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QWidget
from types import SimpleNamespace

from src.configurator.configurator_window import ConfiguratorWindow, NodeInfo
from src.ui_qt.i18n import t

class _WidePropsPage(QWidget):
    def minimumSizeHint(self):
        return QSize(960, 240)


def test_configurator_window_shim_exports_real_class_and_init_smoke():
    app = QApplication.instance() or QApplication([])
    assert NodeInfo.__name__ == "NodeInfo"
    w = ConfiguratorWindow(runtime_url="http://127.0.0.1:8765", db_uid="demo")
    assert w.windowTitle()
    assert hasattr(w, "open_object_tab")
    assert hasattr(w, "_build_menu")
    w.deleteLater()


def test_configurator_window_exposes_direct_1cd_import_action():
    app = QApplication.instance() or QApplication([])
    w = ConfiguratorWindow(runtime_url="http://127.0.0.1:8765", db_uid="demo")
    try:
        assert w.act_import_1cd.objectName() == "tb_import_1cd"
        assert w.act_import_1cd in w._tb_main.actions()
        assert w.act_import_1cd.isVisible()

        cfg_menu = None
        for action in w.menuBar().actions():
            menu = action.menu()
            if menu is not None and menu.title() == t("menu_configuration"):
                cfg_menu = menu
                break
        assert cfg_menu is not None
        assert any(action.text() == t("cfg_import_1cd") for action in cfg_menu.actions())
    finally:
        w.deleteLater()


def test_configurator_window_exposes_lazy_workspace_problems_dock():
    app = QApplication.instance() or QApplication([])
    w = ConfiguratorWindow(runtime_url="http://127.0.0.1:8765", db_uid="demo")
    try:
        assert w.dock_problems.objectName() == "dock_workspace_problems"
        assert w.dock_problems.isVisible() is False
        assert w.act_view_problems.isCheckable()
        assert w.act_view_problems.shortcut().toString() == "Ctrl+Alt+P"
        assert w.act_next_problem.shortcut().toString() == "F8"
        assert w.act_previous_problem.shortcut().toString() == "Shift+F8"
        assert w.workspace_problems.state(include_diagnostics=False)["count"] == 0
    finally:
        w.deleteLater()


def test_workspace_problems_loader_waits_for_background_index(monkeypatch):
    QApplication.instance() or QApplication([])
    w = ConfiguratorWindow(runtime_url="http://127.0.0.1:8765", db_uid="demo")
    statuses = iter(
        [
            {"ready": False, "generation": 0},
            {"ready": True, "generation": 7},
            {"ready": True, "generation": 7},
        ]
    )
    diagnostics_calls: list[int] = []
    service = SimpleNamespace(
        get_workspace_semantic_index_info=lambda: next(statuses),
        get_workspace_semantic_diagnostics=lambda *, limit: (
            diagnostics_calls.append(limit)
            or [{"code": "lexer_partial"}]
        ),
    )
    w._vm = SimpleNamespace(_service=service)
    monkeypatch.setattr(
        "src.configurator.configurator_main_window.time.sleep",
        lambda _seconds: None,
    )
    try:
        result = w._load_workspace_problems()
    finally:
        w.deleteLater()

    assert result == {
        "generation": 7,
        "diagnostics": [{"code": "lexer_partial"}],
    }
    assert diagnostics_calls == [5000]


def test_configurator_window_clamps_properties_dock_width_to_compact_range():
    app = QApplication.instance() or QApplication([])
    w = ConfiguratorWindow(runtime_url="http://127.0.0.1:8765", db_uid="demo")
    page = _WidePropsPage()
    w._props_stack.addWidget(page)
    w._props_stack.setCurrentWidget(page)
    w.resize(1800, 900)
    w.show()
    app.processEvents()

    w._normalize_props_dock_width(force=True)
    app.processEvents()

    assert w.dock_props.width() <= w._PROPS_DOCK_MAX_COMPACT_WIDTH + 40
    assert w.dock_props.maximumWidth() >= 500000
    before = w.dock_props.width()
    w.resizeDocks([w.dock_props], [520], Qt.Orientation.Horizontal)
    app.processEvents()
    assert w.dock_props.maximumWidth() >= 500000
    assert w.dock_props.width() >= before
    w.close()


def test_configurator_window_soft_clamps_absurdly_wide_properties_dock():
    app = QApplication.instance() or QApplication([])
    w = ConfiguratorWindow(runtime_url="http://127.0.0.1:8765", db_uid="demo")
    page = _WidePropsPage()
    w._props_stack.addWidget(page)
    w._props_stack.setCurrentWidget(page)
    w.resize(1800, 900)
    w.show()
    app.processEvents()

    w._normalize_props_dock_width(force=True)
    app.processEvents()
    w.resizeDocks([w.dock_props], [820], Qt.Orientation.Horizontal)
    app.processEvents()
    assert w.dock_props.width() >= 600

    w._normalize_props_dock_width(force=False)
    app.processEvents()

    assert w.dock_props.width() <= int(w.width() * 0.44) + 40
    w.close()
