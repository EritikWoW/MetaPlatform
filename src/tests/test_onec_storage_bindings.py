import runpy
import sys
from types import SimpleNamespace

import pytest

from src.infra.onec.storage_bindings import load_storage_bindings


def test_storage_bindings_retain_tags_and_normalize_uuid(monkeypatch):
    monkeypatch.setattr("src.infra.onec.com_1cd_bridge.parse_dbnames", lambda _: [
        SimpleNamespace(uuid="ABC", tag="Fld", suffix=8),
        SimpleNamespace(uuid="abc", tag="VT", suffix=17),
        SimpleNamespace(uuid="abc", tag="Fld", suffix=8),
    ])
    assert load_storage_bindings("not-opened") == {"abc": {"Fld": 8, "VT": 17}}


@pytest.mark.parametrize("records", [[], [
    SimpleNamespace(uuid="abc", tag="Fld", suffix=8),
    SimpleNamespace(uuid="ABC", tag="Fld", suffix=9),
]])
def test_storage_bindings_reject_missing_or_conflicting_mapping(monkeypatch, records):
    monkeypatch.setattr("src.infra.onec.com_1cd_bridge.parse_dbnames", lambda _: records)
    with pytest.raises(ValueError):
        load_storage_bindings("not-opened")


@pytest.mark.parametrize("args,expected", [([], None), (["--limit", "3"], None), (["--data-limit", "7"], 7)])
def test_data_import_cli_does_not_reuse_preview_limit(monkeypatch, args, expected):
    import src.infra.onec.data_migration as migration
    import src.mpdb.mpdb as storage

    calls = []
    closed = []
    monkeypatch.setattr(storage, "Mpdb", lambda _: SimpleNamespace(close=lambda: closed.append(True)))
    monkeypatch.setattr(migration, "migrate_onecd_data_to_mpdb", lambda *a, **kw: calls.append(kw) or {})
    monkeypatch.setattr(sys, "argv", ["onec_data_migrator", "--src", "not-opened.1CD",
                                   "--db", "not-opened.mpdb", "--import-data", *args])
    runpy.run_module("src.tools.onec_data_migrator", run_name="__main__")
    assert calls[0]["limit_per_table"] == expected
    assert closed == [True]


def test_data_limit_rejected_before_database_open(monkeypatch):
    monkeypatch.setattr("src.mpdb.mpdb.Mpdb", lambda _: pytest.fail("must validate before opening the DB"))
    monkeypatch.setattr(sys, "argv", ["onec_data_migrator", "--src", "not-opened.1CD",
                                   "--db", "not-opened.mpdb", "--import-data", "--data-limit", "-1"])
    with pytest.raises(SystemExit) as error:
        runpy.run_module("src.tools.onec_data_migrator", run_name="__main__")
    assert error.value.code == 2
