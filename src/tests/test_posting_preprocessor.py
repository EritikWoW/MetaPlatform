import pytest

from src.configurator.persistence.modules_tables import MODULES_TABLE
from src.runtime.posting_engine import PostingEngine
from src.runtime.posting_script import PostingBudget, PostingError, execute_posting
from src.tests.test_posting_modules import COMMON, add_common, post, registry_for
from src.tests.test_runtime_posting import EN, header, movements, setup_db, source


def test_object_and_common_module_compile_only_server_branch(setup_db, monkeypatch):
    db, _ = setup_db
    add_common(db, '#If Client Then\ninvalid client syntax $$$;\n' + COMMON +
        '#ElsIf Server Then\n' + COMMON.replace('Document.Amount', 'Document.Amount + 1') + '#EndIf')
    add_common(db, 'invalid unused module', name='ClientOnly', guid='client-only')
    text = EN.replace('Movement.Amount = ThisObject.Amount;', 'Business.Fill(Movement, ThisObject, Cancel);')
    source(db, '#If Client Then\nClientOnly.Run();\n' + EN + '#ElseIf AtServer Then\n' + text + '#EndIf')
    loaded = []
    original = PostingEngine._source
    def read(engine, row):
        loaded.append(row['module_guid'])
        return original(engine, row)
    monkeypatch.setattr(PostingEngine, '_source', read)
    result = post(db)
    assert result.ok, result.messages
    assert movements(db)[0]['Amount'] == 43
    assert 'client-only-source' not in loaded


def test_uk_dynamic_code_selects_branch_and_propagates_reference_cancel(setup_db):
    db, _ = setup_db
    add_common(db, COMMON.replace('EndProcedure', '''Виконати "#Якщо Клієнт Тоді
|MissingModule.Fail();
|#ІнакшеЯкщо Сервер Тоді
|Cancel = Істина;
|#КінецьЯкщо";
EndProcedure'''))
    source(db, EN.replace('Movement.Amount = ThisObject.Amount;', 'Business.Fill(Movement, ThisObject, Cancel);'))
    before = header(db)
    result = post(db)
    assert not result.ok and 'cancelled' in ' '.join(result.messages), result.messages
    assert header(db) == before and not movements(db)


def test_dynamic_code_executes_preprocessed_not_raw_source(setup_db):
    db, _ = setup_db
    source(db, EN.replace('ThisObject.Amount', 'ReadAmount()') + '''
Function ReadAmount()
    Amount = 0;
    Do "#If Server Then
|Amount = 27;
|#Else
|Amount = 999;
|#EndIf";
    Return Amount;
EndFunction''')
    result = post(db)
    assert result.ok, result.messages
    assert movements(db)[0]['Amount'] == 27


@pytest.mark.parametrize('text, expected', [
    ('#If Client Then\n' + EN + '#EndIf', 'no posting handler'),
    ('#If Server Or Unknown Then\n' + EN + '#EndIf', 'Unknown compile-time symbol'),
    ('#If Server Then\n' + EN + '#Else\n#Else\n#EndIf', 'Duplicate Else'),
    (EN.replace('EndProcedure', 'Do "#Else";\nEndProcedure'), 'Unexpected'),
])
def test_bad_conditions_never_commit(setup_db, text, expected):
    db, _ = setup_db
    source(db, text)
    before = header(db)
    result = post(db)
    assert not result.ok and expected in ' '.join(result.messages), result.messages
    assert header(db) == before and not movements(db)


def test_export_in_inactive_branch_is_not_callable(setup_db):
    db, _ = setup_db
    add_common(db, '#If Client Then\n' + COMMON + '#EndIf')
    source(db, EN.replace('Movement.Amount = ThisObject.Amount;', 'Business.Fill(Movement, ThisObject, Cancel);'))
    result = post(db)
    assert not result.ok and 'Exported member not found' in ' '.join(result.messages)
    assert not header(db)['_posted'] and not movements(db)


