"""AST nodes for MetaScript — BSL-compatible language.

Language-neutral: UK/EN keywords both produce the same AST.

Node hierarchy:
  Program
    ├── VarDecl            (Змін / Var)
    ├── ProcedureDecl      (Процедура / Procedure)
    ├── FunctionDecl       (Функція / Function)
    └── statements...
        ├── AssignStmt
        ├── CallStmt
        ├── IfStmt
        ├── ForStmt
        ├── ForEachStmt
        ├── WhileStmt
        ├── ReturnStmt
        ├── BreakStmt
        ├── ContinueStmt
        ├── TryStmt
        ├── RaiseStmt
        └── LabelStmt / GotoStmt
  Expressions:
    ├── Literal            (number, string, true, false, undefined, null)
    ├── NameExpr           (identifier)
    ├── IndexExpr          (arr[i])
    ├── FieldExpr          (obj.field)
    ├── CallExpr           (f(args))
    ├── NewExpr            (New Type(...))
    ├── UnaryExpr          (-, Not)
    └── BinaryExpr         (+, -, *, /, %, =, <>, <, >, <=, >=, And, Or, &)
  DSL (metadata description) nodes:
    ├── CatalogDecl
    ├── DocumentDecl
    ├── RegisterDecl
    ├── EnumDecl
    └── FormDecl
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple, Union


# ---------------------------------------------------------------------------
# Source span
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SourceSpan:
    line: int
    col: int
    end_line: int = 0
    end_col: int = 0

    def __str__(self) -> str:
        return f"L{self.line}:C{self.col}"


# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TypeRef:
    """Reference to a type: String, Number, CatalogRef.Clients, etc."""
    name: str
    qualifier: Optional[str] = None  # e.g. "Clients" in CatalogRef.Clients
    span: SourceSpan = field(default_factory=lambda: SourceSpan(0, 0))

    def full_name(self) -> str:
        return f"{self.name}.{self.qualifier}" if self.qualifier else self.name


@dataclass(frozen=True, slots=True)
class Param:
    """Procedure/Function parameter."""
    name: str
    by_value: bool = False          # Знач / Val
    default_value: Optional["Expr"] = None
    type_hint: Optional[TypeRef] = None
    span: SourceSpan = field(default_factory=lambda: SourceSpan(0, 0))


@dataclass(frozen=True, slots=True)
class Annotation:
    """Declaration annotation such as ``&НаКлиенте`` or ``&Before(...)``."""

    name: str
    args: Tuple["Expr", ...] = ()
    span: SourceSpan = field(default_factory=lambda: SourceSpan(0, 0))


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Literal:
    """Number, String, True, False, Undefined, Null literal."""
    value: Any   # int | float | str | bool | None
    raw: str     # original text
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class NameExpr:
    """Simple identifier reference."""
    name: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class FieldExpr:
    """obj.field access."""
    obj: "Expr"
    field: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class IndexExpr:
    """arr[index] access."""
    obj: "Expr"
    index: "Expr"
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CallExpr:
    """Function/method call: f(a, b)  or  obj.method(a, b)."""
    callee: "Expr"
    args: Tuple["Expr", ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class NewExpr:
    """Static ``New Type(...)`` or dynamic ``New(type_expr, ...)`` construction."""

    type_name: Optional[str]
    args: Tuple["Expr", ...]
    span: SourceSpan
    type_expr: Optional["Expr"] = None


@dataclass(frozen=True, slots=True)
class UnaryExpr:
    """Unary operator: - expr  or  Not expr."""
    op: str      # "-" | "Not" | "Не"
    operand: "Expr"
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class BinaryExpr:
    """Binary operator expression."""
    op: str      # "+" | "-" | "*" | "/" | "%" | "=" | "<>" | "<" | ">" |
                 # "<=" | ">=" | "And" | "Or" | "&"
    left: "Expr"
    right: "Expr"
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class TernaryExpr:
    """Condition ? ThenExpr : ElseExpr  (not in BSL, but useful extension)."""
    condition: "Expr"
    then_expr: "Expr"
    else_expr: "Expr"
    span: SourceSpan


# Expr union
Expr = Union[
    Literal, NameExpr, FieldExpr, IndexExpr,
    CallExpr, NewExpr, UnaryExpr, BinaryExpr, TernaryExpr,
]


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AssignStmt:
    """target = value  (LValue = Expr)."""
    target: Expr   # NameExpr | FieldExpr | IndexExpr
    value: Expr
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CallStmt:
    """Procedure call as statement: DoSomething(x);"""
    call: CallExpr
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ExecuteStmt:
    """Execute MetaScript source text in the current runtime scope."""

    source: Expr
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class VarDecl:
    """Змін x, y, z Експорт;  /  Var x, y Export;"""
    names: Tuple[str, ...]
    exported: bool = False
    span: SourceSpan = field(default_factory=lambda: SourceSpan(0, 0))
    annotations: Tuple[Annotation, ...] = ()


@dataclass(frozen=True, slots=True)
class ReturnStmt:
    value: Optional[Expr]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class BreakStmt:
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ContinueStmt:
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class LabelStmt:
    """~LabelName:"""
    name: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class GotoStmt:
    """Перейти(~LabelName) / Goto(~LabelName)"""
    label: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class RaiseStmt:
    """Викинути ExceptionExpr / Raise ExceptionExpr"""
    value: Optional[Expr]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class IfStmt:
    condition: Expr
    then_block: Tuple["Stmt", ...]
    elseif_clauses: Tuple[Tuple[Expr, Tuple["Stmt", ...]], ...]  # (cond, stmts)*
    else_block: Optional[Tuple["Stmt", ...]]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ForStmt:
    """Для var = start До end Виконати ... КінецьЦиклу"""
    var: str
    start: Expr
    end: Expr
    body: Tuple["Stmt", ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ForEachStmt:
    """Для кожного var З collection Виконати ... КінецьЦиклу"""
    var: str
    collection: Expr
    body: Tuple["Stmt", ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class WhileStmt:
    """Поки condition Виконати ... КінецьЦиклу"""
    condition: Expr
    body: Tuple["Stmt", ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class TryStmt:
    """Спроба ... Виняток ... КінецьСпроби"""
    try_block: Tuple["Stmt", ...]
    except_block: Tuple["Stmt", ...]
    span: SourceSpan


# Stmt union
Stmt = Union[
    AssignStmt, CallStmt, ExecuteStmt, VarDecl, ReturnStmt, BreakStmt, ContinueStmt,
    IfStmt, ForStmt, ForEachStmt, WhileStmt, TryStmt,
    RaiseStmt, LabelStmt, GotoStmt,
]


# ---------------------------------------------------------------------------
# Procedure / Function declarations
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ProcedureDecl:
    """Процедура Name(params) Експорт? ... КінецьПроцедури"""
    name: str
    params: Tuple[Param, ...]
    body: Tuple[Stmt, ...]
    exported: bool = False
    span: SourceSpan = field(default_factory=lambda: SourceSpan(0, 0))
    annotations: Tuple[Annotation, ...] = ()


@dataclass(frozen=True, slots=True)
class FunctionDecl:
    """Функція Name(params) Експорт? ... КінецьФункції"""
    name: str
    params: Tuple[Param, ...]
    body: Tuple[Stmt, ...]
    exported: bool = False
    span: SourceSpan = field(default_factory=lambda: SourceSpan(0, 0))
    annotations: Tuple[Annotation, ...] = ()


# ---------------------------------------------------------------------------
# DSL / Metadata description nodes
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FieldDecl:
    """Single field declaration inside a metadata object."""
    name: str
    type_ref: Optional[TypeRef]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class TablePartDecl:
    """Tabular part declaration."""
    name: str
    fields: Tuple[FieldDecl, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CatalogDecl:
    """Довідник Name { реквізити: ... }"""
    name: str
    fields: Tuple[FieldDecl, ...]
    tabular_parts: Tuple[TablePartDecl, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class DocumentDecl:
    """Документ Name { реквізити: ... }"""
    name: str
    fields: Tuple[FieldDecl, ...]
    tabular_parts: Tuple[TablePartDecl, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class EnumValueDecl:
    name: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class EnumDecl:
    """Перерахування Name { value1, value2, ... }"""
    name: str
    values: Tuple[EnumValueDecl, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class RegisterDecl:
    """Регістр Name { виміри: ... ресурси: ... }"""
    name: str
    dimensions: Tuple[FieldDecl, ...]
    resources: Tuple[FieldDecl, ...]
    attributes: Tuple[FieldDecl, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class FormDecl:
    """Форма QualifiedName { ... }"""
    qualified_name: str    # e.g. "Catalog.Clients.ListForm"
    table_columns: Tuple[str, ...]
    span: SourceSpan


# Top-level item
TopLevelItem = Union[
    VarDecl, ProcedureDecl, FunctionDecl,
    CatalogDecl, DocumentDecl, EnumDecl, RegisterDecl, FormDecl,
    Stmt,
]


# ---------------------------------------------------------------------------
# Program root
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Program:
    """Root AST node."""
    items: Tuple[TopLevelItem, ...]
    span: SourceSpan = field(default_factory=lambda: SourceSpan(0, 0))

    def procedures(self) -> Sequence[ProcedureDecl]:
        return [x for x in self.items if isinstance(x, ProcedureDecl)]

    def functions(self) -> Sequence[FunctionDecl]:
        return [x for x in self.items if isinstance(x, FunctionDecl)]

    def var_decls(self) -> Sequence[VarDecl]:
        return [x for x in self.items if isinstance(x, VarDecl)]

    def catalogs(self) -> Sequence[CatalogDecl]:
        return [x for x in self.items if isinstance(x, CatalogDecl)]

    def documents(self) -> Sequence[DocumentDecl]:
        return [x for x in self.items if isinstance(x, DocumentDecl)]

    def entities(self) -> Sequence[Union[CatalogDecl, DocumentDecl]]:
        return [x for x in self.items if isinstance(x, (CatalogDecl, DocumentDecl))]
