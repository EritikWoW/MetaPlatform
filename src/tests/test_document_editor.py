from PySide6.QtWidgets import QApplication, QListWidget, QTreeWidget
from PySide6.QtCore import Qt

from src.configurator.persistence.manifest_io import sys_object_folder_guid
from src.configurator.manifest_schema import ManifestObject
from src.ui_qt.i18n import get_lang, set_lang
from src.ui_qt.widgets.document_editor import DocumentPayload
from src.ui_qt.widgets.document_editor import DocumentEditorWidget


def test_document_payload_from_imported_payload_uses_requisites_and_imported_fields() -> None:
    payload = {
        "title": {"uk": "Авансовий звіт", "ru": "Авансовый отчет"},
        "comment": "",
        "hint": {"uk": "Підказка"},
        "number_length": 11,
        "number_periodicity": "year",
        "autonumbering": True,
        "posting": "allow",
        "input_by_string": "number_date",
        "default_object_form": "Document.AdvanceReport.Form.ObjectForm",
        "default_list_form": "Document.AdvanceReport.Form.ListForm",
        "list_presentation": {"uk": "Авансові звіти"},
        "explanation": {"uk": "Пояснення"},
        "requisites": [{"name": "Организация", "type": "ref"}],
        "tabular_parts": [{"name": "ПолученныеАвансы", "columns": [{"name": "Сумма", "type": "number"}]}],
    }

    model = DocumentPayload.from_payload(payload)

    assert model.synonym == "Авансовий звіт"
    assert model.hint == "Підказка"
    assert model.number_length == 11
    assert model.number_periodicity == "year"
    assert model.autonumbering is True
    assert model.posting == "allow"
    assert model.input_by_string == "number_date"
    assert model.default_object_form.endswith("ObjectForm")
    assert model.default_list_form.endswith("ListForm")
    assert model.list_presentation == "Авансові звіти"
    assert model.explanation == "Пояснення"
    assert model.requisites[0]["name"] == "Организация"
    assert model.tabular_parts[0]["name"] == "ПолученныеАвансы"


def test_document_editor_uses_single_data_page_and_properties_follow_selection() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "title": {"uk": "Авансовий звіт"},
        "requisites": [
            {
                "name": "Organization",
                "title": {"uk": "Організація"},
                "type": "ref",
                "ref_name": "Catalog.Organizations",
                "required": True,
            }
        ],
        "tabular_parts": [
            {
                "name": "Items",
                "title": {"uk": "Товари"},
                "columns": [
                    {
                        "name": "Amount",
                        "title": {"uk": "Сума"},
                        "type": "number",
                    }
                ],
            }
        ],
    }

    widget = DocumentEditorWidget("АвансовийЗвіт", payload=payload)

    section_keys = [
        str(widget._shell._sections.item(i).data(Qt.ItemDataRole.UserRole) or "")
        for i in range(widget._shell._sections.count())
    ]
    assert "data" in section_keys
    assert "attributes" not in section_keys
    assert "tabular_parts" not in section_keys

    req_item = widget.tree_requisites.topLevelItem(0)
    assert req_item is not None
    widget.tree_requisites.setCurrentItem(req_item)
    app.processEvents()

    props = widget.properties_widget()
    assert props is not None
    assert props.ed_name.text() == "Organization"
    assert props.cb_ref_name.currentText() == "Catalog.Organizations"
    assert props.chk_required.isChecked() is True

    props.cb_ref_name.set_targets(
        [
            ("Організації", "Catalog.Organizations"),
            ("Компанії", "Catalog.Companies"),
        ]
    )
    props.cb_ref_name.set_value("Catalog.Companies", emit_signal=True)
    app.processEvents()

    assert widget._payload_raw["requisites"][0]["ref_name"] == "Catalog.Companies"
    assert widget._shell._pending_patch["requisites"][0]["ref_name"] == "Catalog.Companies"

    tp_item = widget.tree_tabular_parts.topLevelItem(0)
    assert tp_item is not None
    col_item = tp_item.child(0)
    assert col_item is not None
    widget.tree_tabular_parts.setCurrentItem(col_item)
    app.processEvents()

    assert props.ed_name.text() == "Amount"
    assert props.cb_type.currentData() == "number"


