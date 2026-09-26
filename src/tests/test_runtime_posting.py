from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from src.configurator.manifest_schema import MANIFEST_TABLE
from src.configurator.persistence.modules_tables import MODULES_TABLE
from src.mpdb.mpdb import Mpdb, Table
from src.runtime.gateway import GatewayDb, RuntimeGateway
from src.runtime.posting_engine import PostingEngine
from src.runtime.server_handlers_posting import handle_posting_action
from src.runtime.server_state import RpcResponse


EN = '''Procedure Posting(Cancel, PostingMode)
    Movements.Stock.Write = True;
    Movement = Movements.Stock.Add();
    Movement.RecordType = AccumulationRecordType.Expense;
    Movement.Amount = ThisObject.Amount;
EndProcedure
'''
UK = '''Процедура ОбробкаПроведення(Відмова, РежимПроведення)
    Рухи.Запаси.Записувати = Істина;
    Рух = Рухи.Запаси.Додати();
    Рух.ВидРуху = ВидРухуНакопичення.Витрата;
    Рух.Amount = Amount;
КінецьПроцедури
'''


@pytest.fixture
def setup_db(tmp_path):
    path = tmp_path / 'posting.mpdb'
    db = Mpdb(path, compression='zlib:6')
    db.create_table(MANIFEST_TABLE, {})
    db.create_table(MODULES_TABLE, {})
    db.create_table('data_document_invoice', {
        '_guid': {'type': 'str', 'unique': True}, '_posted': {'type': 'bool'},
        '_date': {'type': 'str'}, 'Amount': {'type': 'float'},
    })
    db.create_table('data_reg_stock', {
        '_rec_guid': {'type': 'str', 'unique': True}, '_recorder': {'type': 'str', 'indexed': True},
        '_period': {'type': 'str'}, '_kind': {'type': 'str'}, '_active': {'type': 'bool'},
        'Amount': {'type': 'float'},
    })
    db.table(MANIFEST_TABLE).insert(dict(guid='doc', name='Invoice', kind='object', type='document',
        payload={'register_records': ['AccumulationRegister.Stock']}))
    db.table(MANIFEST_TABLE).insert(dict(guid='reg', name='Stock', kind='object', type='register_accum',
        payload={'source_name': 'Запаси', 'localized_names': {'en': 'Stock', 'uk': 'Запаси'}}))
    db.table(MODULES_TABLE).insert(dict(module_guid='object-module', owner_guid='doc',
        module_kind='ObjectModule', name='ObjectModule', text=EN))
    db.table('data_document_invoice').insert(dict(_guid='rec', _date='2026-09-14', _posted=False, Amount=42))
    yield db, path
    db.close()


def source(db, text):
    db.table(MODULES_TABLE).update({'module_guid': 'object-module'}, {'text': text})


def header(db):
    return db.table('data_document_invoice').select(where={'_guid': 'rec'})[0]


def movements(db):
    return db.table('data_reg_stock').select()


@pytest.mark.parametrize('text', [EN, UK])
def test_saved_object_module_posts_unposts_and_preserves_rowid(setup_db, text):
    db, _ = setup_db
    source(db, text)
    rowid = 1
    assert db.table('data_document_invoice').select(where={'rowid': rowid})[0] == header(db)
    result = PostingEngine(db).post(doc_name='Invoice', doc_guid='rec')
    assert result.ok, result.messages
    assert result.movements_written == 1
    assert header(db)['_posted'] is True
    assert db.table('data_document_invoice').select(where={'rowid': rowid})[0] == header(db)
    assert header(db)['_posting_registers'] == ['reg']
    assert movements(db)[0]['Amount'] == 42
    assert movements(db)[0]['_kind'] == '-'
    assert movements(db)[0]['_recorder'] == 'rec'
    assert not PostingEngine(db).post(doc_name='Invoice', doc_guid='rec').ok
    assert len(movements(db)) == 1
    assert PostingEngine(db).unpost(doc_name='Invoice', doc_guid='rec').ok
    assert not header(db)['_posted']
    assert not movements(db)
    assert PostingEngine(db).post(doc_name='Invoice', doc_guid='rec').ok


