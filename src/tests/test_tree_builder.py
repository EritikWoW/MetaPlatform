from dataclasses import dataclass
from typing import Any

from src.configurator.persistence.manifest_io import sys_object_folder_guid
from src.ui_qt.services.tree_builder import prepare_tree_objects
from src.ui_qt.i18n import t


@dataclass(frozen=True)
class _Node:
    guid: str
    kind: str
    type: Any
    name: str
    title: str
    parent_guid: str | None = None
    payload: Any = None


def test_prepare_tree_objects_keeps_report_forms_section() -> None:
    nodes = [
        _Node(guid="report-1", kind="object", type="report", name="SalesReport", title="Sales report"),
        _Node(guid="report-forms", kind="folder", type="report", name="forms", title="forms", parent_guid="report-1"),
        _Node(guid="report-form-1", kind="object", type="form", name="ReportForm", title="Report form", parent_guid="report-forms"),
    ]

    prepared = prepare_tree_objects(nodes)
    guids = {node.guid for node in prepared}

    assert "report-1" in guids
    assert "report-forms" in guids
    assert "report-form-1" in guids


def test_prepare_tree_objects_filters_by_title_and_keeps_ancestors() -> None:
    nodes = [
        _Node(guid="cfg", kind="root", type="configuration", name="Configuration", title="Configuration"),
        _Node(guid="docs", kind="group", type="documents", name="documents", title="Документи", parent_guid="cfg"),
        _Node(
            guid="target",
            kind="object",
            type="document",
            name="SaleDocument",
            title="Реалізація товарів і послуг",
            parent_guid="docs",
        ),
        _Node(
            guid="other",
            kind="object",
            type="document",
            name="PurchaseDocument",
            title="Надходження товарів",
            parent_guid="docs",
        ),
    ]

    prepared = prepare_tree_objects(nodes, search_text="реалізація")
    assert {node.guid for node in prepared} == {"cfg", "docs", "target"}


def test_prepare_tree_objects_normalizes_physical_object_folder_for_i18n() -> None:
    nodes = [
        _Node(guid="doc-1", kind="object", type="document", name="Sales", title="Sales"),
        _Node(
            guid="doc-forms",
            kind="folder",
            type="document",
            name="forms",
            title="forms",
            parent_guid="doc-1",
            payload={},
        ),
    ]

    prepared = prepare_tree_objects(nodes)
    forms = next(node for node in prepared if node.guid == "doc-forms")

    assert forms.title == t("tree.forms")
    assert forms.payload["system"] is True
    assert forms.payload["protected"] is True
    assert forms.payload["section"] == "forms"


def test_prepare_tree_objects_hides_descendants_of_hidden_section() -> None:
    nodes = [
        _Node(guid="pic-1", kind="object", type="common_picture", name="Logo", title="Logo"),
        _Node(guid="pic-forms", kind="folder", type="common_picture", name="forms", title="forms", parent_guid="pic-1"),
        _Node(guid="pic-form-1", kind="object", type="form", name="HiddenForm", title="Hidden form", parent_guid="pic-forms"),
    ]

    prepared = prepare_tree_objects(nodes)
    guids = {node.guid for node in prepared}

    assert "pic-1" in guids
    assert "pic-forms" not in guids
    assert "pic-form-1" not in guids


def test_prepare_tree_objects_injects_requisites_and_tabular_part_children() -> None:
    nodes = [
        _Node(
            guid="doc-1",
            kind="object",
            type="document",
            name="AdvanceReport",
            title="Advance report",
            payload={
                "requisites": [
                    {"name": "Organization", "title": {"uk": "Організація", "ru": "Организация"}, "type": "ref"},
                    {"name": "Comment", "title": {"uk": "Коментар"}, "type": "string"},
                ],
                "tabular_parts": [
                    {
                        "name": "ReceivedAdvances",
                        "title": {"uk": "ОтриманіАванси"},
                        "columns": [
                            {"name": "AdvanceDocument", "title": {"uk": "ДокументАванса"}, "type": "ref"},
                            {"name": "Amount", "title": {"uk": "Сума"}, "type": "number"},
                        ],
                    }
                ],
            },
        ),
    ]

    prepared = prepare_tree_objects(nodes)
    by_guid = {node.guid: node for node in prepared}

    assert by_guid["virtual:doc-1:attributes"].parent_guid == "doc-1"
    assert by_guid["virtual:doc-1:attributes:Organization"].parent_guid == "virtual:doc-1:attributes"
    assert by_guid["virtual:doc-1:attributes:Organization"].title == "Організація"

    assert by_guid["virtual:doc-1:tabular_parts"].parent_guid == "doc-1"
    assert by_guid["virtual:doc-1:tabular_parts:ReceivedAdvances"].parent_guid == "virtual:doc-1:tabular_parts"
    assert (
        by_guid["virtual:doc-1:tabular_parts:ReceivedAdvances:AdvanceDocument"].parent_guid
        == "virtual:doc-1:tabular_parts:ReceivedAdvances"
    )
    assert by_guid["virtual:doc-1:tabular_parts:ReceivedAdvances:AdvanceDocument"].title == "ДокументАванса"


