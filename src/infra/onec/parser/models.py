#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Internal read-only 1CD parser data models.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class FieldType(Enum):
    BINARY = "B"
    VARIABLE_BINARY = "VB"
    BOOLEAN = "L"
    NUMBER = "N"
    FIXED_STRING = "NC"
    VAR_STRING = "NVC"
    VERSION = "RV"
    UNLIMITED_STRING = "NT"
    UNLIMITED_BINARY = "I"
    DATETIME = "DT"


@dataclass
class Field:
    name: str
    type: FieldType
    null_exists: bool
    length: int
    precision: int
    case_sensitive: str | bool
    offset: int = 0  # Смещение в записи


@dataclass
class IndexField:
    name: str
    descending: bool = False


@dataclass
class Index:
    name: str
    unique: bool
    fields: List[IndexField]


@dataclass
class Table:
    name: str
    fields: List[Field] = field(default_factory=list)
    indexes: List[Index] = field(default_factory=list)
    recordlock: str = "0"
    files: List[str] = field(default_factory=lambda: ["0", "0", "0"])
    description: str = ""
    records_count: int = 0
    row_size: int = 0
    blob_fields: List[str] = field(default_factory=list)
    data_object_id: Optional[int] = None
    blob_object_id: Optional[int] = None
    index_object_id: Optional[int] = None


@dataclass
class DatabaseHeader:
    signature: str
    version: str
    total_pages: int
    unknown: int
    page_size: int
    file_size: int


@dataclass
class ObjectInfo:
    page: int
    type: int
    type_name: str
    length: int
    data_pages: List[int] = field(default_factory=list)


@dataclass
class Record:
    data: Dict[str, Any]
    raw_bytes: bytes = b""
