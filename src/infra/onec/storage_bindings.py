"""Exact storage identifiers, shared by migration and legacy packed readers."""
from __future__ import annotations


def load_storage_bindings(source_path: str) -> dict[str, dict[str, int]]:
    from .com_1cd_bridge import parse_dbnames

    bindings: dict[str, dict[str, int]] = {}
    for record in parse_dbnames(source_path):
        target = bindings.setdefault(record.uuid.casefold(), {})
        if record.tag in target and target[record.tag] != record.suffix:
            raise ValueError(f"Ambiguous DBNames entry: {record.uuid}/{record.tag}")
        target[record.tag] = record.suffix
    if not bindings:
        raise ValueError("DBNames does not contain storage bindings")
    return bindings
