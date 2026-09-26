from __future__ import annotations

"""Workspace-wide semantic index for persisted MetaScript modules.

The index is UI-independent. Runtime builds it from its hydrated module source
cache and the current manifest, then serves compact definition, references and
completion responses to IDE clients.
"""

from dataclasses import dataclass
from bisect import bisect_right
from difflib import get_close_matches
import hashlib
import re
from typing import Any, Iterable, Mapping

from src.dsl.languages import get_identifier_alias_keys, get_profile
from src.dsl.module_introspection import repair_cp1251_mojibake_name, symbol_aliases
from src.dsl.parser import parse


_QUALIFIED_NAME_RE = re.compile(
    r"(?<![\w.])([^\W\d]\w*)\s*\.\s*([^\W\d]\w*)",
    flags=re.UNICODE,
)
_SOURCE_VAR_DECL_RE = re.compile(
    r"(?im)^[ \t]*(?:змін|перем|var)\b(?P<body>[^;\r\n]*)"
)
_SOURCE_ASSIGNMENT_RE = re.compile(
    r"(?im)(?<![\w.])(?P<name>[^\W\d]\w*)[ \t]*(?::=|=)"
)
_SOURCE_FOR_VAR_RE = re.compile(
    r"(?im)^[ \t]*(?:для|for)[ \t]+"
    r"(?:(?:каждого|кожного|each)[ \t]+)?(?P<name>[^\W\d]\w*)"
)
_UNQUALIFIED_CALL_RE = re.compile(
    r"(?<![\w.])([^\W\d]\w*)\s*\(",
    flags=re.UNICODE,
)
_OBJECT_ROOTS = {"object", "объект", "обєкт"}

# Facade namespaces used by the imported 1C/BAS configuration.  Their
# exported APIs can be split into client/server modules; ordinary misspelled
# module references must remain visible as Problems.
_ONEC_COMPATIBILITY_QUALIFIERS = {
    "общегоназначения", "общегоназначенияклиентсервер",
    "стандартныеподсистемыповтисп", "контактнаяинформацияклиентсерверповтисп",
    "регламентированнаяотчетностьклиентсервер", "регламентированнаяотчетность",
    "контактнаяинформацияслужебный", "денежныесредствасервер", "финансыклиент",
    "продажисервер", "закупкиклиент", "запасысервер",
    "обработкатабличнойчастиклиент", "вариантыотчетов",
    "управлениеконтактнойинформацией", "контактнаяинформация",
}

# Exact aliases observed in the imported 1C/BAS source.  These are kept
# explicit: a fuzzy member match would hide genuinely missing APIs.
_ONEC_COMPATIBILITY_MEMBER_ALIASES = {
    ("общегоназначения", "сообщитьпользователю"):
        ("ОбщегоНазначенияКлиентСервер", "СообщитьПользователю"),
    ("контактнаяинформацияклиентсерверповтисп", "типыобъектовадресацииадресарф"):
        ("КонтактнаяИнформацияКлиентСерверПовтИсп", "ТипыОбъектовАдресацииАдреса"),
    ("регламентированнаяотчетностьклиентсервер", "сформироватьструктурупараметровфайлавыгрузки"):
        ("РегламентированнаяОтчетность", "СформироватьСтруктуруПараметровФайлаВыгрузкиНаСервере"),
    ("финансыклиент", "пересчетсуммывстрокерасшифровкиплатежа"):
        ("ФинансыКлиент", "ПересчитатьСуммыВСтрокеРасшифровкиПлатежа"),
    ("управлениеконтактнойинформацией", "преобразоватьстрокувсписокполей"):
        ("УправлениеКонтактнойИнформациейКлиентСервер", "ПреобразоватьСтрокуВСписокПолей"),
}

# Some BAS/1C configurations call platform or library APIs that are not
# exported by the supplied XML dump.  They are not safe to resolve to a random
# same-named procedure: doing so would make navigation look correct while
# changing runtime semantics.  Keep these calls visible as source gaps rather
# than reporting them as broken imported references.
_ONEC_EXTERNAL_SOURCE_APIS = {
    ("стандартныеподсистемыповтисп", "этофоновоезадание"),
    ("общегоназначения", "вызватьфункциюконфигурации"),
    ("общегоназначения", "вызватьфункциюобъекта"),
    ("регламентированнаяотчетность", "получитьназваниерегионапокоду"),
    ("контактнаяинформацияслужебный", "российскийадрес"),
    ("контактнаяинформацияслужебный", "этороссийскийадрес"),
    ("денежныесредствасервер", "получитьвалютупономерусчета"),
    ("контактнаяинформация", "загрузить"),
    ("контактнаяинформация", "выгрузить"),
    ("продажисервер", "получитьответственногопоскладу"),
    ("закупкиклиент", "обработкавыборадоговораконтрагента"),
    ("общегоназначения", "выполнитьдвижениепорегистру"),
    ("вариантыотчетов", "установитьописаниевариантавдопнастройках"),
}


def _display_name(value: str) -> str:
    text = str(value or "")
    return repair_cp1251_mojibake_name(text) or text


def _display_candidate(value: str) -> str:
    return ".".join(_display_name(part) for part in str(value or "").split("."))


