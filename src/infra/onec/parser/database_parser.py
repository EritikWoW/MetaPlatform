#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Robust read-only parser for 1C file databases (*.1CD).

Purpose:
- inspect 1CD structure;
- read physical tables;
- prepare data export/migration to another DBMS.

This module is intentionally read-only. Writing back to 1CD is unsafe without a
full implementation of indexes, allocation maps, transactions and checksums.
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
import json
import math
import os
import re
import struct
from dataclasses import asdict, is_dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterable, Iterator, List, Optional

from .models import DatabaseHeader, Field, FieldType, Index, IndexField, Table
from .value_decoder import decode_value_by_column_name, to_json_safe

FILE_SIGNATURE = b"1CDBMSV8"
OBJECT_SIGNATURE_82 = b"1CDBOBV8"
OBJECT_SIGNATURE_83_DATA = b"\x1c\xfd"
OBJECT_SIGNATURE_83_FREE = b"\x1c\xff"
ROOT_OBJECT_OFFSET = 2
BLOB_CHUNK_SIZE = 256

SUPPORTED_VERSIONS = {"8.2.14.0", "8.3.8.0"}

_TABLE_RE = re.compile(
    r'\{"([^"\r\n]+)",\s*\d+,\s*\n'
    r'\{"Fields",\s*\n(?P<fields>[\s\S]*?)\n\},\s*\n'
    r'\{"Indexes"(?P<indexes>[\s\S]*?)\},\s*\n'
    r'\{"Recordlock","(?P<recordlock>\d+)"\},\s*\n'
    r'\{"Files",(?P<files>[\d,]+)\}\s*\n\}',
    re.MULTILINE,
)

_FIELD_RE = re.compile(r'\{"(\w+)","(\w+)",(\d+),(\d+),(\d+),"(\w+)"\}')
_INDEX_RE = re.compile(r'\{"([^"\r\n]+)",(\d+),([\s\S]*?)\n\}', re.MULTILINE)
_INDEX_FIELD_RE = re.compile(r'\{"(\w+)",(\d+)\}')


def _u16(data: bytes) -> str:
    return data.decode("utf-16", errors="replace").rstrip("\x00")


