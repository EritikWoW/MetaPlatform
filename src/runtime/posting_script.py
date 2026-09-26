"""Bounded posting execution. Scripts receive snapshots/buffers, never a DB."""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager

from src.dsl.compiler import ARG_NAME, LOAD_NAME, compile_module
from src.dsl.languages import get_profile
from src.dsl.parser import parse
from src.dsl.vm import MsException, VM
from src.dsl.preprocessor import SERVER_SYMBOLS, preprocess
from src.dsl.diagnostics import ParseError


class PostingError(Exception):
    pass


class PostingBudget:
    """One budget for the entire operation, including hooks and common modules."""
    def __init__(self, *, instructions=200000, depth=64, modules=128):
        self.remaining = instructions
        self.max_depth = depth
        self.max_modules = modules
        self.depth = 0
        self.source_chars = 0

    @contextmanager
    def frame(self):
        if self.depth >= self.max_depth:
            raise PostingError("Posting execution limit exceeded: call depth")
        self.depth += 1
        try:
            yield
        finally:
            self.depth -= 1

    def source(self, text):
        if not isinstance(text, str) or not text.strip():
            raise PostingError("Module source unavailable")
        self.source_chars += len(text)
        if len(text) > 2000000 or self.source_chars > 8000000:
            raise PostingError("Posting execution limit exceeded: source size")


class PostingMethod:
    """A script call target; unlike host callbacks it retains lvalue arguments."""
    def __init__(self, invoke):
        self.invoke = invoke


class Namespace:
    def __init__(self, values):
        object.__setattr__(self, "_values", {})
        for name, value in values.items():
            self._values[str(name).casefold()] = value

    def __getattr__(self, name):
        try:
            return self._values[name.casefold()]
        except KeyError as exc:
            raise PostingError(f"Unknown posting field or method: {name}") from exc

    def __setattr__(self, name, value):
        raise PostingError(f"Posting snapshot is read-only: {name}")

    def __deepcopy__(self, memo):
        return self


FIELD_ALIASES = {
    "_period": ("Period", "Період", "Период"),
    "_kind": ("RecordType", "ВидРуху", "ВидДвижения"),
    "_active": ("Active", "Активність", "Активность"),
    "_date": ("Date", "Дата"),
    "_number": ("Number", "Номер"),
    "_guid": ("Ref", "Посилання", "Ссылка"),
    "_posted": ("Posted", "Проведено"),
}


def _merge_field_aliases(aliases, extra, storage):
    for alias, target in (extra or {}).items():
        alias = alias.casefold()
        if target not in storage:
            raise PostingError(f"Metadata field is missing from native storage: {target}")
        if alias in aliases and aliases[alias] != target:
            raise PostingError(f"Ambiguous posting field alias: {alias}")
        aliases[alias] = target


def snapshot(values, aliases=None):
    names = {}
    for key in values:
        if not key.startswith("_") and key != "rowid":
            _merge_field_aliases(names, {key: key}, values)
        for alias in FIELD_ALIASES.get(key, ()):
            _merge_field_aliases(names, {alias: key}, values)
    _merge_field_aliases(names, aliases, values)
    return Namespace({alias: deepcopy(values[key]) for alias, key in names.items()})