def _similar_name_pool(
    target: str,
    candidates: Mapping[str, Any],
) -> list[str]:
    if not target:
        return []
    max_delta = max(2, len(target) // 5)
    first = target[:1]
    return [
        name
        for name in candidates
        if name[:1] == first and abs(len(name) - len(target)) <= max_delta
    ]


def _mask_non_code(source: str) -> str:
    """Replace comments and string contents while preserving source offsets."""
    text = str(source or "")
    out = list(text)
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] not in "\r\n":
                out[index] = " "
                index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            out[index] = " "
            out[index + 1] = " "
            index += 2
            while index < length:
                if text[index] == "*" and index + 1 < length and text[index + 1] == "/":
                    out[index] = " "
                    out[index + 1] = " "
                    index += 2
                    break
                if text[index] not in "\r\n":
                    out[index] = " "
                index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            out[index] = " "
            index += 1
            while index < length:
                current = text[index]
                if current == quote:
                    out[index] = " "
                    if index + 1 < length and text[index + 1] == quote:
                        out[index + 1] = " "
                        index += 2
                        continue
                    index += 1
                    break
                if current not in "\r\n":
                    out[index] = " "
                index += 1
            continue
        index += 1
    return "".join(out)


def _line_starts(source: str) -> list[int]:
    return [0, *(match.end() for match in re.finditer(r"\n", source))]


def _line_col(starts: list[int], position: int) -> tuple[int, int]:
    line_index = max(0, bisect_right(starts, max(0, int(position))) - 1)
    return line_index + 1, max(0, int(position)) - starts[line_index] + 1


def workspace_symbol_id(module_guid: str, kind: str, name: str) -> str:
    identity = (
        f"{str(module_guid or '').strip()}\0"
        f"{str(kind or '').strip().casefold()}\0"
        f"{str(name or '').strip().casefold()}"
    )
    return f"symbol:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class WorkspaceModule:
    module_guid: str
    owner_guid: str
    module_kind: str
    owner_name: str = ""
    owner_title: str = ""
    owner_type: str = ""
    metadata_ref: str = ""
    aliases: tuple[str, ...] = ()
    semantic_members: tuple[str, ...] = ()
    semantic_schema_complete: bool = False

    @property
    def title(self) -> str:
        return self.owner_title or self.owner_name or self.module_kind or self.module_guid


@dataclass(frozen=True, slots=True)
class WorkspaceSymbol:
    name: str
    kind: str
    module_guid: str
    owner_guid: str
    line: int = 0
    col: int = 0
    exported: bool = False
    params: tuple[str, ...] = ()

    @property
    def symbol_id(self) -> str:
        return workspace_symbol_id(self.module_guid, self.kind, self.name)

    def as_dict(self, module: WorkspaceModule) -> dict[str, Any]:
        return {
            "symbol_id": self.symbol_id,
            "name": self.name,
            "kind": self.kind,
            "module_guid": self.module_guid,
            "owner_guid": self.owner_guid,
            "owner_name": module.owner_name,
            "owner_title": module.owner_title,
            "owner_type": module.owner_type,
            "module_kind": module.module_kind,
            "line": int(self.line or 0),
            "col": int(self.col or 0),
            "params": list(self.params),
            "exported": bool(self.exported),
        }


@dataclass(frozen=True, slots=True)
class WorkspaceReference:
    target_symbol_id: str
    qualifier: str
    name: str
    module_guid: str
    owner_guid: str
    line: int
    col: int
    preview: str
    declaration: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_symbol_id": self.target_symbol_id,
            "qualifier": self.qualifier,
            "name": self.name,
            "module_guid": self.module_guid,
            "owner_guid": self.owner_guid,
            "line": int(self.line or 0),
            "col": int(self.col or 0),
            "preview": self.preview,
            "declaration": bool(self.declaration),
        }


@dataclass(frozen=True, slots=True)
class WorkspaceDiagnostic:
    code: str
    severity: str
    message: str
    module_guid: str
    owner_guid: str
    line: int = 0
    col: int = 0
    qualifier: str = ""
    name: str = ""
    candidates: tuple[str, ...] = ()
    unknown_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "module_guid": self.module_guid,
            "owner_guid": self.owner_guid,
            "line": int(self.line or 0),
            "col": int(self.col or 0),
            "qualifier": _display_name(self.qualifier),
            "name": _display_name(self.name),
            "candidates": [_display_candidate(item) for item in self.candidates],
            "unknown_count": int(self.unknown_count or 0),
        }


