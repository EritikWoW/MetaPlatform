import pytest

from src.configurator.manifest_schema import MANIFEST_TABLE
from src.configurator.persistence.modules_tables import MODULES_TABLE
from src.runtime.posting_engine import PostingEngine
from src.runtime.posting_modules import PostingModuleRegistry
from src.runtime.posting_script import PostingBudget, PostingError, execute_posting
from src.tests.test_runtime_posting import EN, header, movements, setup_db, source


COMMON = '''Procedure Fill(Movement, Val Document, Cancel) Export
    Movement.Amount = Document.Amount;
EndProcedure
'''


def add_common(db, text=COMMON, *, name='Business', guid='common', **payload):
    db.table(MANIFEST_TABLE).insert(dict(guid=guid, name=name, title='FriendlyTitle',
        kind='object', type='common_module', payload=dict(server=True, **payload)))
    db.table(MODULES_TABLE).insert(dict(module_guid=guid + '-source', owner_guid=guid,
        module_kind='Module', name='Module', text=text))


def post(db):
    return PostingEngine(db).post(doc_name='Invoice', doc_guid='rec')


@pytest.mark.parametrize('alias', ['Business', 'Облік', 'Учет', 'BOOKKEEPING', 'Legacy',
                                  'CommonModule.Bookkeeping', 'ЗагальнийМодуль.Облік'])
def test_technical_aliases_and_reference_parameters_execute_saved_module(setup_db, alias):
    db, _ = setup_db
    add_common(db, source_name='Учет', localized_names={'uk': 'Облік', 'en': 'Bookkeeping'},
               code_refs={'uk': 'ЗагальнийМодуль.Облік', 'en': 'CommonModule.Bookkeeping'},
               legacy_code_refs=['CommonModule.Legacy.Module'])
    source(db, EN.replace('Movement.Amount = ThisObject.Amount;',
                          f'{alias}.fIlL(Movement, ThisObject, Cancel);'))
    result = post(db)
    assert result.ok, result.messages
    assert movements(db)[0]['Amount'] == 42


def test_nested_uk_call_propagates_cancel_and_rolls_back(setup_db):
    db, _ = setup_db
    add_common(db, COMMON.replace('EndProcedure', 'Перевірки.Зупинити(Cancel);\nEndProcedure'))
    add_common(db, 'Процедура Зупинити(Відмова) Експорт\nВідмова = Істина;\nКінецьПроцедури',
               name='Перевірки', guid='checks')
    source(db, EN.replace('Movement.Amount = ThisObject.Amount;', 'Business.Fill(Movement, ThisObject, Cancel);'))
    before = header(db)
    result = post(db)
    assert not result.ok and 'cancelled' in ' '.join(result.messages), result.messages
    assert header(db) == before
    assert not movements(db)


@pytest.mark.parametrize('text, error', [
    (COMMON.replace(' Export', ''), 'Exported member not found'),
    (COMMON.replace('Fill(', 'Other('), 'Exported member not found'),
    (COMMON.replace('Document.Amount;', 'ThisObject.Amount;'), "Name 'ThisObject'"),
    (COMMON.replace('Movement.Amount = Document.Amount;', 'Document.Amount = 0;'), 'read-only'),
    (COMMON.replace('EndProcedure', ''), 'Invalid object module'),
    (COMMON.replace('EndProcedure', 'Raise "business failure";\nEndProcedure'), 'business failure'),
    ('&AtClient\n' + COMMON, 'Unsupported posting annotation'),
    ('#If UnknownContext Then\n' + COMMON + '#EndIf', 'Unknown compile-time symbol'),
    (COMMON.replace('EndProcedure', 'Do "#If UnknownContext Then\n|x = 1;\n|#EndIf";\nEndProcedure'),
     'Unknown compile-time symbol'),
])
def test_invalid_common_module_is_not_silently_ignored(setup_db, text, error):
    db, _ = setup_db
    add_common(db, text)
    source(db, EN.replace('Movement.Amount = ThisObject.Amount;', 'Business.Fill(Movement, ThisObject, Cancel);'))
    before = header(db)
    result = post(db)
    assert not result.ok, result.messages
    assert error in ' '.join(result.messages), result.messages
    assert header(db) == before and not movements(db)
    if error == 'business failure':
        assert 'module://common-source:Fill:L3' in ' '.join(result.messages)


@pytest.mark.parametrize('problem', ['synonym', 'missing_source', 'wrong_kind', 'duplicate_source',
                                    'duplicate_alias', 'client_only', 'unknown_server'])
