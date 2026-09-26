"""Strict, lazy common-module execution scoped to one posting transaction."""
from __future__ import annotations

from src.dsl.vm import MsException
from .posting_script import Namespace, PostingError, PostingMethod, PostingVM, compile_posting_source


def _technical_aliases(row):
    payload = row.get("payload") or {}
    values = [row.get("name"), payload.get("source_name"), payload.get("metadata_ref")]
    for key in ("localized_names", "code_refs", "legacy_code_refs"):
        aliases = payload.get(key)
        if isinstance(aliases, dict):
            values.extend(aliases.values())
        elif isinstance(aliases, list):
            values.extend(aliases)
    result = set()
    for value in values:
        if not isinstance(value, str):
            continue
        parts = value.strip().split(".")
        if len(parts) > 1 and parts[-1].casefold() == "module":
            parts.pop()
        leaf = parts[-1]
        if leaf.isidentifier():
            result.add(leaf.casefold())
    return result


class _ModuleNamespace(Namespace):
    def __init__(self, registry, row):
        object.__setattr__(self, "_registry", registry)
        object.__setattr__(self, "_row", row)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise PostingError("Internal common-module attributes are unavailable")
        return self._registry.member(self._row, name)


class _RegistryNamespace(Namespace):
    def __init__(self, registry):
        object.__setattr__(self, "_registry", registry)

    def __getattr__(self, name):
        return self._registry.namespace(name, allow_namespace=False)


class PostingModuleRegistry:
    def __init__(self, rows, *, modules, source, budget, context):
        self._aliases = {}
        for row in rows:
            if row.get("type") != "common_module" or row.get("kind", "object") != "object":
                continue
            for alias in _technical_aliases(row):
                self._aliases.setdefault(alias, []).append(row)
        self._modules, self._source = modules, source
        self._budget, self._context = budget, context
        self._loaded = {}
        self._loading = set()

    @property
    def budget(self):
        return self._budget

    def namespace(self, name, *, allow_namespace=True):
        matches = self._aliases.get(name.casefold(), [])
        if allow_namespace and name.casefold() in {"commonmodule", "загальниймодуль"}:
            if matches:
                raise PostingError(f"Common module conflicts with a reserved namespace: {name}")
            return _RegistryNamespace(self)
        if not matches:
            raise PostingError(f"Name '{name}' is not defined: common module not found")
        if len(matches) != 1:
            raise PostingError(f"Ambiguous common module: {name}")
        return _ModuleNamespace(self, matches[0])

    def _load(self, row):
        guid = row.get("guid")
        if not guid:
            raise PostingError("Common module has no metadata GUID")
        if guid in self._loading:
            raise PostingError(f"Cyclic common-module initialization: {row['name']}")
        if guid in self._loaded:
            return self._loaded[guid]
        if (row.get("payload") or {}).get("server") is not True:
            raise PostingError(f"Common module is not enabled for Server: {row['name']}")
        if len(self._loaded) + len(self._loading) >= self._budget.max_modules:
            raise PostingError("Posting execution limit exceeded: common modules")
        matches = [module for module in self._modules(guid)
                   if str(module.get("module_kind") or "").casefold() == "module"]
        if len(matches) != 1 or not matches[0].get("module_guid"):
            raise PostingError(f"Exactly one saved Module is required for common module: {row['name']}")
        module_guid = matches[0]["module_guid"]
        self._loading.add(guid)
        try:
            code, required = compile_posting_source(self._source(matches[0]), module_guid=module_guid,
                                                    budget=self._budget)
            vm = PostingVM(code, initial_globals=self._context, budget=self._budget, registry=self)
            vm.initialize()
            self._loaded[guid] = (vm, code, required)
            return self._loaded[guid]
        except Exception as exc:
            raise PostingError(f"Common module {row['name']} (module://{module_guid}): {exc}") from exc
        finally:
            self._loading.remove(guid)

    def member(self, row, name):
        vm, module, required = self._load(row)
        matches = [code for key, code in {**module.procedures, **module.functions}.items()
                   if key.casefold() == name.casefold() and code.exported]
        if len(matches) != 1:
            raise PostingError(f"Exported member not found: {row['name']}.{name}")
        code = matches[0]

        def invoke(args):
            if not required[code.name] <= len(args) <= len(code.params):
                raise PostingError(f"Invalid argument count: {row['name']}.{code.name}")
            try:
                return vm._exec_code(code, args)
            except MsException as exc:
                if not getattr(exc, "posting_location_added", False):
                    exc.args = (f"{exc.module_id or module.name}:{exc.procedure or code.name}:"
                                f"L{exc.line}: {exc}",)
                    exc.Description = str(exc)
                    exc.posting_location_added = True
                raise
        return PostingMethod(invoke)