def test_prepare_tree_objects_uses_attributes_payload_when_requisites_absent() -> None:
    nodes = [
        _Node(
            guid="cat-1",
            kind="object",
            type="catalog",
            name="Products",
            title="Products",
            payload={"attributes": [{"name": "Code", "title": {"uk": "Код"}, "type": "string"}]},
        ),
    ]

    prepared = prepare_tree_objects(nodes)
    by_guid = {node.guid: node for node in prepared}

    assert "virtual:cat-1:attributes" in by_guid
    assert "virtual:cat-1:attributes:Code" in by_guid
    assert by_guid["virtual:cat-1:attributes:Code"].title == "Код"


def test_prepare_tree_objects_injects_missing_system_folders() -> None:
    nodes = [
        _Node(
            guid="cat-1",
            kind="object",
            type="catalog",
            name="AdvanceReportAttachments",
            title="Advance report attachments",
        ),
    ]

    prepared = prepare_tree_objects(nodes)
    by_guid = {node.guid: node for node in prepared}

    forms_guid = sys_object_folder_guid(parent_guid="cat-1", section_key="forms")
    commands_guid = sys_object_folder_guid(parent_guid="cat-1", section_key="commands")
    layouts_guid = sys_object_folder_guid(parent_guid="cat-1", section_key="layouts")
    assert by_guid[forms_guid].kind == "folder"
    assert by_guid[forms_guid].parent_guid == "cat-1"
    assert by_guid[forms_guid].payload["virtual"] is True
    assert by_guid[forms_guid].payload["menu"] == "add_only"

    assert by_guid[commands_guid].kind == "folder"
    assert by_guid[commands_guid].parent_guid == "cat-1"

    assert by_guid[layouts_guid].kind == "folder"
    assert by_guid[layouts_guid].parent_guid == "cat-1"


def test_prepare_tree_objects_keeps_stable_section_order_for_catalog_tree() -> None:
    nodes = [
        _Node(
            guid="cat-1",
            kind="object",
            type="catalog",
            name="AdvanceReportAttachments",
            title="Advance report attachments",
            payload={
                "attributes": [{"name": "Code", "title": {"uk": "Код"}, "type": "string"}],
                "tabular_parts": [{"name": "Items", "title": {"uk": "Товари"}, "columns": []}],
            },
        ),
    ]

    prepared = prepare_tree_objects(nodes)
    children = [
        node.name
        for node in prepared
        if str(getattr(node, "parent_guid", "") or "") == "cat-1"
    ]

    assert children == ["forms", "layouts", "commands", "tabular_parts", "attributes"]


def test_prepare_tree_objects_hides_modules_section_for_object_tree() -> None:
    owner_guid = "doc-1"
    modules_guid = sys_object_folder_guid(parent_guid=owner_guid, section_key="modules")
    nodes = [
        _Node(
            guid=owner_guid,
            kind="object",
            type="document",
            name="AdvanceReport",
            title="Advance report",
        ),
        _Node(
            guid="module-node-1",
            kind="object",
            type="module",
            name="ObjectModule",
            title="Object module",
            parent_guid=modules_guid,
        ),
    ]

    prepared = prepare_tree_objects(nodes)
    by_guid = {node.guid: node for node in prepared}

    assert modules_guid not in by_guid
    assert "module-node-1" not in by_guid


def test_prepare_tree_objects_keeps_common_modules_group_visible() -> None:
    nodes = [
        _Node(guid="common-root", kind="group", type="common", name="common", title="General"),
        _Node(
            guid="common-modules-folder",
            kind="folder",
            type="common",
            name="common_modules",
            title="Common modules",
            parent_guid="common-root",
            payload={"system": True},
        ),
        _Node(
            guid="common-module-1",
            kind="object",
            type="common_module",
            name="CommonServer",
            title="CommonServer",
            parent_guid="common-modules-folder",
        ),
    ]

    prepared = prepare_tree_objects(nodes)
    by_guid = {node.guid: node for node in prepared}

    assert "common-modules-folder" in by_guid
    assert "common-module-1" in by_guid


