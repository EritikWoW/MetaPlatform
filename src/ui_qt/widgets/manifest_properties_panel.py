from __future__ import annotations

import json
from typing import Any, Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QToolButton,
    QWidget,
)

from src.configurator.domain.technical_names import technical_object_name

from src.ui_qt.i18n import t

FieldDef = tuple[Any, ...]

_TYPE_ALIASES = {
    "accumulation_registers": "register_accum",
    "common_commands": "common_command",
    "common_forms": "common_form",
    "common_layouts": "common_layout",
    "common_modules": "common_module",
    "common_pictures": "common_picture",
    "document_journals": "journal",
    "document_numerators": "document_numerator",
    "exchange_plans": "exchange_plan",
    "http_services": "http_service",
    "info_registers": "register_info",
    "languages": "language",
    "roles": "role",
    "session_parameter": "session_param",
    "session_params": "session_param",
    "sequences": "sequence",
    "styles": "style",
    "subsystems": "subsystem",
    "web_services": "web_service",
    "schema_attribute": "schema_requisite",
    "schema_column": "schema_requisite",
    "schema_dimension": "schema_requisite",
    "schema_resource": "schema_requisite",
}

_SKIP_DYNAMIC_KEYS = {
    "asset_key",
    "children",
    "code",
    "columns",
    "dsl",
    "dump_info_children",
    "enum_values_ref",
    "fields",
    "form_model",
    "form_model_ref",
    "imported",
    "items",
    "node_id",
    "nodes",
    "metadata_structure",
    "owner_guid",
    "requisites_ref",
    "source_path",
    "storage_profile",
    "storage_path",
    "system",
    "startup_modules",
    "tabular_parts_ref",
    "title",
}

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "author": ("author", "developer"),
    "compatibility_mode": ("compatibility_mode", "compatibility"),
    "configuration_address": ("configuration_address", "config_address", "config_url"),
    "copyright": ("copyright", "rights"),
    "editing_format": ("editing_format", "edit_format", "format_editing", "format_editor"),
    "default_language": ("default_language", "main_language", "language"),
    "help_info": ("help_info", "help", "reference_info"),
    "hint": ("hint", "tooltip", "help_text"),
    "main_interface": ("main_interface", "interface"),
    "main_language": ("main_language", "default_language", "language"),
    "main_style": ("main_style", "style"),
    "managed_application_module": ("managed_application_module", "startup_modules", "startup_module", "module"),
    "module": ("module", "asset_key", "module_asset_key", "object_module", "manager_module", "module_manager", "module_manager_value", "value_module"),
    "module_manager": ("module_manager", "manager_module"),
    "module_manager_value": ("module_manager_value", "manager_module_value", "value_module"),
    "ordinary_application_module": ("ordinary_application_module",),
    "session_module": ("session_module",),
    "code_length": ("code_length", "code_len"),
    "code_len": ("code_len", "code_length"),
    "name_length": ("name_length", "description_len"),
    "code_type": ("code_type",),
    "hierarchy_type": ("hierarchy_type", "hierarchy"),
    "levels_count": ("levels_count", "levels"),
    "limit_levels": ("limit_levels", "limit_level"),
    "place_groups_top": ("place_groups_top", "place_groups_at_top"),
    "obj_presentation": ("obj_presentation", "object_presentation"),
    "obj_presentation_ext": ("obj_presentation_ext", "extended_object_presentation", "object_presentation_ext"),
    "list_presentation": ("list_presentation",),
    "list_presentation_ext": ("list_presentation_ext", "extended_list_presentation", "extended_list_presentation_ext"),
    "type_link": ("type_link", "type_link_ref", "link_by_type"),
    "default_report_form": ("default_report_form", "report_form"),
    "default_report_settings_form": ("default_report_settings_form", "report_settings_form"),
    "default_report_variant_form": ("default_report_variant_form", "report_variant_form"),
    "default_dynamic_list_settings_form": ("default_dynamic_list_settings_form", "dynamic_list_settings_form"),
    "default_constants_form": ("default_constants_form", "constants_form"),
    "default_search_form": ("default_search_form", "search_form"),
    "default_change_history_form": ("default_change_history_form", "change_history_form"),
    "default_data_history_form": ("default_data_history_form", "data_history_form"),
    "default_data_history_difference_form": ("default_data_history_difference_form", "data_history_difference_form"),
    "default_user_selection_form": ("default_user_selection_form", "user_selection_form"),
    "main_report_layout": ("main_report_layout", "report_layout"),
    "supplier_address": ("supplier_address", "vendor_address"),
    "update_address": ("update_address", "update_catalog", "update_url"),
    "vendor": ("vendor", "supplier"),
    "version": ("version", "config_version"),
    "number_length": ("number_length", "number_len"),
    "autonumbering": ("autonumbering", "autonumber"),
    "input_by_string": ("input_by_string", "input_by"),
    "fill_checking": ("fill_checking", "fill_check"),
    "use_one_command": ("use_one_command",),
}

_MODULE_REF_KEYS = {
    "managed_application_module",
    "external_connection_module",
    "ordinary_application_module",
    "session_module",
}

_BASIC_FIELDS: list[FieldDef] = [
    ("__section__", "section_basic", None),
    ("__name__", "prop_name", "line"),
    ("synonym", "prop_synonym", "line"),
    ("comment", "prop_comment", "text"),
]

_READONLY_SYSTEM_FIELDS: list[FieldDef] = [
    ("__section__", "section_system", None),
    ("__guid__", "prop_guid", "readonly"),
    ("__type__", "prop_type", "readonly"),
    ("__subtype__", "prop_subtype", "readonly"),
    ("__parent_guid__", "prop_parent_guid", "readonly"),
]

_STD_FORM_FIELDS: list[FieldDef] = [
    ("default_list_form", "prop_default_list_form", "line"),
    ("default_object_form", "prop_default_object_form", "line"),
    ("default_choice_form", "prop_default_choice_form", "line"),
    ("use_standard_commands", "prop_use_std_commands", "check"),
]

_CONFIGURATION_FORM_FIELDS: list[FieldDef] = [
    ("default_report_form", "prop_default_report_form", "line"),
    ("default_report_settings_form", "prop_default_report_settings_form", "line"),
    ("default_report_variant_form", "prop_default_report_variant_form", "line"),
    ("default_dynamic_list_settings_form", "prop_default_dynamic_list_settings_form", "line"),
    ("default_constants_form", "prop_default_constants_form", "line"),
    ("default_search_form", "prop_default_search_form", "line"),
    ("default_change_history_form", "prop_default_change_history_form", "line"),
    ("default_data_history_form", "prop_default_data_history_form", "line"),
    ("default_data_history_difference_form", "prop_default_data_history_difference_form", "line"),
    ("default_user_selection_form", "prop_default_user_selection_form", "line"),
    ("main_report_layout", "prop_main_report_layout", "line"),
]

_CONFIGURATION_DEVELOPMENT_FIELDS: list[FieldDef] = [
    ("author", "prop_author", "line"),
    ("vendor", "prop_vendor", "line"),
    ("version", "prop_version", "line"),
    ("update_address", "prop_update_address", "line"),
]

_CONFIGURATION_HELP_FIELDS: list[FieldDef] = [
    ("include_help_in_contents", "prop_include_help", "check"),
    ("help_info", "prop_help_info", "readonly_text"),
]

_CONFIGURATION_COMPAT_FIELDS: list[FieldDef] = [
    ("data_lock_control_mode", "prop_data_lock_control_mode", "combo", ["automatic", "managed"]),
    ("binary_data_storage_mode", "prop_binary_data_storage_mode", "combo", ["use", "dont_use"]),
    ("binary_data_storage_usage_mode", "prop_binary_data_storage_usage_mode", "combo", ["use", "dont_use"]),
    ("autonumbering_mode", "prop_autonumbering_mode", "combo", ["use", "dont_use"]),
    ("modality_mode", "prop_modality_mode", "combo", ["use", "dont_use"]),
    ("sync_calls_mode", "prop_sync_calls_mode", "combo", ["use", "dont_use"]),
    ("tabular_spaces_mode", "prop_tabular_spaces_mode", "combo", ["use", "dont_use"]),
    ("interface_mode", "prop_interface_mode", "line"),
    ("compatibility_mode", "prop_compatibility_mode", "combo", ["1.0", "8.1", "8.2", "8.3", "8.3.12", "8.3.13", "8.3.14", "8.3.15", "8.3.16"]),
]

