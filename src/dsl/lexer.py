"""MetaScript Lexer — tokenizes MetaScript source code.

Supports:
  - Unicode identifiers (Ukrainian letters etc.)
  - Integer and float literals: 42  3.14  1_000_000
  - BSL-compatible strings: doubled delimiters and literal backslashes
  - Single-line comments: // and #
  - Multi-line comments: /* ... */
  - All operators and delimiters
  - Ukrainian / English keyword sets
  - Internal mixed import-compatibility profile for legacy 1C/BAS code
  - Preprocessor directives: #Якщо #Область etc.
  - Case-insensitive keyword matching
"""

from __future__ import annotations

from typing import Iterator, List

from .ast import SourceSpan
from .diagnostics import ParseError
from .languages import LanguageProfile, get_source_preprocessor_aliases
from .tokens import Token, TokenType


# ---------------------------------------------------------------------------
# Single-character token map
# ---------------------------------------------------------------------------
_SINGLE: dict[str, TokenType] = {
    "(": "LPAREN",
    ")": "RPAREN",
    "[": "LBRACKET",
    "]": "RBRACKET",
    "{": "LBRACE",
    "}": "RBRACE",
    ",": "COMMA",
    ";": "SEMICOLON",
    ":": "COLON",
    ".": "DOT",
    "?": "QUESTION",
    "&": "AMPERSAND",
    "%": "PERCENT",
    "+": "PLUS",
    "-": "MINUS",
    "*": "STAR",
    "~": "TILDE",
}


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_" or ord(ch) > 127


def _is_ident_cont(ch: str) -> bool:
    return ch.isalnum() or ch in ("_",) or ord(ch) > 127


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

