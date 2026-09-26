from PySide6.QtWidgets import QApplication, QPlainTextEdit
from types import SimpleNamespace

from src.ui_qt.widgets.manifest_properties_panel import (
    ManifestPropertiesPanel,
    _SECTION_DEFS,
    _dynamic_field_defs,
    _normalize_object_type,
    _payload_value,
)


def test_properties_show_source_name_but_preserve_synonym_without_emitting_edits():
    app = QApplication.instance() or QApplication([])
    panel = ManifestPropertiesPanel()
    changes = []
    panel.editorFieldChanged.connect(lambda *args: changes.append(args))
    panel.update_editor(SimpleNamespace(current={
        "guid": "doc", "type": "document", "name": "PhysicalAlias", "title": "User label",
        "payload": {"source_name": "ActualSourceName"},
    }))
    assert panel._title.text() == "ActualSourceName"
    assert panel._name_row.get_value() == "ActualSourceName"
    assert panel._rows["synonym"].get_value() == "User label"
    assert not changes
    panel.deleteLater()


def test_normalize_object_type_uses_common_subtype() -> None:
    assert _normalize_object_type("common", {"subtype": "common_form"}) == "common_form"


def test_normalize_object_type_maps_aliases() -> None:
    assert _normalize_object_type("session_parameter", {}) == "session_param"
    assert _normalize_object_type("styles", {}) == "style"


def test_dynamic_field_defs_include_scalar_and_complex_payload_rows() -> None:
    defs = _dynamic_field_defs(
        {
            "quick_choice": True,
            "full_text_search": False,
            "notes": "Long enough\ntext",
            "source_path": "skip",
            "command_interface": {"main": "Sales"},
            "main_roles": ["Role.Admin", "Role.User"],
            "form_model": {"nodes": []},
            "length": 12,
        },
        known_keys={"length"},
    )
    keys = [entry[0] for entry in defs]
    assert "__section__" in keys
    assert "quick_choice" in keys
    assert "full_text_search" in keys
    assert "notes" in keys
    assert "command_interface" in keys
    assert "main_roles" in keys
    assert "length" not in keys
    assert "source_path" not in keys
    assert "form_model" not in keys


def test_dynamic_field_defs_skip_internal_structure_blobs() -> None:
    defs = _dynamic_field_defs(
        {
            "metadata_structure": {"sections": []},
            "storage_profile": {"family": "catalog"},
            "custom_field": "value",
        },
        known_keys=set(),
    )
    keys = [entry[0] for entry in defs]
    assert "metadata_structure" not in keys
    assert "storage_profile" not in keys
    assert "custom_field" in keys


def test_payload_value_uses_aliases_and_localizes_dicts() -> None:
    payload = {
        "number_length": 11,
        "default_language": "uk",
        "report_form": "Config.Report.Form",
        "module_asset_key": "module://abc",
        "code_length": 9,
        "name_length": 150,
        "edit_format": "0.00",
        "link_by_type": "Document.BaseDoc",
        "obj_presentation": {"uk": "Присоединенный файл", "ru": "Присоединенный файл"},
        "title": {"uk": "Авансовий звіт", "ru": "Авансовый отчет"},
        "list_presentation": {"uk": "Авансові звіти"},
    }

    assert _payload_value(payload, "number_length") == 11
    assert _payload_value(payload, "code_len") == 9
    assert _payload_value(payload, "name_length") == 150
    assert _payload_value(payload, "main_language") == "uk"
    assert _payload_value(payload, "default_report_form") == "Config.Report.Form"
    assert _payload_value(payload, "module") == "module://abc"
    assert _payload_value(payload, "editing_format") == "0.00"
    assert _payload_value(payload, "type_link") == "Document.BaseDoc"
    assert _payload_value(payload, "obj_presentation") == "Присоединенный файл"
    assert _payload_value(payload, "list_presentation") == "Авансові звіти"