_COMMON_ATTRIBUTE_MODULE_FIELDS: list[FieldDef] = [
    ("module", "prop_module", "readonly_text"),
    ("module_manager", "prop_module_manager", "readonly_text"),
    ("module_manager_value", "prop_module_manager_value", "readonly_text"),
]

_COMMON_ATTRIBUTE_DATA_FIELDS: list[FieldDef] = [
    ("type", "prop_type", "line"),
    ("data_type", "prop_data_type", "line"),
    ("length", "prop_length", "line"),
    ("precision", "prop_precision", "line"),
    ("format", "prop_format", "line"),
    ("editing_format", "prop_editing_format", "line"),
    ("hint", "prop_hint", "text"),
    ("type_link", "prop_type_link", "line"),
]

_COMMON_ATTRIBUTE_BEHAVIOR_FIELDS: list[FieldDef] = [
    ("fill_check", "prop_fill_check", "check"),
    ("check_unique", "prop_check_unique", "check"),
    ("quick_choice", "prop_quick_choice", "check"),
    ("input_by_string", "prop_input_by_string_field", "line"),
    ("use_standard_commands", "prop_use_std_commands", "check"),
    ("full_text_search", "prop_full_text_search", "combo", ["use", "dont_use", "auto"]),
    ("data_history", "prop_data_history", "combo", ["use", "dont_use", "auto"]),
    ("update_data_history_immediately_after_write", "prop_update_data_history", "check"),
    ("execute_after_write_data_history_version_processing", "prop_execute_after_write_history", "check"),
    ("data_lock_control_mode", "prop_data_lock_control_mode", "combo", ["automatic", "managed"]),
]

_COMMON_ATTRIBUTE_PRESENTATION_FIELDS: list[FieldDef] = [
    ("main_presentation", "prop_main_presentation", "line"),
    ("obj_presentation", "prop_object_presentation", "line"),
    ("obj_presentation_ext", "prop_object_presentation_ext", "line"),
    ("list_presentation", "prop_list_presentation", "line"),
    ("list_presentation_ext", "prop_list_presentation_ext", "line"),
    ("explanation", "prop_explanation", "text"),
]

_SCHEMA_REQUISITE_FIELDS: list[FieldDef] = [
    *_BASIC_FIELDS,
    ("__section__", "section_data", None),
    ("type", "prop_data_type", "combo", ["string", "number", "bool", "datetime", "ref", "enum_ref", "any_ref", "unknown"]),
    ("source_type", "prop_source_type", "readonly"),
    ("ref_name", "prop_ref_name", "line"),
    ("string_length", "prop_string_length", "line"),
    ("number_digits", "prop_number_digits", "line"),
    ("number_fraction_digits", "prop_number_fraction_digits", "line"),
    ("format", "prop_format", "line"),
    ("editing_format", "prop_editing_format", "line"),
    ("mask", "prop_mask", "line"),
    ("mark_negatives", "prop_mark_negatives", "check"),
    ("multi_line", "prop_multi_line", "check"),
    ("password_mode", "prop_password_mode", "check"),
    ("extended_edit", "prop_extended_edit", "check"),
    ("__section__", "section_usage", None),
    ("indexing", "prop_indexing", "combo", ["DontIndex", "Index", "IndexWithAdditionalOrder"]),
    ("full_text_search", "prop_full_text_search", "combo", ["Auto", "Use", "DontUse"]),
    ("data_history", "prop_data_history", "combo", ["Auto", "Use", "DontUse"]),
    ("__section__", "section_presentation", None),
    ("hint", "prop_hint", "text"),
    ("fill_from_filling_value", "prop_fill_from_filling_value", "check"),
    ("fill_value", "prop_fill_value", "line"),
    ("fill_checking", "prop_fill_check", "combo", ["DontCheck", "ShowError", "ShowWarning"]),
    ("choice_groups_elements", "prop_choice_groups_elements", "combo", ["Items", "Folders", "FoldersAndItems"]),
    ("parameter_links", "prop_parameter_links", "line"),
    ("choice_parameters", "prop_choice_parameters", "text"),
    ("choice_form", "prop_choice_form", "line"),
    ("quick_choice", "prop_quick_choice", "combo", ["Auto", "Use", "DontUse"]),
    ("create_on_input", "prop_create_on_input", "combo", ["Auto", "Use", "DontUse"]),
    ("choice_history_on_input", "prop_choice_history_on_input", "combo", ["Auto", "Use", "DontUse"]),
    ("type_link", "prop_type_link", "line"),
    ("required", "prop_required", "check"),
    ("read_only", "prop_read_only", "check"),
]

