"""MetaScript Virtual Machine — stack-based interpreter.

This module is the single source of truth for MetaScript bytecode execution.
Runtime-specific debugging is supported through an optional plugin hook, so
other layers can extend execution without forking the VM implementation.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from .compiler import (
    ARG_NAME, ARG_ATTR, ARG_INDEX,
    BINARY_OP,
    CALL,
    CALL_METHOD,
    EXECUTE,
    FOR_ITER,
    JUMP,
    JUMP_IF_FALSE,
    JUMP_IF_TRUE,
    LOAD_ATTR,
    LOAD_CONST,
    LOAD_FAST,
    LOAD_INDEX,
    LOAD_NAME,
    MAKE_ITER,
    NEW_DYNAMIC,
    NEW_OBJ,
    POP,
    POP_BLOCK,
    PUSH_BLOCK,
    RAISE,
    RETURN,
    RETURN_NONE,
    STORE_ATTR,
    STORE_FAST,
    STORE_INDEX,
    STORE_NAME,
    UNARY_OP,
    CodeObject,
    Instruction,
)


class MsArray:
    """MetaScript Array / Масив."""

    def __init__(self, items: Optional[List] = None) -> None:
        self._items: List[Any] = list(items or [])

    def __getitem__(self, idx):
        return self._items[int(idx)]

    def __setitem__(self, idx, val):
        self._items[int(idx)] = val

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def Add(self, val):
        self._items.append(val)
        return self

    def Добавить(self, val):
        self._items.append(val)
        return self

    def Додати(self, val):
        self._items.append(val)
        return self

    def Get(self, idx):
        return self._items[int(idx)]

    def Получить(self, idx):
        return self._items[int(idx)]

    def Отримати(self, idx):
        return self._items[int(idx)]

    def Set(self, idx, val):
        self._items[int(idx)] = val

    def Установить(self, idx, val):
        self._items[int(idx)] = val

    def Встановити(self, idx, val):
        self._items[int(idx)] = val

    def Count(self):
        return len(self._items)

    def Количество(self):
        return len(self._items)

    def Кількість(self):
        return len(self._items)

    def Clear(self):
        self._items.clear()

    def Очистить(self):
        self._items.clear()

    def Очистити(self):
        self._items.clear()

    def Delete(self, idx):
        del self._items[int(idx)]

    def Удалить(self, idx):
        del self._items[int(idx)]

    def Видалити(self, idx):
        del self._items[int(idx)]

    def __repr__(self):
        return f"Array({self._items!r})"


class MsMap:
    """MetaScript Map / Відповідність (dict-like)."""

    def __init__(self, initial: Any = None) -> None:
        if isinstance(initial, MsMap):
            data = dict(initial._data)
        elif isinstance(initial, dict):
            data = dict(initial)
        else:
            data = {}
        object.__setattr__(self, "_data", data)

    def __getattr__(self, name: str) -> Any:
        if str(name or "").startswith("_"):
            raise AttributeError(name)
        return self._data.get(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if str(name or "").startswith("_"):
            object.__setattr__(self, name, value)
            return
        self._data[name] = value

    def __getitem__(self, key):
        return self._data.get(key)

    def __setitem__(self, key, val):
        self._data[key] = val

    def __iter__(self):
        # BSL iterates structures as KeyAndValue objects, not raw keys.
        return iter(MsMapEntry(key, value) for key, value in self._data.items())

    def Insert(self, key, val):
        self._data[key] = val

    def Вставить(self, key, val=None):
        self._data[key] = val

    def Вставити(self, key, val=None):
        self._data[key] = val

    def Get(self, key, default=None):
        return self._data.get(key, default)

    def Получить(self, key, default=None):
        return self._data.get(key, default)

    def Отримати(self, key, default=None):
        return self._data.get(key, default)

    def Delete(self, key):
        self._data.pop(key, None)

    def Удалить(self, key):
        self._data.pop(key, None)

    def Видалити(self, key):
        self._data.pop(key, None)

    def Count(self):
        return len(self._data)

    def Количество(self):
        return len(self._data)

    def Кількість(self):
        return len(self._data)

    def Clear(self):
        self._data.clear()

    def Очистить(self):
        self._data.clear()

    def Очистити(self):
        self._data.clear()

    def Property(self, key, _value=None):
        return key in self._data

    def Свойство(self, key, _value=None):
        return self.Property(key, _value)

    def Властивість(self, key, _value=None):
        return self.Property(key, _value)

    def __repr__(self):
        return f"Map({self._data!r})"


@dataclass(frozen=True, slots=True)
class MsMapEntry:
    """Key/value pair yielded by BSL Structure and Map iteration."""

    Key: Any
    Value: Any

    @property
    def Ключ(self):
        return self.Key

    @property
    def Значение(self):
        return self.Value

    @property
    def Значення(self):
        return self.Value


@dataclass(frozen=True, slots=True)
class MsTypeDescriptor:
    """Runtime type descriptor returned by ``Type`` / ``Тип``."""

    name: str


class MsException(Exception):
    """MetaScript runtime exception."""

    def __init__(self, message: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.Description = message
        self.DetailedDescription = detail
        self.module_id = ""
        self.procedure = ""
        self.line = 0


class _ReturnSignal(Exception):
    def __init__(self, value: Any) -> None:
        self.value = value


def _builtin_string(x) -> str:
    if x is None:
        return ""
    if isinstance(x, bool):
        return "Правда" if x else "Хиба"
    return str(x)


def _builtin_number(x) -> float:
    if x is None:
        return 0.0
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _builtin_boolean(x) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, str):
        return x.lower() in ("true", "правда", "1", "yes")
    return bool(x)


def _builtin_ternary(cond, when_true=None, when_false=None):
    return when_true if _builtin_boolean(cond) else when_false


def _builtin_nstr(value, lang=None):
    raw = str(value or "")
    text = raw.strip()
    if not text:
        return ""

    pairs = dict(
        (k.lower(), v)
        for k, v in re.findall(r"([A-Za-zА-Яа-я_]+)\s*=\s*'([^']*)'", text)
    )
    if not pairs:
        return raw

    lang_code = str(lang or "").strip().lower()
    if lang_code and lang_code in pairs:
        return pairs[lang_code]

    for preferred in ("uk", "en", "ru"):
        if preferred in pairs:
            return pairs[preferred]

    return next(iter(pairs.values()))


def _make_builtins() -> Dict[str, Any]:
    def _ms_message(x):
        print(f"[MetaScript] {_builtin_string(x)}")

    def _ms_round(x, n=0):
        return round(float(x), int(n))

    def _ms_left(s, n):
        return str(s)[: int(n)]

    def _ms_right(s, n):
        return str(s)[-int(n) :]

    def _ms_mid(s, pos, n=None):
        s = str(s)
        start = int(pos) - 1
        if n is None:
            return s[start:]
        return s[start : start + int(n)]

    def _ms_find(s, sub):
        idx = str(s).find(str(sub))
        return idx + 1 if idx >= 0 else 0

    def _ms_replace(s, what, with_):
        return str(s).replace(str(what), str(with_))

    def _ms_format(val, fmt=""):
        return str(val)

    def _ms_trim_lr(s):
        return str(s).strip()

    def _ms_is_blank_string(s):
        return str(s or "") == ""

    def _ms_is_filled(x):
        return not (x is None or x == "" or x == 0)

    def _ms_type(value):
        if isinstance(value, MsTypeDescriptor):
            return value
        if isinstance(value, str):
            return MsTypeDescriptor(value)
        if isinstance(value, type):
            return value
        return type(value)

    def _ms_type_of(value):
        if value is None:
            return MsTypeDescriptor("Неопределено")
        if isinstance(value, MsMap):
            return MsTypeDescriptor("Структура")
        if isinstance(value, MsArray):
            return MsTypeDescriptor("Массив")
        if isinstance(value, bool):
            return MsTypeDescriptor("Булево")
        if isinstance(value, (int, float)):
            return MsTypeDescriptor("Число")
        if isinstance(value, str):
            return MsTypeDescriptor("Строка")
        if isinstance(value, (datetime.date, datetime.datetime)):
            return MsTypeDescriptor("Дата")
        if type(value).__name__ == "CommonModuleNamespace":
            return MsTypeDescriptor("ОбщийМодуль")
        return type(value)

    return {
        "String": _builtin_string,
        "Number": _builtin_number,
        "Boolean": _builtin_boolean,
        "TypeOf": _ms_type_of,
        "Type": _ms_type,
        "Format": _ms_format,
        "Формат": _ms_format,
        "Array": lambda: MsArray(),
        "Map": lambda: MsMap(),
        "Structure": lambda: MsMap(),
        "Соответствие": lambda: MsMap(),
        "Структура": lambda: MsMap(),
        "NewArray": lambda n=0: MsArray([None] * int(n)),
        "NewStructure": lambda: MsMap(),
        "НовыйМассив": lambda n=0: MsArray([None] * int(n)),
        "НовыйСтруктура": lambda: MsMap(),
        "Message": _ms_message,
        "Сообщить": _ms_message,
        "Alert": _ms_message,
        "Предупреждение": _ms_message,
        "Abs": abs,
        "Max": max,
        "Мин": min,
        "Макс": max,
        "Min": min,
        "Round": _ms_round,
        "Окр": _ms_round,
        "Int": lambda x: int(x),
        "Цел": lambda x: int(x),
        "Sqrt": lambda x: float(x) ** 0.5,
        "Log": lambda x: __import__("math").log(float(x)),
        "Pow": lambda x, n: float(x) ** float(n),
        "Len": lambda s: len(str(s)),
        "СтрДлина": lambda s: len(str(s)),
        "Left": _ms_left,
        "Лев": _ms_left,
        "Right": _ms_right,
        "Прав": _ms_right,
        "Mid": _ms_mid,
        "Сред": _ms_mid,
        "Find": _ms_find,
        "Найти": _ms_find,
        "Upper": lambda s: str(s).upper(),
        "Lower": lambda s: str(s).lower(),
        "ВРег": lambda s: str(s).upper(),
        "НРег": lambda s: str(s).lower(),
        "TrimAll": lambda s: str(s).strip(),
        "TrimLeft": lambda s: str(s).lstrip(),
        "TrimRight": lambda s: str(s).rstrip(),
        "СокрЛП": _ms_trim_lr,
        "Replace": _ms_replace,
        "СтрЗаменить": _ms_replace,
        "StrConcat": lambda *args: "".join(str(a) for a in args),
        "StrSplit": lambda s, sep=",": MsArray(str(s).split(str(sep))),
        "StrRepeat": lambda s, n: str(s) * int(n),
        "StrStartsWith": lambda s, p: str(s).startswith(str(p)),
        "StrEndsWith": lambda s, p: str(s).endswith(str(p)),
        "Char": lambda n: chr(int(n)),
        "CharCode": lambda s: ord(str(s)[0]) if s else 0,
        "CurrentDate": lambda: datetime.datetime.now(),
        "ТекущаяДата": lambda: datetime.datetime.now(),
        "Year": lambda d: d.year if hasattr(d, "year") else 0,
        "Month": lambda d: d.month if hasattr(d, "month") else 0,
        "Day": lambda d: d.day if hasattr(d, "day") else 0,
        "Hour": lambda d: d.hour if hasattr(d, "hour") else 0,
        "Minute": lambda d: d.minute if hasattr(d, "minute") else 0,
        "Second": lambda d: d.second if hasattr(d, "second") else 0,
        "Date": lambda y, m, d: datetime.date(int(y), int(m), int(d)),
        "IsNull": lambda x: x is None,
        "IsUndefined": lambda x: x is None,
        "IsEmpty": lambda x: x is None or x == "" or x == 0,
        "IsFilled": lambda x: not (x is None or x == "" or x == 0),
        "ПустаяСтрока": _ms_is_blank_string,
        "ПорожнійРядок": _ms_is_blank_string,
        "ЗначениеЗаполнено": _ms_is_filled,
        "ЗаповненеЗнч": _ms_is_filled,
        "Тип": _ms_type,
        "ТипЗнч": _ms_type_of,
        "Print": print,
        "Write": lambda x: print(x, end=""),
        "?": _builtin_ternary,
        "NStr": _builtin_nstr,
        "Рядок": _builtin_string,
        "Число": _builtin_number,
        "Логічне": _builtin_boolean,
        "Масив": lambda: MsArray(),
        "Відповідність": lambda: MsMap(),
        "НовийМасив": lambda n=0: MsArray([None] * int(n)),
        "Повідомлення": _ms_message,
        "Попередження": _ms_message,
        "Модуль": abs,
        "Макс": max,
        "Мін": min,
        "Округл": _ms_round,
        "Ціле": lambda x: int(x),
        "Дл": lambda s: len(str(s)),
        "Лів": _ms_left,
        "Прав": _ms_right,
        "Сер": _ms_mid,
        "Знайти": _ms_find,
        "ВРег": lambda s: str(s).upper(),
        "НРег": lambda s: str(s).lower(),
        "СкрПробіли": lambda s: str(s).strip(),
        "СкрЛіво": lambda s: str(s).lstrip(),
        "СкрПраво": lambda s: str(s).rstrip(),
        "СтрЗамінити": _ms_replace,
        "НСтр": _builtin_nstr,
        "ПоточнаДата": lambda: datetime.datetime.now(),
        "ЄNull": lambda x: x is None,
        "ЄНевизначено": lambda x: x is None,
        "ПустеЗнч": lambda x: x is None or x == "" or x == 0,
    }


BUILTINS = _make_builtins()


@dataclass
class _Reference:
    read: Any
    write: Any


@dataclass
class _CallArgument:
    reference: _Reference
    value: Any


class _Locals(MutableMapping):
    """Debugger-visible values with live reference bindings, not copy-out slots."""
    def __init__(self, names=()):
        self.values_ = {name: None for name in names}

    def __getitem__(self, key):
        value = self.values_[key]
        return value.read() if isinstance(value, _Reference) else value

    def __setitem__(self, key, value):
        current = self.values_.get(key)
        if isinstance(current, _Reference):
            current.write(value)
        else:
            self.values_[key] = value

    def __delitem__(self, key):
        del self.values_[key]

    def __iter__(self):
        return iter(self.values_)

    def __contains__(self, key):
        return key in self.values_

    def __len__(self):
        return len(self.values_)

    def bind(self, key, reference):
        self.values_[key] = reference


class _ExecuteScope(MutableMapping):
    """Execute shares caller bindings, including aliased reference parameters."""
    def __init__(self, frame):
        self.frame = frame

    def _scope(self, key):
        return self.frame.locals_ if key in self.frame.locals_ else self.frame.globals_

    def __getitem__(self, key):
        return self._scope(key)[key]

    def __setitem__(self, key, value):
        self._scope(key)[key] = value

    def __delitem__(self, key):
        del self._scope(key)[key]

    def __iter__(self):
        return iter(dict.fromkeys((*self.frame.locals_, *self.frame.globals_)))

    def __contains__(self, key):
        return key in self.frame.locals_ or key in self.frame.globals_

    def __len__(self):
        return len(set(self.frame.locals_) | set(self.frame.globals_))


class Frame:
    """Execution frame for a single procedure/function call."""

    def __init__(
        self,
        code: CodeObject,
        globals_: Dict[str, Any],
        builtins: Dict[str, Any],
        module_id: str = "",
    ) -> None:
        self.code = code
        self.globals_ = globals_
        self.builtins = builtins
        self.module_id = module_id
        self.locals_ = _Locals(code.locals_)
        self.stack: List[Any] = []
        self.ip = 0
        self._try_blocks: list[tuple[int, int]] = []
        self.current_line = 0

    def push(self, val: Any) -> None:
        self.stack.append(val)

    def pop(self) -> Any:
        return self.stack.pop()

    def peek(self) -> Any:
        return self.stack[-1]

    def load_name(self, name: str) -> Any:
        if name in self.locals_:
            return self.locals_[name]
        if name in self.globals_:
            return self.globals_[name]
        if name in self.builtins:
            return self.builtins[name]
        raise MsException(f"Name '{name}' is not defined")

    def store_name(self, name: str, val: Any) -> None:
        if name in self.locals_:
            self.locals_[name] = val
        else:
            self.globals_[name] = val


class VmDebugPlugin(Protocol):
    """Optional execution plugin invoked before each instruction."""

    def before_instruction(
        self,
        *,
        module_id: str,
        frame: Frame,
        call_stack: list[Frame],
        instr: Instruction,
    ) -> None: ...


class VM:
    """MetaScript stack-based virtual machine."""

    def __init__(
        self,
        module=None,
        extra_builtins=None,
        initial_globals=None,
        debug_plugin: VmDebugPlugin | None = None,
        module_name: str = "",
    ):
        self._module = module
        self._globals: Dict[str, Any] = {}
        self._builtins = dict(BUILTINS)
        self._debug_plugin = debug_plugin
        self._module_name = str(module_name or getattr(module, "name", "") or "")
        self._call_stack: list[Frame] = []
        self._initialized = False
        if extra_builtins:
            self._builtins.update(extra_builtins)
        if initial_globals:
            self._globals.update(dict(initial_globals))
        if module:
            for name, code in {**module.procedures, **module.functions}.items():
                self._globals[name] = code
            for var in module.module_vars:
                self._globals.setdefault(var, None)

    def call(self, func_name, *args):
        if self._module is None:
            raise MsException("No module loaded")
        code = self._module.functions.get(func_name) or self._module.procedures.get(func_name)
        if code is None:
            raise MsException(f"Function/Procedure '{func_name}' not found")
        return self._exec_code(code, list(args))

    def call_with_outputs(self, func_name, *args):
        """Call an entry and return its final parameter values to the host."""
        if self._module is None:
            raise MsException("No module loaded")
        code = self._module.functions.get(func_name) or self._module.procedures.get(func_name)
        if code is None:
            raise MsException(f"Function/Procedure '{func_name}' not found")
        outputs = {}
        value = self._exec_code(code, list(args), output_locals=outputs)
        return value, {name: outputs.get(name) for name in code.params}

    def initialize(self):
        if self._initialized:
            return None
        self._initialized = True
        code = getattr(self._module, "initializer", None) if self._module is not None else None
        if code is None:
            return None
        return self._exec_code(code, [])

    def eval_code(self, code, args=None):
        return self._exec_code(code, args or [])

    def _exec_code(self, code, args, *, output_locals=None):
        frame = Frame(code, self._globals, self._builtins, self._module_name)
        for i, param_name in enumerate(code.params):
            if i < len(args):
                value = args[i]
            elif i < len(code.defaults):
                value = code.defaults[i]
            else:
                value = None
            if isinstance(value, _CallArgument):
                by_value = i < len(code.by_value) and code.by_value[i]
                if not by_value:
                    frame.locals_.bind(param_name, value.reference)
                    continue
                value = value.value
            frame.locals_[param_name] = value
        try:
            self._call_stack.append(frame)
            return self._run_frame(frame)
        except _ReturnSignal as result:
            return result.value
        finally:
            if output_locals is not None:
                output_locals.update(frame.locals_)
            if self._call_stack and self._call_stack[-1] is frame:
                self._call_stack.pop()
            else:
                try:
                    self._call_stack.remove(frame)
                except ValueError:
                    pass

    def _run_frame(self, frame):
        instructions = frame.code.instructions
        while frame.ip < len(instructions):
            instr = instructions[frame.ip]
            if int(instr.lineno or 0) > 0:
                frame.current_line = int(instr.lineno or 0)
            if self._debug_plugin is not None and int(instr.lineno or 0) > 0:
                self._debug_plugin.before_instruction(
                    module_id=frame.module_id or self._module_name,
                    frame=frame,
                    call_stack=self._call_stack,
                    instr=instr,
                )
            frame.ip += 1
            op = instr.op
            try:
                self._exec_one(frame, instr, op)
            except _ReturnSignal:
                raise
            except MsException as exc:
                if frame._try_blocks:
                    handler_addr, depth = frame._try_blocks.pop()
                    del frame.stack[depth:]
                    frame.push(exc)
                    frame.ip = handler_addr
                else:
                    if not str(getattr(exc, "module_id", "") or ""):
                        exc.module_id = frame.module_id or self._module_name
                        exc.procedure = str(frame.code.name or "")
                        exc.line = int(frame.current_line or 0)
                    raise
            except ZeroDivisionError:
                exc = MsException("Division by zero")
                if frame._try_blocks:
                    handler_addr, depth = frame._try_blocks.pop()
                    del frame.stack[depth:]
                    frame.push(exc)
                    frame.ip = handler_addr
                else:
                    raise
        return None

    def _exec_one(self, frame, instr, op):
        if op == ARG_NAME:
            name = instr.arg
            reference = _Reference(lambda: frame.load_name(name), lambda v: frame.store_name(name, v))
            frame.push(_CallArgument(reference, reference.read()))
        elif op == ARG_ATTR:
            obj, attr = frame.pop(), instr.arg
            reference = _Reference(lambda: self._get_attr(obj, attr), lambda v: self._set_attr(obj, attr, v))
            frame.push(_CallArgument(reference, reference.read()))
        elif op == ARG_INDEX:
            index, obj = frame.pop(), frame.pop()
            reference = _Reference(lambda: obj[index], lambda v: self._set_index(obj, index, v))
            frame.push(_CallArgument(reference, reference.read()))
        elif op == LOAD_CONST:
            frame.push(instr.arg)
        elif op == LOAD_FAST:
            frame.push(frame.locals_.get(instr.arg))
        elif op == STORE_FAST:
            frame.locals_[instr.arg] = frame.pop()
        elif op == LOAD_NAME:
            frame.push(frame.load_name(instr.arg))
        elif op == STORE_NAME:
            frame.store_name(instr.arg, frame.pop())
        elif op == LOAD_ATTR:
            obj = frame.pop()
            frame.push(self._get_attr(obj, instr.arg))
        elif op == STORE_ATTR:
            # Compiler emits assignment as ``value, object, STORE_ATTR`` so
            # complex target expressions are evaluated after the value.
            obj = frame.pop()
            val = frame.pop()
            self._set_attr(obj, instr.arg, val)
        elif op == LOAD_INDEX:
            idx = frame.pop()
            obj = frame.pop()
            frame.push(obj[idx])
        elif op == STORE_INDEX:
            idx = frame.pop()
            obj = frame.pop()
            val = frame.pop()
            self._set_index(obj, idx, val)
        elif op == CALL:
            argc = instr.arg
            args = list(reversed([frame.pop() for _ in range(argc)]))
            callee = frame.pop()
            frame.push(self._do_call(callee, args))
        elif op == CALL_METHOD:
            argc = instr.arg2
            args = list(reversed([frame.pop() for _ in range(argc)]))
            obj = frame.pop()
            method = self._get_attr(obj, instr.arg)
            frame.push(self._do_call(method, args))
        elif op == NEW_OBJ:
            argc = instr.arg2
            args = list(reversed([frame.pop() for _ in range(argc)]))
            frame.push(self._construct(instr.arg, args))
        elif op == NEW_DYNAMIC:
            argc = instr.arg
            args = list(reversed([frame.pop() for _ in range(argc)]))
            frame.push(self._construct_dynamic(frame.pop(), args))
        elif op == EXECUTE:
            self._execute_source(frame, frame.pop())
        elif op == UNARY_OP:
            frame.push(self._unary(instr.arg, frame.pop()))
        elif op == BINARY_OP:
            right = frame.pop()
            left = frame.pop()
            frame.push(self._binary(instr.arg, left, right))
        elif op == JUMP:
            frame.ip = instr.arg
        elif op == JUMP_IF_FALSE:
            cond = frame.pop()
            if not self._to_bool(cond):
                frame.ip = instr.arg
        elif op == JUMP_IF_TRUE:
            cond = frame.pop()
            if self._to_bool(cond):
                frame.ip = instr.arg
        elif op == POP:
            if frame.stack:
                frame.pop()
        elif op == RETURN:
            raise _ReturnSignal(frame.pop())
        elif op == RETURN_NONE:
            raise _ReturnSignal(None)
        elif op == RAISE:
            exc_val = frame.pop()
            if isinstance(exc_val, MsException):
                raise exc_val
            raise MsException(str(exc_val) if exc_val is not None else "")
        elif op == PUSH_BLOCK:
            frame._try_blocks.append((instr.arg, len(frame.stack)))
        elif op == POP_BLOCK:
            if frame._try_blocks:
                frame._try_blocks.pop()
        elif op == MAKE_ITER:
            frame.push(iter(frame.pop()))
        elif op == FOR_ITER:
            it = frame.peek()
            try:
                frame.push(next(it))
            except StopIteration:
                frame.pop()
                frame.ip = instr.arg

    def _do_call(self, callee, args):
        if callable(callee) and not isinstance(callee, CodeObject):
            try:
                return callee(*(a.value if isinstance(a, _CallArgument) else a for a in args))
            except TypeError as exc:
                raise MsException(f"Call error: {exc}") from exc
        if isinstance(callee, CodeObject):
            try:
                return self._exec_code(callee, args)
            except _ReturnSignal as result:
                return result.value
        frame = self._call_stack[-1] if self._call_stack else None
        location = ""
        if frame is not None:
            location = (
                f" at {frame.module_id or self._module_name or '<module>'}:"
                f"{frame.code.name}:L{int(frame.current_line or 0)}"
            )
        raise MsException(f"'{callee}' is not callable{location}")

    def _construct(self, type_name, args):
        ctor_map = {
            "Array": lambda: MsArray(args if args else []),
            "Масив": lambda: MsArray(args if args else []),
            "Массив": lambda: MsArray(args if args else []),
            "FixedArray": lambda: MsArray(list(args[0]) if args else []),
            "ФіксованийМасив": lambda: MsArray(list(args[0]) if args else []),
            "ФиксированныйМассив": lambda: MsArray(list(args[0]) if args else []),
            "Map": lambda: MsMap(),
            "Відповідність": lambda: MsMap(),
            "Соответствие": lambda: MsMap(),
            "Структура": lambda: MsMap(),
            "Structure": lambda: MsMap(),
            "FixedMap": lambda: MsMap(args[0] if args else None),
            "ФіксованаВідповідність": lambda: MsMap(args[0] if args else None),
            "ФиксированноеСоответствие": lambda: MsMap(args[0] if args else None),
            "FixedStructure": lambda: MsMap(args[0] if args else None),
            "ФіксованаСтруктура": lambda: MsMap(args[0] if args else None),
            "ФиксированнаяСтруктура": lambda: MsMap(args[0] if args else None),
        }
        if type_name in ctor_map:
            return ctor_map[type_name]()
        # ``New Type(...)`` addresses a type namespace, even when a local
        # variable happens to have the same name.
        ctor = self._builtins.get(type_name) or self._globals.get(type_name)
        if ctor:
            return self._do_call(ctor, args)
        raise MsException(f"Unknown type '{type_name}'")

    def _construct_dynamic(self, type_value, args):
        if isinstance(type_value, MsTypeDescriptor):
            return self._construct(type_value.name, args)
        if isinstance(type_value, str):
            return self._construct(type_value, args)
        if callable(type_value):
            return self._do_call(type_value, args)
        raise MsException(
            f"Dynamic constructor type must be a name or callable, got "
            f"{type(type_value).__name__}"
        )

    def _execute_source(self, caller_frame: Frame, source: Any) -> None:
        if not isinstance(source, str):
            raise MsException("Execute source must be a string")

        from src.dsl.languages import MIXED_PROFILE
        from src.dsl.parser import parse
        from .compiler import compile_module

        program, diagnostics = parse(source, MIXED_PROFILE)
        errors = [item for item in diagnostics if item.severity == "error"]
        if program is None or errors:
            message = errors[0].message if errors else "Unknown parser error"
            raise MsException(f"Execute parse error: {message}")

        module = compile_module(program, module_name=f"{self._module_name}:execute")
        self._execute_compiled(caller_frame, module)

    def _execute_compiled(self, caller_frame: Frame, module) -> None:
        """Execute a prepared initializer in the caller's live reference scope."""
        code = module.initializer
        if code is None:
            return

        dynamic_globals = _ExecuteScope(caller_frame)
        frame = Frame(code, dynamic_globals, self._builtins, module.name)
        try:
            self._call_stack.append(frame)
            self._run_frame(frame)
        except _ReturnSignal:
            pass
        finally:
            if self._call_stack and self._call_stack[-1] is frame:
                self._call_stack.pop()

    def _get_attr(self, obj, attr):
        if obj is None:
            raise MsException(f"Cannot get attribute '{attr}' of Undefined")
        if isinstance(obj, dict):
            return obj.get(attr)
        if hasattr(obj, attr):
            return getattr(obj, attr)
        for name in dir(obj):
            if name.lower() == attr.lower():
                return getattr(obj, name)
        raise MsException(f"Object has no attribute '{attr}'")

    def _set_attr(self, obj, attr, val):
        if isinstance(obj, dict):
            obj[attr] = val
        else:
            setattr(obj, attr, val)

    def _set_index(self, obj, index, value):
        try:
            obj[int(index) if isinstance(obj, list) else index] = value
        except TypeError as exc:
            raise MsException(f"Object of type {type(obj).__name__} does not support index assignment") from exc

    @staticmethod
    def _to_bool(val):
        if isinstance(val, bool):
            return val
        if val is None:
            return False
        if isinstance(val, str):
            return val.lower() not in ("", "false", "хиба", "0")
        return bool(val)

    @staticmethod
    def _unary(op, val):
        if op == "+":
            return +val
        if op == "-":
            return -val
        if op in ("Not", "Не", "not"):
            return not VM._to_bool(val)
        return val

    @staticmethod
    def _binary(op, left, right):
        if op == "+":
            if isinstance(left, str) or isinstance(right, str):
                return str(left) + str(right)
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0:
                raise MsException("Division by zero")
            return left / right
        if op == "%":
            return left % right
        if op == "&":
            return str(left) + str(right)
        if op == "=":
            return left == right
        if op == "<>":
            return left != right
        if op == "<":
            return left < right
        if op == ">":
            return left > right
        if op == "<=":
            return left <= right
        if op == ">=":
            return left >= right
        if op in ("And", "and", "Та", "та"):
            return VM._to_bool(left) and VM._to_bool(right)
        if op in ("Or", "or", "Або", "або"):
            return VM._to_bool(left) or VM._to_bool(right)
        raise MsException(f"Unknown operator '{op}'")