@pytest.mark.parametrize('text, error', [
    (EN.replace('EndProcedure', 'Cancel = True;\nEndProcedure'), 'cancelled'),
    (EN.replace('ThisObject.Amount', 'MissingModule.Calculate()'), 'not defined'),
    (EN.replace('Movement.Amount', 'Movement.Typo'), 'Unknown movement field'),
    (EN.replace('ThisObject.Amount', '"not a number"'), 'Invalid movement value'),
    (EN.replace('EndProcedure', ''), 'Invalid object module'),
    ('Procedure Posting(Cancel, Mode)\nMovements.Stock.Write = True;\nEndProcedure', 'no movements'),
    ('Procedure Posting(Cancel, Mode)\nWhile True Do\nEndDo\nEndProcedure', 'limit exceeded'),
    ('Procedure SomethingElse()\nEndProcedure', 'no posting handler'),
    (EN.replace('Movements.Stock.Write = True;', ''), 'without enabling Write'),
    (EN.replace('Movement.RecordType = AccumulationRecordType.Expense;', ''), 'RecordType'),
    (EN + EN, 'Multiple'),
    ('Procedure Posting(Cancel, Mode)\nStopPosting(Cancel);\nEndProcedure\n'
     'Procedure StopPosting(Cancel)\nCancel = True;\nEndProcedure', 'cancelled'),
])
def test_failure_never_marks_posted_or_keeps_movements(setup_db, text, error):
    db, _ = setup_db
    source(db, text)
    before = header(db)
    result = PostingEngine(db).post(doc_name='Invoice', doc_guid='rec')
    assert not result.ok
    assert error.casefold() in ' '.join(result.messages).casefold(), result.messages
    assert result.movements_written == 0
    assert header(db) == before
    assert movements(db) == []


@pytest.mark.parametrize('hook', ['BeforePost', 'AfterPost'])
def test_hook_cancellation_is_atomic(setup_db, hook):
    db, _ = setup_db
    db.table(MODULES_TABLE).insert(dict(module_guid='hook', owner_guid='doc',
        module_kind=hook, name=hook, text='Cancel = True;'))
    result = PostingEngine(db).post(doc_name='Invoice', doc_guid='rec')
    assert not result.ok, result.messages
    assert not header(db)['_posted']
    assert not movements(db)


def test_partial_insert_failure_rolls_back_header_and_all_rows(setup_db, monkeypatch):
    db, path = setup_db
    source(db, EN.replace('EndProcedure', 'Other = Movements.Stock.Add();\nOther.RecordType = "-";\nOther.Amount = 7;\nEndProcedure'))
    before = header(db)
    original = Table.insert_tx
    count = 0
    def fail_second(table, tx, row, **kwargs):
        nonlocal count
        if table.name == 'data_reg_stock':
            count += 1
            if count == 2:
                raise RuntimeError('injected storage failure')
        return original(table, tx, row, **kwargs)
    monkeypatch.setattr(Table, 'insert_tx', fail_second)
    result = PostingEngine(db).post(doc_name='Invoice', doc_guid='rec')
    assert not result.ok and count == 2, result.messages
    assert header(db) == before
    assert not movements(db)
    db.close()
    reopened = Mpdb(path)
    try:
        assert header(reopened) == before
        assert not movements(reopened)
    finally:
        reopened.close()


def test_unpost_delete_failure_rolls_back_flag(setup_db, monkeypatch):
    db, _ = setup_db
    assert PostingEngine(db).post(doc_name='Invoice', doc_guid='rec').ok
    before = movements(db)
    monkeypatch.setattr(Table, 'delete_tx', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('delete failed')))
    result = PostingEngine(db).unpost(doc_name='Invoice', doc_guid='rec')
    assert not result.ok
    assert header(db)['_posted']
    assert movements(db) == before


def test_simultaneous_requests_do_not_duplicate_movements(setup_db):
    db, _ = setup_db
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: PostingEngine(db).post(doc_name='Invoice', doc_guid='rec'), range(2)))
    assert sum(result.ok for result in results) == 1
    assert len(movements(db)) == 1


def test_runtime_gateway_routes_one_atomic_request(setup_db, monkeypatch):
    db, _ = setup_db
    handler = SimpleNamespace(_require_db=lambda payload: db)
    gw = RuntimeGateway('http://127.0.0.1:1')
    gw.session_id = 'test-session'
    calls = []
    def call(action, payload, **kwargs):
        calls.append((action, payload))
        result = handle_posting_action(handler, action, payload)
        assert result.status == 'ok', result.error
        return result.data
    monkeypatch.setattr(gw, '_call', call)
    assert GatewayDb(gw).document_post(doc_name='Invoice', doc_guid='rec').ok
    assert calls == [('document.post', {'session_id': 'test-session', 'doc_name': 'Invoice', 'doc_guid': 'rec'})]
    assert GatewayDb(gw).document_post(doc_name='Invoice', doc_guid='rec', post=False).ok
    assert calls[-1][0] == 'document.unpost'


