from __future__ import annotations

import re
from typing import Any, Dict, List

from .onec_requisites_model import OneCMetaObject


_ORIGIN_ROOT_TO_METADATA_ROOT: dict[str, str] = {
    "AccumulationRegisters": "AccumulationRegister",
    "AccountingRegisters": "AccountingRegister",
    "BusinessProcesses": "BusinessProcess",
    "CalculationRegisters": "CalculationRegister",
    "Catalogs": "Catalog",
    "ChartsOfAccounts": "ChartOfAccounts",
    "ChartsOfCalculationTypes": "ChartOfCalculationTypes",
    "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
    "CommandGroups": "CommandGroup",
    "CommonAttributes": "CommonAttribute",
    "CommonCommands": "CommonCommand",
    "CommonForms": "CommonForm",
    "CommonLayouts": "CommonTemplate",
    "CommonModules": "CommonModule",
    "CommonPictures": "CommonPicture",
    "CommonTemplates": "CommonTemplate",
    "Constants": "Constant",
    "DataProcessors": "DataProcessor",
    "DocumentJournals": "DocumentJournal",
    "DocumentNumerators": "DocumentNumerator",
    "Documents": "Document",
    "Enums": "Enum",
    "ExternalDataSources": "ExternalDataSource",
    "InformationRegisters": "InformationRegister",
    "Languages": "Language",
    "Reports": "Report",
    "Roles": "Role",
    "Sequences": "Sequence",
    "Subsystems": "Subsystem",
    "Tasks": "Task",
}


_OBJ_TYPE_TO_METADATA_ROOT: dict[str, str] = {
    "business_process": "BusinessProcess",
    "catalog": "Catalog",
    "chart_of_accounts": "ChartOfAccounts",
    "chart_of_calculation_types": "ChartOfCalculationTypes",
    "chart_of_characteristic_types": "ChartOfCharacteristicTypes",
    "command_group": "CommandGroup",
    "common_attribute": "CommonAttribute",
    "common_command": "CommonCommand",
    "common_form": "CommonForm",
    "common_layout": "CommonTemplate",
    "common_module": "CommonModule",
    "common_picture": "CommonPicture",
    "constants": "Constant",
    "data_processor": "DataProcessor",
    "document": "Document",
    "document_numerator": "DocumentNumerator",
    "enumeration": "Enum",
    "external_sources": "ExternalDataSource",
    "journal": "DocumentJournal",
    "language": "Language",
    "register_accum": "AccumulationRegister",
    "register_accounting": "AccountingRegister",
    "register_calc": "CalculationRegister",
    "register_info": "InformationRegister",
    "report": "Report",
    "role": "Role",
    "sequence": "Sequence",
    "subsystem": "Subsystem",
    "task": "Task",
}

_METADATA_ROOT_LOCALIZED: dict[str, tuple[str, str]] = {
    "AccumulationRegister": ("РегістрНакопичення", "AccumulationRegister"),
    "BusinessProcess": ("БізнесПроцес", "BusinessProcess"),
    "Catalog": ("Довідник", "Catalog"),
    "CommonCommand": ("ЗагальнаКоманда", "CommonCommand"),
    "CommonForm": ("ЗагальнаФорма", "CommonForm"),
    "CommonModule": ("ЗагальнийМодуль", "CommonModule"),
    "Constant": ("Константа", "Constant"),
    "DataProcessor": ("Обробка", "DataProcessor"),
    "Document": ("Документ", "Document"),
    "DocumentJournal": ("ЖурналДокументів", "DocumentJournal"),
    "Enum": ("Перелік", "Enum"),
    "ExchangePlan": ("ПланОбміну", "ExchangePlan"),
    "InformationRegister": ("РегістрВідомостей", "InformationRegister"),
    "Report": ("Звіт", "Report"),
    "SettingsStorage": ("СховищеНалаштувань", "SettingsStorage"),
    "Task": ("Завдання", "Task"),
    "WebService": ("ВебСервіс", "WebService"),
}