def run_module(
    module,
    entry="OnSystemStartup",
    extra_builtins=None,
    initial_globals=None,
    debug_plugin: VmDebugPlugin | None = None,
    module_name: str = "",
    strict_entry: bool = False,
):
    """Create a VM from a compiled module and call the entry function."""

    vm = VM(
        module=module,
        extra_builtins=extra_builtins,
        initial_globals=initial_globals,
        debug_plugin=debug_plugin,
        module_name=module_name or getattr(module, "name", ""),
    )
    initializer = getattr(module, "initializer", None)
    module_identity = str(module_name or getattr(module, "name", "") or "<module>")
    marker_key = "__mp_initialized_modules__"
    marker_raw = initial_globals.get(marker_key) if isinstance(initial_globals, dict) else None
    initialized_modules = set(marker_raw) if isinstance(marker_raw, (set, list, tuple)) else set()
    if initializer is not None and module_identity not in initialized_modules:
        vm.initialize()
        initialized_modules.add(module_identity)
        vm._globals[marker_key] = initialized_modules
        if isinstance(initial_globals, dict):
            initial_globals[marker_key] = initialized_modules
    func = module.functions.get(entry) or module.procedures.get(entry)
    if func is None:
        if strict_entry:
            raise MsException(f"Function/Procedure '{entry}' not found")
        return None
    try:
        return vm.call(entry)
    finally:
        # Debug/evaluation state must reflect assignments completed before a
        # later runtime exception.  Startup coordination also relies on these
        # globals when an imported platform service is not implemented yet.
        if isinstance(initial_globals, dict):
            for key, value in vm._globals.items():
                if isinstance(value, CodeObject) or callable(value):
                    continue
                initial_globals[key] = value