def test_document_editor_schema_properties_show_type_specific_qualifiers() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "title": {"uk": "Тест"},
        "requisites": [
            {
                "name": "Code",
                "title": {"uk": "Код"},
                "type": "string",
                "string_qualifiers": {"length": 9},
            },
            {
                "name": "Amount",
                "title": {"uk": "Сума"},
                "type": "number",
                "number_qualifiers": {"digits": 15, "fraction_digits": 2},
            },
        ],
    }

    widget = DocumentEditorWidget("Тест", payload=payload)
    props = widget.properties_widget()
    assert props is not None

    req_item = widget.tree_requisites.topLevelItem(0)
    assert req_item is not None
    widget.tree_requisites.setCurrentItem(req_item)
    app.processEvents()

    assert props.cb_type.currentData() == "string"
    assert props.sp_string_length.value() == 9
    assert props.sp_string_length.isHidden() is False
    assert props.sp_number_digits.isHidden() is True

    props.sp_string_length.setValue(12)
    app.processEvents()
    assert widget._payload_raw["requisites"][0]["string_qualifiers"]["length"] == 12

    req_item_number = widget.tree_requisites.topLevelItem(1)
    assert req_item_number is not None
    widget.tree_requisites.setCurrentItem(req_item_number)
    app.processEvents()

    assert props.cb_type.currentData() == "number"
    assert props.sp_number_digits.value() == 15
    assert props.sp_number_fraction_digits.value() == 2
    assert props.sp_number_digits.isHidden() is False
    assert props.sp_number_fraction_digits.isHidden() is False

    props.sp_number_digits.setValue(18)
    props.sp_number_fraction_digits.setValue(4)
    app.processEvents()
    assert widget._payload_raw["requisites"][1]["number_qualifiers"]["digits"] == 18
    assert widget._payload_raw["requisites"][1]["number_qualifiers"]["fraction_digits"] == 4


def test_document_editor_schema_properties_store_synonym_as_localized_map() -> None:
    app = QApplication.instance() or QApplication([])
    prev_lang = get_lang()
    try:
        set_lang("uk")
        payload = {
            "title": {"uk": "Тест"},
            "requisites": [
                {
                    "name": "Organization",
                    "title": {"uk": "Організація", "en": "Organization"},
                    "type": "ref",
                }
            ],
        }

        widget = DocumentEditorWidget("Тест", payload=payload)
        props = widget.properties_widget()
        assert props is not None

        req_item = widget.tree_requisites.topLevelItem(0)
        assert req_item is not None
        widget.tree_requisites.setCurrentItem(req_item)
        app.processEvents()

        assert props.ed_synonym.currentText() == "Організація"

        props.ed_synonym.set_value({"uk": "Організація", "en": "Organization"}, emit_signal=True)
        app.processEvents()

        assert widget._payload_raw["requisites"][0]["title"] == {
            "uk": "Організація",
            "en": "Organization",
        }
    finally:
        set_lang(prev_lang)


