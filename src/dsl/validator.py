"""Semantic validation for MetaScript AST."""

from __future__ import annotations

from .ast import (
    CatalogDecl, DocumentDecl, EnumDecl, FormDecl, FunctionDecl,
    ProcedureDecl, Program, RegisterDecl,
)
from .diagnostics import Diagnostic


_KNOWN_PRIMITIVE_TYPES = {
    "string", "str", "рядок",
    "number", "num", "число",
    "int", "integer", "ціле",
    "float", "дробове",
    "bool", "boolean", "логічне",
    "date", "дата",
    "undefined", "невизначено",
    "null", "нуль",
    "any", "будь-який",
}


def validate(program: Program) -> list[Diagnostic]:
    """Validate program semantics.

    Checks:
      - Entity names are unique.
      - Procedure/Function names are unique.
      - Field names are unique within an entity.
      - Form qualified name references an existing entity.
    """

    diags: list[Diagnostic] = []

    # ---- entities ----
    entity_names: dict[str, object] = {}
    for item in program.items:
        if isinstance(item, (CatalogDecl, DocumentDecl, EnumDecl, RegisterDecl)):
            if item.name in entity_names:
                diags.append(Diagnostic(
                    severity="error",
                    message=f"Duplicate entity name: {item.name}",
                    span=item.span,
                ))
            else:
                entity_names[item.name] = item

            if hasattr(item, "fields"):
                seen: set[str] = set()
                for f in item.fields:
                    if f.name in seen:
                        diags.append(Diagnostic(
                            severity="error",
                            message=f"Duplicate field '{f.name}' in {item.name}",
                            span=f.span,
                        ))
                    seen.add(f.name)
                    if f.type_ref:
                        t = f.type_ref.name.lower()
                        if t and t not in _KNOWN_PRIMITIVE_TYPES:
                            # Custom type — warning only
                            diags.append(Diagnostic(
                                severity="warning",
                                message=(
                                    f"Unknown type '{f.type_ref.name}' "
                                    f"(treated as custom reference)"
                                ),
                                span=f.span,
                            ))

    # ---- forms ----
    for item in program.items:
        if isinstance(item, FormDecl):
            base = item.qualified_name.split(".", 1)[0]
            if base not in entity_names:
                diags.append(Diagnostic(
                    severity="warning",
                    message=f"Form refers to unknown entity '{base}'",
                    span=item.span,
                ))

    # ---- procedure/function uniqueness ----
    proc_names: dict[str, object] = {}
    for item in program.items:
        if isinstance(item, (ProcedureDecl, FunctionDecl)):
            if item.name in proc_names:
                diags.append(Diagnostic(
                    severity="error",
                    message=f"Duplicate function/procedure name: {item.name}",
                    span=item.span,
                ))
            else:
                proc_names[item.name] = item

    return diags