def test_prepare_tree_objects_reuses_virtual_folder_guid_for_children() -> None:
    forms_guid = sys_object_folder_guid(parent_guid="cat-1", section_key="forms")
    nodes = [
        _Node(
            guid="cat-1",
            kind="object",
            type="catalog",
            name="AdvanceReportAttachments",
            title="Advance report attachments",
        ),
        _Node(
            guid="form-1",
            kind="object",
            type="form",
            name="ObjectForm",
            title="Object form",
            parent_guid=forms_guid,
        ),
    ]

    prepared = prepare_tree_objects(nodes)
    by_guid = {node.guid: node for node in prepared}

    assert forms_guid in by_guid
    assert by_guid[forms_guid].kind == "folder"
    assert by_guid["form-1"].parent_guid == forms_guid


def test_prepare_tree_objects_keeps_expected_sections_for_business_object_tree() -> None:
    owner_guid = "doc-1"
    forms_guid = sys_object_folder_guid(parent_guid=owner_guid, section_key="forms")
    commands_guid = sys_object_folder_guid(parent_guid=owner_guid, section_key="commands")
    layouts_guid = sys_object_folder_guid(parent_guid=owner_guid, section_key="layouts")
    modules_guid = sys_object_folder_guid(parent_guid=owner_guid, section_key="modules")
    nodes = [
        _Node(
            guid=owner_guid,
            kind="object",
            type="document",
            name="AdvanceReport",
            title="Advance report",
            payload={
                "requisites": [{"name": "Organization", "title": {"uk": "Організація"}, "type": "ref"}],
                "tabular_parts": [{"name": "ReceivedAdvances", "title": {"uk": "ОтриманіАванси"}, "columns": []}],
            },
        ),
        _Node(
            guid="form-1",
            kind="object",
            type="form",
            name="ObjectForm",
            title="Object form",
            parent_guid=forms_guid,
        ),
        _Node(
            guid="command-1",
            kind="object",
            type="command",
            name="Post",
            title="Post",
            parent_guid=commands_guid,
        ),
        _Node(
            guid="layout-1",
            kind="object",
            type="layout",
            name="PrintForm",
            title="Print form",
            parent_guid=layouts_guid,
        ),
        _Node(
            guid="module-node-1",
            kind="object",
            type="module",
            name="ObjectModule",
            title="Object module",
            parent_guid=modules_guid,
        ),
    ]

    prepared = prepare_tree_objects(nodes)
    by_guid = {node.guid: node for node in prepared}

    assert forms_guid in by_guid
    assert commands_guid in by_guid
    assert layouts_guid in by_guid
    assert "form-1" in by_guid
    assert "command-1" in by_guid
    assert "layout-1" in by_guid

    assert modules_guid not in by_guid
    assert "module-node-1" not in by_guid

    assert "virtual:doc-1:attributes" in by_guid
    assert "virtual:doc-1:attributes:Organization" in by_guid
    assert "virtual:doc-1:tabular_parts" in by_guid
    assert "virtual:doc-1:tabular_parts:ReceivedAdvances" in by_guid


def test_prepare_tree_objects_projects_numerators_and_sequences_under_documents_group() -> None:
    nodes = [
        _Node(guid="root-1", kind="root", type="configuration", name="Configuration", title="Configuration"),
        _Node(guid="doc-group", kind="group", type="document", name="document", title="Документи", parent_guid="root-1"),
        _Node(
            guid="old-num-folder",
            kind="folder",
            type="document_numerators",
            name="document_numerators",
            title="Нумератори документів",
            parent_guid="root-1",
        ),
        _Node(
            guid="old-seq-folder",
            kind="folder",
            type="sequences",
            name="sequences",
            title="Послідовності",
            parent_guid="root-1",
        ),
        _Node(
            guid="num-1",
            kind="object",
            type="document_numerator",
            name="Sales",
            title="Sales",
            parent_guid="old-num-folder",
        ),
        _Node(
            guid="seq-1",
            kind="object",
            type="sequence",
            name="Posting",
            title="Posting",
            parent_guid="old-seq-folder",
        ),
    ]

    prepared = prepare_tree_objects(nodes)
    by_guid = {node.guid: node for node in prepared}

    numerators_guid = "virtual:doc-group:document_group_folder:document_numerators"
    sequences_guid = "virtual:doc-group:document_group_folder:sequences"

    assert numerators_guid in by_guid
    assert sequences_guid in by_guid
    assert by_guid[numerators_guid].parent_guid == "doc-group"
    assert by_guid[sequences_guid].parent_guid == "doc-group"
    assert by_guid[numerators_guid].title == t("tree.document_numerators")
    assert by_guid["seq-1"].parent_guid == sequences_guid
    assert by_guid["num-1"].parent_guid == numerators_guid

    assert "old-num-folder" not in by_guid
    assert "old-seq-folder" not in by_guid


