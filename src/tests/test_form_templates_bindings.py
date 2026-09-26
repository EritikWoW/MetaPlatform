from __future__ import annotations

from src.configurator.domain.default_schema import default_attributes_for_object
from src.configurator.domain.form_templates import build_list_form_model, build_object_form_model


def _table_columns(model: dict[str, object]) -> list[dict[str, object]]:
    root = dict(model.get("root") or {})
    children = list(root.get("children") or [])
    for node in children:
        if isinstance(node, dict) and str(node.get("type") or "") == "Table":
            props = dict(node.get("props") or {})
            return list(props.get("columns") or [])
    return []


def _text_bindings(model: dict[str, object]) -> list[str]:
    root = dict(model.get("root") or {})
    children = list(root.get("children") or [])
    out: list[str] = []
    for node in children:
        if not isinstance(node, dict):
            continue
        if str(node.get("type") or "") != "TextBox":
            continue
        out.append(str(node.get("binding") or ""))
    return out


def test_list_form_maps_document_system_fields_to_physical_bindings() -> None:
    model = build_list_form_model(
        form_name="doc_list",
        owner_title="Документ",
        attributes=default_attributes_for_object(obj_type="document"),
        commands=[],
    )

    root_children = list(dict(model.get("root") or {}).get("children") or [])
    assert root_children[0]["type"] == "CommandBar"
    bindings = [str(col.get("binding") or "") for col in _table_columns(model)]
    assert bindings[:3] == ["_number", "_date", "_posted"]


def test_object_form_maps_catalog_system_fields_to_physical_bindings() -> None:
    model = build_object_form_model(
        form_name="cat_obj",
        owner_title="Справочник",
        attributes=default_attributes_for_object(obj_type="catalog"),
        commands=[],
    )

    root_children = list(dict(model.get("root") or {}).get("children") or [])
    assert root_children[0]["type"] == "CommandBar"
    bindings = _text_bindings(model)
    assert "_code" in bindings
    assert "_description" in bindings
