import pytest

from src.dsl.compiler import compile_module
from src.dsl.diagnostics import ParseError
from src.dsl.languages import EN_PROFILE, UK_PROFILE, MIXED_PROFILE
from src.dsl.lexer import Lexer, lex
from src.dsl.parser import parse
from src.dsl.preprocessor import SERVER_SYMBOLS, preprocess
from src.dsl.vm import VM


def selected(source, profile=MIXED_PROFILE, **kwargs):
    return preprocess(source, profile, defined_symbols=SERVER_SYMBOLS, **kwargs)


def run(source, profile=MIXED_PROFILE):
    text = selected(source, profile)
    program, diagnostics = parse(text, profile)
    assert not [d for d in diagnostics if d.severity == 'error'], diagnostics
    vm = VM(compile_module(program))
    vm.initialize()
    return vm


@pytest.mark.parametrize('source, profile', [
    ('#If Client Then\nx = 1;\n#ElsIf Server Then\nx = 2;\n#Else\nx = 3;\n#EndIf', EN_PROFILE),
    ('#Якщо Клієнт Тоді\nx = 1;\n#ІнакшеЯкщо Сервер Тоді\nx = 2;\n#Інакше\nx = 3;\n#КінецьЯкщо', UK_PROFILE),
    ('#Если Клиент Тогда\nx = 1;\n#ИначеЕсли НаСервере Тогда\nx = 2;\n#Иначе\nx = 3;\n#КонецЕсли', MIXED_PROFILE),
    ('#iF cLiEnT tHeN\nx = 1;\n#eLsEiF aTsErVeR tHeN\nx = 2;\n#eLsE\nx = 3;\n#eNdIf', EN_PROFILE),
])
def test_languages_select_exactly_one_branch(source, profile):
    assert run(source, profile)._globals['x'] == 2


@pytest.mark.parametrize('expression, expected', [
    ('Server', True), ('AtServer', True), ('Not Client', True),
    ('Not Server And Client Or Server', True),
    ('Server Or Client And Client', True), ('(Server Or Client) And Client', False),
    ('Not (Server Or Client)', False), ('Not Not (Server)', True),
    ('Server And Not (Client Or ExternalConnection)', True),
    ('True And Not False', True), ('ThinClient Or WebClient', False),
    ('ThickClientOrdinaryApplication Or ThickClientManagedApplication', False),
    ('MobileClient Or MobileAppClient Or MobileAppServer Or MobileStandaloneServer', False),
    ('Сервер Та Не Клієнт Або ЗовнішнєЗєднання', True),
    ('НаСервере И Не (Клиент Или ВнешнееСоединение)', True),
])
def test_boolean_precedence_and_context_symbols(expression, expected):
    vm = run(f'#If {expression} Then\nx = True;\n#Else\nx = False;\n#EndIf')
    assert vm._globals['x'] is expected


def test_nested_inactive_parent_and_first_matching_elseif():
    vm = run('''x = 0;
#If Client Then
    #If Server Then
        x = 1;
    #Else
        x = 2;
    #EndIf
#ElsIf Server Then
    #If Not Client Then
        x = 3;
    #EndIf
#ElsIf AtServer Then
    x = 4;
#Else
    x = 5;
#EndIf''')
    assert vm._globals['x'] == 3


def test_excluded_body_is_not_parsed_or_declared():
    vm = run('''#If Client Then
this is deliberately invalid $$$ code;
Function Pick() Export
    Return 1;
EndFunction
#Else
Function Pick() Export
    Return 2;
EndFunction
#EndIf
x = Pick();''')
    assert vm._globals['x'] == 2


def test_directives_inside_strings_and_comments_do_not_execute():
    text = '''// #If Not Server Then
/* #Else
#EndIf */
x = "#If Client Then
// #Else "comment"
|#EndIf";
y = '#EndRegion';
z = "quotes ""#Else""";
'''
    vm = run(text)
    assert vm._globals['x'] == '#If Client Then\n#EndIf'
    assert vm._globals['y'] == '#EndRegion'
    assert vm._globals['z'] == 'quotes "#Else"'


def test_multiline_comments_on_directive_lines_cannot_leak_code():
    text = '''#If Client Then /* a comment
#EndIf fake directive
*/
invalid code;
#Else /* another comment
*/
x = 8;
#EndIf
'''
    assert run(text)._globals['x'] == 8


def test_keeps_source_offsets_and_crlf_and_bom():
    source = '\ufeff#If Client Then\r\nx = 1;\r\n#Else\r\n\tx = "yes"; // comment\r\n#EndIf\r\n'
    actual = selected(source)
    assert len(actual) == len(source)
    assert [i for i, ch in enumerate(actual) if ch in '\r\n'] == [i for i, ch in enumerate(source) if ch in '\r\n']
    start = source.index('x = "yes"')
    assert actual[start:start + 10] == source[start:start + 10]
    assert run(source)._globals['x'] == 'yes'
    token = next(t for t in lex(actual, MIXED_PROFILE) if t.text == 'x')
    assert (token.span.line, token.span.col) == (4, 2)


