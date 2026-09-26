from __future__ import annotations

from src.dsl.languages import get_profile
from src.dsl.lexer import Lexer


_REGISTER_TYPES = frozenset({
    "InformationRegister", "AccumulationRegister", "AccountingRegister", "CalculationRegister",
})
_HANDLER_NAMES = frozenset(name.casefold() for name in (
    "ОбработкаПроведения", "ОбробкаПроведення", "Posting", "PostingProcessing",
))


def find_posting_handler(source: str) -> int:
    """Find an existing handler without treating comments or strings as code.

    A lexical failure is deliberately propagated: insertion into a damaged
    module must not guess that its handler is absent.
    """
    try:
        tokens = Lexer(source, get_profile("mixed"), strict=True).tokenize()
    except Exception as exc:
        raise ValueError("Cannot inspect the module safely") from exc
    opened = None
    for token in tokens:
        if token.type == "UNKNOWN":
            raise ValueError(f"Unknown token at line {token.span.line}")
        if token.type in {"KW_PROCEDURE", "KW_FUNCTION"}:
            if opened:
                raise ValueError("Nested or unterminated procedure")
            opened = token.type
        elif token.type in {"KW_ENDPROCEDURE", "KW_ENDFUNCTION"}:
            expected = "KW_PROCEDURE" if token.type == "KW_ENDPROCEDURE" else "KW_FUNCTION"
            if opened != expected:
                raise ValueError("Unmatched procedure ending")
            opened = None
    if opened:
        raise ValueError("Unterminated procedure")
    matches = [
        token.span.line
        for token, following in zip(tokens, tokens[1:])
        if token.type in {"KW_PROCEDURE", "KW_FUNCTION"}
        and following.text.casefold() in _HANDLER_NAMES
    ]
    if len(matches) > 1:
        raise ValueError("Multiple posting handlers found")
    return matches[0] if matches else 0


def validate_posting_handler(code: str) -> None:
    """Only insert a complete single procedure, never arbitrary module code."""
    from src.dsl.ast import ProcedureDecl
    from src.dsl.parser import parse

    if not find_posting_handler(code):
        raise ValueError("Posting handler is missing")
    program, diagnostics = parse(code, get_profile("mixed"))
    if diagnostics or program is None or len(program.items) != 1:
        raise ValueError("Expected one valid posting procedure")
    procedure = program.items[0]
    if not isinstance(procedure, ProcedureDecl) or len(procedure.params) != 2:
        raise ValueError("Expected a posting procedure with two parameters")


def generate_posting_handler(
    register_refs: list[str] | tuple[str, ...], *, language: str = "uk",
) -> str:
    """Generate a starter, not invented business rules or populated movements."""
    if language not in {"uk", "en"}:
        raise ValueError("Unsupported posting language")

    names: list[str] = []
    refs_by_name: dict[str, str] = {}
    for ref in register_refs:
        value = str(ref or "").strip()
        prefix, separator, name = value.partition(".")
        if not separator or prefix not in _REGISTER_TYPES or not name.isidentifier():
            raise ValueError(f"Invalid register reference: {value}")
        if Lexer(name, get_profile("mixed")).tokenize()[0].type != "IDENT":
            raise ValueError(f"Invalid register name: {name}")
        previous = refs_by_name.get(name.casefold())
        if previous and previous.casefold() != value.casefold():
            raise ValueError(f"Ambiguous register name: {name}")
        if previous is None:
            names.append(name)
            refs_by_name[name.casefold()] = value
    if not names:
        raise ValueError("Select at least one register")
    if language == "en":
        signature = "Procedure Posting(Cancel, PostingMode)"
        movements, write, true, ending = "Movements", "Write", "True", "EndProcedure"
        hint = "// Add movement records and field mappings for the document's business rules."
    else:
        signature = "Процедура ОбробкаПроведення(Відмова, РежимПроведення)"
        movements, write, true, ending = "Рухи", "Записувати", "Істина", "КінецьПроцедури"
        hint = "// Додайте записи рухів і заповнення полів за бізнес-правилами документа."
    lines = [signature, "", f"    {hint}"]
    for name in names:
        lines.append(f"    {movements}.{name}.{write} = {true};")
    lines.extend(["", ending])
    return "\n".join(lines)
