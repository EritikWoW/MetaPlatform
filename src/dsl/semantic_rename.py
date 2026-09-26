from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from src.dsl.languages import DslLanguage, get_profile
from src.dsl.lexer import lex
from src.dsl.module_introspection import ModuleIntrospection, ProcedureScope, introspect_module_source
from src.dsl.tokens import Token


class SemanticRenameError(ValueError):
    def __init__(self, message: str, *, code: str = "", **details: str) -> None:
        super().__init__(message)
        self.code = str(code or "")
        self.details = {str(key): str(value) for key, value in details.items()}


@dataclass(frozen=True, slots=True)
class RenameOccurrence:
    start: int
    end: int
    line: int
    col: int
    preview: str
    declaration: bool = False


@dataclass(frozen=True, slots=True)
class SemanticRenamePlan:
    old_name: str
    new_name: str
    symbol_kind: str
    scope_name: str
    occurrences: tuple[RenameOccurrence, ...]
    source: str
    updated_source: str


@dataclass(frozen=True, slots=True)
class WorkspaceRenameModulePlan:
    module_guid: str
    module_name: str
    source_hash: str
    updated_hash: str
    occurrences: tuple[RenameOccurrence, ...]
    source: str
    updated_source: str


@dataclass(frozen=True, slots=True)
class WorkspaceRenamePlan:
    declaration_module_guid: str
    old_name: str
    new_name: str
    symbol_kind: str
    qualifier_names: tuple[str, ...]
    modules: tuple[WorkspaceRenameModulePlan, ...]

    @property
    def occurrence_count(self) -> int:
        return sum(len(module.occurrences) for module in self.modules)


@dataclass(frozen=True, slots=True)
class _LocatedToken:
    token: Token
    start: int
    end: int


def plan_semantic_rename(
    source: str,
    cursor_position: int,
    new_name: str,
    *,
    language: DslLanguage = "mixed",
    introspection: ModuleIntrospection | None = None,
) -> SemanticRenamePlan:
    text = str(source or "")
    new_name = str(new_name or "").strip()
    profile = get_profile(language)
    _validate_identifier(new_name, profile)

    tokens = _located_tokens(text, profile)
    selected = _token_at(tokens, cursor_position)
    if selected is None or not _is_identifier_token(selected.token):
        raise SemanticRenameError(
            "Caret is not positioned on an identifier",
            code="caret",
        )

    old_name = str(selected.token.text or "")
    if old_name.casefold() == new_name.casefold():
        raise SemanticRenameError(
            "New name is identical to the current name",
            code="identical",
        )

    info = introspection or introspect_module_source(text, language=language)
    symbol_kind, scope = _resolve_symbol(info, old_name, selected.token.span.line)
    if not symbol_kind:
        raise SemanticRenameError(
            f"Symbol is not declared in this module: {old_name}",
            code="undeclared",
            name=old_name,
        )
    _validate_collision(info, old_name, new_name, symbol_kind, scope)

    occurrences = _collect_occurrences(
        text,
        tokens,
        old_name=old_name,
        symbol_kind=symbol_kind,
        scope=scope,
        info=info,
    )
    if not occurrences:
        raise SemanticRenameError(
            f"No semantic occurrences found for: {old_name}",
            code="no_occurrences",
            name=old_name,
        )

    updated = text
    for occurrence in reversed(occurrences):
        updated = updated[: occurrence.start] + new_name + updated[occurrence.end :]
    return SemanticRenamePlan(
        old_name=old_name,
        new_name=new_name,
        symbol_kind=symbol_kind,
        scope_name=str(scope.name if scope is not None else ""),
        occurrences=tuple(occurrences),
        source=text,
        updated_source=updated,
    )


def symbol_name_at(
    source: str,
    cursor_position: int,
    *,
    language: DslLanguage = "mixed",
) -> str:
    profile = get_profile(language)
    selected = _token_at(_located_tokens(str(source or ""), profile), cursor_position)
    if selected is None or not _is_identifier_token(selected.token):
        return ""
    return str(selected.token.text or "")


