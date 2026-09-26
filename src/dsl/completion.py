from __future__ import annotations

"""Tolerant completion context for unfinished MetaScript expressions."""

from dataclasses import dataclass
import re
from typing import Iterable, Mapping

from src.dsl.platform_symbols import (
    METADATA_COLLECTION_MEMBERS,
    METADATA_OBJECT_MEMBERS,
    METADATA_ROOTS,
    metadata_category_for_name,
    metadata_root_members,
)


_IDENT = r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ_][A-Za-zА-Яа-яЁёІіЇїЄєҐґ0-9_]*"
_CHAIN_RE = re.compile(rf"({_IDENT}(?:\s*\.\s*{_IDENT})*\s*\.?\s*(?:{_IDENT})?)$")


@dataclass(frozen=True, slots=True)
class CompletionContext:
    chain: tuple[str, ...]
    prefix: str
    replace_length: int
    line: int


def completion_context(source: str, cursor_position: int) -> CompletionContext:
    text = str(source or "")
    position = max(0, min(int(cursor_position), len(text)))
    before = text[:position]
    line = before.count("\n") + 1
    current_line = before.rsplit("\n", 1)[-1]
    match = _CHAIN_RE.search(current_line)
    if match is None:
        return CompletionContext((), "", 0, line)
    expression = re.sub(r"\s+", "", match.group(1))
    if not expression:
        return CompletionContext((), "", 0, line)
    if expression.endswith("."):
        parts = tuple(part for part in expression[:-1].split(".") if part)
        return CompletionContext(parts, "", 0, line)
    parts = tuple(part for part in expression.split(".") if part)
    if len(parts) <= 1:
        prefix = parts[0] if parts else ""
        return CompletionContext((), prefix, len(prefix), line)
    prefix = parts[-1]
    return CompletionContext(parts[:-1], prefix, len(prefix), line)


def semantic_completion_candidates(
    context: CompletionContext,
    visible_symbols: Iterable[str],
    *,
    metadata_objects: Mapping[str, Iterable[str]] | None = None,
    namespace_members: Mapping[str, Iterable[str]] | None = None,
) -> list[str]:
    chain = context.chain
    if not chain:
        return sorted({str(item).strip() for item in visible_symbols if str(item).strip()}, key=str.casefold)

    root = chain[0].casefold()
    if root not in {name.casefold() for name in METADATA_ROOTS}:
        if len(chain) == 1 and namespace_members is not None:
            members = namespace_members.get(root, ())
            return sorted(
                {
                    str(item).strip()
                    for item in members
                    if str(item).strip()
                },
                key=str.casefold,
            )
        return []
    if len(chain) == 1:
        return sorted(set(metadata_root_members()), key=str.casefold)

    category = metadata_category_for_name(chain[1])
    if category is None:
        return sorted(set(METADATA_OBJECT_MEMBERS), key=str.casefold)
    if len(chain) == 2:
        objects = []
        if metadata_objects is not None:
            objects = [str(item).strip() for item in metadata_objects.get(category.type_name, ()) if str(item).strip()]
        return sorted(set([*METADATA_COLLECTION_MEMBERS, *objects]), key=str.casefold)
    return sorted(set(METADATA_OBJECT_MEMBERS), key=str.casefold)
