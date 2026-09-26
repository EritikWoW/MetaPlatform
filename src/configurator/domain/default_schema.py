from __future__ import annotations

"""Default schema templates for metadata objects.

This module provides idempotent default templates for:
- attributes (requisites)
- tabular parts

The goal is to give newly created objects a usable MVP schema,
without preventing users from customizing it later.

Notes
- We keep the schema minimal and stable.
- Functions return JSON-serializable structures.
"""

from typing import Any, Dict, List


def default_attributes_for_object(*, obj_type: str, subtype: str | None = None) -> List[Dict[str, Any]]:
    obj_type = (obj_type or "").strip()
    st = (subtype or "").strip()

    if obj_type in ("catalog", "catalogs"):
        return [
            {"name": "code", "type": "string", "required": True, "comment": ""},
            {"name": "description", "type": "string", "required": False, "comment": ""},
        ]

    if obj_type in ("document", "documents"):
        return [
            {"name": "number", "type": "string", "required": True, "comment": ""},
            {"name": "date", "type": "datetime", "required": True, "comment": ""},
            {"name": "posted", "type": "bool", "required": False, "comment": ""},
        ]

    # Default: no schema for unknown types.
    return []


def default_tabular_parts_for_object(*, obj_type: str, subtype: str | None = None) -> List[Dict[str, Any]]:
    obj_type = (obj_type or "").strip()
    st = (subtype or "").strip()

    if obj_type in ("document", "documents"):
        return [
            {
                "name": "items",
                "title": "Items",
                "comment": "",
                "columns": [
                    {"name": "item", "type": "string", "required": True, "comment": ""},
                    {"name": "qty", "type": "float", "required": True, "comment": ""},
                    {"name": "price", "type": "money", "required": False, "comment": ""},
                    {"name": "amount", "type": "money", "required": False, "comment": ""},
                ],
            }
        ]

    # Catalogs: no default tabular parts by default.
    return []


def ensure_schema_defaults(*, payload: Any, obj_type: str, subtype: str | None = None) -> Dict[str, Any]:
    """Ensure payload contains schema defaults (idempotent).

    We only add keys when:
    - defaults are non-empty OR the key already exists in payload
    - existing key value is missing/empty and defaults exist

    The function never mutates input payload.
    """
    p = payload if isinstance(payload, dict) else {}
    out: Dict[str, Any] = dict(p)

    attr_def = default_attributes_for_object(obj_type=obj_type, subtype=subtype)
    tp_def = default_tabular_parts_for_object(obj_type=obj_type, subtype=subtype)

    cur_attrs = out.get("attributes")
    if attr_def:
        if not isinstance(cur_attrs, list) or len(cur_attrs) == 0:
            out["attributes"] = attr_def

    cur_tp = out.get("tabular_parts")
    if tp_def:
        if not isinstance(cur_tp, list) or len(cur_tp) == 0:
            out["tabular_parts"] = tp_def

    return out