@pytest.mark.parametrize('text, message', [
    ('#If Server\nx = 1;\n#EndIf', 'end with Then'),
    ('#If Then\n#EndIf', 'Incomplete'),
    ('#If Server And Then\n#EndIf', 'Incomplete'),
    ('#If (Server Then\n#EndIf', 'Incomplete'),
    ('#If Server) Then\n#EndIf', 'Unmatched'),
    ('#If Server Client Then\n#EndIf', 'operator'),
    ('#If Server = True Then\n#EndIf', 'operator'),
    ('#If Server Or Typo Then\n#EndIf', 'Unknown compile-time'),
    ('#If Client Then\n#If Typo Then\n#EndIf\n#EndIf', 'Unknown compile-time'),
    ('#If Server Then', 'Unclosed If'),
    ('#Else', 'Unexpected'), ('#EndIf', 'Unexpected'),
    ('#ElsIf Server Then', 'Unexpected ElsIf'),
    ('#If Server Then\n#Else\n#Else\n#EndIf', 'Duplicate Else'),
    ('#If Server Then\n#Else\n#ElsIf Server Then\n#EndIf', 'Unexpected ElsIf'),
    ('#If Server Then\n#Else garbage\n#EndIf', 'malformed'),
    ('#If Server Then\n#EndIf extra', 'malformed'),
    ('x = 1; #If Server Then\n#EndIf', 'start a source line'),
    ('#If Server Then x = 1;\n#EndIf', 'end with Then'),
    ('#Use Other', 'Unsupported preprocessor'),
    ('#If Client Then\n#Use Other\n#EndIf', 'Unsupported preprocessor'),
    ('#If Typo() Then\n#EndIf', 'Unknown compile-time'),
    ('#Unknown Foo', 'Unknown or unsupported'), ('#IfServer Then', 'Unknown or unsupported'),
    ('#Region Test', 'Unclosed Region'), ('#EndRegion', 'Unexpected EndRegion'),
    ('#Region Test Other\n#EndRegion', 'Invalid region name'),
    ('#If Client Then\nx = "bad\n#EndIf', 'Unterminated string'),
    ('#If Client Then\n/* bad\n#EndIf', 'Unterminated block comment'),
])
def test_malformed_or_unsupported_source_fails_closed(text, message):
    with pytest.raises(ParseError, match=message):
        selected(text)


def test_explicit_context_is_independent_of_source_variables():
    assert run('Server = False;\n#If Server Then\nx = 1;\n#Else\nx = 2;\n#EndIf')._globals['x'] == 1
    source = '#If Server Then\nx = 1;\n#Else\nx = 2;\n#EndIf'
    actual = preprocess(source, EN_PROFILE, defined_symbols=frozenset({'client', 'thinclient'}))
    assert 'x = 1' not in actual and 'x = 2' in actual
    with pytest.raises(ValueError, match='context'):
        preprocess(source, EN_PROFILE, defined_symbols=frozenset({'typo'}))


def test_large_comment_runs_and_expression_do_not_recurse():
    text = '// comment\n' * 3000 + '/*comment*/' * 3000 + '\n'
    text += '#If ' + 'Not ' * 2000 + 'Server Then\nx = 1;\n#EndIf'
    assert run(text)._globals['x'] == 1


def test_nesting_limit():
    text = '#If Server Then\n' * 5 + 'x = 1;\n' + '#EndIf\n' * 5
    with pytest.raises(ParseError, match='nesting limit'):
        selected(text, max_nesting=4)
    assert 'x = 1;' in selected(text, max_nesting=5)


def test_source_token_offsets_include_original_escaped_multiline_string():
    text = '// before\nText = "a ""quote""\n// comment\n|b";'
    tokens = list(Lexer(text, MIXED_PROFILE, strict=True).source_tokens())
    token, start, end = next(t for t in tokens if t[0].type == 'STRING')
    assert text[start:end] == '"a ""quote""\n// comment\n|b"'
    assert token.text == 'a "quote"\nb'


def test_editor_parser_recognizes_elseif_directive_without_selecting_branches():
    program, diagnostics = parse('#If Client Then\nx = 1;\n#ElseIf Server Then\nx = 2;\n#EndIf', EN_PROFILE)
    assert program is not None and not diagnostics
    tokens = lex('#ІнакшеЯкщо Сервер Тоді', UK_PROFILE)
    assert tokens[0].type == 'KW_ELSEIF_COMPILE'