_MODULE_KIND_LOCALIZED: dict[str, tuple[str, str]] = {
    "CommandModule": ("МодульКоманди", "CommandModule"),
    "ExternalConnectionModule": ("МодульЗовнішньогоЗєднання", "ExternalConnectionModule"),
    "FormModule": ("МодульФорми", "FormModule"),
    "ManagedApplicationModule": ("МодульКерованогоЗастосунку", "ManagedApplicationModule"),
    "ManagerModule": ("МодульМенеджера", "ManagerModule"),
    "Module": ("Модуль", "Module"),
    "ObjectModule": ("МодульОбєкта", "ObjectModule"),
    "OrdinaryApplicationModule": ("МодульЗвичайногоЗастосунку", "OrdinaryApplicationModule"),
    "RecordSetModule": ("МодульНаборуЗаписів", "RecordSetModule"),
    "SessionModule": ("МодульСеансу", "SessionModule"),
    "ValueManagerModule": ("МодульМенеджераЗначення", "ValueManagerModule"),
}


# Code aliases are identifiers, not UI captions. 1C configurations commonly
# contain Russian technical names and only a Ukrainian synonym. Keep a small,
# deterministic platform glossary for the structural terms and transliterate
# unknown business words so an English alias is always valid and stable.
_EN_CODE_WORDS: dict[str, str] = {
    "автономна": "Standalone",
    "автономний": "Standalone",
    "базова": "Base",
    "базовий": "Base",
    "вик": "",
    "виклик": "Call",
    "використання": "Reuse",
    "даних": "Data",
    "дані": "Data",
    "документ": "Document",
    "документи": "Documents",
    "загальна": "Common",
    "загальний": "Common",
    "клієнт": "Client",
    "модуль": "Module",
    "обладнання": "Equipment",
    "обробка": "Processing",
    "підсистема": "Subsystem",
    "підсистеми": "Subsystems",
    "повт": "Reuse",
    "повторне": "Reuse",
    "робота": "Work",
    "сервер": "Server",
    "службовий": "Service",
    "стандартна": "Standard",
    "стандартний": "Standard",
    "стандартні": "Standard",
    "форма": "Form",
}

_CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d",
    "е": "e", "є": "ye", "ж": "zh", "з": "z", "и": "y", "і": "i",
    "ї": "yi", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ь": "", "ъ": "", "ы": "y", "э": "e", "ю": "yu", "я": "ya", "ё": "yo",
}


def repair_cp1251_mojibake_component(value: str) -> str:
    raw = str(value or "")
    try:
        repaired = raw.encode("latin1").decode("cp1251")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw
    before = sum("\u0400" <= char <= "\u04ff" for char in raw)
    after = sum("\u0400" <= char <= "\u04ff" for char in repaired)
    return repaired if after > before else raw


def _reference_identifier(value: str, fallback: str = "Object") -> str:
    words = re.findall(r"[^\W_]+", repair_cp1251_mojibake_component(value), flags=re.UNICODE)
    identifier = "".join(word[:1].upper() + word[1:] for word in words)
    if not identifier:
        identifier = fallback
    if identifier[:1].isdigit():
        identifier = f"_{identifier}"
    return identifier


def _source_reference_identifier(value: str, fallback: str = "Object") -> str:
    """Keep a metadata Properties/Name identifier byte-for-byte where valid."""

    source = repair_cp1251_mojibake_component(value).strip()
    identifier = "".join(char for char in source if char == "_" or char.isalnum())
    if not identifier:
        identifier = fallback
    if identifier[:1].isdigit():
        identifier = f"_{identifier}"
    return identifier