def test_prepare_tree_objects_hides_subsystem_forms_and_commands_sections() -> None:
    nodes = [
        _Node(guid="sub-1", kind="object", type="subsystem", name="Administration", title="Administration"),
        _Node(
            guid="sub-forms",
            kind="folder",
            type="subsystem",
            name="forms",
            title="Forms",
            parent_guid="sub-1",
        ),
        _Node(
            guid="sub-commands",
            kind="folder",
            type="subsystem",
            name="commands",
            title="Commands",
            parent_guid="sub-1",
        ),
        _Node(
            guid="sub-form-1",
            kind="object",
            type="form",
            name="SubsystemForm",
            title="Subsystem form",
            parent_guid="sub-forms",
        ),
        _Node(
            guid="sub-command-1",
            kind="object",
            type="command",
            name="SubsystemCommand",
            title="Subsystem command",
            parent_guid="sub-commands",
        ),
    ]

    prepared = prepare_tree_objects(nodes)
    by_guid = {node.guid: node for node in prepared}

    assert "sub-1" in by_guid
    assert "sub-forms" not in by_guid
    assert "sub-commands" not in by_guid
    assert "sub-form-1" not in by_guid
    assert "sub-command-1" not in by_guid


def test_prepare_tree_objects_preserves_subsystem_hierarchy() -> None:
    common_guid = "common-root"
    subsystems_guid = sys_object_folder_guid(parent_guid=common_guid, section_key="subsystems")
    nodes = [
        _Node(guid=common_guid, kind="group", type="common", name="common", title="Загальні"),
        _Node(
            guid=subsystems_guid,
            kind="folder",
            type="subsystem",
            name="subsystems",
            title="Підсистеми",
            parent_guid=common_guid,
            payload={"system": True},
        ),
        _Node(
            guid="sub-1",
            kind="object",
            type="subsystem",
            name="Administration",
            title="Адміністрування",
            parent_guid=subsystems_guid,
            payload={"child_subsystems": ["Nested"]},
        ),
        _Node(
            guid="sub-2",
            kind="object",
            type="subsystem",
            name="Nested",
            title="Вкладена підсистема",
            parent_guid="sub-1",
        ),
    ]

    prepared = prepare_tree_objects(nodes)
    by_guid = {node.guid: node for node in prepared}

    assert by_guid["sub-1"].parent_guid == subsystems_guid
    assert by_guid["sub-2"].parent_guid == "sub-1"
    assert by_guid["sub-1"].payload["child_subsystems"] == ["Nested"]


def test_subsystem_filter_keeps_only_objects_in_given_subsystem() -> None:
    sub_guid = "sub-a"
    nodes = [
        _Node(guid="cat-1", kind="object", type="catalog", name="Products", title="Products",
              payload={"subsystems": [sub_guid, "sub-b"]}),
        _Node(guid="cat-2", kind="object", type="catalog", name="Partners", title="Partners",
              payload={"subsystems": ["sub-b"]}),
        _Node(guid="doc-1", kind="object", type="document", name="Invoice", title="Invoice",
              payload={"subsystems": [sub_guid]}),
        _Node(guid="doc-2", kind="object", type="document", name="Order", title="Order",
              payload={"subsystems": []}),
    ]

    prepared = prepare_tree_objects(nodes, subsystem_filter_guid=sub_guid)
    guids = {node.guid for node in prepared}

    assert "cat-1" in guids
    assert "doc-1" in guids
    assert "cat-2" not in guids
    assert "doc-2" not in guids


def test_subsystem_filter_keeps_system_ancestors() -> None:
    sub_guid = "sub-a"
    catalogs_group_guid = "grp-catalogs"
    nodes = [
        _Node(guid=catalogs_group_guid, kind="group", type="catalog", name="catalogs", title="Catalogs",
              payload={"system": True}),
        _Node(guid="cat-1", kind="object", type="catalog", name="Products", title="Products",
              parent_guid=catalogs_group_guid, payload={"subsystems": [sub_guid]}),
        _Node(guid="cat-2", kind="object", type="catalog", name="Partners", title="Partners",
              parent_guid=catalogs_group_guid, payload={"subsystems": ["sub-b"]}),
    ]

    prepared = prepare_tree_objects(nodes, subsystem_filter_guid=sub_guid)
    guids = {node.guid for node in prepared}

    assert catalogs_group_guid in guids
    assert "cat-1" in guids
    assert "cat-2" not in guids


def test_subsystem_filter_empty_guid_returns_all_objects() -> None:
    nodes = [
        _Node(guid="cat-1", kind="object", type="catalog", name="Products", title="Products",
              payload={"subsystems": ["sub-a"]}),
        _Node(guid="cat-2", kind="object", type="catalog", name="Partners", title="Partners",
              payload={"subsystems": []}),
    ]

    prepared_all = prepare_tree_objects(nodes, subsystem_filter_guid="")
    guids = {node.guid for node in prepared_all}

    assert "cat-1" in guids
    assert "cat-2" in guids
