"""src.configurator.persistence.db_export — DB dump / restore.

Provides full database export to a ZIP archive containing JSON files,
and import (restore) from such an archive.

Archive structure:
    metaplatform_dump/
        meta.json          — export metadata (version, date, db_uid)
        manifest.json      — all manifest rows
        tables/
            sys_users.json
            sys_roles.json
            ...             (all non-empty tables)

Usage:
    # Export
    exporter = DbExporter(db)
    exporter.export_zip("/path/to/backup.zip")

    # Import
    importer = DbImporter(db)
    report = importer.import_zip("/path/to/backup.zip")
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Tables to always include (even if empty)
_SYSTEM_TABLES = [
    "manifest",
    "sys_users",
    "sys_roles",
    "sys_user_roles",
    "sys_audit_log",
    "sys_config",
    "sys_numerators",
    "config_releases",
    "config_head",
]

# Prefixes that indicate data tables (include all of them)
_DATA_PREFIXES = ("data_catalog_", "data_document_", "data_tp_", "data_reg_")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _discover_data_tables(db) -> List[str]:
    """Find all data_* tables by trying common discovery patterns."""
    found = []
    # Try internal table listing via mpdb meta
    try:
        meta = getattr(db, "_meta", {}) or {}
        table_registry = meta.get("tables") or {}
        for name in table_registry:
            if any(name.startswith(p) for p in _DATA_PREFIXES):
                found.append(name)
        return sorted(found)
    except Exception:
        pass
    return found


@dataclass
class ExportReport:
    tables_exported:  List[str] = field(default_factory=list)
    rows_exported:    int = 0
    errors:           List[str] = field(default_factory=list)
    ok:               bool = True

    def summary(self) -> str:
        return (
            f"{len(self.tables_exported)} table(s), "
            f"{self.rows_exported} row(s)"
            + (f", {len(self.errors)} error(s)" if self.errors else "")
        )


@dataclass
class ImportReport:
    tables_imported:  List[str] = field(default_factory=list)
    rows_imported:    int = 0
    rows_skipped:     int = 0
    errors:           List[str] = field(default_factory=list)
    ok:               bool = True

    def summary(self) -> str:
        return (
            f"{len(self.tables_imported)} table(s), "
            f"{self.rows_imported} row(s) imported"
            + (f", {self.rows_skipped} skipped" if self.rows_skipped else "")
            + (f", {len(self.errors)} error(s)" if self.errors else "")
        )


# ─────────────────────────────────── Exporter ─────────────────────────────

class DbExporter:
    """Export all tables from an mpdb database to a ZIP archive."""

    def __init__(self, db) -> None:
        self._db = db

    def export_zip(self, path: str) -> ExportReport:
        """Write the archive to ``path``. Returns an export report."""
        report = ExportReport()
        db = self._db
        db_uid = getattr(db, "db_uid", "unknown")

        tables = list(_SYSTEM_TABLES) + _discover_data_tables(db)
        # deduplicate preserving order
        seen: set[str] = set()
        unique_tables: list[str] = []
        for t in tables:
            if t not in seen:
                seen.add(t)
                unique_tables.append(t)

        meta_info = {
            "version":    "1.0",
            "db_uid":     db_uid,
            "created_at": _now_iso(),
            "tables":     unique_tables,
        }

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "metaplatform_dump/meta.json",
                json.dumps(meta_info, ensure_ascii=False, indent=2)
            )

            for tname in unique_tables:
                try:
                    rows = db.table(tname).select() or []
                except Exception:
                    rows = []

                # Always write system tables, skip empty data tables
                if not rows and not any(
                    tname == s for s in _SYSTEM_TABLES
                ):
                    continue

                data = json.dumps(rows, ensure_ascii=False,
                                  indent=2, default=str)
                zf.writestr(
                    f"metaplatform_dump/tables/{tname}.json", data
                )
                report.tables_exported.append(tname)
                report.rows_exported += len(rows)

        return report


# ─────────────────────────────────── Importer ─────────────────────────────

class DbImporter:
    """Restore tables from a ZIP archive into an mpdb database.

    Default mode: MERGE — insert rows that don't exist (by _guid / primary).
    Use replace=True to REPLACE all existing rows (full restore).
    """

    def __init__(self, db) -> None:
        self._db = db

    def import_zip(self, path: str, *,
                   replace: bool = False) -> ImportReport:
        """Read archive from ``path`` and restore into the DB."""
        report = ImportReport()

        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()

            # Read meta
            meta_name = "metaplatform_dump/meta.json"
            if meta_name not in names:
                report.ok = False
                report.errors.append(
                    "Invalid archive: missing metaplatform_dump/meta.json"
                )
                return report

            meta = json.loads(zf.read(meta_name).decode("utf-8"))
            table_files = [
                n for n in names
                if n.startswith("metaplatform_dump/tables/")
                and n.endswith(".json")
            ]

            for tfile in sorted(table_files):
                tname = tfile.split("/")[-1].removesuffix(".json")
                try:
                    rows: List[Dict[str, Any]] = json.loads(
                        zf.read(tfile).decode("utf-8")
                    )
                except Exception as e:
                    report.errors.append(f"{tname}: JSON parse error: {e}")
                    continue

                try:
                    self._restore_table(tname, rows, replace=replace, report=report)
                    report.tables_imported.append(tname)
                except Exception as e:
                    report.errors.append(f"{tname}: {e}")
                    report.ok = False

        return report

    def _restore_table(self, tname: str, rows: List[dict],
                       replace: bool, report: ImportReport) -> None:
        db = self._db

        # Ensure table exists (use first row as schema hint)
        try:
            db.table(tname)
        except Exception:
            if not rows:
                return  # can't create without schema
            schema = {
                k: {"type": "str"} for k in rows[0].keys()
            }
            db.create_table(tname, schema=schema)

        tbl = db.table(tname)

        if replace:
            # Delete all existing rows
            try:
                existing = tbl.select() or []
                for row in existing:
                    if "_guid" in row:
                        tbl.delete(where={"_guid": row["_guid"]})
                    elif "rowid" in row:
                        tbl.delete(where={"rowid": row["rowid"]})
            except Exception:
                pass

        for row in rows:
            row = dict(row)
            try:
                guid = str(row.get("_guid") or "")
                if guid and not replace:
                    existing = tbl.select(where={"_guid": guid}) or []
                    if existing:
                        report.rows_skipped += 1
                        continue
                tbl.insert(row)
                report.rows_imported += 1
            except Exception as e:
                report.errors.append(
                    f"{tname}/{row.get('_guid','?')}: {e}"
                )
