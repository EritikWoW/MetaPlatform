from __future__ import annotations

"""Module-level introspection for MetaScript/1C-compatible source.

This module is intentionally independent from Qt. It is the IDE-facing layer
over lexer/parser/compiler: editors, debugger and future language services can
ask one place for variables, procedures, functions and known runtime names.
"""

from dataclasses import dataclass, field
from typing import Any

from src.dsl.ast import (
    AssignStmt,
    ForEachStmt,
    ForStmt,
    FunctionDecl,
    IfStmt,
    NameExpr,
    ProcedureDecl,
    TryStmt,
    VarDecl,
    WhileStmt,
)
from src.dsl.compiler import compile_module
from src.dsl.diagnostics import Diagnostic
from src.dsl.languages import DslLanguage, get_profile
from src.dsl.parser import parse
from src.dsl.platform_symbols import standard_runtime_names


@dataclass(frozen=True, slots=True)
class ModuleSymbol:
    name: str
    kind: str
    line: int = 0
    exported: bool = False
    params: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProcedureScope:
    name: str
    kind: str
    line_start: int = 0
    line_end: int = 0
    params: tuple[str, ...] = ()
    locals: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()

    def contains_line(self, line: int) -> bool:
        line_i = int(line or 0)
        if line_i <= 0 or self.line_start <= 0:
            return False
        end = self.line_end if self.line_end >= self.line_start else self.line_start
        return self.line_start <= line_i <= end


