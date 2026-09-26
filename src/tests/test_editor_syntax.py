"""Editing helpers must tolerate incomplete code without changing literal data."""

import pytest

from src.dsl.editor_syntax import format_indentation, indentation_plan, scan_editor_line


@pytest.mark.parametrize("source, expected", [
    ("Procedure Run()\nIf Ready Then // comment\nWork();\nElse\nTry\nOther();\nExcept\nReport();\nEndTry;\nEndIf;\nEndProcedure",
     "Procedure Run()\n    If Ready Then // comment\n        Work();\n    Else\n        Try\n            Other();\n        Except\n            Report();\n        EndTry;\n    EndIf;\nEndProcedure"),
    ("Функція Тест() Експорт\nДля Кожного Рядок З Колекція Цикл\nПоки Умова Цикл\nПовернути Рядок;\nКінецьЦиклу;\nКінецьЦиклу;\nКінецьФункції",
     "Функція Тест() Експорт\n    Для Кожного Рядок З Колекція Цикл\n        Поки Умова Цикл\n            Повернути Рядок;\n        КінецьЦиклу;\n    КінецьЦиклу;\nКінецьФункції"),
    ("Procedure Run(\nVal Input,\nOther) Export\nCall(\nInput,\nNested(\nOther));\nEndProcedure",
     "Procedure Run(\n    Val Input,\n    Other) Export\n    Call(\n        Input,\n        Nested(\n            Other));\nEndProcedure"),
    ("Procedure Run()\nIf Ready Then Work(); Else Other(); EndIf;\nNext();\nEndProcedure",
     "Procedure Run()\n    If Ready Then Work(); Else Other(); EndIf;\n    Next();\nEndProcedure"),
    ("Procedure Run()\nEndDate = 1;\nElseValue = 2;\nObject.If = 3;\nValue = Object.Try();\nEndProcedure",
     "Procedure Run()\n    EndDate = 1;\n    ElseValue = 2;\n    Object.If = 3;\n    Value = Object.Try();\nEndProcedure"),
    ("#If Server Then\nProcedure Run()\nWork();\nEndProcedure\n#Else\nProcedure Run()\nOther();\nEndProcedure\n#EndIf",
     "#If Server Then\nProcedure Run()\n    Work();\nEndProcedure\n#Else\nProcedure Run()\n    Other();\nEndProcedure\n#EndIf"),
    ("Procedure Run()\nIf (Ready And\nOther)\nThen\nWork();\nEndIf;\nEndProcedure",
     "Procedure Run()\n    If (Ready And\n        Other)\n    Then\n        Work();\n    EndIf;\nEndProcedure"),
    ("Module {\nProcedure Run()\nIf Ready Then\nWork();\nEndIf;\nEndProcedure\n}",
     "Module {\n    Procedure Run()\n        If Ready Then\n            Work();\n        EndIf;\n    EndProcedure\n}"),
])
def test_formats_structural_indentation_and_is_idempotent(source, expected):
    assert format_indentation(source) == expected
    assert format_indentation(expected) == expected


def test_format_preserves_multiline_payload_and_comment_interior():
    source = ('Procedure Run()\r\nValue = "If Then\r\n'
              '  // "comment, not a delimiter\r\n\t|EndIf /* text\r\n'
              ' |end";\r\n/* block\r\n  "EndProcedure"\r\n*/\r\nNext();\r\nEndProcedure\r\n')
    expected = source.replace('Value =', '    Value =').replace('/* block', '    /* block').replace('Next();', '    Next();')
    assert format_indentation(source) == expected
    assert format_indentation(expected) == expected


def test_format_selection_uses_surrounding_scope_but_changes_only_selected_lines():
    source = "Procedure Run()\nIf Ready Then\nWork();\nEndIf;\nEndProcedure"
    assert format_indentation(source, start_line=2, end_line=3) == (
        "Procedure Run()\nIf Ready Then\n        Work();\n    EndIf;\nEndProcedure")


def test_unfinished_source_still_has_a_safe_indent_plan():
    plan = indentation_plan('Procedure Run()\nIf (Ready And\nOther')
    assert [line.level for line in plan] == [0, 1, 2]
    assert plan[-1].next_level == 2


def test_scanner_doubled_quotes_and_literal_backslash_match_bsl():
    line = scan_editor_line('Path = "C:\\"; // "Else"')
    assert [span.kind for span in line.spans] == ['string', 'comment']
    escaped = scan_editor_line('Text = "value ""/*quoted*/"""; Work();')
    assert len(escaped.spans) == 1
    assert escaped.spans[0].kind == 'string'


@pytest.mark.parametrize('source', [
    'Procedure Run()\nValue = "If Then\n  // "comment\n |EndIf /* \\ text\n |end";\nEndProcedure',
    "Function Run()\nValue = 'single '' quote\n |EndTry';\nReturn Value;\nEndFunction",
    '\ufeffProcedure Run()\r\nPath = "C:\\";\r\nMessage(Path); // "If"\r\nEndProcedure\r\n',
    'Procedure Run()\n/* If Then\n EndProcedure */\nIf Ready Then\nFor I = 0 To 9 Do\nMessage(I);\nEndDo;\nEndIf;\nEndProcedure',
])
def test_format_preserves_compiler_tokens_and_string_values(source):
    from src.dsl.languages import get_profile
    from src.dsl.lexer import Lexer

    def tokens(text):
        return [(t.type, t.text) for t in Lexer(text, get_profile('mixed'), strict=True).tokenize()]

    formatted = format_indentation(source)
    assert tokens(formatted) == tokens(source)
    assert format_indentation(formatted) == formatted


def test_format_unmatched_closers_never_produces_negative_depth():
    plan = indentation_plan('EndIf;\nEndDo;\nExcept\n}\nNext();')
    assert all(item.level >= 0 and item.next_level >= 0 for item in plan)


def test_conditional_alternatives_do_not_leak_partial_scopes():
    source = '#If Server Then\nProcedure Run()\n#Else\nProcedure Other()\n#EndIf\nWork();\nEndProcedure'
    assert format_indentation(source) == source.replace('Work();', '    Work();')