_SECTION_DEFS: dict[str, list[FieldDef]] = {
    "schema_requisite": _SCHEMA_REQUISITE_FIELDS,
    "schema_tabular_part": [
        *_BASIC_FIELDS,
        ("__section__", "section_data", None),
        ("read_only", "prop_read_only", "check"),
    ],
    "configuration": [
        *_BASIC_FIELDS,
        ("__section__", "section_presentation", None),
        ("brief_info", "prop_brief_info", "line"),
        ("detail_info", "prop_detail_info", "text"),
        ("main_presentation", "prop_main_presentation", "line"),
        ("main_interface", "prop_main_interface", "line"),
        ("main_style", "prop_main_style", "line"),
        ("main_language", "prop_main_language", "line"),
        ("logo", "prop_logo", "line"),
        ("splash", "prop_splash", "line"),
        ("copyright", "prop_copyright", "text"),
        ("supplier_address", "prop_supplier_address", "line"),
        ("configuration_address", "prop_configuration_address", "line"),
        ("__section__", "section_development", None),
        *_CONFIGURATION_DEVELOPMENT_FIELDS,
        ("__section__", "section_help", None),
        *_CONFIGURATION_HELP_FIELDS,
        ("__section__", "section_forms", None),
        *_CONFIGURATION_FORM_FIELDS,
        ("__section__", "section_behavior", None),
        ("include_in_command_interface", "prop_include_cmd_interface", "check"),
        ("command_interface", "prop_command_interface", "readonly_text"),
        ("managed_application_module", "prop_managed_application_module", "module_ref"),
        ("session_module", "prop_session_module", "module_ref"),
        ("external_connection_module", "prop_external_connection_module", "module_ref"),
        ("ordinary_application_module", "prop_ordinary_application_module", "module_ref"),
        ("__section__", "section_compatibility", None),
        *_CONFIGURATION_COMPAT_FIELDS,
        ("__section__", "section_standard", None),
        *_STD_FORM_FIELDS,
    ],
    "constant": [*_BASIC_FIELDS, ("__section__", "section_data", None), ("data_type", "prop_data_type", "line"), ("length", "prop_length", "line"), ("default_value", "prop_default_value", "line"), ("fill_check", "prop_fill_check", "check")],
    "constants": [*_BASIC_FIELDS, ("__section__", "section_data", None), ("data_type", "prop_data_type", "line"), ("length", "prop_length", "line"), ("default_value", "prop_default_value", "line"), ("fill_check", "prop_fill_check", "check")],
    "catalog": [
        *_BASIC_FIELDS,
        ("__section__", "section_data", None),
        ("hierarchical", "prop_hierarchical", "check"),
        ("hierarchy_type", "prop_hierarchy_type", "combo", ["hierarchy", "groups", "elements"]),
        ("limit_levels", "prop_limit_levels", "check"),
        ("levels_count", "prop_levels_count", "line"),
        ("place_groups_top", "prop_place_groups_top", "check"),
        ("owners", "prop_owners", "readonly_text"),
        ("code_length", "prop_code_len", "line"),
        ("name_length", "prop_name_length", "line"),
        ("code_type", "prop_code_type", "combo", ["string", "number"]),
        ("input_by", "prop_input_by", "combo", ["code", "description", "code_description"]),
        ("check_unique", "prop_check_unique", "check"),
        ("autonumbering", "prop_autonumber", "check"),
        ("quick_choice", "prop_quick_choice", "check"),
        ("fill_check", "prop_fill_check", "check"),
        ("__section__", "section_behavior", None),
        ("use_standard_commands", "prop_use_std_commands", "check"),
        ("input_by_string", "prop_input_by_string_field", "line"),
        ("create_on_input", "prop_create_on_input", "combo", ["use", "dont_use", "auto"]),
        ("search_string_mode_on_input_by_string", "prop_search_string_mode_on_input", "combo", ["begin", "any_part"]),
        ("full_text_search_on_input_by_string", "prop_full_text_search_on_input", "combo", ["use", "dont_use", "auto"]),
        ("choice_data_get_mode_on_input_by_string", "prop_choice_data_get_mode", "combo", ["directly", "on_demand"]),
        ("choice_history_on_input", "prop_choice_history_on_input", "combo", ["use", "dont_use", "auto"]),
        ("data_lock_fields", "prop_data_lock_fields", "line"),
        ("data_lock_control_mode", "prop_data_lock_control_mode", "combo", ["automatic", "managed"]),
        ("full_text_search", "prop_full_text_search", "combo", ["use", "dont_use", "auto"]),
        ("data_history", "prop_data_history", "combo", ["use", "dont_use", "auto"]),
        ("update_data_history_immediately_after_write", "prop_update_data_history", "check"),
        ("execute_after_write_data_history_version_processing", "prop_execute_after_write_history", "check"),
        ("__section__", "section_forms", None),
        ("default_object_form", "prop_default_object_form", "line"),
        ("default_list_form", "prop_default_list_form", "line"),
        ("default_choice_form", "prop_default_choice_form", "line"),
        ("main_object_form", "prop_main_object_form", "line"),
        ("main_group_form", "prop_main_group_form", "line"),
        ("main_list_form", "prop_main_list_form", "line"),
        ("main_choice_form", "prop_main_choice_form", "line"),
        ("additional_object_form", "prop_additional_object_form", "line"),
        ("additional_group_form", "prop_additional_group_form", "line"),
        ("additional_list_form", "prop_additional_list_form", "line"),
        ("additional_choice_form", "prop_additional_choice_form", "line"),
        ("__section__", "section_presentation", None),
        ("main_presentation", "prop_main_presentation", "line"),
        ("obj_presentation", "prop_object_presentation", "line"),
        ("obj_presentation_ext", "prop_object_presentation_ext", "line"),
        ("list_presentation", "prop_list_presentation", "line"),
        ("list_presentation_ext", "prop_list_presentation_ext", "line"),
        ("explanation", "prop_explanation", "text"),
        ("__section__", "section_help", None),
        ("include_help_in_contents", "prop_include_help", "check"),
        ("help_info", "prop_help_info", "readonly_text"),
        ("__section__", "section_standard", None),
        *_STD_FORM_FIELDS,
    ],
    "document": [*_BASIC_FIELDS, ("__section__", "section_data", None), ("number_length", "prop_number_len", "line"), ("number_periodicity", "prop_number_period", "combo", ["year", "quarter", "month", "day", "none"]), ("autonumbering", "prop_autonumber", "check"), ("posting", "prop_posting", "combo", ["allow", "forbid", "not_supported"]), ("input_by_string", "prop_input_by", "combo", ["number", "date", "number_date"]), ("fill_checking", "prop_fill_check", "check"), ("__section__", "section_presentation", None), ("object_presentation", "prop_object_presentation", "line"), ("extended_object_presentation", "prop_object_presentation_ext", "line"), ("list_presentation", "prop_list_presentation", "line"), ("extended_list_presentation", "prop_list_presentation_ext", "line"), ("explanation", "prop_explanation", "text"), ("__section__", "section_standard", None), *_STD_FORM_FIELDS],
    "journal": [*_BASIC_FIELDS],
    "enumeration": [*_BASIC_FIELDS, ("__section__", "section_standard", None), ("use_standard_commands", "prop_use_std_commands", "check")],
    "report": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("use_standard_commands", "prop_use_std_commands", "check"), ("main_presentation", "prop_main_presentation", "line"), ("explanation", "prop_explanation", "text"), ("__section__", "section_standard", None), ("default_list_form", "prop_default_list_form", "line")],
    "data_processor": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("use_standard_commands", "prop_use_std_commands", "check"), ("main_presentation", "prop_main_presentation", "line"), ("explanation", "prop_explanation", "text"), ("__section__", "section_standard", None), ("default_list_form", "prop_default_list_form", "line")],
    "register_info": [*_BASIC_FIELDS, ("__section__", "section_data", None), ("periodic", "prop_periodic", "check"), ("write_on_input_only", "prop_write_on_input", "check"), ("fill_check", "prop_fill_check", "check"), ("__section__", "section_standard", None), *_STD_FORM_FIELDS],
    "register_accum": [*_BASIC_FIELDS, ("__section__", "section_data", None), ("kind", "prop_reg_kind", "combo", ["balance", "turnover"]), ("periodic", "prop_periodic", "check"), ("fill_check", "prop_fill_check", "check"), ("__section__", "section_standard", None), *_STD_FORM_FIELDS],
    "register_accounting": [*_BASIC_FIELDS, ("__section__", "section_data", None), ("periodic", "prop_periodic", "check"), ("fill_check", "prop_fill_check", "check"), ("__section__", "section_standard", None), *_STD_FORM_FIELDS],
    "register_calc": [*_BASIC_FIELDS, ("__section__", "section_data", None), ("periodic", "prop_periodic", "check"), ("fill_check", "prop_fill_check", "check"), ("__section__", "section_standard", None), *_STD_FORM_FIELDS],
    "subsystem": [*_BASIC_FIELDS, ("__section__", "section_presentation", None), ("include_help_in_contents", "prop_include_help", "check"), ("include_in_command_interface", "prop_include_cmd_interface", "check"), ("use_one_command", "prop_use_one_command", "check"), ("picture_ref", "prop_picture_ref", "readonly_text"), ("command_interface", "prop_command_interface", "readonly_text"), ("explanation", "prop_explanation", "text")],
    "common_module": [*_BASIC_FIELDS, ("code_ref_uk", "prop_code_ref_uk", "readonly"), ("code_ref_en", "prop_code_ref_en", "readonly"), ("__section__", "section_behavior", None), ("module", "prop_module", "readonly_text"), ("global", "prop_global", "check"), ("client_managed", "prop_client_managed", "check"), ("server", "prop_server", "check"), ("external_conn", "prop_external_conn", "check"), ("privileged", "prop_privileged", "check")],
    "session_param": [*_BASIC_FIELDS, ("__section__", "section_data", None), ("data_type", "prop_data_type", "line"), ("length", "prop_length", "line"), ("fill_check", "prop_fill_check", "check")],
    "role": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("authentication", "prop_authentication", "check")],
    "common_attribute": [
        *_BASIC_FIELDS,
        ("__section__", "section_data", None),
        *_COMMON_ATTRIBUTE_DATA_FIELDS,
        ("__section__", "section_behavior", None),
        *_COMMON_ATTRIBUTE_BEHAVIOR_FIELDS,
        ("__section__", "section_presentation", None),
        *_COMMON_ATTRIBUTE_PRESENTATION_FIELDS,
        ("__section__", "section_modules", None),
        *_COMMON_ATTRIBUTE_MODULE_FIELDS,
        ("__section__", "section_help", None),
        ("include_help_in_contents", "prop_include_help", "check"),
        ("help_info", "prop_help_info", "readonly_text"),
    ],
    "document_numerator": [*_BASIC_FIELDS, ("__section__", "section_data", None), ("number_len", "prop_number_len", "line"), ("number_periodicity", "prop_number_period", "combo", ["year", "quarter", "month", "day", "none"])],
    "exchange_plan": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("namespace", "prop_namespace", "line"), ("fill_check", "prop_fill_check", "check"), ("__section__", "section_standard", None), *_STD_FORM_FIELDS],
    "selection_criterion": [*_BASIC_FIELDS, ("__section__", "section_standard", None), ("default_list_form", "prop_default_list_form", "line"), ("default_object_form", "prop_default_object_form", "line")],
    "event_subscription": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("restart_session", "prop_restart_session", "check")],
    "scheduled_job": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("restart_session", "prop_restart_session", "check"), ("use_purposes", "prop_use_purposes", "check")],
    "functional_option": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("default_value", "prop_default_value", "line")],
    "functional_option_param": [*_BASIC_FIELDS, ("__section__", "section_data", None), ("data_type", "prop_data_type", "line"), ("default_value", "prop_default_value", "line")],
    "defined_type": [*_BASIC_FIELDS, ("__section__", "section_data", None), ("data_type", "prop_data_type", "line"), ("length", "prop_length", "line"), ("precision", "prop_precision", "line")],
    "settings_storage": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("namespace", "prop_namespace", "line")],
    "common_command": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("default_value", "prop_default_value", "line"), ("include_in_command_interface", "prop_include_cmd_interface", "check"), ("use_standard_commands", "prop_use_std_commands", "check")],
    "command_group": [*_BASIC_FIELDS, ("__section__", "section_presentation", None), ("main_presentation", "prop_main_presentation", "line")],
    "common_form": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("subtype", "prop_form_kind", "readonly"), ("main_presentation", "prop_main_presentation", "line"), ("default_object_form", "prop_default_object_form", "line"), ("default_list_form", "prop_default_list_form", "line")],
    "common_layout": [*_BASIC_FIELDS, ("__section__", "section_presentation", None), ("main_presentation", "prop_main_presentation", "line")],
    "common_picture": [*_BASIC_FIELDS, ("__section__", "section_presentation", None), ("main_presentation", "prop_main_presentation", "line"), ("source_path", "prop_source_path", "readonly")],
    "xdto_package": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("namespace", "prop_namespace", "line")],
    "web_service": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("namespace", "prop_namespace", "line"), ("authentication", "prop_authentication", "check")],
    "http_service": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("namespace", "prop_namespace", "line"), ("authentication", "prop_authentication", "check")],
    "ws_link": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("namespace", "prop_namespace", "line")],
    "websocket_client": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("namespace", "prop_namespace", "line")],
    "integration_service": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("namespace", "prop_namespace", "line")],
    "style_element": [*_BASIC_FIELDS, ("__section__", "section_presentation", None), ("main_presentation", "prop_main_presentation", "line")],
    "style": [*_BASIC_FIELDS, ("__section__", "section_presentation", None), ("main_presentation", "prop_main_presentation", "line")],
    "language": [*_BASIC_FIELDS, ("__section__", "section_presentation", None), ("locale_code", "prop_locale_code", "line")],
    "sequence": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("namespace", "prop_namespace", "line")],
    "form": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("subtype", "prop_form_kind", "readonly"), ("main_presentation", "prop_main_presentation", "line"), ("default_object_form", "prop_default_object_form", "line"), ("default_list_form", "prop_default_list_form", "line")],
    "command": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("default_value", "prop_default_value", "line")],
    "layout": [*_BASIC_FIELDS, ("__section__", "section_presentation", None), ("main_presentation", "prop_main_presentation", "line")],
    "module": [*_BASIC_FIELDS, ("__section__", "section_behavior", None), ("global", "prop_global", "check"), ("client_managed", "prop_client_managed", "check"), ("server", "prop_server", "check")],
    "business_process": [*_BASIC_FIELDS, ("__section__", "section_standard", None), *_STD_FORM_FIELDS],
    "task": [*_BASIC_FIELDS, ("__section__", "section_standard", None), *_STD_FORM_FIELDS],
    "chart_of_characteristic_types": [*_BASIC_FIELDS, ("__section__", "section_standard", None), *_STD_FORM_FIELDS],
    "chart_of_accounts": [*_BASIC_FIELDS, ("__section__", "section_standard", None), *_STD_FORM_FIELDS],
    "chart_of_calculation_types": [*_BASIC_FIELDS, ("__section__", "section_standard", None), *_STD_FORM_FIELDS],
}