def _transliterate_code_word(value: str) -> str:
    out: list[str] = []
    for char in str(value or ""):
        mapped = _CYRILLIC_TO_LATIN.get(char.casefold())
        if mapped is None:
            if char.isascii() and char.isalnum():
                mapped = char
            else:
                continue
        out.append(mapped)
    word = "".join(out)
    return word[:1].upper() + word[1:]


def _english_reference_identifier(
    *,
    explicit_english: str,
    ukrainian: str,
    technical_name: str,
) -> str:
    explicit = repair_cp1251_mojibake_component(explicit_english).strip()
    # Some exports fill a missing English synonym with the technical Russian
    # name. Treat it as a fallback, not as a valid English code alias.
    if explicit and not re.search(r"[\u0400-\u04ff]", explicit):
        return _source_reference_identifier(explicit)

    source = repair_cp1251_mojibake_component(ukrainian or technical_name)
    if not re.search(r"[\u0400-\u04ff]", source):
        return _source_reference_identifier(source)

    # Preserve the CamelCase boundary from Properties/Name while translating
    # each component. Flattening the whole name would produce a lower-cased
    # alias such as ``Standartnyepodsystemy`` and lose the code convention.
    words = re.findall(
        r"[A-ZА-ЯЁЇІЄҐ][^A-ZА-ЯЁЇІЄҐ_\s]*|[a-zа-яёїієґ]+|[0-9]+|_+",
        source,
    )
    translated: list[str] = []
    for word in words:
        mapped = _EN_CODE_WORDS.get(word.casefold())
        if mapped is None:
            mapped = _transliterate_code_word(word)
        if mapped and (not translated or translated[-1] != mapped):
            translated.append(mapped)
    return _reference_identifier(" ".join(translated), fallback="Object")


def module_refs_from_import_origin(
    origin_path: str,
    *,
    module_kind: str = "",
    owner_name: str = "",
    owner_title_uk: str = "",
    owner_title_en: str = "",
) -> Dict[str, str]:
    """Build stable source/canonical and localized references for a module."""

    source_ref = str(origin_path or "").replace("\\", "/").strip("/")
    parts = [repair_cp1251_mojibake_component(part) for part in source_ref.split("/") if part]
    kind = str(module_kind or "").strip() or (parts[-1][:-4] if parts and parts[-1].lower().endswith(".bsl") else "Module")

    if parts[:1] == ["Ext"]:
        canonical = f"Configuration.{kind}"
        uk_kind, en_kind = _MODULE_KIND_LOCALIZED.get(kind, (kind, kind))
        return {
            "source_ref": source_ref,
            "canonical_ref": canonical,
            "ref_uk": f"Конфігурація.{uk_kind}",
            "ref_en": f"Configuration.{en_kind}",
        }

    root = _ORIGIN_ROOT_TO_METADATA_ROOT.get(parts[0], "") if parts else ""
    path_owner_name = repair_cp1251_mojibake_component(parts[1] if len(parts) > 1 else "")
    technical_name = repair_cp1251_mojibake_component(owner_name or path_owner_name)
    canonical_owner = path_owner_name or technical_name or "Object"
    canonical_parts = [root or "Metadata", canonical_owner]
    nested_kind = ""
    nested_name = ""
    if "Forms" in parts:
        index = parts.index("Forms")
        nested_kind = "Form"
        nested_name = parts[index + 1] if index + 1 < len(parts) else "Form"
        canonical_parts.extend([nested_kind, nested_name])
    elif "Commands" in parts:
        index = parts.index("Commands")
        nested_kind = "Command"
        nested_name = parts[index + 1] if index + 1 < len(parts) else "Command"
        canonical_parts.extend([nested_kind, nested_name])
    canonical_parts.append(kind)

    uk_root, en_root = _METADATA_ROOT_LOCALIZED.get(root, (root or "Метадані", root or "Metadata"))
    uk_kind, en_kind = _MODULE_KIND_LOCALIZED.get(kind, (kind, kind))
    if nested_kind:
        # Child XML carries the form/command synonym, while the stable parent
        # identity is encoded in the source path. Keep both in the reference.
        uk_owner = _reference_identifier(path_owner_name or technical_name)
        en_owner = _english_reference_identifier(
            explicit_english="",
            ukrainian="",
            technical_name=path_owner_name or technical_name,
        )
        uk_child = _reference_identifier(owner_title_uk or nested_name)
        en_child = _english_reference_identifier(
            explicit_english=owner_title_en,
            ukrainian=owner_title_uk,
            technical_name=nested_name,
        )
        uk_nested_kind = "Форма" if nested_kind == "Form" else "Команда"
        return {
            "source_ref": source_ref,
            "canonical_ref": ".".join(canonical_parts),
            "ref_uk": f"{uk_root}.{uk_owner}.{uk_nested_kind}.{uk_child}.{uk_kind}",
            "ref_en": f"{en_root}.{en_owner}.{nested_kind}.{en_child}.{en_kind}",
        }

    if root == "CommonModule":
        # A common-module synonym is presentation text and is not a callable
        # identity. Real configurations legitimately contain hundreds of
        # modules with the same synonym (for example, "Driver handler").
        # 1C source addresses them by Properties/Name, so keep that exact
        # CamelCase technical name as the identity. Localized code namespaces
        # may render the same identity differently, but never use the synonym.
        uk_owner = _source_reference_identifier(technical_name)
        en_owner = _english_reference_identifier(
            explicit_english="",
            ukrainian="",
            technical_name=technical_name,
        )
    else:
        uk_owner = _reference_identifier(owner_title_uk or technical_name)
        en_owner = _english_reference_identifier(
            explicit_english=owner_title_en,
            ukrainian=owner_title_uk,
            technical_name=technical_name,
        )
    return {
        "source_ref": source_ref,
        "canonical_ref": ".".join(canonical_parts),
        "ref_uk": f"{uk_root}.{uk_owner}.{uk_kind}",
        "ref_en": f"{en_root}.{en_owner}.{en_kind}",
    }