@dataclass(frozen=True, slots=True)
class ModuleIntrospection:
    language: str
    symbols: tuple[ModuleSymbol, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    module_vars: tuple[str, ...] = ()
    procedures: tuple[str, ...] = ()
    functions: tuple[str, ...] = ()
    runtime_names: tuple[str, ...] = ()
    scopes: tuple[ProcedureScope, ...] = ()
    symbol_by_name: dict[str, ModuleSymbol] = field(default_factory=dict)


_STANDARD_RUNTIME_NAMES: tuple[str, ...] = standard_runtime_names()


def repair_cp1251_mojibake_name(name: str) -> str:
    text = str(name or "")
    if not text:
        return ""
    try:
        repaired = text.encode("latin1").decode("cp1251")
    except Exception:
        return ""
    return repaired if repaired and repaired != text else ""


def symbol_aliases(name: str) -> tuple[str, ...]:
    aliases: list[str] = []
    repaired = repair_cp1251_mojibake_name(name)
    if repaired:
        aliases.append(repaired)
    return tuple(dict.fromkeys(aliases))


def _span_line(item: Any) -> int:
    try:
        return int(getattr(getattr(item, "span", None), "line", 0) or 0)
    except Exception:
        return 0


def _stmt_line(item: Any) -> int:
    return _span_line(item)


def _add_name(target: list[str], name: str) -> None:
    name_s = str(name or "").strip()
    if name_s and name_s not in target:
        target.append(name_s)


def _param_names(item: Any) -> tuple[str, ...]:
    try:
        return tuple(str(getattr(param, "name", "") or "") for param in getattr(item, "params", ()) or ())
    except Exception:
        return ()


def _walk_statement_lines(stmts: tuple[Any, ...] | list[Any]) -> int:
    max_line = 0
    for stmt in stmts or ():
        max_line = max(max_line, _stmt_line(stmt))
        if isinstance(stmt, IfStmt):
            max_line = max(max_line, _walk_statement_lines(stmt.then_block))
            for _, block in stmt.elseif_clauses or ():
                max_line = max(max_line, _walk_statement_lines(block))
            if stmt.else_block:
                max_line = max(max_line, _walk_statement_lines(stmt.else_block))
        elif isinstance(stmt, (ForStmt, ForEachStmt, WhileStmt)):
            max_line = max(max_line, _walk_statement_lines(stmt.body))
        elif isinstance(stmt, TryStmt):
            max_line = max(max_line, _walk_statement_lines(stmt.try_block))
            max_line = max(max_line, _walk_statement_lines(stmt.except_block))
    return max_line


def _collect_local_names(
    stmts: tuple[Any, ...] | list[Any],
    *,
    module_vars: set[str],
    out: list[str],
) -> None:
    for stmt in stmts or ():
        if isinstance(stmt, VarDecl):
            for name in stmt.names:
                _add_name(out, name)
        elif isinstance(stmt, AssignStmt):
            target = stmt.target
            if isinstance(target, NameExpr):
                name = str(target.name or "")
                if name and name not in module_vars:
                    _add_name(out, name)
        elif isinstance(stmt, ForStmt):
            _add_name(out, stmt.var)
            _collect_local_names(stmt.body, module_vars=module_vars, out=out)
        elif isinstance(stmt, ForEachStmt):
            _add_name(out, stmt.var)
            _collect_local_names(stmt.body, module_vars=module_vars, out=out)
        elif isinstance(stmt, WhileStmt):
            _collect_local_names(stmt.body, module_vars=module_vars, out=out)
        elif isinstance(stmt, IfStmt):
            _collect_local_names(stmt.then_block, module_vars=module_vars, out=out)
            for _, block in stmt.elseif_clauses or ():
                _collect_local_names(block, module_vars=module_vars, out=out)
            if stmt.else_block:
                _collect_local_names(stmt.else_block, module_vars=module_vars, out=out)
        elif isinstance(stmt, TryStmt):
            _collect_local_names(stmt.try_block, module_vars=module_vars, out=out)
            _collect_local_names(stmt.except_block, module_vars=module_vars, out=out)


def _build_scope(
    item: ProcedureDecl | FunctionDecl,
    *,
    kind: str,
    module_vars: set[str],
    compiled_locals: tuple[str, ...] = (),
) -> ProcedureScope:
    params = _param_names(item)
    locals_: list[str] = []
    for name in params:
        _add_name(locals_, name)
    _collect_local_names(item.body, module_vars=module_vars, out=locals_)
    for name in compiled_locals:
        _add_name(locals_, name)
    line_start = _span_line(item)
    line_end = max(line_start, _walk_statement_lines(item.body))
    return ProcedureScope(
        name=str(item.name or ""),
        kind=kind,
        line_start=line_start,
        line_end=line_end,
        params=params,
        locals=tuple(locals_),
        aliases=symbol_aliases(str(item.name or "")),
    )


def _build_symbol_index(symbols: list[ModuleSymbol]) -> dict[str, ModuleSymbol]:
    out: dict[str, ModuleSymbol] = {}
    for symbol in symbols:
        out.setdefault(symbol.name, symbol)
        out.setdefault(symbol.name.casefold(), symbol)
        for alias in symbol.aliases:
            out.setdefault(alias, symbol)
            out.setdefault(alias.casefold(), symbol)
    return out


def introspect_module_source(source: str, *, language: DslLanguage = "mixed") -> ModuleIntrospection:
    lang = str(language or "mixed").strip().lower()
    if lang not in {"uk", "en", "mixed"}:
        lang = "mixed"
    profile = get_profile(lang)  # type: ignore[arg-type]
    program, diagnostics = parse(str(source or ""), profile)
    symbols: list[ModuleSymbol] = []
    module_vars: list[str] = []
    procedures: list[str] = []
    functions: list[str] = []
    scopes: list[ProcedureScope] = []
    if program is not None:
        for item in getattr(program, "items", ()) or ():
            if isinstance(item, VarDecl):
                for name in item.names:
                    _add_name(module_vars, name)
        module_var_set = set(module_vars)
        compiled_procedure_locals: dict[str, tuple[str, ...]] = {}
        compiled_function_locals: dict[str, tuple[str, ...]] = {}
        try:
            compiled = compile_module(program, module_name="<introspection>")
            module_vars = list(dict.fromkeys([*module_vars, *compiled.module_vars]))
            module_var_set = set(module_vars)
            compiled_procedure_locals = {
                name: tuple(code.locals_) for name, code in compiled.procedures.items()
            }
            compiled_function_locals = {
                name: tuple(code.locals_) for name, code in compiled.functions.items()
            }
            procedures = list(dict.fromkeys([*procedures, *compiled.procedures.keys()]))
            functions = list(dict.fromkeys([*functions, *compiled.functions.keys()]))
        except Exception:
            pass
        for item in getattr(program, "items", ()) or ():
            if isinstance(item, VarDecl):
                for name in item.names:
                    name_s = str(name or "")
                    symbols.append(
                        ModuleSymbol(
                            name=name_s,
                            kind="variable",
                            line=_span_line(item),
                            exported=bool(item.exported),
                            aliases=symbol_aliases(name_s),
                        )
                    )
            elif isinstance(item, ProcedureDecl):
                name_s = str(item.name or "")
                _add_name(procedures, name_s)
                scopes.append(
                    _build_scope(
                        item,
                        kind="procedure",
                        module_vars=module_var_set,
                        compiled_locals=compiled_procedure_locals.get(name_s, ()),
                    )
                )
                symbols.append(
                    ModuleSymbol(
                        name=name_s,
                        kind="procedure",
                        line=_span_line(item),
                        exported=bool(item.exported),
                        params=_param_names(item),
                        aliases=symbol_aliases(name_s),
                    )
                )
            elif isinstance(item, FunctionDecl):
                name_s = str(item.name or "")
                _add_name(functions, name_s)
                scopes.append(
                    _build_scope(
                        item,
                        kind="function",
                        module_vars=module_var_set,
                        compiled_locals=compiled_function_locals.get(name_s, ()),
                    )
                )
                symbols.append(
                    ModuleSymbol(
                        name=name_s,
                        kind="function",
                        line=_span_line(item),
                        exported=bool(item.exported),
                        params=_param_names(item),
                        aliases=symbol_aliases(name_s),
                    )
                )
    runtime_names = tuple(_STANDARD_RUNTIME_NAMES)
    for name in runtime_names:
        symbols.append(ModuleSymbol(name=name, kind="runtime", aliases=symbol_aliases(name)))
    return ModuleIntrospection(
        language=lang,
        symbols=tuple(symbols),
        diagnostics=tuple(diagnostics or ()),
        module_vars=tuple(dict.fromkeys(module_vars)),
        procedures=tuple(dict.fromkeys(procedures)),
        functions=tuple(dict.fromkeys(functions)),
        runtime_names=runtime_names,
        scopes=tuple(scopes),
        symbol_by_name=_build_symbol_index(symbols),
    )
