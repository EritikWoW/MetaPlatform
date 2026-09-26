from __future__ import annotations

from typing import Any


_DOCUMENT_LIKE_TYPES = frozenset({
    "document",
    "business_process",
    "task",
})


def data_table_name(obj_type: str, obj_name: str) -> str:
    type_name = str(obj_type or "").strip().lower()
    object_name = str(obj_name or "").strip().lower()
    return f"data_document_{object_name}" if type_name in _DOCUMENT_LIKE_TYPES else f"data_catalog_{object_name}"


def infer_data_table_name(obj_name: str, record: Any) -> str:
    rec = record if isinstance(record, dict) else {}
    obj_type = "document" if any(key in rec for key in ("_date", "_posted", "_number_prefix", "_operation_kind")) else "catalog"
    return data_table_name(obj_type, obj_name)
