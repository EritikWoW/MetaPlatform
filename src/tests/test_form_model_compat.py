from src.configurator.domain.form_model import (
    FormModel,
    form_node_is_visible,
    normalize_form_open_mode,
    normalize_form_window_lock_mode,
)


def test_form_window_modes_normalize_platform_and_onec_values() -> None:
    assert normalize_form_open_mode(None) == "auto"
    assert normalize_form_open_mode("Client_Workspace") == "workspace"
    assert normalize_form_open_mode("SeparateWindow") == "window"
    assert normalize_form_window_lock_mode("DontUse") == "none"
    assert normalize_form_window_lock_mode("LockOwnerWindow") == "owner"
    assert normalize_form_window_lock_mode("LockWholeInterface") == "interface"


def test_form_model_normalizes_and_persists_client_visibility() -> None:
    raw = {
        "schema_version": 1,
        "id": "visible-form",
        "root": {
            "id": "root",
            "type": "Container",
            "props": {"layout": "vertical"},
            "children": [
                {
                    "id": "hidden-field",
                    "type": "TextBox",
                    "props": {"user_visible": "false"},
                    "children": [],
                }
            ],
        },
    }

    model = FormModel.from_dict(raw)
    field = model.root.children[0]

    assert form_node_is_visible(field) is False
    assert field.props["visible"] is False
    assert "user_visible" not in field.props
    assert model.to_dict()["root"]["children"][0]["props"]["visible"] is False


def test_form_model_normalizes_legacy_pages_container_to_tabs() -> None:
    raw = {
        "schema_version": 1,
        "id": "doc-form",
        "name": "FormaDokumenta",
        "title": "ФормаДокумента",
        "root": {
            "id": "root",
            "type": "Container",
            "props": {"layout": "vertical"},
            "children": [
                {
                    "id": "pages",
                    "type": "Container",
                    "name": "HruppaStranytsy",
                    "title": "Сторінки",
                    "props": {"layout": "vertical"},
                    "children": [
                        {
                            "id": "page-1",
                            "type": "Container",
                            "name": "MainPage",
                            "title": "Основна",
                            "props": {"layout": "vertical"},
                            "children": [],
                        },
                        {
                            "id": "page-2",
                            "type": "Container",
                            "name": "ExtraPage",
                            "title": "Додатково",
                            "props": {"layout": "vertical"},
                            "children": [],
                        },
                    ],
                }
            ],
        },
    }

    model = FormModel.from_dict(raw)

    pages = model.root.children[0]
    assert pages.type == "Tabs"
    assert pages.props["pages_representation"] == "TabsOnTop"
    assert [child.title for child in pages.children] == ["Основна", "Додатково"]


