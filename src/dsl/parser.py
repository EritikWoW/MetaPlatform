"""MetaScript Parser — recursive descent.

Grammar (simplified):
  program         ::= top_level_item* EOF
  top_level_item  ::= var_decl | proc_decl | func_decl
                    | catalog_decl | document_decl | enum_decl
                    | register_decl | form_decl
  proc_decl       ::= KW_PROCEDURE IDENT '(' params ')' KW_EXPORT?
                        body KW_ENDPROCEDURE
  func_decl       ::= KW_FUNCTION IDENT '(' params ')' KW_EXPORT?
                        body KW_ENDFUNCTION
  var_decl        ::= KW_VAR ident_list KW_EXPORT? ';'?
  body            ::= stmt*
  stmt            ::= assign_stmt | call_stmt | if_stmt | for_stmt
                    | foreach_stmt | while_stmt | return_stmt
                    | break_stmt | continue_stmt | try_stmt
                    | raise_stmt | execute_stmt | var_decl | label_stmt | goto_stmt
  assign_stmt     ::= lvalue '=' expr ';'?
  call_stmt       ::= expr ';'?   (when expr is CallExpr)
  if_stmt         ::= KW_IF expr KW_THEN body
                        (KW_ELSEIF expr KW_THEN body)*
                        (KW_ELSE body)?
                      KW_ENDIF
  for_stmt        ::= KW_FOR IDENT '=' expr KW_TO expr KW_DO body KW_ENDDO
  foreach_stmt    ::= KW_FOR KW_EACH IDENT KW_IN expr KW_DO body KW_ENDDO
  while_stmt      ::= KW_WHILE expr KW_DO body KW_ENDDO
  return_stmt     ::= KW_RETURN expr? ';'?
  try_stmt        ::= KW_TRY body KW_EXCEPT body KW_ENDTRY
  raise_stmt      ::= KW_RAISE expr? ';'?
  expr            ::= or_expr
  or_expr         ::= and_expr (KW_OR and_expr)*
  and_expr        ::= not_expr (KW_AND not_expr)*
  not_expr        ::= KW_NOT not_expr | cmp_expr
  cmp_expr        ::= add_expr (('='|'<>'|'<'|'>'|'<='|'>=') add_expr)*
  add_expr        ::= mul_expr (('+' | '-' | '&') mul_expr)*
  mul_expr        ::= unary_expr (('*' | '/' | '%') unary_expr)*
  unary_expr      ::= '-' unary_expr | postfix_expr
  postfix_expr    ::= primary_expr ('.' IDENT | '[' expr ']' | '(' args ')')*
  primary_expr    ::= literal | IDENT | '(' expr ')' | KW_NEW IDENT '(' args ')'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .ast import (
    Annotation, AssignStmt, BinaryExpr, BreakStmt, CallExpr, CallStmt,
    CatalogDecl, ContinueStmt, DocumentDecl, EnumDecl, EnumValueDecl,
    ExecuteStmt, FieldDecl, ForEachStmt, ForStmt, FormDecl, FunctionDecl,
    GotoStmt, IfStmt, IndexExpr, LabelStmt, Literal, NameExpr,
    NewExpr, FieldExpr, Param, ProcedureDecl, Program, RaiseStmt,
    RegisterDecl, ReturnStmt, SourceSpan, Stmt, TablePartDecl,
    TopLevelItem, TryStmt, TypeRef, UnaryExpr, VarDecl,
    WhileStmt, Expr,
)
from .diagnostics import Diagnostic, ParseError
from .languages import LanguageProfile, get_source_preprocessor_aliases
from .lexer import lex
from .tokens import Token, TokenType


_PP_COMPAT_ANNOTATIONS = {
    alias.casefold()
    for alias, token_type in get_source_preprocessor_aliases("mixed").items()
    if token_type in {"KW_REGION", "KW_ENDREGION", "KW_USE"}
}


@dataclass
class Parser:
    tokens: List[Token]
    _idx: int = field(default=0, init=False)
    _diags: List[Diagnostic] = field(default_factory=list, init=False)

    # ---- token navigation ----

    def _cur(self) -> Token:
        return self.tokens[self._idx]

    def _peek(self, offset: int = 1) -> Token:
        idx = min(self._idx + offset, len(self.tokens) - 1)
        return self.tokens[idx]

    def _at(self, *types: TokenType) -> bool:
        return self._cur().type in types

    def _eat(self, *types: TokenType) -> Token:
        tok = self._cur()
        if tok.type not in types:
            expected = " or ".join(types)
            raise ParseError(
                f"Expected {expected}, got '{tok.text}' ({tok.type})",
                tok.span,
            )
        self._idx += 1
        return tok

    def _match(self, *types: TokenType) -> Optional[Token]:
        if self._cur().type in types:
            tok = self._cur()
            self._idx += 1
            return tok
        return None

    def _skip_semicolons(self) -> None:
        while self._match("SEMICOLON"):
            pass

    def _skip_source_line(self) -> None:
        """Skip a preprocessor directive without consuming the next source line."""

        line = self._cur().span.line
        while not self._at("EOF") and self._cur().span.line == line:
            self._idx += 1

    def _skip_expression_directives(self) -> None:
        """Skip compile-directive source lines embedded between expression parts."""

        while self._at(
            "KW_IF_COMPILE",
            "KW_THEN_COMPILE",
            "KW_ELSEIF_COMPILE",
            "KW_ELSE_COMPILE",
            "KW_ENDIF_COMPILE",
        ):
            self._skip_source_line()

    def _at_ident_like(self) -> bool:
        tok = self._cur()
        return tok.type == "IDENT" or tok.is_keyword()

    def _eat_ident_like(self) -> Token:
        tok = self._cur()
        if tok.type == "IDENT" or tok.is_keyword():
            self._idx += 1
            return tok
        raise ParseError(
            f"Expected IDENT, got '{tok.text}' ({tok.type})",
            tok.span,
        )

    # ---- program ----

    def parse_program(self) -> Program:
        items: List[TopLevelItem] = []
        sp = self._cur().span
        self._skip_semicolons()
        while not self._at("EOF"):
            try:
                item = self._parse_top_level()
                if item is not None:
                    items.append(item)
                self._skip_semicolons()
            except ParseError as e:
                self._diags.append(
                    Diagnostic(severity="error", message=e.message, span=e.span)
                )
                # error recovery: skip to next procedure/function/EOF
                self._recover_to_top_level()
        self._match("EOF")
        return Program(items=tuple(items), span=sp)

    def _recover_to_top_level(self) -> None:
        """Skip tokens until we reach a recognizable top-level keyword or EOF."""
        top_level = {
            "KW_PROCEDURE", "KW_FUNCTION", "KW_VAR",
            "KW_CATALOG", "KW_DOCUMENT", "KW_REGISTER",
            "KW_ENUM", "KW_FORM", "AMPERSAND", "EOF",
        }
        while not self._at(*top_level):
            self._idx += 1

    def _parse_top_level(self) -> Optional[TopLevelItem]:
        tok = self._cur()
        if tok.type == "AMPERSAND":
            annotations: List[Annotation] = []
            while self._at("AMPERSAND"):
                annotation = self._parse_annotation()
                if annotation.name.casefold() not in _PP_COMPAT_ANNOTATIONS:
                    annotations.append(annotation)
                self._skip_semicolons()
            if not annotations:
                return None
            if self._at("KW_PROCEDURE"):
                return self._parse_procedure(tuple(annotations))
            if self._at("KW_FUNCTION"):
                return self._parse_function(tuple(annotations))
            if self._at("KW_VAR"):
                return self._parse_var_decl(tuple(annotations))
            raise ParseError(
                "Declaration annotation must precede a variable, procedure or function",
                tok.span,
            )
        if tok.type == "KW_PROCEDURE":
            return self._parse_procedure()
        if tok.type == "KW_FUNCTION":
            return self._parse_function()
        if tok.type == "KW_VAR":
            return self._parse_var_decl()
        if tok.type == "KW_CATALOG":
            return self._parse_catalog_decl()
        if tok.type == "KW_DOCUMENT":
            return self._parse_document_decl()
        if tok.type == "KW_ENUM":
            return self._parse_enum_decl()
        if tok.type == "KW_REGISTER":
            return self._parse_register_decl()
        if tok.type == "KW_FORM":
            return self._parse_form_decl()
        if tok.type == "TILDE":
            # label at top level — wrap in a procedure? skip for now
            self._idx += 1
            return None
        # Preprocessor directives — skip entire #Region blocks etc.
        if tok.type in ("KW_REGION", "KW_ENDREGION",
                        "KW_IF_COMPILE", "KW_THEN_COMPILE", "KW_ELSEIF_COMPILE",
                        "KW_ELSE_COMPILE", "KW_ENDIF_COMPILE",
                        "KW_USE"):
            self._skip_source_line()
            return None
        # 1C/BAS modules may contain executable initialization statements at
        # module level. They are compiled into a dedicated module initializer.
        return self._parse_stmt()

    # ---- Procedure / Function ----

    def _parse_annotation(self) -> Annotation:
        sp = self._eat("AMPERSAND").span
        name = self._eat_ident_like().text
        args: Tuple[Expr, ...] = ()
        if self._match("LPAREN"):
            args = tuple(self._parse_args())
            self._eat("RPAREN")
        return Annotation(name=name, args=args, span=sp)

    def _parse_params(self) -> Tuple[Param, ...]:
        params: List[Param] = []
        self._eat("LPAREN")
        while not self._at("RPAREN", "EOF"):
            sp = self._cur().span
            by_value = bool(self._match("KW_VAL"))
            name = self._eat_ident_like().text
            default: Optional[Expr] = None
            if self._match("EQ", "ASSIGN"):
                default = self._parse_expr()
            params.append(Param(name=name, by_value=by_value,
                                default_value=default, span=sp))
            if not self._match("COMMA"):
                break
        self._eat("RPAREN")
        return tuple(params)

    def _parse_procedure(
        self,
        annotations: Tuple[Annotation, ...] = (),
    ) -> ProcedureDecl:
        sp = self._cur().span
        self._eat("KW_PROCEDURE")
        name = self._eat_ident_like().text
        params = self._parse_params()
        exported = bool(self._match("KW_EXPORT"))
        self._skip_semicolons()
        body = self._parse_body({"KW_ENDPROCEDURE"})
        self._eat("KW_ENDPROCEDURE")
        return ProcedureDecl(name=name, params=params, body=body,
                             exported=exported, span=sp,
                             annotations=annotations)

    def _parse_function(
        self,
        annotations: Tuple[Annotation, ...] = (),
    ) -> FunctionDecl:
        sp = self._cur().span
        self._eat("KW_FUNCTION")
        name = self._eat_ident_like().text
        params = self._parse_params()
        exported = bool(self._match("KW_EXPORT"))
        self._skip_semicolons()
        body = self._parse_body({"KW_ENDFUNCTION"})
        self._eat("KW_ENDFUNCTION")
        return FunctionDecl(name=name, params=params, body=body,
                            exported=exported, span=sp,
                            annotations=annotations)

    # ---- Var declaration ----

    def _parse_var_decl(
        self,
        annotations: Tuple[Annotation, ...] = (),
    ) -> VarDecl:
        sp = self._cur().span
        self._eat("KW_VAR")
        names: List[str] = []
        first_name = self._eat_ident_like().text
        names.append(first_name)
        # Support: Var x = initializer  (syntactic sugar → VarDecl + assign)
        # We only support initializer for the first variable for now.
        self._var_init_name: Optional[str] = None
        self._var_init_expr: Optional[Expr] = None
        if self._at("EQ", "ASSIGN"):
            self._idx += 1  # consume =
            self._var_init_name = first_name
            self._var_init_expr = self._parse_expr()
        else:
            while self._match("COMMA"):
                names.append(self._eat_ident_like().text)
        exported = bool(self._match("KW_EXPORT"))
        self._match("SEMICOLON")
        return VarDecl(
            names=tuple(names),
            exported=exported,
            span=sp,
            annotations=annotations,
        )

    # ---- Body / Statements ----

    _END_OF_BODY = frozenset({
        "KW_ENDPROCEDURE", "KW_ENDFUNCTION",
        "KW_ENDIF", "KW_ELSE", "KW_ELSEIF",
        "KW_ENDDO", "KW_ENDWHILE",
        "KW_EXCEPT", "KW_ENDTRY",
        "EOF",
    })

    def _parse_body(self, terminators: set) -> Tuple[Stmt, ...]:
        stmts: List[Stmt] = []
        stop = self._END_OF_BODY | terminators
        while not self._at(*stop):
            self._skip_semicolons()
            if self._at(*stop):
                break
            try:
                stmt = self._parse_stmt()
                if stmt is not None:
                    stmts.append(stmt)
            except ParseError as e:
                self._diags.append(
                    Diagnostic(severity="error", message=e.message, span=e.span)
                )
                # recover: skip to semicolon or end-of-body
                while not self._at("SEMICOLON", *stop):
                    self._idx += 1
                self._match("SEMICOLON")
            self._skip_semicolons()
        return tuple(stmts)

    def _parse_stmt(self) -> Optional[Stmt]:
        tok = self._cur()

        if tok.type == "KW_IF":
            return self._parse_if()
        if tok.type == "KW_FOR":
            return self._parse_for()
        if tok.type == "KW_WHILE":
            return self._parse_while()
        if tok.type == "KW_RETURN":
            return self._parse_return()
        if tok.type == "KW_BREAK":
            self._idx += 1
            return BreakStmt(span=tok.span)
        if tok.type == "KW_CONTINUE":
            self._idx += 1
            return ContinueStmt(span=tok.span)
        if tok.type == "KW_TRY":
            return self._parse_try()
        if tok.type == "KW_RAISE":
            return self._parse_raise()
        if tok.type == "KW_DO":
            return self._parse_execute()
        if tok.type == "KW_VAR":
            return self._parse_var_decl()
        if tok.type == "KW_GOTO":
            return self._parse_goto()
        if tok.type == "TILDE":
            return self._parse_label()
        # Preprocessor — skip
        if tok.type in ("KW_REGION", "KW_ENDREGION",
                        "KW_IF_COMPILE", "KW_THEN_COMPILE", "KW_ELSEIF_COMPILE",
                        "KW_ELSE_COMPILE", "KW_ENDIF_COMPILE"):
            self._skip_source_line()
            return None
        # Expression statement: assign or call
        return self._parse_expr_stmt()

    def _parse_if(self) -> IfStmt:
        sp = self._cur().span
        self._eat("KW_IF")
        cond = self._parse_expr()
        self._eat("KW_THEN")
        self._skip_semicolons()
        then_body = self._parse_body({"KW_ELSEIF", "KW_ELSE", "KW_ENDIF"})
        elseifs: List[Tuple] = []
        while self._at("KW_ELSEIF"):
            self._idx += 1
            ei_cond = self._parse_expr()
            self._eat("KW_THEN")
            self._skip_semicolons()
            ei_body = self._parse_body({"KW_ELSEIF", "KW_ELSE", "KW_ENDIF"})
            elseifs.append((ei_cond, ei_body))
        else_body = None
        if self._match("KW_ELSE"):
            self._skip_semicolons()
            else_body = self._parse_body({"KW_ENDIF"})
        self._eat("KW_ENDIF")
        return IfStmt(
            condition=cond,
            then_block=then_body,
            elseif_clauses=tuple(elseifs),
            else_block=else_body,
            span=sp,
        )

    def _parse_for(self) -> Stmt:
        sp = self._cur().span
        self._eat("KW_FOR")
        if self._at("KW_EACH"):
            # ForEach
            self._eat("KW_EACH")
            var = self._eat_ident_like().text
            self._eat("KW_IN")
            coll = self._parse_expr()
            self._eat("KW_DO")
            self._skip_semicolons()
            body = self._parse_body({"KW_ENDDO"})
            self._eat("KW_ENDDO")
            return ForEachStmt(var=var, collection=coll, body=body, span=sp)
        # Numeric For
        var = self._eat_ident_like().text
        self._eat("EQ", "ASSIGN")
        start = self._parse_expr()
        self._eat("KW_TO")
        end = self._parse_expr()
        self._eat("KW_DO")
        self._skip_semicolons()
        body = self._parse_body({"KW_ENDDO"})
        self._eat("KW_ENDDO")
        return ForStmt(var=var, start=start, end=end, body=body, span=sp)

    def _parse_while(self) -> WhileStmt:
        sp = self._cur().span
        self._eat("KW_WHILE")
        cond = self._parse_expr()
        self._eat("KW_DO")
        self._skip_semicolons()
        body = self._parse_body({"KW_ENDDO", "KW_ENDWHILE"})
        if not self._match("KW_ENDDO"):
            self._eat("KW_ENDWHILE")
        return WhileStmt(condition=cond, body=body, span=sp)

    def _parse_return(self) -> ReturnStmt:
        sp = self._cur().span
        self._eat("KW_RETURN")
        value: Optional[Expr] = None
        if not self._at("SEMICOLON", *self._END_OF_BODY):
            value = self._parse_expr()
        self._match("SEMICOLON")
        return ReturnStmt(value=value, span=sp)

    def _parse_try(self) -> TryStmt:
        sp = self._cur().span
        self._eat("KW_TRY")
        self._skip_semicolons()
        try_body = self._parse_body({"KW_EXCEPT"})
        self._eat("KW_EXCEPT")
        self._skip_semicolons()
        except_body = self._parse_body({"KW_ENDTRY"})
        self._eat("KW_ENDTRY")
        return TryStmt(try_block=try_body, except_block=except_body, span=sp)

    def _parse_raise(self) -> RaiseStmt:
        sp = self._cur().span
        self._eat("KW_RAISE")
        value: Optional[Expr] = None
        if not self._at("SEMICOLON", *self._END_OF_BODY):
            value = self._parse_expr()
        self._match("SEMICOLON")
        return RaiseStmt(value=value, span=sp)

    def _parse_execute(self) -> ExecuteStmt:
        sp = self._eat("KW_DO").span
        source = self._parse_expr()
        self._match("SEMICOLON")
        return ExecuteStmt(source=source, span=sp)

    def _parse_goto(self) -> GotoStmt:
        sp = self._cur().span
        self._eat("KW_GOTO")
        self._eat("LPAREN")
        self._eat("TILDE")
        label = self._eat("IDENT").text
        self._eat("RPAREN")
        return GotoStmt(label=label, span=sp)

    def _parse_label(self) -> LabelStmt:
        sp = self._cur().span
        self._eat("TILDE")
        name = self._eat("IDENT").text
        self._match("COLON")
        return LabelStmt(name=name, span=sp)

    def _parse_expr_stmt(self) -> Stmt:
        sp = self._cur().span
        expr = self._parse_postfix()
        # assignment?
        if self._at("EQ", "ASSIGN") and isinstance(expr, (NameExpr, FieldExpr, IndexExpr)):
            self._idx += 1
            value = self._parse_expr()
            self._match("SEMICOLON")
            return AssignStmt(target=expr, value=value, span=sp)
        # call statement?
        if isinstance(expr, CallExpr):
            self._match("SEMICOLON")
            return CallStmt(call=expr, span=sp)
        # Try to parse as call (func without parens call not supported — require ())
        self._match("SEMICOLON")
        # Wrap bare expr in CallStmt if it looks like a call
        if isinstance(expr, CallExpr):
            return CallStmt(call=expr, span=sp)
        # Otherwise treat as assignment to allow "x" as no-op (used in some BSL patterns)
        return CallStmt(call=CallExpr(callee=expr, args=(), span=sp), span=sp)

    # ---- Expressions ----

    def _parse_expr(self) -> Expr:
        return self._parse_or()

    def _parse_or(self) -> Expr:
        self._skip_expression_directives()
        left = self._parse_and()
        while True:
            self._skip_expression_directives()
            if not self._at("OR"):
                break
            op_tok = self._cur(); self._idx += 1
            right = self._parse_and()
            left = BinaryExpr(op="Or", left=left, right=right, span=op_tok.span)
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_not()
        while True:
            self._skip_expression_directives()
            if not self._at("AND"):
                break
            op_tok = self._cur(); self._idx += 1
            right = self._parse_not()
            left = BinaryExpr(op="And", left=left, right=right, span=op_tok.span)
        return left

    def _parse_not(self) -> Expr:
        if self._at("NOT"):
            sp = self._cur().span; self._idx += 1
            return UnaryExpr(op="Not", operand=self._parse_not(), span=sp)
        return self._parse_cmp()

    def _parse_cmp(self) -> Expr:
        left = self._parse_add()
        while True:
            self._skip_expression_directives()
            if not self._at("EQ", "NEQ", "LT", "GT", "LE", "GE"):
                break
            op_tok = self._cur(); self._idx += 1
            right = self._parse_add()
            op_str = {"EQ": "=", "NEQ": "<>", "LT": "<", "GT": ">",
                      "LE": "<=", "GE": ">="}[op_tok.type]
            left = BinaryExpr(op=op_str, left=left, right=right, span=op_tok.span)
        return left

    def _parse_add(self) -> Expr:
        left = self._parse_mul()
        while True:
            self._skip_expression_directives()
            if not self._at("PLUS", "MINUS", "AMPERSAND"):
                break
            op_tok = self._cur(); self._idx += 1
            right = self._parse_mul()
            left = BinaryExpr(op=op_tok.text, left=left, right=right, span=op_tok.span)
        return left

    def _parse_mul(self) -> Expr:
        left = self._parse_unary()
        while True:
            self._skip_expression_directives()
            if not self._at("STAR", "SLASH", "PERCENT"):
                break
            op_tok = self._cur(); self._idx += 1
            right = self._parse_unary()
            left = BinaryExpr(op=op_tok.text, left=left, right=right, span=op_tok.span)
        return left

    def _parse_unary(self) -> Expr:
        if self._at("PLUS", "MINUS"):
            tok = self._cur(); self._idx += 1
            return UnaryExpr(op=tok.text, operand=self._parse_unary(), span=tok.span)
        return self._parse_postfix()

    def _parse_postfix(self) -> Expr:
        expr = self._parse_primary()
        while True:
            if self._at("DOT"):
                sp = self._cur().span; self._idx += 1
                field_name = self._eat_ident_like().text
                expr = FieldExpr(obj=expr, field=field_name, span=sp)
            elif self._at("LBRACKET"):
                sp = self._cur().span; self._idx += 1
                idx_expr = self._parse_expr()
                self._eat("RBRACKET")
                expr = IndexExpr(obj=expr, index=idx_expr, span=sp)
            elif self._at("LPAREN"):
                sp = self._cur().span; self._idx += 1
                args = self._parse_args()
                self._eat("RPAREN")
                expr = CallExpr(callee=expr, args=tuple(args), span=sp)
            else:
                break
        return expr

    def _parse_args(self) -> List[Expr]:
        args: List[Expr] = []
        while not self._at("RPAREN", "EOF"):
            if self._match("COMMA"):
                comma_tok = self.tokens[self._idx - 1]
                args.append(Literal(value=None, raw="", span=comma_tok.span))
                continue
            args.append(self._parse_expr())
            if not self._match("COMMA"):
                break
            if self._at("RPAREN", "EOF"):
                comma_tok = self.tokens[self._idx - 1]
                args.append(Literal(value=None, raw="", span=comma_tok.span))
        return args

    def _parse_primary(self) -> Expr:
        tok = self._cur()

        if tok.type == "NUMBER":
            self._idx += 1
            raw = tok.text.replace("_", "")
            val: float | int = float(raw) if "." in raw else int(raw)
            return Literal(value=val, raw=tok.text, span=tok.span)

        if tok.type == "STRING":
            self._idx += 1
            parts = [tok.text]
            raw_parts = [tok.text]
            while self._at("STRING"):
                next_tok = self._cur()
                self._idx += 1
                parts.append(next_tok.text)
                raw_parts.append(next_tok.text)
            return Literal(value="".join(parts), raw="".join(raw_parts), span=tok.span)

        if tok.type == "TRUE":
            self._idx += 1
            return Literal(value=True, raw=tok.text, span=tok.span)

        if tok.type == "FALSE":
            self._idx += 1
            return Literal(value=False, raw=tok.text, span=tok.span)

        if tok.type in ("UNDEFINED", "NULL"):
            self._idx += 1
            return Literal(value=None, raw=tok.text, span=tok.span)

        if tok.type == "LPAREN":
            self._idx += 1
            expr = self._parse_expr()
            self._eat("RPAREN")
            return expr

        if tok.type == "QUESTION":
            sp = tok.span
            self._idx += 1
            self._eat("LPAREN")
            args = self._parse_args()
            self._eat("RPAREN")
            return CallExpr(
                callee=NameExpr(name="?", span=sp),
                args=tuple(args),
                span=sp,
            )

        if tok.type == "KW_NEW":
            sp = tok.span; self._idx += 1
            if self._match("LPAREN"):
                dynamic_args = self._parse_args()
                self._eat("RPAREN")
                if not dynamic_args:
                    raise ParseError(
                        "Dynamic constructor requires a type expression",
                        sp,
                    )
                return NewExpr(
                    type_name=None,
                    type_expr=dynamic_args[0],
                    args=tuple(dynamic_args[1:]),
                    span=sp,
                )
            type_name = self._eat_ident_like().text
            args: List[Expr] = []
            if self._match("LPAREN"):
                args = self._parse_args()
                self._eat("RPAREN")
            return NewExpr(type_name=type_name, args=tuple(args), span=sp)

        if self._at_ident_like():
            self._idx += 1
            return NameExpr(name=tok.text, span=tok.span)

        raise ParseError(
            f"Unexpected token in expression: '{tok.text}' ({tok.type})",
            tok.span,
        )

    # ---- DSL metadata declarations ----

    def _parse_field_decl(self) -> FieldDecl:
        sp = self._cur().span
        name = self._eat_ident_like().text
        type_ref: Optional[TypeRef] = None
        if self._match("COLON"):
            type_name = self._eat_ident_like().text
            qualifier = None
            if self._match("DOT"):
                qualifier = self._eat_ident_like().text
            type_ref = TypeRef(name=type_name, qualifier=qualifier, span=sp)
        return FieldDecl(name=name, type_ref=type_ref, span=sp)

    def _parse_field_list(self) -> List[FieldDecl]:
        fields: List[FieldDecl] = []
        while self._at_ident_like():
            fields.append(self._parse_field_decl())
            self._match("COMMA")
            self._skip_semicolons()
        return fields

    def _parse_table_part(self) -> TablePartDecl:
        sp = self._cur().span
        self._eat("KW_TABLE")
        name = self._eat_ident_like().text
        self._eat("LBRACE")
        self._skip_semicolons()
        if self._match("KW_FIELDS"):
            self._match("COLON")
        fields = self._parse_field_list()
        self._eat("RBRACE")
        return TablePartDecl(name=name, fields=tuple(fields), span=sp)

    def _parse_catalog_decl(self) -> CatalogDecl:
        sp = self._cur().span
        self._eat("KW_CATALOG")
        name = self._eat_ident_like().text
        self._eat("LBRACE")
        self._skip_semicolons()
        fields: List[FieldDecl] = []
        tables: List[TablePartDecl] = []
        while not self._at("RBRACE", "EOF"):
            if self._match("KW_FIELDS"):
                self._match("COLON")
                fields = self._parse_field_list()
            elif self._at("KW_TABLE"):
                tables.append(self._parse_table_part())
            else:
                self._idx += 1
        self._eat("RBRACE")
        return CatalogDecl(name=name, fields=tuple(fields),
                           tabular_parts=tuple(tables), span=sp)

    def _parse_document_decl(self) -> DocumentDecl:
        sp = self._cur().span
        self._eat("KW_DOCUMENT")
        name = self._eat_ident_like().text
        self._eat("LBRACE")
        self._skip_semicolons()
        fields: List[FieldDecl] = []
        tables: List[TablePartDecl] = []
        while not self._at("RBRACE", "EOF"):
            if self._match("KW_FIELDS"):
                self._match("COLON")
                fields = self._parse_field_list()
            elif self._at("KW_TABLE"):
                tables.append(self._parse_table_part())
            else:
                self._idx += 1
        self._eat("RBRACE")
        return DocumentDecl(name=name, fields=tuple(fields),
                            tabular_parts=tuple(tables), span=sp)

    def _parse_enum_decl(self) -> EnumDecl:
        sp = self._cur().span
        self._eat("KW_ENUM")
        name = self._eat_ident_like().text
        self._eat("LBRACE")
        self._skip_semicolons()
        values: List[EnumValueDecl] = []
        # Enum values can be any IDENT or keyword used as name
        while not self._at("RBRACE", "EOF"):
            tok = self._cur()
            if tok.type in ("IDENT",) or tok.is_keyword():
                vsp = tok.span
                vname = tok.text
                self._idx += 1
                values.append(EnumValueDecl(name=vname, span=vsp))
                self._match("COMMA")
                self._skip_semicolons()
            else:
                break
        self._eat("RBRACE")
        return EnumDecl(name=name, values=tuple(values), span=sp)

    def _parse_register_decl(self) -> RegisterDecl:
        sp = self._cur().span
        self._eat("KW_REGISTER")
        name = self._eat_ident_like().text
        self._eat("LBRACE")
        self._skip_semicolons()
        dimensions: List[FieldDecl] = []
        resources: List[FieldDecl] = []
        attributes: List[FieldDecl] = []
        while not self._at("RBRACE", "EOF"):
            if self._match("KW_DIMENSIONS"):
                self._match("COLON")
                dimensions = self._parse_field_list()
            elif self._match("KW_RESOURCES"):
                self._match("COLON")
                resources = self._parse_field_list()
            elif self._match("KW_FIELDS"):
                self._match("COLON")
                attributes = self._parse_field_list()
            else:
                self._idx += 1
        self._eat("RBRACE")
        return RegisterDecl(name=name,
                            dimensions=tuple(dimensions),
                            resources=tuple(resources),
                            attributes=tuple(attributes),
                            span=sp)

    def _parse_form_decl(self) -> FormDecl:
        sp = self._cur().span
        self._eat("KW_FORM")
        parts = [self._eat_ident_like().text]
        while self._match("DOT"):
            parts.append(self._eat_ident_like().text)
        qname = ".".join(parts)
        self._eat("LBRACE")
        self._skip_semicolons()
        cols: List[str] = []
        while not self._at("RBRACE", "EOF"):
            if self._match("KW_TABLE"):
                self._match("COLON")
                while self._at_ident_like():
                    cols.append(self._eat_ident_like().text)
                    self._match("COMMA")
            else:
                self._idx += 1
        self._eat("RBRACE")
        return FormDecl(qualified_name=qname,
                        table_columns=tuple(cols), span=sp)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(
    text: str,
    profile: LanguageProfile,
) -> tuple[Program | None, list[Diagnostic]]:
    """Parse MetaScript source into AST.

    Returns:
        (program, diagnostics)
        - program is None only if a fatal unrecoverable error occurred.
        - diagnostics may contain errors even when program is returned
          (soft recovery mode: partial AST with error notes).
    """
    try:
        tokens = lex(text, profile)
    except Exception as e:
        span = SourceSpan(1, 1)
        return None, [Diagnostic(severity="error",
                                  message=f"Lexer error: {e}", span=span)]

    p = Parser(tokens=tokens)
    try:
        prog = p.parse_program()
    except ParseError as e:
        p._diags.append(
            Diagnostic(severity="error", message=e.message, span=e.span)
        )
        prog = None
    except Exception as e:
        p._diags.append(
            Diagnostic(severity="error",
                       message=f"Internal parser error: {e}",
                       span=SourceSpan(1, 1))
        )
        prog = None

    return prog, p._diags
