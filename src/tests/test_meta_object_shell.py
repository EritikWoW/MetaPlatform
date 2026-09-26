from PySide6.QtWidgets import QApplication, QWidget

from src.ui_qt.widgets.meta_object_shell import EditorSection, MetaObjectEditorShell


def test_meta_object_shell_emits_apply_even_without_pending_patch() -> None:
    app = QApplication.instance() or QApplication([])
    emitted: list[dict] = []

    shell = MetaObjectEditorShell(title="Test")
    shell.applyRequested.connect(emitted.append)
    app.processEvents()

    shell._on_apply_clicked()

    assert emitted == [{}]


def test_programmatic_navigation_runs_lazy_load_and_updates_buttons():
    app = QApplication.instance() or QApplication([])
    shell = MetaObjectEditorShell()
    loaded = []
    pages = [QWidget(), QWidget()]
    for index, page in enumerate(pages):
        page._on_section_shown = lambda i=index: loaded.append(i)
    shell.set_sections([EditorSection(str(i), "btn_help", lambda p=page: p) for i, page in enumerate(pages)])
    assert loaded == [0]
    shell._btn_next.click()
    assert loaded == [0, 1]
    assert shell.current_index() == 1
    assert shell._btn_back.isEnabled() and not shell._btn_next.isEnabled()
    shell._btn_back.click()
    shell.set_current_section("1")
    assert loaded == [0, 1]
    assert shell._sections.currentRow() == 1
    shell.deleteLater()
