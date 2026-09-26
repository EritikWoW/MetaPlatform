"""Explicit compile-time branch selection without changing source coordinates.

This does not alter parser/editor defaults. Execution callers must opt in and
provide a context; no host environment or script variable changes that context.
"""
from __future__ import annotations

from dataclasses import dataclass

from .ast import SourceSpan
from .diagnostics import ParseError
from .languages import LanguageProfile
from .lexer import Lexer


_SYMBOL_GROUPS = {
    "server": ("Server", "AtServer", "Сервер", "НаСервері", "НаСервере"),
    "client": ("Client", "AtClient", "Клієнт", "НаКлієнті", "Клиент", "НаКлиенте"),
    "thinclient": ("ThinClient", "ТонкийКлієнт", "ТонкийКлиент"),
    "webclient": ("WebClient", "ВебКлієнт", "ВебКлиент"),
    "thickclientmanagedapplication": ("ThickClientManagedApplication", "ТовстийКлієнтКерованийЗастосунок",
                                      "ТолстыйКлиентУправляемоеПриложение"),
    "thickclientordinaryapplication": ("ThickClientOrdinaryApplication", "ТовстийКлієнтЗвичайнийЗастосунок",
                                       "ТолстыйКлиентОбычноеПриложение"),
    "externalconnection": ("ExternalConnection", "ЗовнішнєЗєднання", "ВнешнееСоединение"),
    "mobileclient": ("MobileClient", "МобільнийКлієнт", "МобильныйКлиент"),
    "mobileappclient": ("MobileAppClient", "МобільнийЗастосунокКлієнт", "МобильноеПриложениеКлиент"),
    "mobileappserver": ("MobileAppServer", "МобільнийЗастосунокСервер", "МобильноеПриложениеСервер"),
    "mobilestandaloneserver": ("MobileStandaloneServer", "МобільнийАвтономнийСервер", "МобильныйАвтономныйСервер"),
}
_SYMBOLS = {alias.casefold(): canonical for canonical, aliases in _SYMBOL_GROUPS.items() for alias in aliases}
SERVER_SYMBOLS = frozenset({"server"})
_PRECEDENCE = {"NOT": 3, "AND": 2, "OR": 1}


def _condition(tokens, defined, span):
    if not tokens or tokens[-1].type != "KW_THEN":
        raise ParseError("Preprocessor condition must end with Then", span)
    values, operators = [], []
    expect_value = True

    def reduce_one():
        operator = operators.pop()
        if operator == "NOT":
            values.append(not values.pop())
        else:
            right, left = values.pop(), values.pop()
            values.append(left and right if operator == "AND" else left or right)

    for token in tokens[:-1]:
        kind = token.type
        if expect_value:
            if kind in {"NOT", "LPAREN"}:
                operators.append(kind)
                continue
            if kind in {"TRUE", "FALSE"}:
                value = kind == "TRUE"
            elif token.text.casefold() in _SYMBOLS:
                value = _SYMBOLS[token.text.casefold()] in defined
            else:
                raise ParseError(f"Unknown compile-time symbol or invalid operand: {token.text}", token.span)
            values.append(value)
            expect_value = False
        elif kind == "RPAREN":
            while operators and operators[-1] != "LPAREN":
                reduce_one()
            if not operators:
                raise ParseError("Unmatched preprocessor parenthesis", token.span)
            operators.pop()
        elif kind in {"AND", "OR"}:
            while operators and operators[-1] != "LPAREN" and _PRECEDENCE[operators[-1]] >= _PRECEDENCE[kind]:
                reduce_one()
            operators.append(kind)
            expect_value = True
        else:
            raise ParseError(f"Invalid preprocessor operator: {token.text}", token.span)
    if expect_value or "LPAREN" in operators:
        raise ParseError("Incomplete preprocessor condition", span)
    while operators:
        reduce_one()
    return values[0]


@dataclass
class _Branch:
    parent_active: bool
    matched: bool
    active: bool
    span: SourceSpan
    else_seen: bool = False


def preprocess(source: str, profile: LanguageProfile, *, defined_symbols: frozenset[str], max_nesting=128) -> str:
    """Mask directives, comments and inactive tokens, preserving length/lines.

    Strings/comments must be lexically complete even in inactive branches.
    Unknown symbols/directives fail everywhere, never silently select a branch.
    """
    defined = frozenset(symbol.casefold() for symbol in defined_symbols)
    if not defined.issubset(_SYMBOL_GROUPS):
        raise ValueError("Unknown compilation context symbols")
    tokens = list(Lexer(source, profile, strict=True, strict_directives=True).source_tokens())
    result = [ch if ch in " \t\r\n" else " " for ch in source]
    branches, regions = [], []
    index = 0
    while index < len(tokens):
        token, start, end = tokens[index]
        index += 1
        if token.type == "EOF":
            break
        active = not branches or branches[-1].active
        is_directive = token.text.startswith("#") and token.type.startswith("KW_")
        if not is_directive:
            if active:
                result[start:end] = source[start:end]
            continue
        line_start = start - token.span.col + 1
        if source[line_start:start].strip(" \t\r\ufeff"):
            raise ParseError("Preprocessor directive must start a source line", token.span)
        args = []
        while index < len(tokens) and tokens[index][0].span.line == token.span.line and tokens[index][0].type != "EOF":
            args.append(tokens[index][0])
            index += 1
        kind = token.type
        if kind in {"KW_IF_COMPILE", "KW_ELSEIF_COMPILE"}:
            condition = _condition(args, defined, token.span)
            if kind == "KW_IF_COMPILE":
                if len(branches) >= max_nesting:
                    raise ParseError("Preprocessor nesting limit exceeded", token.span)
                branches.append(_Branch(active, condition, active and condition, token.span))
            else:
                if not branches or branches[-1].else_seen:
                    raise ParseError("Unexpected ElsIf directive", token.span)
                branch = branches[-1]
                branch.active = branch.parent_active and not branch.matched and condition
                branch.matched = branch.matched or condition
        elif kind in {"KW_ELSE_COMPILE", "KW_ENDIF_COMPILE"}:
            if args or not branches:
                raise ParseError("Unexpected or malformed conditional directive", token.span)
            if kind == "KW_ENDIF_COMPILE":
                branches.pop()
            else:
                branch = branches[-1]
                if branch.else_seen:
                    raise ParseError("Duplicate Else directive", token.span)
                branch.active = branch.parent_active and not branch.matched
                branch.else_seen = True
                branch.matched = True
        elif kind == "KW_REGION":
            if len(args) > 1 or (args and not args[0].text.isidentifier()):
                raise ParseError("Invalid region name", token.span)
            if len(regions) >= max_nesting:
                raise ParseError("Preprocessor nesting limit exceeded", token.span)
            regions.append(token.span)
        elif kind == "KW_ENDREGION":
            if args or not regions:
                raise ParseError("Unexpected EndRegion directive", token.span)
            regions.pop()
        else:
            raise ParseError(f"Unsupported preprocessor directive: {token.text}", token.span)
    if branches:
        raise ParseError("Unclosed If directive", branches[-1].span)
    if regions:
        raise ParseError("Unclosed Region directive", regions[-1])
    return "".join(result)
