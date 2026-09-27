"""Representative real-.1CD acceptance gate."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--repeat", action="store_true")
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
                db, str(source), limit_per_table=None, storage_mode="packed",
                replace_existing=True, fail_on_table_errors=True,
            )
            _validate(first)
            packed_table = str(first.get("packed_table") or "")
            first_rows = int(
                (db._meta.get("tables", {}).get(packed_table, {}) or {}).get("next_rowid") or 1
            ) - 1
            db.verify_integrity()

            second_rows = first_rows
            if args.repeat:
                second = migrate_onecd_data_to_mpdb(
                    db, str(source), limit_per_table=None, storage_mode="packed",
                    replace_existing=True, fail_on_table_errors=True,
                )
                _validate(second)
                second_rows = int(
                    (db._meta.get("tables", {}).get(packed_table, {}) or {}).get("next_rowid") or 1
                ) - 1
                if second_rows != first_rows:
                    raise AssertionError(
                        f"repeat import changed packed row count: {first_rows} -> {second_rows}"
                    )
                db.verify_integrity()

            report = {
                "status": "ok",
                "source": str(source),
                "rows_imported": int(first["summary"].get("rows_imported") or 0),
                "source_rows": int(first["summary"].get("source_rows") or 0),
                "tables_imported": int(first["summary"].get("tables_imported") or 0),
                "storage_bindings": len(first.get("storage_bindings") or {}),
                "packed_rows": first_rows,
                "repeat_verified": bool(args.repeat),
                "repeat_packed_rows": second_rows,
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