def plan_workspace_export_rename(
    module_sources: list[dict[str, Any]],
    *,
    declaration_module_guid: str,
    cursor_position: int,
    new_name: str,
    qualifier_names: tuple[str, ...] | list[str],
    language: DslLanguage = "mixed",
) -> WorkspaceRenamePlan:
    declaration_guid = str(declaration_module_guid or "").strip()
    if not declaration_guid:
        raise SemanticRenameError(
            "Declaration module GUID is required",
            code="module_required",
        )
    target_row = next(
        (
            row
            for row in module_sources
            if str(row.get("module_guid") or "").strip() == declaration_guid
        ),
        None,
    )
    if not isinstance(target_row, dict):
        raise SemanticRenameError(
            f"Declaration module was not found: {declaration_guid}",
            code="module_not_found",
            name=declaration_guid,
        )
    target_source = str(target_row.get("source_text") or "")
    local_plan = plan_semantic_rename(
        target_source,
        cursor_position,
        new_name,
        language=language,
    )
    if local_plan.symbol_kind not in {"procedure", "function"}:
        raise SemanticRenameError(
            "Workspace rename is available only for exported procedures and functions",
            code="not_exported_method",
        )
    target_info = introspect_module_source(target_source, language=language)
    symbol = (
        target_info.symbol_by_name.get(local_plan.old_name)
        or target_info.symbol_by_name.get(local_plan.old_name.casefold())
    )
    if symbol is None or not bool(getattr(symbol, "exported", False)):
        raise SemanticRenameError(
            "Workspace rename is available only for exported procedures and functions",
            code="not_exported_method",
        )

    qualifiers = tuple(
        dict.fromkeys(
            str(name or "").strip()
            for name in qualifier_names
            if str(name or "").strip()
        )
    )
    if not qualifiers:
        raise SemanticRenameError(
            "Module qualifier is required for workspace rename",
            code="qualifier_required",
        )

    modules: list[WorkspaceRenameModulePlan] = [
        _workspace_module_plan(
            target_row,
            source=target_source,
            updated_source=local_plan.updated_source,
            occurrences=local_plan.occurrences,
        )
    ]
    for row in module_sources:
        module_guid = str(row.get("module_guid") or "").strip()
        if not module_guid or module_guid == declaration_guid:
            continue
        source = str(row.get("source_text") or "")
        occurrences = _qualified_method_occurrences(
            source,
            qualifier_names=qualifiers,
            method_name=local_plan.old_name,
            language=language,
        )
        if not occurrences:
            continue
        updated = source
        for occurrence in reversed(occurrences):
            updated = (
                updated[: occurrence.start]
                + local_plan.new_name
                + updated[occurrence.end :]
            )
        modules.append(
            _workspace_module_plan(
                row,
                source=source,
                updated_source=updated,
                occurrences=tuple(occurrences),
            )
        )
    return WorkspaceRenamePlan(
        declaration_module_guid=declaration_guid,
        old_name=local_plan.old_name,
        new_name=local_plan.new_name,
        symbol_kind=local_plan.symbol_kind,
        qualifier_names=qualifiers,
        modules=tuple(modules),
    )


def _validate_identifier(name: str, profile) -> None:
    if not name:
        raise SemanticRenameError("New name is required", code="required")
    tokens = lex(name, profile)
    meaningful = [token for token in tokens if token.type != "EOF"]
    if len(meaningful) != 1 or meaningful[0].type != "IDENT" or meaningful[0].text != name:
        raise SemanticRenameError(
            f"Invalid identifier: {name}",
            code="invalid",
            name=name,
        )


def _line_starts(source: str) -> list[int]:
    starts = [0]
    starts.extend(index + 1 for index, char in enumerate(source) if char == "\n")
    return starts


def _located_tokens(source: str, profile) -> list[_LocatedToken]:
    starts = _line_starts(source)
    out: list[_LocatedToken] = []
    for token in lex(source, profile):
        if token.type == "EOF":
            continue
        line_index = max(0, int(token.span.line or 1) - 1)
        if line_index >= len(starts):
            continue
        start = starts[line_index] + max(0, int(token.span.col or 1) - 1)
        end = start + len(str(token.text or ""))
        out.append(_LocatedToken(token=token, start=start, end=end))
    return out


def _token_at(tokens: list[_LocatedToken], cursor_position: int) -> _LocatedToken | None:
    position = max(0, int(cursor_position or 0))
    probes = (position, max(0, position - 1))
    for probe in probes:
        for item in tokens:
            if item.start <= probe < item.end:
                return item
    return None


def _resolve_symbol(
    info: ModuleIntrospection,
    old_name: str,
    line: int,
) -> tuple[str, ProcedureScope | None]:
    folded = old_name.casefold()
    current_scope = next(
        (scope for scope in info.scopes if scope.contains_line(line)),
        None,
    )
    if current_scope is not None:
        if folded in {name.casefold() for name in current_scope.params}:
            return "parameter", current_scope
        if folded in {name.casefold() for name in current_scope.locals}:
            return "local", current_scope
    if folded in {name.casefold() for name in info.module_vars}:
        return "module_variable", None
    symbol = info.symbol_by_name.get(old_name) or info.symbol_by_name.get(folded)
    kind = str(getattr(symbol, "kind", "") or "")
    if kind in {"procedure", "function"}:
        return kind, None
    return "", None


