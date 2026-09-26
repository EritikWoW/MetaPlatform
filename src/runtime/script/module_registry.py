"""Lazy executable namespaces for imported common modules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from src.dsl.compiler import CodeObject, compile_module
from src.dsl.languages import get_identifier_alias_keys, get_profile
from src.dsl.parser import parse
from src.dsl.vm import MsException

from .debugger import DebugSession
from .vm import VM


ModuleResolver = Callable[[str], dict[str, Any] | None]


@dataclass
class _LoadedCommonModule:
    name: str
    module_id: str
    vm: VM


class CommonModuleNamespace:
    """Object exposed to MetaScript as ``CommonModuleName``."""

    def __init__(self, registry: "CommonModuleRegistry", name: str) -> None:
        self._registry = registry
        self._name = str(name or "").strip()

    def __getattr__(self, member: str):
        if str(member or "").startswith("_"):
            raise AttributeError(member)

        if self._registry._load(self._name) is None:
            return _MissingRuntimeValue()

        def _invoke(*args):
            return self._registry.call(self._name, str(member or ""), list(args))

        _invoke.__name__ = str(member or "common_module_call")
        return _invoke

    def __repr__(self) -> str:
        return f"<CommonModuleNamespace {self._name}>"


class _MissingRuntimeValue:
    """Compatibility value for platform services not implemented yet."""

    def __getattr__(self, _name: str):
        return self

    def __call__(self, *_args, **_kwargs):
        return self

    def __bool__(self) -> bool:
        return False

    def __iter__(self):
        return iter(())

    def __len__(self) -> int:
        return 0

    def __eq__(self, other: object) -> bool:
        return (
            other is None
            or isinstance(other, _MissingRuntimeValue)
            or other == ""
            or other == 0
            or other is False
        )

    def __str__(self) -> str:
        return ""

    def Count(self) -> int:
        return 0

    def Количество(self) -> int:
        return 0

    def Кількість(self) -> int:
        return 0


class CommonModuleRegistry:
    """Resolve, compile and cache common modules on first external call."""

    _DOTTED_ROOT = re.compile(r"(?<![.\w])([^\W\d]\w*)\s*\.", flags=re.UNICODE)

    def __init__(
        self,
        resolver: ModuleResolver,
        *,
        shared_context: dict[str, Any] | None = None,
        extra_builtins: dict[str, Any] | None = None,
        debug_session: DebugSession | None = None,
    ) -> None:
        self._resolver = resolver
        self._shared_context = shared_context if isinstance(shared_context, dict) else {}
        self._extra_builtins = dict(extra_builtins or {})
        self._debug_session = debug_session
        self._namespaces: dict[str, CommonModuleNamespace] = {}
        self._modules: dict[str, _LoadedCommonModule] = {}
        self._missing_modules: set[str] = set()
        self._extra_builtins.setdefault("Вычислить", self.evaluate)
        self._extra_builtins.setdefault("Обчислити", self.evaluate)
        self._extra_builtins.setdefault("Evaluate", self.evaluate)

    def evaluate(self, expression: Any) -> Any:
        """Resolve the identifier expressions used for dynamic common modules."""

        source = str(expression or "").strip()
        if re.fullmatch(r"[^\W\d]\w*", source, flags=re.UNICODE):
            return self.namespace(source)
        if len(source) >= 2 and source[0] == source[-1] and source[0] in {'"', "'"}:
            return source[1:-1]
        raise MsException(f"Unsupported dynamic expression: {source}")

    def namespace(self, name: str) -> CommonModuleNamespace:
        key = str(name or "").strip().casefold()
        if not key:
            raise MsException("Common module name is empty")
        namespace = self._namespaces.get(key)
        if namespace is None:
            namespace = CommonModuleNamespace(self, str(name or "").strip())
            self._namespaces[key] = namespace
        return namespace

    def install_source_names(self, context: dict[str, Any], source: str) -> None:
        """Install lazy namespaces for dotted global roots found in source."""

        if not isinstance(context, dict):
            return
        for match in self._DOTTED_ROOT.finditer(str(source or "")):
            name = str(match.group(1) or "").strip()
            if not name or name in context or name in self._extra_builtins:
                continue
            context[name] = self.namespace(name)

    def _load(self, name: str) -> _LoadedCommonModule | None:
        key = str(name or "").strip().casefold()
        cached = self._modules.get(key)
        if cached is not None:
            return cached
        if key in self._missing_modules:
            return None

        descriptor = self._resolver(str(name or "").strip())
        if not isinstance(descriptor, dict) or not descriptor:
            self._missing_modules.add(key)
            return None
        module_guid = str(descriptor.get("module_guid") or "").strip()
        source = str(descriptor.get("text") or "")
        if not module_guid or not source.strip():
            raise MsException(f"Common module '{name}' has no executable source")
        language = str(descriptor.get("lang") or "uk").strip().lower() or "uk"
        if language not in {"uk", "en"}:
            language = "uk"
        program, diagnostics = parse(source, get_profile(language))
        errors = [item for item in diagnostics if item.severity == "error"]
        if program is None or errors:
            first = errors[0] if errors else None
            detail = (
                f"L{first.span.line}:{first.span.col} {first.message}"
                if first is not None
                else "unknown parser error"
            )
            raise MsException(f"Common module '{name}' cannot be compiled: {detail}")

        module_id = f"module://{module_guid}"
        module = compile_module(program, module_name=module_id)
        module_context = dict(self._shared_context)
        self_namespace = self.namespace(name)
        module_context.setdefault("ЭтотОбъект", self_namespace)
        module_context.setdefault("ЦейОбєкт", self_namespace)
        module_context.setdefault("ThisObject", self_namespace)
        self.install_source_names(module_context, source)
        vm = VM(
            module=module,
            extra_builtins=self._extra_builtins,
            initial_globals=module_context,
            debugger=self._debug_session,
            module_name=module_id,
        )
        loaded = _LoadedCommonModule(str(name or ""), module_id, vm)
        self._modules[key] = loaded
        vm.initialize()
        return loaded

    @staticmethod
    def _exported_member(loaded: _LoadedCommonModule, member: str) -> tuple[str, CodeObject] | None:
        targets = set(get_identifier_alias_keys(member, "methods"))
        module = loaded.vm._module
        if module is None:
            return None
        for actual, code in {**module.procedures, **module.functions}.items():
            if actual.casefold() in targets and bool(code.exported):
                return actual, code
        return None

    def call(self, module_name: str, member: str, args: list[Any]) -> Any:
        loaded = self._load(module_name)
        if loaded is None:
            return _MissingRuntimeValue()
        resolved = self._exported_member(loaded, member)
        if resolved is None:
            raise MsException(
                f"Exported function/procedure '{module_name}.{member}' was not found"
            )
        actual, _code = resolved
        try:
            return loaded.vm.call(actual, *list(args or []))
        except MsException as exc:
            module_id = str(getattr(exc, "module_id", "") or loaded.module_id)
            procedure = str(getattr(exc, "procedure", "") or actual)
            line = int(getattr(exc, "line", 0) or 0)
            message = str(exc)
            if " at module://" not in message:
                message = f"{message} at {module_id}:{procedure}:L{line}"
            wrapped = MsException(message, getattr(exc, "DetailedDescription", ""))
            wrapped.module_id = module_id
            wrapped.procedure = procedure
            wrapped.line = line
            raise wrapped from exc


__all__ = ["CommonModuleNamespace", "CommonModuleRegistry"]
