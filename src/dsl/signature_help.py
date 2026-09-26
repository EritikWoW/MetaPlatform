"""Tolerant signature help over compiler tokens, independent of Qt or Runtime."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from .editor_syntax import BLOCK_COMMENT, CODE, LINE_COMMENT, scan_editor_line
from .languages import get_profile
from .lexer import Lexer


@dataclass(frozen=True)
class ParameterSignature:
    name: str
    by_value: bool = False
    default_text: str | None = None


@dataclass(frozen=True)
class CallableSignature:
    name: str
    kind: str
    parameters: tuple[ParameterSignature, ...]
    line: int = 0


@dataclass(frozen=True)
class CallContext:
    chain: tuple[str, ...]
    active_parameter: int
    opening_position: int


_OPEN = {"LPAREN": "RPAREN", "LBRACKET": "RBRACKET", "LBRACE": "RBRACE"}
_DECLARATIONS = {"KW_PROCEDURE", "KW_FUNCTION"}
_ENDS = {"KW_ENDPROCEDURE", "KW_ENDFUNCTION"}


class SignatureDocument:
    """One lexical snapshot per buffer revision; incomplete bodies are allowed.

    Offsets are Python code points. Callers using Qt must convert UTF-16 cursor
    positions. Duplicate declarations are retained, never resolved by guessing.
    """

    def __init__(self, source: str, *, language: str = "mixed") -> None:
        self.source = source
        self.tokens = list(Lexer(source, get_profile(language)).source_tokens())
        self.starts = [start for _token, start, _end in self.tokens]
        self.line_starts = [0]
        self.line_states = []
        state = CODE
        offset = 0
        for line in source.split("\n"):
            self.line_states.append(state)
            state = scan_editor_line(line, state).state
            offset += len(line) + 1
            self.line_starts.append(offset)
        self.signatures: dict[str, list[CallableSignature]] = {}
        self.callable_names: set[str] = set()
        self._scopes: list[tuple[int, int, set[str]]] = []
        self._module_names: set[str] = set()
        self._collect_declarations()

    def _chain_before(self, index: int) -> tuple[tuple[str, ...], int]:
        i = index - 1
        if i < 0 or self.tokens[i][0].type != "IDENT":
            return (), i
        chain = [self.tokens[i][0].text]
        i -= 1
        while i >= 0 and self.tokens[i][0].type == "DOT":
            if i == 0 or self.tokens[i - 1][0].type != "IDENT":
                return (), i
            chain.insert(0, self.tokens[i - 1][0].text)
            i -= 2
        return tuple(chain), i

    def context_at(self, position: int) -> CallContext | None:
        position = max(0, min(position, len(self.source)))
        line = bisect_right(self.line_starts, position) - 1
        prefix = self.source[self.line_starts[line]:position]
        scanned = scan_editor_line(prefix, self.line_states[line])
        if scanned.state in (BLOCK_COMMENT, LINE_COMMENT):
            return None
        # Continuation-line comments retain the surrounding string state.
        # A closed block comment, however, leaves the caret back in code.
        if scanned.state != CODE and scanned.spans and scanned.spans[-1].kind == "comment" and scanned.spans[-1].end == len(prefix):
            return None
        # closer, callable chain, argument index, opening offset, declaration
        stack: list[list] = []
        for index in range(bisect_left(self.starts, position)):
            token, start, _end = self.tokens[index]
            kind = token.type
            if kind in _OPEN:
                chain, before = self._chain_before(index) if kind == "LPAREN" else ((), -1)
                declaration = bool(chain and before >= 0 and self.tokens[before][0].type in _DECLARATIONS)
                stack.append([_OPEN[kind], chain, 0, start, declaration])
            elif kind in _OPEN.values():
                if not stack or stack[-1][0] != kind:
                    stack.clear()
                else:
                    stack.pop()
            elif kind == "COMMA" and stack and stack[-1][1]:
                stack[-1][2] += 1
            elif kind == "SEMICOLON" or kind in _DECLARATIONS or kind in _ENDS:
                stack.clear()
        if any(frame[4] for frame in stack):
            return None
        for _close, chain, active, opening, _declaration in reversed(stack):
            if chain:
                return CallContext(chain, active, opening)
        return None

    def _header(self, index: int) -> tuple[CallableSignature, int] | None:
        tokens = self.tokens
        if index + 2 >= len(tokens) or tokens[index + 1][0].type != "IDENT" or tokens[index + 2][0].type != "LPAREN":
            return None
        parameters = []
        start = index + 3
        stack = []
        for cursor in range(start, len(tokens)):
            token = tokens[cursor][0]
            if token.type in _DECLARATIONS | _ENDS | {"EOF"}:
                return None
            if not stack and token.type in {"RPAREN", "COMMA"}:
                part = tokens[start:cursor]
                if part:
                    by_value = part[0][0].type == "KW_VAL"
                    name_index = int(by_value)
                    if len(part) <= name_index or part[name_index][0].type != "IDENT":
                        return None
                    default = None
                    if len(part) > name_index + 1:
                        if part[name_index + 1][0].type != "EQ" or len(part) <= name_index + 2:
                            return None
                        default = self.source[part[name_index + 2][1]:part[-1][2]]
                    parameters.append(ParameterSignature(part[name_index][0].text, by_value, default))
                elif token.type == "COMMA" or parameters:
                    return None
                if token.type == "RPAREN":
                    return CallableSignature(
                        tokens[index + 1][0].text,
                        "procedure" if tokens[index][0].type == "KW_PROCEDURE" else "function",
                        tuple(parameters), tokens[index][0].span.line,
                    ), cursor
                start = cursor + 1
            elif token.type in _OPEN:
                stack.append(_OPEN[token.type])
            elif token.type in _OPEN.values():
                if not stack or stack.pop() != token.type:
                    return None
        return None

    def _collect_declarations(self) -> None:
        current_names = self._module_names
        scope_start = None
        for index, (token, start, end) in enumerate(self.tokens):
            if token.type in _DECLARATIONS:
                if index + 1 < len(self.tokens) and self.tokens[index + 1][0].type == "IDENT":
                    self.callable_names.add(self.tokens[index + 1][0].text.casefold())
                if scope_start is not None:
                    self._scopes.append((scope_start, start, current_names))
                header = self._header(index)
                scope_start = start
                current_names = set()
                if header is not None:
                    signature, _end_index = header
                    self.signatures.setdefault(signature.name.casefold(), []).append(signature)
                    current_names.update(p.name.casefold() for p in signature.parameters)
            elif token.type in _ENDS and scope_start is not None:
                self._scopes.append((scope_start, end, current_names))
                scope_start = None
                current_names = self._module_names
            elif token.type == "IDENT":
                previous = self.tokens[index - 1][0].type if index else ""
                following = self.tokens[index + 1][0].type if index + 1 < len(self.tokens) else ""
                if previous in {"KW_VAR", "KW_FOR", "KW_EACH"} or (following in {"EQ", "ASSIGN"} and previous != "DOT"):
                    current_names.add(token.text.casefold())
            elif token.type == "KW_VAR":
                for next_index in range(index + 1, len(self.tokens)):
                    declaration = self.tokens[next_index][0]
                    if declaration.type in {"SEMICOLON", "EOF"}:
                        break
                    if declaration.type == "IDENT":
                        current_names.add(declaration.text.casefold())
        if scope_start is not None:
            self._scopes.append((scope_start, len(self.source) + 1, current_names))

    def is_shadowed(self, name: str, position: int) -> bool:
        folded = name.casefold()
        return folded in self._module_names or any(
            start <= position < end and folded in names for start, end, names in self._scopes
        )