def test_unknown_dynamic_condition_cannot_be_caught_to_fake_success(setup_db):
    db, _ = setup_db
    source(db, EN.replace('EndProcedure', '''Try
    Do "#If Typo Then
|Cancel = True;
|#EndIf";
Except
EndTry;
EndProcedure'''))
    result = post(db)
    assert not result.ok and not movements(db), result.messages


def test_conditional_hooks_and_unposting_handler_are_executed(setup_db):
    db, _ = setup_db
    source(db, EN + '''#If Server Then
Procedure UndoPosting(Cancel)
    Message("server unpost");
EndProcedure
#Else
Procedure UndoPosting(Cancel)
    Cancel = True;
EndProcedure
#EndIf''')
    db.table(MODULES_TABLE).insert(dict(module_guid='before', owner_guid='doc', module_kind='BeforePost', text=
        '#If Client Then\nCancel = True;\n#Else\nMessage("server before");\n#EndIf'))
    db.table(MODULES_TABLE).insert(dict(module_guid='after', owner_guid='doc', module_kind='AfterPost', text=
        '#If Server Then\nMessage("server after");\n#Else\nCancel = True;\n#EndIf'))
    result = post(db)
    assert result.ok and 'server before' in result.messages and 'server after' in result.messages, result.messages
    undone = PostingEngine(db).unpost(doc_name='Invoice', doc_guid='rec')
    assert undone.ok and 'server unpost' in undone.messages, undone.messages
    assert not movements(db)


def test_runtime_error_keeps_original_common_module_line():
    registry, budget = registry_for({'A': '''#If Client Then
Function Run() Export
    Return 1;
EndFunction
#Else
Function Run() Export
    Raise "selected error";
EndFunction
#EndIf'''})
    with pytest.raises(Exception, match='module://A:Run:L7: selected error'):
        registry.namespace('A').Run.invoke([])


def test_dynamic_error_and_regular_calls_have_distinct_frame_locations():
    registry, budget = registry_for({'A': '''Function Run() Export
    Do "#If Client Then
|x = 1;
|#Else
|Raise ""dynamic error"";
|#EndIf";
EndFunction'''})
    with pytest.raises(Exception, match='module://A:execute:.*L4: dynamic error'):
        registry.namespace('A').Run.invoke([])
    registry, _ = registry_for({'A': '''Function Run() Export
    Do "LocalFailure();";
EndFunction
Procedure LocalFailure()
    Raise "local error";
EndProcedure'''})
    with pytest.raises(Exception, match='module://A:LocalFailure:L5: local error'):
        registry.namespace('A').Run.invoke([])


def test_dynamic_execution_and_compilation_keep_shared_budgets():
    with pytest.raises(PostingError, match='limit exceeded'):
        execute_posting('Procedure Posting(Cancel, Mode)\nDo "#If Server Then\n|While True Do\n|EndDo\n|#EndIf";\nEndProcedure',
                        module_guid='root', context={}, budget=PostingBudget(instructions=50))
    budget = PostingBudget()
    budget.source_chars = 8000000 - 10
    with pytest.raises(PostingError, match='source size'):
        execute_posting('#If Server Then\nx = 1;\n#EndIf', module_guid='root', context={}, budget=budget)


def test_real_http_saves_conditional_common_source_without_rewriting_it(setup_db):
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
        gateway.module_update_text('object-module', '#If Server Then\n' + EN.replace(
            'Movement.Amount = ThisObject.Amount;', 'Business.Fill(Movement, ThisObject, Cancel);') + '#EndIf')
        for amount in (19, 61):
            text = '#If Client Then\n' + COMMON.replace('Document.Amount', '999') + '#ElsIf Server Then\n' + COMMON.replace('Document.Amount', str(amount)) + '#EndIf'
            gateway.module_update_text('common-source', text)
            assert gateway.module_get_text('common-source') == text
            result = gateway.document_post(doc_name='Invoice', doc_guid='rec')
            assert result.ok, result.messages
            assert movements(db)[0]['Amount'] == amount
            assert gateway.document_post(doc_name='Invoice', doc_guid='rec', post=False).ok
            assert gateway.module_get_text('common-source') == text
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