def test_metadata_identity_and_server_flags_are_strict(setup_db, problem):
    db, _ = setup_db
    add_common(db)
    call = 'Business.Fill(Movement, ThisObject, Cancel);'
    if problem == 'synonym':
        call = call.replace('Business', 'FriendlyTitle')
    elif problem == 'missing_source':
        db.table(MODULES_TABLE).delete({'owner_guid': 'common'})
    elif problem == 'wrong_kind':
        db.table(MODULES_TABLE).update({'owner_guid': 'common'}, {'module_kind': 'ManagerModule'})
    elif problem == 'duplicate_source':
        db.table(MODULES_TABLE).insert(dict(module_guid='extra', owner_guid='common', module_kind='Module', text=COMMON))
    elif problem == 'duplicate_alias':
        add_common(db, name='Other', guid='duplicate', source_name='Business')
    else:
        db.table(MANIFEST_TABLE).update({'guid': 'common'},
            {'payload': {'server': False} if problem == 'client_only' else {}})
    source(db, EN.replace('Movement.Amount = ThisObject.Amount;', call))
    before = header(db)
    result = post(db)
    assert not result.ok, result.messages
    assert header(db) == before and not movements(db)


def test_guard_failure_cannot_be_caught_and_committed(setup_db):
    db, _ = setup_db
    add_common(db, COMMON.replace(' Export', ''))
    source(db, EN.replace('EndProcedure',
        'Try\nBusiness.Fill(Movement, ThisObject, Cancel);\nExcept\nEndTry;\nEndProcedure'))
    result = post(db)
    assert not result.ok and not movements(db), result.messages


def test_business_exception_can_be_handled_explicitly(setup_db):
    db, _ = setup_db
    add_common(db, 'Procedure Fail() Export\nRaise "validation";\nEndProcedure')
    source(db, EN.replace('EndProcedure',
        'Try\nBusiness.Fail();\nExcept\nMovement.Amount = 11;\nEndTry;\nEndProcedure'))
    result = post(db)
    assert result.ok, result.messages
    assert movements(db)[0]['Amount'] == 11


def test_aliases_share_state_but_next_post_loads_latest_source(setup_db, monkeypatch):
    db, _ = setup_db
    add_common(db, '''Var Counter;
Function Next() Export
    Counter = Counter + 1;
    Return Counter;
EndFunction
Counter = 0;
''', localized_names={'uk': 'Облік'})
    add_common(db, 'not executable', guid='unused', name='Unused')
    source(db, EN.replace('ThisObject.Amount', 'Business.Next() + Облік.Next()'))
    loaded = []
    read_source = PostingEngine._source
    def record_load(engine, row):
        loaded.append(row['module_guid'])
        return read_source(engine, row)
    monkeypatch.setattr(PostingEngine, '_source', record_load)
    assert post(db).ok
    assert movements(db)[0]['Amount'] == 3
    assert loaded.count('common-source') == 1 and 'unused-source' not in loaded
    assert PostingEngine(db).unpost(doc_name='Invoice', doc_guid='rec').ok
    assert post(db).ok
    assert movements(db)[0]['Amount'] == 3
    assert PostingEngine(db).unpost(doc_name='Invoice', doc_guid='rec').ok
    db.table(MODULES_TABLE).update({'module_guid': 'common-source'}, {'text':
        'Function Next() Export\nReturn 10;\nEndFunction'})
    assert post(db).ok
    assert movements(db)[0]['Amount'] == 20


def test_common_state_is_shared_with_hooks(setup_db):
    db, _ = setup_db
    add_common(db, '''Var Amount;
Procedure SetAmount(Val Value) Export
    Amount = Value;
EndProcedure
Function GetAmount() Export
    Return Amount;
EndFunction
''')
    db.table(MODULES_TABLE).insert(dict(module_guid='before', owner_guid='doc', module_kind='BeforePost',
                                       text='Business.SetAmount(11);'))
    source(db, EN.replace('ThisObject.Amount', 'Business.GetAmount()'))
    result = post(db)
    assert result.ok, result.messages
    assert movements(db)[0]['Amount'] == 11


def registry_for(sources, *, budget=None):
    budget = budget or PostingBudget()
    rows = [dict(name=name, guid=name, type='common_module', payload={'server': True}) for name in sources]
    return PostingModuleRegistry(rows, modules=lambda guid: [dict(module_kind='Module', module_guid=guid, text=sources[guid])],
                                 source=lambda row: row['text'], budget=budget, context={}), budget


@pytest.mark.parametrize('sources, message', [
    ({'A': 'Function Run() Export\nReturn B.Run();\nEndFunction',
      'B': 'Function Run() Export\nReturn A.Run();\nEndFunction'}, 'call depth'),
    ({'A': 'Function Run() Export\nWhile True Do\nEndDo\nEndFunction'}, 'execution limit'),
    ({'A': 'Function Run() Export\nReturn 1;\nEndFunction\nx = B.Run();',
      'B': 'Function Run() Export\nReturn 1;\nEndFunction\nx = A.Run();'}, 'Cyclic'),
])
def test_shared_limits_and_initialization_cycles(sources, message):
    registry, budget = registry_for(sources, budget=PostingBudget(instructions=500, depth=8))
    with pytest.raises(PostingError, match=message):
        execute_posting('Procedure Posting(Cancel, Mode)\nx = A.Run();\nEndProcedure',
                        module_guid='root', context={}, registry=registry, budget=budget)
    assert budget.depth == 0