def test_document_editor_schema_properties_support_compound_reference_targets() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "title": {"uk": "Тест"},
        "requisites": [
            {
                "name": "BaseDocument",
                "title": {"uk": "Документ-основа"},
                "type": "ref",
                "ref_name": "Document.AdvanceReport",
            }
        ],
    }

    widget = DocumentEditorWidget("Тест", payload=payload)
    props = widget.properties_widget()
    assert props is not None
    props.set_reference_targets(
        [
            ("Авансовий звіт", "Document.AdvanceReport"),
            ("Видатковий касовий ордер", "Document.CashExpenseOrder"),
            ("Списання безготівкових коштів", "Document.WriteOffCashless"),
        ]
    )

    req_item = widget.tree_requisites.topLevelItem(0)
    assert req_item is not None
    widget.tree_requisites.setCurrentItem(req_item)
    app.processEvents()

    assert "compound_type" not in props._rows

    props.cb_ref_name.set_multi_select(True, emit_signal=True)
    props.cb_ref_name.set_values(
        [
            "Document.AdvanceReport",
            "Document.CashExpenseOrder",
            "Document.WriteOffCashless",
        ],
        emit_signal=True,
    )
    app.processEvents()

    req = widget._payload_raw["requisites"][0]
    assert req["compound_type"] is True
    assert req["ref_name"] == "Document.AdvanceReport"
    assert req["ref_targets"] == [
        "Document.AdvanceReport",
        "Document.CashExpenseOrder",
        "Document.WriteOffCashless",
    ]

    props.cb_ref_name.set_multi_select(False, emit_signal=True)
    app.processEvents()

    req = widget._payload_raw["requisites"][0]
    assert "compound_type" not in req
    assert "ref_targets" not in req
    assert req["ref_name"] == "Document.AdvanceReport"


def test_document_editor_data_page_shows_icons_and_supports_add_delete_actions() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "title": {"uk": "Тест"},
        "requisites": [{"name": "Organization", "title": {"uk": "Організація"}, "type": "ref"}],
        "tabular_parts": [
            {
                "name": "Items",
                "title": {"uk": "Товари"},
                "columns": [{"name": "Amount", "title": {"uk": "Сума"}, "type": "number"}],
            }
        ],
    }

    widget = DocumentEditorWidget("Тест", payload=payload)
    app.processEvents()

    req_item = widget.tree_requisites.topLevelItem(0)
    tp_item = widget.tree_tabular_parts.topLevelItem(0)
    col_item = tp_item.child(0) if tp_item is not None else None
    assert req_item is not None and not req_item.icon(0).isNull()
    assert tp_item is not None and not tp_item.icon(0).isNull()
    assert col_item is not None and not col_item.icon(0).isNull()

    widget.btn_req_add.click()
    app.processEvents()
    assert len(widget._payload_raw["requisites"]) == 2
    assert widget.tree_requisites.currentItem() is not None

    widget.btn_req_delete.click()
    app.processEvents()
    assert len(widget._payload_raw["requisites"]) == 1

    widget.btn_tp_add.click()
    app.processEvents()
    assert len(widget._payload_raw["tabular_parts"]) == 2

    widget.tree_tabular_parts.setCurrentItem(widget.tree_tabular_parts.topLevelItem(0))
    app.processEvents()
    widget.btn_tp_add_column.click()
    app.processEvents()
    assert len(widget._payload_raw["tabular_parts"][0]["columns"]) == 2

    widget.tree_tabular_parts.setCurrentItem(widget.tree_tabular_parts.topLevelItem(0).child(1))
    app.processEvents()
    widget.btn_tp_delete.click()
    app.processEvents()
    assert len(widget._payload_raw["tabular_parts"][0]["columns"]) == 1


def test_document_editor_reference_targets_include_only_metadata_objects() -> None:
    class VmStub:
        def list_objects(self):
            return [
                ManifestObject(
                    guid="catalog-group",
                    parent_guid="root",
                    type="catalog",
                    name="catalog",
                    title="Справочники",
                    kind="group",
                    payload={},
                ),
                ManifestObject(
                    guid="catalog-owner",
                    parent_guid="catalog-group",
                    type="catalog",
                    name="Organizations",
                    title="Організації",
                    kind="object",
                    payload={},
                ),
                ManifestObject(
                    guid="catalog-commands",
                    parent_guid="catalog-owner",
                    type="catalog",
                    name="commands",
                    title="commands",
                    kind="folder",
                    payload={"system": True},
                ),
                ManifestObject(
                    guid="catalog-forms",
                    parent_guid="catalog-owner",
                    type="catalog",
                    name="forms",
                    title="forms",
                    kind="folder",
                    payload={"system": True},
                ),
                ManifestObject(
                    guid="document-owner",
                    parent_guid="document-group",
                    type="document",
                    name="AdvanceReport",
                    title="Авансовий звіт",
                    kind="object",
                    payload={},
                ),
            ]

        def list_subsystems(self):
            return []

    widget = DocumentEditorWidget("Тест", payload={"requisites": []}, vm=VmStub())

    targets = widget._collect_reference_targets()

    assert ("Організації (Organizations)", "Catalog.Organizations") in targets
    assert ("Авансовий звіт (AdvanceReport)", "Document.AdvanceReport") in targets
    assert all(value != "Catalog.commands" for _, value in targets)
    assert all(value != "Catalog.forms" for _, value in targets)


