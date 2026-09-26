"""Token definitions for MetaScript — BSL-compatible language (EN/UK).

MetaScript is the built-in language of MetaPlatform.
It is syntactically close to 1C:BSL but supports both
Ukrainian and English keywords.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .ast import SourceSpan


TokenType = Literal[
    # Literals
    "NUMBER", "STRING", "TRUE", "FALSE", "UNDEFINED", "NULL",
    # Identifiers
    "IDENT",
    # Arithmetic
    "PLUS", "MINUS", "STAR", "SLASH", "PERCENT",
    # Comparison
    "EQ", "NEQ", "LT", "GT", "LE", "GE",
    # Assignment
    "ASSIGN",
    # Logical
    "NOT", "AND", "OR",
    # Delimiters
    "LPAREN", "RPAREN", "LBRACKET", "RBRACKET", "LBRACE", "RBRACE",
    "COMMA", "SEMICOLON", "COLON", "DOT", "QUESTION", "AMPERSAND",
    "ARROW", "TILDE",
    # Control flow
    "KW_IF", "KW_THEN", "KW_ELSEIF", "KW_ELSE", "KW_ENDIF",
    "KW_FOR", "KW_EACH", "KW_IN", "KW_TO", "KW_DO", "KW_ENDDO",
    "KW_WHILE", "KW_ENDWHILE",
    "KW_BREAK", "KW_CONTINUE", "KW_RETURN",
    "KW_TRY", "KW_EXCEPT", "KW_RAISE", "KW_ENDTRY",
    # Declarations
    "KW_PROCEDURE", "KW_ENDPROCEDURE",
    "KW_FUNCTION", "KW_ENDFUNCTION",
    "KW_VAR", "KW_EXPORT", "KW_VAL",
    # New/Delete
    "KW_NEW", "KW_DELETE",
    # Goto
    "KW_GOTO",
    # Preprocessor
    "KW_IF_COMPILE", "KW_THEN_COMPILE", "KW_ELSEIF_COMPILE", "KW_ELSE_COMPILE", "KW_ENDIF_COMPILE",
    "KW_REGION", "KW_ENDREGION", "KW_USE",
    # DSL / metadata
    "KW_CATALOG", "KW_DOCUMENT", "KW_REGISTER", "KW_ENUM", "KW_FORM",
    "KW_FIELDS", "KW_TABLE", "KW_DIMENSIONS", "KW_RESOURCES",
    "KW_MODULE", "KW_SUBSYSTEM", "KW_ROLE",
    # Special
    "EOF", "UNKNOWN",
]


@dataclass(frozen=True, slots=True)
class Token:
    type: TokenType
    text: str
    span: SourceSpan

    def is_keyword(self) -> bool:
        return self.type.startswith("KW_")

    def __repr__(self) -> str:
        return f"Token({self.type}, {self.text!r}, L{self.span.line}:C{self.span.col})"
