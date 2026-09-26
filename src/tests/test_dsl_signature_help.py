import pytest

from src.dsl.signature_help import SignatureDocument


@pytest.mark.parametrize('source, chain, active', [
    ('Round(', ('Round',), 0),
    ('Round(123, ', ('Round',), 1),
    ('Outer(1, Inner(', ('Inner',), 0),
    ('Outer(Inner(1, 2), ', ('Outer',), 1),
    ('Outer((1 + 2), ', ('Outer',), 1),
    ('Outer(Items[1, 2], ', ('Outer',), 1),
    ('Outer({"a": 1, "b": 2}, ', ('Outer',), 1),
    ('Outer("a,b(c)", ', ('Outer',), 1),
    ('Outer("a ""b,c()""", ', ('Outer',), 1),
    ('Outer("C:\\", ', ('Outer',), 1),
    ('Outer(\n Inner(1, 2),\n ', ('Outer',), 1),
    ('СпільнийСервер.Обробити(\nДані, ', ('СпільнийСервер', 'Обробити'), 1),
    ('CommonModule.ServerModule.Calculate(', ('CommonModule', 'ServerModule', 'Calculate'), 0),
    ('Outer(1, // Some(1, 2)\n ', ('Outer',), 1),
    ('Outer(/* Some(1,2) */1, ', ('Outer',), 1),
    ('Outer(1, /* Some(1,2) */', ('Outer',), 1),
    ('Outer(1, /* comment\nend */', ('Outer',), 1),
    ('Outer("text\n |a,b(c)\n |end", ', ('Outer',), 1),
    ('Outer("text\n // a " comment\n |a,b(c)\n |end", ', ('Outer',), 1),
    ('Outer("still typing (,', ('Outer',), 0),
    ('Text = "😀"; Round(123, ', ('Round',), 1),
])
def test_active_parameter_ignores_nested_delimiters_and_literal_contents(source, chain, active):
    context = SignatureDocument(source).context_at(len(source))
    assert context is not None
    assert context.chain == chain
    assert context.active_parameter == active
    assert source[context.opening_position] == '('


@pytest.mark.parametrize('source', [
    '// Round(', '/* Round(', 'Text = "Round(', '# note Round(',
    'Procedure Round(', 'Function Example(Val X = Round(',
    'Outer(1, // comment', 'Outer(1, /* comment',
    'Outer("text\n // comment', 'Round(1)',
    'If (', 'Getter().Round(', 'Items[0].Round(',
    'Broken(1; Next = 2;',
])
def test_noncall_context_does_not_offer_a_signature(source):
    assert SignatureDocument(source).context_at(len(source)) is None


def test_cursor_movement_changes_parameter_without_rebuilding_snapshot():
    source = 'Outer(1, Inner(2, 3), 4)'
    document = SignatureDocument(source)
    for marker, chain, index in [('1', ('Outer',), 0), ('2', ('Inner',), 0), ('3', ('Inner',), 1), ('4', ('Outer',), 2)]:
        context = document.context_at(source.index(marker))
        assert (context.chain, context.active_parameter) == (chain, index)


@pytest.mark.parametrize('boundary', [
    'EndProcedure', 'EndFunction', 'Procedure Second()', 'Function Second()',
])
def test_unclosed_call_does_not_leak_across_routine_boundaries(boundary):
    source = 'Round(1,\n' + boundary + '\nValue = 1'
    assert SignatureDocument(source).context_at(len(source)) is None


def test_signatures_survive_incomplete_body_and_retain_val_defaults():
    source = ('Функція Обробити(Знач Дані, Текст = "<b>,)", Кількість = 2) Експорт\n'
              'Повернути Дані;\nКінецьФункції\nОбробити(\n')
    document = SignatureDocument(source)
    signature = document.signatures['обробити'][0]
    assert signature.kind == 'function'
    assert signature.line == 1
    assert [(p.name, p.by_value, p.default_text) for p in signature.parameters] == [
        ('Дані', True, None), ('Текст', False, '"<b>,)"'), ('Кількість', False, '2')]


def test_duplicate_declarations_are_not_collapsed():
    document = SignatureDocument('Procedure Same(A)\nEndProcedure\nProcedure SAME(B)\nEndProcedure')
    assert len(document.signatures['same']) == 2


def test_comment_and_string_fake_declarations_are_not_indexed():
    document = SignatureDocument('// Function Fake(X)\nText = "Procedure Pretend(Y)";\nProcedure Real(A)\nEndProcedure')
    assert set(document.signatures) == {'real'}


def test_multiline_signature_defaults_and_empty_parameters():
    document = SignatureDocument('Procedure Empty()\nEndProcedure\nFunction Multi(\nVal A,\nB = Build(1, 2))\nEndFunction')
    assert document.signatures['empty'][0].parameters == ()
    assert document.signatures['multi'][0].parameters[1].default_text == 'Build(1, 2)'


@pytest.mark.parametrize('header', ['Procedure Bad(', 'Procedure Bad(A,)', 'Procedure Bad(,)', 'Procedure Bad(Val)', 'Procedure Bad(A = )'])
def test_incomplete_or_malformed_header_does_not_fabricate_parameters(header):
    document = SignatureDocument(header + '\nEndProcedure\nProcedure Good(A)\nEndProcedure')
    assert 'bad' not in document.signatures
    assert 'good' in document.signatures


def test_namespace_shadowing_is_scoped_and_module_variables_apply_everywhere():
    source = ('Var GlobalName, OtherName;\nProcedure First(ServerModule)\n'
              'Assigned = 1;\nVar Local;\nServerModule.Call(\nEndProcedure\n'
              'Procedure Second()\nServerModule.Call(\nEndProcedure')
    document = SignatureDocument(source)
    first = source.index('ServerModule.Call')
    second = source.rindex('ServerModule.Call')
    for name in ('ServerModule', 'Assigned', 'Local', 'GlobalName', 'OtherName'):
        assert document.is_shadowed(name, first)
    assert not document.is_shadowed('ServerModule', second)
    assert document.is_shadowed('GlobalName', second)