_DEFAULT_FIELDS: list[FieldDef] = [*_BASIC_FIELDS]

_EXTRA = {
    "en": {
        "section_advanced": "Advanced", "section_basic": "Basic", "section_behavior": "Behavior", "section_compatibility": "Compatibility",
        "section_data": "Data", "section_development": "Development", "section_forms": "Forms", "section_help": "Help",
        "section_modules": "Modules", "section_presentation": "Presentation", "section_standard": "Standard", "section_system": "System",
        "prop_authentication": "Authentication", "prop_brief_info": "Brief info", "prop_client_managed": "Client (managed app)",
        "prop_author": "Author", "prop_binary_data_storage_mode": "Binary data storage mode",
        "prop_binary_data_storage_usage_mode": "Binary data storage usage mode", "prop_compatibility_mode": "Compatibility mode",
        "prop_configuration_address": "Configuration address", "prop_copyright": "Copyright",
        "prop_code_len": "Code length", "prop_comment": "Comment", "prop_check_unique": "Check uniqueness", "prop_data_type": "Data type",
        "prop_code_ref_uk": "Ukrainian code reference", "prop_code_ref_en": "English code reference",
        "prop_editing_format": "Editing format", "prop_format": "Format", "prop_hint": "Hint", "prop_module": "Module",
        "prop_code_type": "Code type", "prop_default_report_form": "Default report form",
        "prop_default_report_settings_form": "Default report settings form", "prop_default_report_variant_form": "Default report variant form",
        "prop_data_lock_control_mode": "Data lock control mode", "prop_default_change_history_form": "Default change history form",
        "prop_default_constants_form": "Default constants form", "prop_default_data_history_difference_form": "Default data history difference form",
        "prop_default_data_history_form": "Default data history form", "prop_default_dynamic_list_settings_form": "Default dynamic list settings form",
        "prop_default_list_form": "Default list form", "prop_default_object_form": "Default object form",
        "prop_default_choice_form": "Default choice form", "prop_default_report_form": "Default report form",
        "prop_default_report_settings_form": "Default report settings form", "prop_default_report_variant_form": "Default report variant form",
        "prop_default_search_form": "Default search form", "prop_default_user_selection_form": "Default user selection form",
        "prop_default_value": "Default value", "prop_description_len": "Description length", "prop_detail_info": "Detail info",
        "prop_external_conn": "External connection", "prop_fill_check": "Fill check", "prop_form_kind": "Form kind",
        "prop_global": "Global", "prop_guid": "GUID", "prop_hierarchical": "Hierarchical", "prop_include_cmd_interface": "Include in command interface", "prop_include_help": "Include in help contents",
        "prop_help_info": "Help information", "prop_interface_mode": "Interface mode", "prop_logo": "Logo",
        "prop_hierarchy_type": "Hierarchy type", "prop_input_by": "Input by", "prop_length": "Length", "prop_levels_count": "Levels count", "prop_limit_levels": "Limit levels",
        "prop_locale_code": "Locale code", "prop_main_choice_form": "Main choice form", "prop_main_group_form": "Main group form",
        "prop_main_interface": "Main interface", "prop_main_language": "Main language",
        "prop_main_presentation": "Main presentation", "prop_main_report_layout": "Main report layout", "prop_main_style": "Main style", "prop_command_interface": "Command interface",
        "prop_managed_application_module": "Managed application module",
        "prop_session_module": "Session module",
        "prop_external_connection_module": "External connection module",
        "prop_ordinary_application_module": "Ordinary application module",
        "prop_main_object_form": "Main object form", "prop_main_list_form": "Main list form", "prop_modality_mode": "Modal mode",
        "prop_module_manager": "Module manager", "prop_module_manager_value": "Module manager value", "prop_picture_ref": "Picture", "prop_type_link": "Type link", "prop_use_one_command": "Use one command",
        "prop_name_length": "Name length", "prop_owners": "Owners", "prop_place_groups_top": "Place groups on top", "prop_splash": "Splash", "prop_supplier_address": "Supplier address",
        "prop_name": "Name", "prop_namespace": "Namespace", "prop_number_len": "Number length", "prop_number_period": "Number periodicity",
        "prop_parent_guid": "Parent GUID", "prop_periodic": "Periodic", "prop_posting": "Posting", "prop_precision": "Precision",
        "prop_privileged": "Privileged", "prop_quick_choice": "Quick choice", "prop_reg_kind": "Kind", "prop_restart_session": "Restart session",
        "prop_source_path": "Source path", "prop_subtype": "Subtype", "prop_supplier_address": "Supplier address", "prop_sync_calls_mode": "Synchronous calls mode",
        "prop_synonym": "Synonym", "prop_tabular_spaces_mode": "Tabular spaces mode", "prop_type": "Type",
        "prop_use_purposes": "Use purposes", "prop_use_std_commands": "Use standard commands", "prop_write_on_input": "Write on input only",
        "prop_update_address": "Update address", "prop_vendor": "Vendor", "prop_version": "Version", "prop_binary_data_storage_usage_mode": "Binary data storage usage mode",
        "prop_autonumbering_mode": "Autonumbering mode",
        "props_no_selection": "Select an object in the tree",
    },
    "uk": {
        "section_advanced": "Додатково", "section_basic": "Основні", "section_behavior": "Поведінка", "section_compatibility": "Сумісність",
        "section_data": "Дані", "section_development": "Розробка", "section_forms": "Форми", "section_help": "Довідка",
        "section_modules": "Модулі", "section_presentation": "Представлення", "section_standard": "Стандартні", "section_system": "Система",
        "prop_authentication": "Автентифікація", "prop_brief_info": "Коротка інформація", "prop_client_managed": "Клієнт (керований застосунок)",
        "prop_author": "Автор", "prop_binary_data_storage_mode": "Режим сховища двійкових даних",
        "prop_binary_data_storage_usage_mode": "Режим використання сховища двійкових даних", "prop_compatibility_mode": "Режим сумісності",
        "prop_configuration_address": "Адреса інформації про конфігурацію", "prop_copyright": "Авторські права",
        "prop_code_len": "Довжина коду", "prop_comment": "Коментар", "prop_check_unique": "Перевірка унікальності", "prop_data_type": "Тип даних",
        "prop_code_ref_uk": "Посилання в коді (UK)", "prop_code_ref_en": "Посилання в коді (EN)",
        "prop_editing_format": "Формат редагування", "prop_format": "Формат", "prop_hint": "Підказка", "prop_module": "Модуль",
        "prop_code_type": "Тип коду", "prop_default_report_form": "Основна форма звіту",
        "prop_default_report_settings_form": "Основна форма налаштувань звіту", "prop_default_report_variant_form": "Основна форма варіанта звіту",
        "prop_data_lock_control_mode": "Режим контролю блокування даних", "prop_default_change_history_form": "Основна форма історії змін",
        "prop_default_constants_form": "Основна форма констант", "prop_default_data_history_difference_form": "Основна форма різниці версій історії даних",
        "prop_default_data_history_form": "Основна форма даних версії історії даних", "prop_default_dynamic_list_settings_form": "Основна форма налаштувань динамічного списку",
        "prop_default_list_form": "Форма списку за замовчуванням", "prop_default_object_form": "Форма об'єкта за замовчуванням",
        "prop_default_choice_form": "Форма вибору за замовчуванням", "prop_default_report_form": "Основна форма звіту",
        "prop_default_report_settings_form": "Основна форма налаштувань звіту", "prop_default_report_variant_form": "Основна форма варіанта звіту",
        "prop_default_search_form": "Основна форма пошуку", "prop_default_user_selection_form": "Основна форма вибору користувачів системи взаємодії",
        "prop_default_value": "Значення за замовчуванням", "prop_description_len": "Довжина найменування", "prop_detail_info": "Детальна інформація",
        "prop_external_conn": "Зовнішнє з'єднання", "prop_fill_check": "Перевірка заповнення", "prop_form_kind": "Вид форми",
        "prop_global": "Глобальний", "prop_guid": "GUID", "prop_hierarchical": "Ієрархічний", "prop_include_cmd_interface": "Включати до командного інтерфейсу", "prop_include_help": "Включати у зміст довідки",
        "prop_help_info": "Довідкова інформація", "prop_interface_mode": "Режим інтерфейсу", "prop_logo": "Логотип",
        "prop_hierarchy_type": "Тип ієрархії", "prop_input_by": "Введення по", "prop_length": "Довжина", "prop_levels_count": "Кількість рівнів", "prop_limit_levels": "Обмежувати кількість рівнів",
        "prop_locale_code": "Код локалі", "prop_main_choice_form": "Основна форма вибору", "prop_main_group_form": "Основна форма групи",
        "prop_main_interface": "Основний інтерфейс", "prop_main_language": "Основна мова",
        "prop_main_presentation": "Основне представлення", "prop_main_report_layout": "Основний макет оформлення звіту", "prop_main_style": "Основний стиль", "prop_command_interface": "Командний інтерфейс",
        "prop_managed_application_module": "Модуль керованого застосунку",
        "prop_session_module": "Модуль сеансу",
        "prop_external_connection_module": "Модуль зовнішнього з'єднання",
        "prop_ordinary_application_module": "Модуль звичайного застосунку",
        "prop_main_object_form": "Основна форма об'єкта", "prop_main_list_form": "Основна форма списку", "prop_modality_mode": "Режим використання модальності",
        "prop_module_manager": "Модуль менеджера", "prop_module_manager_value": "Модуль менеджера значення", "prop_picture_ref": "Картинка", "prop_type_link": "Зв'язок по типу", "prop_use_one_command": "Використовувати одну команду",
        "prop_name_length": "Довжина найменування", "prop_owners": "Власники", "prop_place_groups_top": "Розміщувати групи зверху", "prop_splash": "Заставка", "prop_supplier_address": "Адреса інформації про постачальника",
        "prop_name": "Ім'я", "prop_namespace": "Простір імен", "prop_number_len": "Довжина номера", "prop_number_period": "Періодичність номера",
        "prop_parent_guid": "GUID батька", "prop_periodic": "Періодичний", "prop_posting": "Проведення", "prop_precision": "Точність",
        "prop_privileged": "Привілейований", "prop_quick_choice": "Швидкий вибір", "prop_reg_kind": "Вид", "prop_restart_session": "Перезапускати сеанс",
        "prop_source_path": "Шлях до джерела", "prop_subtype": "Підтип", "prop_sync_calls_mode": "Режим використання синхронних викликів розширень платформи і зовнішніх компонентів",
        "prop_synonym": "Синонім", "prop_tabular_spaces_mode": "Режим використання табличних просторів", "prop_type": "Тип",
        "prop_use_purposes": "Використовувати призначення", "prop_use_std_commands": "Використовувати стандартні команди",
        "prop_write_on_input": "Записувати тільки при введенні", "prop_update_address": "Адреса каталогу оновлень",
        "prop_vendor": "Постачальник", "prop_version": "Версія", "prop_binary_data_storage_usage_mode": "Режим використання сховища двійкових даних",
        "prop_autonumbering_mode": "Режим автонумерації", "props_no_selection": "Виберіть об'єкт у дереві",
    },
}

