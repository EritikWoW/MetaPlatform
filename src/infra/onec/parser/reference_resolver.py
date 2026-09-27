#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reference resolver for 1C (*.1CD) migration.

Builds a lightweight index from tables containing _IDRRef and uses it to map
binary *_RRef values to their physical table and, when possible, a display name.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from .value_decoder import bytes_to_uuid, bytes_to_uuid_1c


NAME_CANDIDATES = (
    "_DESCRIPTION",
    "DESCRIPTION",
    "_CODE",
    "CODE",
    "_NUMBER",
    "NUMBER",
    "_PRESENTATION",
    "PRESENTATION",
)


class ReferenceResolver:
    """Build and query an index of 1C binary references."""

    def __init__(self, database: Any, scan_limit_per_table: Optional[int] = None):
        self.database = database
        self.scan_limit_per_table = scan_limit_per_table
        self.id_index: Dict[str, Dict[str, Any]] = {}
        self.table_stats: Dict[str, int] = {}

    def build_index(self, table_names: Optional[Iterable[str]] = None) -> int:
        """Scan tables with _IDRRef and return the number of indexed refs."""
        names = list(table_names) if table_names is not None else self.database.get_table_names()
        before = len(self.id_index)
        for table_name in names:
            table = self.database.get_table_info(table_name)
            if not table:
                continue
            field_names = {f.name.upper(): f.name for f in table.fields}
            id_field = field_names.get("_IDRREF")
            if not id_field:
                continue

            indexed_for_table = 0
            try:
                iterator = self.database.iter_table_rows(
                    table_name,
                    limit=self.scan_limit_per_table,
                    read_blobs=False,
                    include_deleted=False,
                    decode=False,
                )
                for row in iterator:
                    raw = row.get(id_field)
                    if not isinstance(raw, (bytes, bytearray)) or len(raw) != 16:
                        continue
                    display_name = self._extract_name(row)
                    self._add(bytes(raw), table_name, display_name)
                    indexed_for_table += 1
            except Exception:
                # Some service tables may be unreadable. Migration should continue.
                continue
            self.table_stats[table_name] = indexed_for_table
        return len(self.id_index) - before

    def _add(self, raw: bytes, table_name: str, display_name: Optional[str]) -> None:
        direct = bytes_to_uuid(raw)
        onec = bytes_to_uuid_1c(raw)
        info = {
            "table": table_name,
            "name": display_name,
            "raw_hex": raw.hex(),
            "uuid": direct,
            "uuid_1c": onec,
        }
        if direct:
            self.id_index[direct] = info
        if onec:
            self.id_index[onec] = info
        self.id_index[raw.hex()] = info

    def _extract_name(self, row: Dict[str, Any]) -> Optional[str]:
        upper_to_real = {k.upper(): k for k in row.keys()}
        for candidate in NAME_CANDIDATES:
            real = upper_to_real.get(candidate)
            if real is None:
                continue
            value = row.get(real)
            if value not in (None, "", b""):
                return str(value)
        return None

    def resolve(self, value: Any) -> Optional[Dict[str, Any]]:
        """Resolve bytes, raw hex or UUID string into index metadata."""
        if isinstance(value, (bytes, bytearray)):
            raw = bytes(value)
            for key in (bytes_to_uuid_1c(raw), bytes_to_uuid(raw), raw.hex()):
                if key and key in self.id_index:
                    return self.id_index[key]
            return None
        if isinstance(value, str):
            return self.id_index.get(value.lower()) or self.id_index.get(value)
        return None
