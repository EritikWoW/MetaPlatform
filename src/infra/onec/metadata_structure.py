from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


_OBJ_TYPE_TO_STORAGE_FAMILY: dict[str, str] = {
    "business_process": "business_process",
    "catalog": "catalog",
    "chart_of_accounts": "chart_of_accounts",
    "chart_of_calculation_types": "chart_of_calculation_types",
    "chart_of_characteristic_types": "chart_of_characteristic_types",
    "constants": "constant",
    "document": "document",
    "register_accum": "accumulation_register",
    "register_accounting": "accounting_register",
    "register_calc": "calculation_register",
    "register_info": "information_register",
    "task": "task",
}

_PRESENTATION_KEYS = (
    "title",
    "object_presentation",
    "extended_object_presentation",
    "object_presentation_ext",
    "list_presentation",
    "extended_list_presentation",
    "list_presentation_ext",
    "hint",
    "explanation",
    "picture_ref",
    "picture_guid",
)
_SCHEMA_KEYS = (
    "requisites",
    "attributes",
    "dimensions",
    "resources",
    "tabular_parts",
    "enum_values",
)
_FORM_KEYS = (
    "default_object_form",
    "default_list_form",
    "default_choice_form",
)
_BEHAVIOR_KEYS = (
    "use_standard_commands",
    "number_type",
    "number_allowed_length",
    "number_length",
    "number_periodicity",
    "check_unique",
    "autonumbering",
    "posting",
    "real_time_posting",
    "register_records_deletion",
    "register_records_writing_on_post",
    "sequence_filling",
    "input_by_string",
    "create_on_input",
    "search_string_mode_on_input_by_string",
    "full_text_search_on_input_by_string",
    "choice_data_get_mode_on_input_by_string",
    "choice_history_on_input",
    "full_text_search",
    "data_history",
    "update_data_history_immediately_after_write",
    "execute_after_write_data_history_version_processing",
    "post_in_privileged_mode",
    "unpost_in_privileged_mode",
    "include_help_in_contents",
    "include_in_command_interface",
    "use_one_command",
    "data_lock_fields",
    "data_lock_control_mode",
)
_COMPOSITION_KEYS = (
    "owners",
    "based_on",
    "register_records",
    "content_refs",
    "child_subsystems",
    "objects",
    "help_pages",
)


def storage_family_for_obj_type(obj_type: str) -> str:
    return _OBJ_TYPE_TO_STORAGE_FAMILY.get(str(obj_type or "").strip().lower(), "")


def _preview_scalar(value: Any, *, limit: int = 120) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    return text[:limit].rstrip() + ("..." if len(text) > limit else "")


def _preview_mapping(value: Dict[str, Any], *, limit: int = 4) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key in list(value.keys())[:limit]:
        out[str(key)] = _preview_scalar(value.get(key))
    return out


def _preview_collection(values: Iterable[Any], *, limit: int = 5) -> list[str]:
    preview: list[str] = []
    for item in list(values)[:limit]:
        if isinstance(item, dict):
            label = (
                item.get("name")
                or item.get("title")
                or item.get("key")
                or item.get("field")
                or item.get("target_field")
                or item.get("source_field")
            )
            if isinstance(label, dict):
                label = next((v for v in label.values() if isinstance(v, str) and v.strip()), "")
            preview.append(_preview_scalar(label or item))
        else:
            preview.append(_preview_scalar(item))
    return [item for item in preview if item]


def _summarize_payload_value(key: str, value: Any) -> Dict[str, Any]:
    if isinstance(value, list):
        return {
            "key": key,
            "kind": "collection",
            "count": len(value),
            "preview": _preview_collection(value),
        }
    if isinstance(value, dict):
        scalar_values = all(not isinstance(item, (dict, list)) for item in value.values())
        summary: Dict[str, Any] = {
            "key": key,
            "kind": "mapping",
            "count": len(value),
        }
        if scalar_values:
            summary["preview"] = _preview_mapping(value)
        else:
            summary["preview_keys"] = [str(item) for item in list(value.keys())[:6]]
        return summary
    return {
        "key": key,
        "kind": "scalar",
        "value": _preview_scalar(value),
    }


def build_storage_profile(
    *,
    blueprint: Dict[str, Any] | None,
    family_templates: Dict[str, Any] | None,
    meta_platform_templates: Dict[str, Any] | None,
) -> Dict[str, Any]:
    if not blueprint:
        return {}

    family = str(blueprint.get("family") or "").strip()
    template_key = str(blueprint.get("template_key") or "").strip()
    preferred_source_kind = str(blueprint.get("preferred_source_kind") or "").strip()
    observed = dict(blueprint.get("observed_source_tables") or {})
    family_template = dict((family_templates or {}).get(template_key) or {})

    mp_template_key = family
    if family in {
        "accumulation_register",
        "information_register",
        "accounting_register",
        "calculation_register",
    }:
        mp_template_key = "register"
    meta_template = dict((meta_platform_templates or {}).get(mp_template_key) or {})

    return {
        "family": family,
        "mapping_confidence": str(blueprint.get("mapping_confidence") or ""),
        "preferred_source_kind": preferred_source_kind,
        "target_tables": list(blueprint.get("target_tables") or []),
        "target_table_pattern": str(meta_template.get("target_table_pattern") or ""),
        "system_fields": list(meta_template.get("system_fields") or []),
        "observed_source_tables": {
            "count": int(observed.get("count") or 0),
            "examples": list(observed.get("examples") or []),
            "token_examples": list(observed.get("token_examples") or []),
        },
        "field_aliases": {
            "slots": dict(family_template.get("slot_examples") or {}),
            "targets": dict(family_template.get("target_fields") or {}),
        },
    }


