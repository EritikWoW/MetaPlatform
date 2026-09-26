from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.ui_qt.widgets.load_config_dialog import LoadConfigDialog


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_load_config_dialog_can_start_in_1cd_mode_and_enable_data_import():
    _ensure_app()
    dlg = LoadConfigDialog(initial_mode="1cd")
    try:
        assert dlg.rb_db.isChecked()

        dlg.path_edit.setText("F:/bases/1Cv8.1CD")
        assert dlg.cb_import_data.isEnabled()
        assert dlg.cb_import_data.isChecked()

        dlg.cb_import_data.setChecked(True)
        choice = dlg.choice()
        assert choice.mode == "1cd"
        assert choice.migrate_data is True
        assert dlg.should_import_data() is True
    finally:
        dlg.deleteLater()


def test_load_config_dialog_disables_data_import_outside_1cd_mode():
    _ensure_app()
    dlg = LoadConfigDialog(initial_mode="1cd")
    try:
        dlg.path_edit.setText("F:/bases/1Cv8.1CD")
        dlg.cb_import_data.setChecked(True)

        dlg.rb_xml.setChecked(True)

        assert not dlg.cb_import_data.isEnabled()
        assert not dlg.cb_import_data.isChecked()
        assert dlg.choice().migrate_data is False
    finally:
        dlg.deleteLater()
