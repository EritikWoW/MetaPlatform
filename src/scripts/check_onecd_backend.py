"""Check the bundled 1CD reader against an explicit source, reporting no row values.

Run with ``python -m src.scripts.check_onecd_backend --source path/to/1Cv8.1CD``.
The source is hashed before and after; the migration target is a disposable mpdb.
This is a bounded migration smoke, not a full import or a GUI acceptance test.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool) -> None:
    if not condition:
        raise RuntimeError("1CD backend contract failed")


def _check_migration(source: Path, table_name: str, limit: int) -> dict[str, Any]:
    from src.infra.onec.data_migration import (
        ONECD_DATA_MIGRATION_ASSET_KEY,
        migrate_onecd_data_to_mpdb,
    )
    from src.mpdb.mpdb import Mpdb

    with tempfile.TemporaryDirectory(prefix="metaplatform-onecd-smoke-") as directory:
        target = Path(directory) / "sample.mpdb"
        db = Mpdb(str(target))
        try:
            result = migrate_onecd_data_to_mpdb(
                db,
                str(source),
                table_names=[table_name],
                limit_per_table=limit,
                build_refs=False,
                read_blobs=False,
                batch_size=limit,
                storage_mode="packed",
            )
            summary = result["summary"]
            error_count = len(result.get("errors") or []) + sum(
                len(table.get("errors") or []) for table in result.get("tables") or []
            )
            _require(error_count == 0)
            _require(int(summary["tables_seen"]) == 1)
            _require(int(summary["tables_imported"]) == 1)
            _require(0 < int(summary["rows_imported"]) <= limit)
            packed_table = str(result["packed_table"])
            db.checkpoint()
        finally:
            db.close()

        reopened = Mpdb(str(target))
        try:
            persisted_rows = reopened.table(packed_table).select()
            manifest_bytes, _mime = reopened.get_asset(ONECD_DATA_MIGRATION_ASSET_KEY)
            persisted_manifest = json.loads(manifest_bytes)
            imported_rows = int(summary["rows_imported"])
            _require(len(persisted_rows) == imported_rows)
            _require(int(persisted_manifest["summary"]["rows_imported"]) == imported_rows)
        finally:
            reopened.close()
        return {
            "tables_imported": 1,
            "rows_imported": imported_rows,
            "rows_after_reopen": len(persisted_rows),
            "row_limit": limit,
            "errors": error_count,
            "temporary_target": True,
        }


def _probe(source: Path, limit: int, table: str | None, report: dict[str, Any]) -> None:
    from src.infra.onec.data_migration import _load_parse1cd_backend as load_data_backend
    from src.infra.onec.onecd_source import (
        OneCDConfigSource,
        _decode_table_file_payload,
        _read_blob_from_raw,
    )
    from src.infra.onec.physical_mapping import inspect_1cd_table_catalog
    from src.infra.onec.physical_schema import _load_parse1cd_backend, inspect_1cd_database

    report["stage"] = "backend"
    parser_root, backend = _load_parse1cd_backend()
    data_backend = load_data_backend()
    bundled_root = Path(__file__).resolve().parents[1] / "infra" / "onec"
    _require(Path(parser_root).resolve().is_relative_to(bundled_root))
    _require(backend.OneCDatabase is data_backend.database_parser.OneCDatabase)
    report["backend"] = {"bundled": True, "shared_reader": True}

    report["stage"] = "physical_schema"
    summary = inspect_1cd_database(source, sample_limit=0)
    _require(bool(summary.get("opened")) and not summary.get("parse_error"))
    catalog = inspect_1cd_table_catalog(source)
    _require(len(catalog) == int(summary["tables_count"]) > 0)
    report["physical_schema"] = {
        "tables": len(catalog),
        "fields": int(summary["total_fields"]),
        "indexes": int(summary["total_indexes"]),
        "table_description_errors": int(summary.get("table_description_errors") or 0),
    }

    report["stage"] = "params_dbnames"
    with backend.OneCDatabase(str(source)) as reader:
        _require(reader._fh is not None and not reader._fh.writable())
        report["backend"]["source_handle_read_only"] = True
        params = reader.get_table_info("Params")
        _require(params is not None)
        rows = reader.get_table_data("Params", limit=100000)
        dbnames = next((row for row in rows if row.get("FILENAME") == "DBNames"), None)
        _require(dbnames is not None)
        decoded = _decode_table_file_payload(_read_blob_from_raw(reader._get_blob_raw(params), dbnames))
        _require(bool(decoded))
        report["params_dbnames"] = {"param_rows": len(rows), "decoded_characters": len(decoded)}

        report["stage"] = "sample_table"
        names = reader.get_table_names()
        if table:
            names = [name for name in names if name.casefold() == table.casefold()]
        selected = None
        for name in names:
            if data_backend.schema_reader.SchemaReader.is_service_table(name):
                continue
            if reader.get_total_rows(name) <= 0:
                continue
            if next(reader.iter_table_rows(name, limit=1, read_blobs=False), None) is not None:
                selected = name
                break
        _require(selected is not None)

    report["stage"] = "semantic_source"
    with OneCDConfigSource(source) as config:
        objects = config.metadata_objects()
        files = config.list_files()
        _require(bool(objects) and bool(files))
        report["semantic_source"] = {
            "metadata_objects": len(objects),
            "files": len(files),
            "bsl_files": sum(name.lower().endswith(".bsl") for name in files),
        }

    report["stage"] = "sample_migration"
    report["migration"] = _check_migration(source, selected, limit)


def run_check(source: Path, *, limit: int = 3, table: str | None = None) -> dict[str, Any]:
    source = Path(source).resolve()
    if source.suffix.lower() != ".1cd" or not source.is_file():
        raise ValueError("--source must be an existing .1CD file")
    if not 1 <= limit <= 100:
        raise ValueError("--limit must be between 1 and 100")

    started = time.perf_counter()
    report: dict[str, Any] = {"ok": False, "source_size_bytes": source.stat().st_size, "errors": []}
    report["sha256_before"] = _sha256(source)
    # Legacy diagnostic output and exception messages may contain source data.
    # Publish only the deliberately assembled aggregate report below.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            _probe(source, limit, table, report)
        except Exception as exc:
            report["errors"].append({"stage": report.get("stage", "backend"), "type": type(exc).__name__})
        finally:
            try:
                report["sha256_after"] = _sha256(source)
                report["source_unchanged"] = report["sha256_before"] == report["sha256_after"]
            except Exception as exc:
                report["source_unchanged"] = False
                report["errors"].append({"stage": "source_hash_after", "type": type(exc).__name__})
    if not report["source_unchanged"]:
        report["errors"].append({"stage": "source_integrity", "type": "SourceChanged"})
    report.pop("stage", None)
    report["ok"] = not report["errors"]
    report["duration_sec"] = round(time.perf_counter() - started, 3)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Explicit .1CD source; opened read-only")
    parser.add_argument("--table", help="Optional physical business table for the sample migration")
    parser.add_argument("--limit", type=int, default=3, help="Sample rows (1–100; default 3)")
    args = parser.parse_args(argv)
    try:
        report = run_check(args.source, limit=args.limit, table=args.table)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