def build_metadata_structure(
    *,
    obj_type: str,
    name: str,
    payload: Dict[str, Any],
    metadata_ref: str = "",
    storage_profile: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    imported = payload.get("imported") if isinstance(payload.get("imported"), dict) else {}
    sections: list[Dict[str, Any]] = []

    def add_section(section_key: str, keys: Iterable[str]) -> None:
        items = [
            _summarize_payload_value(key, payload.get(key))
            for key in keys
            if key in payload
        ]
        if items:
            sections.append({"key": section_key, "items": items})

    identity_items = [
        {"key": "name", "kind": "scalar", "value": str(name or "")},
        {"key": "obj_type", "kind": "scalar", "value": str(obj_type or "")},
    ]
    if metadata_ref:
        identity_items.append({"key": "metadata_ref", "kind": "scalar", "value": metadata_ref})
    origin = str(imported.get("origin") or "").strip()
    if origin:
        identity_items.append({"key": "origin", "kind": "scalar", "value": origin})
    if identity_items:
        sections.append({"key": "identity", "items": identity_items})

    add_section("presentation", _PRESENTATION_KEYS)
    add_section("schema", _SCHEMA_KEYS)
    add_section("forms", _FORM_KEYS)
    add_section("behavior", _BEHAVIOR_KEYS)
    add_section("composition", _COMPOSITION_KEYS)

    if storage_profile:
        sections.append(
            {
                "key": "storage",
                "items": [
                    _summarize_payload_value("family", storage_profile.get("family")),
                    _summarize_payload_value("mapping_confidence", storage_profile.get("mapping_confidence")),
                    _summarize_payload_value("preferred_source_kind", storage_profile.get("preferred_source_kind")),
                    _summarize_payload_value("target_tables", storage_profile.get("target_tables")),
                    _summarize_payload_value("target_table_pattern", storage_profile.get("target_table_pattern")),
                    _summarize_payload_value("system_fields", storage_profile.get("system_fields")),
                    _summarize_payload_value(
                        "observed_source_tables",
                        storage_profile.get("observed_source_tables"),
                    ),
                    _summarize_payload_value("field_aliases", storage_profile.get("field_aliases")),
                ],
            }
        )

    return {
        "source": "1c",
        "obj_type": str(obj_type or ""),
        "name": str(name or ""),
        "metadata_ref": metadata_ref,
        "sections": sections,
    }


def apply_onec_structural_metadata(db, mapping_report: Dict[str, Any] | None) -> int:
    if not isinstance(mapping_report, dict):
        return 0

    from src.configurator.persistence import manifest_io
    from .onec_requisites_enrich import metadata_ref_for_manifest_object

    try:
        objects = manifest_io.list_objects(db)
    except Exception:
        return 0

    blueprints = list(mapping_report.get("object_migration_blueprints") or [])
    family_templates = dict(mapping_report.get("family_templates") or {})
    meta_platform_templates = dict(mapping_report.get("meta_platform_templates") or {})

    blueprint_index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for blueprint in blueprints:
        family = str(blueprint.get("family") or "").strip()
        name = str(blueprint.get("name") or "").strip()
        if family and name:
            blueprint_index[(family, name.casefold())] = dict(blueprint)

    payloads_by_guid: Dict[str, Dict[str, Any]] = {}
    for obj in objects:
        if str(getattr(obj, "kind", "") or "") != "object":
            continue
        payload = obj.payload if isinstance(obj.payload, dict) else {}
        imported = payload.get("imported") if isinstance(payload.get("imported"), dict) else {}
        if str(imported.get("source") or "").strip().lower() != "1c":
            continue

        origin = str(imported.get("origin") or "").strip()
        metadata_ref = metadata_ref_for_manifest_object(
            obj_type=str(obj.type or ""),
            name=str(obj.name or ""),
            origin_path=origin,
        )
        family = storage_family_for_obj_type(str(obj.type or ""))
        blueprint = blueprint_index.get((family, str(obj.name or "").casefold()))
        storage_profile = build_storage_profile(
            blueprint=blueprint,
            family_templates=family_templates,
            meta_platform_templates=meta_platform_templates,
        )

        updated_payload = dict(payload)
        if metadata_ref:
            updated_payload["metadata_ref"] = metadata_ref
        if storage_profile:
            updated_payload["storage_profile"] = storage_profile
        updated_payload["metadata_structure"] = build_metadata_structure(
            obj_type=str(obj.type or ""),
            name=str(obj.name or ""),
            payload=updated_payload,
            metadata_ref=metadata_ref,
            storage_profile=storage_profile,
        )
        if updated_payload != payload:
            payloads_by_guid[str(obj.guid or "")] = updated_payload

    if not payloads_by_guid:
        return 0
    return int(manifest_io.bulk_update_payloads(db, payloads_by_guid) or 0)


__all__ = [
    "apply_onec_structural_metadata",
    "build_metadata_structure",
    "build_storage_profile",
    "storage_family_for_obj_type",
]
