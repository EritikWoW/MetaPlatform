import threading
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.ui_qt.widgets.code_editor_widget import create_metascript_code_edit


@pytest.fixture
def edit():
    app = QApplication.instance() or QApplication([])
    editor, highlighter = create_metascript_code_edit(autocomplete=False)
    editor.resize(800, 500)
    editor.show()
    editor.setFocus()
    app.processEvents()
    yield editor
    editor.close()
    editor.deleteLater()
    app.processEvents()


def set_source(edit, source):
    edit.setPlainText(source)
    cursor = edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    edit.setTextCursor(cursor)


def wait_until(condition, timeout=1500):
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        if condition():
            return
        QTest.qWait(10)
    assert condition()


def trigger(edit):
    QTest.keyClick(edit, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)


def test_builtin_manual_shortcut_preserves_focus_and_does_not_insert_space(edit):
    set_source(edit, 'Round(100, ')
    trigger(edit)
    assistant = edit._syntax_assistant
    assert assistant._popup.isVisible()
    assert assistant._active_func.name_en == 'Round'
    assert assistant._popup._current_param == 1
    assert edit.hasFocus()
    assert edit.toPlainText() == 'Round(100, '


def test_local_unsaved_signature_overrides_builtin_and_escapes_html(edit):
    source = 'Function Round(Val Input, Markup = "<b>,)")\nEndFunction\nRound(1, '
    set_source(edit, source)
    trigger(edit)
    assistant = edit._syntax_assistant
    assert assistant._active_func.category_en == 'Current module'
    html = assistant._popup._lbl_signature.text()
    assert 'Input' in html and '&lt;b&gt;' in html
    assert ' = &quot;' in html
    assert assistant._popup._current_param == 1
    changed = source.replace('Markup', 'Changed')
    set_source(edit, changed)
    wait_until(lambda: 'Changed' in assistant._popup._lbl_signature.text())


def test_uk_en_switch_changes_signature_surface_not_source_identifiers(edit):
    set_source(edit, 'Round(1, ')
    assistant = edit._syntax_assistant
    assistant.set_language('en')
    trigger(edit)
    assert 'Function' in assistant._popup._lbl_signature.text()
    assistant.set_language('uk')
    trigger(edit)
    assert 'Функція' in assistant._popup._lbl_signature.text()
    assert edit.toPlainText() == 'Round(1, '


def test_automatic_popup_tracks_nested_multiline_calls_and_closes(edit):
    source = 'Function Work(First, Second)\nEndFunction\nWork(\nRound(1, '
    set_source(edit, source)
    assistant = edit._syntax_assistant
    wait_until(lambda: assistant._popup.isVisible())
    assert assistant._active_func.name_en == 'Round'
    edit.insertPlainText('2), ')
    wait_until(lambda: assistant._active_func is not None and assistant._active_func.name_en == 'Work')
    assert assistant._popup._current_param == 1
    edit.insertPlainText('3);')
    wait_until(lambda: not assistant._popup.isVisible())


def test_popup_resumes_after_closing_block_comment(edit):
    set_source(edit, 'Round(1, /* comment')
    trigger(edit)
    assistant = edit._syntax_assistant
    assert not assistant._popup.isVisible()
    edit.insertPlainText(' */')
    wait_until(lambda: assistant._popup.isVisible())
    assert assistant._popup._current_param == 1


def test_popup_does_not_leak_from_unclosed_call_in_previous_routine(edit):
    set_source(edit, 'Procedure First()\nRound(\nEndProcedure\nProcedure Second()\nValue = 1')
    trigger(edit)
    assert not edit._syntax_assistant._popup.isVisible()


def test_popup_hides_when_caret_scrolls_out_of_view(edit):
    set_source(edit, '// padding\n' * 100 + 'Round(1, ')
    trigger(edit)
    assistant = edit._syntax_assistant
    assert assistant._popup.isVisible()
    edit.verticalScrollBar().setValue(0)
    wait_until(lambda: not assistant._popup.isVisible())
    trigger(edit)
    assert not assistant._popup.isVisible()
    edit.ensureCursorVisible()
    trigger(edit)
    assert assistant._popup.isVisible()