def _validate_collision(
    info: ModuleIntrospection,
    old_name: str,
    new_name: str,
    symbol_kind: str,
    scope: ProcedureScope | None,
) -> None:
    old_folded = old_name.casefold()
    new_folded = new_name.casefold()
    if symbol_kind in {"parameter", "local"} and scope is not None:
        names = {*scope.params, *scope.locals}
    else:
        names = {*info.module_vars, *info.procedures, *info.functions}
    conflicts = {
        name
        for name in names
        if name.casefold() == new_folded and name.casefold() != old_folded
    }
    if conflicts:
        conflict = sorted(conflicts, key=str.casefold)[0]
        raise SemanticRenameError(
            f"Name conflicts with an existing symbol: {conflict}",
            code="conflict",
            name=conflict,
        )


def _collect_occurrences(
    source: str,
    tokens: list[_LocatedToken],
    *,
    old_name: str,
    symbol_kind: str,
    scope: ProcedureScope | None,
    info: ModuleIntrospection,
) -> list[RenameOccurrence]:
    folded = old_name.casefold()
    out: list[RenameOccurrence] = []
    for index, item in enumerate(tokens):
        token = item.token
        if not _is_identifier_token(token) or token.text.casefold() != folded:
            continue
        line = int(token.span.line or 0)
        if scope is not None and not scope.contains_line(line):
            continue
        previous = tokens[index - 1].token if index > 0 else None
        if previous is not None and previous.type == "DOT":
            continue
        if symbol_kind in {"module_variable", "procedure", "function"}:
            shadow_scope = next((candidate for candidate in info.scopes if candidate.contains_line(line)), None)
            if shadow_scope is not None:
                shadow_names = {
                    name.casefold()
                    for name in (*shadow_scope.params, *shadow_scope.locals)
                }
                if folded in shadow_names:
                    continue
        declaration = _is_declaration(item, symbol_kind, scope, info)
        out.append(
            RenameOccurrence(
                start=item.start,
                end=item.end,
                line=line,
                col=int(token.span.col or 0),
                preview=_line_preview(source, line),
                declaration=declaration,
            )
        )
    return out


def _is_declaration(
    item: _LocatedToken,
    symbol_kind: str,
    scope: ProcedureScope | None,
    info: ModuleIntrospection,
) -> bool:
    line = int(item.token.span.line or 0)
    if symbol_kind == "parameter" and scope is not None:
        return line == scope.line_start
    if symbol_kind == "local" and scope is not None:
        return line == scope.line_start
    symbol = info.symbol_by_name.get(item.token.text) or info.symbol_by_name.get(item.token.text.casefold())
    return bool(symbol is not None and int(getattr(symbol, "line", 0) or 0) == line)


def _line_preview(source: str, line: int) -> str:
    lines = source.splitlines()
    index = max(0, int(line or 1) - 1)
    return lines[index].strip() if index < len(lines) else ""


def _is_identifier_token(token: Token) -> bool:
    return token.type == "IDENT" or token.is_keyword()


def _qualified_method_occurrences(
    source: str,
    *,
    qualifier_names: tuple[str, ...],
    method_name: str,
    language: DslLanguage,
) -> list[RenameOccurrence]:
    tokens = _located_tokens(source, get_profile(language))
    qualifiers = {name.casefold() for name in qualifier_names}
    method_folded = str(method_name or "").casefold()
    out: list[RenameOccurrence] = []
    for index, item in enumerate(tokens):
        if (
            index < 2
            or not _is_identifier_token(item.token)
            or str(item.token.text or "").casefold() != method_folded
            or tokens[index - 1].token.type != "DOT"
        ):
            continue
        qualifier = tokens[index - 2].token
        if (
            not _is_identifier_token(qualifier)
            or str(qualifier.text or "").casefold() not in qualifiers
        ):
            continue
        if index >= 3 and tokens[index - 3].token.type == "DOT":
            continue
        out.append(
            RenameOccurrence(
                start=item.start,
                end=item.end,
                line=int(item.token.span.line or 0),
                col=int(item.token.span.col or 0),
                preview=_line_preview(source, int(item.token.span.line or 0)),
                declaration=False,
            )
        )
    return out


def _workspace_module_plan(
    row: dict[str, Any],
    *,
    source: str,
    updated_source: str,
    occurrences: tuple[RenameOccurrence, ...],
) -> WorkspaceRenameModulePlan:
    return WorkspaceRenameModulePlan(
        module_guid=str(row.get("module_guid") or "").strip(),
        module_name=str(
            row.get("owner_title")
            or row.get("owner_name")
            or row.get("name")
            or row.get("module_kind")
            or "module"
        ),
        source_hash=_source_hash(source),
        updated_hash=_source_hash(updated_source),
        occurrences=tuple(occurrences),
        source=source,
        updated_source=updated_source,
    )


def _source_hash(source: str) -> str:
    return hashlib.sha256(str(source or "").encode("utf-8")).hexdigest()
