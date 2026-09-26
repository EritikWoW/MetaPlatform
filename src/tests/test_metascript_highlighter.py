from PySide6.QtGui import QTextDocument
import pytest

from src.ui_qt.widgets.metascript_highlighter import MetaScriptHighlighter, _Palette


def test_highlighter_formats_ukrainian_for_each_in_operator_as_keyword() -> None:
    source = "Для Кожного Елемент З Колекція Цикл"
    document = QTextDocument(source)
    highlighter = MetaScriptHighlighter(document, dark=True)

    highlighter.rehighlight()

    formats = document.firstBlock().layout().formats()
    in_start = source.index(" З ") + 1
    in_format = next(
        item.format
        for item in formats
        if item.start == in_start and item.length == 1
    )
    assert in_format.foreground().color().name().lower() == _Palette.DARK["keyword"].lower()


@pytest.mark.parametrize('directive', ['#If', '#Else', '#ElsIf', '#ElseIf', '#ІнакшеЯкщо', '#КінецьЯкщо'])
def test_highlighter_formats_complete_elseif_directive(directive):
    document = QTextDocument(directive + ' Server Then')
    highlighter = MetaScriptHighlighter(document, dark=True)
    highlighter.rehighlight()
    formats = document.firstBlock().layout().formats()
    assert any(item.start == 0 and item.length == len(directive)
               and item.format.foreground().color().name().lower() == _Palette.DARK['preprocessor'].lower()
               for item in formats)


@pytest.mark.parametrize('source, color', [
    ('// #ElsIf Server Then', 'comment'), ('#unknown comment', 'comment'),
    ('"#ElsIf Server Then"', 'string'), ('/* #ElsIf Server Then */', 'comment'),
])
def test_directive_highlighting_does_not_override_comments_or_literals(source, color):
    document = QTextDocument(source)
    highlighter = MetaScriptHighlighter(document, dark=True)
    highlighter.rehighlight()
    index = source.index('#')
    ranges = document.firstBlock().layout().formats()
    fmt = next(r.format for r in ranges if r.start <= index < r.start + r.length)
    assert fmt.foreground().color().name().lower() == _Palette.DARK[color].lower()


@pytest.mark.parametrize('source, needle, color', [
    ('// "If True Then"', 'If', 'comment'),
    ('Value = "/* not a comment */"; If True Then', 'not', 'string'),
    ('Value = "/*";\nIf True Then', 'If', 'keyword'),
    ('Path = "C:\\"; If True Then', 'If', 'keyword'),
    ('Text = "a\n |If True Then\n |end";\nEndIf;', 'If', 'string'),
    ('Text = "a\n // "comment\n |end";', 'comment', 'comment'),
    ('Text = "😀"; If True Then', 'If', 'keyword'),
    ('Function Test()\nReturn True;\nEndFunction', 'Function', 'keyword'),
    ('If True Then', 'True', 'literal'),
    ('Якщо Істина Та Не Хибність Тоді', 'Істина', 'literal'),
    ('Якщо Істина Та Не Хибність Тоді', 'Та', 'logical_op'),
])
def test_lexical_context_controls_highlighting(source, needle, color):
    document = QTextDocument(source)
    highlighter = MetaScriptHighlighter(document, dark=True)
    highlighter.rehighlight()
    position = len(source[:source.index(needle)].encode('utf-16-le')) // 2
    block = document.findBlock(position)
    index = position - block.position()
    ranges = block.layout().formats()
    fmt = next(r.format for r in ranges if r.start <= index < r.start + r.length)
    assert fmt.foreground().color().name().lower() == _Palette.DARK[color].lower()
