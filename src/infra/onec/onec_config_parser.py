"""Parser for 1C binary Config format stored in the Config table of 1CD files.

1C stores metadata objects as nested {}-text in Config table BLOBs.
Each metadata object (requisite, tabular part, column, enum value) is encoded as:

    {0,0,<uuid>},"<Name>",{N,"ru","RuName","uk","UkName"},"",0,0}

Followed immediately (for requisites/columns) by a type descriptor:

    {"Pattern", <type_info>}

Where <type_info> is one of:
    {"B"}               -> bool
    {"S"}               -> string (unlimited)
    {"S",N,M}           -> string length N, M=0 fixed / M=1 variable
    {"D"}               -> date only
    {"D","D"}           -> date + time
    {"D","T"}           -> time only
    {"N",digits,frac,sign}  -> number
    {"#",<ref_uuid>}    -> reference to another config object

Tabular parts follow the same header pattern but are NOT followed by {"Pattern",},
instead they have a sub-collection of system fields ({-N}).

Enum values (for enum-family objects) have the header pattern but no Pattern block
and no sub-collection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .onec_requisites_model import (
    OneCEnumValue,
    OneCMetaObject,
    OneCRequisite,
    OneCTabularColumn,
    OneCTabularPart,
)


# ---------------------------------------------------------------------------
# Regex constants
# ---------------------------------------------------------------------------

_GUID_PAT = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_GUID_RE = re.compile(_GUID_PAT, re.IGNORECASE)

# Named object header. Real Config payloads use both {0,0,...} and {1,0,...}.
_HEADER_RE = re.compile(
    r"\{[01],0,(" + _GUID_PAT + r")\}\s*,\s*\"([^\"]+)\"\s*,\s*\{",
    re.IGNORECASE,
)

# Synonym pairs inside the synonyms block
_SYN_PAIR_RE = re.compile(r"\"([a-z]{2,3})\"\s*,\s*\"([^\"]*)\"\s*(?:,|\})")

# Pattern type blocks (whitespace-normalised externally)
_PAT_BOOL_RE = re.compile(r"^\s*\{\"B\"\}\s*$", re.IGNORECASE)
_PAT_STR_RE = re.compile(r'^\s*\{"S"(?:,(\d+),(\d+))?\}\s*$', re.IGNORECASE)
_PAT_DATE_RE = re.compile(r'^\s*\{"D"(?:,"([DT])")?\}\s*$', re.IGNORECASE)
_PAT_NUM_RE = re.compile(r'^\s*\{"N"\s*,(\d+)\s*,(\d+)\s*,(\d+)\}\s*$', re.IGNORECASE)
_PAT_REF_RE = re.compile(
    r'^\s*\{"#"\s*,\s*(' + _GUID_PAT + r')\}\s*$', re.IGNORECASE
)
_PAT_REF_FIND_RE = re.compile(
    r'\{"#"\s*,\s*(' + _GUID_PAT + r')\}', re.IGNORECASE
)

# System field marker: {-N} immediately after named-object header close
_SYSTEM_FIELD_RE = re.compile(r"\{-\d+\}")

_ROOT_TYPE_ALIAS_RE = re.compile(
    r"^\s*\{\d+\s*,\s*\{\d+\s*,(?P<aliases>[^{}]*)\{",
    re.DOTALL,
)

# Pattern presence search: look for {"Pattern", within N chars after object close
_PATTERN_SEARCH_RE = re.compile(r'\{"Pattern"\s*,')

# Tabular-part system field sub-collection
_TABPART_SYSFIELD_RE = re.compile(r"\{1\s*,\s*\{1\s*,\s*\d+\s*,\s*\{-\d+\}")

# Enum value: simple {0,0,uuid},"Name",{synonyms} with NO Pattern and NO system sub-col
# Detection: after closing "","",0,0} comes nothing structural


# ---------------------------------------------------------------------------
# Low-level utilities
# ---------------------------------------------------------------------------

def _find_close_brace(text: str, open_pos: int) -> int:
    """Return the position of the matching } for { at open_pos."""
    depth = 0
    i = open_pos
    in_str = False
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


_SUPPORTED_LANGS = frozenset(("uk", "en"))


def _parse_synonyms(block_text: str) -> Dict[str, str]:
    """Parse {N,"ru","Value","uk","Value",...} -> {'uk': 'Value', 'en': 'Value'}.

    Only uk and en are stored — Russian is dropped per project localization policy.
    """
    out: Dict[str, str] = {}
    for m in _SYN_PAIR_RE.finditer(block_text):
        lang = m.group(1).strip().lower()
        value = m.group(2).strip()
        if lang in _SUPPORTED_LANGS and value and lang not in out:
            out[lang] = value
    return out


def extract_config_type_aliases(config_text: str) -> List[str]:
    """Return object-specific type GUIDs declared in a Config root header."""

    match = _ROOT_TYPE_ALIAS_RE.search(str(config_text or ""))
    if match is None:
        return []
    return list(
        dict.fromkeys(
            guid.lower()
            for guid in _GUID_RE.findall(match.group("aliases"))
        )
    )


def _parse_pattern_type(
    inner: str,
    *,
    ref_uuid_to_name: Dict[str, Tuple[str, str]],
) -> Tuple[str, str, Optional[str], Dict[str, Any]]:
    """Parse the inner content of {"Pattern", <inner>} and return (mp_type, raw_type, ref_name, qualifiers).

    ref_uuid_to_name: uuid -> (family, name) for resolving references.
    """
    s = inner.strip()
    qualifiers: Dict[str, Any] = {}

    if _PAT_BOOL_RE.match(s):
        return "bool", "B", None, qualifiers

    m = _PAT_STR_RE.match(s)
    if m:
        if m.group(1) is not None:
            qualifiers["str_length"] = int(m.group(1))
            qualifiers["str_allowed_length"] = "variable" if m.group(2) == "1" else "fixed"
        return "string", "S", None, qualifiers

    m = _PAT_DATE_RE.match(s)
    if m:
        qualifier = (m.group(1) or "").upper()
        if qualifier == "T":
            return "time", "DT", None, qualifiers
        if qualifier == "D":
            return "datetime", "DT", None, qualifiers
        return "date", "D", None, qualifiers

    m = _PAT_NUM_RE.match(s)
    if m:
        qualifiers["digits"] = int(m.group(1))
        qualifiers["fraction_digits"] = int(m.group(2))
        qualifiers["allowed_sign"] = "nonnegative" if m.group(3) == "0" else "any"
        return "number", "N", None, qualifiers

    m = _PAT_REF_RE.match(s)
    if m:
        ref_uuid = m.group(1).lower()
        return _reference_type_result(
            ref_uuid,
            ref_uuid_to_name=ref_uuid_to_name,
            qualifiers=qualifiers,
        )

    # Composite reference types contain several {"#", GUID} descriptors.
    # Preserve them as a reference and use the first resolvable metadata type.
    ref_uuids = [match.lower() for match in _PAT_REF_FIND_RE.findall(s)]
    if ref_uuids:
        ref_uuid = next(
            (uuid for uuid in ref_uuids if ref_uuid_to_name.get(uuid, ("", ""))[1]),
            ref_uuids[0],
        )
        qualifiers["ref_uuids"] = ref_uuids
        return _reference_type_result(
            ref_uuid,
            ref_uuid_to_name=ref_uuid_to_name,
            qualifiers=qualifiers,
        )

    # Unrecognised pattern
    raw_preview = s[:40].replace("\n", " ").replace("\r", "")
    return "unknown", raw_preview, None, qualifiers


# ---------------------------------------------------------------------------
# Named-object extraction
# ---------------------------------------------------------------------------

@dataclass
class _NamedObj:
    uuid: str
    name: str
    synonyms: Dict[str, str]
    pos: int           # start of {0,0,uuid} in original text
    end_pos: int       # position after closing } of the synonyms block + ,"",0,0}
    pattern_inner: Optional[str]          # content of {"Pattern", ...} or None
    has_tabpart_structure: bool           # True if sub-collection with {-N} present
    extra_synonyms: Dict[str, str]        # extended description found after header
    comment: str = ""
    value_properties: Optional[List[Any]] = None
    outer_properties: Optional[List[Any]] = None
    depth: int = 0                        # brace depth at pos (computed lazily)


class _BraceValueParser:
    """Small parser for the nested brace values used by Config records."""

    def __init__(self, text: str, start: int = 0) -> None:
        self.text = text
        self.pos = max(int(start), 0)

    def _skip_space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def parse_value(self) -> Any:
        self._skip_space()
        if self.pos >= len(self.text):
            raise ValueError("Unexpected end of Config value")
        if self.text[self.pos] == "{":
            return self._parse_list()
        if self.text[self.pos] == '"':
            return self._parse_string()
        if self.text.startswith("#base64:", self.pos):
            return self._parse_base64()

        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in ",{}\r\n\t ":
            self.pos += 1
        if self.pos == start:
            raise ValueError(f"Unexpected Config token at {self.pos}")
        return self.text[start:self.pos]

    def _parse_base64(self) -> str:
        """Read a multiline Config base64 atom without treating whitespace as a delimiter."""

        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in ",}":
            self.pos += 1
        return "".join(self.text[start:self.pos].split())

    def _parse_list(self) -> List[Any]:
        self.pos += 1
        values: List[Any] = []
        self._skip_space()
        while self.pos < len(self.text) and self.text[self.pos] != "}":
            values.append(self.parse_value())
            self._skip_space()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1
                self._skip_space()
            elif self.pos < len(self.text) and self.text[self.pos] != "}":
                raise ValueError(f"Expected comma or closing brace at {self.pos}")
        if self.pos >= len(self.text):
            raise ValueError("Unterminated Config list")
        self.pos += 1
        return values

    def _parse_string(self) -> str:
        self.pos += 1
        chars: List[str] = []
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char != '"':
                chars.append(char)
                self.pos += 1
                continue
            if self.pos + 1 < len(self.text) and self.text[self.pos + 1] == '"':
                chars.append('"')
                self.pos += 2
                continue
            self.pos += 1
            return "".join(chars)
        raise ValueError("Unterminated Config string")


_FIELD_CONTAINER_PREFIX_RE = re.compile(
    r"\{\d+\s*,\s*\{\d+\s*,\s*\{2\s*,\s*\{3\s*,\s*$",
    re.DOTALL,
)
_INNER_FIELD_CONTAINER_PREFIX_RE = re.compile(
    r"\{\d+\s*,\s*\{2\s*,\s*\{3\s*,\s*$",
    re.DOTALL,
)


def _parse_field_serialization_nodes(text: str, header_pos: int) -> Tuple[Optional[List[Any]], Optional[List[Any]]]:
    """Return the value-property node and its outer storage-property node."""

    window_start = max(0, int(header_pos) - 160)
    prefix = text[window_start:header_pos]
    matches = list(_FIELD_CONTAINER_PREFIX_RE.finditer(prefix))
    if matches:
        outer_start = window_start + matches[-1].start()
        try:
            outer = _BraceValueParser(text, outer_start).parse_value()
        except (ValueError, IndexError):
            outer = None
        if isinstance(outer, list) and len(outer) > 1 and isinstance(outer[1], list):
            return outer[1], outer

    matches = list(_INNER_FIELD_CONTAINER_PREFIX_RE.finditer(prefix))
    if matches:
        inner_start = window_start + matches[-1].start()
        try:
            inner = _BraceValueParser(text, inner_start).parse_value()
        except (ValueError, IndexError):
            inner = None
        if isinstance(inner, list):
            return inner, None
    return None, None


def _brace_depth_at(text: str, pos: int) -> int:
    """Count open-brace depth at position pos (0 = top level)."""
    depth = 0
    in_str = False
    for i in range(pos):
        ch = text[i]
        if in_str:
            if ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
    return max(depth, 0)


def _extract_named_objects(text: str) -> List[_NamedObj]:
    """Find all named metadata objects in the Config text."""
    results: List[_NamedObj] = []

    for m in _HEADER_RE.finditer(text):
        obj_uuid = m.group(1).lower()
        obj_name = m.group(2)
        brace_start = m.end() - 1  # position of { opening synonyms block

        syn_end = _find_close_brace(text, brace_start)
        if syn_end < 0:
            continue

        syn_block = text[brace_start : syn_end + 1]
        synonyms = _parse_synonyms(syn_block)

        # The header tail has several format-version dependent scalar fields.
        # Its first item is always the comment, and it ends at the next brace.
        tail_m = re.match(
            r'\s*,\s*"([^"]*)"\s*,\s*[^{}]*\}',
            text[syn_end + 1 :],
            re.DOTALL,
        )
        if tail_m is None:
            continue
        comment = tail_m.group(1).strip()
        end_pos = syn_end + 1 + tail_m.end()

        # Scan ahead (up to 600 chars) to determine what follows
        lookahead = text[end_pos : end_pos + 600]

        # Strip leading whitespace/commas/closing braces carefully
        lookahead_stripped = lookahead.lstrip(' \t\r\n,}')

        # Check for {"Pattern",
        pat_m = _PATTERN_SEARCH_RE.search(lookahead)
        pattern_inner: Optional[str] = None
        if pat_m and pat_m.start() < 400:
            pat_open = end_pos + pat_m.end()  # position right after '{"Pattern",'
            # The inner content is everything up to the matching close brace
            # The {"Pattern", opens with { at pat_m.start() relative to end_pos
            abs_pat_start = end_pos + pat_m.start()
            pat_close = _find_close_brace(text, abs_pat_start)
            if pat_close > 0:
                # Inner content: between "," and closing }
                comma_pos = text.index(",", abs_pat_start)
                pattern_inner = text[comma_pos + 1 : pat_close].strip()

        # Check for tabular-part sub-collection (system fields block)
        has_tabpart = bool(_TABPART_SYSFIELD_RE.search(lookahead[:500])) if pattern_inner is None else False

        # Extended localized text is the requisite tooltip in real Config rows.
        extra_synonyms: Dict[str, str] = {}
        ext_m = re.search(
            r'\{2\s*,\s*"ru"\s*,\s*"([^"]+)"\s*,\s*"uk"\s*,\s*"([^"]+)"\s*\}',
            lookahead[:300],
        )
        if ext_m:
            if ext_m.group(2) and ext_m.group(2) != synonyms.get("uk", ""):
                extra_synonyms["uk"] = ext_m.group(2)

        value_properties, outer_properties = _parse_field_serialization_nodes(text, m.start())

        results.append(
            _NamedObj(
                uuid=obj_uuid,
                name=obj_name,
                synonyms=synonyms,
                pos=m.start(),
                end_pos=end_pos,
                pattern_inner=pattern_inner,
                has_tabpart_structure=has_tabpart,
                extra_synonyms=extra_synonyms,
                comment=comment,
                value_properties=value_properties,
                outer_properties=outer_properties,
                depth=0,  # filled in after all objects found
            )
        )

    # Compute brace depths using a single O(n) pass
    if results:
        depth = 0
        in_str = False
        result_idx = 0
        sorted_results = sorted(results, key=lambda o: o.pos)
        for i, ch in enumerate(text):
            if in_str:
                if ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth = max(depth - 1, 0)
            while result_idx < len(sorted_results) and sorted_results[result_idx].pos == i:
                sorted_results[result_idx].depth = depth
                result_idx += 1
        results = sorted_results

    return results


def _token_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _token_bool(value: Any) -> bool:
    return _token_int(value, 0) != 0


def _localized_serialized_value(value: Any) -> Dict[str, str]:
    if not isinstance(value, list) or len(value) < 3:
        return {}
    out: Dict[str, str] = {}
    index = 1
    while index + 1 < len(value):
        lang = str(value[index] or "").strip().lower()
        content = str(value[index + 1] or "").strip()
        if lang in _SUPPORTED_LANGS and content and lang not in out:
            out[lang] = content
        index += 2
    return out


def _serialized_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list) or not value:
        return ""
    kind = str(value[0] or "").upper()
    if kind == "S" and len(value) > 1:
        return str(value[1] or "")
    return ""


def _nested_strings(value: Any) -> List[str]:
    out: List[str] = []

    def append(current: Any) -> None:
        if isinstance(current, list):
            for child in current:
                append(child)
        elif isinstance(current, str) and current:
            out.append(current)

    append(value)
    return out


_FAMILY_METADATA_PREFIX = {
    "catalog": "Catalog",
    "document": "Document",
    "enum": "Enum",
    "chart_of_accounts": "ChartOfAccounts",
    "chart_of_characteristic_types": "ChartOfCharacteristicTypes",
    "business_process": "BusinessProcess",
    "task": "Task",
    "exchange_plan": "ExchangePlan",
}

_FAMILY_RAW_REF_PREFIX = {
    "catalog": "cfg:CatalogRef.",
    "document": "cfg:DocumentRef.",
    "enum": "cfg:EnumRef.",
    "business_process": "cfg:BusinessProcessRef.",
    "task": "cfg:TaskRef.",
    "exchange_plan": "cfg:ExchangePlanRef.",
    "chart_of_accounts": "cfg:ChartOfAccountsRef.",
    "chart_of_characteristic_types": "cfg:ChartOfCharacteristicTypesRef.",
    "characteristic": "cfg:Characteristic.",
}


def _reference_type_result(
    ref_uuid: str,
    *,
    ref_uuid_to_name: Dict[str, Tuple[str, str]],
    qualifiers: Dict[str, Any],
) -> Tuple[str, str, Optional[str], Dict[str, Any]]:
    family, ref_name = ref_uuid_to_name.get(ref_uuid, ("", ""))
    qualifiers["ref_uuid"] = ref_uuid
    qualifiers["ref_family"] = family
    if family == "enum":
        mp_type = "enum_ref"
    elif family == "characteristic":
        mp_type = "any_ref"
    else:
        mp_type = "ref"
    raw_prefix = _FAMILY_RAW_REF_PREFIX.get(family, "")
    raw_type = f"{raw_prefix}{ref_name}" if raw_prefix and ref_name else "#"
    return mp_type, raw_type, ref_name or None, qualifiers


def _decode_serialized_fill_value(
    value: Any,
    *,
    ref_uuid_to_name: Dict[str, Tuple[str, str]],
) -> Any:
    if not isinstance(value, list) or not value:
        return None
    kind = str(value[0] or "").upper()
    if kind == "U":
        return None
    if kind in {"S", "N"}:
        scalar = str(value[1] if len(value) > 1 else "")
        return scalar if kind == "N" or scalar else None
    if kind == "B":
        return _token_bool(value[1] if len(value) > 1 else 0)
    if kind != "#":
        return None

    descriptor = next(
        (
            item
            for item in value[1:]
            if isinstance(item, list)
            and len(item) >= 3
            and str(item[0]) == "0"
            and _GUID_RE.fullmatch(str(item[1] or ""))
        ),
        None,
    )
    if descriptor is None:
        return None
    type_uuid = str(descriptor[1]).lower()
    value_uuid = str(descriptor[2] or "").lower()
    family, name = ref_uuid_to_name.get(type_uuid, ("", ""))
    prefix = _FAMILY_METADATA_PREFIX.get(family, "")
    if name and prefix and value_uuid == "00000000-0000-0000-0000-000000000000":
        return f"{prefix}.{name}.EmptyRef"
    if name and prefix:
        return f"{prefix}.{name}.Ref.{value_uuid}"
    return f"ref://{type_uuid}/{value_uuid}"


def _decode_value_properties(
    obj: _NamedObj,
    *,
    ref_uuid_to_name: Dict[str, Tuple[str, str]],
) -> Dict[str, Any]:
    values = obj.value_properties
    if not isinstance(values, list) or len(values) < 23:
        return {}

    properties: Dict[str, Any] = {
        "comment": obj.comment,
        "hint": _localized_serialized_value(values[4]),
        "mark_negatives": _token_bool(values[5]),
        "mask": str(values[6] or ""),
        "multi_line": _token_bool(values[7]),
        "format": _serialized_text(values[8]),
        "editing_format": _serialized_text(values[9]),
        "password_mode": _token_bool(values[10]),
        # Attribute serialization versions encode this slot differently; Items
        # is the stable Configurator default and the value emitted by XMLConf.
        "choice_groups_elements": "Items",
        "fill_checking": {
            0: "DontCheck",
            1: "ShowError",
        }.get(_token_int(values[13]), "DontCheck"),
        "extended_edit": _token_bool(values[17]),
        "fill_value": _decode_serialized_fill_value(
            values[19],
            ref_uuid_to_name=ref_uuid_to_name,
        ),
        "fill_from_filling_value": _token_bool(values[20]),
        "quick_choice": {
            0: "Auto",
            1: "Use",
            2: "DontUse",
        }.get(_token_int(values[21]), "Auto"),
        "choice_history_on_input": "Auto",
        "indexing": "DontIndex",
        "full_text_search": "Use",
        "data_history": "Use",
    }
    properties["create_on_input"] = (
        "Use" if properties["quick_choice"] == "DontUse" else "Auto"
    )

    parameter_links = [
        item for item in _nested_strings(values[14]) if item.startswith("Отбор.")
    ]
    if parameter_links:
        properties["parameter_links"] = list(dict.fromkeys(parameter_links))

    choice_parameters = [
        item
        for item in _nested_strings(values[16])
        if item not in {"0", "1", "2", "3", "#", "B", "S", "N", "U"}
        and not _GUID_RE.fullmatch(item)
    ]
    if choice_parameters:
        properties["choice_parameters"] = list(dict.fromkeys(choice_parameters))

    choice_form_guid = str(values[11] or "")
    if _GUID_RE.fullmatch(choice_form_guid) and choice_form_guid != "00000000-0000-0000-0000-000000000000":
        properties["choice_form"] = f"form://{choice_form_guid.lower()}"

    type_links = [
        item.lower()
        for item in _nested_strings(values[15])
        if _GUID_RE.fullmatch(item)
        and item.lower() != "00000000-0000-0000-0000-000000000000"
    ]
    if type_links:
        properties["type_link"] = f"metadata://{type_links[-1]}"

    outer = obj.outer_properties
    if isinstance(outer, list) and len(outer) >= 5:
        properties["indexing"] = {
            0: "DontIndex",
            1: "Index",
            2: "IndexWithAdditionalOrder",
        }.get(_token_int(outer[2]), "DontIndex")
        properties["full_text_search"] = {
            0: "DontUse",
            1: "Use",
        }.get(_token_int(outer[3]), "DontUse")
        properties["data_history"] = {
            0: "DontUse",
            1: "Use",
        }.get(_token_int(outer[4]), "DontUse")
    return properties


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_config_text(
    config_text: str,
    object_uuid: str,
    object_family: str,
    *,
    ref_uuid_to_name: Optional[Dict[str, Tuple[str, str]]] = None,
) -> Optional[OneCMetaObject]:
    """Parse 1C Config text and return a populated OneCMetaObject.

    Args:
        config_text: Raw text decoded from the Config BLOB row.
        object_uuid: UUID of the main object (from DBNames), lower-case.
        object_family: Family string ('catalog', 'document', 'enum', etc.).
        ref_uuid_to_name: Optional mapping uuid -> (family, name) for resolving
                          reference types.  Build it from DBNames + Config names.
    Returns:
        OneCMetaObject or None if the config text cannot be parsed.
    """
    if not config_text or not object_uuid:
        return None

    lookup = ref_uuid_to_name or {}
    named = _extract_named_objects(config_text)
    if not named:
        return None

    # The first object whose UUID matches is the main object itself
    main_obj: Optional[_NamedObj] = None
    for obj in named:
        if obj.uuid == object_uuid.lower():
            main_obj = obj
            break
    if main_obj is None:
        # Fallback: first found
        main_obj = named[0]

    main_name = main_obj.name
    main_synonyms = main_obj.synonyms

    # All remaining objects are requisites, tabular parts, or their columns
    children = [obj for obj in named if obj is not main_obj]

    # For ENUM family: all children are enum values (no Pattern, no sub-collection)
    if object_family == "enum":
        enum_values: List[OneCEnumValue] = []
        for idx, obj in enumerate(children):
            enum_values.append(
                OneCEnumValue(
                    name=obj.name,
                    synonyms=obj.synonyms,
                    uuid=obj.uuid,
                    order=idx,
                )
            )
        return OneCMetaObject(
            obj_type=object_family,
            name=main_name,
            synonyms=main_synonyms,
            uuid=object_uuid,
            enum_values=enum_values,
            origin_path=f"1cd://Config/{object_uuid}",
        )

    # Separate tabular parts from requisites/columns
    tabparts: List[_NamedObj] = []
    field_objs: List[_NamedObj] = []

    for obj in children:
        if obj.has_tabpart_structure and obj.pattern_inner is None:
            tabparts.append(obj)
        elif obj.pattern_inner is not None:
            field_objs.append(obj)
        else:
            # Unknown: no Pattern, no tabpart sub-collection
            # Could be enum-like child or unrecognised — skip
            pass

    child_subsystems: List[str] = []
    if object_family == "subsystem":
        child_subsystems = [
            obj.name
            for obj in children
            if obj not in tabparts and obj not in field_objs and str(obj.name or "").strip()
        ]
        if child_subsystems:
            child_subsystems = list(dict.fromkeys(child_subsystems))

    # Assign field_objs to their parent using brace depth.
    # Tabular parts are at some depth D.  Their columns are deeper (D+1 or more)
    # AND appear between the tabpart's pos and the next tabpart's pos.
    # Top-level requisites are at the SAME depth as the tabparts.
    tabpart_depth = min((tp.depth for tp in tabparts), default=None)

    tabpart_positions = sorted((tp.pos, tp) for tp in tabparts)

    def _parent_tabpart(obj: _NamedObj) -> Optional[_NamedObj]:
        """Return the tabular part that 'owns' this field, or None if top-level requisite."""
        # If object is at the same depth as tabparts → top-level requisite
        if tabpart_depth is not None and obj.depth <= tabpart_depth:
            return None
        # Otherwise assign to the nearest preceding tabpart
        last_tp = None
        for tp_pos, tp in tabpart_positions:
            if tp_pos < obj.pos:
                last_tp = tp
            else:
                break
        return last_tp

    requisites: List[OneCRequisite] = []
    tabpart_columns: Dict[str, List[OneCTabularColumn]] = {}  # tabpart uuid -> columns

    for obj in field_objs:
        mp_type, raw_type, ref_name, qualifiers = _parse_pattern_type(
            obj.pattern_inner or "",
            ref_uuid_to_name=lookup,
        )
        value_props = _decode_value_properties(
            obj,
            ref_uuid_to_name=lookup,
        )
        parent = _parent_tabpart(obj)

        if parent is not None:
            # Column of a tabular part
            serialized_fill = (
                obj.value_properties[19]
                if isinstance(obj.value_properties, list) and len(obj.value_properties) > 19
                else None
            )
            column_fill_value = value_props.get("fill_value")
            if isinstance(serialized_fill, list) and serialized_fill:
                if str(serialized_fill[0] or "").upper() in {"U", "S", "N"}:
                    column_fill_value = None
            col = OneCTabularColumn(
                name=obj.name,
                synonyms=obj.synonyms,
                mp_type=mp_type,
                ref_name=ref_name,
                raw_type=raw_type,
                uuid=obj.uuid,
                digits=qualifiers.get("digits"),
                fraction_digits=qualifiers.get("fraction_digits"),
                str_length=qualifiers.get("str_length"),
                required=value_props.get("fill_checking") == "ShowError",
                fill_checking=str(value_props.get("fill_checking") or ""),
                comment=str(value_props.get("comment") or ""),
                fill_value=column_fill_value,
                format=str(value_props.get("format") or ""),
                editing_format=str(value_props.get("editing_format") or ""),
                hint=dict(value_props.get("hint") or {}),
                mark_negatives=value_props.get("mark_negatives"),
                mask=str(value_props.get("mask") or ""),
                multi_line=bool(value_props.get("multi_line")),
                password_mode=bool(value_props.get("password_mode")),
                extended_edit=value_props.get("extended_edit"),
                fill_from_filling_value=None,
                choice_groups_elements=str(value_props.get("choice_groups_elements") or ""),
                parameter_links=list(value_props.get("parameter_links") or []),
                choice_parameters=list(value_props.get("choice_parameters") or []),
                quick_choice=str(value_props.get("quick_choice") or ""),
                create_on_input=str(value_props.get("create_on_input") or ""),
                choice_form=str(value_props.get("choice_form") or ""),
                type_link=str(value_props.get("type_link") or ""),
                choice_history_on_input=str(value_props.get("choice_history_on_input") or ""),
                indexing=str(value_props.get("indexing") or ""),
                full_text_search=str(value_props.get("full_text_search") or ""),
                data_history=str(value_props.get("data_history") or ""),
            )
            tabpart_columns.setdefault(parent.uuid, []).append(col)
        else:
            # Top-level requisite
            req = OneCRequisite(
                name=obj.name,
                synonyms=obj.synonyms,
                mp_type=mp_type,
                ref_name=ref_name,
                raw_type=raw_type,
                uuid=obj.uuid,
                digits=qualifiers.get("digits"),
                fraction_digits=qualifiers.get("fraction_digits"),
                allowed_sign=qualifiers.get("allowed_sign"),
                str_length=qualifiers.get("str_length"),
                str_allowed_length=qualifiers.get("str_allowed_length"),
                fill_checking=str(value_props.get("fill_checking") or ""),
                fill_value=value_props.get("fill_value"),
                required=value_props.get("fill_checking") == "ShowError",
                multi_line=bool(value_props.get("multi_line")),
                password_mode=bool(value_props.get("password_mode")),
                comment=str(value_props.get("comment") or ""),
                format=str(value_props.get("format") or ""),
                editing_format=str(value_props.get("editing_format") or ""),
                hint=dict(value_props.get("hint") or {}),
                mark_negatives=value_props.get("mark_negatives"),
                mask=str(value_props.get("mask") or ""),
                extended_edit=value_props.get("extended_edit"),
                fill_from_filling_value=value_props.get("fill_from_filling_value"),
                choice_groups_elements=str(value_props.get("choice_groups_elements") or ""),
                parameter_links=list(value_props.get("parameter_links") or []),
                choice_parameters=list(value_props.get("choice_parameters") or []),
                quick_choice=str(value_props.get("quick_choice") or ""),
                create_on_input=str(value_props.get("create_on_input") or ""),
                choice_form=str(value_props.get("choice_form") or ""),
                type_link=str(value_props.get("type_link") or ""),
                choice_history_on_input=str(value_props.get("choice_history_on_input") or ""),
                indexing=str(value_props.get("indexing") or ""),
                full_text_search=str(value_props.get("full_text_search") or ""),
                data_history=str(value_props.get("data_history") or ""),
            )
            requisites.append(req)

    # Build tabular part objects
    tabular_parts: List[OneCTabularPart] = []
    for tp_node in tabparts:
        columns = tabpart_columns.get(tp_node.uuid, [])
        tabular_parts.append(
            OneCTabularPart(
                name=tp_node.name,
                synonyms=tp_node.synonyms,
                uuid=tp_node.uuid,
                columns=columns,
            )
        )

    # Map requisites to correct slot by family
    attributes: List[OneCRequisite] = []
    dimensions: List[OneCRequisite] = []
    resources: List[OneCRequisite] = []

    _REGISTER_FAMILIES = {
        "information_register",
        "accumulation_register",
        "accounting_register",
        "calculation_register",
    }

    if object_family in _REGISTER_FAMILIES:
        # For registers: try to assign by position (dims first, then resources, then attributes)
        # Without more context just keep all as requisites
        attributes = requisites
        requisites = []

    return OneCMetaObject(
        obj_type=object_family,
        name=main_name,
        synonyms=main_synonyms,
        uuid=object_uuid,
        origin_path=f"1cd://Config/{object_uuid}",
        requisites=requisites,
        attributes=attributes,
        dimensions=dimensions,
        resources=resources,
        tabular_parts=tabular_parts,
        child_subsystems=child_subsystems,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_ref_uuid_to_name(
    primary_by_guid: Dict[str, Any],
) -> Dict[str, Tuple[str, str]]:
    """Build a uuid -> (family, name) lookup from the parsed DBNames index.

    primary_by_guid: {guid_lower: (OneCDMetadataKind, order)} as returned by
                     OneCDConfigSource._load_metadata_objects() internal parsing,
                     or any dict with .family and the pre-resolved name.

    This is a lightweight helper — callers may supply pre-built name maps.
    """
    out: Dict[str, Tuple[str, str]] = {}
    for uuid, value in primary_by_guid.items():
        if isinstance(value, tuple) and len(value) >= 1:
            kind = value[0]
            family = str(getattr(kind, "family", "") or "")
            # name is not known here without Config lookup; use empty
            out[str(uuid).lower()] = (family, "")
    return out


__all__ = [
    "parse_config_text",
    "build_ref_uuid_to_name",
    "extract_config_type_aliases",
]
