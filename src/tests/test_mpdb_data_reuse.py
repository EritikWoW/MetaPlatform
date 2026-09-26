import json


from mpdb.mpdb import (
    _data_page_get_record,
    _data_page_init,
    _data_page_insert,
    _data_page_mark_deleted,
    DATA_HDR,
)


def _rec(i: int) -> bytes:
    # same encoding as Table: {rowid:int, data:dict}
    return json.dumps({"rowid": i, "data": {"v": i}}, ensure_ascii=False).encode("utf-8")


def test_data_page_reuses_tombstone_slot_without_growing_slot_count() -> None:
    payload = _data_page_init(512)

    # Insert 5 records -> slots 0..4
    slots = []
    for i in range(5):
        payload, slot_pos = _data_page_insert(payload, _rec(i + 1))
        slots.append(slot_pos)
    assert slots == [0, 1, 2, 3, 4]

    # Delete newest slot (slot_pos=4)
    payload = _data_page_mark_deleted(payload, 4)

    # Insert again: should reuse slot_pos=4, not create slot_pos=5
    payload2, slot_pos2 = _data_page_insert(payload, _rec(999))
    assert slot_pos2 == 4

    # slot_count must remain 5
    _magic, _ver, slot_count, _fs, _fe, _flags, _res = DATA_HDR.unpack_from(payload2, 0)
    assert int(slot_count) == 5

    # record is accessible via reused slot_pos
    raw = _data_page_get_record(payload2, 4)
    obj = json.loads(raw.decode("utf-8"))
    assert obj["rowid"] == 999