def test_document_editor_load_to_ui_refreshes_forms_and_layouts_lists() -> None:
    app = QApplication.instance() or QApplication([])

    class VmStub:
        def __init__(self, objs):
            self._objs = list(objs)

        def list_objects(self):
            return list(self._objs)

        def list_subsystems(self):
            return []

        def create_object_quick(self, *args, **kwargs):
            return ""

        def request_open_new(self, *args, **kwargs):
            return None

        def delete_object(self, *args, **kwargs):
            return False

    owner_guid = "doc-guid"
    forms_guid = "forms-guid"
    layouts_guid = "layouts-guid"
    objs = [
        ManifestObject(guid=owner_guid, parent_guid="", type="document", name="AdvanceReport", title="АвансовыйОтчет", kind="object", payload={}),
        ManifestObject(guid=forms_guid, parent_guid=owner_guid, type="document", name="forms", title="forms", kind="folder", payload={"system": True}),
        ManifestObject(guid=layouts_guid, parent_guid=owner_guid, type="document", name="layouts", title="layouts", kind="folder", payload={"system": True}),
        ManifestObject(guid="form-guid", parent_guid=forms_guid, type="form", name="ObjectForm", title="ФормаДокумента", kind="object", payload={}),
        ManifestObject(guid="layout-guid", parent_guid=layouts_guid, type="layout", name="Layout1", title="Макет1", kind="object", payload={}),
    ]
    widget = DocumentEditorWidget(
        "АвансовыйОтчет",
        payload={
            "name": "AdvanceReport",
            "default_object_form": "Document.AdvanceReport.Form.ObjectForm",
            "default_list_form": "Document.AdvanceReport.Form.ListForm",
        },
        vm=VmStub(objs),
        obj_guid=owner_guid,
        available_subsystems=[],
    )

    widget.lst_forms.clear()
    widget.lst_layouts.clear()

    widget._load_to_ui()
    app.processEvents()

    assert widget.lst_forms.count() == 1
    assert widget.lst_layouts.count() == 1
    assert widget.lst_forms.item(0).text() == "ObjectForm"
    assert widget.lst_layouts.item(0).text() == "Layout1"
    assert widget.ed_default_object_form.currentText() == "ObjectForm"
    assert widget.ed_default_object_form.currentData() == "Document.AdvanceReport.Form.ObjectForm"
    assert widget.ed_default_list_form.currentData() == "Document.AdvanceReport.Form.ListForm"


