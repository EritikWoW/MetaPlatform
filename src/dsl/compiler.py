"""MetaScript Compiler — AST -> Bytecode.

This module is the canonical compiler implementation for MetaScript.
Runtime-specific layers import from here through compatibility shims.

Bytecode format:
  Each instruction is a tuple: (Opcode, *operands)
  Operands depend on the opcode.

Instruction set (stack-based):
  LOAD_CONST  value          - push constant onto stack
  LOAD_NAME   name           - push variable value
  STORE_NAME  name           - pop top, store in variable
  LOAD_ATTR   attr           - pop obj, push obj.attr
  STORE_ATTR  attr           - pop obj, pop value, store obj.attr = value
  LOAD_INDEX                 - pop index, pop obj, push obj[index]
  STORE_INDEX                - pop value, pop index, pop obj, obj[index]=value
  CALL        argc           - pop argc args + callable, push result
  CALL_METHOD attr argc      - pop argc args + obj, call obj.attr(args), push result
  ARG_NAME/ATTR/INDEX        - capture argument value and optional lvalue binding
  NEW         type_name argc - pop argc args, construct type_name(*args), push result
  UNARY_OP    op             - pop operand, push result
  BINARY_OP   op             - pop right, pop left, push result
  JUMP        offset         - unconditional jump
  JUMP_IF_FALSE offset       - pop bool, jump if False
  JUMP_IF_TRUE  offset       - pop bool, jump if True
  POP                        - discard top of stack
  RETURN                     - pop return value, return from function
  RETURN_NONE                - return None
  RAISE                      - pop exception, raise it
  PUSH_BLOCK   kind          - push exception block (try/for/while)
  POP_BLOCK                  - pop exception block
  MAKE_ITER                  - pop iterable, push iterator
  FOR_ITER    offset         - advance iterator; push next value or jump
  STORE_FAST  name           - same as STORE_NAME but for local scope
  LOAD_FAST   name           - same as LOAD_NAME but for local scope
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from src.dsl.ast import (
    Annotation,
    AssignStmt,
    BinaryExpr,
    BreakStmt,
    CallExpr,
    CallStmt,
    ContinueStmt,
    ExecuteStmt,
    Expr,
    FieldExpr,
    ForEachStmt,
    ForStmt,
    FunctionDecl,
    GotoStmt,
    IfStmt,
    IndexExpr,
    LabelStmt,
    Literal,
    NameExpr,
    NewExpr,
    ProcedureDecl,
    Program,
    RaiseStmt,
    ReturnStmt,
    Stmt,
    TryStmt,
    UnaryExpr,
    VarDecl,
    WhileStmt,
)


LOAD_CONST = "LOAD_CONST"
LOAD_NAME = "LOAD_NAME"
STORE_NAME = "STORE_NAME"
LOAD_ATTR = "LOAD_ATTR"
STORE_ATTR = "STORE_ATTR"
LOAD_INDEX = "LOAD_INDEX"
STORE_INDEX = "STORE_INDEX"
CALL = "CALL"
CALL_METHOD = "CALL_METHOD"
ARG_NAME = "ARG_NAME"
ARG_ATTR = "ARG_ATTR"
ARG_INDEX = "ARG_INDEX"
NEW_OBJ = "NEW_OBJ"
NEW_DYNAMIC = "NEW_DYNAMIC"
EXECUTE = "EXECUTE"
UNARY_OP = "UNARY_OP"
BINARY_OP = "BINARY_OP"
JUMP = "JUMP"
JUMP_IF_FALSE = "JUMP_IF_FALSE"
JUMP_IF_TRUE = "JUMP_IF_TRUE"
POP = "POP"
RETURN = "RETURN"
RETURN_NONE = "RETURN_NONE"
RAISE = "RAISE"
MAKE_ITER = "MAKE_ITER"
FOR_ITER = "FOR_ITER"
PUSH_BLOCK = "PUSH_BLOCK"
POP_BLOCK = "POP_BLOCK"
LOAD_FAST = "LOAD_FAST"
STORE_FAST = "STORE_FAST"
NOP = "NOP"


@dataclass
class Instruction:
    op: str
    arg: Any = None
    arg2: Any = None
    lineno: int = 0

    def __repr__(self) -> str:
        parts = [self.op]
        if self.arg is not None:
            parts.append(repr(self.arg))
        if self.arg2 is not None:
            parts.append(repr(self.arg2))
        return f"  {' '.join(parts)}"


@dataclass
class CodeObject:
    """Compiled function/procedure body."""

    name: str
    params: List[str]
    by_value: List[bool]
    defaults: List[Any]
    instructions: List[Instruction]
    locals_: List[str]
    exported: bool = False
    is_function: bool = True
    annotations: Tuple[Annotation, ...] = ()


@dataclass
class ModuleCode:
    """Compiled module (top-level code + procedures + functions)."""

    name: str
    procedures: Dict[str, CodeObject]
    functions: Dict[str, CodeObject]
    module_vars: List[str]
    module_var_annotations: Dict[str, Tuple[Annotation, ...]] = field(default_factory=dict)
    initializer: CodeObject | None = None


class _Loop:
    """Context for break/continue fixup."""

    def __init__(self, try_depth: int = 0) -> None:
        self.break_patches: List[int] = []
        self.continue_patches: List[int] = []
        self.try_depth = try_depth


class Compiler:
    """Compiles AST to CodeObject."""

    def __init__(self, func_name: str = "<module>") -> None:
        self._name = func_name
        self._instructions: List[Instruction] = []
        self._locals: List[str] = []
        self._loop_stack: List[_Loop] = []
        self._try_depth = 0
        self._label_defs: Dict[str, int] = {}
        self._label_patches: List[Tuple[int, str]] = []

    def _emit(self, op: str, arg: Any = None, arg2: Any = None, lineno: int = 0) -> int:
        idx = len(self._instructions)
        self._instructions.append(Instruction(op=op, arg=arg, arg2=arg2, lineno=lineno))
        return idx

    def _patch(self, idx: int, new_arg: Any) -> None:
        self._instructions[idx].arg = new_arg

    def _current_addr(self) -> int:
        return len(self._instructions)

    def _declare_local(self, name: str) -> None:
        if name not in self._locals:
            self._locals.append(name)

    def compile_body(self, stmts: Tuple[Stmt, ...]) -> None:
        for stmt in stmts:
            self._compile_stmt(stmt)

    def _compile_stmt(self, stmt: Stmt) -> None:
        ln = stmt.span.line if hasattr(stmt, "span") else 0

        if isinstance(stmt, VarDecl):
            for name in stmt.names:
                self._declare_local(name)
                self._emit(LOAD_CONST, None, lineno=ln)
                self._emit(STORE_FAST, name, lineno=ln)

        elif isinstance(stmt, AssignStmt):
            self._compile_expr(stmt.value, ln)
            self._compile_store(stmt.target, ln)

        elif isinstance(stmt, CallStmt):
            self._compile_expr(stmt.call, ln)
            self._emit(POP, lineno=ln)

        elif isinstance(stmt, ExecuteStmt):
            self._compile_expr(stmt.source, ln)
            self._emit(EXECUTE, lineno=ln)

        elif isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                self._compile_expr(stmt.value, ln)
            else:
                self._emit(LOAD_CONST, None, lineno=ln)
            self._emit(RETURN, lineno=ln)

        elif isinstance(stmt, BreakStmt):
            if self._loop_stack:
                for _ in range(self._try_depth - self._loop_stack[-1].try_depth):
                    self._emit(POP_BLOCK, lineno=ln)
                idx = self._emit(JUMP, None, lineno=ln)
                self._loop_stack[-1].break_patches.append(idx)

        elif isinstance(stmt, ContinueStmt):
            if self._loop_stack:
                for _ in range(self._try_depth - self._loop_stack[-1].try_depth):
                    self._emit(POP_BLOCK, lineno=ln)
                idx = self._emit(JUMP, None, lineno=ln)
                self._loop_stack[-1].continue_patches.append(idx)

        elif isinstance(stmt, IfStmt):
            self._compile_if(stmt, ln)

        elif isinstance(stmt, ForStmt):
            self._compile_for(stmt, ln)

        elif isinstance(stmt, ForEachStmt):
            self._compile_foreach(stmt, ln)

        elif isinstance(stmt, WhileStmt):
            self._compile_while(stmt, ln)

        elif isinstance(stmt, TryStmt):
            self._compile_try(stmt, ln)

        elif isinstance(stmt, RaiseStmt):
            if stmt.value is not None:
                self._compile_expr(stmt.value, ln)
            else:
                self._emit(LOAD_CONST, None, lineno=ln)
            self._emit(RAISE, lineno=ln)

        elif isinstance(stmt, LabelStmt):
            self._label_defs[stmt.name] = self._current_addr()

        elif isinstance(stmt, GotoStmt):
            idx = self._emit(JUMP, None, lineno=ln)
            self._label_patches.append((idx, stmt.label))

        else:
            self._emit(NOP, lineno=ln)

    def _compile_if(self, stmt: IfStmt, ln: int) -> None:
        self._compile_expr(stmt.condition, ln)
        jump_false = self._emit(JUMP_IF_FALSE, None, lineno=ln)
        self.compile_body(stmt.then_block)
        end_patches = []
        if stmt.elseif_clauses or stmt.else_block is not None:
            end_patches.append(self._emit(JUMP, None, lineno=ln))

        self._patch(jump_false, self._current_addr())

        for cond, body in stmt.elseif_clauses:
            self._compile_expr(cond, ln)
            jf = self._emit(JUMP_IF_FALSE, None, lineno=ln)
            self.compile_body(body)
            end_patches.append(self._emit(JUMP, None, lineno=ln))
            self._patch(jf, self._current_addr())

        if stmt.else_block is not None:
            self.compile_body(stmt.else_block)

        for ep in end_patches:
            self._patch(ep, self._current_addr())

    def _compile_for(self, stmt: ForStmt, ln: int) -> None:
        self._declare_local(stmt.var)
        self._compile_expr(stmt.start, ln)
        self._emit(STORE_FAST, stmt.var, lineno=ln)

        loop = _Loop(self._try_depth)
        self._loop_stack.append(loop)

        test_addr = self._current_addr()
        self._emit(LOAD_FAST, stmt.var, lineno=ln)
        self._compile_expr(stmt.end, ln)
        self._emit(BINARY_OP, "<=", lineno=ln)
        jmp_out = self._emit(JUMP_IF_FALSE, None, lineno=ln)

        self.compile_body(stmt.body)

        increment_addr = self._current_addr()
        self._emit(LOAD_FAST, stmt.var, lineno=ln)
        self._emit(LOAD_CONST, 1, lineno=ln)
        self._emit(BINARY_OP, "+", lineno=ln)
        self._emit(STORE_FAST, stmt.var, lineno=ln)
        self._emit(JUMP, test_addr, lineno=ln)

        end_addr = self._current_addr()
        self._patch(jmp_out, end_addr)
        for idx in loop.break_patches:
            self._patch(idx, end_addr)
        for idx in loop.continue_patches:
            self._patch(idx, increment_addr)
        self._loop_stack.pop()

    def _compile_foreach(self, stmt: ForEachStmt, ln: int) -> None:
        self._declare_local(stmt.var)
        self._compile_expr(stmt.collection, ln)
        self._emit(MAKE_ITER, lineno=ln)

        loop = _Loop(self._try_depth)
        self._loop_stack.append(loop)

        iter_addr = self._current_addr()
        for_iter_idx = self._emit(FOR_ITER, None, lineno=ln)
        self._emit(STORE_FAST, stmt.var, lineno=ln)
        self.compile_body(stmt.body)
        self._emit(JUMP, iter_addr, lineno=ln)

        break_addr = self._current_addr()
        self._emit(POP, lineno=ln)
        end_addr = self._current_addr()
        self._patch(for_iter_idx, end_addr)
        for idx in loop.break_patches:
            self._patch(idx, break_addr)
        for idx in loop.continue_patches:
            self._patch(idx, iter_addr)
        self._loop_stack.pop()

    def _compile_while(self, stmt: WhileStmt, ln: int) -> None:
        loop = _Loop(self._try_depth)
        self._loop_stack.append(loop)

        test_addr = self._current_addr()
        self._compile_expr(stmt.condition, ln)
        jmp_out = self._emit(JUMP_IF_FALSE, None, lineno=ln)
        self.compile_body(stmt.body)
        self._emit(JUMP, test_addr, lineno=ln)

        end_addr = self._current_addr()
        self._patch(jmp_out, end_addr)
        for idx in loop.break_patches:
            self._patch(idx, end_addr)
        for idx in loop.continue_patches:
            self._patch(idx, test_addr)
        self._loop_stack.pop()

    def _compile_try(self, stmt: TryStmt, ln: int) -> None:
        block = self._emit(PUSH_BLOCK, None, lineno=ln)
        self._try_depth += 1
        self.compile_body(stmt.try_block)
        self._try_depth -= 1
        self._emit(POP_BLOCK, lineno=ln)
        jmp_end = self._emit(JUMP, None, lineno=ln)
        exc_addr = self._current_addr()
        self._emit(POP, lineno=ln)
        self.compile_body(stmt.except_block)
        end_addr = self._current_addr()
        self._patch(jmp_end, end_addr)
        self._patch(block, exc_addr)

    def _compile_expr(self, expr: Expr, ln: int) -> None:
        if isinstance(expr, Literal):
            self._emit(LOAD_CONST, expr.value, lineno=ln)
        elif isinstance(expr, NameExpr):
            if expr.name in self._locals:
                self._emit(LOAD_FAST, expr.name, lineno=ln)
            else:
                self._emit(LOAD_NAME, expr.name, lineno=ln)
        elif isinstance(expr, UnaryExpr):
            self._compile_expr(expr.operand, ln)
            self._emit(UNARY_OP, expr.op, lineno=ln)
        elif isinstance(expr, BinaryExpr):
            if expr.op in {"And", "and", "Та", "та"}:
                self._compile_logical_and(expr, ln)
                return
            if expr.op in {"Or", "or", "Або", "або"}:
                self._compile_logical_or(expr, ln)
                return
            self._compile_expr(expr.left, ln)
            self._compile_expr(expr.right, ln)
            self._emit(BINARY_OP, expr.op, lineno=ln)
        elif isinstance(expr, CallExpr):
            self._compile_call(expr, ln)
        elif isinstance(expr, FieldExpr):
            self._compile_expr(expr.obj, ln)
            self._emit(LOAD_ATTR, expr.field, lineno=ln)
        elif isinstance(expr, IndexExpr):
            self._compile_expr(expr.obj, ln)
            self._compile_expr(expr.index, ln)
            self._emit(LOAD_INDEX, lineno=ln)
        elif isinstance(expr, NewExpr):
            if expr.type_expr is not None:
                self._compile_expr(expr.type_expr, ln)
                for arg in expr.args:
                    self._compile_expr(arg, ln)
                self._emit(NEW_DYNAMIC, len(expr.args), lineno=ln)
                return
            for arg in expr.args:
                self._compile_expr(arg, ln)
            self._emit(NEW_OBJ, expr.type_name, len(expr.args), lineno=ln)
        else:
            self._emit(LOAD_CONST, None, lineno=ln)

    def _compile_logical_and(self, expr: BinaryExpr, ln: int) -> None:
        self._compile_expr(expr.left, ln)
        left_false = self._emit(JUMP_IF_FALSE, None, lineno=ln)
        self._compile_expr(expr.right, ln)
        right_false = self._emit(JUMP_IF_FALSE, None, lineno=ln)
        self._emit(LOAD_CONST, True, lineno=ln)
        jump_end = self._emit(JUMP, None, lineno=ln)
        false_addr = self._current_addr()
        self._emit(LOAD_CONST, False, lineno=ln)
        end_addr = self._current_addr()
        self._patch(left_false, false_addr)
        self._patch(right_false, false_addr)
        self._patch(jump_end, end_addr)

    def _compile_logical_or(self, expr: BinaryExpr, ln: int) -> None:
        self._compile_expr(expr.left, ln)
        left_true = self._emit(JUMP_IF_TRUE, None, lineno=ln)
        self._compile_expr(expr.right, ln)
        right_true = self._emit(JUMP_IF_TRUE, None, lineno=ln)
        self._emit(LOAD_CONST, False, lineno=ln)
        jump_end = self._emit(JUMP, None, lineno=ln)
        true_addr = self._current_addr()
        self._emit(LOAD_CONST, True, lineno=ln)
        end_addr = self._current_addr()
        self._patch(left_true, true_addr)
        self._patch(right_true, true_addr)
        self._patch(jump_end, end_addr)

    def _compile_call(self, expr: CallExpr, ln: int) -> None:
        if isinstance(expr.callee, FieldExpr):
            self._compile_expr(expr.callee.obj, ln)
            for arg in expr.args:
                self._compile_argument(arg, ln)
            self._emit(CALL_METHOD, expr.callee.field, len(expr.args), lineno=ln)
        else:
            self._compile_expr(expr.callee, ln)
            for arg in expr.args:
                self._compile_argument(arg, ln)
            self._emit(CALL, len(expr.args), lineno=ln)

    def _compile_argument(self, expr: Expr, ln: int) -> None:
        # Preserve lvalues until the callee's Val/reference contract is known.
        if isinstance(expr, NameExpr):
            self._emit(ARG_NAME, expr.name, lineno=ln)
        elif isinstance(expr, FieldExpr):
            self._compile_expr(expr.obj, ln)
            self._emit(ARG_ATTR, expr.field, lineno=ln)
        elif isinstance(expr, IndexExpr):
            self._compile_expr(expr.obj, ln)
            self._compile_expr(expr.index, ln)
            self._emit(ARG_INDEX, lineno=ln)
        else:
            self._compile_expr(expr, ln)

    def _compile_store(self, target: Expr, ln: int) -> None:
        if isinstance(target, NameExpr):
            if target.name in self._locals:
                self._emit(STORE_FAST, target.name, lineno=ln)
            else:
                self._emit(STORE_NAME, target.name, lineno=ln)
        elif isinstance(target, FieldExpr):
            self._compile_expr(target.obj, ln)
            self._emit(STORE_ATTR, target.field, lineno=ln)
        elif isinstance(target, IndexExpr):
            self._compile_expr(target.obj, ln)
            self._compile_expr(target.index, ln)
            self._emit(STORE_INDEX, lineno=ln)

    def _fixup_labels(self) -> None:
        for idx, label in self._label_patches:
            addr = self._label_defs.get(label)
            if addr is not None:
                self._patch(idx, addr)

    def finish(
        self,
        name: str,
        params: Tuple,
        exported: bool = False,
        is_function: bool = True,
        annotations: Tuple[Annotation, ...] = (),
    ) -> CodeObject:
        self._emit(RETURN_NONE)
        self._fixup_labels()
        return CodeObject(
            name=name,
            params=[p.name for p in params],
            by_value=[p.by_value for p in params],
            defaults=[
                p.default_value.value if isinstance(p.default_value, Literal) else None
                for p in params
            ],
            instructions=self._instructions,
            locals_=list(self._locals),
            exported=exported,
            is_function=is_function,
            annotations=annotations,
        )


def compile_module(prog: Program, module_name: str = "<module>") -> ModuleCode:
    """Compile a parsed Program into a ModuleCode object."""

    procedures: Dict[str, CodeObject] = {}
    functions: Dict[str, CodeObject] = {}
    module_vars: List[str] = [
        name
        for item in prog.items
        if isinstance(item, VarDecl)
        for name in item.names
    ]
    module_var_annotations: Dict[str, Tuple[Annotation, ...]] = {}
    module_body: List[Stmt] = []
    module_var_keys = {name.casefold() for name in module_vars}
    startup_cancel_keys = {"cancel", "отказ", "відмова"}

    for item in prog.items:
        if isinstance(item, ProcedureDecl):
            c = Compiler(item.name)
            for p in item.params:
                c._declare_local(p.name)
            for name in _assigned_names(item.body):
                if name.casefold() not in module_var_keys | startup_cancel_keys:
                    c._declare_local(name)
            c.compile_body(item.body)
            code = c.finish(
                item.name,
                item.params,
                exported=item.exported,
                is_function=False,
                annotations=item.annotations,
            )
            procedures[item.name] = code

        elif isinstance(item, FunctionDecl):
            c = Compiler(item.name)
            for p in item.params:
                c._declare_local(p.name)
            for name in _assigned_names(item.body):
                if name.casefold() not in module_var_keys | startup_cancel_keys:
                    c._declare_local(name)
            c.compile_body(item.body)
            code = c.finish(
                item.name,
                item.params,
                exported=item.exported,
                is_function=True,
                annotations=item.annotations,
            )
            functions[item.name] = code

        elif isinstance(item, VarDecl):
            for name in item.names:
                if item.annotations:
                    module_var_annotations[name] = item.annotations

        elif isinstance(
            item,
            (
                AssignStmt,
                BreakStmt,
                CallStmt,
                ContinueStmt,
                ExecuteStmt,
                ForEachStmt,
                ForStmt,
                GotoStmt,
                IfStmt,
                LabelStmt,
                RaiseStmt,
                ReturnStmt,
                TryStmt,
                WhileStmt,
            ),
        ):
            module_body.append(item)

    initializer = None
    if module_body:
        init_compiler = Compiler("__module_init__")
        init_compiler.compile_body(tuple(module_body))
        initializer = init_compiler.finish(
            "__module_init__",
            (),
            exported=False,
            is_function=False,
        )

    return ModuleCode(
        name=module_name,
        procedures=procedures,
        functions=functions,
        module_vars=module_vars,
        module_var_annotations=module_var_annotations,
        initializer=initializer,
    )


def _assigned_names(stmts: Tuple[Stmt, ...]) -> List[str]:
    """Collect procedure-local assignment targets before bytecode generation."""

    names: List[str] = []

    def add(name: str) -> None:
        if name and name not in names:
            names.append(name)

    def walk(items: Tuple[Stmt, ...]) -> None:
        for stmt in items:
            if isinstance(stmt, VarDecl):
                for name in stmt.names:
                    add(name)
            elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, NameExpr):
                add(stmt.target.name)
            elif isinstance(stmt, (ForStmt, ForEachStmt)):
                add(stmt.var)
                walk(stmt.body)
            elif isinstance(stmt, IfStmt):
                walk(stmt.then_block)
                for _condition, body in stmt.elseif_clauses:
                    walk(body)
                if stmt.else_block is not None:
                    walk(stmt.else_block)
            elif isinstance(stmt, WhileStmt):
                walk(stmt.body)
            elif isinstance(stmt, TryStmt):
                walk(stmt.try_block)
                walk(stmt.except_block)

    walk(stmts)
    return names


__all__ = [
    "ARG_NAME", "ARG_ATTR", "ARG_INDEX",
    "BINARY_OP",
    "CALL",
    "CALL_METHOD",
    "CodeObject",
    "Compiler",
    "EXECUTE",
    "FOR_ITER",
    "Instruction",
    "JUMP",
    "JUMP_IF_FALSE",
    "JUMP_IF_TRUE",
    "LOAD_ATTR",
    "LOAD_CONST",
    "LOAD_FAST",
    "LOAD_INDEX",
    "LOAD_NAME",
    "MAKE_ITER",
    "ModuleCode",
    "NEW_DYNAMIC",
    "NEW_OBJ",
    "NOP",
    "POP",
    "POP_BLOCK",
    "PUSH_BLOCK",
    "RAISE",
    "RETURN",
    "RETURN_NONE",
    "STORE_ATTR",
    "STORE_FAST",
    "STORE_INDEX",
    "STORE_NAME",
    "UNARY_OP",
    "compile_module",
]
