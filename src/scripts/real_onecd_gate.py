"""Representative real-.1CD acceptance gate."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from src.infra.onec.data_migration import migrate_onecd_data_to_mpdb
from src.mpdb.mpdb import Mpdb


def _validate(manifest: dict) -> None:
    if manifest.get("sampled") or manifest.get("limit_per_table") is not None:
        raise AssertionError("representative gate must run without a sample limit")
    if not manifest.get("complete"):
        raise AssertionError(f"migration is incomplete: {manifest.get('errors')!r}")
    if manifest.get("errors"):
        raise AssertionError(f"migration contains errors: {manifest['errors']!r}")
    if not isinstance(manifest.get("storage_bindings"), dict) or not manifest["storage_bindings"]:
        raise AssertionError("UUID/DBNames storage bindings were not recovered")
    summary = dict(manifest.get("summary") or {})
    if int(summary.get("tables_limited") or 0):
        raise AssertionError("migration contains limited tables")
    if int(summary.get("tables_failed") or 0):
        raise AssertionError("migration contains failed tables")
    if int(summary.get("rows_imported") or 0) <= 0:
        raise AssertionError("migration imported no business rows")


def _name_key(value: Any) -> str:
    return re.sub(r"[^0-9a-zа-яіїєґ]+", "", str(value or "").casefold())


def _entry_active_rows(entry: dict[str, Any]) -> int:
    return int(entry.get("_source_row_index") or entry.get("imported_rows") or 0)


def _assert_table_complete(entry: dict[str, Any]) -> None:
    source_table = str(entry.get("source_table") or "")
    if entry.get("errors"):
        raise AssertionError(f"{source_table} contains table errors: {entry['errors']!r}")
    if entry.get("limited"):
        raise AssertionError(f"{source_table} is sample-limited")
    imported = int(entry.get("imported_rows") or 0)
    active = _entry_active_rows(entry)
    if imported != active:
        raise AssertionError(
            f"{source_table} active/imported row mismatch: {active} != {imported}"
        )


def _representative_document_report(
    db: Mpdb,
    manifest: dict[str, Any],
    requested_name: str,
) -> dict[str, Any]:
    requested_key = _name_key(requested_name)
    if not requested_key:
        raise AssertionError("representative document name is empty")

    tables = [
        dict(entry)
        for entry in list(manifest.get("tables") or [])
        if isinstance(entry, dict)
    ]
    candidates: list[dict[str, Any]] = []
    for entry in tables:
        if str(entry.get("kind") or "").casefold() != "document":
            continue
        names = (
            entry.get("logical_name"),
            entry.get("logical_title"),
            entry.get("metadata_uuid"),
            entry.get("source_table"),
        )
        keys = {_name_key(value) for value in names if str(value or "").strip()}
        if requested_key in keys:
            candidates.append(entry)

    if not candidates:
        known = sorted(
            {
                str(entry.get("logical_name") or entry.get("logical_title") or "").strip()
                for entry in tables
                if str(entry.get("kind") or "").casefold() == "document"
                and str(entry.get("logical_name") or entry.get("logical_title") or "").strip()
            }
        )
        raise AssertionError(
            f"representative document {requested_name!r} not found; "
            f"known documents include {known[:30]!r}"
        )

    object_candidates = [
        entry
        for entry in candidates
        if str(entry.get("table_role") or "").casefold() in {"object", "main", ""}
    ]
    document = object_candidates[0] if object_candidates else candidates[0]
    _assert_table_complete(document)
    if int(document.get("imported_rows") or 0) <= 0:
        raise AssertionError(
            f"representative document {requested_name!r} imported no active rows"
        )

    metadata_uuid = str(document.get("metadata_uuid") or "").strip().casefold()
    related = [
        entry
        for entry in tables
        if metadata_uuid
        and str(entry.get("metadata_uuid") or "").strip().casefold() == metadata_uuid
        and str(entry.get("source_table") or "") != str(document.get("source_table") or "")
    ]
    for entry in related:
        _assert_table_complete(entry)

    packed_table = str(manifest.get("packed_table") or "")
    first_rowid = 1
    sample_fields: list[str] = []
    for entry in tables:
        count = int(entry.get("imported_rows") or 0)
        if str(entry.get("source_table") or "") == str(document.get("source_table") or ""):
            if count > 0 and packed_table:
                rows = db.table(packed_table).select_rowid_range(
                    first_rowid,
                    first_rowid,
                    limit=1,
                ) or []
                if rows and isinstance(rows[0].get("data"), dict):
                    sample_fields = sorted(str(key) for key in rows[0]["data"])
            break
        first_rowid += max(0, count)

    return {
        "requested": requested_name,
        "logical_name": str(document.get("logical_name") or ""),
        "logical_title": str(document.get("logical_title") or ""),
        "metadata_uuid": str(document.get("metadata_uuid") or ""),
        "source_table": str(document.get("source_table") or ""),
        "source_rows": int(document.get("source_rows") or 0),
        "active_rows": _entry_active_rows(document),
        "imported_rows": int(document.get("imported_rows") or 0),
        "sample_fields": sample_fields,
        "related_tables": [
            {
                "source_table": str(entry.get("source_table") or ""),
                "table_role": str(entry.get("table_role") or ""),
                "source_rows": int(entry.get("source_rows") or 0),
                "active_rows": _entry_active_rows(entry),
                "imported_rows": int(entry.get("imported_rows") or 0),
            }
            for entry in related
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--repeat", action="store_true")
    parser.add_argument(
        "--representative-document",
        help="Technical name, title, metadata UUID or physical table of a document that must be fully imported.",
    )
    args = parser.parse_args()

    source = args.source.resolve()
    if source.suffix.lower() != ".1cd" or not source.is_file():
        parser.error("--source must point to an existing .1CD file")

    report: dict[str, object]
    with tempfile.TemporaryDirectory(prefix="metaplatform-real-onecd-gate-") as tmp:
        db_path = Path(tmp) / "acceptance.mpdb"
        db = Mpdb(str(db_path))
        try:
            first = migrate_onecd_data_to_mpdb(
                db,
                str(source),
                limit_per_table=None,
                storage_mode="packed",
                replace_existing=True,
                fail_on_table_errors=True,
            )
            _validate(first)
            packed_table = str(first.get("packed_table") or "")
            first_rows = int(
                (db._meta.get("tables", {}).get(packed_table, {}) or {}).get("next_rowid") or 1
            ) - 1
            db.verify_integrity()

            representative = None
            if args.representative_document:
                representative = _representative_document_report(
                    db,
                    first,
                    args.representative_document,
                )

            second_rows = first_rows
            if args.repeat:
                second = migrate_onecd_data_to_mpdb(
                    db,
                    str(source),
                    limit_per_table=None,
                    storage_mode="packed",
                    replace_existing=True,
                    fail_on_table_errors=True,
                )
                _validate(second)
                second_rows = int(
                    (db._meta.get("tables", {}).get(packed_table, {}) or {}).get("next_rowid") or 1
                ) - 1
                if second_rows != first_rows:
                    raise AssertionError(
                        f"repeat import changed packed row count: {first_rows} -> {second_rows}"
                    )
                if args.representative_document:
                    repeated = _representative_document_report(
                        db,
                        second,
                        args.representative_document,
                    )
                    if repeated["imported_rows"] != representative["imported_rows"]:
                        raise AssertionError(
                            "repeat import changed representative document row count: "
                            f"{representative['imported_rows']} -> {repeated['imported_rows']}"
                        )
                db.verify_integrity()

            report = {
                "status": "ok",
                "source": str(source),
                "rows_imported": int(first["summary"].get("rows_imported") or 0),
                "source_rows": int(first["summary"].get("source_rows") or 0),
                "active_rows_scanned": int(first["summary"].get("active_rows_scanned") or 0),
                "tables_imported": int(first["summary"].get("tables_imported") or 0),
                "storage_bindings": len(first.get("storage_bindings") or {}),
                "packed_rows": first_rows,
                "repeat_verified": bool(args.repeat),
                "repeat_packed_rows": second_rows,
                "representative_document_verified": representative is not None,
                "representative_document": representative,
            }
        finally:
            db.close()

    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    print(encoded)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