def test_document_editor_default_form_selectors_use_available_forms_and_preserve_missing_value() -> None:
    app = QApplication.instance() or QApplication([])

    class VmStub:
        def __init__(self, objs):
            self._objs = list(objs)

        def list_objects(self):
            return list(self._objs)

        def list_subsystems(self):
            return []

        def create_object_quick(self, *args, **kwargs):
            return ""

        def request_open_new(self, *args, **kwargs):
            return None

        def delete_object(self, *args, **kwargs):
            return False

    owner_guid = "doc-guid"
    forms_guid = "forms-guid"
    objs = [
        ManifestObject(guid=owner_guid, parent_guid="", type="document", name="AdvanceReport", title="АвансовыйОтчет", kind="object", payload={}),
        ManifestObject(guid=forms_guid, parent_guid=owner_guid, type="document", name="forms", title="forms", kind="folder", payload={"system": True}),
        ManifestObject(guid="form-guid-1", parent_guid=forms_guid, type="form", name="ObjectForm", title="ФормаДокумента", kind="object", payload={}),
        ManifestObject(guid="form-guid-2", parent_guid=forms_guid, type="form", name="ListForm", title="ФормаСписка", kind="object", payload={}),
    ]
    widget = DocumentEditorWidget(
        "АвансовыйОтчет",
        payload={
            "name": "AdvanceReport",
            "default_object_form": "Document.AdvanceReport.Form.ObjectForm",
            "default_list_form": "Document.AdvanceReport.Form.ListForm",
            "default_choice_form": "Document.AdvanceReport.Form.MissingChoiceForm",
        },
        vm=VmStub(objs),
        obj_guid=owner_guid,
        available_subsystems=[],
    )
    app.processEvents()

    object_items = [widget.ed_default_object_form.itemText(i) for i in range(widget.ed_default_object_form.count())]
    object_values = [widget.ed_default_object_form.itemData(i) for i in range(widget.ed_default_object_form.count())]
    assert "ObjectForm" in object_items
    assert "Document.AdvanceReport.Form.ObjectForm" in object_values
    assert widget.ed_default_object_form.currentText() == "ObjectForm"

    list_items = [widget.ed_default_list_form.itemText(i) for i in range(widget.ed_default_list_form.count())]
    list_values = [widget.ed_default_list_form.itemData(i) for i in range(widget.ed_default_list_form.count())]
    assert "ListForm" in list_items
    assert "Document.AdvanceReport.Form.ListForm" in list_values
    assert widget.ed_default_list_form.currentText() == "ListForm"

    choice_values = [widget.ed_default_choice_form.itemData(i) for i in range(widget.ed_default_choice_form.count())]
    assert "Document.AdvanceReport.Form.MissingChoiceForm" in choice_values
    assert widget.ed_default_choice_form.currentData() == "Document.AdvanceReport.Form.MissingChoiceForm"


def test_document_editor_uses_virtual_folder_guid_when_physical_folder_is_absent() -> None:
    app = QApplication.instance() or QApplication([])

    class VmStub:
        def __init__(self, objs):
            self._objs = list(objs)

        def list_objects(self):
            return list(self._objs)

        def list_subsystems(self):
            return []

        def create_object_quick(self, *args, **kwargs):
            return ""

        def request_open_new(self, *args, **kwargs):
            return None

        def delete_object(self, *args, **kwargs):
            return False

    owner_guid = "doc-guid"
    virtual_forms_guid = sys_object_folder_guid(parent_guid=owner_guid, section_key="forms")
    virtual_layouts_guid = sys_object_folder_guid(parent_guid=owner_guid, section_key="layouts")
    objs = [
        ManifestObject(guid=owner_guid, parent_guid="", type="document", name="AdvanceReport", title="АвансовыйОтчет", kind="object", payload={}),
        ManifestObject(guid="form-guid", parent_guid=virtual_forms_guid, type="form", name="ObjectForm", title="ФормаДокумента", kind="object", payload={}),
        ManifestObject(guid="layout-guid", parent_guid=virtual_layouts_guid, type="layout", name="Layout1", title="Макет1", kind="object", payload={}),
    ]
    widget = DocumentEditorWidget(
        "АвансовыйОтчет",
        payload={},
        vm=VmStub(objs),
        obj_guid=owner_guid,
        available_subsystems=[],
    )
    app.processEvents()

    assert widget.lst_forms.count() == 1
    assert widget.lst_layouts.count() == 1
    assert widget.lbl_forms_info.text()
    assert widget.lbl_layouts_info.text()