class MovementRow:
    def __init__(self, schema, period, field_aliases=None):
        object.__setattr__(self, "_schema", schema)
        object.__setattr__(self, "_data", {"_period": period, "_active": True})
        aliases = {key.casefold(): key for key in schema if not key.startswith("_")}
        for key in ("_period", "_kind", "_active"):
            for alias in FIELD_ALIASES[key]:
                aliases[alias.casefold()] = key
        _merge_field_aliases(aliases, field_aliases, schema)
        object.__setattr__(self, "_aliases", aliases)

    def __getattr__(self, name):
        key = self._aliases.get(name.casefold())
        if key is None:
            raise PostingError(f"Unknown movement field: {name}")
        return self._data.get(key)

    def __setattr__(self, name, value):
        key = self._aliases.get(name.casefold())
        if key is None:
            raise PostingError(f"Unknown movement field: {name}")
        self._data[key] = value

    def validated(self, *, require_kind):
        row = dict(self._data)
        for key, spec in self._schema.items():
            if not key.startswith("_") and (spec.get("required") or spec.get("nullable") is False):
                if row.get(key) is None:
                    raise PostingError(f"Required movement field is missing: {key}")
        if not isinstance(row.get("_period"), str) or not row["_period"].strip():
            raise PostingError("Movement Period is required")
        if require_kind and row.get("_kind") not in {"+", "-"}:
            raise PostingError("Movement RecordType must explicitly be Receipt or Expense")
        if "_kind" in row:
            row["_record_kind"] = row["_kind"]
        for key, value in row.items():
            kind = str((self._schema.get(key) or {}).get("type") or "").casefold()
            if value is None:
                continue
            valid = True
            if kind in {"float", "number", "decimal", "int", "integer"}:
                valid = isinstance(value, (int, float)) and not isinstance(value, bool)
                if kind in {"int", "integer"}:
                    valid = valid and isinstance(value, int)
                if isinstance(value, float):
                    import math
                    valid = valid and math.isfinite(value)
            elif kind in {"str", "string"}:
                valid = isinstance(value, str)
            elif kind in {"bool", "boolean"}:
                valid = isinstance(value, bool)
            if not valid:
                raise PostingError(f"Invalid movement value for {key}: expected {kind}")
        return row


class MovementSet:
    def __init__(self, schema, period, *, require_kind, field_aliases=None):
        object.__setattr__(self, "_schema", schema)
        object.__setattr__(self, "_period", period)
        object.__setattr__(self, "_require_kind", require_kind)
        object.__setattr__(self, "_rows", [])
        object.__setattr__(self, "_write", False)
        object.__setattr__(self, "_field_aliases", field_aliases)

    def __getattr__(self, name):
        key = name.casefold()
        if key in {"write", "записувати", "записывать"}:
            return self._write
        if key in {"add", "додати", "добавить"}:
            return self.add
        if key in {"count", "кількість", "количество"}:
            return lambda: len(self._rows)
        raise PostingError(f"Unsupported movement operation: {name}")

    def __setattr__(self, name, value):
        if name.casefold() not in {"write", "записувати", "записывать"} or not isinstance(value, bool):
            raise PostingError(f"Invalid movement write flag: {name}")
        object.__setattr__(self, "_write", value)

    def add(self):
        if len(self._rows) >= 10000:
            raise PostingError("Movement row limit exceeded")
        row = MovementRow(self._schema, self._period, self._field_aliases)
        self._rows.append(row)
        return row

    def validated(self):
        if self._rows and not self._write:
            raise PostingError("Movement rows were created without enabling Write")
        return [row.validated(require_kind=self._require_kind) for row in self._rows]


