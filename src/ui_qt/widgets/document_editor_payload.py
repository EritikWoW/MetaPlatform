from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from src.ui_qt.i18n import get_lang, t

from .catalog_editor_payload import _parse_subsystems


def _localized_text(value: Any) -> str:
    if isinstance(value, dict):
        lang = get_lang()
        for key in (lang, "uk", "ru", "en"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
        for text in value.values():
            if isinstance(text, str) and text.strip():
                return text.strip()
        return ""
    return str(value or "").strip()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "так", "да"}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _pick_payload_value(payload: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return default


def _workspace_document_candidate_paths(origin: str) -> list[Path]:
    rel = str(origin or "").replace("\\", "/").lstrip("/")
    if not rel:
        return []
    cwd = Path.cwd()
    candidates = [cwd / rel]
    if not rel.startswith("XMLConf/"):
        candidates.append(cwd / "XMLConf" / rel)
    return candidates


@lru_cache(maxsize=256)
def _load_document_payload_from_workspace(origin: str) -> dict[str, Any]:
    rel = str(origin or "").strip()
    if not rel:
        return {}
    for candidate in _workspace_document_candidate_paths(rel):
        try:
            if not candidate.exists() or not candidate.is_file():
                continue
            from src.infra.onec.onec_requisites_parser import parse_object_xml

            obj = parse_object_xml(candidate.read_bytes(), origin_path=rel)
            if obj is None:
                continue
            return obj.to_mp_payload()
        except Exception:
            continue
    return {}


def _workspace_xml_dump_root() -> Path | None:
    cwd = Path.cwd()
    candidates = [cwd]
    if cwd.name.lower() != "xmlconf":
        candidates.insert(0, cwd / "XMLConf")
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir() and (candidate / "Documents").exists():
            return candidate
    return None


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return path.read_text(encoding="utf-8", errors="ignore")


def _append_unique(items: list[Any], value: Any) -> None:
    if value not in items:
        items.append(value)


def _append_unique_exchange_plan(items: list[dict[str, str]], value: dict[str, str]) -> None:
    plan_name = str(value.get("name") or "").strip()
    auto_record = str(value.get("auto_record") or "").strip()
    if not plan_name:
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() == plan_name and str(item.get("auto_record") or "").strip() == auto_record:
            return
    items.append({"name": plan_name, "auto_record": auto_record})


_SCHEMA_REF_OBJECT_TYPES: dict[str, str] = {
    "catalog": "Catalog",
    "document": "Document",
    "enumeration": "Enum",
    "business_process": "BusinessProcess",
    "task": "Task",
    "chart_of_characteristic_types": "ChartOfCharacteristicTypes",
    "chart_of_accounts": "ChartOfAccounts",
    "exchange_plan": "ExchangePlan",
}

_METADATA_REF_KIND_TO_TYPE: dict[str, str] = {
    "Catalog": "catalog",
    "Document": "document",
    "Enum": "enumeration",
    "BusinessProcess": "business_process",
    "Task": "task",
    "ChartOfCharacteristicTypes": "chart_of_characteristic_types",
    "ChartOfAccounts": "chart_of_accounts",
    "ExchangePlan": "exchange_plan",
    "InformationRegister": "register_info",
    "AccumulationRegister": "register_accum",
    "AccountingRegister": "register_accounting",
    "CalculationRegister": "register_calc",
}

_RIGHTS_I18N: dict[str, str] = {
    "Read": "right.read",
    "Insert": "right.insert",
    "Update": "right.update",
    "Delete": "right.delete",
    "Posting": "right.posting",
    "UndoPosting": "right.undo_posting",
    "View": "right.view",
    "InteractiveInsert": "right.interactive_insert",
    "Edit": "right.edit",
    "InteractiveSetDeletionMark": "right.interactive_set_deletion_mark",
    "InteractiveClearDeletionMark": "right.interactive_clear_deletion_mark",
    "InteractivePosting": "right.interactive_posting",
}

_ENUM_I18N: dict[tuple[str, str], str] = {
    ("schema_type", "string"): "enum.common.string",
    ("schema_type", "number"): "enum.common.number",
    ("schema_type", "bool"): "enum.common.bool",
    ("schema_type", "date"): "enum.common.date",
    ("schema_type", "datetime"): "enum.common.datetime",
    ("schema_type", "ref"): "enum.common.ref",
    ("schema_type", "enum_ref"): "enum.common.enum_ref",
    ("schema_type", "any_ref"): "enum.common.any_ref",
    ("schema_type", "unknown"): "enum.common.unknown",
    ("number_type", "string"): "enum.common.string",
    ("number_type", "number"): "enum.common.number",
    ("number_periodicity", "year"): "enum.common.year",
    ("number_periodicity", "quarter"): "enum.common.quarter",
    ("number_periodicity", "month"): "enum.common.month",
    ("number_periodicity", "day"): "enum.common.day",
    ("number_periodicity", "none"): "enum.common.none",
    ("posting", "allow"): "enum.common.allow",
    ("posting", "forbid"): "enum.common.forbid",
    ("posting", "not_supported"): "enum.common.not_supported",
    ("register_records_deletion", "auto_delete_off"): "enum.register_records_deletion.auto_delete_off",
    ("register_records_deletion", "auto_delete_on"): "enum.register_records_deletion.auto_delete_on",
    ("register_records_writing", "write_selected"): "enum.register_records_writing.write_selected",
    ("register_records_writing", "write_all"): "enum.register_records_writing.write_all",
    ("sequence_filling", "auto_fill_off"): "enum.sequence_filling.auto_fill_off",
    ("sequence_filling", "auto_fill_on"): "enum.sequence_filling.auto_fill_on",
    ("toggle_mode", "use"): "enum.common.use",
    ("toggle_mode", "dont_use"): "enum.common.dont_use",
    ("toggle_mode", "auto"): "enum.common.auto",
    ("search_string_mode", "begin"): "enum.common.begin",
    ("search_string_mode", "any_part"): "enum.common.any_part",
    ("choice_data_get_mode", "directly"): "enum.common.directly",
    ("choice_data_get_mode", "on_demand"): "enum.common.on_demand",
    ("data_lock_control_mode", "automatic"): "enum.common.automatic",
    ("data_lock_control_mode", "managed"): "enum.common.managed",
    ("fill_checking", ""): "enum.fill_checking.default",
    ("fill_checking", "DontCheck"): "enum.fill_checking.dont_check",
    ("fill_checking", "ShowError"): "enum.fill_checking.show_error",
    ("fill_checking", "ShowWarning"): "enum.fill_checking.show_warning",
    ("auto_record", "allow"): "enum.auto_record.allow",
    ("auto_record", "deny"): "enum.auto_record.deny",
}


def _localized_enum_label(group: str, value: Any) -> str:
    raw = str(value or "")
    key = _ENUM_I18N.get((str(group or "").strip().lower(), raw))
    if key:
        return t(key)
    key = _ENUM_I18N.get((str(group or "").strip().lower(), raw.strip().lower()))
    if key:
        return t(key)
    return raw


def _localized_right_name(name: Any) -> str:
    raw = str(name or "").strip()
    key = _RIGHTS_I18N.get(raw)
    return t(key) if key else raw


@lru_cache(maxsize=128)
def _load_document_workspace_links(doc_ref: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "functional_options": [],
        "journals": [],
        "sequences": [],
        "exchange_plans": [],
    }
    target = str(doc_ref or "").strip()
    if not target:
        return out

    root = _workspace_xml_dump_root()
    if root is None:
        return out

    exact_token = f">{target}<"
    prefix_token = f"{target}."

    journals_dir = root / "DocumentJournals"
    if journals_dir.exists():
        for path in journals_dir.rglob("*.xml"):
            try:
                if exact_token in _safe_read_text(path):
                    _append_unique(out["journals"], path.stem)
            except Exception:
                continue

    sequences_dir = root / "Sequences"
    if sequences_dir.exists():
        for path in sequences_dir.rglob("*.xml"):
            try:
                if exact_token in _safe_read_text(path):
                    _append_unique(out["sequences"], path.stem)
            except Exception:
                continue

    functional_options_dir = root / "FunctionalOptions"
    if functional_options_dir.exists():
        for path in functional_options_dir.rglob("*.xml"):
            try:
                text = _safe_read_text(path)
                if exact_token in text or prefix_token in text:
                    _append_unique(out["functional_options"], path.stem)
            except Exception:
                continue

    exchange_plans_dir = root / "ExchangePlans"
    if exchange_plans_dir.exists():
        for path in exchange_plans_dir.rglob("Content.xml"):
            try:
                text = _safe_read_text(path)
                if exact_token not in text:
                    continue
                plan_name = path.parent.parent.name
                auto_record = ""
                try:
                    ns = {"xp": "http://v8.1c.ru/8.3/xcf/extrnprops"}
                    tree = ET.fromstring(text)
                    for item in tree.findall("xp:Item", ns):
                        metadata = str(item.findtext("xp:Metadata", default="", namespaces=ns) or "").strip()
                        if metadata != target:
                            continue
                        auto_record = str(item.findtext("xp:AutoRecord", default="", namespaces=ns) or "").strip()
                        break
                except Exception:
                    auto_record = ""
                _append_unique_exchange_plan(
                    out["exchange_plans"],
                    {"name": plan_name, "auto_record": auto_record},
                )
            except Exception:
                continue

    out["functional_options"].sort(key=str.casefold)
    out["journals"].sort(key=str.casefold)
    out["sequences"].sort(key=str.casefold)
    out["exchange_plans"].sort(key=lambda item: str(item.get("name") or "").casefold())
    return out


def _normalize_exchange_plan_items(value: Any) -> list[dict[str, str]]:
    items = value if isinstance(value, list) else []
    out: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            auto_record = str(item.get("auto_record") or "").strip()
            if name:
                _append_unique_exchange_plan(out, {"name": name, "auto_record": auto_record})
            continue
        text = str(item or "").strip()
        if not text:
            continue
        if text.endswith(")") and " (" in text:
            name, _, suffix = text.rpartition(" (")
            _append_unique_exchange_plan(
                out,
                {"name": name.strip(), "auto_record": suffix[:-1].strip()},
            )
            continue
        _append_unique_exchange_plan(out, {"name": text, "auto_record": ""})
    return out


@lru_cache(maxsize=128)
def _load_document_workspace_roles(doc_ref: str) -> list[dict[str, Any]]:
    target = str(doc_ref or "").strip()
    if not target:
        return []

    root = _workspace_xml_dump_root()
    if root is None:
        return []

    out: list[dict[str, Any]] = []
    roles_dir = root / "Roles"
    if not roles_dir.exists():
        return out

    ns = {"r": "http://v8.1c.ru/8.2/roles"}
    for path in roles_dir.rglob("Rights.xml"):
        try:
            text = _safe_read_text(path)
            if target not in text:
                continue
            role_name = path.parent.parent.name
            rights: list[tuple[str, bool]] = []
            has_related = False
            try:
                tree = ET.fromstring(text)
                for obj in tree.findall("r:object", ns):
                    name = str(obj.findtext("r:name", default="", namespaces=ns) or "").strip()
                    if not name.startswith(target):
                        continue
                    if name == target:
                        for right in obj.findall("r:right", ns):
                            right_name = str(right.findtext("r:name", default="", namespaces=ns) or "").strip()
                            right_value = str(
                                right.findtext("r:value", default="", namespaces=ns) or ""
                            ).strip().lower()
                            if right_name:
                                rights.append((right_name, right_value in {"true", "1", "yes"}))
                    else:
                        has_related = True
            except Exception:
                has_related = True
            if rights or has_related:
                out.append({"name": role_name, "rights": rights, "has_related": has_related})
        except Exception:
            continue

    out.sort(key=lambda item: str(item.get("name") or "").casefold())
    return out


def _merge_missing_payload_fields(payload: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    if not extra:
        return dict(payload)
    out = dict(payload)
    for key, value in extra.items():
        if key not in out or out.get(key) in (None, "", [], {}):
            out[key] = value
    return out


def _normalize_string_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _display_metadata_ref(value: Any, *, vm: Any | None = None) -> str:
    from src.configurator.domain.technical_names import technical_object_name

    text = str(value or "").strip()
    if not text:
        return ""
    parts = [part for part in text.split(".") if part]
    if vm is not None and len(parts) == 2:
        ref_kind = parts[0]
        ref_name = parts[1]
        obj_type = _METADATA_REF_KIND_TO_TYPE.get(ref_kind)
        if obj_type:
            try:
                list_by_type = getattr(vm, "list_objects_by_type", None)
                objs = (
                    list_by_type(obj_type)
                    if callable(list_by_type)
                    else vm.list_objects() or []
                )
                for obj in objs:
                    if str(getattr(obj, "type", "") or "").strip().lower() != obj_type:
                        continue
                    name = str(getattr(obj, "name", "") or "").strip()
                    technical = technical_object_name(name, payload=getattr(obj, "payload", None))
                    if ref_name.casefold() not in {name.casefold(), technical.casefold()}:
                        continue
                    return technical
            except Exception:
                pass
    if len(parts) >= 2:
        return parts[-1]
    return text


def _normalize_input_by_string(value: Any) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "numberdate": "number_date",
        "number_date": "number_date",
        "number": "number",
        "code": "code",
    }
    return mapping.get(raw, raw)


def _merge_named_items(existing: Any, updated: Any) -> list[dict]:
    existing_items = existing if isinstance(existing, list) else []
    updated_items = updated if isinstance(updated, list) else []
    existing_by_name: dict[str, dict[str, Any]] = {}
    for item in existing_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            existing_by_name[name.casefold()] = dict(item)

    out: list[dict] = []
    for item in updated_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        merged = dict(existing_by_name.get(name.casefold(), {}))
        merged.update(item)
        out.append(merged)
    return out


def _merge_tabular_parts(existing: Any, updated: Any) -> list[dict]:
    existing_parts = existing if isinstance(existing, list) else []
    updated_parts = updated if isinstance(updated, list) else []
    existing_by_name: dict[str, dict[str, Any]] = {}
    for item in existing_parts:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            existing_by_name[name.casefold()] = dict(item)

    out: list[dict] = []
    for item in updated_parts:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        base = dict(existing_by_name.get(name.casefold(), {}))
        merged = dict(base)
        merged.update({k: v for k, v in item.items() if k != "columns"})
        merged["columns"] = _merge_named_items(base.get("columns"), item.get("columns"))
        out.append(merged)
    return out


@dataclass(frozen=True, slots=True)
class DocumentPayload:
    """Best-effort typed view over document payload."""

    name: str = ""
    synonym: str = ""
    comment: str = ""
    hint: str = ""
    object_presentation: str = ""
    extended_object_presentation: str = ""
    list_presentation: str = ""
    extended_list_presentation: str = ""
    explanation: str = ""
    use_standard_commands: bool = True
    numerator: str = ""
    number_type: str = "string"
    number_allowed_length: str = "fixed"
    number_length: int = 11
    number_periodicity: str = "year"
    autonumbering: bool = True
    check_unique: bool = True
    posting: str = "allow"
    real_time_posting: str = "allow"
    register_records_deletion: str = "auto_delete_off"
    register_records_writing_on_post: str = "write_selected"
    sequence_filling: str = "auto_fill_off"
    input_by_string: str = ""
    input_by_string_field: str = ""
    create_on_input: str = "use"
    search_string_mode_on_input_by_string: str = "begin"
    full_text_search_on_input_by_string: str = "dont_use"
    choice_data_get_mode_on_input_by_string: str = "directly"
    choice_history_on_input: str = "dont_use"
    fill_checking: str = "DontCheck"
    full_text_search: str = "dont_use"
    data_history: str = "dont_use"
    update_data_history_immediately_after_write: bool = False
    execute_after_write_data_history_version_processing: bool = False
    post_in_privileged_mode: bool = False
    unpost_in_privileged_mode: bool = False
    include_help_in_contents: bool = False
    data_lock_fields: str = ""
    data_lock_control_mode: str = "automatic"
    default_object_form: str = ""
    default_list_form: str = ""
    default_choice_form: str = ""
    based_on: list[str] = field(default_factory=list)
    register_records: list[str] = field(default_factory=list)
    posting_handler: str = ""
    document_journals: list[str] = field(default_factory=list)
    sequence_memberships: list[str] = field(default_factory=list)
    exchange_plans: list[dict[str, str]] = field(default_factory=list)
    subsystems: list[str] = field(default_factory=list)
    requisites: list[dict] = field(default_factory=list)
    tabular_parts: list[dict] = field(default_factory=list)

    @staticmethod
    def from_payload(payload: Any) -> "DocumentPayload":
        p = payload if isinstance(payload, dict) else {}
        return DocumentPayload(
            name=str(p.get("name") or ""),
            synonym=_localized_text(_pick_payload_value(p, "synonym", "title")),
            comment=_localized_text(p.get("comment")),
            hint=_localized_text(_pick_payload_value(p, "hint", "tool_tip")),
            object_presentation=_localized_text(_pick_payload_value(p, "object_presentation", "main_presentation")),
            extended_object_presentation=_localized_text(_pick_payload_value(p, "extended_object_presentation")),
            list_presentation=_localized_text(_pick_payload_value(p, "list_presentation")),
            extended_list_presentation=_localized_text(_pick_payload_value(p, "extended_list_presentation")),
            explanation=_localized_text(_pick_payload_value(p, "explanation")),
            use_standard_commands=_as_bool(_pick_payload_value(p, "use_standard_commands", default=True)),
            numerator=str(_pick_payload_value(p, "numerator") or ""),
            number_type=str(_pick_payload_value(p, "number_type", default="string") or "string").strip().lower(),
            number_allowed_length=str(
                _pick_payload_value(p, "number_allowed_length", default="fixed") or "fixed"
            ).strip().lower(),
            number_length=_as_int(_pick_payload_value(p, "number_length", "number_len", default=11), 11),
            number_periodicity=str(_pick_payload_value(p, "number_periodicity", default="year") or "year")
            .strip()
            .lower(),
            autonumbering=_as_bool(_pick_payload_value(p, "autonumbering", "autonumber", default=True)),
            check_unique=_as_bool(_pick_payload_value(p, "check_unique", default=True)),
            posting=str(_pick_payload_value(p, "posting", default="allow") or "allow").strip().lower(),
            real_time_posting=str(_pick_payload_value(p, "real_time_posting", default="allow") or "allow")
            .strip()
            .lower(),
            register_records_deletion=str(
                _pick_payload_value(p, "register_records_deletion", default="auto_delete_off")
                or "auto_delete_off"
            )
            .strip()
            .lower(),
            register_records_writing_on_post=str(
                _pick_payload_value(p, "register_records_writing_on_post", default="write_selected")
                or "write_selected"
            )
            .strip()
            .lower(),
            sequence_filling=str(_pick_payload_value(p, "sequence_filling", default="auto_fill_off") or "auto_fill_off")
            .strip()
            .lower(),
            input_by_string=_normalize_input_by_string(_pick_payload_value(p, "input_by_string", default="")),
            input_by_string_field=str(_pick_payload_value(p, "input_by_string_field") or ""),
            create_on_input=str(_pick_payload_value(p, "create_on_input", default="use") or "use").strip().lower(),
            search_string_mode_on_input_by_string=str(
                _pick_payload_value(p, "search_string_mode_on_input_by_string", default="begin") or "begin"
            )
            .strip()
            .lower(),
            full_text_search_on_input_by_string=str(
                _pick_payload_value(p, "full_text_search_on_input_by_string", default="dont_use") or "dont_use"
            )
            .strip()
            .lower(),
            choice_data_get_mode_on_input_by_string=str(
                _pick_payload_value(p, "choice_data_get_mode_on_input_by_string", default="directly")
                or "directly"
            )
            .strip()
            .lower(),
            choice_history_on_input=str(
                _pick_payload_value(p, "choice_history_on_input", default="dont_use") or "dont_use"
            )
            .strip()
            .lower(),
            fill_checking=str(_pick_payload_value(p, "fill_checking", "fill_check", default="DontCheck") or "DontCheck"),
            full_text_search=str(_pick_payload_value(p, "full_text_search", default="dont_use") or "dont_use")
            .strip()
            .lower(),
            data_history=str(_pick_payload_value(p, "data_history", default="dont_use") or "dont_use")
            .strip()
            .lower(),
            update_data_history_immediately_after_write=_as_bool(
                _pick_payload_value(p, "update_data_history_immediately_after_write", default=False)
            ),
            execute_after_write_data_history_version_processing=_as_bool(
                _pick_payload_value(p, "execute_after_write_data_history_version_processing", default=False)
            ),
            post_in_privileged_mode=_as_bool(_pick_payload_value(p, "post_in_privileged_mode", default=False)),
            unpost_in_privileged_mode=_as_bool(_pick_payload_value(p, "unpost_in_privileged_mode", default=False)),
            include_help_in_contents=_as_bool(_pick_payload_value(p, "include_help_in_contents", default=False)),
            data_lock_fields=str(_pick_payload_value(p, "data_lock_fields") or ""),
            data_lock_control_mode=str(
                _pick_payload_value(p, "data_lock_control_mode", default="automatic") or "automatic"
            )
            .strip()
            .lower(),
            default_object_form=str(_pick_payload_value(p, "default_object_form") or ""),
            default_list_form=str(_pick_payload_value(p, "default_list_form") or ""),
            default_choice_form=str(_pick_payload_value(p, "default_choice_form") or ""),
            based_on=_normalize_string_list(_pick_payload_value(p, "based_on", default=[])),
            register_records=_normalize_string_list(_pick_payload_value(p, "register_records", default=[])),
            posting_handler=str(_pick_payload_value(p, "posting_handler", default="") or ""),
            document_journals=_normalize_string_list(
                _pick_payload_value(p, "document_journals", default=[])
            ),
            sequence_memberships=_normalize_string_list(
                _pick_payload_value(p, "sequence_memberships", default=[])
            ),
            exchange_plans=_normalize_exchange_plan_items(
                _pick_payload_value(p, "exchange_plans", default=[])
            ),
            subsystems=_parse_subsystems(p.get("subsystems")),
            requisites=list(p.get("requisites") or p.get("attributes") or []),
            tabular_parts=list(p.get("tabular_parts") or []),
        )