_FIELD_HELP_EXTRA = {
    "en": {
        "name": "Internal metadata identifier used in the tree, module routing and references.",
        "synonym": "User-facing title shown in the configurator and client UI.",
        "comment": "Technical or business comment for the metadata object.",
        "data_type": "Base data type of the field or object value.",
        "format": "Display format assigned to the object or attribute.",
        "editing_format": "Input/editing format used by the editor widget.",
        "default_value": "Value used when the platform creates a new object automatically.",
        "number_length": "Maximum length of an auto-generated document number.",
        "number_periodicity": "How numbering resets over time: year, quarter, month, day or never.",
        "posting": "Whether document posting is allowed for this metadata object.",
        "input_by_string": "How the object can be found or entered from textual input.",
        "fill_check": "Defines whether empty values are allowed and how validation reacts.",
        "type_link": "Reference to another type used to constrain the value.",
        "guid": "Stable system identifier of the metadata object in manifest.",
        "type": "Technical metadata type used by the platform.",
        "subtype": "More specific subtype when the object belongs to a generic family.",
        "parent_guid": "GUID of the parent metadata object in manifest tree.",
        "namespace": "Logical namespace used by integration and service objects.",
        "module": "Linked module asset or module reference for this metadata object.",
        "main_presentation": "Primary human-readable presentation used by the client.",
        "main_interface": "Primary UI interface selected for the configuration root.",
        "main_style": "Primary visual style selected for the configuration root.",
        "main_language": "Primary language used by the configuration root.",
        "managed_application_module": "Built-in module used by the managed application client at startup.",
        "session_module": "Built-in module executed for each client session.",
        "external_connection_module": "Built-in module used for external connection sessions.",
        "ordinary_application_module": "Built-in module used by the ordinary application client at startup.",
        "command_interface": "Summary of the imported command interface structure.",
        "include_in_command_interface": "Whether this object participates in the command interface.",
        "use_one_command": "Whether subsystem commands are collapsed into one command.",
        "hint": "Short hint shown to the user in editors and forms.",
    },
    "uk": {
        "name": "Внутрішній ідентифікатор метаданих для дерева, модулів та посилань.",
        "synonym": "Назва, яку бачить користувач у клієнті. Конфігуратор показує технічне ім'я.",
        "comment": "Технічний або бізнес-коментар до об'єкта метаданих.",
        "data_type": "Базовий тип даних реквізиту або значення об'єкта.",
        "format": "Формат відображення, призначений об'єкту або реквізиту.",
        "editing_format": "Формат введення/редагування для віджета редактора.",
        "default_value": "Значення, яке використовується при автоматичному створенні нового об'єкта.",
        "number_length": "Максимальна довжина автоматично сформованого номера документа.",
        "number_periodicity": "Як часто скидається нумерація: рік, квартал, місяць, день або ніколи.",
        "posting": "Чи дозволене проведення для цього об'єкта метаданих.",
        "input_by_string": "Як об'єкт шукається або вводиться за текстовим рядком.",
        "fill_check": "Визначає, чи дозволені порожні значення і як реагує перевірка.",
        "type_link": "Посилання на інший тип, який обмежує значення.",
        "guid": "Стабільний системний ідентифікатор об'єкта в manifest.",
        "type": "Технічний тип метаданих, який використовує платформа.",
        "subtype": "Уточнений підтип для об'єктів узагальненої сім'ї.",
        "parent_guid": "GUID батьківського об'єкта в дереві manifest.",
        "namespace": "Логічний простір імен для інтеграційних і сервісних об'єктів.",
        "module": "Пов'язаний модуль або посилання на модуль для цього об'єкта.",
        "main_presentation": "Основне читабельне представлення, яке бачить клієнт.",
        "main_interface": "Основний інтерфейс, який вибрано для кореня конфігурації.",
        "main_style": "Основний візуальний стиль, який вибрано для кореня конфігурації.",
        "main_language": "Основна мова, яку використовує корінь конфігурації.",
        "managed_application_module": "Вбудований модуль, який запускається у керованому застосунку.",
        "session_module": "Вбудований модуль, що виконується для кожного сеансу клієнта.",
        "external_connection_module": "Вбудований модуль для зовнішнього з'єднання.",
        "ordinary_application_module": "Вбудований модуль звичайного застосунку.",
        "command_interface": "Зведення імпортованої структури командного інтерфейсу.",
        "include_in_command_interface": "Чи бере об'єкт участь у командному інтерфейсі.",
        "use_one_command": "Чи згортати команди підсистеми в одну команду.",
        "hint": "Коротка підказка, яку бачить користувач у редакторах і формах.",
    },
}