def test_escape_dismisses_until_explicit_shortcut_and_closing_editor_hides_popup(edit):
    set_source(edit, 'Round(1, ')
    trigger(edit)
    assistant = edit._syntax_assistant
    QTest.keyClick(edit, Qt.Key.Key_Escape)
    assert not assistant._popup.isVisible()
    QTest.qWait(120)
    assert not assistant._popup.isVisible()
    trigger(edit)
    assert assistant._popup.isVisible()
    edit.close()
    assert not assistant._popup.isVisible()


@pytest.mark.parametrize('source', ['// Round(', 'Text = "Round(', 'Procedure Round(', 'Other.Round('])
def test_no_invented_signature_for_comments_declarations_or_unknown_method(edit, source):
    set_source(edit, source)
    trigger(edit)
    assert not edit._syntax_assistant._popup.isVisible()


def test_duplicate_local_declarations_do_not_fall_back_to_builtin(edit):
    set_source(edit, 'Procedure Round(A)\nEndProcedure\nProcedure Round(B)\nEndProcedure\nRound(')
    trigger(edit)
    assert not edit._syntax_assistant._popup.isVisible()


def test_utf16_cursor_coordinates_after_emoji(edit):
    set_source(edit, 'Text = "😀"; Round(1, ')
    trigger(edit)
    assert edit._syntax_assistant._popup._current_param == 1
    assert edit._syntax_assistant._active_func.name_en == 'Round'


def test_remote_signatures_are_async_exact_cached_and_do_not_reopen_stale_call(edit):
    release = threading.Event()
    called = threading.Event()
    threads = []

    def provider(namespace):
        threads.append(threading.get_ident())
        assert namespace == 'ServerModule'
        called.set()
        release.wait(2)
        return {'found': True, 'members': [{'name': 'Calculate', 'kind': 'function', 'params': ['Data', 'Rate']}]}

    assistant = edit._syntax_assistant
    assistant.set_namespace_provider(provider)
    set_source(edit, 'ServerModule.Calculate(1, ')
    trigger(edit)
    try:
        wait_until(called.is_set)
        assert threads[0] != threading.get_ident()
        assert not assistant._popup.isVisible()
        edit.insertPlainText('2);')
        release.set()
        wait_until(lambda: not assistant._pending)
        assert not assistant._popup.isVisible()
        set_source(edit, 'ServerModule.Calculate(1, ')
        wait_until(lambda: assistant._popup.isVisible())
        assert len(threads) == 1
        assert assistant._active_func.name_en == 'ServerModule.Calculate'
        assert assistant._popup._current_param == 1
        assert 'Rate' in assistant._popup._lbl_signature.text()
    finally:
        release.set()


def test_shadowed_namespace_never_queries_runtime(edit):
    calls = []
    edit._syntax_assistant.set_namespace_provider(lambda namespace: calls.append(namespace) or {})
    set_source(edit, 'Procedure Work(ServerModule)\nServerModule.Calculate(')
    trigger(edit)
    QTest.qWait(120)
    assert calls == []
    assert not edit._syntax_assistant._popup.isVisible()


def test_failed_provider_does_not_break_local_help(edit):
    def provider(namespace):
        raise ConnectionError('Offline')

    assistant = edit._syntax_assistant
    assistant.set_namespace_provider(provider)
    set_source(edit, 'ServerModule.Calculate(')
    trigger(edit)
    wait_until(lambda: not assistant._pending)
    assert not assistant._popup.isVisible()
    set_source(edit, 'Round(1, ')
    trigger(edit)
    assert assistant._popup.isVisible()


def test_parameter_shadowing_beats_same_named_local_function(edit):
    set_source(edit, 'Function Round(A)\nEndFunction\nProcedure Main(Round)\nRound(')
    trigger(edit)
    assert not edit._syntax_assistant._popup.isVisible()


@pytest.mark.parametrize('members', [
    [{'name': 'Other', 'kind': 'function', 'params': ['X']}],
    [{'name': 'Calculate', 'kind': 'function', 'params': ['X']}, {'name': 'CALCULATE', 'kind': 'procedure', 'params': ['Y']}],
])
def test_remote_lookup_does_not_guess_missing_or_duplicate_member(edit, members):
    assistant = edit._syntax_assistant
    assistant.set_namespace_provider(lambda namespace: {'found': True, 'members': members})
    set_source(edit, 'ServerModule.Calculate(')
    trigger(edit)
    wait_until(lambda: not assistant._pending)
    assert not assistant._popup.isVisible()


