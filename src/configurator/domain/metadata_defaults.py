from __future__ import annotations

"""Metadata defaults integration helpers.

This module provides a single entry point used by ViewModels/Services to
populate object payload with:
- default requisites
- default commands

The merge functions are idempotent.
"""

from typing import Any, Dict, Optional

from .default_commands import default_commands_for_object, merge_commands
from .default_requisites import default_requisites_for_object, merge_requisites


def build_default_payload_patch(*, obj_type: str, subtype: str | None = None) -> Dict[str, Any]:
    """Build a payload patch containing defaults for the given object type."""
    return {
        "requisites": default_requisites_for_object(obj_type=obj_type, subtype=subtype),
        "commands": default_commands_for_object(obj_type=obj_type, subtype=subtype),
    }


def ensure_payload_defaults(*, payload: Any, obj_type: str, subtype: str | None = None) -> Dict[str, Any]:
    """Return payload with ensured defaults (no mutation of input).

    We only touch keys that are relevant for the given object type:
    - if defaults are empty and the key does not exist in payload, we do not add it
      (to avoid polluting payload for object types that do not use requisites/commands).
    """
    p = payload if isinstance(payload, dict) else {}
    p2: Dict[str, Any] = dict(p)

    req_defaults = default_requisites_for_object(obj_type=obj_type, subtype=subtype)
    cmd_defaults = default_commands_for_object(obj_type=obj_type, subtype=subtype)

    if req_defaults or ("requisites" in p):
        p2["requisites"] = merge_requisites(p.get("requisites"), req_defaults)

    if cmd_defaults or ("commands" in p):
        p2["commands"] = merge_commands(p.get("commands"), cmd_defaults)

    return p2
