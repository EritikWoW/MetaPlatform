from __future__ import annotations

from src.infra.onec.physical_schema import _load_parse1cd_backend


def _backend():
    _parser_root, backend = _load_parse1cd_backend()
    return backend


def test_parse1cd_bcd_examples_follow_tool1cd_spec() -> None:
    backend = _backend()
    db = backend.OneCDatabase("dummy")

    assert db._parse_bcd(bytes([0x18, 0x47, 0x23]), 5, 3) == 84.723
    assert db._parse_bcd(bytes([0x00, 0x00, 0x91]), 5, 3) == -0.091


def test_parse1cd_datetime_uses_7_byte_bcd_layout() -> None:
    backend = _backend()
    db = backend.OneCDatabase("dummy")
    field = backend.Field(
        name="_PERIOD",
        type=backend.FieldType.DATETIME,
        null_exists=False,
        length=0,
        precision=0,
        case_sensitive="CS",
        offset=0,
    )

    value = db._parse_val(field, bytes([0x20, 0x26, 0x05, 0x21, 0x13, 0x45, 0x59]))

    assert value == "2026-05-21 13:45:59"


def test_parse1cd_layout_moves_version_first_and_adds_hidden_version() -> None:
    backend = _backend()
    db = backend.OneCDatabase("dummy")

    version = backend.Field(
        name="_VERSION",
        type=backend.FieldType.VERSION,
        null_exists=False,
        length=0,
        precision=0,
        case_sensitive="CS",
        offset=0,
    )
    name = backend.Field(
        name="NAME",
        type=backend.FieldType.VAR_STRING,
        null_exists=False,
        length=10,
        precision=0,
        case_sensitive="CI",
        offset=0,
    )
    tbl = backend.Table(name="T", fields=[name, version], recordlock="0")
    db._apply_physical_layout(tbl)

    assert [field.name for field in tbl.fields] == ["_VERSION", "NAME"]
    assert tbl.fields[0].offset == 1
    assert tbl.fields[1].offset == 17

    period = backend.Field(
        name="_PERIOD",
        type=backend.FieldType.DATETIME,
        null_exists=False,
        length=0,
        precision=0,
        case_sensitive="CS",
        offset=0,
    )
    flag = backend.Field(
        name="FLAG",
        type=backend.FieldType.BOOLEAN,
        null_exists=False,
        length=0,
        precision=0,
        case_sensitive="CS",
        offset=0,
    )
    locked = backend.Table(name="LOCKED", fields=[period, flag], recordlock="1")
    db._apply_physical_layout(locked)

    assert [field.offset for field in locked.fields] == [9, 16]
    assert locked.row_size == 17


def test_parse1cd_numeric_field_size_matches_tool1cd_formula() -> None:
    backend = _backend()
    db = backend.OneCDatabase("dummy")

    assert db._base_fsize(backend.FieldType.NUMBER, 5) == 3
    assert db._base_fsize(backend.FieldType.NUMBER, 10) == 6


def test_parse1cd_variable_binary_uses_declared_inline_width_and_stays_raw() -> None:
    backend = _backend()
    db = backend.OneCDatabase("dummy")
    fields = db._parse_fields('{"STORAGEID","VB",0,16,0,"CS"}')
    table = backend.Table(name="BINARY_DATA", fields=fields, recordlock="0")

    db._apply_physical_layout(table)

    assert fields[0].type == backend.FieldType.VARIABLE_BINARY
    assert fields[0].offset == 1
    assert table.row_size == 17
    assert db._decode_field(fields[0], bytes(range(16)), None, False) == bytes(range(16))


def test_parse1cd_indexes_include_field_list() -> None:
    backend = _backend()
    db = backend.OneCDatabase("dummy")

    text = (
        '{"Indexes",'
        '{"_IDRREFIDX",1,{"_IDRREF",16}},'
        '{"_REFERENCE4_CODE_SR",0,{"_CODE",9},{"_IDRREF",16}}'
        "}"
    )

    indexes = db._parse_indexes(text)

    assert len(indexes) == 2
    assert indexes[0].name == "_IDRREFIDX"
    assert indexes[0].unique is True
    assert [field.name for field in indexes[0].fields] == ["_IDRREF"]
    assert indexes[1].name == "_REFERENCE4_CODE_SR"
    assert [field.name for field in indexes[1].fields] == ["_CODE", "_IDRREF"]
