from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID


def technical_object_name(
    name: Any = "", *, payload: Any = None, fallback: Any = ""
) -> str:
    """Project a Configurator name without synonyms or localized code aliases.

    Imported Source Name is authoritative when manifest.name is an old ASCII
    alias. Missing names remain visibly missing rather than masquerading as IDs.
    """
    data = payload if isinstance(payload, Mapping) else {}
    # Slim runtime snapshots retain the canonical reference but may omit
    # source_name. Use it without hydrating every object just to label the tree.
    reference = str(data.get("metadata_ref") or "")
    source_leaf = reference.rsplit(".", 1)[-1] if "." in reference else ""
    if not source_leaf.isidentifier():
        source_leaf = ""
    for value in (data.get("source_name"), source_leaf, name, data.get("name"), fallback):
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        try:
            UUID(value)
        except ValueError:
            return value
    return "<unnamed>"