class PostingVM(VM):
    """Bounded execution with read-only document snapshots."""
    def __init__(self, *args, budget=None, registry=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._budget = budget or PostingBudget()
        self._registry = registry

    def _exec_code(self, code, args, *, output_locals=None):
        allowed = {"atserver", "насервере", "насервері", "atservernocontext",
                   "насерверебезконтекста", "насерверібезконтексту"}
        for annotation in code.annotations:
            if annotation.name.casefold() not in allowed or annotation.args:
                raise PostingError(f"Unsupported posting annotation: {annotation.name}")
        with self._budget.frame():
            return super()._exec_code(code, args, output_locals=output_locals)

    def _exec_one(self, frame, instr, op):
        self._budget.remaining -= 1
        if self._budget.remaining < 0:
            raise PostingError("Posting execution limit exceeded")
        if self._registry is not None and op in {LOAD_NAME, ARG_NAME}:
            name = instr.arg
            if name not in frame.locals_ and name not in frame.globals_ and name not in frame.builtins:
                frame.globals_[name] = self._registry.namespace(name)
        try:
            return super()._exec_one(frame, instr, op)
        except (MsException, ZeroDivisionError) as exc:
            if isinstance(exc, ZeroDivisionError):
                exc = MsException("Division by zero")
            if not exc.module_id:
                exc.module_id, exc.procedure, exc.line = frame.module_id or self._module_name, frame.code.name, frame.current_line
            raise exc

    def _do_call(self, callee, args):
        if isinstance(callee, PostingMethod):
            return callee.invoke(args)
        return super()._do_call(callee, args)

    def _execute_source(self, caller_frame, source):
        module, _ = compile_posting_source(source, module_guid=self._module_name + ":execute", budget=self._budget)
        with self._budget.frame():
            return self._execute_compiled(caller_frame, module)

    def _get_attr(self, obj, attr):
        if attr.startswith("_"):
            raise PostingError("Internal attributes are unavailable to posting scripts")
        if isinstance(obj, (Namespace, MovementRow, MovementSet)):
            return getattr(obj, attr)
        return super()._get_attr(obj, attr)

    def _set_attr(self, obj, attr, val):
        if attr.startswith("_"):
            raise PostingError("Internal attributes are unavailable to posting scripts")
        return super()._set_attr(obj, attr, val)


def compile_posting_source(source, *, module_guid, budget):
    budget.source(source)
    module_uri = module_guid if str(module_guid).startswith("module://") else f"module://{module_guid}"
    profile = get_profile("mixed")
    try:
        source = preprocess(source, profile, defined_symbols=SERVER_SYMBOLS)
    except ParseError as exc:
        raise PostingError(f"{module_uri}: {exc}") from exc
    program, diagnostics = parse(source, profile)
    errors = [f"L{d.span.line}: {d.message}" for d in diagnostics if d.severity == "error"]
    if errors or program is None:
        raise PostingError("Invalid object module: " + "; ".join(errors[:5]))
    from src.dsl.ast import ProcedureDecl, FunctionDecl, Literal
    declared = [item.name.casefold() for item in program.items if isinstance(item, (ProcedureDecl, FunctionDecl))]
    if len(declared) != len(set(declared)):
        raise PostingError("Multiple declarations of the same procedure or function")
    for item in program.items:
        if isinstance(item, (ProcedureDecl, FunctionDecl)):
            for param in item.params:
                if param.default_value is not None and not isinstance(param.default_value, Literal):
                    raise PostingError(f"Unsupported non-literal parameter default: {item.name}.{param.name}")
    module = compile_module(program, module_name=module_uri)
    required = {
        item.name: max((i + 1 for i, param in enumerate(item.params) if param.default_value is None), default=0)
        for item in program.items if isinstance(item, (ProcedureDecl, FunctionDecl))
    }
    return module, required


def execute_posting(source, *, module_guid, context, action="post", hook="", budget=None, registry=None):
    """Execute only a valid saved module; return messages via context callbacks."""
    budget = budget or (registry.budget if registry is not None else PostingBudget())
    if registry is not None and budget is not registry.budget:
        raise PostingError("Posting modules must share the operation budget")
    module, _ = compile_posting_source(source, module_guid=module_guid, budget=budget)
    aliases = ({hook.casefold()} if hook else
               {"posting", "postingprocessing", "обробкапроведення", "обработкапроведения"}
               if action == "post" else
               {"undoposting", "обробкаскасуванняпроведення", "обработкаудаленияпроведения"})
    candidates = [name for name in (*module.procedures, *module.functions) if name.casefold() in aliases]
    if len(candidates) > 1:
        raise PostingError("Multiple posting handlers found")
    if not candidates and not hook and action == "post":
        raise PostingError("ObjectModule has no posting handler")
    vm = PostingVM(module, initial_globals=context, budget=budget, registry=registry)
    vm.initialize()
    if candidates:
        name = candidates[0]
        code = module.procedures.get(name)
        count = 0 if hook else (2 if action == "post" else 1)
        if code is None or len(code.params) != count or (not hook and code.by_value[0]):
            raise PostingError("Invalid posting handler signature")
        args = [] if hook else [False, "Regular"] if action == "post" else [False]
        _, outputs = vm.call_with_outputs(name, *args)
        if not hook:
            cancel = outputs[code.params[0]]
            if not isinstance(cancel, bool):
                raise PostingError("Posting Cancel must be Boolean")
            if cancel:
                raise PostingError("Posting cancelled by object module")
    if any(vm._globals.get(name) for name in ("Cancel", "Відмова", "Отказ")):
        raise PostingError("Posting cancelled by module")
