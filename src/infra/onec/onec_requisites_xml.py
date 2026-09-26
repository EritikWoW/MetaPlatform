from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import xml.etree.ElementTree as ET

from .onec_requisites_model import (
    OneCEnumValue,
    OneCMetaObject,
    OneCRequisite,
    OneCTabularColumn,
    OneCTabularPart,
)


NS_MD = "http://v8.1c.ru/8.3/MDClasses"
NS_V8 = "http://v8.1c.ru/8.1/data/core"
NS_ROLE = "http://v8.1c.ru/8.2/roles"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def _tag(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


MD = lambda local: _tag(NS_MD, local)
V8 = lambda local: _tag(NS_V8, local)
ROLE = lambda local: _tag(NS_ROLE, local)


_XS_TYPE_MAP: Dict[str, str] = {
    "xs:string": "string",
    "xs:decimal": "number",
    "xs:boolean": "bool",
    "xs:date": "date",
    "xs:dateTime": "datetime",
    "xs:int": "number",
    "xs:integer": "number",
    "xs:long": "number",
}

_REF_PREFIXES: Dict[str, str] = {
    "cfg:CatalogRef.": "ref",
    "cfg:DocumentRef.": "ref",
    "cfg:EnumRef.": "enum_ref",
    "cfg:BusinessProcessRef.": "ref",
    "cfg:TaskRef.": "ref",
    "cfg:ChartOfCharacteristicTypesRef.": "ref",
    "cfg:Characteristic.": "any_ref",
    "cfg:ChartOfAccountsRef.": "ref",
    "cfg:ExchangePlanRef.": "ref",
    "cfg:AnyRef": "any_ref",
}

_ROOT_TAG_TO_OBJ_TYPE: Dict[str, str] = {
    "Constant": "constants",
    "Catalog": "catalog",
    "Document": "document",
    "Enum": "enumeration",
    "Subsystem": "subsystem",
    "InformationRegister": "register_info",
    "AccumulationRegister": "register_accum",
    "AccountingRegister": "register_accounting",
    "CalculationRegister": "register_calc",
    "Report": "report",
    "DataProcessor": "data_processor",
    "ChartOfCharacteristicTypes": "chart_of_characteristic_types",
    "ChartOfAccounts": "chart_of_accounts",
    "ChartOfCalculationTypes": "chart_of_calculation_types",
    "BusinessProcess": "business_process",
    "Task": "task",
    "DocumentJournal": "journal",
    "Role": "role",
}


def _map_onec_type(raw_type: str) -> Tuple[str, Optional[str]]:
    text = (raw_type or "").strip()
    if not text:
        return "string", None

    mapped = _XS_TYPE_MAP.get(text)
    if mapped:
        return mapped, None

    for prefix, mp_type in _REF_PREFIXES.items():
        if text.startswith(prefix):
            ref_name = text[len(prefix):] if text != prefix else ""
            return mp_type, ref_name or None

    return "unknown", text


def _synonyms_from_el(synonym_el: Optional[ET.Element]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if synonym_el is None:
        return out
    for item in synonym_el:
        lang_el = item.find(V8("lang"))
        content_el = item.find(V8("content"))
        if lang_el is not None and content_el is not None:
            lang = (lang_el.text or "").strip()
            content = (content_el.text or "").strip()
            if lang and content:
                out[lang] = content
    return out


def _localized_text_from_el(node: Optional[ET.Element]) -> str:
    values = _synonyms_from_el(node)
    for lang in ("uk", "en"):
        text = str(values.get(lang) or "").strip()
        if text:
            return text
    return ""


_SUBSYSTEM_PREFIX_RE = re.compile(r"^\s*\d+\s+(.+?)\s*$")


def _normalize_subsystem_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _SUBSYSTEM_PREFIX_RE.match(text)
    if match is not None:
        return match.group(1).strip()
    return text


def _normalize_code_value(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", raw).lower()


def _text(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _find_child(parent: ET.Element, *tags: str) -> Optional[ET.Element]:
    for tag in tags:
        el = parent.find(MD(tag))
        if el is None:
            el = parent.find(V8(tag))
        if el is not None:
            return el
        for child in list(parent):
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == tag:
                return child
    return None


def _child_text(parent: ET.Element, *tags: str) -> str:
    for tag in tags:
        el = _find_child(parent, tag)
        if el is not None:
            return (el.text or "").strip()
    return ""


def _child_text_deep(parent: ET.Element, *tags: str) -> str:
    for tag in tags:
        el = _find_child(parent, tag)
        if el is None:
            continue
        text = "".join(part.strip() for part in el.itertext() if str(part or "").strip())
        if text:
            return text
    return ""


def _child_code(parent: ET.Element, *tags: str) -> str:
    return _normalize_code_value(_child_text(parent, *tags))


def _child_bool(parent: ET.Element, *tags: str) -> Optional[bool]:
    value = _child_text(parent, *tags).strip().lower()
    if not value:
        return None
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    return None


def _child_item_texts(parent: ET.Element, tag: str) -> List[str]:
    holder = _find_child(parent, tag)
    if holder is None:
        return []
    out: List[str] = []
    for child in list(holder):
        text = "".join(part.strip() for part in child.itertext() if str(part or "").strip())
        if text:
            out.append(text)
    return out


def _role_child(parent: ET.Element, tag: str) -> Optional[ET.Element]:
    for child in list(parent):
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == tag:
            return child
    return None


def _role_child_text(parent: ET.Element, tag: str) -> str:
    child = _role_child(parent, tag)
    if child is None:
        return ""
    return (child.text or "").strip()


def _role_child_text_deep(parent: ET.Element, tag: str) -> str:
    child = _role_child(parent, tag)
    if child is None:
        return ""
    return "".join(part for part in child.itertext()).strip()


def _role_child_bool(parent: ET.Element, tag: str) -> Optional[bool]:
    value = _role_child_text(parent, tag).strip().lower()
    if not value:
        return None
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    return None


def _parse_type_block(
    type_el: Optional[ET.Element],
) -> Tuple[str, Optional[str], str, Optional[int], Optional[int], Optional[str], Optional[int], Optional[str]]:
    if type_el is None:
        return "string", None, "", None, None, None, None, None

    raw_type = ""
    for tag_name in ("Type", "TypeSet"):
        for type_item in type_el.findall(V8(tag_name)):
            value = (type_item.text or "").strip()
            if value:
                raw_type = value
                break
        if raw_type:
            break

    mp_type, ref_name = _map_onec_type(raw_type)

    digits = None
    fraction_digits = None
    allowed_sign = None
    number_qualifiers = type_el.find(V8("NumberQualifiers"))
    if number_qualifiers is not None:
        digits_text = _text(number_qualifiers.find(V8("Digits")))
        fraction_text = _text(number_qualifiers.find(V8("FractionDigits")))
        sign_text = _text(number_qualifiers.find(V8("AllowedSign")))
        digits = int(digits_text) if digits_text.isdigit() else None
        fraction_digits = int(fraction_text) if fraction_text.isdigit() else None
        allowed_sign = sign_text or None

    str_length = None
    str_allowed_length = None
    string_qualifiers = type_el.find(V8("StringQualifiers"))
    if string_qualifiers is not None:
        length_text = _text(string_qualifiers.find(V8("Length")))
        allowed_length_text = _text(string_qualifiers.find(V8("AllowedLength")))
        str_length = int(length_text) if length_text.isdigit() else None
        str_allowed_length = allowed_length_text or None

    return (
        mp_type,
        ref_name,
        raw_type,
        digits,
        fraction_digits,
        allowed_sign,
        str_length,
        str_allowed_length,
    )


def _parse_value_properties(props: ET.Element) -> Dict[str, object]:
    fill_value = _child_text_deep(props, "FillValue") or None
    parameter_links = _child_item_texts(props, "ChoiceParameterLinks")
    choice_parameters = _child_item_texts(props, "ChoiceParameters")
    return {
        "fill_checking": _child_text(props, "FillChecking"),
        "fill_value": fill_value,
        "format": _child_text_deep(props, "Format"),
        "editing_format": _child_text_deep(props, "EditFormat"),
        "hint": _synonyms_from_el(_find_child(props, "ToolTip")),
        "mark_negatives": _child_bool(props, "MarkNegatives"),
        "mask": _child_text_deep(props, "Mask"),
        "multi_line": _child_bool(props, "MultiLine") is True,
        "password_mode": _child_bool(props, "PasswordMode") is True,
        "extended_edit": _child_bool(props, "ExtendedEdit"),
        "fill_from_filling_value": _child_bool(props, "FillFromFillingValue"),
        "choice_groups_elements": _child_text(props, "ChoiceFoldersAndItems"),
        "parameter_links": parameter_links,
        "choice_parameters": choice_parameters,
        "quick_choice": _child_text(props, "QuickChoice"),
        "create_on_input": _child_text(props, "CreateOnInput"),
        "choice_form": _child_text_deep(props, "ChoiceForm"),
        "type_link": _child_text_deep(props, "LinkByType"),
        "choice_history_on_input": _child_text(props, "ChoiceHistoryOnInput"),
        "indexing": _child_text(props, "Indexing"),
        "full_text_search": _child_text(props, "FullTextSearch"),
        "data_history": _child_text(props, "DataHistory"),
    }


def _parse_attribute(attr_el: ET.Element) -> Optional[OneCRequisite]:
    uuid = (attr_el.attrib.get("uuid") or "").strip()
    props = attr_el.find(MD("Properties"))
    if props is None:
        return None

    name = _child_text(props, "Name")
    if not name:
        return None

    synonyms = _synonyms_from_el(props.find(MD("Synonym")))
    comment = _child_text(props, "Comment")
    (
        mp_type,
        ref_name,
        raw_type,
        digits,
        fraction_digits,
        allowed_sign,
        str_length,
        str_allowed_length,
    ) = _parse_type_block(props.find(MD("Type")))

    value_properties = _parse_value_properties(props)
    fill_checking = str(value_properties.get("fill_checking") or "")
    use = _child_text(props, "Use")

    return OneCRequisite(
        name=name,
        synonyms=synonyms,
        mp_type=mp_type,
        ref_name=ref_name,
        raw_type=raw_type,
        uuid=uuid,
        digits=digits,
        fraction_digits=fraction_digits,
        allowed_sign=allowed_sign,
        str_length=str_length,
        str_allowed_length=str_allowed_length,
        **value_properties,
        use=use,
        required=fill_checking == "ShowError",
        comment=comment,
    )


def _parse_tabular_column(col_el: ET.Element) -> Optional[OneCTabularColumn]:
    uuid = (col_el.attrib.get("uuid") or "").strip()
    props = col_el.find(MD("Properties"))
    if props is None:
        return None
    name = _child_text(props, "Name")
    if not name:
        return None

    synonyms = _synonyms_from_el(props.find(MD("Synonym")))
    comment = _child_text(props, "Comment")
    mp_type, ref_name, raw_type, digits, fraction_digits, _, str_length, _ = _parse_type_block(
        props.find(MD("Type"))
    )
    value_properties = _parse_value_properties(props)
    fill_checking = str(value_properties.get("fill_checking") or "")

    return OneCTabularColumn(
        name=name,
        synonyms=synonyms,
        mp_type=mp_type,
        ref_name=ref_name,
        raw_type=raw_type,
        uuid=uuid,
        digits=digits,
        fraction_digits=fraction_digits,
        str_length=str_length,
        required=fill_checking == "ShowError",
        **value_properties,
        comment=comment,
    )


def _parse_tabular_part(tp_el: ET.Element) -> Optional[OneCTabularPart]:
    uuid = (tp_el.attrib.get("uuid") or "").strip()
    props = tp_el.find(MD("Properties"))
    if props is None:
        return None
    name = _child_text(props, "Name")
    if not name:
        return None

    synonyms = _synonyms_from_el(props.find(MD("Synonym")))
    comment = _child_text(props, "Comment")
    columns: List[OneCTabularColumn] = []
    child_objects = tp_el.find(MD("ChildObjects"))
    if child_objects is not None:
        for col_el in child_objects.findall(MD("Attribute")):
            column = _parse_tabular_column(col_el)
            if column:
                columns.append(column)

    return OneCTabularPart(
        name=name,
        synonyms=synonyms,
        uuid=uuid,
        columns=columns,
        comment=comment,
    )


def _parse_enum_value(val_el: ET.Element, order: int) -> Optional[OneCEnumValue]:
    uuid = (val_el.attrib.get("uuid") or "").strip()
    props = val_el.find(MD("Properties"))
    if props is None:
        return None
    name = _child_text(props, "Name")
    if not name:
        return None
    return OneCEnumValue(
        name=name,
        synonyms=_synonyms_from_el(props.find(MD("Synonym"))),
        uuid=uuid,
        order=order,
        comment=_child_text(props, "Comment"),
    )


def parse_object_xml(xml_bytes: bytes, origin_path: str = "") -> Optional[OneCMetaObject]:
    try:
        root = ET.fromstring(xml_bytes.lstrip(b"\xef\xbb\xbf"))
    except ET.ParseError:
        return None

    meta_root = root
    if root.tag == MD("MetaDataObject") or root.tag == "MetaDataObject":
        children = list(root)
        if not children:
            return None
        meta_root = children[0]

    local_tag = meta_root.tag.split("}")[-1] if "}" in meta_root.tag else meta_root.tag
    obj_type = _ROOT_TAG_TO_OBJ_TYPE.get(local_tag)
    if not obj_type:
        return None

    uuid = (meta_root.attrib.get("uuid") or "").strip()
    props = meta_root.find(MD("Properties"))
    if props is None:
        return None

    name = _child_text(props, "Name") or _child_text(props, "n")
    synonyms = _synonyms_from_el(props.find(MD("Synonym")))
    if obj_type == "subsystem":
        name = _normalize_subsystem_label(name)
        synonyms = {lang: _normalize_subsystem_label(text) for lang, text in synonyms.items() if str(text or "").strip()}
    comment = _child_text(props, "Comment")
    use_standard_commands = _child_bool(props, "UseStandardCommands")
    number_type = _child_code(props, "NumberType")
    number_length_text = _child_text(props, "NumberLength")
    number_allowed_length = _child_code(props, "NumberAllowedLength")
    number_periodicity = _child_text(props, "NumberPeriodicity")
    check_unique = _child_bool(props, "CheckUnique")
    autonumbering = _child_text(props, "Autonumbering")
    posting = _child_text(props, "Posting")
    real_time_posting = _child_code(props, "RealTimePosting")
    input_by_string = _child_text_deep(props, "InputByString")
    based_on = _child_item_texts(props, "BasedOn")
    create_on_input = _child_code(props, "CreateOnInput")
    search_string_mode_on_input_by_string = _child_code(props, "SearchStringModeOnInputByString")
    full_text_search_on_input_by_string = _child_code(props, "FullTextSearchOnInputByString")
    choice_data_get_mode_on_input_by_string = _child_code(props, "ChoiceDataGetModeOnInputByString")
    choice_history_on_input = _child_code(props, "ChoiceHistoryOnInput")
    default_object_form = _child_text(props, "DefaultObjectForm")
    default_list_form = _child_text(props, "DefaultListForm")
    default_choice_form = _child_text(props, "DefaultChoiceForm")
    register_records_deletion = _child_code(props, "RegisterRecordsDeletion")
    register_records_writing_on_post = _child_code(props, "RegisterRecordsWritingOnPost")
    sequence_filling = _child_code(props, "SequenceFilling")
    register_records = _child_item_texts(props, "RegisterRecords")
    post_in_privileged_mode = _child_bool(props, "PostInPrivilegedMode")
    unpost_in_privileged_mode = _child_bool(props, "UnpostInPrivilegedMode")
    include_help_in_contents = _child_bool(props, "IncludeHelpInContents")
    include_in_command_interface = _child_bool(props, "IncludeInCommandInterface")
    use_one_command = _child_bool(props, "UseOneCommand")
    picture_ref = _child_text_deep(props, "Picture")
    content_refs = _child_item_texts(props, "Content")
    data_lock_fields = ", ".join(_child_item_texts(props, "DataLockFields")) or _child_text_deep(props, "DataLockFields")
    data_lock_control_mode = _child_code(props, "DataLockControlMode")
    object_presentation = _synonyms_from_el(props.find(MD("ObjectPresentation")))
    object_presentation_ext = _synonyms_from_el(props.find(MD("ExtendedObjectPresentation")))
    list_presentation = _synonyms_from_el(props.find(MD("ListPresentation")))
    list_presentation_ext = _synonyms_from_el(props.find(MD("ExtendedListPresentation")))
    explanation = _synonyms_from_el(props.find(MD("Explanation")))
    hint = _synonyms_from_el(props.find(MD("ToolTip")))
    full_text_search = _child_code(props, "FullTextSearch")
    data_history = _child_code(props, "DataHistory")
    update_data_history_immediately_after_write = _child_bool(props, "UpdateDataHistoryImmediatelyAfterWrite")
    execute_after_write_data_history_version_processing = _child_bool(
        props,
        "ExecuteAfterWriteDataHistoryVersionProcessing",
    )
    hierarchy_type = _child_text(props, "HierarchyType")

    owners: List[str] = []
    owners_el = props.find(MD("Owners"))
    if owners_el is not None:
        for owner_el in owners_el:
            text = (owner_el.text or "").strip()
            if text:
                owners.append(text.split(".")[-1] if "." in text else text)

    register_obj_types = {"register_info", "register_accum", "register_accounting", "register_calc"}
    requisites: List[OneCRequisite] = []
    attributes: List[OneCRequisite] = []
    dimensions: List[OneCRequisite] = []
    resources: List[OneCRequisite] = []
    tabular_parts: List[OneCTabularPart] = []
    enum_values: List[OneCEnumValue] = []
    child_subsystems: List[str] = []

    child_objects = meta_root.find(MD("ChildObjects"))
    if child_objects is not None:
        enum_order = 0
        seen_child_subsystems: set[str] = set()
        for child in child_objects:
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == "Attribute":
                req = _parse_attribute(child)
                if req:
                    if obj_type in register_obj_types:
                        attributes.append(req)
                    else:
                        requisites.append(req)
            elif local == "Dimension":
                req = _parse_attribute(child)
                if req:
                    dimensions.append(req)
            elif local == "Resource":
                req = _parse_attribute(child)
                if req:
                    resources.append(req)
            elif local == "TabularSection":
                part = _parse_tabular_part(child)
                if part:
                    tabular_parts.append(part)
            elif local == "EnumValue":
                enum_value = _parse_enum_value(child, enum_order)
                if enum_value:
                    enum_values.append(enum_value)
                    enum_order += 1
            elif local == "Subsystem":
                text = (child.text or "").strip()
                if text:
                    value = _normalize_subsystem_label(text) if obj_type == "subsystem" else text
                    value = value.strip()
                    if value and value not in seen_child_subsystems:
                        seen_child_subsystems.add(value)
                        child_subsystems.append(value)

    return OneCMetaObject(
        obj_type=obj_type,
        name=name,
        synonyms=synonyms,
        uuid=uuid,
        comment=comment,
        origin_path=origin_path,
        requisites=requisites,
        attributes=attributes,
        dimensions=dimensions,
        resources=resources,
        tabular_parts=tabular_parts,
        enum_values=enum_values,
        hierarchy_type=hierarchy_type,
        owners=owners,
        use_standard_commands=use_standard_commands,
        number_type=number_type,
        number_length=int(number_length_text) if number_length_text.isdigit() else None,
        number_allowed_length=number_allowed_length,
        number_periodicity=_normalize_code_value(number_periodicity),
        check_unique=check_unique,
        autonumbering=(autonumbering.lower() == "true") if autonumbering else None,
        posting=_normalize_code_value(posting),
        real_time_posting=real_time_posting,
        input_by_string=(
            _normalize_code_value(input_by_string)
            if input_by_string in {"NumberDate", "Number", "Code"}
            else input_by_string
        ),
        based_on=based_on,
        create_on_input=create_on_input,
        search_string_mode_on_input_by_string=search_string_mode_on_input_by_string,
        full_text_search_on_input_by_string=full_text_search_on_input_by_string,
        choice_data_get_mode_on_input_by_string=choice_data_get_mode_on_input_by_string,
        choice_history_on_input=choice_history_on_input,
        default_object_form=default_object_form,
        default_list_form=default_list_form,
        default_choice_form=default_choice_form,
        register_records_deletion=register_records_deletion,
        register_records_writing_on_post=register_records_writing_on_post,
        sequence_filling=sequence_filling,
        register_records=register_records,
        post_in_privileged_mode=post_in_privileged_mode,
        unpost_in_privileged_mode=unpost_in_privileged_mode,
        include_help_in_contents=include_help_in_contents,
        include_in_command_interface=include_in_command_interface,
        use_one_command=use_one_command,
        picture_ref=picture_ref,
        content_refs=content_refs,
        child_subsystems=child_subsystems,
        data_lock_fields=data_lock_fields,
        data_lock_control_mode=data_lock_control_mode,
        object_presentation=object_presentation,
        object_presentation_ext=object_presentation_ext,
        list_presentation=list_presentation,
        list_presentation_ext=list_presentation_ext,
        explanation=explanation,
        hint=hint,
        full_text_search=full_text_search,
        data_history=data_history,
        update_data_history_immediately_after_write=update_data_history_immediately_after_write,
        execute_after_write_data_history_version_processing=execute_after_write_data_history_version_processing,
    )


def parse_role_rights_xml(xml_bytes: bytes) -> Dict[str, object]:
    try:
        root = ET.fromstring(xml_bytes.lstrip(b"\xef\xbb\xbf"))
    except ET.ParseError:
        return {}

    local_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if local_tag != "Rights":
        return {}

    payload: Dict[str, object] = {}
    set_for_new_objects = _role_child_bool(root, "setForNewObjects")
    set_for_attributes_by_default = _role_child_bool(root, "setForAttributesByDefault")
    independent_rights_of_child_objects = _role_child_bool(root, "independentRightsOfChildObjects")

    if set_for_new_objects is not None:
        payload["set_for_new_objects"] = set_for_new_objects
    if set_for_attributes_by_default is not None:
        payload["set_for_attributes_by_default"] = set_for_attributes_by_default
    if independent_rights_of_child_objects is not None:
        payload["independent_rights_of_child_objects"] = independent_rights_of_child_objects

    rights_items: List[Dict[str, object]] = []
    for obj_el in root.findall(ROLE("object")):
        object_name = _role_child_text(obj_el, "name")
        if not object_name:
            continue
        rights_map: Dict[str, bool] = {}
        restrictions: List[Dict[str, str]] = []
        for right_el in obj_el.findall(ROLE("right")):
            right_name = _role_child_text(right_el, "name")
            if not right_name:
                continue
            right_value = _role_child_bool(right_el, "value")
            rights_map[right_name] = bool(right_value)
            restriction_el = _role_child(right_el, "restrictionByCondition")
            if restriction_el is not None:
                restriction = _role_child_text_deep(restriction_el, "condition")
                restriction_field = _role_child_text(restriction_el, "field")
                if restriction:
                    item = {
                        "right": right_name,
                        "condition": restriction,
                    }
                    if restriction_field:
                        item["field"] = restriction_field
                    restrictions.append(item)
        entry: Dict[str, object] = {
            "object": object_name,
            "rights": rights_map,
        }
        if restrictions:
            entry["restrictions"] = restrictions
        rights_items.append(entry)
    if rights_items:
        payload["rights"] = rights_items

    restriction_templates: List[Dict[str, str]] = []
    for tmpl_el in root.findall(ROLE("restrictionTemplate")):
        name = _role_child_text(tmpl_el, "name")
        condition = _role_child_text_deep(tmpl_el, "condition")
        if not name and not condition:
            continue
        restriction_templates.append(
            {
                "name": name,
                "condition": condition,
            }
        )
    if restriction_templates:
        payload["restriction_templates"] = restriction_templates

    return payload


__all__ = [
    "NS_MD",
    "NS_V8",
    "NS_ROLE",
    "NS_XSI",
    "MD",
    "V8",
    "ROLE",
    "parse_object_xml",
    "parse_role_rights_xml",
]
