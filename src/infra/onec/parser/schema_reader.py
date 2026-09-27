#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Schema helpers for 1C (*.1CD) parser.

This module does not try to fully decode 1C metadata. It provides practical
migration helpers: table summaries, service-table detection, relation guesses
and JSON schema export.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, List

from .value_decoder import to_json_safe


class SchemaReader:
    """High-level schema view over OneCDatabase."""

    def __init__(self, database: Any):
        self.database = database

    def list_tables(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for name in self.database.get_table_names():
            table = self.database.get_table_info(name)
            if not table:
                continue
            result.append(
                {
                    "name": name,
                    "fields": len(table.fields),
                    "rows": self.database.get_total_rows(name),
                    "row_size": table.row_size,
                    "files": table.files,
                    "service": self.is_service_table(name),
                    "kind": self.guess_table_kind(name),
                }
            )
        return result

    @staticmethod
    def is_service_table(table_name: str) -> bool:
        name = table_name.upper()
        return name in {"CONFIG", "CONFIGSAVE", "DBSCHEMA", "FILES", "DEPOTFILES", "PARAMS"} or name.startswith("_") is False

    @staticmethod
    def guess_table_kind(table_name: str) -> str:
        name = table_name.upper()
        if name.startswith("_REFERENCE"):
            return "catalog"
        if name.startswith("_DOCUMENT"):
            return "document"
        if name.startswith("_ACCUMRG"):
            return "accumulation_register"
        if name.startswith("_INFOREG"):
            return "information_register"
        if name.startswith("_ENUM"):
            return "enum"
        if name.startswith("_CONST"):
            return "constant"
        if name in {"CONFIG", "CONFIGSAVE", "DBSCHEMA"}:
            return "metadata/service"
        return "unknown"

    def relation_guesses(self) -> List[Dict[str, str]]:
        guesses: List[Dict[str, str]] = []
        for name in self.database.get_table_names():
            table = self.database.get_table_info(name)
            if not table:
                continue
            fields = {f.name.upper(): f.name for f in table.fields}
            for upper, real in fields.items():
                if upper.endswith("RREF") and upper != "_IDRREF":
                    type_field = None
                    base = real[:-4]
                    for candidate in (base + "TREF", base + "TRREF", base + "TYPE"):
                        if candidate.upper() in fields:
                            type_field = fields[candidate.upper()]
                            break
                    guesses.append({"table": name, "field": real, "type_field": type_field or ""})
        return guesses

    def export(self, path: str) -> None:
        self.database._validate_export_path(path)
        payload = {
            "header": asdict(self.database.header) if self.database.header else None,
            "locale": getattr(self.database, "locale", ""),
            "tables": self.list_tables(),
            "relations": self.relation_guesses(),
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=to_json_safe)
