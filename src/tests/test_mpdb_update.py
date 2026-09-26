from __future__ import annotations


import pytest

from mpdb.mpdb import Mpdb, MpdbError


def test_update_keeps_rowid_and_maintains_secondary_indexes(tmp_path):
    db_path = tmp_path / "u.mpdb"
    db = Mpdb(db_path, page_size=16384, compression="zlib:6", cache_mb=8)
    db.create_table(
        "t",
        {
            "name": {"type": "str", "indexed": True},
            "qty": {"type": "int"},
        },
    )

    t = db.table("t")
    r1 = t.insert({"name": "a", "qty": 1})
    r2 = t.insert({"name": "b", "qty": 2})
    t.insert({"name": "c", "qty": 3})

    assert db.query("t", where={"name": "b"}) == [{"name": "b", "qty": 2}]

    updated = t.update({"name": "b"}, {"name": "bb", "qty": 20})
    assert updated == 1

    # old key should no longer match
    assert db.query("t", where={"name": "b"}) == []
    # new key should match
    assert db.query("t", where={"name": "bb"}) == [{"name": "bb", "qty": 20}]

    # order_by should reflect the updated value
    rows = db.query("t", order_by="name")
    assert [x["name"] for x in rows] == ["a", "bb", "c"]

    # rowid remains stable: delete by original rowid removes the updated row
    assert t.delete({"rowid": r2}) == 1
    assert db.query("t", where={"name": "bb"}) == []

    # cleanup
    assert t.delete({"rowid": r1}) == 1
    db.close()


def test_update_respects_unique_index(tmp_path):
    db_path = tmp_path / "uuniq.mpdb"
    db = Mpdb(db_path, page_size=16384, compression="zlib:6", cache_mb=8)
    db.create_table(
        "t",
        {
            "code": {"type": "str", "unique": True},
            "qty": {"type": "int"},
        },
    )
    t = db.table("t")
    t.insert({"code": "A", "qty": 1})
    t.insert({"code": "B", "qty": 2})

    with pytest.raises(MpdbError):
        t.update({"code": "B"}, {"code": "A"})

    db.close()


def test_update_tx_rolls_back_with_other_table_writes(tmp_path):
    db = Mpdb(tmp_path / 'atomic.mpdb', compression='zlib:6')
    try:
        db.create_table('header', {'key': {'unique': True}, 'value': {'indexed': True}})
        db.create_table('lines', {})
        rowid = db.table('header').insert({'key': 'doc', 'value': 'old'})
        with pytest.raises(RuntimeError, match='abort'):
            with db.transaction() as tx:
                db.table('header').update_tx(tx, {'key': 'doc'}, {'value': 'new'})
                db.table('lines').insert_tx(tx, {'owner': 'doc'})
                raise RuntimeError('abort')
        assert db.table('header').select({'rowid': rowid}) == [{'key': 'doc', 'value': 'old'}]
        assert db.table('header').select({'value': 'new'}) == []
        assert db.table('lines').select() == []
        with db.transaction() as tx:
            assert db.table('header').update_tx(tx, {'key': 'doc'}, {'value': 'new'}) == 1
            db.table('lines').insert_tx(tx, {'owner': 'doc'})
        assert db.table('header').select({'rowid': rowid}) == [{'key': 'doc', 'value': 'new'}]
        assert db.table('header').select({'value': 'old'}) == []
    finally:
        db.close()


def test_update_tx_rejects_stale_reads_of_pending_table_rows(tmp_path):
    db = Mpdb(tmp_path / 'pending.mpdb', compression='zlib:6')
    try:
        db.create_table('t', {})
        db.table('t').insert({'key': 'doc', 'value': 'old'})
        with pytest.raises(MpdbError, match='precede'):
            with db.transaction() as tx:
                db.table('t').update_tx(tx, {'key': 'doc'}, {'value': 'one'})
                db.table('t').update_tx(tx, {'key': 'doc'}, {'value': 'two'})
        assert db.table('t').select() == [{'key': 'doc', 'value': 'old'}]
    finally:
        db.close()