def _u8(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").rstrip("\x00")


def _clean_name(value: str) -> str:
    return "".join(ch for ch in value if ch == " " or ord(ch) >= 32).strip()


def calc_raw_field_len(field_type: str, length: int) -> int:
    if field_type == "B":
        return length
    if field_type == "L":
        return 1
    if field_type == "N":
        return length // 2 + 1
    if field_type == "NC":
        return length * 2
    if field_type == "NVC":
        return length * 2 + 2
    if field_type == "RV":
        return 16
    if field_type in {"NT", "I"}:
        return 8
    if field_type == "DT":
        return 7
    raise ValueError(f"Unsupported 1CD field type: {field_type}")


def field_type_from_raw(value: str) -> FieldType:
    mapping = {
        "B": FieldType.BINARY,
        "L": FieldType.BOOLEAN,
        "N": FieldType.NUMBER,
        "NC": FieldType.FIXED_STRING,
        "NVC": FieldType.VAR_STRING,
        "RV": FieldType.VERSION,
        "NT": FieldType.UNLIMITED_STRING,
        "I": FieldType.UNLIMITED_BINARY,
        "DT": FieldType.DATETIME,
    }
    return mapping[value]


def raw_type_from_field(field: Field) -> str:
    return field.type.value if isinstance(field.type, FieldType) else str(field.type)


def decode_numeric(data: bytes, length: int, precision: int) -> Optional[Any]:
    if not data:
        return None
    # 1C numeric is stored as packed decimal-like hex digits.
    hex_value = "".join(f"{b:02X}" for b in data)
    sign = "-" if hex_value[0] == "0" else ""
    digits = hex_value[1 : length + 1]
    if not digits:
        return None
    if precision:
        if len(digits) <= precision:
            digits = "0" * (precision - len(digits) + 1) + digits
        value = f"{sign}{digits[:-precision] or '0'}.{digits[-precision:]}"
        try:
            return Decimal(value)
        except InvalidOperation:
            return value
    value = f"{sign}{digits}"
    try:
        return int(value)
    except ValueError:
        return value


def decode_nvc(data: bytes) -> str:
    if len(data) < 2:
        return ""
    length = struct.unpack_from("<H", data, 0)[0]
    raw = data[2 : 2 + length * 2]
    return raw.decode("utf-16", errors="replace")


def decode_datetime(data: bytes) -> Optional[dt.datetime]:
    if len(data) < 7 or data[:2] == b"\x00\x00":
        return None
    # 1CD DT is BCD-like: YYYY MM DD HH MM SS in hex digits, 7 bytes total.
    value = "".join(f"{b:02X}" for b in data[:7])
    try:
        return dt.datetime(
            int(value[0:4]),
            int(value[4:6]),
            int(value[6:8]),
            int(value[8:10]),
            int(value[10:12]),
            int(value[12:14]),
        )
    except ValueError:
        return None


def json_safe(value: Any) -> Any:
    if isinstance(value, BlobRef):
        return value.preview()
    if is_dataclass(value):
        return asdict(value)
    return to_json_safe(value)


class DBObject:
    """Logical 1CD object assembled from physical pages."""

    def __init__(self, db: "OneCDatabase", object_page: int):
        self.db = db
        self.object_page = object_page
        self.page_size = db.page_size
        self.version = db.header.version
        self.length = 0
        self.pages: List[int] = []
        self.fat_level = 0
        self._load_header()

    def _load_header(self) -> None:
        page = self.db._read_page(self.object_page)
        if len(page) < 16:
            raise ValueError(f"Object page {self.object_page} is too short")

        if self.version == "8.3.8.0":
            sig = page[:2]
            if sig == OBJECT_SIGNATURE_83_FREE:
                raise NotImplementedError("Free-page object is not readable as data object")
            if sig != OBJECT_SIGNATURE_83_DATA:
                raise ValueError(f"Unknown 8.3 object signature at page {self.object_page}: {sig.hex()}")

            self.fat_level = struct.unpack_from("<H", page, 2)[0]
            # Layout: 2s, H, 3I, Q, then page pointers.
            self.length = struct.unpack_from("<Q", page, 16)[0]
            pointers_count = (self.page_size - 24) // 4
            pointers = struct.unpack_from(f"<{pointers_count}I", page, 24)

            if self.fat_level == 0:
                count = math.ceil(self.length / self.page_size)
                self.pages = [p for p in pointers[:count] if p]
            elif self.fat_level == 1:
                for index_page in pointers:
                    if not index_page:
                        break
                    self.pages.extend(self._read_pointer_page(index_page))
            else:
                raise NotImplementedError(f"8.3 FAT level {self.fat_level} is not supported yet")
            return

        if page[:8] != OBJECT_SIGNATURE_82:
            raise ValueError(f"Unknown 8.2 object signature at page {self.object_page}: {page[:8]!r}")

        # Layout used by old 8.2 file DBs: 8s, 3i, I, 1018I.
        self.length = struct.unpack_from("<i", page, 8)[0]
        index_pages_count = (self.length - 1) // (1023 * self.page_size) + 1 if self.length else 0
        index_pages = struct.unpack_from("<1018I", page, 24)[:index_pages_count]
        for index_page in index_pages:
            if not index_page:
                continue
            index_data = self.db._read_page(index_page)
            count = struct.unpack_from("<i", index_data, 0)[0]
            self.pages.extend(struct.unpack_from(f"<{count}I", index_data, 4))

    def _read_pointer_page(self, page_number: int) -> List[int]:
        data = self.db._read_page(page_number)
        pointers = struct.unpack_from(f"<{self.page_size // 4}I", data, 0)
        result: List[int] = []
        for pointer in pointers:
            if not pointer:
                break
            result.append(pointer)
        return result

    def read(self, pos: int = 0, size: int = -1) -> bytes:
        if pos < 0:
            raise ValueError("Negative positions are not supported")
        if pos >= self.length:
            return b""
        if size < 0:
            size = self.length - pos
        else:
            size = min(size, self.length - pos)

        chunks: List[bytes] = []
        done = 0
        while done < size:
            absolute = pos + done
            page_index = absolute // self.page_size
            page_offset = absolute % self.page_size
            if page_index >= len(self.pages):
                break
            page = self.db._read_page(self.pages[page_index])
            take = min(size - done, self.page_size - page_offset)
            chunks.append(page[page_offset : page_offset + take])
            done += take
        return b"".join(chunks)


class BlobRef:
    """Reference to 1CD chained BLOB blocks inside a table blob object."""

    def __init__(self, obj: DBObject, size: int, chunk_offset: int, field_type: str):
        self.obj = obj
        self.size = size
        self.chunk_offset = chunk_offset
        self.field_type = field_type
        self._value: Optional[Any] = None

    def iter_chunks(self) -> Iterator[bytes]:
        if self.size == 0:
            return
        current = self.chunk_offset
        read_total = 0
        visited = set()
        while current and read_total < self.size:
            if current in visited:
                raise ValueError(f"BLOB chain loop detected at chunk {current}")
            visited.add(current)
            block = self.obj.read(current * BLOB_CHUNK_SIZE, BLOB_CHUNK_SIZE)
            if len(block) < 6:
                break
            next_chunk, chunk_size = struct.unpack_from("<Ih", block, 0)
            if chunk_size < 0 or chunk_size > 250:
                raise ValueError(f"Invalid BLOB chunk size {chunk_size} at chunk {current}")
            payload = block[6 : 6 + min(chunk_size, self.size - read_total)]
            read_total += len(payload)
            yield payload
            if not next_chunk:
                break
            current = next_chunk

    @property
    def value(self) -> Any:
        if self._value is not None:
            return self._value
        raw = b"".join(self.iter_chunks())
        if self.field_type == "NT":
            self._value = raw.decode("utf-16", errors="replace")
        else:
            self._value = raw
        return self._value

    def preview(self) -> str:
        # The semantic importer consumes this stable offset/length marker.
        return f"BLOB:{self.chunk_offset}:{self.size}"


class OneCDatabase:
    """Read-only 1CD database reader."""

    def __init__(self, filepath: str, cache_pages: int = 20000):
        self.filepath = filepath
        self.cache_pages = cache_pages
        self.page_size = 4096
        self.header: Optional[DatabaseHeader] = None
        self.locale = ""
        self.tables: "collections.OrderedDict[str, Table]" = collections.OrderedDict()
        self._fh: Optional[BinaryIO] = None
        self._page_cache: Dict[int, bytes] = {}
        self._root_offsets: List[int] = []
        self._description_errors: List[str] = []
        self._table_data_pages: Dict[str, List[int]] = {}
        self.last_error: Optional[str] = None

    def __enter__(self) -> "OneCDatabase":
        if not self.open():
            raise RuntimeError("Unable to open 1CD database")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def open(self) -> bool:
        self.close()
        self.header = None
        self.tables.clear()
        self._root_offsets.clear()
        self._description_errors.clear()
        self._table_data_pages.clear()
        self.last_error = None
        try:
            if not os.path.exists(self.filepath):
                raise FileNotFoundError(self.filepath)
            self._fh = open(self.filepath, "rb")
            self._read_header()
            self._read_root_object()
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self.close()
            return False

    def close(self) -> None:
        if self._fh:
            self._fh.close()
        self._fh = None
        self._page_cache.clear()

    def _read_header(self) -> None:
        assert self._fh is not None
        self._fh.seek(0)
        fmt = "<8s4bIi"
        raw = self._fh.read(struct.calcsize(fmt))
        if len(raw) != struct.calcsize(fmt):
            raise ValueError("File is too small to be a 1CD database")
        sig, v1, v2, v3, v4, total_pages, unknown = struct.unpack(fmt, raw)
        if sig != FILE_SIGNATURE:
            raise ValueError(f"Invalid 1CD signature: {sig!r}")
        version = f"{v1}.{v2}.{v3}.{v4}"
        if version not in SUPPORTED_VERSIONS:
            raise NotImplementedError(f"Unsupported 1CD format version: {version}")
        if version == "8.3.8.0":
            self.page_size = struct.unpack("<I", self._fh.read(4))[0]
        else:
            self.page_size = 4096
        if self.page_size not in {4096, 8192, 16384, 32768, 65536}:
            raise ValueError(f"Invalid 1CD page size: {self.page_size}")
        file_size = os.path.getsize(self.filepath)
        self.header = DatabaseHeader(
            signature=sig.decode("ascii"),
            version=version,
            total_pages=total_pages,
            unknown=unknown,
            page_size=self.page_size,
            file_size=file_size,
        )

    def _read_root_object(self) -> None:
        assert self.header is not None
        root = DBObject(self, ROOT_OBJECT_OFFSET)

        if self.header.version == "8.3.8.0":
            root_payload = BlobRef(root, root.length, 1, "I").value
            if not isinstance(root_payload, bytes):
                raise ValueError("Root object payload must be bytes")
        else:
            root_payload = root.read()

        if len(root_payload) < 36:
            raise ValueError("Root object payload is too short")

        locale_raw, table_count = struct.unpack_from("<32si", root_payload, 0)
        self.locale = _u8(locale_raw)

        # Validate the root header. If it looks wrong, fail loudly instead of
        # continuing with random offsets and producing fake table names.
        max_reasonable = max(0, (len(root_payload) - 36) // 4)
        if table_count < 0 or table_count > max_reasonable:
            raise ValueError(
                f"Invalid root table count {table_count}; payload={len(root_payload)} bytes. "
                "Root BLOB chain is probably being decoded from a wrong offset."
            )

        self._root_offsets = list(struct.unpack_from(f"<{table_count}i", root_payload, 36))
        for offset in self._root_offsets:
            if offset <= 0:
                continue
            try:
                description = self._read_table_description(root, offset)
                self._parse_table_description(description)
            except Exception as exc:
                self._description_errors.append(f"offset={offset}: {exc}")

    def _read_table_description(self, root: DBObject, offset: int) -> str:
        assert self.header is not None
        if self.header.version == "8.3.8.0":
            payload = BlobRef(root, root.length, offset, "I").value
            if not isinstance(payload, bytes):
                raise ValueError("Table description payload must be bytes")
            return _u8(payload)
        obj = DBObject(self, offset)
        return _u16(obj.read())

    def _parse_table_description(self, text: str) -> None:
        for match in _TABLE_RE.finditer(text):
            name = _clean_name(match.group(1))
            if not name:
                continue
            table = Table(name=name)
            table.recordlock = match.group("recordlock")
            table.files = match.group("files").split(",")
            table.description = text
            table.data_object_id = int(table.files[0]) if table.files and table.files[0].isdigit() else None
            table.blob_object_id = int(table.files[1]) or None if len(table.files) > 1 else None
            table.index_object_id = int(table.files[2]) or None if len(table.files) > 2 else None
            table.fields = self._parse_fields(match.group("fields"))
            table.indexes = self._parse_indexes('{"Indexes"' + match.group("indexes") + '}')
            self._apply_physical_layout(table)
            table.blob_fields = [f.name for f in table.fields if f.type in {FieldType.UNLIMITED_STRING, FieldType.UNLIMITED_BINARY}]
            self.tables[name] = table

    def _parse_fields(self, fields_text: str) -> List[Field]:
        fields: List[Field] = []
        offset = 17 if '"RV"' in fields_text else 1
        for match in _FIELD_RE.finditer(fields_text):
            name, type_raw, null_raw, length_raw, precision_raw, case_raw = match.groups()
            length = int(length_raw)
            null_exists = null_raw == "1"
            data_len = (1 if null_exists else 0) + calc_raw_field_len(type_raw, length)
            data_offset = 1 if type_raw == "RV" else offset
            if type_raw != "RV":
                offset += data_len
            fields.append(
                Field(
                    name=name,
                    type=field_type_from_raw(type_raw),
                    null_exists=null_exists,
                    length=length,
                    precision=int(precision_raw),
                    case_sensitive=(case_raw == "CS"),
                    offset=data_offset,
                )
            )
        return fields

    def _parse_indexes(self, indexes_text: str) -> List[Index]:
        indexes = []
        depth = 0
        start = -1
        for pos, char in enumerate(indexes_text):
            if char == "{":
                depth += 1
                if depth == 2:
                    start = pos
            elif char == "}":
                if depth == 2 and start >= 0:
                    block = indexes_text[start:pos + 1]
                    match = re.match(r'\{\s*"([^"]+)"\s*,\s*([01])\s*,', block)
                    if match:
                        fields = [
                            IndexField(name=_clean_name(name), descending=int(size) < 0)
                            for name, size in re.findall(r'\{\s*"([^"]+)"\s*,\s*(-?\d+)\s*\}', block)
                        ]
                        indexes.append(Index(_clean_name(match.group(1)), match.group(2) == "1", fields))
                depth = max(0, depth - 1)
        return indexes

    def _base_fsize(self, field_type: FieldType, length: int) -> int:
        return calc_raw_field_len(field_type.value, length)

    def _field_size(self, field: Field) -> int:
        return self._base_fsize(field.type, field.length) + int(field.null_exists)

    def _apply_physical_layout(self, table: Table) -> None:
        versions = [field for field in table.fields if field.type == FieldType.VERSION]
        fields = [field for field in table.fields if field.type != FieldType.VERSION]
        offset = 1
        if not versions and str(table.recordlock) == "1":
            offset += 8
        table.fields = versions + fields
        for field in table.fields:
            field.offset = offset
            offset += self._field_size(field)
        table.row_size = max(offset, 5)

    def _parse_bcd(self, data: bytes, length: int, precision: int) -> Any:
        value = decode_numeric(data, length, precision)
        return float(value) if isinstance(value, Decimal) else value

    def _parse_val(self, field: Field, data: bytes) -> Any:
        """Compatibility for legacy callers requesting a displayed field value."""
        value = self._decode_field(field, data, None, False)
        if isinstance(value, Decimal):
            return float(value)
        return decode_value_by_column_name(field.name, value)

    def _calc_row_size(self, fields: List[Field]) -> int:
        offset = 17 if any(f.type == FieldType.VERSION for f in fields) else 1
        for field in fields:
            raw_type = raw_type_from_field(field)
            field_len = (1 if field.null_exists else 0) + calc_raw_field_len(raw_type, field.length)
            if raw_type == "RV":
                offset = max(offset, 1 + field_len)
            else:
                offset = max(offset, field.offset + field_len)
        return max(offset, 5)

    def _read_page(self, page_number: int) -> bytes:
        assert self._fh is not None
        if page_number < 0:
            raise ValueError(f"Negative page number: {page_number}")
        cached = self._page_cache.get(page_number)
        if cached is not None:
            return cached
        self._fh.seek(page_number * self.page_size)
        data = self._fh.read(self.page_size)
        if len(data) < self.page_size:
            data = data.ljust(self.page_size, b"\x00")
        if len(self._page_cache) < self.cache_pages:
            self._page_cache[page_number] = data
        return data

    def _table_data_object(self, table: Table) -> DBObject:
        if table.data_object_id is None:
            raise ValueError(f"Table {table.name} has no data object id")
        obj = DBObject(self, table.data_object_id)
        self._table_data_pages[table.name] = obj.pages
        return obj

    def _table_blob_object(self, table: Table) -> Optional[DBObject]:
        try:
            blob_id = int(table.files[1]) if len(table.files) > 1 else 0
        except (TypeError, ValueError):
            return None
        if blob_id <= 0:
            return None
        return DBObject(self, blob_id)

    def get_table_names(self) -> List[str]:
        return list(self.tables.keys())

    def get_table_info(self, name: str) -> Optional[Table]:
        return self.tables.get(name)

    def get_total_rows(self, name: str) -> int:
        table = self.tables.get(name)
        if not table or table.row_size <= 0:
            return 0
        try:
            return self._table_data_object(table).length // table.row_size
        except (ValueError, NotImplementedError):
            return 0

    def _get_blob_raw(self, table: Table) -> bytes:
        obj = self._table_blob_object(table)
        return obj.read() if obj is not None else b""

    def read_blob_chain(self, table_name: str, start_block: int, length: int) -> bytes:
        table = self.tables.get(table_name)
        if table is None or start_block <= 0 or length <= 0:
            return b""
        obj = self._table_blob_object(table)
        return BlobRef(obj, length, start_block, "I").value if obj is not None else b""

    def get_database_info(self) -> Dict[str, Any]:
        if self.header is None:
            return {}
        for table in self.tables.values():
            if table.name not in self._table_data_pages:
                try:
                    self._table_data_object(table)
                except (ValueError, NotImplementedError):
                    self._table_data_pages[table.name] = []
        return {"file": self.filepath, **asdict(self.header), "tables_count": len(self.tables), "read_only": True}

    def iter_table_rows(
        self,
        name: str,
        offset: int = 0,
        limit: Optional[int] = None,
        read_blobs: bool = False,
        include_deleted: bool = False,
        decode: bool = True,
        rich_refs: bool = False,
        resolver: Any = None,
    ) -> Iterator[Dict[str, Any]]:
        table = self.tables.get(name)
        if not table:
            raise KeyError(f"Table not found: {name}")
        if table.row_size <= 0:
            return
        if limit is not None and limit <= 0:
            return

        data_obj = self._table_data_object(table)
        blob_obj = self._table_blob_object(table)
        row_size = table.row_size
        pos = max(0, offset) * row_size
        emitted = 0

        while pos + row_size <= data_obj.length:
            raw = data_obj.read(pos, row_size)
            pos += row_size
            if not raw:
                break
            is_deleted = raw[:1] == b"\x01"
            if is_deleted and not include_deleted:
                continue
            record = self._decode_row(table, raw, blob_obj, read_blobs)
            record["__deleted__"] = is_deleted
            if decode:
                record = self.decode_record(record, resolver=resolver, rich_refs=rich_refs)
            yield record
            emitted += 1
            if limit is not None and emitted >= limit:
                break

    def get_table_data(
        self,
        name: str,
        limit: int = 200,
        offset: int = 0,
        read_blobs: bool = False,
        decode: bool = True,
        rich_refs: bool = False,
        resolver: Any = None,
    ) -> List[Dict[str, Any]]:
        return list(
            self.iter_table_rows(
                name,
                offset=offset,
                limit=limit,
                read_blobs=read_blobs,
                decode=decode,
                rich_refs=rich_refs,
                resolver=resolver,
            )
        )

    def get_table_data_advanced(self, name: str, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        # Compatibility method for the old UI worker.
        return self.get_table_data(name, limit=limit, offset=offset, read_blobs=False, decode=True)

    def decode_record(self, row: Dict[str, Any], resolver: Any = None, rich_refs: bool = False) -> Dict[str, Any]:
        """Decode bytes in a row to migration/UI-friendly values.

        By default *_RRef values are shown as 1C-style UUID strings, *_TRef and
        *_TRRef as hex type tokens, and other bytes as hex. With rich_refs=True
        references become dictionaries with raw hex, both UUID candidates and
        optional resolver metadata.
        """
        decoded: "collections.OrderedDict[str, Any]" = collections.OrderedDict()
        for key, value in row.items():
            if key.startswith("__"):
                decoded[key] = json_safe(value)
            else:
                decoded[key] = decode_value_by_column_name(
                    key,
                    value,
                    resolver=resolver,
                    rich_refs=rich_refs,
                )
        return decoded

    def _decode_row(self, table: Table, raw: bytes, blob_obj: Optional[DBObject], read_blobs: bool) -> Dict[str, Any]:
        result: "collections.OrderedDict[str, Any]" = collections.OrderedDict()
        for field in table.fields:
            raw_type = raw_type_from_field(field)
            field_len = (1 if field.null_exists else 0) + calc_raw_field_len(raw_type, field.length)
            data = raw[field.offset : field.offset + field_len]
            result[field.name] = self._decode_field(field, data, blob_obj, read_blobs)
        return result

    def _decode_field(self, field: Field, data: bytes, blob_obj: Optional[DBObject], read_blobs: bool) -> Any:
        if field.null_exists:
            if not data or data[:1] == b"\x00":
                return None
            data = data[1:]
        if not data:
            return None

        raw_type = raw_type_from_field(field)
        if raw_type == "B":
            return data
        if raw_type == "L":
            return struct.unpack("<?", data[:1])[0]
        if raw_type == "N":
            return decode_numeric(data, field.length, field.precision)
        if raw_type == "NC":
            return data.decode("utf-16", errors="replace").rstrip("\x00")
        if raw_type == "NVC":
            return decode_nvc(data)
        if raw_type == "RV":
            return ".".join(str(part) for part in struct.unpack("<4i", data[:16]))
        if raw_type == "DT":
            return decode_datetime(data)
        if raw_type in {"NT", "I"}:
            if len(data) < 8:
                return None
            chunk_offset, size = struct.unpack_from("<2I", data, 0)
            if not blob_obj:
                return f"BLOB:{chunk_offset}:{size}"
            ref = BlobRef(blob_obj, size, chunk_offset, raw_type)
            return ref.value if read_blobs else ref.preview()
        return data

    def debug_table_data(self, name: str) -> Dict[str, Any]:
        table = self.tables.get(name)
        if not table:
            return {"error": f"Table not found: {name}"}
        info: Dict[str, Any] = {
            "name": table.name,
            "row_size": table.row_size,
            "fields": len(table.fields),
            "files": table.files,
            "data_object_id": table.data_object_id,
        }
        try:
            obj = self._table_data_object(table)
            info.update({"object_length": obj.length, "pages": len(obj.pages), "rows": self.get_total_rows(name)})
        except Exception as exc:
            info["object_error"] = str(exc)
        return info

    def export_structure(self, path: str) -> bool:
        self._validate_export_path(path)
        data = {
            "header": asdict(self.header) if self.header else None,
            "locale": self.locale,
            "tables_count": len(self.tables),
            "description_errors": self._description_errors[:100],
            "tables": {},
        }
        for name, table in self.tables.items():
            data["tables"][name] = {
                "name": table.name,
                "recordlock": table.recordlock,
                "files": table.files,
                "data_object_id": table.data_object_id,
                "row_size": table.row_size,
                "records_count": self.get_total_rows(name),
                "fields": [
                    {
                        "name": f.name,
                        "type": raw_type_from_field(f),
                        "null_exists": f.null_exists,
                        "length": f.length,
                        "precision": f.precision,
                        "case_sensitive": f.case_sensitive,
                        "offset": f.offset,
                    }
                    for f in table.fields
                ],
                "indexes": table.indexes,
            }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, default=json_safe)
        return True

    def export_table_json(self, table_name: str, path: str, limit: Optional[int] = None, read_blobs: bool = False, decode: bool = True, rich_refs: bool = False, resolver: Any = None) -> int:
        self._validate_export_path(path)
        count = 0
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[\n")
            first = True
            for row in self.iter_table_rows(table_name, limit=limit, read_blobs=read_blobs, decode=decode, rich_refs=rich_refs, resolver=resolver):
                if not first:
                    fh.write(",\n")
                first = False
                json.dump(row, fh, ensure_ascii=False, default=json_safe)
                count += 1
            fh.write("\n]\n")
        return count

    def export_table_csv(self, table_name: str, path: str, limit: Optional[int] = None, read_blobs: bool = False, decode: bool = True, resolver: Any = None) -> int:
        self._validate_export_path(path)
        table = self.tables[table_name]
        fieldnames = [f.name for f in table.fields] + ["__deleted__"]
        count = 0
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in self.iter_table_rows(table_name, limit=limit, read_blobs=read_blobs, decode=decode, rich_refs=False, resolver=resolver):
                writer.writerow({k: json_safe(v) for k, v in row.items()})
                count += 1
        return count

    def _validate_export_path(self, path: str) -> None:
        source = Path(self.filepath).resolve()
        target = Path(path).resolve()
        same_file = target == source
        if not same_file and target.exists() and source.exists():
            same_file = os.path.samefile(source, target)
        if same_file:
            raise ValueError("Cannot export over the read-only 1CD source")