def test_document_editor_opens_existing_form_with_reuse_path() -> None:
    app = QApplication.instance() or QApplication([])

    class VmStub:
        def __init__(self, objs):
            self._objs = list(objs)
            self.open_calls = []
            self.new_calls = []

        def list_objects(self):
            return list(self._objs)

        def list_subsystems(self):
            return []

        def create_object_quick(self, *args, **kwargs):
            return ""

        def request_open_new(self, info):
            self.new_calls.append(info)

        def on_open(self, info):
            self.open_calls.append(info)

        def delete_object(self, *args, **kwargs):
            return False

    owner_guid = "doc-guid"
    forms_guid = "forms-guid"
    objs = [
        ManifestObject(guid=owner_guid, parent_guid="", type="document", name="AdvanceReport", title="АвансовыйОтчет", kind="object", payload={}),
        ManifestObject(guid=forms_guid, parent_guid=owner_guid, type="document", name="forms", title="forms", kind="folder", payload={"system": True}),
        ManifestObject(guid="form-guid", parent_guid=forms_guid, type="form", name="ObjectForm", title="ФормаДокумента", kind="object", payload={}),
    ]
    vm = VmStub(objs)
    widget = DocumentEditorWidget(
        "АвансовыйОтчет",
        payload={"name": "AdvanceReport"},
        vm=vm,
        obj_guid=owner_guid,
        available_subsystems=[],
    )
    widget.lst_forms.setCurrentRow(0)
    widget._on_open_selected_form()
    app.processEvents()

    assert len(vm.open_calls) == 1
    assert len(vm.new_calls) == 0
    assert vm.open_calls[0].guid == "form-guid"


def test_document_editor_localizes_enum_labels_and_rights_display() -> None:
    app = QApplication.instance() or QApplication([])
    prev_lang = get_lang()
    set_lang("uk")
    try:
        payload = {
            "title": {"uk": "Авансовий звіт"},
            "number_type": "string",
            "number_periodicity": "year",
            "posting": "allow",
            "sequence_filling": "auto_fill_off",
            "create_on_input": "use",
            "search_string_mode_on_input_by_string": "begin",
            "choice_data_get_mode_on_input_by_string": "directly",
            "full_text_search_on_input_by_string": "dont_use",
            "choice_history_on_input": "dont_use",
            "requisites": [],
            "tabular_parts": [],
        }

        class VmStub:
            def list_objects(self):
                return [
                    ManifestObject(
                        guid="doc-other",
                        parent_guid="",
                        type="document",
                        name="RaskhodnyyKassovyyOrder",
                        title="Видатковий касовий ордер",
                        kind="object",
                        payload={},
                    )
                ]

            def list_subsystems(self):
                return []

            def get_meta_by_guid(self, guid: str):
                if guid == "doc-other":
                    return {"guid": guid, "title": "Видатковий касовий ордер", "name": "RaskhodnyyKassovyyOrder"}
                return None

        widget = DocumentEditorWidget(
            "АвансовийЗвіт",
            payload=payload,
            vm=VmStub(),
            obj_guid="doc-guid",
        )
        app.processEvents()

        assert widget.cb_number_type.itemText(0) == "Рядок"
        assert widget.cb_number_periodicity.itemText(0) == "У межах року"
        assert widget.cb_posting.itemText(0) == "Дозволити"
        assert widget.cb_sequence_filling.itemText(0) == "Не заповнювати автоматично"
        assert widget.cb_create_on_input.itemText(0) == "Використовувати"
        assert widget.cb_search_string_mode.itemText(0) == "Початок"
        assert widget.cb_choice_data_get_mode.itemText(0) == "Безпосередньо"

        widget.lst_roles.addItem("Бухгалтер")
        widget.lst_roles.item(0).setData(Qt.ItemDataRole.UserRole, {"rights": [("Read", True)], "has_related": False})
        widget.lst_roles.setCurrentRow(0)
        widget._reload_role_rights_view()

        assert widget.lst_role_rights.item(0).text() == "Читання"
        assert widget.lst_role_rights.item(0).checkState() == Qt.CheckState.Checked

        assert widget._fill_list_widget is not None
        widget.lst_based_on = QListWidget()
        widget._fill_list_widget(widget.lst_based_on, ["Document.RaskhodnyyKassovyyOrder"])
        assert widget.lst_based_on.item(0).text() == "RaskhodnyyKassovyyOrder"
    finally:
        set_lang(prev_lang)


