"""Synthetic .1CD migration contract smoke for CI."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from src.infra.onec import data_migration
from src.infra.onec import storage_bindings
from src.mpdb.mpdb import Mpdb


class _Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._table = SimpleNamespace(
            name="_REFERENCE10",
            fields=[
                SimpleNamespace(name="_IDRRef", type=SimpleNamespace(value="B"), length=16, precision=0),
                SimpleNamespace(name="_Description", type=SimpleNamespace(value="NVC"), length=64, precision=0),
            ],
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def get_table_names(self):
        return ["_REFERENCE10"]

    def get_table_info(self, name: str):
        return self._table if name == "_REFERENCE10" else None

    def get_total_rows(self, name: str) -> int:
        return 2 if name == "_REFERENCE10" else 0

    def iter_table_rows(self, name: str, **_kwargs):
        if name != "_REFERENCE10":
            return
        for index, title in enumerate(("First", "Second"), start=1):
            yield {
                "_IDRRef": {"uuid": f"00000000-0000-0000-0000-00000000000{index}"},
                "_Description": title,
                "__deleted__": False,
            }


class _SchemaReader:
    @staticmethod
    def is_service_table(_name: str) -> bool:
        return False

    @staticmethod
    def guess_table_kind(_name: str) -> str:
        return "catalog"


class _ReferenceResolver:
    def __init__(self, _db) -> None:
        pass

    def build_index(self, _tables=None) -> int:
        return 2


def _backend() -> data_migration.Parse1CDBackend:
    return data_migration.Parse1CDBackend(
        parser_root=Path("synthetic-parse1cd"),
        database_parser=SimpleNamespace(OneCDatabase=_Database),
        schema_reader=SimpleNamespace(SchemaReader=_SchemaReader),
        reference_resolver=SimpleNamespace(ReferenceResolver=_ReferenceResolver),
        value_decoder=SimpleNamespace(to_json_safe=lambda value: value),
    )


def _assert_manifest(manifest: dict) -> None:
    if manifest.get("sampled"):
        raise AssertionError(f"CI import unexpectedly sampled rows: {manifest!r}")
    if not manifest.get("complete"):
        raise AssertionError(f"CI import is not complete: {manifest!r}")
    summary = dict(manifest.get("summary") or {})
    expected = {
        "source_rows": 2,
        "active_rows_scanned": 2,
        "rows_imported": 2,
        "tables_limited": 0,
        "tables_failed": 0,
    }
    for key, value in expected.items():
        if int(summary.get(key) or 0) != value:
            raise AssertionError(f"{key}: expected {value}, got {summary.get(key)!r}")


def main() -> int:
    original_backend = data_migration._load_parse1cd_backend
    original_metadata = data_migration._load_metadata_by_kind_order
    original_bindings = storage_bindings.load_storage_bindings
    data_migration._load_parse1cd_backend = _backend
    data_migration._load_metadata_by_kind_order = lambda _source: {
        ("catalog", 10): [
            {
                "family": "catalog",
                "name": "SmokeCatalog",
                "title": "Smoke catalog",
                "uuid": "catalog-guid",
                "dbname_kind": "Reference",
                "order": 10,
                "origin": "synthetic",
            }
        ]
    }
    storage_bindings.load_storage_bindings = lambda _source: {"catalog-guid": {"Fld": 1}}

    report: dict[str, object] = {"status": "error"}
    try:
        with tempfile.TemporaryDirectory(prefix="metaplatform-import-smoke-") as tmp:
            root = Path(tmp)
            source = root / "smoke.1CD"
            source.write_bytes(b"synthetic")
            db_path = root / "smoke.mpdb"
            db = Mpdb(str(db_path))
            try:
                first = data_migration.migrate_onecd_data_to_mpdb(
                    db, str(source), storage_mode="packed",
                    replace_existing=True, fail_on_table_errors=True,
                )
                _assert_manifest(first)
                second = data_migration.migrate_onecd_data_to_mpdb(
                    db, str(source), storage_mode="packed",
                    replace_existing=True, fail_on_table_errors=True,
                )
                _assert_manifest(second)
                if int(second["summary"].get("reset_tables") or 0) != 1:
                    raise AssertionError(f"repeat import did not reset packed storage: {second!r}")

                packed_table = str(second.get("packed_table") or "")
                table = db.table(packed_table)
                rows = table.select() or []
                if len(rows) != 2:
                    raise AssertionError(f"unexpected row count after rebuild: {rows!r}")
                for rowid in (1, 2):
                    point = table.select(where={"rowid": rowid}, limit=1)
                    if len(point or []) != 1:
                        raise AssertionError(f"row locator failed for rowid={rowid}")
                db.verify_integrity()
            finally:
                db.close()

            reopened = Mpdb(str(db_path))
            try:
                rows = reopened.table(packed_table).select(order_by="rowid") or []
                if len(rows) != 2:
                    raise AssertionError(f"repeat import duplicated rows after reopen: {rows!r}")
                reopened.verify_integrity()
            finally:
                reopened.close()

            report = {
                "status": "ok",
                "rows": 2,
                "repeat_reset": True,
                "locator_verified": True,
            }
    finally:
        data_migration._load_parse1cd_backend = original_backend
        data_migration._load_metadata_by_kind_order = original_metadata
        storage_bindings.load_storage_bindings = original_bindings

    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
