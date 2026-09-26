"""Diagnostics and errors for DSL parsing/validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .ast import SourceSpan


Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: Severity
    message: str
    span: SourceSpan


class DslError(Exception):
    """Base exception for DSL pipeline."""


class ParseError(DslError):
    """Raised on unrecoverable parsing error."""

    def __init__(self, message: str, span: SourceSpan):
        super().__init__(f"{message} (line {span.line}, col {span.col})")
        self.message = message
        self.span = span