def test_instruction_budget_not_reset_between_modules_or_hooks():
    registry, budget = registry_for({'A': 'Function Run() Export\nReturn 1;\nEndFunction'},
                                   budget=PostingBudget(instructions=30))
    def run():
        execute_posting('x = A.Run();', module_guid='hook', context={}, hook='BeforePost',
                        registry=registry, budget=budget)
    run()
    first = budget.remaining
    run()
    assert budget.remaining < first
    with pytest.raises(PostingError, match='limit exceeded'):
        for _ in range(30):
            run()


def test_argument_arity_and_defaults():
    registry, budget = registry_for({'A': 'Function Run(Val X, Val Y = 4) Export\nReturn X + Y;\nEndFunction'})
    member = registry.namespace('A').Run
    assert member.invoke([3]) == 7
    with pytest.raises(PostingError, match='argument count'):
        member.invoke([])
    with pytest.raises(PostingError, match='argument count'):
        member.invoke([1, 2, 3])


def test_nonliteral_defaults_are_not_silently_converted_to_undefined():
    registry, _ = registry_for({'A': 'Function Run(X = 2 + 3) Export\nReturn X;\nEndFunction'})
    with pytest.raises(PostingError, match='non-literal parameter default'):
        registry.namespace('A').Run


@pytest.mark.parametrize('target, succeeds', [('Movement.Amount', True), ('ThisObject.Amount', False)])
def test_scalar_field_reference_across_module_boundary(setup_db, target, succeeds):
    db, _ = setup_db
    add_common(db, 'Procedure Change(Value) Export\nValue = 13;\nEndProcedure')
    source(db, EN.replace('EndProcedure', f'Business.Change({target});\nEndProcedure'))
    result = post(db)
    assert result.ok is succeeds, result.messages
    assert header(db)['Amount'] == 42
    if succeeds:
        assert movements(db)[0]['Amount'] == 13
    else:
        assert not header(db)['_posted'] and not movements(db)


def test_module_count_limit_is_shared():
    registry, budget = registry_for({'A': 'Function Run() Export\nReturn B.Run();\nEndFunction',
                                    'B': 'Function Run() Export\nReturn 1;\nEndFunction'},
                                   budget=PostingBudget(modules=1))
    with pytest.raises(PostingError, match='limit exceeded: common modules'):
        registry.namespace('A').Run.invoke([])


def test_region_and_server_annotation_supported():
    registry, budget = registry_for({'A': '#Region API\n&AtServer\n'
        'Function Run() Export\nReturn 7;\nEndFunction\n#EndRegion'})
    assert registry.namespace('A').Run.invoke([]) == 7


def test_zero_division_reports_actual_common_module_line():
    registry, _ = registry_for({'A': 'Function Run() Export\nReturn 1 / 0;\nEndFunction'})
    with pytest.raises(Exception, match='module://A:Run:L2: Division by zero'):
        registry.namespace('A').Run.invoke([])


def test_cannot_pass_independent_budget_to_root_vm():
    registry, _ = registry_for({})
    with pytest.raises(PostingError, match='share the operation budget'):
        execute_posting('x = 1;', module_guid='root', context={}, hook='BeforePost',
                        registry=registry, budget=PostingBudget())


@pytest.mark.parametrize('missing', [False, True])
def test_common_module_asset_is_read_instead_of_stale_inline_source(setup_db, missing):
    db, _ = setup_db
    add_common(db, 'inline source must not be executed')
    if not missing:
        db.put_asset('common-source-asset', COMMON.encode('utf-8-sig'), mime='text/plain')
    db.table(MODULES_TABLE).update({'module_guid': 'common-source'},
        {'storage_kind': 'asset', 'content_ref': 'common-source-asset'})
    source(db, EN.replace('Movement.Amount = ThisObject.Amount;', 'Business.Fill(Movement, ThisObject, Cancel);'))
    result = post(db)
    assert result.ok is not missing, result.messages
    if missing:
        assert not header(db)['_posted'] and not movements(db)
    else:
        assert movements(db)[0]['Amount'] == 42


def test_http_saved_common_module_changes_are_used_on_next_post(setup_db):
    import threading
    from http.server import ThreadingHTTPServer
    from src.runtime.gateway import RuntimeGateway
    from src.runtime.server import RuntimeHandler
    from src.runtime.server_state import RpcResponse
    db, _ = setup_db
    add_common(db)

    class Handler(RuntimeHandler):
        def _require_db(self, payload):
            return db if payload.get('session_id') == 'test' else RpcResponse('error', error='session required')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    gateway = RuntimeGateway(f'http://127.0.0.1:{server.server_port}')
    gateway.session_id = 'test'
    try:
        gateway.module_update_text('object-module', EN.replace('Movement.Amount = ThisObject.Amount;',
            'Business.Fill(Movement, ThisObject, Cancel);'))
        for value in (12, 34):
            text = COMMON.replace('Document.Amount', str(value))
            gateway.module_update_text('common-source', text)
            assert gateway.module_get_text('common-source') == text
            result = gateway.document_post(doc_name='Invoice', doc_guid='rec')
            assert result.ok, result.messages
            assert movements(db)[0]['Amount'] == value
            assert gateway.document_post(doc_name='Invoice', doc_guid='rec', post=False).ok
            assert not movements(db)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
