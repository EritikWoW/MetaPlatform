from __future__ import annotations

import json

import pytest

from src.scripts import check_onecd_backend as smoke


def test_smoke_checks_source_hash_even_when_backend_fails(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.1CD"
    source.write_bytes(b"original source")

    def fail_probe(path, _limit, _table, report):
        report["stage"] = "sample_migration"
        print("private business record")
        path.write_bytes(b"unexpected change")
        raise RuntimeError("private business record")

    monkeypatch.setattr(smoke, "_probe", fail_probe)
    report = smoke.run_check(source)

    assert report["ok"] is False
    assert report["source_unchanged"] is False
    assert report["sha256_before"] != report["sha256_after"]
    assert report["errors"] == [
        {"stage": "sample_migration", "type": "RuntimeError"},
        {"stage": "source_integrity", "type": "SourceChanged"},
    ]
    assert "private business record" not in json.dumps(report)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_smoke_rejects_unbounded_sample_before_reading_source(tmp_path, monkeypatch, limit):
    source = tmp_path / "source.1CD"
    source.write_bytes(b"source")
    monkeypatch.setattr(smoke, "_sha256", lambda _path: pytest.fail("invalid sample must not start reading"))

    with pytest.raises(ValueError, match="between 1 and 100"):
        smoke.run_check(source, limit=limit)


def test_smoke_migration_uses_disposable_target_and_reopens_persisted_data(tmp_path, monkeypatch):
    from src.infra.onec import data_migration

    source = tmp_path / "source.1CD"
    source.write_bytes(b"source")
    target_paths = []

    def migrate(db, source_path, **options):
        assert source_path == str(source)
        assert options["table_names"] == ["_REFERENCE10"]
        assert options["limit_per_table"] == 2
        assert options["build_refs"] is False
        assert options["read_blobs"] is False
        target_paths.append(db.path)
        db.create_table("sample_rows", {"columns": [{"name": "value", "type": "string"}]})
        db.table("sample_rows").insert({"value": "private business record"})
        result = {
            "packed_table": "sample_rows",
            "summary": {"tables_seen": 1, "tables_imported": 1, "rows_imported": 1},
            "tables": [{"errors": []}],
            "errors": [],
        }
        db.put_asset(data_migration.ONECD_DATA_MIGRATION_ASSET_KEY,
                     json.dumps(result).encode(), mime="application/json")
        return result

    monkeypatch.setattr(data_migration, "migrate_onecd_data_to_mpdb", migrate)
    result = smoke._check_migration(source, "_REFERENCE10", 2)

    assert result["rows_imported"] == result["rows_after_reopen"] == 1
    assert "private business record" not in json.dumps(result)
    assert target_paths and all(not path.exists() for path in target_paths)
    assert source.read_bytes() == b"source"