def test_invalidate_discards_inflight_old_database_response(edit):
    release = threading.Event()

    def old_provider(namespace):
        release.wait(2)
        return {'found': True, 'members': [{'name': 'Calculate', 'kind': 'function', 'params': ['Old']} ]}

    assistant = edit._syntax_assistant
    assistant.set_namespace_provider(old_provider)
    set_source(edit, 'ServerModule.Calculate(')
    trigger(edit)
    assistant.set_namespace_provider(lambda namespace: {
        'found': True, 'members': [{'name': 'Calculate', 'kind': 'function', 'params': ['New']} ]})
    release.set()
    wait_until(lambda: assistant._popup.isVisible())
    assert assistant._active_func.params[0].name_en == 'New'


def test_manual_refresh_reloads_remote_saved_signature(edit):
    names = ['First']
    calls = []

    def provider(namespace):
        calls.append(namespace)
        return {'found': True, 'members': [{'name': 'Calculate', 'kind': 'procedure', 'params': list(names)}]}

    assistant = edit._syntax_assistant
    assistant.set_namespace_provider(provider)
    set_source(edit, 'ServerModule.Calculate(')
    trigger(edit)
    wait_until(lambda: assistant._popup.isVisible())
    names[:] = ['Second']
    trigger(edit)
    wait_until(lambda: assistant._active_func is not None and assistant._active_func.params[0].name_en == 'Second')
    assert len(calls) == 2


def test_no_parameter_and_extra_argument_hints_do_not_highlight_wrong_parameter(edit):
    assistant = edit._syntax_assistant
    assistant.set_language('en')
    set_source(edit, 'Procedure Empty()\nEndProcedure\nEmpty(')
    trigger(edit)
    assert assistant._popup._lbl_param_desc.text() == 'No parameters'
    set_source(edit, 'Procedure One(First)\nEndProcedure\nOne(1, 2, ')
    trigger(edit)
    assert assistant._popup._current_param == 2
    assert 'Argument 3; parameters: 1' in assistant._popup._lbl_param_desc.text()


def test_code_editor_widget_connects_existing_runtime_completion_service(edit):
    from src.ui_qt.widgets.code_editor_widget import CodeEditorWidget

    class Service:
        def get_common_module_completion(self, name):
            assert name == 'Shared'
            return {'found': True, 'members': [{'name': 'Run', 'kind': 'procedure', 'params': ['Input']}]}

    class VM:
        _objects_snapshot = []
        _service = Service()

        def get_text_asset(self, asset):
            return 'Shared.Run(', 'text/metascript', asset

    widget = CodeEditorWidget(vm=VM(), asset_key='module://signature-test', title='Signature')
    widget.show()
    editor = widget._edit
    editor.setFocus()
    QApplication.processEvents()
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    trigger(editor)
    wait_until(lambda: editor._syntax_assistant._popup.isVisible())
    assert editor._syntax_assistant._active_func.name_en == 'Shared.Run'
    widget._apply_loaded_text('NoCall;', 'text/metascript', 'module://signature-test')
    assert not editor._syntax_assistant._popup.isVisible()
    assert not editor._syntax_assistant._cache
    widget.close()
    widget.deleteLater()


def test_large_snapshot_is_built_off_ui_thread_and_stale_buffer_is_discarded(edit, monkeypatch):
    import src.ui_qt.widgets.syntax_assistant as module

    original = module.SignatureDocument
    release = threading.Event()
    started = threading.Event()
    threads = []

    def slow_snapshot(source):
        if len(source) > 32_000:
            threads.append(threading.get_ident())
            started.set()
            release.wait(2)
        return original(source)

    monkeypatch.setattr(module, 'SignatureDocument', slow_snapshot)
    set_source(edit, '// padding\n' * 3500 + 'Round(1, ')
    trigger(edit)
    try:
        wait_until(started.is_set)
        assert threads == [threads[0]] and threads[0] != threading.get_ident()
        set_source(edit, 'Function Current(Input)\nEndFunction\nCurrent(')
        trigger(edit)
        assert edit._syntax_assistant._active_func.name_en == 'Current'
        release.set()
        wait_until(lambda: not edit._syntax_assistant._snapshot_pending)
        assert edit._syntax_assistant._active_func.name_en == 'Current'
    finally:
        release.set()