class Lexer:
    """Stateful lexer for MetaScript."""

    def __init__(self, text: str, profile: LanguageProfile, *, strict: bool = False,
                 strict_directives: bool = False) -> None:
        self._text = text
        self._profile = profile
        self._strict = strict
        self._strict_directives = strict_directives
        self._pp_aliases = get_source_preprocessor_aliases(profile.language)
        self._i = 0
        self._line = 1
        self._col = 1

    # ---- position helpers ----

    def _cur(self, offset: int = 0) -> str:
        idx = self._i + offset
        if idx >= len(self._text):
            return ""
        return self._text[idx]

    def _span(self) -> SourceSpan:
        return SourceSpan(line=self._line, col=self._col)

    def _advance(self) -> str:
        ch = self._cur()
        if not ch:
            return ""
        self._i += 1
        if ch == "\n":
            self._line += 1
            self._col = 1
        else:
            self._col += 1
        return ch

    def _skip_while(self, pred) -> None:
        while self._cur() and pred(self._cur()):
            self._advance()

    # ---- tokenize ----

    def tokenize(self) -> List[Token]:
        tokens: List[Token] = []
        while True:
            tok = self._next_token()
            tokens.append(tok)
            if tok.type == "EOF":
                break
        return tokens

    def source_tokens(self) -> Iterator[tuple[Token, int, int]]:
        """Yield tokens and exact source offsets, including raw multiline strings."""
        starts = [0] + [i + 1 for i, ch in enumerate(self._text) if ch == "\n"]
        while True:
            token = self._next_token()
            start = starts[token.span.line - 1] + token.span.col - 1
            yield token, start, self._i
            if token.type == "EOF":
                break

    def _next_token(self) -> Token:
        token = self._scan_token()
        while token is None:
            token = self._scan_token()
        return token

    def _scan_token(self) -> Token | None:
        if self._i == 0 and self._cur() == "\ufeff":
            self._advance()
        # skip whitespace
        while self._cur() and self._cur() in (" ", "\t", "\r", "\n"):
            self._advance()

        if not self._cur():
            return Token(type="EOF", text="", span=self._span())

        ch = self._cur()
        sp = self._span()

        # ----- single-line comment: // -----
        if ch == "/" and self._cur(1) == "/":
            while self._cur() and self._cur() != "\n":
                self._advance()
            return None

        # ----- single-line comment: # (not preprocessor here) -----
        if ch == "#":
            # Check for preprocessor directive: #Якщо #Область etc.
            word_start = word_end = self._i + 1
            while word_end < len(self._text) and _is_ident_cont(self._text[word_end]):
                word_end += 1
            if word_end > word_start:
                directive_word = self._text[word_start:word_end].lower()
                pp_map = self._pp_aliases
                if directive_word in pp_map:
                    raw = self._text[self._i:word_end]
                    while self._i < word_end:
                        self._advance()
                    return Token(type=pp_map[directive_word], text=raw, span=sp)
            if self._strict_directives:
                raise ParseError("Unknown or unsupported preprocessor directive", sp)
            # Otherwise: comment line starting with #
            while self._cur() and self._cur() != "\n":
                self._advance()
            return None

        # ----- multi-line comment: /* ... */ -----
        if ch == "/" and self._cur(1) == "*":
            self._advance(); self._advance()  # consume /*
            while self._cur():
                if self._cur() == "*" and self._cur(1) == "/":
                    self._advance(); self._advance()
                    break
                self._advance()
            else:
                if self._strict:
                    raise ParseError("Unterminated block comment", sp)
            return None

        # ----- string literals -----
        if ch in ('"', "'"):
            return self._lex_string(sp)

        # ----- numeric literals -----
        if ch.isdigit() or (ch == "." and self._cur(1).isdigit()):
            return self._lex_number(sp)

        # ----- operators -----
        if ch == "<":
            self._advance()
            if self._cur() == ">":
                self._advance()
                return Token(type="NEQ", text="<>", span=sp)
            if self._cur() == "=":
                self._advance()
                return Token(type="LE", text="<=", span=sp)
            return Token(type="LT", text="<", span=sp)

        if ch == ">":
            self._advance()
            if self._cur() == "=":
                self._advance()
                return Token(type="GE", text=">=", span=sp)
            return Token(type="GT", text=">", span=sp)

        if ch == "-" and self._cur(1) == ">":
            self._advance(); self._advance()
            return Token(type="ARROW", text="->", span=sp)

        if ch == ":" and self._cur(1) == "=":
            self._advance(); self._advance()
            return Token(type="ASSIGN", text=":=", span=sp)

        if ch == "=":
            self._advance()
            return Token(type="EQ", text="=", span=sp)

        if ch == "/":
            self._advance()
            return Token(type="SLASH", text="/", span=sp)

        # ----- single-char tokens -----
        if ch in _SINGLE:
            self._advance()
            return Token(type=_SINGLE[ch], text=ch, span=sp)

        # ----- identifiers / keywords -----
        if _is_ident_start(ch):
            return self._lex_ident(sp)

        # unknown character
        self._advance()
        return Token(type="UNKNOWN", text=ch, span=sp)

    def _lex_string(self, sp: SourceSpan) -> Token:
        quote = self._advance()
        buf: list[str] = []
        while self._cur():
            if self._cur() == quote:
                self._advance()
                if self._cur() == quote:
                    self._advance()
                    buf.append(quote)
                    continue
                break
            if self._cur() == "\n":
                self._advance()
                # BSL continues a string on physical lines prefixed with ``|``.
                # Source comments may be placed between continuation lines and
                # are not part of the resulting string value.
                while self._cur():
                    while self._cur() in (" ", "\t", "\r"):
                        self._advance()
                    if self._cur() == "/" and self._cur(1) == "/":
                        while self._cur() and self._cur() != "\n":
                            self._advance()
                        if self._cur() == "\n":
                            self._advance()
                        continue
                    if self._cur() == "\n":
                        self._advance()
                        continue
                    if self._cur() == "|":
                        self._advance()
                    buf.append("\n")
                    break
                continue
            buf.append(self._advance())
        else:
            if self._strict:
                raise ParseError("Unterminated string literal", sp)
        return Token(type="STRING", text="".join(buf), span=sp)

    def _lex_number(self, sp: SourceSpan) -> Token:
        start = self._i
        while self._cur() and (self._cur().isdigit() or self._cur() == "_"):
            self._advance()
        if self._cur() == ".":
            next_ch = self._cur(1)
            # BSL permits a decimal point without a fractional part (``0.``).
            # Keep ``1.Property`` tokenized as member access for MetaScript.
            is_member_access = bool(next_ch) and _is_ident_start(next_ch)
            if next_ch != "." and not is_member_access:
                self._advance()
                while self._cur() and (self._cur().isdigit() or self._cur() == "_"):
                    self._advance()
        raw = self._text[start:self._i].replace("_", "")
        return Token(type="NUMBER", text=raw, span=sp)

    def _lex_ident(self, sp: SourceSpan) -> Token:
        start = self._i
        while self._cur() and _is_ident_cont(self._cur()):
            self._advance()
        raw = self._text[start:self._i]
        key = raw.lower()
        kw = self._profile.keywords.get(key)
        if kw is not None:
            return Token(type=kw, text=raw, span=sp)
        # Special literals by value
        if key in ("true", "правда", "хибність"):
            return Token(type="TRUE", text=raw, span=sp)
        if key in ("false", "хиба"):
            return Token(type="FALSE", text=raw, span=sp)
        if key in ("undefined", "невизначено"):
            return Token(type="UNDEFINED", text=raw, span=sp)
        if key in ("null", "нуль"):
            return Token(type="NULL", text=raw, span=sp)
        return Token(type="IDENT", text=raw, span=sp)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lex(text: str, profile: LanguageProfile) -> List[Token]:
    """Tokenize MetaScript source text.

    Args:
        text: Source code string.
        profile: Language profile (uk / en / internal mixed compatibility).

    Returns:
        List of tokens ending with EOF.
    """
    return Lexer(text, profile).tokenize()