def test_configuration_section_is_more_complete() -> None:
    defs = _SECTION_DEFS["configuration"]
    keys = [entry[0] for entry in defs if entry and not str(entry[0]).startswith("__")]
    assert "brief_info" in keys
    assert "detail_info" in keys
    assert "main_interface" in keys
    assert "main_style" in keys
    assert "main_language" in keys
    assert "version" in keys
    assert "vendor" in keys
    assert "update_address" in keys
    assert "author" in keys
    assert "include_help_in_contents" in keys
    assert "include_in_command_interface" in keys
    assert "command_interface" in keys
    assert "default_report_form" in keys
    assert "default_choice_form" in keys
    assert "compatibility_mode" in keys
    assert "data_lock_control_mode" in keys


def test_subsystem_section_has_command_interface_controls() -> None:
    defs = _SECTION_DEFS["subsystem"]
    keys = [entry[0] for entry in defs if entry and not str(entry[0]).startswith("__")]
    assert "include_in_command_interface" in keys
    assert "command_interface" in keys
    assert "use_one_command" in keys
    assert "picture_ref" in keys


def test_common_attribute_section_matches_rich_metadata_profile() -> None:
    defs = _SECTION_DEFS["common_attribute"]
    keys = [entry[0] for entry in defs if entry and not str(entry[0]).startswith("__")]
    for expected in (
        "type",
        "module",
        "module_manager",
        "module_manager_value",
        "length",
        "precision",
        "format",
        "editing_format",
        "hint",
        "type_link",
        "fill_check",
        "check_unique",
        "quick_choice",
        "full_text_search",
        "data_history",
        "update_data_history_immediately_after_write",
        "execute_after_write_data_history_version_processing",
        "main_presentation",
        "obj_presentation",
        "list_presentation",
        "include_help_in_contents",
        "help_info",
    ):
        assert expected in keys


def test_catalog_section_has_rich_object_profile() -> None:
    defs = _SECTION_DEFS["catalog"]
    keys = [entry[0] for entry in defs if entry and not str(entry[0]).startswith("__")]
    for expected in (
        "hierarchical",
        "hierarchy_type",
        "owners",
        "code_length",
        "name_length",
        "code_type",
        "check_unique",
        "autonumbering",
        "input_by_string",
        "create_on_input",
        "search_string_mode_on_input_by_string",
        "choice_data_get_mode_on_input_by_string",
        "choice_history_on_input",
        "data_lock_fields",
        "data_lock_control_mode",
        "full_text_search",
        "data_history",
        "default_object_form",
        "default_list_form",
        "default_choice_form",
        "obj_presentation",
        "obj_presentation_ext",
        "list_presentation",
        "list_presentation_ext",
    ):
        assert expected in keys


def test_common_module_section_includes_module_link() -> None:
    defs = _SECTION_DEFS["common_module"]
    keys = [entry[0] for entry in defs if entry and not str(entry[0]).startswith("__")]
    assert "module" in keys


def test_schema_requisite_section_matches_metadata_property_profile() -> None:
    defs = _SECTION_DEFS["schema_requisite"]
    keys = [entry[0] for entry in defs if entry and not str(entry[0]).startswith("__")]
    for expected in (
        "type",
        "source_type",
        "ref_name",
        "string_length",
        "number_digits",
        "number_fraction_digits",
        "indexing",
        "full_text_search",
        "data_history",
        "hint",
        "fill_from_filling_value",
        "fill_value",
        "fill_checking",
        "choice_groups_elements",
        "parameter_links",
        "choice_parameters",
        "choice_form",
        "quick_choice",
        "create_on_input",
        "choice_history_on_input",
        "type_link",
        "required",
        "read_only",
    ):
        assert expected in keys


def test_manifest_properties_panel_has_pinned_help_footer() -> None:
    app = QApplication.instance() or QApplication([])
    panel = ManifestPropertiesPanel()
    panel.update_editor(
        type(
            "_State",
            (),
            {
                "current": {
                    "guid": "cfg-guid",
                    "type": "configuration",
                    "name": "Configuration",
                    "title": "Конфігурація",
                    "payload": {"synonym": "Конфігурація"},
                }
            },
        )()
    )

    help_boxes = [item for item in panel.findChildren(QPlainTextEdit) if item.objectName() == "ManifestPropertiesHelp"]
    assert help_boxes
    assert app is not None
