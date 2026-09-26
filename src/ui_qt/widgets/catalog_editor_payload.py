from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _parse_subsystems(value: Any) -> list[str]:
    """Normalize subsystem references to a unique GUID list."""

    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text and text not in out:
                out.append(text)
        return out
    if isinstance(value, str):
        text = (
            value.replace(";", " ")
            .replace(",", " ")
            .replace("\n", " ")
            .replace("\t", " ")
        )
        out: list[str] = []
        for item in text.split():
            part = str(item or "").strip()
            if part and part not in out:
                out.append(part)
        return out
    try:
        text = str(value or "").strip()
        return [text] if text else []
    except Exception:
        return []


@dataclass(frozen=True, slots=True)
class CatalogPayload:
    """Strongly-typed best-effort view over catalog payload."""

    name: str = ""
    synonym: str = ""
    comment: str = ""
    obj_presentation: str = ""
    obj_presentation_ext: str = ""
    list_presentation: str = ""
    list_presentation_ext: str = ""
    hint: str = ""
    code_length: int = 9
    name_length: int = 25
    code_type: str = "string"
    subsystems: list[str] = field(default_factory=list)

    @staticmethod
    def from_payload(payload: Any) -> "CatalogPayload":
        data = payload if isinstance(payload, dict) else {}
        return CatalogPayload(
            name=str(data.get("name") or ""),
            synonym=str(data.get("synonym") or ""),
            comment=str(data.get("comment") or ""),
            obj_presentation=str(data.get("obj_presentation") or ""),
            obj_presentation_ext=str(data.get("obj_presentation_ext") or ""),
            list_presentation=str(data.get("list_presentation") or ""),
            list_presentation_ext=str(data.get("list_presentation_ext") or ""),
            hint=str(data.get("hint") or ""),
            code_length=int(data.get("code_length") or 9),
            name_length=int(data.get("name_length") or 25),
            code_type=str(data.get("code_type") or "string"),
            subsystems=_parse_subsystems(data.get("subsystems")),
        )


__all__ = ["CatalogPayload", "_parse_subsystems"]