def execute_script(
    source,
    language="uk",
    entry="OnSystemStartup",
    extra_builtins=None,
    context=None,
    module_name: str = "",
    debug_plugin: VmDebugPlugin | None = None,
    strict_entry: bool = False,
):
    """Parse, compile, and execute a MetaScript source string."""

    from src.dsl.languages import get_profile
    from src.dsl.parser import parse
    from .compiler import compile_module

    profile = get_profile(language)
    prog, diags = parse(source, profile)
    errors = [
        f"L{diag.span.line}:{diag.span.col} {diag.message}"
        for diag in diags
        if diag.severity == "error"
    ]
    if errors or prog is None:
        return None, errors
    module = compile_module(prog, module_name=module_name or "<module>")
    try:
        result = run_module(
            module,
            entry=entry,
            extra_builtins=extra_builtins,
            initial_globals=context,
            debug_plugin=debug_plugin,
            module_name=module_name or getattr(module, "name", ""),
            strict_entry=strict_entry,
        )
        return result, []
    except MsException as exc:
        return None, [str(exc)]
    except Exception as exc:
        return None, [f"Runtime error: {exc}"]


__all__ = [
    "BUILTINS",
    "Frame",
    "MsArray",
    "MsException",
    "MsMap",
    "MsTypeDescriptor",
    "VM",
    "VmDebugPlugin",
    "execute_script",
    "run_module",
]