def enrich_manifest_payload(existing_payload: Dict[str, Any], obj: OneCMetaObject) -> Dict[str, Any]:
    """Merge parsed 1C metadata into existing manifest payload."""

    payload = dict(existing_payload)
    parsed_payload = obj.to_mp_payload()

    if obj.synonyms and "title" not in payload:
        payload["title"] = obj.synonyms

    def _merge_named_items(key: str, parsed_items: List[Dict[str, Any]]) -> None:
        if not parsed_items:
            return
        existing_items: List[Dict[str, Any]] = payload.get(key) or []
        existing_names = {item.get("name") for item in existing_items if isinstance(item, dict)}
        for item in parsed_items:
            if str(item.get("name") or "") not in existing_names:
                existing_items.append(item)
        payload[key] = existing_items

    _merge_named_items("requisites", [req.to_mp_payload() for req in obj.requisites])
    _merge_named_items("attributes", [req.to_mp_payload() for req in obj.attributes])
    _merge_named_items("dimensions", [req.to_mp_payload() for req in obj.dimensions])
    _merge_named_items("resources", [req.to_mp_payload() for req in obj.resources])
    _merge_named_items("tabular_parts", [part.to_mp_payload() for part in obj.tabular_parts])

    if obj.enum_values:
        payload.setdefault("enum_values", [value.to_mp_payload() for value in obj.enum_values])

    # Preserve the importer-assigned origin path and other import-side hints.
    # The XML parser also exposes an origin, but for manifest rows we want the
    # canonical rel_xml chosen by the import planner, not a parser-side alias.
    imported = dict(parsed_payload.get("imported", {}))
    imported.update(dict(payload.get("imported") or {}))
    payload["imported"] = imported

    if obj.hierarchy_type:
        payload.setdefault("hierarchy_type", obj.hierarchy_type)
    if obj.owners:
        payload.setdefault("owners", obj.owners)

    for key in (
        "use_standard_commands",
        "number_type",
        "number_allowed_length",
        "check_unique",
        "number_length",
        "number_periodicity",
        "autonumbering",
        "posting",
        "real_time_posting",
        "register_records_deletion",
        "register_records_writing_on_post",
        "sequence_filling",
        "based_on",
        "register_records",
        "input_by_string",
        "input_by_string_field",
        "create_on_input",
        "search_string_mode_on_input_by_string",
        "full_text_search_on_input_by_string",
        "choice_data_get_mode_on_input_by_string",
        "choice_history_on_input",
        "default_object_form",
        "default_list_form",
        "default_choice_form",
        "object_presentation",
        "extended_object_presentation",
        "object_presentation_ext",
        "list_presentation",
        "extended_list_presentation",
        "list_presentation_ext",
        "explanation",
        "hint",
        "full_text_search",
        "data_history",
        "update_data_history_immediately_after_write",
        "execute_after_write_data_history_version_processing",
        "post_in_privileged_mode",
        "unpost_in_privileged_mode",
        "include_help_in_contents",
        "include_in_command_interface",
        "use_one_command",
        "picture_ref",
        "content_refs",
        "child_subsystems",
        "set_for_new_objects",
        "set_for_attributes_by_default",
        "independent_rights_of_child_objects",
        "rights",
        "restriction_templates",
        "data_lock_fields",
        "data_lock_control_mode",
    ):
        if key in parsed_payload:
            payload.setdefault(key, parsed_payload[key])
    if obj.comment:
        payload.setdefault("comment", obj.comment)

    return payload