def test_runtime_requires_a_database_session():
    handler = SimpleNamespace(_require_db=lambda payload: RpcResponse('error', error='no session'))
    result = handle_posting_action(handler, 'document.post', {})
    assert result.status == 'error' and result.error == 'no session'
    assert handle_posting_action(handler, 'other', {}) is None


def test_real_http_roundtrip_posts_and_unposts(setup_db):
    import threading
    from http.server import ThreadingHTTPServer
    from src.runtime.server import RuntimeHandler

    db, _ = setup_db
    class TestHandler(RuntimeHandler):
        def _require_db(self, payload):
            if payload.get('session_id') != 'isolated-test':
                return RpcResponse('error', error='invalid test session')
            return db

    server = ThreadingHTTPServer(('127.0.0.1', 0), TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    gateway = RuntimeGateway(f'http://127.0.0.1:{server.server_port}')
    gateway.session_id = 'isolated-test'
    try:
        assert gateway.table_update('data_document_invoice', {'_guid': 'rec'}, {'Amount': 51}) == 1
        result = GatewayDb(gateway).document_post(doc_name='Invoice', doc_guid='rec')
        assert result.ok, result.messages
        assert result.movements_written == 1
        assert header(db)['_posted'] and len(movements(db)) == 1
        with pytest.raises(RuntimeError, match='Unpost'):
            gateway.table_update('data_document_invoice', {'_guid': 'rec'}, {'Amount': 1})
        assert GatewayDb(gateway).document_post(doc_name='Invoice', doc_guid='rec', post=False).ok
        assert not header(db)['_posted'] and not movements(db)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_unpost_cleans_recorded_register_after_configuration_selection_changes(setup_db):
    db, _ = setup_db
    assert PostingEngine(db).post(doc_name='Invoice', doc_guid='rec').ok
    db.table(MANIFEST_TABLE).update({'guid': 'doc'}, {'payload': {'register_records': []}})
    result = PostingEngine(db).unpost(doc_name='Invoice', doc_guid='rec')
    assert result.ok, result.messages
    assert not movements(db)


def test_handler_reads_only_this_document_tabular_rows(setup_db):
    db, _ = setup_db
    db.table(MANIFEST_TABLE).insert(dict(guid='tps', parent_guid='doc', type='tabular_parts', kind='folder'))
    db.table(MANIFEST_TABLE).insert(dict(guid='tp', parent_guid='tps', type='tabular_part', kind='object', name='Lines'))
    db.create_table('data_tp_invoice_lines', {})
    for record, amount in [('rec', 5), ('another', 1000), ('rec', 7)]:
        db.table('data_tp_invoice_lines').insert({'_doc_guid': record, 'Amount': amount, '_line_no': amount})
    source(db, '''Procedure Posting(Cancel, Mode)
    Movements.Stock.Write = True;
    For Each Line In Lines Do
        Movement = Movements.Stock.Add();
        Movement.RecordType = "-";
        Movement.Amount = Line.Amount;
    EndDo;
EndProcedure''')
    result = PostingEngine(db).post(doc_name='Invoice', doc_guid='rec')
    assert result.ok, result.messages
    assert [r['Amount'] for r in movements(db)] == [5, 7]


@pytest.mark.parametrize('failure', ['missing_module', 'manager_only', 'ambiguous_module', 'missing_register', 'bad_asset'])
def test_incomplete_metadata_fails_closed(setup_db, failure):
    db, _ = setup_db
    if failure == 'missing_module':
        db.table(MODULES_TABLE).delete({'module_guid': 'object-module'})
    elif failure == 'manager_only':
        db.table(MODULES_TABLE).update({'module_guid': 'object-module'}, {'module_kind': 'ManagerModule'})
    elif failure == 'ambiguous_module':
        db.table(MODULES_TABLE).insert(dict(module_guid='other', owner_guid='doc', module_kind='ObjectModule', text=EN))
    elif failure == 'missing_register':
        db.table(MANIFEST_TABLE).delete({'guid': 'reg'})
    else:
        db.table(MODULES_TABLE).update({'module_guid': 'object-module'}, {'storage_kind': 'asset', 'content_ref': 'absent'})
    result = PostingEngine(db).post(doc_name='Invoice', doc_guid='rec')
    assert not result.ok
    assert not header(db)['_posted']
    assert not movements(db)


def test_explicit_information_register_rows(setup_db):
    db, _ = setup_db
    db.table(MANIFEST_TABLE).update({'guid': 'reg'}, {'type': 'register_info'})
    db.table(MANIFEST_TABLE).update({'guid': 'doc'}, {'payload': {'register_records': ['InformationRegister.Stock']}})
    source(db, EN.replace('Movement.RecordType = AccumulationRecordType.Expense;', ''))
    result = PostingEngine(db).post(doc_name='Invoice', doc_guid='rec')
    assert result.ok, result.messages
    assert movements(db)[0]['Amount'] == 42


def test_saved_asset_source_and_value_helper_are_executable(setup_db):
    db, _ = setup_db
    text = EN.replace('ThisObject.Amount', 'Double(ThisObject.Amount)')
    text += '\nFunction Double(Val Amount)\nReturn Amount * 2;\nEndFunction'
    db.put_asset('saved-source', text.encode('utf-8'), mime='text/plain')
    db.table(MODULES_TABLE).update({'module_guid': 'object-module'},
                                 {'storage_kind': 'asset', 'content_ref': 'saved-source', 'text': ''})
    result = PostingEngine(db).post(doc_name='Invoice', doc_guid='rec')
    assert result.ok, result.messages
    assert movements(db)[0]['Amount'] == 84


def test_unpost_rejects_unknown_legacy_movement_inventory(setup_db):
    db, _ = setup_db
    db.table('data_document_invoice').update({'_guid': 'rec'}, {'_posted': True})
    result = PostingEngine(db).unpost(doc_name='Invoice', doc_guid='rec')
    assert not result.ok and 'inventory' in ' '.join(result.messages)
    assert header(db)['_posted']


def test_cancel_from_unposting_handler_keeps_existing_movements(setup_db):
    db, _ = setup_db
    assert PostingEngine(db).post(doc_name='Invoice', doc_guid='rec').ok
    source(db, EN + '\nProcedure UndoPosting(Cancel)\nCancel = True;\nEndProcedure')
    before = movements(db)
    result = PostingEngine(db).unpost(doc_name='Invoice', doc_guid='rec')
    assert not result.ok
    assert header(db)['_posted']
    assert movements(db) == before


def test_generic_document_rpcs_cannot_bypass_posting(setup_db, monkeypatch):
    import src.runtime.server_handlers_table as tables
    db, _ = setup_db
    # Native-only routing, with real storage and document guards.
    virtual = SimpleNamespace(handle_select=lambda *a: (False, None),
                              handle_insert=lambda *a: (False, None),
                              handle_update=lambda *a: (False, None),
                              handle_delete=lambda *a: (False, None))
    monkeypatch.setattr(tables, 'get_virtual_data_tables', lambda db: virtual)
    handler = SimpleNamespace(_require_db=lambda payload: db)
    base = {'table': 'data_document_invoice', 'where': {'_guid': 'rec'}}
    forged = tables.handle_table_action(handler, 'table.update', dict(base, values={'_posted': True}))
    assert forged.status == 'error'
    forged = tables.handle_table_action(handler, 'table.insert', dict(base, row={'_guid': 'other', '_posted': True}))
    assert forged.status == 'error'
    update = tables.handle_table_action(handler, 'table.update', dict(base, values={'Amount': 84, '_posted': False}))
    assert update.status == 'ok'
    assert PostingEngine(db).post(doc_name='Invoice', doc_guid='rec').ok
    for action, values in [('table.update', {'Amount': 1}), ('table.update', {'_posted': False}), ('table.delete', {})]:
        response = tables.handle_table_action(handler, action, dict(base, values=values))
        assert response.status == 'error'
    assert header(db)['_posted'] and header(db)['Amount'] == 84
    assert len(movements(db)) == 1
    assert PostingEngine(db).unpost(doc_name='Invoice', doc_guid='rec').ok
    update = tables.handle_table_action(handler, 'table.update', dict(base, values={'Amount': 1}))
    assert update.status == 'ok'


def test_posting_invalidates_cached_native_projection(setup_db, monkeypatch):
    from src.runtime.onec_virtual_tables import _ADAPTERS
    db, _ = setup_db
    cache = {'data_document_invoice': [header(db)]}
    monkeypatch.setitem(_ADAPTERS, id(db), SimpleNamespace(physical_rows_cache=cache))
    result = PostingEngine(db).post(doc_name='Invoice', doc_guid='rec')
    assert result.ok, result.messages
    assert cache == {}
