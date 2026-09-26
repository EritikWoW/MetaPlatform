import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.ui_qt.widgets.code_editor_widget import create_metascript_code_edit


@pytest.fixture
def editor():
    app = QApplication.instance() or QApplication([])
    edit, highlighter = create_metascript_code_edit()
    edit.resize(800, 500)
    edit.show()
    edit.setFocus()
    app.processEvents()
    yield edit
    edit.close()
    edit.deleteLater()
    app.processEvents()


def at_end(editor, source):
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    editor._autocomplete_completer.popup().hide()


@pytest.mark.parametrize('source, expected', [
    ('Procedure Work() Export', 'Procedure Work() Export\n    '),
    ('Функція Робота() Експорт // опис', 'Функція Робота() Експорт // опис\n    '),
    ('If Ready Then // Do not lose depth', 'If Ready Then // Do not lose depth\n    '),
    ('If Ready Then\n    Else', 'If Ready Then\nElse\n    '),
    ('Try\n    Except', 'Try\nExcept\n    '),
    ('Procedure Work()\n    If Ready Then\n    EndIf;', 'Procedure Work()\n    If Ready Then\n    EndIf;\n    '),
    ('Procedure Work()\n    EndDate = 1;', 'Procedure Work()\n    EndDate = 1;\n    '),
    ('Procedure Work()\n    ElseValue = 2;', 'Procedure Work()\n    ElseValue = 2;\n    '),
    ('Procedure Work()\n    // If Ready Then', 'Procedure Work()\n    // If Ready Then\n    '),
    ('Procedure Work()\n    Text = "😀";', 'Procedure Work()\n    Text = "😀";\n    '),
    ('Text = "first\n |If Then', 'Text = "first\n |If Then\n'),
    ('/* comment\nIf Ready Then', '/* comment\nIf Ready Then\n'),
])
def test_enter_uses_syntax_context_and_is_one_undo(editor, source, expected):
    at_end(editor, source)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert editor.toPlainText() == expected
    editor.undo()
    assert editor.toPlainText() == source


def test_enter_in_middle_uses_only_text_before_caret(editor):
    source = 'If Ready Then'
    at_end(editor, source)
    cursor = editor.textCursor()
    cursor.setPosition(3)
    editor.setTextCursor(cursor)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert editor.toPlainText() == 'If \n    Ready Then'