def test_document_editor_reference_sections_use_checklists_and_grouped_register_tree() -> None:
    app = QApplication.instance() or QApplication([])

    class VmStub:
        def list_objects(self):
            return [
                ManifestObject(
                    guid="acc-reg",
                    parent_guid="acc-root",
                    type="register_accum",
                    name="Cash",
                    title="Гроші",
                    kind="object",
                    payload={},
                ),
                ManifestObject(
                    guid="info-reg",
                    parent_guid="info-root",
                    type="register_info",
                    name="DocSums",
                    title="СумиДокументів",
                    kind="object",
                    payload={},
                ),
                ManifestObject(
                    guid="doc-base",
                    parent_guid="doc-root",
                    type="document",
                    name="BaseDoc",
                    title="ДокументОснова",
                    kind="object",
                    payload={},
                ),
            ]

        def list_subsystems(self):
            return []

        def get_meta_by_guid(self, guid: str):
            if guid == "doc-base":
                return {"guid": guid, "title": "ДокументОснова", "name": "BaseDoc", "payload": {}}
            return None

    widget = DocumentEditorWidget(
        "АвансовийЗвіт",
        payload={
            "name": "AdvanceReport",
            "based_on": ["Document.BaseDoc"],
            "document_journals": ["РеестрТорговыхДокументов"],
            "sequence_memberships": ["ПроведениеПоРасчетамСПоставщиками"],
            "register_records": [
                "AccumulationRegister.Cash",
                "InformationRegister.DocSums",
            ],
            "requisites": [
                {"name": "Organization", "title": {"uk": "Організація"}, "type": "ref"},
            ],
        },
        vm=VmStub(),
    )
    widget._workspace_links = lambda: {
        "functional_options": [],
        "journals": ["РеестрТорговыхДокументов"],
        "sequences": ["ПроведениеПоРасчетамСПоставщиками"],
        "exchange_plans": [
            {"name": "ИнтеграцияС1СДокументооборотом", "auto_record": "allow"},
            {"name": "Полный", "auto_record": "deny"},
        ],
    }
    widget._reload_reference_lists()
    app.processEvents()

    assert widget.lst_based_on.count() == 1
    assert widget.lst_based_on.item(0).data(Qt.ItemDataRole.UserRole) == "Document.BaseDoc"

    assert widget.lst_journals.count() == 1
    assert widget.lst_journals.item(0).checkState() == Qt.CheckState.Checked
    assert widget.lst_sequences.count() == 1
    assert widget.lst_sequences.item(0).checkState() == Qt.CheckState.Checked

    tree = widget.tree_register_records
    assert isinstance(tree, QTreeWidget)
    assert tree.topLevelItemCount() == 2
    first_group = tree.topLevelItem(0)
    second_group = tree.topLevelItem(1)
    assert first_group is not None and first_group.childCount() == 1
    assert second_group is not None and second_group.childCount() == 1
    assert first_group.child(0).checkState(0) == Qt.CheckState.Checked
    assert second_group.child(0).checkState(0) == Qt.CheckState.Checked

    assert widget.tree_exchange_plans.topLevelItemCount() == 2
    assert widget.tree_exchange_plans.topLevelItem(0).text(0) == "ИнтеграцияС1СДокументооборотом"
    assert widget.tree_exchange_plans.topLevelItem(0).text(1)


