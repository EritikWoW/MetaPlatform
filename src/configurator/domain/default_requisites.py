from __future__ import annotations

"""Default requisites (attributes) for metadata objects.

This module defines the *system* requisites that are created automatically for
new metadata objects (Catalogs, Documents, Registers, etc.).

Design goals:
- stable 'code' values (used for bindings, form columns, runtime mapping)
- localized titles stored as {'uk': ..., 'en': ...} for future UI rendering
- simple, explicit schema (no Qt dependencies)
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class RequisiteSpec:
    code: str
    title_uk: str
    title_en: str
    data_type: str  # 'string'|'number'|'bool'|'date'|'datetime'|'ref' ...
    length: Optional[int] = None
    precision: Optional[int] = None
    scale: Optional[int] = None
    required: bool = False
    read_only: bool = False
    system: bool = True

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "code": self.code,
            "title": {"uk": self.title_uk, "en": self.title_en},
            "type": self.data_type,
            "required": bool(self.required),
            "read_only": bool(self.read_only),
            "system": bool(self.system),
        }
        if self.length is not None:
            out["length"] = int(self.length)
        if self.precision is not None:
            out["precision"] = int(self.precision)
        if self.scale is not None:
            out["scale"] = int(self.scale)
        return out


def _catalog_defaults() -> List[RequisiteSpec]:
    # Minimal, 1C-like baseline for directory items.
    return [
        RequisiteSpec("Code", "Код", "Code", "string", length=12, required=True),
        RequisiteSpec("Description", "Найменування", "Description", "string", length=150, required=True),
        RequisiteSpec("DeletionMark", "Помітка видалення", "Deletion mark", "bool", read_only=True),
        RequisiteSpec("Predefined", "Попередньо визначений", "Predefined", "bool", read_only=True),
    ]


def _document_defaults() -> List[RequisiteSpec]:
    # Document header fields typical for accounting workflows.
    return [
        RequisiteSpec("Number", "Номер", "Number", "string", length=20, required=True),
        RequisiteSpec("Date", "Дата", "Date", "datetime", required=True),
        RequisiteSpec("Posted", "Проведено", "Posted", "bool", read_only=True),
        RequisiteSpec("DeletionMark", "Помітка видалення", "Deletion mark", "bool", read_only=True),
        RequisiteSpec("Comment", "Коментар", "Comment", "string", length=250),
    ]


def _register_common_defaults() -> List[RequisiteSpec]:
    # Registers usually have system dimensions for period/recorder, even if
    # user-defined dimensions/resources are added later.
    return [
        RequisiteSpec("Period", "Період", "Period", "datetime", required=True),
        RequisiteSpec("Recorder", "Регістратор", "Recorder", "ref", required=True, read_only=True),
        RequisiteSpec("LineNo", "Номер рядка", "Line No.", "number", precision=10, scale=0, read_only=True),
    ]


def default_requisites_for_object(*, obj_type: str, subtype: str | None = None) -> List[Dict[str, Any]]:
    """Return default requisites for the given metadata object type.

    Args:
        obj_type: manifest object type ('catalog', 'document', 'register_accum', ...)
        subtype: optional subtype (reserved for future use)

    Returns:
        List of dicts suitable for storing in object payload under 'requisites'.
    """
    t = (obj_type or "").strip().lower()

    specs: List[RequisiteSpec] = []
    if t == "catalog":
        specs = _catalog_defaults()
    elif t == "document":
        specs = _document_defaults()
    elif t in ("register_accum", "register_info"):
        specs = _register_common_defaults()
    else:
        specs = []

    return [s.to_dict() for s in specs]


def merge_requisites(existing: Any, defaults: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge defaults into existing requisites list.

    - Keeps existing entries (by 'code' or imported 1C 'name') as-is.
    - Adds missing defaults (by 'code' or 'name') at the end.
    - Returns a *new* list.
    """
    existing_list = existing if isinstance(existing, list) else []
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def identity(item: Dict[str, Any]) -> str:
        return str(item.get("code") or item.get("name") or "").strip().casefold()

    for item in existing_list:
        if not isinstance(item, dict):
            continue
        item_identity = identity(item)
        if not item_identity:
            continue
        if item_identity in seen:
            continue
        out.append(item)
        seen.add(item_identity)

    for d in defaults:
        item_identity = identity(d)
        if item_identity and item_identity not in seen:
            out.append(d)
            seen.add(item_identity)

    return out