def test_format_shortcut_keeps_breakpoints_cursor_lines_and_undo(editor):
    source = 'Procedure Run()\nIf Ready Then\nText = "😀";\nEndIf;\nEndProcedure'
    at_end(editor, source)
    editor._breakpoints = {3}
    cursor = editor.textCursor()
    cursor.setPosition(editor.document().findBlockByNumber(2).position() + 4)
    editor.setTextCursor(cursor)
    QTest.keyClick(editor, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert editor.toPlainText() == 'Procedure Run()\n    If Ready Then\n        Text = "😀";\n    EndIf;\nEndProcedure'
    assert editor.textCursor().blockNumber() == 2
    assert editor.textCursor().positionInBlock() == 12
    assert editor._breakpoints == {3}
    assert not editor._autocomplete_completer.popup().isVisible()
    assert not editor.format_code_indentation()
    editor.undo()
    assert editor.toPlainText() == source
    editor.redo()
    assert '        Text' in editor.toPlainText()


def test_format_reversed_selection_preserves_direction_and_excludes_next_line(editor):
    source = 'Procedure Run()\nIf Ready Then\nWork();\nEndIf;\nEndProcedure'
    at_end(editor, source)
    cursor = editor.textCursor()
    cursor.setPosition(editor.document().findBlockByNumber(3).position())
    cursor.setPosition(editor.document().findBlockByNumber(2).position(), QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    editor.format_code_indentation()
    assert editor.toPlainText() == source.replace('Work();', '        Work();')
    assert editor.textCursor().position() < editor.textCursor().anchor()
    assert editor.textCursor().selectedText() == '        Work();\u2029'
    editor.undo()
    assert editor.toPlainText() == source


@pytest.mark.parametrize('source', ['// If', '# note', '/* If', 'Text = "If', 'Text = "a\n |If'])
def test_completion_and_pairing_do_not_intrude_on_literals_and_comments(editor, source):
    at_end(editor, source)
    calls = []
    editor.set_autocomplete_namespace_provider(lambda namespace: calls.append(namespace) or ['Member'])
    QTest.keyClick(editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert not editor._autocomplete_completer.popup().isVisible()
    QTest.keyClicks(editor, '(')
    assert editor.toPlainText() == source + '('
    assert calls == []


@pytest.mark.parametrize('key', [Qt.Key.Key_Return, Qt.Key.Key_Tab, Qt.Key.Key_Backtab])
def test_readonly_editor_cannot_be_changed_by_editing_helpers(editor, key):
    source = 'Procedure Run()\nWork();\nEndProcedure'
    at_end(editor, source)
    editor.setReadOnly(True)
    QTest.keyClick(editor, key)
    QTest.keyClicks(editor, '(')
    editor.format_code_indentation()
    editor.apply_autocomplete_completion('If')
    assert editor.toPlainText() == source


@pytest.mark.parametrize('accept_key', [Qt.Key.Key_Return, Qt.Key.Key_Tab])
def test_completion_accepts_arrow_selected_item_without_newline_or_indent(editor, accept_key):
    at_end(editor, 'Cust')
    editor.set_autocomplete_words(['CustomAlpha', 'CustomBeta'])
    QTest.keyClick(editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    popup = editor._autocomplete_completer.popup()
    assert popup.isVisible()
    assert popup.currentIndex().data() == 'CustomAlpha'
    QTest.keyClick(popup, Qt.Key.Key_Down)
    assert popup.currentIndex().data() == 'CustomBeta'
    QTest.keyClick(popup, accept_key)
    assert editor.toPlainText() == 'CustomBeta'
    assert not popup.isVisible()


def test_completion_does_not_automatically_offer_an_already_complete_word(editor):
    at_end(editor, '')
    editor.set_autocomplete_words(['Customer', 'Customers'])
    QTest.keyClicks(editor, 'Customer')
    assert not editor._autocomplete_completer.popup().isVisible()


def test_ctrl_space_accepts_first_option_and_escape_does_not_insert(editor):
    at_end(editor, 'Cust')
    editor.set_autocomplete_words(['CustomAlpha', 'CustomBeta'])
    QTest.keyClick(editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert editor.toPlainText() == 'CustomAlpha'
    at_end(editor, 'Cust')
    QTest.keyClick(editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(editor._autocomplete_completer.popup(), Qt.Key.Key_Escape)
    assert editor.toPlainText() == 'Cust'
    assert not editor._autocomplete_completer.popup().isVisible()


def test_completion_after_non_bmp_literal_uses_correct_text_offsets(editor):
    at_end(editor, 'Text = "😀"; Cust')
    editor.set_autocomplete_words(['Customer'])
    QTest.keyClick(editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(editor._autocomplete_completer.popup(), Qt.Key.Key_Return)
    assert editor.toPlainText() == 'Text = "😀"; Customer'


@pytest.mark.parametrize('opening, closing', [('(', ')'), ('[', ']'), ('{', '}')])
def test_paired_delimiters_can_be_overtype_closed_or_deleted_together(editor, opening, closing):
    at_end(editor, '')
    QTest.keyClicks(editor, opening)
    assert editor.toPlainText() == opening + closing
    assert editor.textCursor().position() == 1
    QTest.keyClick(editor, Qt.Key.Key_Backspace)
    assert editor.toPlainText() == ''
    editor.undo()
    assert editor.toPlainText() == opening + closing
    cursor = editor.textCursor()
    cursor.setPosition(1)
    editor.setTextCursor(cursor)
    QTest.keyClicks(editor, closing)
    assert editor.toPlainText() == opening + closing
    assert editor.textCursor().position() == 2


def test_readonly_keeps_definition_navigation_and_can_be_reenabled(editor):
    at_end(editor, 'Module.Call()')
    calls = []
    editor._definition_handler = lambda: calls.append(True)
    editor.setReadOnly(True)
    QTest.keyClick(editor, Qt.Key.Key_F12)
    assert calls == [True]
    editor.setReadOnly(False)
    assert editor._format_action.isEnabled()


def test_highlighter_recalculates_following_lines_after_string_delimiter_edit(editor):
    from src.ui_qt.widgets.metascript_highlighter import _Palette

    at_end(editor, 'Text = "open\n |If True Then')
    QApplication.processEvents()
    block = editor.document().findBlockByNumber(1)
    ranges = block.layout().formats()
    assert any(r.format.foreground().color().name() == _Palette.DARK['string'].lower() for r in ranges)
    cursor = editor.textCursor()
    cursor.setPosition(len('Text = "open'))
    cursor.insertText('";')
    QApplication.processEvents()
    ranges = block.layout().formats()
    assert any(r.format.foreground().color().name() == _Palette.DARK['keyword'].lower() for r in ranges)


def test_shared_configuration_still_accepts_a_plain_text_editor(editor):
    from PySide6.QtWidgets import QPlainTextEdit
    from src.ui_qt.widgets.code_editor_widget import configure_metascript_editor

    plain = QPlainTextEdit()
    highlighter = configure_metascript_editor(plain)
    plain.setPlainText('Text = "😀"; Cust')
    cursor = plain.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    plain.setTextCursor(cursor)
    plain._autocomplete_words = {'Customer'}
    plain._autocomplete_handler(True)
    assert plain._autocomplete_completer.completionPrefix() == 'Cust'
    plain._autocomplete_insert_handler('Customer')
    assert plain.toPlainText() == 'Text = "😀"; Customer'
    plain.close()