def test_document_editor_input_by_string_fields_include_standard_and_requisites() -> None:
    app = QApplication.instance() or QApplication([])
    widget = DocumentEditorWidget(
        "АвансовийЗвіт",
        payload={
            "name": "AdvanceReport",
            "input_by_string": "Document.AdvanceReport.StandardAttribute.Number",
            "requisites": [
                {"name": "Organization", "title": {"uk": "Організація"}, "type": "ref"},
            ],
        },
    )
    app.processEvents()

    fields = widget._available_input_by_string_fields()
    values = [value for _label, value in fields]

    assert "Document.AdvanceReport.StandardAttribute.Number" in values
    assert "Document.AdvanceReport.StandardAttribute.Date" in values
    assert "Document.AdvanceReport.Attribute.Organization" in values

    widget._on_clear_input_by_string_field()
    app.processEvents()

    assert widget.ed_input_by_string_field.text() == ""
    assert widget._payload_raw["input_by_string"] == ""
    assert widget._payload_raw["input_by_string_field"] == ""


def test_document_editor_based_for_includes_business_processes_and_tasks() -> None:
    app = QApplication.instance() or QApplication([])

    class VmStub:
        def list_objects(self):
            return [
                ManifestObject(
                    guid="doc-self",
                    parent_guid="",
                    type="document",
                    name="AdvanceReport",
                    title="АвансовийЗвіт",
                    kind="object",
                    payload={},
                ),
                ManifestObject(
                    guid="bp-1",
                    parent_guid="",
                    type="business_process",
                    name="Approval",
                    title="Погодження",
                    kind="object",
                    payload={},
                ),
                ManifestObject(
                    guid="task-1",
                    parent_guid="",
                    type="task",
                    name="FollowUp",
                    title="Завдання",
                    kind="object",
                    payload={},
                ),
            ]

        def list_subsystems(self):
            return []

        def get_meta_by_guid(self, guid: str):
            if guid == "bp-1":
                return {"guid": guid, "title": "Погодження", "name": "Approval", "payload": {"based_on": ["Document.AdvanceReport"]}}
            if guid == "task-1":
                return {"guid": guid, "title": "Завдання", "name": "FollowUp", "payload": {"based_on": ["Document.AdvanceReport"]}}
            return {"guid": guid, "payload": {}}

    widget = DocumentEditorWidget(
        "АвансовийЗвіт",
        payload={"name": "AdvanceReport"},
        vm=VmStub(),
        obj_guid="doc-self",
    )
    widget._reload_reference_lists()
    app.processEvents()

    values = [widget.lst_based_for.item(i).text() for i in range(widget.lst_based_for.count())]
    assert "Approval" in values
    assert "FollowUp" in values
    assert "Погодження" not in values
    assert "Завдання" not in values


def test_document_editor_exchange_tree_merges_available_plans_with_selected_items() -> None:
    app = QApplication.instance() or QApplication([])

    class VmStub:
        def list_objects(self):
            return [
                ManifestObject(
                    guid="xp-1",
                    parent_guid="",
                    type="exchange_plan",
                    name="Full",
                    title="Повний",
                    kind="object",
                    payload={},
                ),
                ManifestObject(
                    guid="xp-2",
                    parent_guid="",
                    type="exchange_plan",
                    name="Trade",
                    title="Торгівля",
                    kind="object",
                    payload={},
                ),
            ]

        def list_subsystems(self):
            return []

    widget = DocumentEditorWidget(
        "АвансовийЗвіт",
        payload={
            "name": "AdvanceReport",
            "exchange_plans": [{"name": "Full", "auto_record": "allow"}],
        },
        vm=VmStub(),
    )
    widget._reload_reference_lists()
    app.processEvents()

    assert widget.tree_exchange_plans.topLevelItemCount() == 2
    assert widget.tree_exchange_plans.topLevelItem(0).checkState(0) in {
        Qt.CheckState.Checked,
        Qt.CheckState.Unchecked,
    }
    checked = [
        widget.tree_exchange_plans.topLevelItem(i).text(0)
        for i in range(widget.tree_exchange_plans.topLevelItemCount())
        if widget.tree_exchange_plans.topLevelItem(i).checkState(0) == Qt.CheckState.Checked
    ]
    assert "Full" in checked
    assert "Повний" not in checked