def _tr(key: str) -> str:
    val = t(key)
    if val != key:
        return val
    try:
        from src.ui_qt.i18n import get_lang
        lang = get_lang()
    except Exception:
        lang = "uk"
    return (_EXTRA.get(lang) or _EXTRA["uk"]).get(key, key)


def _humanize_key(key: str) -> str:
    parts = [part for part in str(key or "").replace("-", "_").split("_") if part]
    return " ".join(part[:1].upper() + part[1:] for part in parts) or str(key or "")


def _label_for_key(key: str) -> str:
    tr_key = f"prop_{key}"
    val = _tr(tr_key)
    return val if val != tr_key else _humanize_key(key)


def _localized_scalar(value: Any) -> Any:
    if isinstance(value, dict):
        try:
            from src.ui_qt.i18n import get_lang
            lang = get_lang()
        except Exception:
            lang = "uk"
        for key in (lang, "uk", "ru", "en"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
        for text in value.values():
            if isinstance(text, str) and text.strip():
                return text.strip()
        return ""
    return value


def _stringify_payload_value(value: Any) -> str:
    value = _localized_scalar(value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    if isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            return ", ".join(str(_localized_scalar(item)) for item in value if str(_localized_scalar(item)).strip())
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    if isinstance(value, dict):
        if all(not isinstance(item, (dict, list)) for item in value.values()):
            parts = []
            for key, item in value.items():
                text = str(_localized_scalar(item) or "").strip()
                if text:
                    parts.append(f"{key}: {text}")
            return "; ".join(parts)
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return str(value)


def _payload_value(payload: dict[str, Any], key: str) -> Any:
    if key in _MODULE_REF_KEYS:
        candidates = [key, *(_FIELD_ALIASES.get(key, ())) ]
        for candidate in candidates:
            value = payload.get(candidate)
            if value in (None, "", [], {}):
                continue
            value = _localized_scalar(value)
            if isinstance(value, list):
                for item in value:
                    text = str(_localized_scalar(item) or "").strip()
                    if text:
                        return text
                continue
            if isinstance(value, dict):
                for alias in ("asset_key", "module_guid", "guid", "ref", "value"):
                    text = str(_localized_scalar(value.get(alias)) or "").strip()
                    if text:
                        return text
                continue
            text = str(value or "").strip()
            if text:
                return text
        return ""
    if key in payload:
        value = _localized_scalar(payload.get(key))
        return _stringify_payload_value(value) if isinstance(value, (dict, list)) else value
    for alias in _FIELD_ALIASES.get(key, ()):
        if alias in payload:
            value = _localized_scalar(payload.get(alias))
            return _stringify_payload_value(value) if isinstance(value, (dict, list)) else value
    return ""


def _normalize_object_type(obj_type: str, payload: dict[str, Any]) -> str:
    ot = str(obj_type or "").strip().lower()
    if ot == "common":
        subtype = str(payload.get("subtype") or "").strip().lower()
        if subtype:
            ot = subtype
    return _TYPE_ALIASES.get(ot, ot)


def _dynamic_field_defs(payload: dict[str, Any], known_keys: set[str]) -> list[FieldDef]:
    rows: list[FieldDef] = []
    for key in sorted(payload.keys(), key=lambda item: _label_for_key(item).lower()):
        if key in known_keys or key in _SKIP_DYNAMIC_KEYS or str(key).startswith("_"):
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            rows.append((key, _label_for_key(key), "check"))
        elif isinstance(value, (int, float)):
            rows.append((key, _label_for_key(key), "line"))
        elif isinstance(value, str):
            rows.append((key, _label_for_key(key), "text" if "\n" in value or len(value) > 80 else "line"))
        elif isinstance(value, (list, dict)):
            text = _stringify_payload_value(value)
            if text:
                rows.append((key, _label_for_key(key), "readonly_text" if "\n" in text or len(text) > 80 else "readonly"))
    return [("__section__", "section_advanced", None), *rows] if rows else []


class _SectionHeader(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(("▸ " + text).upper(), parent)
        self.setObjectName("PropSectionHeader")
        self.setStyleSheet(
            "QLabel#PropSectionHeader {"
            "font-weight: 700; font-size: 7pt; color: #7f8ba0; padding: 10px 10px 4px 10px;"
            "background: rgba(15, 23, 42, 0.72); border-top: 1px solid rgba(45, 55, 72, 0.7);"
            "border-bottom: 1px solid rgba(45, 55, 72, 0.85);}"
        )


class _CommitTextEdit(QPlainTextEdit):
    commitRequested = Signal()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.commitRequested.emit()


class _PropRow(QWidget):
    valueChanged = Signal(str, object)
    commitRequested = Signal(str, object)
    focusReceived = Signal(str)
    moduleOpenRequested = Signal(str, str)

    def __init__(
        self,
        payload_key: str,
        label: str,
        widget_type: str,
        options: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._key = payload_key
        self._wtype = widget_type
        self._block = False
        self._module_open_button: QToolButton | None = None
        self._module_ref_value: str = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(8)

        lbl = QLabel(label)
        lbl.setFixedWidth(154)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: rgba(200,208,218,0.78); font-size: 8pt;")
        layout.addWidget(lbl)

        if widget_type == "line":
            ed: QWidget = QLineEdit()
            ed.editingFinished.connect(self._emit)  # type: ignore[attr-defined]
        elif widget_type == "text":
            ed = _CommitTextEdit()
            ed.setFixedHeight(60)
            ed.textChanged.connect(self._emit_no_commit)  # type: ignore[attr-defined]
            ed.commitRequested.connect(self._emit)  # type: ignore[attr-defined]
        elif widget_type == "check":
            ed = QCheckBox()
            ed.stateChanged.connect(self._emit)  # type: ignore[attr-defined]
        elif widget_type == "combo":
            ed = QComboBox()
            for option in options or []:
                ed.addItem(option)  # type: ignore[attr-defined]
            ed.currentTextChanged.connect(self._emit)  # type: ignore[attr-defined]
        elif widget_type == "readonly_text":
            ed = QPlainTextEdit()
            ed.setReadOnly(True)
            ed.setFixedHeight(74)
            ed.setStyleSheet("color: rgba(255,255,255,0.65);")
        elif widget_type == "module_ref":
            open_btn = QToolButton()
            open_btn.setText(_tr("act_open"))
            open_btn.setToolTip(_tr("act_open"))
            open_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
            open_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            open_btn.setAutoRaise(False)
            open_btn.setMinimumWidth(110)
            open_btn.clicked.connect(self._emit_open)  # type: ignore[attr-defined]
            self._module_open_button = open_btn
            ed = open_btn
            layout.addWidget(open_btn, 0)
            layout.addStretch(1)
        else:
            ed = QLineEdit()
            ed.setReadOnly(True)
            ed.setStyleSheet("color: rgba(255,255,255,0.35);")

        self._editor = ed
        self._editor.installEventFilter(self)
        if widget_type != "module_ref":
            layout.addWidget(self._editor, 1)
        self.setStyleSheet(
            "QLineEdit, QComboBox, QPlainTextEdit {"
            "background: rgba(17, 24, 39, 0.98);"
            "border: 1px solid rgba(75, 85, 99, 0.72);"
            "border-radius: 4px;"
            "padding: 4px 6px;"
            "color: #E5E7EB;"
            "}"
            "QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {"
            "border: 1px solid rgba(124, 124, 232, 1.0);"
            "}"
            "QCheckBox { border: none; background: transparent; padding: 0px; }"
        )

    def set_value(self, value: Any) -> None:
        self._block = True
        try:
            if self._wtype in ("line", "readonly"):
                self._editor.setText("" if value is None else str(value))  # type: ignore[attr-defined]
            elif self._wtype == "text":
                self._editor.setPlainText("" if value is None else str(value))  # type: ignore[attr-defined]
            elif self._wtype == "readonly_text":
                self._editor.setPlainText("" if value is None else str(value))  # type: ignore[attr-defined]
            elif self._wtype == "check":
                self._editor.setChecked(bool(value))  # type: ignore[attr-defined]
            elif self._wtype == "combo":
                text = "" if value is None else str(value)
                idx = self._editor.findText(text)  # type: ignore[attr-defined]
                if idx < 0 and text:
                    self._editor.addItem(text)  # type: ignore[attr-defined]
                    idx = self._editor.findText(text)  # type: ignore[attr-defined]
                if idx >= 0:
                    self._editor.setCurrentIndex(idx)  # type: ignore[attr-defined]
            elif self._wtype == "module_ref":
                self._module_ref_value = "" if value is None else str(value).strip()
        finally:
            self._block = False
        self._sync_module_buttons()

    def get_value(self) -> Any:
        if self._wtype in ("line", "readonly"):
            return self._editor.text()  # type: ignore[attr-defined]
        if self._wtype == "module_ref":
            return self._module_ref_value
        if self._wtype == "text":
            return self._editor.toPlainText()  # type: ignore[attr-defined]
        if self._wtype == "readonly_text":
            return self._editor.toPlainText()  # type: ignore[attr-defined]
        if self._wtype == "check":
            return self._editor.isChecked()  # type: ignore[attr-defined]
        if self._wtype == "combo":
            return self._editor.currentText()  # type: ignore[attr-defined]
        return ""

    def _emit(self, *_: Any) -> None:
        if self._block:
            return
        value = self.get_value()
        self.valueChanged.emit(self._key, value)
        self.commitRequested.emit(self._key, value)

    def _emit_no_commit(self, *_: Any) -> None:
        if not self._block:
            self.valueChanged.emit(self._key, self.get_value())

    def set_enabled(self, enabled: bool) -> None:
        self._editor.setEnabled(enabled)
        if self._module_open_button is not None:
            self._module_open_button.setEnabled(enabled and bool(self._module_ref_value))

    def _sync_module_buttons(self) -> None:
        if self._module_open_button is None:
            return
        has_value = bool(str(self.get_value() or "").strip())
        self._module_open_button.setEnabled(has_value and self._editor.isEnabled())

    def _emit_open(self, *_: Any) -> None:
        self.moduleOpenRequested.emit(self._key, str(self.get_value() or "").strip())

    def eventFilter(self, watched: object, event: object) -> bool:
        if watched is self._editor and isinstance(event, QEvent) and event.type() == QEvent.Type.FocusIn:
            self.focusReceived.emit(self._key)
        return super().eventFilter(watched, event)


class ManifestPropertiesPanel(QWidget):
    editorFieldChanged = Signal(str, object)
    editorPayloadChanged = Signal(object)
    openModuleRequested = Signal(str, str)
    applyRequested = Signal()
    revertRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ManifestPropertiesPanel")
        self._guid = ""
        self._obj_type = ""
        self._payload: dict[str, Any] = {}
        self._rows: dict[str, _PropRow] = {}
        self._name_row: _PropRow | None = None
        self._blocking = False
        self._dynamic_signature: tuple[str, ...] = ()
        self._meta_values: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setStyleSheet(
            "QWidget#ManifestPropertiesPanel { background: #0B1220; }"
            "QFrame#PropHeader { background: #111827; border-bottom: 1px solid rgba(45, 55, 72, 0.95); }"
            "QScrollArea { border: none; background: #0B1220; }"
            "QScrollArea > QWidget > QWidget { background: #0B1220; }"
            "QToolButton#PropApplyButton, QToolButton#PropRevertButton {"
            "background: rgba(255,255,255,0.04);"
            "border: 1px solid rgba(75, 85, 99, 0.6);"
            "border-radius: 4px;"
            "padding: 4px;"
            "}"
            "QToolButton#PropApplyButton:hover, QToolButton#PropRevertButton:hover {"
            "background: rgba(124,124,232,0.18);"
            "border-color: rgba(124,124,232,0.9);"
            "}"
        )

        header = QFrame()
        header.setObjectName("PropHeader")
        header.setFrameShape(QFrame.Shape.NoFrame)
        header_l = QVBoxLayout(header)
        header_l.setContentsMargins(10, 10, 10, 10)
        header_l.setSpacing(5)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)

        self._title = QLabel(_tr("props_no_selection"))
        self._title.setObjectName("PropTitle")
        self._title.setWordWrap(True)
        self._title.setStyleSheet("QLabel#PropTitle {font-weight: 700; font-size: 10pt;}")
        text_box.addWidget(self._title)

        self._subtitle = QLabel("")
        self._subtitle.setObjectName("PropSubtitle")
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet("QLabel#PropSubtitle {color: rgba(214, 223, 235, 0.68); font-size: 8pt;}")
        text_box.addWidget(self._subtitle)

        top_row.addLayout(text_box, 1)

        self._btn_apply = QToolButton()
        self._btn_apply.setObjectName("PropApplyButton")
        self._btn_apply.setAutoRaise(True)
        self._btn_apply.setToolTip(t("act_apply") if t("act_apply") != "act_apply" else "Apply")
        self._btn_apply.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        self._btn_apply.clicked.connect(lambda: self.applyRequested.emit())
        self._btn_apply.setEnabled(False)

        self._btn_revert = QToolButton()
        self._btn_revert.setObjectName("PropRevertButton")
        self._btn_revert.setAutoRaise(True)
        self._btn_revert.setToolTip(t("act_revert") if t("act_revert") != "act_revert" else "Revert")
        self._btn_revert.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self._btn_revert.clicked.connect(lambda: self.revertRequested.emit())
        self._btn_revert.setEnabled(False)

        top_row.addWidget(self._btn_apply, 0, Qt.AlignmentFlag.AlignTop)
        top_row.addWidget(self._btn_revert, 0, Qt.AlignmentFlag.AlignTop)
        header_l.addLayout(top_row)

        self._meta_line = QLabel("")
        self._meta_line.setObjectName("PropMetaLine")
        self._meta_line.setWordWrap(True)
        self._meta_line.setStyleSheet("QLabel#PropMetaLine {color: rgba(214, 223, 235, 0.54); font-size: 7.5pt;}")
        header_l.addWidget(self._meta_line)

        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName("PropScroll")

        self._host = QWidget()
        self._host.setObjectName("PropHost")
        self._layout = QVBoxLayout(self._host)
        self._layout.setContentsMargins(0, 0, 0, 6)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)
        scroll.setWidget(self._host)
        root.addWidget(scroll, 1)

        self._help = QPlainTextEdit()
        self._help.setReadOnly(True)
        self._help.setFixedHeight(92)
        self._help.setObjectName("ManifestPropertiesHelp")
        self._help.setStyleSheet(
            "QPlainTextEdit#ManifestPropertiesHelp {"
            "border-top: 1px solid rgba(45, 55, 72, 0.9);"
            "border-left: none; border-right: none; border-bottom: none;"
            "background: #0F172A;"
            "color: rgba(214, 223, 235, 0.78);"
            "padding: 8px 10px;"
            "}"
        )
        root.addWidget(self._help, 0)
        self._set_help_text("")

    def set_properties_rows(self, rows: list[tuple[str, str]]) -> None:
        pass

    def update_editor(self, st: Any) -> None:
        cur = getattr(st, "current", None) or {}
        guid = str(cur.get("guid") or "")
        if not guid:
            self._clear()
            return

        payload = cur.get("payload") if isinstance(cur.get("payload"), dict) else {}
        obj_type = _normalize_object_type(str(cur.get("type") or ""), payload)
        name = str(cur.get("name") or "")
        title = str(cur.get("title") or "")
        parent_guid = str(cur.get("parent_guid") or "")
        subtype = str(payload.get("subtype") or "")
        dynamic_signature = tuple(
            key for key, *_ in _dynamic_field_defs(payload, self._known_payload_keys(obj_type)) if not str(key).startswith("__")
        )

        if guid != self._guid or obj_type != self._obj_type or dynamic_signature != self._dynamic_signature:
            self._guid = guid
            self._obj_type = obj_type
            self._dynamic_signature = dynamic_signature
            self._build(obj_type, payload)

        self._meta_values = {
            "__guid__": guid,
            "__type__": obj_type,
            "__subtype__": subtype,
            "__parent_guid__": parent_guid,
        }

        self._blocking = True
        try:
            self._payload = dict(payload or {})
            if self._name_row:
                display_name = technical_object_name(name, payload=payload)
                self._name_row.set_value(display_name)
            for key, row in self._rows.items():
                if key == "synonym":
                    row.set_value(title)
                elif key.startswith("__"):
                    row.set_value(self._meta_values.get(key, ""))
                else:
                    row.set_value(_payload_value(payload, key))
        finally:
            self._blocking = False

        header_name = technical_object_name(name, payload=payload)
        self._title.setText(header_name or obj_type or _tr("props_no_selection"))
        meta_bits = [part for part in (obj_type, subtype, guid) if part]
        self._subtitle.setText("  ".join(meta_bits))
        self._meta_line.setText(f"{_tr('prop_guid')}: {guid}" if guid else "")
        self._btn_apply.setEnabled(bool(guid))
        self._btn_revert.setEnabled(bool(guid))

    def set_editor_enabled(self, enabled: bool) -> None:
        if not enabled:
            self._clear()
        if self._name_row:
            self._name_row.set_enabled(enabled)
        for row in self._rows.values():
            row.set_enabled(enabled)

    def _clear(self) -> None:
        self._guid = ""
        self._obj_type = ""
        self._payload = {}
        self._dynamic_signature = ()
        self._meta_values = {}
        self._title.setText(_tr("props_no_selection"))
        self._subtitle.setText("")
        self._meta_line.setText("")
        self._btn_apply.setEnabled(False)
        self._btn_revert.setEnabled(False)
        self._set_help_text("")
        self._wipe_layout()

    def _wipe_layout(self) -> None:
        self._rows.clear()
        self._name_row = None
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()

    def _known_payload_keys(self, obj_type: str) -> set[str]:
        defs = _SECTION_DEFS.get(obj_type, _DEFAULT_FIELDS)
        out = {str(entry[0]) for entry in defs if entry and not str(entry[0]).startswith("__")}
        for key in list(out):
            out.update(_FIELD_ALIASES.get(key, ()))
        return out

    def _build(self, obj_type: str, payload: dict[str, Any]) -> None:
        self._wipe_layout()
        defs = list(_SECTION_DEFS.get(obj_type, _DEFAULT_FIELDS))
        defs.extend(_dynamic_field_defs(payload, self._known_payload_keys(obj_type)))
        defs.extend(_READONLY_SYSTEM_FIELDS)
        for entry in defs:
            key = str(entry[0])
            label_key = str(entry[1])
            wtype = entry[2] if len(entry) > 2 else None
            options = list(entry[3]) if len(entry) > 3 else None
            if key == "__section__":
                self._layout.addWidget(_SectionHeader(_tr(label_key)))
                continue
            label = _tr(label_key) if label_key.startswith("prop_") else str(label_key)
            if key == "__name__":
                row = _PropRow(key, label, "readonly" if obj_type == "common_module" else "line")
                if obj_type != "common_module":
                    row.valueChanged.connect(self._on_name)
                row.commitRequested.connect(self._on_commit)
                row.focusReceived.connect(self._on_row_focused)
                self._name_row = row
                self._layout.addWidget(row)
                continue
            row = _PropRow(key, label, wtype or "line", options)
            row.valueChanged.connect(self._on_payload)
            row.commitRequested.connect(self._on_commit)
            row.focusReceived.connect(self._on_row_focused)
            row.moduleOpenRequested.connect(self._on_module_open_requested)
            self._rows[key] = row
            self._layout.addWidget(row)
        self._layout.addStretch(1)

    def _on_name(self, _key: str, value: Any) -> None:
        if not self._blocking:
            self.editorFieldChanged.emit("name", str(value))

    def _on_payload(self, key: str, value: Any) -> None:
        if self._blocking or key.startswith("__"):
            return
        if key == "synonym":
            self.editorFieldChanged.emit("title", str(value))
            return
        updated = dict(self._payload)
        updated[key] = value
        self._payload = updated
        self.editorPayloadChanged.emit(updated)

    def _on_commit(self, key: str, value: Any) -> None:
        # Editing stays reactive in memory. Persistence is explicit via the
        # Apply button or the configurator Save command, like in a regular IDE.
        return

    def _on_row_focused(self, key: str) -> None:
        self._set_help_text(self._help_text_for_key(key))

    def _on_module_open_requested(self, key: str, value: str) -> None:
        self.openModuleRequested.emit(str(key or ""), str(value or ""))

    def _set_help_text(self, text: str) -> None:
        self._help.setPlainText(str(text or ""))

    def _help_text_for_key(self, key: str) -> str:
        try:
            from src.ui_qt.i18n import get_lang
            lang = get_lang()
        except Exception:
            lang = "uk"
        normalized = str(key or "").strip("_")
        help_map = _FIELD_HELP_EXTRA.get(lang) or _FIELD_HELP_EXTRA["uk"]
        text = help_map.get(normalized)
        if text:
            return text
        label = _label_for_key(normalized)
        return label if label != normalized else ""
