from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _unique_strings(values: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


@dataclass
class OneCRequisite:
    """Реквизит объекта 1С."""

    name: str
    synonyms: Dict[str, str]
    mp_type: str
    ref_name: Optional[str]
    raw_type: str
    uuid: str
    digits: Optional[int] = None
    fraction_digits: Optional[int] = None
    allowed_sign: Optional[str] = None
    str_length: Optional[int] = None
    str_allowed_length: Optional[str] = None
    fill_checking: str = ""
    fill_value: Any = None
    use: str = ""
    required: bool = False
    read_only: bool = False
    multi_line: bool = False
    password_mode: bool = False
    comment: str = ""
    format: str = ""
    editing_format: str = ""
    hint: Dict[str, str] = field(default_factory=dict)
    mark_negatives: Optional[bool] = None
    mask: str = ""
    extended_edit: Optional[bool] = None
    fill_from_filling_value: Optional[bool] = None
    choice_groups_elements: str = ""
    parameter_links: List[str] = field(default_factory=list)
    choice_parameters: List[str] = field(default_factory=list)
    quick_choice: str = ""
    create_on_input: str = ""
    choice_form: str = ""
    type_link: str = ""
    choice_history_on_input: str = ""
    indexing: str = ""
    full_text_search: str = ""
    data_history: str = ""

    def to_mp_payload(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "name": self.name,
            "title": self.synonyms,
            "type": self.mp_type,
            "required": self.required,
            "read_only": self.read_only,
            "system": False,
            "comment": self.comment,
            "imported": {
                "source": "1c",
                "src_uuid": self.uuid,
                "raw_type": self.raw_type,
            },
        }
        if self.ref_name:
            data["ref_name"] = self.ref_name
        if self.mp_type == "number":
            qualifiers: Dict[str, Any] = {}
            if self.digits is not None:
                qualifiers["digits"] = self.digits
            if self.fraction_digits is not None:
                qualifiers["fraction_digits"] = self.fraction_digits
            if self.allowed_sign:
                qualifiers["allowed_sign"] = self.allowed_sign
            if qualifiers:
                data["number_qualifiers"] = qualifiers
        if self.mp_type == "string":
            qualifiers = {}
            if self.str_length is not None:
                qualifiers["length"] = self.str_length
            if self.str_allowed_length:
                qualifiers["allowed_length"] = self.str_allowed_length
            if qualifiers:
                data["string_qualifiers"] = qualifiers
        if self.fill_checking:
            data["fill_checking"] = self.fill_checking
        if self.fill_value is not None:
            data["fill_value"] = self.fill_value
        if self.use:
            data["use"] = self.use
        if self.multi_line:
            data["multi_line"] = True
        if self.password_mode:
            data["password_mode"] = True
        if self.format:
            data["format"] = self.format
        if self.editing_format:
            data["editing_format"] = self.editing_format
        if self.hint:
            data["hint"] = dict(self.hint)
        if self.mark_negatives is not None:
            data["mark_negatives"] = self.mark_negatives
        if self.mask:
            data["mask"] = self.mask
        if self.extended_edit is not None:
            data["extended_edit"] = self.extended_edit
        if self.fill_from_filling_value is not None:
            data["fill_from_filling_value"] = self.fill_from_filling_value
        if self.choice_groups_elements:
            data["choice_groups_elements"] = self.choice_groups_elements
        if self.parameter_links:
            data["parameter_links"] = list(self.parameter_links)
        if self.choice_parameters:
            data["choice_parameters"] = list(self.choice_parameters)
        if self.quick_choice:
            data["quick_choice"] = self.quick_choice
        if self.create_on_input:
            data["create_on_input"] = self.create_on_input
        if self.choice_form:
            data["choice_form"] = self.choice_form
        if self.type_link:
            data["type_link"] = self.type_link
        if self.choice_history_on_input:
            data["choice_history_on_input"] = self.choice_history_on_input
        if self.indexing:
            data["indexing"] = self.indexing
        if self.full_text_search:
            data["full_text_search"] = self.full_text_search
        if self.data_history:
            data["data_history"] = self.data_history
        return data


@dataclass
class OneCTabularColumn:
    """Колонка табличной части."""

    name: str
    synonyms: Dict[str, str]
    mp_type: str
    ref_name: Optional[str]
    raw_type: str
    uuid: str
    digits: Optional[int] = None
    fraction_digits: Optional[int] = None
    str_length: Optional[int] = None
    required: bool = False
    fill_checking: str = ""
    comment: str = ""
    fill_value: Any = None
    format: str = ""
    editing_format: str = ""
    hint: Dict[str, str] = field(default_factory=dict)
    mark_negatives: Optional[bool] = None
    mask: str = ""
    multi_line: bool = False
    password_mode: bool = False
    extended_edit: Optional[bool] = None
    fill_from_filling_value: Optional[bool] = None
    choice_groups_elements: str = ""
    parameter_links: List[str] = field(default_factory=list)
    choice_parameters: List[str] = field(default_factory=list)
    quick_choice: str = ""
    create_on_input: str = ""
    choice_form: str = ""
    type_link: str = ""
    choice_history_on_input: str = ""
    indexing: str = ""
    full_text_search: str = ""
    data_history: str = ""

    def to_mp_payload(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "name": self.name,
            "title": self.synonyms,
            "type": self.mp_type,
            "required": self.required,
            "comment": self.comment,
            "imported": {
                "source": "1c",
                "src_uuid": self.uuid,
                "raw_type": self.raw_type,
            },
        }
        if self.ref_name:
            data["ref_name"] = self.ref_name
        if self.mp_type == "number" and self.digits is not None:
            data["number_qualifiers"] = {
                "digits": self.digits,
                "fraction_digits": self.fraction_digits or 0,
            }
        if self.mp_type == "string" and self.str_length is not None:
            data["string_qualifiers"] = {"length": self.str_length}
        if self.fill_checking:
            data["fill_checking"] = self.fill_checking
        if self.fill_value is not None:
            data["fill_value"] = self.fill_value
        if self.format:
            data["format"] = self.format
        if self.editing_format:
            data["editing_format"] = self.editing_format
        if self.hint:
            data["hint"] = dict(self.hint)
        if self.mark_negatives is not None:
            data["mark_negatives"] = self.mark_negatives
        if self.mask:
            data["mask"] = self.mask
        if self.multi_line:
            data["multi_line"] = True
        if self.password_mode:
            data["password_mode"] = True
        if self.extended_edit is not None:
            data["extended_edit"] = self.extended_edit
        if self.fill_from_filling_value is not None:
            data["fill_from_filling_value"] = self.fill_from_filling_value
        if self.choice_groups_elements:
            data["choice_groups_elements"] = self.choice_groups_elements
        if self.parameter_links:
            data["parameter_links"] = list(self.parameter_links)
        if self.choice_parameters:
            data["choice_parameters"] = list(self.choice_parameters)
        if self.quick_choice:
            data["quick_choice"] = self.quick_choice
        if self.create_on_input:
            data["create_on_input"] = self.create_on_input
        if self.choice_form:
            data["choice_form"] = self.choice_form
        if self.type_link:
            data["type_link"] = self.type_link
        if self.choice_history_on_input:
            data["choice_history_on_input"] = self.choice_history_on_input
        if self.indexing:
            data["indexing"] = self.indexing
        if self.full_text_search:
            data["full_text_search"] = self.full_text_search
        if self.data_history:
            data["data_history"] = self.data_history
        return data


@dataclass
class OneCTabularPart:
    """Табличная часть объекта 1С."""

    name: str
    synonyms: Dict[str, str]
    uuid: str
    columns: List[OneCTabularColumn] = field(default_factory=list)
    comment: str = ""

    def to_mp_payload(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "title": self.synonyms,
            "comment": self.comment,
            "columns": [column.to_mp_payload() for column in self.columns],
            "imported": {"source": "1c", "src_uuid": self.uuid},
        }


@dataclass
class OneCEnumValue:
    """Значение перечисления."""

    name: str
    synonyms: Dict[str, str]
    uuid: str
    order: int = 0
    comment: str = ""

    def to_mp_payload(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "title": self.synonyms,
            "order": self.order,
            "comment": self.comment,
            "imported": {"source": "1c", "src_uuid": self.uuid},
        }


@dataclass
class OneCMetaObject:
    """Разобранный объект конфигурации 1С."""

    obj_type: str
    name: str
    synonyms: Dict[str, str]
    uuid: str
    comment: str = ""
    origin_path: str = ""
    requisites: List[OneCRequisite] = field(default_factory=list)
    attributes: List[OneCRequisite] = field(default_factory=list)
    dimensions: List[OneCRequisite] = field(default_factory=list)
    resources: List[OneCRequisite] = field(default_factory=list)
    tabular_parts: List[OneCTabularPart] = field(default_factory=list)
    enum_values: List[OneCEnumValue] = field(default_factory=list)
    hierarchy_type: str = ""
    owners: List[str] = field(default_factory=list)
    use_standard_commands: Optional[bool] = None
    number_type: str = ""
    number_allowed_length: str = ""
    number_length: Optional[int] = None
    number_periodicity: str = ""
    check_unique: Optional[bool] = None
    autonumbering: Optional[bool] = None
    posting: str = ""
    real_time_posting: str = ""
    register_records_deletion: str = ""
    register_records_writing_on_post: str = ""
    sequence_filling: str = ""
    input_by_string: str = ""
    based_on: List[str] = field(default_factory=list)
    register_records: List[str] = field(default_factory=list)
    create_on_input: str = ""
    search_string_mode_on_input_by_string: str = ""
    full_text_search_on_input_by_string: str = ""
    choice_data_get_mode_on_input_by_string: str = ""
    choice_history_on_input: str = ""
    default_object_form: str = ""
    default_list_form: str = ""
    default_choice_form: str = ""
    object_presentation: Dict[str, str] = field(default_factory=dict)
    object_presentation_ext: Dict[str, str] = field(default_factory=dict)
    list_presentation: Dict[str, str] = field(default_factory=dict)
    list_presentation_ext: Dict[str, str] = field(default_factory=dict)
    explanation: Dict[str, str] = field(default_factory=dict)
    hint: Dict[str, str] = field(default_factory=dict)
    full_text_search: str = ""
    data_history: str = ""
    update_data_history_immediately_after_write: Optional[bool] = None
    execute_after_write_data_history_version_processing: Optional[bool] = None
    post_in_privileged_mode: Optional[bool] = None
    unpost_in_privileged_mode: Optional[bool] = None
    include_help_in_contents: Optional[bool] = None
    include_in_command_interface: Optional[bool] = None
    use_one_command: Optional[bool] = None
    picture_ref: str = ""
    content_refs: List[str] = field(default_factory=list)
    child_subsystems: List[str] = field(default_factory=list)
    set_for_new_objects: Optional[bool] = None
    set_for_attributes_by_default: Optional[bool] = None
    independent_rights_of_child_objects: Optional[bool] = None
    rights: List[Dict[str, Any]] = field(default_factory=list)
    restriction_templates: List[Dict[str, Any]] = field(default_factory=list)
    data_lock_fields: str = ""
    data_lock_control_mode: str = ""

    def to_mp_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "imported": {
                "source": "1c",
                "src_uuid": self.uuid,
                "origin": self.origin_path,
            },
            "comment": self.comment,
        }
        if self.requisites:
            payload["requisites"] = [req.to_mp_payload() for req in self.requisites]
        if self.attributes:
            payload["attributes"] = [req.to_mp_payload() for req in self.attributes]
        if self.dimensions:
            payload["dimensions"] = [req.to_mp_payload() for req in self.dimensions]
        if self.resources:
            payload["resources"] = [req.to_mp_payload() for req in self.resources]
        if self.tabular_parts:
            payload["tabular_parts"] = [part.to_mp_payload() for part in self.tabular_parts]
        if self.enum_values:
            payload["enum_values"] = [value.to_mp_payload() for value in self.enum_values]
        if self.hierarchy_type:
            payload["hierarchy_type"] = self.hierarchy_type
        if self.owners:
            payload["owners"] = self.owners
        if self.use_standard_commands is not None:
            payload["use_standard_commands"] = self.use_standard_commands
        if self.number_type:
            payload["number_type"] = self.number_type
        if self.number_allowed_length:
            payload["number_allowed_length"] = self.number_allowed_length
        if self.number_length is not None:
            payload["number_length"] = self.number_length
        if self.number_periodicity:
            payload["number_periodicity"] = self.number_periodicity
        if self.check_unique is not None:
            payload["check_unique"] = self.check_unique
        if self.autonumbering is not None:
            payload["autonumbering"] = self.autonumbering
        if self.posting:
            payload["posting"] = self.posting
        if self.real_time_posting:
            payload["real_time_posting"] = self.real_time_posting
        if self.register_records_deletion:
            payload["register_records_deletion"] = self.register_records_deletion
        if self.register_records_writing_on_post:
            payload["register_records_writing_on_post"] = self.register_records_writing_on_post
        if self.sequence_filling:
            payload["sequence_filling"] = self.sequence_filling
        if self.input_by_string:
            payload["input_by_string"] = self.input_by_string
            payload["input_by_string_field"] = self.input_by_string
        if self.based_on:
            payload["based_on"] = list(self.based_on)
        if self.register_records:
            payload["register_records"] = list(self.register_records)
        if self.create_on_input:
            payload["create_on_input"] = self.create_on_input
        if self.search_string_mode_on_input_by_string:
            payload["search_string_mode_on_input_by_string"] = self.search_string_mode_on_input_by_string
        if self.full_text_search_on_input_by_string:
            payload["full_text_search_on_input_by_string"] = self.full_text_search_on_input_by_string
        if self.choice_data_get_mode_on_input_by_string:
            payload["choice_data_get_mode_on_input_by_string"] = self.choice_data_get_mode_on_input_by_string
        if self.choice_history_on_input:
            payload["choice_history_on_input"] = self.choice_history_on_input
        if self.default_object_form:
            payload["default_object_form"] = self.default_object_form
        if self.default_list_form:
            payload["default_list_form"] = self.default_list_form
        if self.default_choice_form:
            payload["default_choice_form"] = self.default_choice_form
        if self.object_presentation:
            payload["object_presentation"] = dict(self.object_presentation)
        if self.object_presentation_ext:
            payload["extended_object_presentation"] = dict(self.object_presentation_ext)
            payload["object_presentation_ext"] = dict(self.object_presentation_ext)
        if self.list_presentation:
            payload["list_presentation"] = dict(self.list_presentation)
        if self.list_presentation_ext:
            payload["extended_list_presentation"] = dict(self.list_presentation_ext)
            payload["list_presentation_ext"] = dict(self.list_presentation_ext)
        if self.explanation:
            payload["explanation"] = dict(self.explanation)
        if self.hint:
            payload["hint"] = dict(self.hint)
        if self.full_text_search:
            payload["full_text_search"] = self.full_text_search
        if self.data_history:
            payload["data_history"] = self.data_history
        if self.update_data_history_immediately_after_write is not None:
            payload["update_data_history_immediately_after_write"] = (
                self.update_data_history_immediately_after_write
            )
        if self.execute_after_write_data_history_version_processing is not None:
            payload["execute_after_write_data_history_version_processing"] = (
                self.execute_after_write_data_history_version_processing
            )
        if self.post_in_privileged_mode is not None:
            payload["post_in_privileged_mode"] = self.post_in_privileged_mode
        if self.unpost_in_privileged_mode is not None:
            payload["unpost_in_privileged_mode"] = self.unpost_in_privileged_mode
        if self.include_help_in_contents is not None:
            payload["include_help_in_contents"] = self.include_help_in_contents
        if self.include_in_command_interface is not None:
            payload["include_in_command_interface"] = self.include_in_command_interface
        if self.use_one_command is not None:
            payload["use_one_command"] = self.use_one_command
        if self.picture_ref:
            payload["picture_ref"] = self.picture_ref
        if self.content_refs:
            payload["content_refs"] = _unique_strings(list(self.content_refs))
        if self.child_subsystems:
            payload["child_subsystems"] = _unique_strings(list(self.child_subsystems))
        if self.set_for_new_objects is not None:
            payload["set_for_new_objects"] = self.set_for_new_objects
        if self.set_for_attributes_by_default is not None:
            payload["set_for_attributes_by_default"] = self.set_for_attributes_by_default
        if self.independent_rights_of_child_objects is not None:
            payload["independent_rights_of_child_objects"] = self.independent_rights_of_child_objects
        if self.rights:
            payload["rights"] = [dict(item) for item in self.rights if isinstance(item, dict)]
        if self.restriction_templates:
            payload["restriction_templates"] = [
                dict(item) for item in self.restriction_templates if isinstance(item, dict)
            ]
        if self.data_lock_fields:
            payload["data_lock_fields"] = self.data_lock_fields
        if self.data_lock_control_mode:
            payload["data_lock_control_mode"] = self.data_lock_control_mode
        return payload


__all__ = [
    "OneCRequisite",
    "OneCTabularColumn",
    "OneCTabularPart",
    "OneCEnumValue",
    "OneCMetaObject",
]
