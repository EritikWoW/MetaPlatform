"""Public API for DSL parsing and validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .diagnostics import Diagnostic
from .languages import DslLanguage, get_profile
from .parser import parse
from .validator import validate


@dataclass(frozen=True, slots=True)
class ParseResult:
    program: Optional[object]
    diagnostics: tuple[Diagnostic, ...]


def parse_dsl(text: str, language: DslLanguage = "uk") -> ParseResult:
    """Parse and validate DSL.

    Args:
        text: DSL source.
        language: 'uk' or 'en'.

    Returns:
        ParseResult with `program` as AST Program or None on parse error.
    """

    profile = get_profile(language)
    program, diags = parse(text, profile)
    if program is not None:
        diags.extend(validate(program))
    return ParseResult(program=program, diagnostics=tuple(diags))