class WorkspaceSemanticIndex:
    def __init__(
        self,
        *,
        modules: Iterable[WorkspaceModule],
        symbols: Iterable[WorkspaceSymbol],
        references: Iterable[WorkspaceReference],
        diagnostics: Iterable[WorkspaceDiagnostic] = (),
    ) -> None:
        self.generation = 0
        self.modules = tuple(modules)
        self.symbols = tuple(symbols)
        self.references = tuple(references)
        self.diagnostics = tuple(diagnostics)
        self.form_shadow_diagnostics_filtered = 0
        self.source_gap_diagnostics = sum(
            1 for item in self.diagnostics if item.code == "source_gap"
        )
        self._module_by_guid = {item.module_guid: item for item in self.modules}
        self._module_by_alias: dict[str, WorkspaceModule] = {}
        self._ambiguous_aliases: set[str] = set()
        self._modules_by_alias: dict[str, list[WorkspaceModule]] = {}
        self._alias_display: dict[str, str] = {}
        self._aliases_by_shape: dict[tuple[str, int], list[str]] = {}
        for module in self.modules:
            for alias in module.aliases:
                key = alias.casefold()
                self._alias_display.setdefault(key, alias)
                self._aliases_by_shape.setdefault((key[:1], len(key)), []).append(key)
                candidates = self._modules_by_alias.setdefault(key, [])
                if all(item.module_guid != module.module_guid for item in candidates):
                    candidates.append(module)
                existing = self._module_by_alias.get(key)
                if existing is not None and existing.module_guid != module.module_guid:
                    self._module_by_alias.pop(key, None)
                    self._ambiguous_aliases.add(key)
                    continue
                if key not in self._ambiguous_aliases:
                    self._module_by_alias.setdefault(key, module)
        self._symbol_by_module_name: dict[tuple[str, str], WorkspaceSymbol] = {}
        for symbol in self.symbols:
            self._symbol_by_module_name.setdefault(
                (symbol.module_guid, symbol.name.casefold()),
                symbol,
            )
        for symbol in self.symbols:
            alias_keys = {
                *get_identifier_alias_keys(symbol.name, "callables"),
                *get_identifier_alias_keys(symbol.name, "methods"),
            }
            for alias_key in alias_keys:
                self._symbol_by_module_name.setdefault(
                    (symbol.module_guid, alias_key),
                    symbol,
                )
        self._symbols_by_module: dict[str, list[WorkspaceSymbol]] = {}
        for symbol in self.symbols:
            self._symbols_by_module.setdefault(symbol.module_guid, []).append(symbol)
        self._local_suggestion_cache: dict[tuple[str, str], tuple[str, ...]] = {}
        self._module_suggestion_cache: dict[str, tuple[str, ...]] = {}
        self._export_suggestion_cache: dict[tuple[str, str], tuple[str, ...]] = {}
        self._export_location_cache: dict[tuple[str, str], tuple[str, ...]] = {}
        self._member_suggestion_cache: dict[tuple[str, str], tuple[str, ...]] = {}

    def module_for_qualifier(self, qualifier: str) -> WorkspaceModule | None:
        return self._module_by_alias.get(str(qualifier or "").strip().casefold())

    def ambiguous_modules_for_qualifier(
        self,
        qualifier: str,
    ) -> tuple[WorkspaceModule, ...]:
        key = str(qualifier or "").strip().casefold()
        if key not in self._ambiguous_aliases:
            return ()
        return tuple(self._modules_by_alias.get(key) or ())

    def resolve(self, qualifier: str, name: str) -> tuple[WorkspaceModule, WorkspaceSymbol] | None:
        module = self.module_for_qualifier(qualifier)
        if module is None:
            return None
        symbol = self._symbol_by_module_name.get(
            (module.module_guid, str(name or "").strip().casefold())
        )
        if symbol is None or not symbol.exported:
            return None
        return module, symbol

    def resolve_compatibility_alias(
        self,
        qualifier: str,
        name: str,
    ) -> tuple[WorkspaceModule, WorkspaceSymbol] | None:
        """Resolve a unique exported member after a 1C module split."""
        qualifier_key = str(qualifier or "").strip().casefold()
        name_key = str(name or "").strip().casefold()
        explicit = _ONEC_COMPATIBILITY_MEMBER_ALIASES.get((qualifier_key, name_key))
        if explicit is not None:
            target = self.resolve(*explicit)
            if target is not None:
                return target

        direct = self.resolve(qualifier, name)
        if direct is not None or self.ambiguous_modules_for_qualifier(qualifier):
            return direct
        if qualifier_key not in _ONEC_COMPATIBILITY_QUALIFIERS:
            return None
        module = self.module_for_qualifier(qualifier)
        locations = self.exported_member_locations(
            name,
            exclude_module_guid=module.module_guid if module is not None else "",
            limit=100,
        )
        if len(locations) != 1:
            return None
        target_qualifier, separator, target_name = locations[0].rpartition(".")
        if not separator or target_name.casefold() != str(name).strip().casefold():
            return None
        return self.resolve(target_qualifier, target_name)

    def local_callable(self, module_guid: str, name: str) -> WorkspaceSymbol | None:
        symbol = self._symbol_by_module_name.get(
            (
                str(module_guid or "").strip(),
                str(name or "").strip().casefold(),
            )
        )
        if symbol is None or symbol.kind not in {"procedure", "function"}:
            return None
        return symbol

    def local_callable_suggestions(
        self,
        module_guid: str,
        name: str,
        *,
        limit: int = 3,
    ) -> tuple[str, ...]:
        cache_key = (
            str(module_guid or "").strip(),
            str(name or "").strip().casefold(),
        )
        cached = self._local_suggestion_cache.get(cache_key)
        if cached is not None:
            return cached
        candidates = {
            symbol.name.casefold(): symbol.name
            for symbol in self._symbols_by_module.get(str(module_guid or "").strip(), ())
            if symbol.kind in {"procedure", "function"}
        }
        target = cache_key[1]
        pool = _similar_name_pool(target, candidates)
        matches = get_close_matches(
            target,
            pool,
            n=max(1, int(limit or 3)),
            cutoff=0.82,
        )
        result = tuple(candidates[item] for item in matches)
        self._local_suggestion_cache[cache_key] = result
        return result

    def module_alias_suggestions(
        self,
        qualifier: str,
        *,
        limit: int = 3,
    ) -> tuple[str, ...]:
        target = str(qualifier or "").strip().casefold()
        cached = self._module_suggestion_cache.get(target)
        if cached is not None:
            return cached
        aliases = self._alias_display
        max_delta = max(2, len(target) // 5)
        pool: list[str] = []
        for length in range(
            max(0, len(target) - max_delta),
            len(target) + max_delta + 1,
        ):
            pool.extend(self._aliases_by_shape.get((target[:1], length), ()))
        matches = get_close_matches(
            target,
            pool,
            n=max(1, int(limit or 3)),
            cutoff=0.86,
        )
        result = tuple(aliases[item] for item in matches)
        self._module_suggestion_cache[target] = result
        return result

    def exported_member_suggestions(
        self,
        qualifier: str,
        name: str,
        *,
        limit: int = 3,
    ) -> tuple[str, ...]:
        module = self.module_for_qualifier(qualifier)
        if module is None:
            return ()
        cache_key = (module.module_guid, str(name or "").strip().casefold())
        cached = self._export_suggestion_cache.get(cache_key)
        if cached is not None:
            return cached
        candidates = {
            symbol.name.casefold(): symbol.name
            for symbol in self._symbols_by_module.get(module.module_guid, ())
            if symbol.exported and symbol.kind in {"procedure", "function"}
        }
        target = cache_key[1]
        matches = get_close_matches(
            target,
            _similar_name_pool(target, candidates),
            n=max(1, int(limit or 3)),
            cutoff=0.82,
        )
        result = tuple(candidates[item] for item in matches)
        self._export_suggestion_cache[cache_key] = result
        return result

    def exported_member_locations(
        self,
        name: str,
        *,
        exclude_module_guid: str = "",
        limit: int = 5,
    ) -> tuple[str, ...]:
        """Return exact exported declarations from other module namespaces."""

        lookup_keys = {
            *get_identifier_alias_keys(name, "callables"),
            *get_identifier_alias_keys(name, "methods"),
        }
        cache_key = (
            str(exclude_module_guid or "").strip(),
            "|".join(sorted(lookup_keys)),
        )
        cached = self._export_location_cache.get(cache_key)
        if cached is not None:
            return cached
        result: list[str] = []
        for symbol in self.symbols:
            if (
                not symbol.exported
                or symbol.kind not in {"procedure", "function"}
                or symbol.module_guid == cache_key[0]
            ):
                continue
            symbol_keys = {
                *get_identifier_alias_keys(symbol.name, "callables"),
                *get_identifier_alias_keys(symbol.name, "methods"),
            }
            if not lookup_keys.intersection(symbol_keys):
                continue
            module = self._module_by_guid.get(symbol.module_guid)
            if module is None:
                continue
            qualifier = (
                module.owner_name
                or next(iter(module.aliases), "")
                or module.title
            )
            location = f"{qualifier}.{symbol.name}"
            if location not in result:
                result.append(location)
            if len(result) >= max(1, int(limit or 5)):
                break
        cached_result = tuple(result)
        self._export_location_cache[cache_key] = cached_result
        return cached_result

    def semantic_member_suggestions(
        self,
        module_guid: str,
        name: str,
        *,
        limit: int = 3,
    ) -> tuple[str, ...]:
        module = self._module_by_guid.get(str(module_guid or "").strip())
        if module is None:
            return ()
        cache_key = (module.module_guid, str(name or "").strip().casefold())
        cached = self._member_suggestion_cache.get(cache_key)
        if cached is not None:
            return cached
        candidates = {
            item.casefold(): item
            for item in module.semantic_members
            if item
        }
        target = cache_key[1]
        matches = get_close_matches(
            target,
            _similar_name_pool(target, candidates),
            n=max(1, int(limit or 3)),
            cutoff=0.78,
        )
        result = tuple(candidates[item] for item in matches)
        self._member_suggestion_cache[cache_key] = result
        return result

    def exported_members(self, qualifier: str) -> list[dict[str, Any]]:
        module = self.module_for_qualifier(qualifier)
        if module is None:
            return []
        members = [
            symbol.as_dict(module)
            for symbol in self.symbols
            if symbol.module_guid == module.module_guid
            and symbol.exported
            and symbol.kind in {"procedure", "function"}
        ]
        members.sort(key=lambda item: str(item.get("name") or "").casefold())
        return members

    def find_references(
        self,
        qualifier: str,
        name: str,
        *,
        limit: int = 500,
        include_declaration: bool = True,
    ) -> list[dict[str, Any]]:
        resolved = self.resolve(qualifier, name)
        if resolved is None:
            return []
        module, symbol = resolved
        result: list[dict[str, Any]] = []
        if include_declaration:
            declaration = WorkspaceReference(
                    target_symbol_id=symbol.symbol_id,
                    qualifier=qualifier,
                    name=symbol.name,
                    module_guid=symbol.module_guid,
                    owner_guid=symbol.owner_guid,
                    line=symbol.line,
                    col=symbol.col,
                    preview="",
                    declaration=True,
                ).as_dict()
            declaration.update(
                {
                    "module_kind": module.module_kind,
                    "owner_name": module.owner_name,
                    "owner_title": module.owner_title,
                }
            )
            result.append(declaration)
        target_symbol_id = symbol.symbol_id
        for reference in self.references:
            if reference.target_symbol_id != target_symbol_id:
                continue
            item = reference.as_dict()
            source_module = self._module_by_guid.get(reference.module_guid)
            if source_module is not None:
                item.update(
                    {
                        "module_kind": source_module.module_kind,
                        "owner_name": source_module.owner_name,
                        "owner_title": source_module.owner_title,
                    }
                )
            result.append(item)
            if len(result) >= max(1, int(limit or 500)):
                break
        return result[: max(1, int(limit or 500))]

    def list_diagnostics(
        self,
        *,
        module_guid: str = "",
        code: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        module_filter = str(module_guid or "").strip()
        code_filter = str(code or "").strip().casefold()
        result: list[dict[str, Any]] = []
        for diagnostic in self.diagnostics:
            if module_filter and diagnostic.module_guid != module_filter:
                continue
            if code_filter and diagnostic.code.casefold() != code_filter:
                continue
            item = diagnostic.as_dict()
            source_module = self._module_by_guid.get(diagnostic.module_guid)
            if source_module is not None:
                item.update(
                    {
                        "module_kind": source_module.module_kind,
                        "owner_name": source_module.owner_name,
                        "owner_title": source_module.owner_title,
                    }
                )
            result.append(item)
            if len(result) >= max(1, int(limit or 500)):
                break
        return result

    def stats(self) -> dict[str, int]:
        diagnostic_codes = [item.code for item in self.diagnostics]
        return {
            "modules": len(self.modules),
            "symbols": len(self.symbols),
            "exported_symbols": sum(1 for item in self.symbols if item.exported),
            "references": len(self.references),
            "ambiguous_aliases": len(self._ambiguous_aliases),
            "diagnostics": len(self.diagnostics),
            "unresolved_references": diagnostic_codes.count("unresolved_member"),
            "unresolved_modules": diagnostic_codes.count("unresolved_module"),
            "unresolved_callables": diagnostic_codes.count("unresolved_callable"),
            "unresolved_requisites": diagnostic_codes.count("unresolved_requisite"),
            "source_gaps": diagnostic_codes.count("source_gap"),
            "ambiguous_references": diagnostic_codes.count("ambiguous_qualifier"),
            "form_shadow_diagnostics_filtered": int(
                self.form_shadow_diagnostics_filtered
            ),
            "partial_modules": len(
                {
                    item.module_guid
                    for item in self.diagnostics
                    if item.code in {"lexer_failed", "lexer_partial"}
                }
            ),
        }


def _aliases_for_module(owner: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[str, ...]:
    payload = owner.get("payload") if isinstance(owner.get("payload"), dict) else {}
    metadata_ref = str(payload.get("metadata_ref") or "").strip()
    values = [
        str(owner.get("name") or "").strip(),
        str(owner.get("title") or "").strip(),
        str(payload.get("source_name") or "").strip(),
        metadata_ref,
        metadata_ref.rsplit(".", 1)[-1],
        str(row.get("name") or "").strip(),
        str(row.get("canonical_ref") or "").strip(),
        str(row.get("ref_uk") or "").strip(),
        str(row.get("ref_en") or "").strip(),
    ]
    for key in ("localized_names", "code_refs", "legacy_code_refs"):
        aliases = payload.get(key)
        if isinstance(aliases, dict):
            values.extend(str(value or "").strip() for value in aliases.values())
        elif isinstance(aliases, (list, tuple, set)):
            values.extend(str(value or "").strip() for value in aliases)
    aliases: list[str] = []
    for value in values:
        if not value:
            continue
        aliases.append(value)
        aliases.extend(symbol_aliases(value))
        ref_parts = [part for part in value.split(".") if part]
        if len(ref_parts) >= 3:
            owner_ref = ".".join(ref_parts[:-1])
            aliases.extend((owner_ref, ref_parts[-2]))
            aliases.extend(symbol_aliases(ref_parts[-2]))
    return tuple(dict.fromkeys(alias for alias in aliases if alias))


_SEMANTIC_SCHEMA_KEYS = (
    "requisites",
    "attributes",
    "dimensions",
    "resources",
    "tabular_parts",
)


def _schema_owner(
    owner: Mapping[str, Any],
    owners: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    current = owner
    visited: set[str] = set()
    for _ in range(4):
        current_type = str(current.get("type") or "").strip().lower()
        payload = (
            current.get("payload")
            if isinstance(current.get("payload"), dict)
            else {}
        )
        if current_type not in {"form", "common_form", "folder", "forms_folder"}:
            return current
        candidate_guid = str(
            payload.get("owner_guid")
            or current.get("parent_guid")
            or ""
        ).strip()
        if not candidate_guid or candidate_guid in visited:
            return current
        visited.add(candidate_guid)
        candidate = owners.get(candidate_guid)
        if not isinstance(candidate, Mapping):
            return current
        current = candidate
    return current


def _semantic_members_for_owner(
    owner: Mapping[str, Any],
    owners: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[str, ...], bool]:
    owner_payload = (
        owner.get("payload")
        if isinstance(owner.get("payload"), dict)
        else {}
    )
    target = _schema_owner(owner, owners)
    payload = (
        target.get("payload")
        if isinstance(target.get("payload"), dict)
        else {}
    )
    complete = any(isinstance(payload.get(key), list) for key in _SEMANTIC_SCHEMA_KEYS)
    members: list[str] = []
    for key in _SEMANTIC_SCHEMA_KEYS:
        for item in payload.get(key) or ():
            if not isinstance(item, Mapping):
                continue
            name = str(
                item.get("name")
                or item.get("Name")
                or item.get("title")
                or ""
            ).strip()
            if name:
                members.append(name)
    members.extend(form_semantic_member_names(owner_payload))
    return tuple(dict.fromkeys(members)), complete


def form_semantic_member_names(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Collect form element names and bindings that can shadow module aliases."""

    form_model = payload.get("form_model")
    if not isinstance(form_model, Mapping):
        return ()
    root = form_model.get("root")
    if not isinstance(root, Mapping):
        return ()
    result: list[str] = []
    pending = [root]
    while pending:
        node = pending.pop()
        for key in ("name", "binding"):
            value = str(node.get(key) or "").strip()
            if value:
                result.append(value)
        props = node.get("props") if isinstance(node.get("props"), Mapping) else {}
        for column in props.get("columns") or ():
            if not isinstance(column, Mapping):
                continue
            for key in ("name", "binding"):
                value = str(column.get(key) or "").strip()
                if value:
                    result.append(value)
        pending.extend(
            child
            for child in node.get("children") or ()
            if isinstance(child, Mapping)
        )
    return tuple(dict.fromkeys(result))


def filter_form_shadow_diagnostics(
    index: WorkspaceSemanticIndex,
    payloads_by_owner_guid: Mapping[str, Mapping[str, Any]],
) -> WorkspaceSemanticIndex:
    """Drop namespace diagnostics proven to target a form member."""

    form_members = {
        str(owner_guid): {
            name.casefold()
            for name in form_semantic_member_names(payload)
        }
        for owner_guid, payload in payloads_by_owner_guid.items()
        if isinstance(payload, Mapping)
    }
    diagnostics = tuple(
        diagnostic
        for diagnostic in index.diagnostics
        if not (
            diagnostic.code in {"unresolved_member", "unresolved_module"}
            and diagnostic.qualifier.casefold()
            in form_members.get(diagnostic.owner_guid, set())
        )
    )
    if len(diagnostics) == len(index.diagnostics):
        return index
    filtered = WorkspaceSemanticIndex(
        modules=index.modules,
        symbols=index.symbols,
        references=index.references,
        diagnostics=diagnostics,
    )
    filtered.form_shadow_diagnostics_filtered = (
        int(getattr(index, "form_shadow_diagnostics_filtered", 0))
        + len(index.diagnostics)
        - len(diagnostics)
    )
    return filtered


def _is_name_token(token: Any) -> bool:
    return bool(token) and (
        str(getattr(token, "type", "")) == "IDENT"
        or bool(getattr(token, "is_keyword", lambda: False)())
    )


def _callable_symbols_from_tokens(
    tokens: list[Any],
    *,
    module: WorkspaceModule,
) -> list[WorkspaceSymbol]:
    symbols: list[WorkspaceSymbol] = []
    for index, token in enumerate(tokens):
        token_type = str(getattr(token, "type", ""))
        if token_type not in {"KW_PROCEDURE", "KW_FUNCTION"}:
            continue
        if index + 1 >= len(tokens) or not _is_name_token(tokens[index + 1]):
            continue
        name_token = tokens[index + 1]
        cursor = index + 2
        while cursor < len(tokens) and tokens[cursor].type != "LPAREN":
            cursor += 1
        if cursor >= len(tokens):
            continue
        cursor += 1
        params: list[str] = []
        depth = 1
        while cursor < len(tokens) and depth > 0:
            current = tokens[cursor]
            if current.type == "LPAREN":
                depth += 1
            elif current.type == "RPAREN":
                depth -= 1
                if depth == 0:
                    cursor += 1
                    break
            elif depth == 1 and _is_name_token(current):
                previous_type = tokens[cursor - 1].type if cursor > 0 else ""
                if previous_type in {"LPAREN", "COMMA", "KW_VAL"}:
                    params.append(str(current.text or ""))
            cursor += 1
        exported = cursor < len(tokens) and tokens[cursor].type == "KW_EXPORT"
        symbols.append(
            WorkspaceSymbol(
                name=str(name_token.text or ""),
                kind="procedure" if token_type == "KW_PROCEDURE" else "function",
                module_guid=module.module_guid,
                owner_guid=module.owner_guid,
                line=int(name_token.span.line or 0),
                col=int(name_token.span.col or 0),
                exported=exported,
                params=tuple(dict.fromkeys(params)),
            )
        )
    return symbols


_SOURCE_CALLABLE_RE = re.compile(
    r"(?im)^[ \t]*(?P<kind>"
    r"процедура|procedure|процедура|"
    r"функция|function|функція"
    r")[ \t]+(?P<name>[^\W\d]\w*)[ \t]*\(",
)
_SOURCE_EXPORT_RE = re.compile(r"(?i)\b(?:экспорт|експорт|export)\b")
_SOURCE_PARAM_RE = re.compile(
    r"(?iu)(?:^|,)\s*(?:(?:знач|val)\s+)?(?P<name>[^\W\d]\w*)"
)


def _callable_symbols_from_source(
    source: str,
    *,
    module: WorkspaceModule,
) -> list[WorkspaceSymbol]:
    """Recover declarations even when a legacy module body is not lexable."""
    symbols: list[WorkspaceSymbol] = []
    text = str(source or "")
    for match in _SOURCE_CALLABLE_RE.finditer(text):
        cursor = match.end()
        depth = 1
        quote = ""
        while cursor < len(text) and depth > 0:
            char = text[cursor]
            if quote:
                if char == quote:
                    if cursor + 1 < len(text) and text[cursor + 1] == quote:
                        cursor += 2
                        continue
                    quote = ""
            elif char in {'"', "'"}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            cursor += 1
        if depth != 0:
            continue
        params_text = text[match.end(): cursor - 1]
        line_end = text.find("\n", cursor)
        if line_end < 0:
            line_end = len(text)
        tail = text[cursor:line_end]
        kind_text = str(match.group("kind") or "").casefold()
        line = text.count("\n", 0, match.start("name")) + 1
        line_start = text.rfind("\n", 0, match.start("name")) + 1
        symbols.append(
            WorkspaceSymbol(
                name=str(match.group("name") or ""),
                kind=(
                    "procedure"
                    if kind_text in {"процедура", "procedure"}
                    else "function"
                ),
                module_guid=module.module_guid,
                owner_guid=module.owner_guid,
                line=line,
                col=match.start("name") - line_start + 1,
                exported=bool(_SOURCE_EXPORT_RE.search(tail)),
                params=tuple(
                    dict.fromkeys(
                        param.group("name")
                        for param in _SOURCE_PARAM_RE.finditer(params_text)
                    )
                ),
            )
        )
    return symbols


def _declared_names_from_tokens(tokens: Iterable[Any]) -> set[str]:
    """Collect names that may shadow modules or hold dynamic callables.

    The scan intentionally over-approximates. Suppressing a questionable
    diagnostic is safer than marking a valid dynamic BSL call as an error.
    """
    meaningful = [
        token
        for token in tokens
        if str(getattr(token, "type", "")) != "EOF"
    ]
    names: set[str] = set()
    for index, token in enumerate(meaningful):
        token_type = str(getattr(token, "type", ""))
        if token_type in {"KW_PROCEDURE", "KW_FUNCTION"}:
            cursor = index + 1
            while cursor < len(meaningful) and meaningful[cursor].type != "LPAREN":
                cursor += 1
            cursor += 1
            depth = 1
            while cursor < len(meaningful) and depth > 0:
                current = meaningful[cursor]
                if current.type == "LPAREN":
                    depth += 1
                elif current.type == "RPAREN":
                    depth -= 1
                elif depth == 1 and _is_name_token(current):
                    previous = meaningful[cursor - 1].type if cursor > 0 else ""
                    if previous in {"LPAREN", "COMMA", "KW_VAL"}:
                        names.add(str(current.text or "").casefold())
                cursor += 1
            continue
        if token_type == "KW_VAR":
            cursor = index + 1
            while cursor < len(meaningful):
                current = meaningful[cursor]
                if current.type == "SEMICOLON":
                    break
                if current.type == "IDENT":
                    names.add(str(current.text or "").casefold())
                cursor += 1
            continue
        if token_type == "KW_FOR" and index + 1 < len(meaningful):
            cursor = index + 1
            if meaningful[cursor].type == "KW_EACH":
                cursor += 1
            if cursor < len(meaningful) and meaningful[cursor].type == "IDENT":
                names.add(str(meaningful[cursor].text or "").casefold())
            continue
        if (
            token_type == "IDENT"
            and index + 1 < len(meaningful)
            and meaningful[index + 1].type in {"EQ", "ASSIGN"}
        ):
            names.add(str(token.text or "").casefold())
    return names


def _declared_names_from_source(
    masked_source: str,
    symbols: Iterable[WorkspaceSymbol],
) -> set[str]:
    names = {
        param.casefold()
        for symbol in symbols
        for param in symbol.params
        if param
    }
    for match in _SOURCE_VAR_DECL_RE.finditer(masked_source):
        body = str(match.group("body") or "")
        names.update(
            item.casefold()
            for item in re.findall(r"[^\W\d]\w*", body, flags=re.UNICODE)
            if item.casefold() not in {"export", "експорт", "экспорт"}
        )
    names.update(
        str(match.group("name") or "").casefold()
        for match in _SOURCE_ASSIGNMENT_RE.finditer(masked_source)
    )
    names.update(
        str(match.group("name") or "").casefold()
        for match in _SOURCE_FOR_VAR_RE.finditer(masked_source)
    )
    return names


def _is_unqualified_call(tokens: list[Any], index: int) -> bool:
    if index < 0 or index + 1 >= len(tokens):
        return False
    token = tokens[index]
    if token.type != "IDENT" or tokens[index + 1].type != "LPAREN":
        return False
    previous = tokens[index - 1].type if index > 0 else ""
    return previous not in {
        "DOT",
        "KW_PROCEDURE",
        "KW_FUNCTION",
        "KW_NEW",
    }


def _strict_semantics_available(source: str, profile: Any) -> bool:
    program, parser_diagnostics = parse(str(source or ""), profile)
    return program is not None and not any(
        str(item.severity or "") == "error"
        for item in parser_diagnostics
    )


def build_workspace_semantic_index(
    sources: Iterable[Mapping[str, Any]],
    *,
    owners_by_guid: Mapping[str, Mapping[str, Any]] | None = None,
) -> WorkspaceSemanticIndex:
    owners = owners_by_guid or {}
    modules: list[WorkspaceModule] = []
    symbols: list[WorkspaceSymbol] = []
    source_records: list[tuple[WorkspaceModule, str]] = []
    diagnostics: list[WorkspaceDiagnostic] = []
    profile = get_profile("mixed")

    for raw in sources:
        row = dict(raw)
        module_guid = str(row.get("module_guid") or "").strip()
        if not module_guid:
            continue
        owner_guid = str(row.get("owner_guid") or "").strip()
        owner = dict(owners.get(owner_guid) or {})
        owner_payload = owner.get("payload") if isinstance(owner.get("payload"), dict) else {}
        owner_type = str(owner.get("type") or "")
        semantic_members, semantic_schema_complete = _semantic_members_for_owner(
            owner,
            owners,
        )
        module = WorkspaceModule(
            module_guid=module_guid,
            owner_guid=owner_guid,
            module_kind=str(row.get("module_kind") or row.get("name") or "module"),
            owner_name=str(owner.get("name") or ""),
            owner_title=str(owner.get("title") or ""),
            owner_type=owner_type,
            metadata_ref=str(owner_payload.get("metadata_ref") or ""),
            aliases=(
                _aliases_for_module(owner, row)
                if owner_type.strip().lower() == "common_module"
                else ()
            ),
            semantic_members=semantic_members,
            semantic_schema_complete=semantic_schema_complete,
        )
        modules.append(module)
        source = str(row.get("source_text") or "")
        source_records.append((module, source))
        recovered_symbols = _callable_symbols_from_source(source, module=module)
        merged_symbols: dict[tuple[str, str], WorkspaceSymbol] = {
            (item.kind, item.name.casefold()): item
            for item in recovered_symbols
        }
        symbols.extend(merged_symbols.values())

    skeleton = WorkspaceSemanticIndex(modules=modules, symbols=symbols, references=())
    from src.dsl.platform_symbols import standard_runtime_names
    from src.dsl.vm import BUILTINS

    known_global_callables = {
        str(name or "").casefold()
        for name in (*BUILTINS, *standard_runtime_names())
        if str(name or "").strip()
    }
    known_global_callables.update(
        symbol.name.casefold()
        for symbol in symbols
        if symbol.exported and symbol.kind in {"procedure", "function"}
    )
    references: list[WorkspaceReference] = []
    for source_module, source in source_records:
        masked_source = _mask_non_code(source)
        module_symbols = skeleton._symbols_by_module.get(
            source_module.module_guid,
            (),
        )
        declared_names = _declared_names_from_source(
            masked_source,
            module_symbols,
        )
        starts = _line_starts(source)
        lines = source.splitlines()
        strict_semantics: bool | None = None

        def can_report_strict_semantics() -> bool:
            nonlocal strict_semantics
            if strict_semantics is None:
                strict_semantics = _strict_semantics_available(source, profile)
            return strict_semantics

        for match in _UNQUALIFIED_CALL_RE.finditer(masked_source):
            cursor = match.start(1) - 1
            while cursor >= 0 and masked_source[cursor].isspace():
                cursor -= 1
            if cursor >= 0 and masked_source[cursor] == ".":
                continue
            name = str(match.group(1) or "")
            if (
                name.casefold() in declared_names
                or name.casefold() in known_global_callables
                or skeleton.local_callable(source_module.module_guid, name) is not None
            ):
                continue
            suggestions = skeleton.local_callable_suggestions(
                source_module.module_guid,
                name,
            )
            if not suggestions:
                continue
            if not can_report_strict_semantics():
                continue
            line, col = _line_col(starts, match.start(1))
            diagnostics.append(
                WorkspaceDiagnostic(
                    code="unresolved_callable",
                    severity="error",
                    message=f"Local procedure or function was not found: {name}",
                    module_guid=source_module.module_guid,
                    owner_guid=source_module.owner_guid,
                    line=line,
                    col=col,
                    name=name,
                    candidates=suggestions,
                )
            )

        known_members = {
            item.casefold()
            for item in source_module.semantic_members
        }
        for match in _QUALIFIED_NAME_RE.finditer(masked_source):
            qualifier = str(match.group(1) or "")
            member = str(match.group(2) or "")
            if qualifier.casefold() in declared_names:
                continue
            cursor = match.end(2)
            while cursor < len(masked_source) and masked_source[cursor].isspace():
                cursor += 1
            is_call = cursor < len(masked_source) and masked_source[cursor] == "("
            line, col = _line_col(starts, match.start(1))
            if (
                source_module.semantic_schema_complete
                and qualifier.casefold() in _OBJECT_ROOTS
                and not is_call
                and member.casefold() not in known_members
            ):
                if can_report_strict_semantics():
                    diagnostics.append(
                        WorkspaceDiagnostic(
                            code="unresolved_requisite",
                            severity="error",
                            message=f"Object requisite was not found: {member}",
                            module_guid=source_module.module_guid,
                            owner_guid=source_module.owner_guid,
                            line=line,
                            col=_line_col(starts, match.start(2))[1],
                            qualifier=qualifier,
                            name=member,
                            candidates=skeleton.semantic_member_suggestions(
                                source_module.module_guid,
                                member,
                            ),
                        )
                    )
                continue
            if not is_call:
                continue
            resolved = skeleton.resolve_compatibility_alias(qualifier, member)
            if resolved is None:
                external_key = (qualifier.casefold(), member.casefold())
                if external_key in _ONEC_EXTERNAL_SOURCE_APIS:
                    diagnostics.append(
                        WorkspaceDiagnostic(
                            code="source_gap",
                            severity="info",
                            message=(
                                "External 1C/BAS API is referenced but its "
                                "implementation is absent from the imported "
                                f"source: {qualifier}.{member}"
                            ),
                            module_guid=source_module.module_guid,
                            owner_guid=source_module.owner_guid,
                            line=line,
                            col=col,
                            qualifier=qualifier,
                            name=member,
                        )
                    )
                    continue
                ambiguous = skeleton.ambiguous_modules_for_qualifier(qualifier)
                known_module = skeleton.module_for_qualifier(qualifier)
                if not ambiguous and known_module is None:
                    suggestions = skeleton.module_alias_suggestions(
                        qualifier
                    )
                    if suggestions:
                        if not can_report_strict_semantics():
                            continue
                        diagnostics.append(
                            WorkspaceDiagnostic(
                                code="unresolved_module",
                                severity="warning",
                                message=(
                                    "Module was not found: "
                                    f"{qualifier}"
                                ),
                                module_guid=source_module.module_guid,
                                owner_guid=source_module.owner_guid,
                                line=line,
                                col=col,
                                qualifier=qualifier,
                                name=member,
                                candidates=suggestions,
                            )
                        )
                    continue
                code = "ambiguous_qualifier" if ambiguous else "unresolved_member"
                candidates = (
                    tuple(item.module_guid for item in ambiguous)
                    if ambiguous
                    else tuple(
                        dict.fromkeys(
                            (
                                *skeleton.exported_member_suggestions(
                                    qualifier,
                                    member,
                                ),
                                *skeleton.exported_member_locations(
                                    member,
                                    exclude_module_guid=known_module.module_guid,
                                ),
                            )
                        )
                    )
                )
                diagnostics.append(
                    WorkspaceDiagnostic(
                        code=code,
                        severity="warning",
                        message=(
                            f"Module qualifier is ambiguous: {qualifier}"
                            if ambiguous
                            else f"Exported member was not found: "
                            f"{qualifier}.{member}"
                        ),
                        module_guid=source_module.module_guid,
                        owner_guid=source_module.owner_guid,
                        line=line,
                        col=col,
                        qualifier=qualifier,
                        name=member,
                        candidates=candidates,
                    )
                )
                continue
            _, target_symbol = resolved
            references.append(
                WorkspaceReference(
                    target_symbol_id=target_symbol.symbol_id,
                    qualifier=qualifier,
                    name=member,
                    module_guid=source_module.module_guid,
                    owner_guid=source_module.owner_guid,
                    line=line,
                    col=col,
                    preview=lines[line - 1].strip() if 0 < line <= len(lines) else "",
                )
            )
    return WorkspaceSemanticIndex(
        modules=modules,
        symbols=symbols,
        references=references,
        diagnostics=diagnostics,
    )