def metadata_ref_from_import_origin(origin_path: str) -> str:
    rel = str(origin_path or "").replace("\\", "/").strip()
    if not rel.lower().endswith(".xml"):
        return ""
    stem = rel[:-4]
    parts = [part for part in stem.split("/") if part]
    if not parts:
        return ""
    if parts[0] == "Subsystems":
        names: list[str] = []
        idx = 1
        while idx < len(parts):
            names.append(parts[idx])
            idx += 2 if idx + 1 < len(parts) and parts[idx + 1] == "Subsystems" else 1
        if not names:
            return ""
        out: list[str] = []
        for name in names:
            out.extend(["Subsystem", name])
        return ".".join(out)

    root = _ORIGIN_ROOT_TO_METADATA_ROOT.get(parts[0], "")
    if not root or len(parts) < 2:
        return ""
    return f"{root}.{parts[1]}"


def metadata_ref_for_manifest_object(*, obj_type: str, name: str, origin_path: str = "") -> str:
    ref = metadata_ref_from_import_origin(origin_path)
    if ref:
        return ref
    root = _OBJ_TYPE_TO_METADATA_ROOT.get(str(obj_type or "").strip().lower(), "")
    object_name = str(name or "").strip()
    if root and object_name:
        return f"{root}.{object_name}"
    return ""


def resolve_subsystem_payload(payload: Dict[str, Any], *, meta_ref_to_guid: Dict[str, str]) -> Dict[str, Any]:
    resolved = dict(payload or {})
    refs = resolved.get("content_refs")
    if isinstance(refs, list):
        objects: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            guid = meta_ref_to_guid.get(str(ref or "").strip())
            if not guid or guid in seen:
                continue
            seen.add(guid)
            objects.append(guid)
        if objects:
            resolved["objects"] = objects

    picture_ref = str(resolved.get("picture_ref") or "").strip()
    if picture_ref:
        picture_guid = meta_ref_to_guid.get(picture_ref)
        if picture_guid:
            resolved["picture_guid"] = picture_guid

    return resolved


__all__ = [
    "enrich_manifest_payload",
    "module_refs_from_import_origin",
    "metadata_ref_for_manifest_object",
    "metadata_ref_from_import_origin",
    "repair_cp1251_mojibake_component",
    "resolve_subsystem_payload",
]
