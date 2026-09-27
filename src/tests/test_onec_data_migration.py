from __future__ import annotations

import json
from types import SimpleNamespace

from src.infra.onec import data_migration
from src.mpdb.mpdb import Mpdb


class _FakeOneCDatabase:
    def __init__(self, path: str):
        self.path = path
        self._tables = {
            "CONFIG": SimpleNamespace(name="CONFIG", fields=[]),
            "_REFERENCE10": SimpleNamespace(
                name="_REFERENCE10",
                fields=[
                    SimpleNamespace(name="_IDRRef", type=SimpleNamespace(value="B"), length=16, precision=0),
                    SimpleNamespace(name="_Description", type=SimpleNamespace(value="NVC"), length=64, precision=0),
                    SimpleNamespace(name="_Fld100", type=SimpleNamespace(value="N"), length=10, precision=0),
                ],
            ),
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get_table_names(self):
        return list(self._tables)

    def get_table_info(self, name: str):
        return self._tables.get(name)

    def get_total_rows(self, name: str) -> int:
        return 1 if name == "_REFERENCE10" else 0

    def iter_table_rows(self, name: str, **_kwargs):
        if name == "_REFERENCE10":
            yield {
                "_IDRRef": {"uuid_1c": "00000000-0000-0000-0000-000000000001"},
                "_Description": "Goods",
                "_Fld100": 42,
                "__deleted__": False,
            }


class _FakeInfoRegisterOneCDatabase:
    def __init__(self, path: str):
        self.path = path
        self._tables = {
            "_INFORG4455": SimpleNamespace(
                name="_INFORG4455",
                fields=[
                    SimpleNamespace(name="_Period", type=SimpleNamespace(value="D"), length=8, precision=0),
                    SimpleNamespace(name="_Fld1", type=SimpleNamespace(value="N"), length=10, precision=0),
                ],
            ),
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get_table_names(self):
        return list(self._tables)

    def get_table_info(self, name: str):
        return self._tables.get(name)

    def get_total_rows(self, name: str) -> int:
        return 1 if name == "_INFORG4455" else 0

    def iter_table_rows(self, name: str, **_kwargs):
        if name == "_INFORG4455":
            yield {
                "_Period": "2026-01-01T00:00:00",
                "_Fld1": 10,
                "__deleted__": False,
            }


class _FakeSchemaReader:
    @staticmethod
    def is_service_table(name: str) -> bool:
        return str(name).upper() == "CONFIG"

    @staticmethod
    def guess_table_kind(name: str) -> str:
        return "catalog" if str(name).upper().startswith("_REFERENCE") else "service"


class _FakeReferenceResolver:
    def __init__(self, _database):
        pass

    def build_index(self, _table_names=None) -> int:
        return 1


class _FakeFailingOneCDatabase:
    def __init__(self, path: str):
        self.path = path
        self._tables = {
            "_BROKEN1": SimpleNamespace(
                name="_BROKEN1",
                fields=[
                    SimpleNamespace(name="_IDRRef", type=SimpleNamespace(value="B"), length=16, precision=0),
                ],
            ),
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get_table_names(self):
        return list(self._tables)

    def get_table_info(self, name: str):
        return self._tables.get(name)

    def get_total_rows(self, name: str) -> int:
        return 1

    def iter_table_rows(self, name: str, **_kwargs):
        raise ValueError("simulated table read failure")


class _FakeLargeRowOneCDatabase:
    def __init__(self, path: str):
        self.path = path
        self._tables = {
            "_ACCUMRGTN11755": SimpleNamespace(
                name="_ACCUMRGTN11755",
                fields=[
                    SimpleNamespace(name="_RecorderRRef", type=SimpleNamespace(value="B"), length=16, precision=0),
                    SimpleNamespace(name="_LineNo", type=SimpleNamespace(value="N"), length=10, precision=0),
                    SimpleNamespace(name="_FldLarge", type=SimpleNamespace(value="NVC"), length=30000, precision=0),
                ],
            ),
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get_table_names(self):
        return list(self._tables)

    def get_table_info(self, name: str):
        return self._tables.get(name)

    def get_total_rows(self, name: str) -> int:
        return 2

    def iter_table_rows(self, name: str, **_kwargs):
        for row_index, marker in enumerate(("X", "Y"), start=1):
            yield {
                "_RecorderRRef": {"uuid_1c": f"00000000-0000-0000-0000-00000000011{row_index}"},
                "_LineNo": row_index,
                "_FldLarge": marker * 30000,
                "__deleted__": False,
            }


class _FakeHeartbeatOneCDatabase:
    def __init__(self, path: str):
        self.path = path
        self._tables = {
            "_REFERENCE10": SimpleNamespace(
                name="_REFERENCE10",
                fields=[
                    SimpleNamespace(name="_IDRRef", type=SimpleNamespace(value="B"), length=16, precision=0),
                    SimpleNamespace(name="_Description", type=SimpleNamespace(value="NVC"), length=64, precision=0),
                    SimpleNamespace(name="_Fld100", type=SimpleNamespace(value="N"), length=10, precision=0),
                ],
            ),
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get_table_names(self):
        return list(self._tables)

    def get_table_info(self, name: str):
        return self._tables.get(name)

    def get_total_rows(self, name: str) -> int:
        return 300 if name == "_REFERENCE10" else 0

    def iter_table_rows(self, name: str, **_kwargs):
        if name != "_REFERENCE10":
            return
        for row_index in range(1, 301):
            yield {
                "_IDRRef": {"uuid_1c": f"00000000-0000-0000-0000-00000000{row_index:04d}"},
                "_Description": f"Row {row_index}",
                "_Fld100": row_index,
                "__deleted__": False,
            }


def test_migrate_onecd_data_to_mpdb_imports_physical_rows(monkeypatch, tmp_path):
    onecd_path = tmp_path / "1Cv8.1CD"
    onecd_path.write_bytes(b"fake")
    db = Mpdb(str(tmp_path / "target.mpdb"))

    backend = data_migration.Parse1CDBackend(
        parser_root=tmp_path,
        database_parser=SimpleNamespace(OneCDatabase=_FakeOneCDatabase),
        schema_reader=SimpleNamespace(SchemaReader=_FakeSchemaReader),
        reference_resolver=SimpleNamespace(ReferenceResolver=_FakeReferenceResolver),
        value_decoder=SimpleNamespace(to_json_safe=lambda value: value),
    )
    monkeypatch.setattr(data_migration, "_load_parse1cd_backend", lambda: backend)
    progress_events: list[dict[str, object]] = []

    try:
        result = data_migration.migrate_onecd_data_to_mpdb(
            db,
            str(onecd_path),
            progress=progress_events.append,
        )

        assert result["summary"]["tables_seen"] == 1
        assert result["summary"]["tables_imported"] == 1
        assert result["summary"]["rows_imported"] == 1
        assert result["storage_mode"] == "packed"
        assert result["packed_table"] == "onec__data_rows"
        assert result["tables"][0]["target_table"] == "onec__data_rows"
        assert result["tables"][0]["logical_table"] == "onec__reference10"
        assert [event["stage"] for event in progress_events][-1] == "done"
        assert any(event["stage"] == "table_start" for event in progress_events)
        assert any(event["stage"] == "rows" for event in progress_events)
        assert "onec__reference10" not in db._meta["tables"]
        assert "schema" not in db._meta["tables"]["onec__data_rows"]
        assert str(db._meta["tables"]["onec__data_rows"].get("schema_ref") or "").startswith("__ts/")

        rows = db.table("onec__data_rows").select()
        assert rows[0]["data"]["description"] == "Goods"
        assert rows[0]["data"]["fld100"] == 42
        assert rows[0]["__source_table"] == "_REFERENCE10"

        payload, mime = db.get_asset(data_migration.ONECD_DATA_MIGRATION_ASSET_KEY)
        assert mime == "application/json"
        assert b"onec__data_rows" in payload
    finally:
        db.close()


def test_migrate_onecd_data_enriches_physical_table_from_dbnames(monkeypatch, tmp_path):
    onecd_path = tmp_path / "1Cv8.1CD"
    onecd_path.write_bytes(b"fake")
    db = Mpdb(str(tmp_path / "target.mpdb"))

    backend = data_migration.Parse1CDBackend(
        parser_root=tmp_path,
        database_parser=SimpleNamespace(OneCDatabase=_FakeInfoRegisterOneCDatabase),
        schema_reader=SimpleNamespace(SchemaReader=_FakeSchemaReader),
        reference_resolver=SimpleNamespace(ReferenceResolver=_FakeReferenceResolver),
        value_decoder=SimpleNamespace(to_json_safe=lambda value: value),
    )
    monkeypatch.setattr(data_migration, "_load_parse1cd_backend", lambda: backend)
    monkeypatch.setattr(
        data_migration,
        "_load_metadata_by_kind_order",
        lambda _source: {
            ("information_register", 4455): [
                {
                    "family": "information_register",
                    "name": "ЦеныНоменклатуры",
                    "title": "Ціни номенклатури",
                    "uuid": "info-rg-1",
                    "dbname_kind": "InfoRg",
                    "order": 4455,
                    "origin": "1cd://Config/info-rg-1",
                }
            ]
        },
    )

    try:
        result = data_migration.migrate_onecd_data_to_mpdb(
            db,
            str(onecd_path),
            table_names=["_INFORG4455"],
            build_refs=False,
        )

        table = result["tables"][0]
        assert table["kind"] == "information_register"
        assert table["table_role"] == "register_data"
        assert table["logical_name"] == "ЦеныНоменклатуры"
        assert table["metadata_order"] == 4455
        assert table["dbname_kind"] == "InfoRg"
    finally:
        db.close()


def test_metadata_by_kind_order_uses_dbnames_physical_order(monkeypatch, tmp_path) -> None:
    onecd_path = tmp_path / "1Cv8.1CD"
    onecd_path.write_bytes(b"fake")

    class _FakeOneCDConfigSource:
        def __init__(self, _source):
            pass

        def metadata_objects(self):
            return [
                SimpleNamespace(
                    family="information_register",
                    name="ЦеныНоменклатуры",
                    title="Ціни номенклатури",
                    uuid="info-rg-1",
                    dbname_kind="InfoRg",
                    order=3_000_000,
                    dbname_order=4455,
                    origin="1cd://Config/info-rg-1",
                )
            ]

    monkeypatch.setattr("src.infra.onec.onecd_source.OneCDConfigSource", _FakeOneCDConfigSource)

    mapping = data_migration._load_metadata_by_kind_order(onecd_path)

    assert ("information_register", 4455) in mapping
    assert ("information_register", 3_000_000) not in mapping
    assert mapping[("information_register", 4455)][0]["semantic_order"] == 3_000_000


def test_document_journal_prefix_is_not_classified_as_document() -> None:
    assert data_migration._fallback_table_kind("_DOCUMENTJOURNAL12278") == "journal"
    assert data_migration._physical_table_order("_DOCUMENTJOURNAL12278") == 12278

    class _DocumentGuessSchema:
        @staticmethod
        def guess_table_kind(_name: str) -> str:
            return "document"

    description = data_migration._describe_physical_table("_DOCUMENTJOURNAL12278", _DocumentGuessSchema, {})
    assert description["kind"] == "journal"
    assert description["table_role"] == "journal"
    assert data_migration._physical_table_role("_ACCUMRGT17060", "accumulation_register") == "totals"
    assert data_migration._physical_table_role("_BPRPOINTS10", "business_process") == "route_points"
    assert data_migration._fallback_table_kind("_SCHEDULEDJOBS17526") == "scheduled_job"
    assert data_migration._fallback_table_kind("v8users") == "system"
    assert data_migration._fallback_table_kind("_REFSINF17590") == "system"


def test_migrate_onecd_data_offloads_large_packed_rows(monkeypatch, tmp_path):
    onecd_path = tmp_path / "1Cv8.1CD"
    onecd_path.write_bytes(b"fake")
    db = Mpdb(str(tmp_path / "target.mpdb"))

    backend = data_migration.Parse1CDBackend(
        parser_root=tmp_path,
        database_parser=SimpleNamespace(OneCDatabase=_FakeLargeRowOneCDatabase),
        schema_reader=SimpleNamespace(SchemaReader=_FakeSchemaReader),
        reference_resolver=SimpleNamespace(ReferenceResolver=_FakeReferenceResolver),
        value_decoder=SimpleNamespace(to_json_safe=lambda value: value),
    )
    monkeypatch.setattr(data_migration, "_load_parse1cd_backend", lambda: backend)

    original_put_assets_bulk = db.put_assets_bulk

    def _guard_put_assets_bulk(items, *args, **kwargs):
        if any(str(item[0]).startswith(data_migration.ONECD_PACKED_ROW_ASSET_PREFIX) for item in items):
            raise AssertionError("packed row assets must be written in the outer migration transaction")
        return original_put_assets_bulk(items, *args, **kwargs)

    monkeypatch.setattr(db, "put_assets_bulk", _guard_put_assets_bulk)

    try:
        result = data_migration.migrate_onecd_data_to_mpdb(db, str(onecd_path))

        assert result["storage_mode"] == "packed"
        assert result["packed_inline_limit"] == data_migration.ONECD_PACKED_INLINE_LIMIT
        assert result["summary"]["tables_imported"] == 1
        assert result["summary"]["rows_imported"] == 2
        assert result["summary"]["rows_offloaded"] == 2
        assert result["summary"]["bytes_offloaded"] > 60000
        assert result["tables"][0]["offloaded_rows"] == 2

        rows = db.table("onec__data_rows").select()
        assert len(rows) == 2
        assert rows[0]["data"] == {}
        assert rows[0]["data_inline"] is False
        assert rows[0]["data_size"] > 30000
        assert rows[0]["data_asset"].startswith(data_migration.ONECD_PACKED_ROW_ASSET_PREFIX)
        assert rows[0]["data_asset"] == rows[1]["data_asset"]

        payload, mime = db.get_asset(rows[0]["data_asset"])
        assert mime == "application/x-jsonlines"
        for row, marker in zip(rows, ("X", "Y")):
            start = row["data_offset"]
            end = start + row["data_size"]
            payload_obj = json.loads(payload[start:end].decode("utf-8"))
            assert payload_obj["fldlarge"] == marker * 30000
            assert payload_obj["lineno"] in {1, 2}
        db.checkpoint(durable=True, keep_wal_bytes=0)
    finally:
        db.close()


def test_migrate_onecd_data_emits_heartbeat_progress_for_large_tables(monkeypatch, tmp_path):
    onecd_path = tmp_path / "1Cv8.1CD"
    onecd_path.write_bytes(b"fake")
    db = Mpdb(str(tmp_path / "target.mpdb"))

    backend = data_migration.Parse1CDBackend(
        parser_root=tmp_path,
        database_parser=SimpleNamespace(OneCDatabase=_FakeHeartbeatOneCDatabase),
        schema_reader=SimpleNamespace(SchemaReader=_FakeSchemaReader),
        reference_resolver=SimpleNamespace(ReferenceResolver=_FakeReferenceResolver),
        value_decoder=SimpleNamespace(to_json_safe=lambda value: value),
    )
    monkeypatch.setattr(data_migration, "_load_parse1cd_backend", lambda: backend)

    tick = {"value": 0.0}

    def _fake_monotonic() -> float:
        tick["value"] += 1.0
        return tick["value"]

    monkeypatch.setattr(data_migration.time, "monotonic", _fake_monotonic)

    progress_events: list[dict[str, object]] = []
    try:
        result = data_migration.migrate_onecd_data_to_mpdb(
            db,
            str(onecd_path),
            batch_size=1000,
            progress=progress_events.append,
        )

        row_events = [event for event in progress_events if event.get("stage") == "rows"]
        assert len(row_events) >= 2
        assert any(int(event.get("table_rows") or 0) < 300 for event in row_events)
        assert result["summary"]["rows_imported"] == 300
    finally:
        db.close()


def test_migrate_onecd_data_per_table_mode_imports_physical_rows(monkeypatch, tmp_path):
    onecd_path = tmp_path / "1Cv8.1CD"
    onecd_path.write_bytes(b"fake")
    db = Mpdb(str(tmp_path / "target.mpdb"))

    backend = data_migration.Parse1CDBackend(
        parser_root=tmp_path,
        database_parser=SimpleNamespace(OneCDatabase=_FakeOneCDatabase),
        schema_reader=SimpleNamespace(SchemaReader=_FakeSchemaReader),
        reference_resolver=SimpleNamespace(ReferenceResolver=_FakeReferenceResolver),
        value_decoder=SimpleNamespace(to_json_safe=lambda value: value),
    )
    monkeypatch.setattr(data_migration, "_load_parse1cd_backend", lambda: backend)

    try:
        result = data_migration.migrate_onecd_data_to_mpdb(
            db,
            str(onecd_path),
            storage_mode="per_table",
        )

        assert result["storage_mode"] == "per_table"
        assert result["summary"]["tables_imported"] == 1
        assert result["tables"][0]["target_table"] == "onec__reference10"
        assert db._meta["indexes"].get("onec__reference10", {}) == {}
        assert "schema" not in db._meta["tables"]["onec__reference10"]
        assert str(db._meta["tables"]["onec__reference10"].get("schema_ref") or "").startswith("__ts/")

        rows = db.table("onec__reference10").select()
        assert rows[0]["description"] == "Goods"
        assert rows[0]["fld100"] == 42
    finally:
        db.close()


def test_migrate_onecd_data_drops_empty_target_after_table_error(monkeypatch, tmp_path):
    onecd_path = tmp_path / "1Cv8.1CD"
    onecd_path.write_bytes(b"fake")
    db = Mpdb(str(tmp_path / "target.mpdb"))

    backend = data_migration.Parse1CDBackend(
        parser_root=tmp_path,
        database_parser=SimpleNamespace(OneCDatabase=_FakeFailingOneCDatabase),
        schema_reader=SimpleNamespace(SchemaReader=_FakeSchemaReader),
        reference_resolver=SimpleNamespace(ReferenceResolver=_FakeReferenceResolver),
        value_decoder=SimpleNamespace(to_json_safe=lambda value: value),
    )
    monkeypatch.setattr(data_migration, "_load_parse1cd_backend", lambda: backend)

    try:
        result = data_migration.migrate_onecd_data_to_mpdb(
            db,
            str(onecd_path),
            build_refs=False,
            storage_mode="per_table",
        )

        assert result["summary"]["tables_seen"] == 1
        assert result["summary"]["tables_imported"] == 0
        assert result["summary"]["rows_imported"] == 0
        assert result["tables"][0]["dropped_empty_target"] is True
        assert "onec__broken1" not in db._meta["tables"]
        db.checkpoint(durable=True, keep_wal_bytes=0)
    finally:
        db.close()


def test_migrate_onecd_data_skips_empty_physical_tables(monkeypatch, tmp_path):
    onecd_path = tmp_path / "1Cv8.1CD"
    onecd_path.write_bytes(b"fake")
    db = Mpdb(str(tmp_path / "target.mpdb"))

    backend = data_migration.Parse1CDBackend(
        parser_root=tmp_path,
        database_parser=SimpleNamespace(OneCDatabase=_FakeOneCDatabase),
        schema_reader=SimpleNamespace(SchemaReader=_FakeSchemaReader),
        reference_resolver=SimpleNamespace(ReferenceResolver=_FakeReferenceResolver),
        value_decoder=SimpleNamespace(to_json_safe=lambda value: value),
    )
    monkeypatch.setattr(data_migration, "_load_parse1cd_backend", lambda: backend)
    progress_events: list[dict[str, object]] = []

    try:
        result = data_migration.migrate_onecd_data_to_mpdb(
            db,
            str(onecd_path),
            table_names=["CONFIG"],
            build_refs=False,
            progress=progress_events.append,
        )

        assert result["summary"]["tables_seen"] == 1
        assert result["summary"]["tables_imported"] == 0
        assert result["summary"]["tables_skipped_empty"] == 1
        assert "onec__config" not in db._meta["tables"]
        assert any(event["stage"] == "table_skipped_empty" for event in progress_events)
    finally:
        db.close()


def test_migrate_onecd_data_manifest_asset_write_is_non_fatal(monkeypatch, tmp_path):
    onecd_path = tmp_path / "1Cv8.1CD"
    onecd_path.write_bytes(b"fake")
    db = Mpdb(str(tmp_path / "target.mpdb"))

    backend = data_migration.Parse1CDBackend(
        parser_root=tmp_path,
        database_parser=SimpleNamespace(OneCDatabase=_FakeOneCDatabase),
        schema_reader=SimpleNamespace(SchemaReader=_FakeSchemaReader),
        reference_resolver=SimpleNamespace(ReferenceResolver=_FakeReferenceResolver),
        value_decoder=SimpleNamespace(to_json_safe=lambda value: value),
    )
    monkeypatch.setattr(data_migration, "_load_parse1cd_backend", lambda: backend)

    original_put_assets_bulk = db.put_assets_bulk

    def _fail_put_assets_bulk(items):
        if any(item[0] == data_migration.ONECD_DATA_MIGRATION_ASSET_KEY for item in items):
            raise ValueError("simulated meta page overflow")
        return original_put_assets_bulk(items)

    monkeypatch.setattr(db, "put_assets_bulk", _fail_put_assets_bulk)

    try:
        result = data_migration.migrate_onecd_data_to_mpdb(db, str(onecd_path))

        assert result["summary"]["tables_imported"] == 1
        assert result["summary"]["rows_imported"] == 1
        assert result["asset_key"] == ""
        assert "simulated meta page overflow" in result["asset_error"]
        assert any(
            error.get("stage") == "store_migration_manifest"
            for error in result["errors"]
        )

        rows = db.table("onec__data_rows").select()
        assert rows[0]["data"]["description"] == "Goods"
    finally:
        db.close()


def test_sanitize_table_name_is_stable_and_ascii():
    assert data_migration.sanitize_table_name("_ACCUMRG11588") == "onec__accumrg11588"
    assert data_migration.sanitize_column_name("_IDRRef", set()) == "idrref"


def test_repeat_packed_migration_replaces_rows_and_resets_locator(monkeypatch, tmp_path):
    onecd_path = tmp_path / "1Cv8.1CD"
    onecd_path.write_bytes(b"fake")
    db = Mpdb(str(tmp_path / "repeat.mpdb"))
    backend = data_migration.Parse1CDBackend(
        parser_root=tmp_path,
        database_parser=SimpleNamespace(OneCDatabase=_FakeOneCDatabase),
        schema_reader=SimpleNamespace(SchemaReader=_FakeSchemaReader),
        reference_resolver=SimpleNamespace(ReferenceResolver=_FakeReferenceResolver),
        value_decoder=SimpleNamespace(to_json_safe=lambda value: value),
    )
    monkeypatch.setattr(data_migration, "_load_parse1cd_backend", lambda: backend)
    try:
        first = data_migration.migrate_onecd_data_to_mpdb(db, str(onecd_path))
        second = data_migration.migrate_onecd_data_to_mpdb(db, str(onecd_path))

        table = db.table("onec__data_rows")
        rows = table.select()
        assert len(rows) == 1
        point = table.select_rowid_range(1, 1, limit=1)
        assert len(point) == 1
        assert point[0]["data"]["description"] == "Goods"
        assert first["summary"]["rows_imported"] == 1
        assert second["summary"]["rows_imported"] == 1
        assert second["summary"]["reset_tables"] == 1
        assert second["complete"] is True
        assert db._meta["tables"]["onec__data_rows"]["next_rowid"] == 2
    finally:
        db.close()


def test_migration_reports_explicit_sampling_and_completeness(monkeypatch, tmp_path):
    onecd_path = tmp_path / "1Cv8.1CD"
    onecd_path.write_bytes(b"fake")
    db = Mpdb(str(tmp_path / "sample.mpdb"))
    backend = data_migration.Parse1CDBackend(
        parser_root=tmp_path,
        database_parser=SimpleNamespace(OneCDatabase=_FakeHeartbeatOneCDatabase),
        schema_reader=SimpleNamespace(SchemaReader=_FakeSchemaReader),
        reference_resolver=SimpleNamespace(ReferenceResolver=_FakeReferenceResolver),
        value_decoder=SimpleNamespace(to_json_safe=lambda value: value),
    )
    monkeypatch.setattr(data_migration, "_load_parse1cd_backend", lambda: backend)
    try:
        sampled = data_migration.migrate_onecd_data_to_mpdb(
            db, str(onecd_path), limit_per_table=20
        )
        assert sampled["sampled"] is True
        assert sampled["complete"] is False
        assert sampled["summary"]["tables_limited"] == 1
        assert sampled["summary"]["source_rows"] == 300
        assert sampled["summary"]["active_rows_scanned"] == 20

        full = data_migration.migrate_onecd_data_to_mpdb(db, str(onecd_path))
        assert full["sampled"] is False
        assert full["complete"] is True
        assert full["summary"]["tables_limited"] == 0
        assert full["summary"]["source_rows"] == 300
        assert full["summary"]["active_rows_scanned"] == 300
        assert len(db.table("onec__data_rows").select()) == 300
    finally:
        db.close()
