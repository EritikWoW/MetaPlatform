#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
High-level decoders for 1C (*.1CD) values.

The low-level reader returns Python values as they are stored in physical table
records. This module converts common 1C binary values into migration-friendly
representations: UUIDs, type references, BLOB previews and JSON-safe values.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID


@dataclass(frozen=True)
class DecodedReference:
    """Decoded 1C reference value.

    raw_hex: original 16 bytes as hex.
    uuid: direct RFC UUID interpretation.
    uuid_1c: UUID with the first 4+2+2 bytes reversed; this is often the value
             that matches 1C GUIDs shown in metadata/tools.
    resolved_table/resolved_name: optional values filled by ReferenceResolver.
    """

    raw_hex: str
    uuid: str
    uuid_1c: str
    resolved_table: Optional[str] = None
    resolved_name: Optional[str] = None

    def compact(self) -> str:
        if self.resolved_table:
            return f"{self.uuid_1c} -> {self.resolved_table}"
        return self.uuid_1c

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def bytes_to_uuid(raw: bytes) -> Optional[str]:
    """Return direct UUID interpretation for exactly 16 bytes."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != 16:
        return None
    return str(UUID(bytes=bytes(raw)))


def bytes_to_uuid_1c(raw: bytes) -> Optional[str]:
    """Return 1C-style UUID candidate for exactly 16 bytes.

    In many 1C stores the first 4, 2 and 2 bytes are little-endian while the
    remaining 8 bytes are already in network order. Keeping both forms during
    diagnostics is useful, but uuid_1c is usually the migration-friendly form.
    """
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != 16:
        return None
    b = bytes(raw)
    mixed = b[3::-1] + b[5:3:-1] + b[7:5:-1] + b[8:]
    return str(UUID(bytes=mixed))


def decode_reference(raw: bytes, resolver: Any = None) -> Optional[DecodedReference]:
    """Decode a binary _...RRef value and optionally resolve it through an index."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != 16:
        return None
    raw_bytes = bytes(raw)
    direct = bytes_to_uuid(raw_bytes) or raw_bytes.hex()
    onec = bytes_to_uuid_1c(raw_bytes) or direct
    resolved_table = None
    resolved_name = None
    if resolver is not None:
        try:
            resolved = resolver.resolve(raw_bytes)
        except Exception:
            resolved = None
        if resolved:
            resolved_table = resolved.get("table")
            resolved_name = resolved.get("name")
    return DecodedReference(
        raw_hex=raw_bytes.hex(),
        uuid=direct,
        uuid_1c=onec,
        resolved_table=resolved_table,
        resolved_name=resolved_name,
    )


def decode_type_ref(raw: bytes) -> str:
    """Decode _...TRef/_...TRRef bytes as a stable hex type token."""
    if not isinstance(raw, (bytes, bytearray)):
        return str(raw)
    return raw.hex()


def to_json_safe(value: Any) -> Any:
    """Convert values returned by the parser to JSON/CSV-safe objects."""
    if isinstance(value, DecodedReference):
        return value.to_dict()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    return value


def decode_value_by_column_name(
    column_name: str,
    value: Any,
    *,
    resolver: Any = None,
    rich_refs: bool = False,
    prefer_1c_uuid: bool = True,
) -> Any:
    """Decode a value using 1C naming conventions.

    - *_RRef: 16-byte object reference;
    - *_TRef, *_TRRef, *_Type: type discriminator/reference;
    - other bytes: hex string.

    rich_refs=False returns compact UI/export values. rich_refs=True returns a
    structured dict with raw hex, both UUID candidates and resolution metadata.
    """
    if value is None:
        return None

    name = (column_name or "").upper()

    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if name.endswith("RREF") and len(raw) == 16:
            ref = decode_reference(raw, resolver=resolver)
            if ref is None:
                return raw.hex()
            return ref.to_dict() if rich_refs else (ref.uuid_1c if prefer_1c_uuid else ref.uuid)

        if name.endswith("TRREF") or name.endswith("TREF") or name.endswith("TYPE"):
            return decode_type_ref(raw)

        return raw.hex()

    if isinstance(value, DecodedReference):
        return value.to_dict() if rich_refs else value.compact()

    return to_json_safe(value)
