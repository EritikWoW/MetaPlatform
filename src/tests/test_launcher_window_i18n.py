from PySide6.QtWidgets import QApplication

from src.platform.db_catalog import DbEntry
from src.ui_qt import i18n as i18n_mod
from src.ui_qt import launcher_window as launcher_module
from src.ui_qt.launcher_window import LauncherWindow


def test_launcher_window_uses_current_lang_for_texts_and_selector(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    prev_path = i18n_mod._SETTINGS_PATH
    prev_lang = i18n_mod.get_lang()
    try:
        i18n_mod._SETTINGS_PATH = tmp_path / "settings.json"
        i18n_mod._lang = "uk"
        i18n_mod._inited = True
        widget = LauncherWindow()
        widget.show()
        app.processEvents()

        assert widget.lbl_subtitle.text() == "Вибір бази даних"
        assert widget.lbl_list.text() == "Підключені бази:"
        assert widget.btn_client.text() == "Клієнт"
        assert widget.cmb_lang.currentText() == "UA"
    finally:
        i18n_mod._SETTINGS_PATH = prev_path
        i18n_mod._lang = prev_lang
        i18n_mod._inited = True


def test_open_db_via_runtime_reports_unavailable_runtime(monkeypatch) -> None:
    warnings: list[tuple[object, str, str]] = []

    class FakeLauncher:
        def _ensure_runtime(self, runtime_url: str, *, autostart: bool) -> bool:
            assert runtime_url == "http://127.0.0.1:8765"
            assert autostart is False
            return False

    monkeypatch.setattr(
        launcher_module.QMessageBox,
        "warning",
        lambda parent, title, message: warnings.append((parent, title, message)),
    )
    launcher = FakeLauncher()
    entry = DbEntry(
        name="Unavailable",
        runtime_url="http://127.0.0.1:8765",
        autostart=False,
    )

    result = LauncherWindow._open_db_via_runtime(launcher, entry)

    assert result is None
    assert warnings == [
        (launcher, i18n_mod.t("dlg_config_title"), i18n_mod.t("dlg_runtime_unavailable"))
    ]