def test_form_model_rebinds_legacy_page_tables_from_items_to_table_name() -> None:
    raw = {
        "schema_version": 1,
        "id": "doc-form",
        "name": "FormaDokumenta",
        "title": "ФормаДокумента",
        "root": {
            "id": "root",
            "type": "Container",
            "props": {"layout": "vertical"},
            "children": [
                {
                    "id": "pages",
                    "type": "Container",
                    "name": "Tabs",
                    "title": "Сторінки",
                    "props": {"layout": "vertical"},
                    "children": [
                        {
                            "id": "page-1",
                            "type": "Container",
                            "name": "LinesPage",
                            "title": "Рядки",
                            "props": {"layout": "vertical"},
                            "children": [
                                {
                                    "id": "table-1",
                                    "type": "Table",
                                    "name": "Tovary",
                                    "title": "Товари",
                                    "binding": "items",
                                    "props": {"columns": []},
                                    "children": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    }

    model = FormModel.from_dict(raw)

    pages = model.root.children[0]
    table = pages.children[0].children[0]
    assert pages.type == "Tabs"
    assert table.type == "Table"
    assert table.binding == "Tovary"


def test_form_model_normalizes_legacy_command_bar_container() -> None:
    raw = {
        "schema_version": 1,
        "id": "doc-form",
        "name": "FormaDokumenta",
        "title": "ФормаДокумента",
        "root": {
            "id": "root",
            "type": "Container",
            "props": {"layout": "vertical"},
            "children": [
                {
                    "id": "cmd-1",
                    "type": "Container",
                    "name": "FormaKomandnayaPanel",
                    "title": "ФормаКоманднаяПанель",
                    "props": {"layout": "horizontal"},
                    "children": [
                        {
                            "id": "btn-1",
                            "type": "Button",
                            "name": "Save",
                            "title": "Зберегти",
                            "props": {"command": "save"},
                            "children": [],
                        }
                    ],
                }
            ],
        },
    }

    model = FormModel.from_dict(raw)

    cmd = model.root.children[0]
    assert cmd.type == "CommandBar"
    assert cmd.children == []
    assert cmd.props["buttons"][0]["title"] == "Зберегти"
    assert cmd.props["buttons"][0]["command"] == "save"


def test_form_model_preserves_command_bar_children_for_editing() -> None:
    raw = {
        "schema_version": 1,
        "id": "doc-form",
        "name": "FormaDokumenta",
        "title": "ФормаДокумента",
        "root": {
            "id": "root",
            "type": "Container",
            "props": {"layout": "vertical"},
            "children": [
                {
                    "id": "cmd-1",
                    "type": "CommandBar",
                    "name": "command_bar",
                    "props": {
                        "buttons": [
                            {"title": "Зберегти", "command": "save"},
                            {"title": "Закрити", "command": "close"},
                        ],
                        "show_all_actions": True,
                    },
                    "children": [
                        {
                            "id": "btn-1",
                            "type": "Button",
                            "name": "Save",
                            "title": "Зберегти",
                            "props": {"command": "save"},
                            "children": [],
                        },
                        {
                            "id": "btn-2",
                            "type": "Button",
                            "name": "Close",
                            "title": "Закрити",
                            "props": {"command": "close"},
                            "children": [],
                        },
                    ],
                },
            ],
        },
    }

    model = FormModel.from_dict(raw)

    cmd = model.root.children[0]
    assert cmd.type == "CommandBar"
    assert [child.type for child in cmd.children] == ["Button", "Button"]
    assert cmd.to_dict()["props"]["buttons"][0]["command"] == "save"


def test_form_model_preserves_hidden_command_button_visibility() -> None:
    raw = {
        "schema_version": 1,
        "id": "command-form",
        "root": {
            "id": "root",
            "type": "Container",
            "props": {"layout": "vertical"},
            "children": [
                {
                    "id": "cmd-1",
                    "type": "CommandBar",
                    "props": {},
                    "children": [
                        {
                            "id": "btn-hidden",
                            "type": "Button",
                            "title": "Hidden",
                            "props": {"command": "hidden", "visible": False},
                            "children": [],
                        }
                    ],
                }
            ],
        },
    }

    model = FormModel.from_dict(raw)

    button = model.to_dict()["root"]["children"][0]["props"]["buttons"][0]
    assert button["visible"] is False


def test_form_model_does_not_reclassify_generic_horizontal_button_group() -> None:
    raw = {
        "schema_version": 1,
        "id": "form",
        "root": {
            "id": "root",
            "type": "Container",
            "props": {"layout": "vertical"},
            "children": [
                {
                    "id": "choices",
                    "type": "Container",
                    "name": "Choices",
                    "props": {"layout": "horizontal"},
                    "children": [
                        {"id": "yes", "type": "Button", "title": "Yes", "children": []},
                        {"id": "no", "type": "Button", "title": "No", "children": []},
                    ],
                }
            ],
        },
    }

    model = FormModel.from_dict(raw)

    assert model.root.children[0].type == "Container"


def test_form_model_normalizes_legacy_table_panel_wrapper() -> None:
    raw = {
        "schema_version": 1,
        "id": "doc-form",
        "name": "FormaDokumenta",
        "title": "ФормаДокумента",
        "root": {
            "id": "root",
            "type": "Container",
            "props": {"layout": "vertical"},
            "children": [
                {
                    "id": "wrap-1",
                    "type": "Container",
                    "name": "PoluchennyeAvansy",
                    "title": "ПолученныеАвансы",
                    "props": {"layout": "vertical"},
                    "children": [
                        {
                            "id": "bar-1",
                            "type": "Container",
                            "name": "PoluchennyeAvansyKomandnayaPanel",
                            "title": "ПолученныеАвансыКоманднаяПанель",
                            "props": {"layout": "horizontal"},
                            "children": [
                                {
                                    "id": "btn-1",
                                    "type": "Button",
                                    "name": "ZapolnytPoluchennyeAvansy",
                                    "title": "Заповнити за залишками",
                                    "props": {},
                                    "children": [],
                                }
                            ],
                        },
                        {
                            "id": "table-1",
                            "type": "Table",
                            "name": "PoluchennyeAvansy",
                            "title": "ПолученныеАвансы",
                            "binding": "PoluchennyeAvansy",
                            "props": {
                                "columns": [
                                    {"name": "LineNo", "title": "N"},
                                    {"name": "Doc", "title": "Документ"},
                                ]
                            },
                            "children": [],
                        },
                    ],
                }
            ],
        },
    }

    model = FormModel.from_dict(raw)

    panel = model.root.children[0]
    assert panel.type == "TablePanel"
    assert panel.binding == "PoluchennyeAvansy"
    assert panel.props["fill_by_stock"] == "Заповнити за залишками"
    assert panel.props["fill_by_stock_command"] == "ZapolnytPoluchennyeAvansy"
    assert panel.props["fill_by_stock_designer_name"] == "ZapolnytPoluchennyeAvansy"
    assert panel.props["command_bar_designer_name"] == "PoluchennyeAvansyKomandnayaPanel"
    assert panel.props["can_add"] is False
    assert panel.props["can_delete"] is False
    assert len(panel.props["columns"]) == 2
