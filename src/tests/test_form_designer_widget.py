from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QDragLeaveEvent, QDropEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QPlainTextEdit, QScrollArea, QSizePolicy, QTabWidget, QWidget

from src.ui_qt import i18n as i18n_mod
from src.ui_qt.i18n import get_lang, set_lang, t
from src.configurator.domain.form_model import FormModel, FormNode
from src.client.forms.form_runtime_widget import FormRuntimeWidget, ObjContext
from src.ui_qt.widgets.form_designer_widget import FormDesignerWidget, FormLockTarget
from src.ui_qt.widgets.form_designer_canvas import FORM_CONTROL_MIME, FormDesignerCanvasView
from src.ui_qt.widgets.form_designer_support import FORM_ELEMENT_TYPE_SPECS, FormElementTypeDialog
from src.ui_qt.widgets.metascript_highlighter import MetaScriptHighlighter


class _DummyVm:
    def get_meta_by_guid(self, _guid: str):
        return None


class _FormModuleFallbackVmStub(_DummyVm):
    def resolve_module_asset_key_for_owner(self, owner_guid: str) -> str:
        return "module://form-mod-1" if str(owner_guid) == "form-guid" else ""

    def get_text_asset(self, asset_key: str) -> tuple[str, str, str]:
        if str(asset_key) == "module://form-mod-1":
            return "Процедура Тест()\nКінецьПроцедури", "text/plain", "module://form-mod-1"
        return "", "text/plain", str(asset_key)


class _FormModelAssetVmStub(_DummyVm):
    def get_text_asset(self, asset_key: str) -> tuple[str, str, str]:
        if str(asset_key) == "manifest-payload/form-guid/form_model.json":
            return (
                """{"schema_version":1,"id":"f1","name":"Form","title":"Form","root":{"id":"root","type":"Container","name":"root","props":{"layout":"vertical"},"children":[{"id":"lbl1","type":"Label","name":"header","title":"Заголовок","props":{},"children":[]}]}}""",
                "application/json",
                "manifest-payload/form-guid/form_model.json",
            )
        return "", "text/plain", str(asset_key)


class _SaveVmStub(_DummyVm):
    def __init__(self) -> None:
        self.asset_saves: list[tuple[str, dict, str, bool]] = []
        self.patch_saves: list[tuple[str, dict, bool]] = []
        self._saved_payload: dict | None = None
        self.asset_save_result = True
        self.patch_save_result = True

    def save_externalized_payload_asset(self, guid: str, payload: dict, *, key: str, reload: bool = False) -> bool:
        self.asset_saves.append((str(guid), dict(payload), str(key), bool(reload)))
        if self.asset_save_result:
            self._saved_payload = dict(payload)
        return self.asset_save_result

    def save_object_payload_patch(self, guid: str, patch: dict, *, reload: bool = False) -> bool:
        self.patch_saves.append((str(guid), dict(patch), bool(reload)))
        return self.patch_save_result

    def get_meta_by_guid(self, guid: str):
        if str(guid) != "form-guid" or self._saved_payload is None:
            return None
        payload = dict(self._saved_payload)
        model = dict(payload.get("form_model") or {})
        try:
            model["root"]["children"][0]["title"] = "Збережений стан"
        except Exception:
            pass
        payload["form_model"] = model
        payload["form_module"] = "Процедура Збережено()\nКінецьПроцедури"
        return {
            "guid": "form-guid",
            "type": "form",
            "name": "ФормаДокумента",
            "title": "ФормаДокумента",
            "parent_guid": "forms-folder-guid",
            "payload": payload,
        }


class _RefreshVmStub(_DummyVm):
    def __init__(self, payload: dict) -> None:
        self.payload = dict(payload)

    def get_meta_by_guid(self, guid: str):
        if str(guid) != "form-guid":
            return None
        return {
            "guid": "form-guid",
            "type": "form",
            "name": "ФормаДокумента",
            "title": "ФормаДокумента",
            "parent_guid": "forms-folder-guid",
            "payload": dict(self.payload),
        }


class _StorageStub:
    def __init__(self) -> None:
        self.commits: list[tuple[str, dict, str, str]] = []

    def connection(self):
        return object()

    def is_lock_held_by_me(self, *, lock_key: str, user_id: str = "SYSTEM") -> bool:
        return True

    def commit(self, *, lock_key: str, payload: dict, message: str = "", user_id: str = "SYSTEM") -> None:
        self.commits.append((str(lock_key), dict(payload), str(message), str(user_id)))

    def get_latest(self, *, lock_key: str):
        return None


class _OwnerMetaVm(_DummyVm):
    def __init__(self, *, subtype: str = "object_form") -> None:
        self._meta = {
            "form-guid": {
                "guid": "form-guid",
                "type": "form",
                "name": "ФормаДокумента",
                "title": "Форма документа",
                "parent_guid": "forms-folder-guid",
                "payload": {"subtype": subtype},
            },
            "forms-folder-guid": {
                "guid": "forms-folder-guid",
                "type": "document",
                "name": "forms",
                "title": "Forms",
                "parent_guid": "owner-guid",
                "payload": {},
            },
            "owner-guid": {
                "guid": "owner-guid",
                "type": "document",
                "name": "AdvanceReport",
                "title": "Авансовый отчет",
                "payload": {
                    "requisites": [
                        {"code": "Number", "type": "string", "required": True},
                        {"code": "Date", "type": "datetime", "required": True},
                    ]
                },
            },
        }

    def get_meta_by_guid(self, guid: str):
        return self._meta.get(str(guid))


class _ImportedOwnerMetaVm(_OwnerMetaVm):
    def __init__(self) -> None:
        super().__init__()
        self._meta["owner-guid"]["payload"] = {
            "requisites": [
                {"name": "Organization", "title": {"uk": "Організація"}, "type": "ref"},
                {"name": "Comment", "title": {"uk": "Коментар"}, "type": "string"},
            ],
            "tabular_parts": [
                {
                    "name": "Advances",
                    "title": {"uk": "Отримані аванси"},
                    "columns": [
                        {"name": "Amount", "title": {"uk": "Сума"}, "type": "number"},
                    ],
                }
            ],
        }


def _make_payload() -> dict:
    return {
        "form_module": "Якщо і = 1 Тоді\nКінецьЯкщо;",
        "form_model": {
            "schema_version": 1,
            "id": "f1",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "name": "root",
                "props": {"layout": "vertical"},
                "children": [
                    {
                        "id": "lbl1",
                        "type": "Label",
                        "name": "header",
                        "title": "Заголовок",
                        "props": {},
                        "children": [],
                    },
                    {
                        "id": "grp1",
                        "type": "Container",
                        "name": "HruppaShapka",
                        "title": "Шапка",
                        "props": {"layout": "vertical"},
                        "children": [
                            {
                                "id": "f_org",
                                "type": "TextBox",
                                "name": "Organization",
                                "title": "Організація",
                                "binding": "Organization",
                                "props": {"title_location": "Left"},
                                "children": [],
                            }
                        ],
                    },
                    {
                        "id": "tbl1",
                        "type": "Table",
                        "name": "Rows",
                        "title": "Рядки",
                        "props": {"columns": ["Колонка"]},
                        "children": [],
                    },
                ],
            },
        }
    }


def _make_externalized_payload() -> dict:
    payload = _make_payload()
    payload["form_model_ref"] = "manifest-payload/form-guid/form_model.json"
    return payload


def _make_decoration_payload() -> dict:
    payload = _make_payload()
    decoration = payload["form_model"]["root"]["children"][0]
    decoration.update(
        {
            "name": "Decoration1",
            "title": "",
            "props": {
                "is_decoration": True,
                "decoration_kind": "label",
                "layout_spacer": True,
                "width_chars": 2,
            },
        }
    )
    return payload


def test_form_designer_exposes_decoration_properties_and_keeps_empty_title() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_decoration_payload(),
    )
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    decoration_item = root_item.child(0)
    assert decoration_item is not None
    widget.tree.setCurrentItem(decoration_item)
    app.processEvents()

    assert widget._ed_name.text() == "Decoration1"
    assert widget._ed_title.text() == ""
    assert widget._cb_decoration_kind.isHidden() is False
    assert widget._chk_enabled.isHidden() is False
    assert widget._ed_tooltip.isHidden() is False
    assert widget._sp_width_chars.value() == 2

    widget._ed_title.setText("Visible caption")
    widget._on_prop_changed()
    app.processEvents()

    node = widget._node_by_id["lbl1"]
    assert node.title == "Visible caption"
    assert node.props["layout_spacer"] is False


def _redirect_i18n_settings(tmp_path) -> tuple[object, str]:
    prev_path = i18n_mod._SETTINGS_PATH
    prev_lang = i18n_mod.get_lang()
    i18n_mod._SETTINGS_PATH = tmp_path / "settings.json"
    i18n_mod._lang = prev_lang
    i18n_mod._inited = True
    return prev_path, prev_lang


def _restore_i18n_settings(prev_path, prev_lang: str) -> None:
    i18n_mod._SETTINGS_PATH = prev_path
    i18n_mod._lang = prev_lang
    i18n_mod._inited = True


def test_form_designer_localizes_toolbox_and_tree_and_filters_properties(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    prev_path, prev_lang = _redirect_i18n_settings(tmp_path)
    try:
        set_lang("uk")
        widget = FormDesignerWidget(
            vm=_DummyVm(),
            form_guid="form-guid",
            form_title="ФормаДокумента",
            form_meta_payload=_make_payload(),
        )
        widget.show()
        app.processEvents()

        assert widget.toolbox.item(0).text() == "Напис"
        assert widget.requisites.headerItem().text(0) == "Реквізит"
        assert widget.requisites.headerItem().text(1) == "Використовувати завжди"
        assert widget.requisites.headerItem().text(2) == "Тип"

        root_item = widget.tree.topLevelItem(0)
        assert root_item is not None
        assert widget._chk_visible.isHidden() is True
        assert widget._cb_open_mode.isHidden() is False
        assert widget._cb_window_lock_mode.isHidden() is False
        assert widget._cb_open_mode.currentData() == "auto"
        assert widget._cb_window_lock_mode.isEnabled() is False

        widget._cb_open_mode.setCurrentIndex(widget._cb_open_mode.findData("window"))
        widget._cb_window_lock_mode.setCurrentIndex(widget._cb_window_lock_mode.findData("owner"))
        app.processEvents()
        assert widget._model.root.props["open_mode"] == "window"
        assert widget._model.root.props["window_lock_mode"] == "owner"
        root_item = widget.tree.topLevelItem(0)
        assert root_item is not None
        label_item = root_item.child(0)
        assert label_item is not None
        assert label_item.text(0) == "Заголовок"

        group_item = root_item.child(1)
        assert group_item is not None
        assert group_item.text(0) == "Шапка"

        widget.tree.setCurrentItem(label_item)
        app.processEvents()

        assert widget._chk_visible.isHidden() is False
        assert widget._chk_visible.isChecked() is True
        assert widget._ed_form_title.isHidden() is True
        assert widget._cb_open_mode.isHidden() is True
        assert widget._cb_window_lock_mode.isHidden() is True
        assert widget._ed_binding.isHidden() is True
        assert widget._cb_layout.isHidden() is True
        assert widget._cb_representation.isHidden() is True
        assert widget._sp_grid_cols.isHidden() is True
        assert widget._lbl_table_columns.isHidden() is True
        assert widget._tbl_columns.isHidden() is True

        widget.tree.setCurrentItem(group_item)
        app.processEvents()
        assert widget._cb_layout.isHidden() is False
        assert widget._cb_representation.isHidden() is False
        assert widget._chk_show_title.isHidden() is False

        table_item = root_item.child(2)
        assert table_item is not None
        widget.tree.setCurrentItem(table_item)
        app.processEvents()

        assert widget._lbl_table_columns.isHidden() is False
        assert widget._tbl_columns.isHidden() is False
    finally:
        _restore_i18n_settings(prev_path, prev_lang)


def test_form_designer_lists_imported_name_requisites_and_tabular_parts(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    prev_path, prev_lang = _redirect_i18n_settings(tmp_path)
    try:
        set_lang("uk")
        widget = FormDesignerWidget(
            vm=_ImportedOwnerMetaVm(),
            form_guid="form-guid",
            form_title="ФормаДокумента",
            form_meta_payload=_make_payload(),
        )
        widget.show()
        app.processEvents()

        assert widget.requisites.topLevelItemCount() == 1
        object_item = widget.requisites.topLevelItem(0)
        assert object_item.text(0) == "Об'єкт"
        assert object_item.text(2) == "(ДокументОб'єкт.AdvanceReport)"
        assert object_item.child(0).text(0) == "Посилання"
        assert object_item.child(1).text(0) == "Організація"
        assert object_item.child(2).text(0) == "Коментар"
        table_item = object_item.child(3)
        assert table_item.text(0) == "Отримані аванси"
        assert table_item.text(2) == "(ДокументТабличнаЧастина.AdvanceReport.Advances)"
        assert table_item.childCount() == 1
        assert table_item.child(0).text(0) == "Сума"
        assert table_item.child(0).text(2) == "Число"

        widget._on_requisite_double_clicked(table_item)
        table = next(
            node
            for node in widget._model.root.children
            if node.type == "Table" and node.binding == "Advances"
        )
        assert table.binding == "Advances"
        assert table.props["columns"][0]["name"] == "Amount"
        assert table.props["columns"][0]["title"] == "Сума"
        widget._set_dirty(False)
        widget.close()
    finally:
        _restore_i18n_settings(prev_path, prev_lang)


def test_form_designer_projects_table_structure_without_mutating_form_model(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    prev_path, prev_lang = _redirect_i18n_settings(tmp_path)
    try:
        set_lang("uk")
        widget = FormDesignerWidget(
            vm=_DummyVm(),
            form_guid="form-guid",
            form_title="ФормаДокумента",
            form_meta_payload=_make_payload(),
        )
        widget.show()
        app.processEvents()

        root_item = widget.tree.topLevelItem(0)
        table_item = root_item.child(2)
        assert table_item.text(0) == "Рядки"
        assert table_item.childCount() == 2
        assert table_item.child(0).text(0) == "Командна панель"
        assert table_item.child(1).text(0) == "Колонка"
        assert str(table_item.child(1).data(0, Qt.ItemDataRole.UserRole)).startswith("virtual:")

        table_node = widget._model.root.children[2]
        assert table_node.type == "Table"
        assert table_node.children == []
        widget.tree.setCurrentItem(table_item.child(1))
        assert widget._current_node() is None
        widget.close()
    finally:
        _restore_i18n_settings(prev_path, prev_lang)


def test_form_designer_uses_imported_technical_names_in_elements_tree(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    prev_path, prev_lang = _redirect_i18n_settings(tmp_path)
    try:
        set_lang("uk")
        payload = _make_payload()
        payload["imported"] = {"source": "1c"}
        group = payload["form_model"]["root"]["children"][1]
        table = payload["form_model"]["root"]["children"][2]
        table["props"]["columns"] = [
            {
                "name": "ТоварыКоличество",
                "title": "Кількість",
                "binding": "Количество",
            }
        ]
        widget = FormDesignerWidget(
            vm=_DummyVm(),
            form_guid="form-guid",
            form_title="ФормаДокумента",
            form_meta_payload=payload,
        )
        widget.show()
        app.processEvents()

        root_item = widget.tree.topLevelItem(0)
        assert root_item.child(1).text(0) == "HruppaShapka"
        assert root_item.child(2).text(0) == "Rows"
        assert root_item.child(2).child(1).text(0) == "ТоварыКоличество"
        widget.close()
    finally:
        _restore_i18n_settings(prev_path, prev_lang)


def test_form_designer_persists_use_always_requisites_in_form_model(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    prev_path, prev_lang = _redirect_i18n_settings(tmp_path)
    try:
        set_lang("uk")
        widget = FormDesignerWidget(
            vm=_ImportedOwnerMetaVm(),
            form_guid="form-guid",
            form_title="ФормаДокумента",
            form_meta_payload=_make_payload(),
        )
        widget.show()
        app.processEvents()

        object_item = widget.requisites.topLevelItem(0)
        organization_item = object_item.child(1)
        organization_item.setCheckState(1, Qt.CheckState.Unchecked)
        app.processEvents()

        use_always = widget._model.root.props["use_always_requisites"]
        assert "Organization" not in use_always
        assert "Comment" in use_always
        assert "Advances.Amount" in use_always
        widget._set_dirty(False)
        widget.close()
    finally:
        _restore_i18n_settings(prev_path, prev_lang)


def test_form_designer_omits_redundant_form_surface_toolbar() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.resize(1400, 850)
    widget.show()
    app.processEvents()

    assert widget._design_hint.isHidden() is True
    assert widget._design_toolbar.isHidden() is True
    assert widget._elements_toolbar.isVisible() is True
    assert widget._design_window_scroll.isVisible() is True


def test_form_element_type_dialog_localizes_and_returns_group_variant(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    prev_path, prev_lang = _redirect_i18n_settings(tmp_path)
    try:
        set_lang("uk")
        dialog = FormElementTypeDialog()

        assert dialog.windowTitle() == "Тип елемента"
        assert dialog.type_list.count() == len(FORM_ELEMENT_TYPE_SPECS)
        assert dialog.type_list.item(0).text() == "Група - звичайна група"

        dialog.type_list.setCurrentRow(1)
        spec = dialog.selected_spec()
        assert spec is not None
        assert spec.control_type == "Container"
        assert spec.props() == {
            "layout": "vertical",
            "representation": "none",
            "show_title": False,
        }
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
    finally:
        _restore_i18n_settings(prev_path, prev_lang)


def test_form_designer_add_dialog_applies_selected_type_defaults(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    class _AcceptedDialog:
        def __init__(self, _parent=None) -> None:
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_spec(self):
            return FORM_ELEMENT_TYPE_SPECS[0]

    monkeypatch.setattr("src.ui_qt.widgets.form_designer.FormElementTypeDialog", _AcceptedDialog)
    before = len(widget._model.root.children)
    widget._show_add_element_dialog()
    app.processEvents()

    assert len(widget._model.root.children) == before + 1
    added = widget._model.root.children[-1]
    assert added.type == "Container"
    assert added.title == t("form_element_default_group_title")
    assert added.props.get("representation") == "usual"
    assert added.props.get("show_title") is True


def test_form_designer_tree_uses_compact_rows_and_disclosure_button_hit_area() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.resize(1400, 850)
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    group_item = root_item.child(1) if root_item is not None else None
    assert root_item is not None
    assert group_item is not None
    widget.tree.expandAll()
    widget.tree.setCurrentItem(root_item)
    app.processEvents()

    group_rect = widget.tree.visualItemRect(group_item)
    assert group_rect.height() <= 24
    assert widget.tree.indentation() == 18
    button_rect = widget.tree._branch_button_rect(group_rect)

    QTest.mouseClick(
        widget.tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=QPoint(2, group_rect.center().y()),
    )
    app.processEvents()
    assert group_item.isExpanded() is True
    assert widget.tree.currentItem() is root_item

    QTest.mouseClick(
        widget.tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=button_rect.center(),
    )
    app.processEvents()
    assert group_item.isExpanded() is False
    assert widget.tree.currentItem() is root_item



def test_form_designer_container_representation_is_saved_back_to_model(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    prev_path, prev_lang = _redirect_i18n_settings(tmp_path)
    try:
        widget = FormDesignerWidget(
            vm=_DummyVm(),
            form_guid="form-guid",
            form_title="ФормаДокумента",
            form_meta_payload=_make_payload(),
        )
        widget.show()
        app.processEvents()

        root_item = widget.tree.topLevelItem(0)
        assert root_item is not None
        group_item = root_item.child(1)
        assert group_item is not None
        widget.tree.setCurrentItem(group_item)
        app.processEvents()

        widget._cb_representation.setCurrentIndex(widget._cb_representation.findData("none"))
        widget._chk_show_title.setChecked(False)
        app.processEvents()

        node = widget._node_by_id["grp1"]
        assert node.props.get("representation") == "none"
        assert node.props.get("show_title") is False
    finally:
        _restore_i18n_settings(prev_path, prev_lang)


def test_form_designer_group_anchor_is_saved_back_to_model(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    prev_path, prev_lang = _redirect_i18n_settings(tmp_path)
    try:
        widget = FormDesignerWidget(
            vm=_DummyVm(),
            form_guid="form-guid",
            form_title="ФормаДокумента",
            form_meta_payload=_make_payload(),
        )
        widget.show()
        app.processEvents()

        root_item = widget.tree.topLevelItem(0)
        assert root_item is not None
        group_item = root_item.child(1)
        assert group_item is not None
        field_item = group_item.child(0)
        assert field_item is not None

        widget.tree.setCurrentItem(field_item)
        app.processEvents()

        widget._cb_group_anchor.setCurrentIndex(widget._cb_group_anchor.findData("end"))
        app.processEvents()

        node = widget._node_by_id["f_org"]
        assert node.props.get("group_anchor") == "end"
    finally:
        _restore_i18n_settings(prev_path, prev_lang)


def test_form_designer_does_not_render_layout_only_group_as_groupbox() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    assert widget.preview_host.findChildren(QGroupBox) == []
    assert widget._design_preview_host.findChildren(QGroupBox) == []

    group_widget = widget._design_wrap_by_id.get("grp1")
    assert group_widget is not None
    margins = group_widget.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (0, 0, 0, 0)

    field_wrap = widget._design_wrap_by_id.get("f_org")
    assert field_wrap is not None
    wrap_margins = field_wrap.layout().contentsMargins()
    assert (wrap_margins.left(), wrap_margins.top(), wrap_margins.right(), wrap_margins.bottom()) == (0, 0, 0, 0)


def test_form_designer_renders_groupbox_for_visible_group_title() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["children"][1]["props"]["representation"] = "usual"
    payload["form_model"]["root"]["children"][1]["props"]["show_title"] = True
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    preview_groups = widget.preview_host.findChildren(QGroupBox)
    design_groups = widget._design_preview_host.findChildren(QGroupBox)
    assert len(preview_groups) == 1
    assert len(design_groups) == 1
    assert preview_groups[0].title() == "Шапка"
    assert design_groups[0].title() == "Шапка"


def test_form_designer_left_titles_are_left_aligned() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    labels = [
        lab for lab in widget._design_preview_host.findChildren(QLabel)
        if lab.text().startswith("Організація")
    ]
    assert labels
    assert labels[0].alignment() & Qt.AlignmentFlag.AlignLeft
    field_wrap = widget._design_wrap_by_id.get("f_org")
    assert field_wrap is not None
    assert field_wrap.findChildren(QLabel) == []


def test_form_designer_retranslates_open_widget(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    prev_path, prev_lang = _redirect_i18n_settings(tmp_path)
    try:
        set_lang("en")
        widget = FormDesignerWidget(
            vm=_DummyVm(),
            form_guid="form-guid",
            form_title="ФормаДокумента",
            form_meta_payload=_make_payload(),
        )
        widget.show()
        app.processEvents()
        assert widget.toolbox.item(0).text() == "Label"

        set_lang("uk")
        app.processEvents()

        assert widget.toolbox.item(0).text() == "Напис"
        assert widget._props_title.text() == "Властивості форми"
        root_item = widget.tree.topLevelItem(0)
        assert root_item is not None
        assert root_item.text(0) == "Форма"
    finally:
        _restore_i18n_settings(prev_path, prev_lang)


def test_form_designer_module_tab_uses_metascript_editor_chrome() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    assert widget._module_editor.toPlainText().startswith("Якщо")
    assert "background: #0B1020" in widget._module_editor.styleSheet()
    assert widget._module_editor.font().family() == "Cascadia Code"
    assert isinstance(widget._module_highlighter, MetaScriptHighlighter)
    assert hasattr(widget._module_editor, "line_number_area_width")


def test_form_designer_loads_module_text_from_owner_module_asset_when_payload_is_empty() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload.pop("form_module", None)
    payload.pop("module", None)
    widget = FormDesignerWidget(
        vm=_FormModuleFallbackVmStub(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    assert "Процедура Тест" in widget._module_editor.toPlainText()
    assert str((widget._payload.get("module") or {}).get("asset_key") or "") == "module://form-mod-1"


def test_form_designer_loads_form_model_from_externalized_asset_when_payload_is_ref_only() -> None:
    app = QApplication.instance() or QApplication([])
    payload = {
        "form_model_ref": "manifest-payload/form-guid/form_model.json",
        "form_module": "",
    }
    widget = FormDesignerWidget(
        vm=_FormModelAssetVmStub(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    assert widget._model.root.children
    assert widget._model.root.children[0].title == "Заголовок"


def test_form_designer_preview_uses_runtime_widget() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    assert isinstance(widget._preview_runtime_widget, FormRuntimeWidget)


def test_form_runtime_embedded_root_expands_to_available_width() -> None:
    app = QApplication.instance() or QApplication([])
    runtime = FormRuntimeWidget(
        model=_make_payload()["form_model"],
        embedded=True,
        ctx=ObjContext(),
        manifest_rows=[],
    )
    runtime.show()
    app.processEvents()

    roots = [
        child
        for child in runtime.findChildren(QWidget)
        if bool(child.property("mp_form_surface_root"))
    ]
    assert roots
    assert roots[0].sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert runtime.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding


def test_form_runtime_horizontal_stretch_sets_layout_stretch_factor() -> None:
    app = QApplication.instance() or QApplication([])
    model = FormModel(
        id="f2",
        name="Form",
        title="Form",
        root=FormNode(
            id="root",
            type="Container",
            props={"layout": "horizontal"},
            children=[
                FormNode(
                    id="stretch",
                    type="TextBox",
                    name="StretchField",
                    title="Поле",
                    props={"horizontal_stretch": True},
                )
            ],
        ),
    )
    runtime = FormRuntimeWidget(model=model, embedded=True, ctx=ObjContext(), manifest_rows=[])
    runtime.show()
    app.processEvents()

    field = runtime.findChild(QLineEdit)
    assert field is not None
    wrap = field.parentWidget()
    assert wrap is not None
    layout = wrap.layout()
    assert isinstance(layout, QHBoxLayout)
    assert layout.stretch(layout.indexOf(field)) == 1


def test_form_runtime_vertical_stretch_in_horizontal_layout_sets_expand_policy() -> None:
    app = QApplication.instance() or QApplication([])
    model = FormModel(
        id="f4",
        name="Form",
        title="Form",
        root=FormNode(
            id="root",
            type="Container",
            props={"layout": "horizontal"},
            children=[
                FormNode(
                    id="stretch",
                    type="TextBox",
                    name="StretchField",
                    title="Поле",
                    props={"vertical_stretch": True},
                )
            ],
        ),
    )
    runtime = FormRuntimeWidget(model=model, embedded=True, ctx=ObjContext(), manifest_rows=[])
    runtime.show()
    app.processEvents()

    field = runtime.findChild(QLineEdit)
    assert field is not None
    assert field.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding


def test_form_runtime_grid_stretch_sets_row_and_column_stretch() -> None:
    app = QApplication.instance() or QApplication([])
    model = FormModel(
        id="f5",
        name="Form",
        title="Form",
        root=FormNode(
            id="root",
            type="Container",
            props={"layout": "grid"},
            children=[
                FormNode(
                    id="stretch-x",
                    type="TextBox",
                    name="StretchX",
                    title="X",
                    props={"grid": {"row": 0, "col": 0}, "horizontal_stretch": True},
                ),
                FormNode(
                    id="stretch-y",
                    type="TextArea",
                    name="StretchY",
                    title="Y",
                    props={"grid": {"row": 1, "col": 0}, "vertical_stretch": True},
                ),
            ],
        ),
    )
    runtime = FormRuntimeWidget(model=model, embedded=True, ctx=ObjContext(), manifest_rows=[])
    runtime.show()
    app.processEvents()

    root_frame = next(
        (
            w
            for w in runtime.findChildren(QWidget)
            if w.layout() is not None
            and type(w.layout()).__name__ == "QGridLayout"
            and w.layout().count() == 2
        ),
        None,
    )
    assert root_frame is not None
    layout = root_frame.layout()
    assert isinstance(layout, QGridLayout)
    assert layout.columnStretch(0) == 1
    rows = {}
    for idx in range(layout.count()):
        item = layout.itemAt(idx)
        assert item is not None
        widget = item.widget()
        assert widget is not None
        row, col, _rowspan, _colspan = layout.getItemPosition(idx)
        rows[(row, col)] = widget
    assert (0, 0) in rows
    assert (1, 0) in rows
    assert rows[(1, 0)].sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding


def test_form_runtime_vertical_stretch_sets_row_stretch() -> None:
    app = QApplication.instance() or QApplication([])
    model = FormModel(
        id="f3",
        name="Form",
        title="Form",
        root=FormNode(
            id="root",
            type="Container",
            props={"layout": "vertical"},
            children=[
                FormNode(
                    id="stretch",
                    type="TextBox",
                    name="StretchField",
                    title="Поле",
                    props={"vertical_stretch": True},
                )
            ],
        ),
    )
    runtime = FormRuntimeWidget(model=model, embedded=True, ctx=ObjContext(), manifest_rows=[])
    runtime.show()
    app.processEvents()

    field = runtime.findChild(QLineEdit)
    assert field is not None
    wrap = field.parentWidget()
    assert wrap is not None
    layout = wrap.layout()
    assert isinstance(layout, QGridLayout)
    idx = layout.indexOf(field)
    row, _col, _rowspan, _colspan = layout.getItemPosition(idx)
    assert layout.rowStretch(row) == 1


def test_form_designer_non_absolute_design_uses_runtime_surface_mapping() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    assert getattr(widget, "_design_runtime_surface", None) is not None
    assert "f_org" in widget._design_wrap_by_id


def test_form_designer_rebuilds_design_preview_on_property_change() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    original_surface = getattr(widget, "_design_runtime_surface", None)
    assert original_surface is not None

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    group_item = root_item.child(1)
    assert group_item is not None
    field_item = group_item.child(0)
    assert field_item is not None

    widget.tree.setCurrentItem(field_item)
    app.processEvents()

    widget._ed_title.setText("Організація оновлена")
    widget._on_prop_changed()
    app.processEvents()

    rebuilt_surface = getattr(widget, "_design_runtime_surface", None)
    assert rebuilt_surface is not None
    assert rebuilt_surface is not original_surface


def test_form_designer_edits_client_visibility_without_hiding_design_node() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["children"][0]["props"]["visible"] = False
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    hidden_item = root_item.child(0)
    assert hidden_item is not None
    widget.tree.setCurrentItem(hidden_item)
    app.processEvents()

    assert widget._chk_visible.isChecked() is False
    assert t("form_hidden_in_client") in hidden_item.text(0)
    hidden_wrap = widget._design_runtime_surface.widget_for_node("lbl1")
    assert hidden_wrap is not None
    assert hidden_wrap.isVisible()
    assert hidden_wrap.property("form_hidden_in_client") is True

    widget._chk_visible.setChecked(True)
    app.processEvents()

    assert widget._node_by_id["lbl1"].props["visible"] is True
    assert t("form_hidden_in_client") not in widget._tree_item_by_id["lbl1"].text(0)


def test_form_designer_saves_client_visibility_to_externalized_form_model() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _SaveVmStub()
    payload = _make_externalized_payload()
    payload["form_model"]["root"]["children"][0]["props"]["visible"] = False
    widget = FormDesignerWidget(
        vm=vm,
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    widget._set_dirty(True)
    assert widget.save() is True

    saved_model = vm.asset_saves[-1][1]["form_model"]
    assert saved_model["root"]["children"][0]["props"]["visible"] is False


def test_form_designer_horizontal_stretch_updates_design_preview_runtime() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    group_item = root_item.child(1)
    assert group_item is not None
    field_item = group_item.child(0)
    assert field_item is not None

    widget.tree.setCurrentItem(field_item)
    app.processEvents()

    widget._chk_hstretch.setChecked(True)
    widget._on_prop_changed()
    app.processEvents()

    rebuilt_surface = getattr(widget, "_design_runtime_surface", None)
    assert rebuilt_surface is not None
    field = rebuilt_surface.findChild(QLineEdit)
    assert field is not None
    assert field.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding


def test_form_designer_preview_drop_inserts_control_into_selected_container() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    group_item = root_item.child(1)
    assert group_item is not None
    widget.tree.setCurrentItem(group_item)
    app.processEvents()

    surface = getattr(widget, "_design_runtime_surface", None)
    assert surface is not None
    target = surface.widget_for_node("grp1")
    assert target is not None

    before = len(widget._model.root.children[1].children)

    mime = QMimeData()
    mime.setData(FORM_CONTROL_MIME, b"TextBox")
    event = QDropEvent(
        QPointF(18.0, 26.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    handled = surface.eventFilter(target, event)
    app.processEvents()

    assert handled is True
    assert len(widget._model.root.children[1].children) == before + 1
    assert any(ch.type == "TextBox" for ch in widget._model.root.children[1].children)


def test_form_designer_canvas_drop_inserts_control_into_hovered_container() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["props"]["layout"] = "absolute"
    payload["form_model"]["root"]["children"][0]["props"] = {"x": 20, "y": 20, "w": 120, "h": 24}
    payload["form_model"]["root"]["children"][1]["props"] = {"layout": "absolute", "x": 40, "y": 60, "w": 240, "h": 160}
    payload["form_model"]["root"]["children"][1]["children"][0]["props"] = {"x": 10, "y": 10, "w": 160, "h": 28}
    payload["form_model"]["root"]["children"][2]["props"] = {"x": 340, "y": 60, "w": 240, "h": 160}
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    before = len(widget._model.root.children[1].children)

    mime = QMimeData()
    mime.setData(FORM_CONTROL_MIME, b"TextBox")
    event = QDropEvent(
        QPointF(90.0, 110.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    widget.canvas.dropEvent(event)
    app.processEvents()

    assert len(widget._model.root.children[1].children) == before + 1
    assert widget._model.root.children[1].children[-1].type == "TextBox"


def test_form_designer_canvas_prefers_deepest_nested_absolute_container() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["props"]["layout"] = "absolute"
    payload["form_model"]["root"]["children"][0]["props"] = {"x": 20, "y": 20, "w": 120, "h": 24}
    payload["form_model"]["root"]["children"][1]["props"] = {"layout": "absolute", "x": 40, "y": 60, "w": 260, "h": 180}
    payload["form_model"]["root"]["children"][1]["children"] = [
        {
            "id": "inner_grp",
            "type": "Container",
            "name": "InnerGroup",
            "title": "Внутрішня",
            "props": {"layout": "absolute", "x": 30, "y": 30, "w": 120, "h": 80},
            "children": [],
        }
    ]
    payload["form_model"]["root"]["children"][2]["props"] = {"x": 340, "y": 60, "w": 240, "h": 160}
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    inner_container = widget.canvas._item_by_id.get("inner_grp")
    assert inner_container is not None
    assert widget.canvas._drop_parent_id_for_scene_pos(QPointF(95.0, 125.0)) == "inner_grp"

    before_outer = len(widget._model.root.children[1].children)
    before_inner = len(widget._model.root.children[1].children[0].children)

    mime = QMimeData()
    mime.setData(FORM_CONTROL_MIME, b"TextBox")
    event = QDropEvent(
        QPointF(95.0, 125.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    widget.canvas.dropEvent(event)
    app.processEvents()

    assert len(widget._model.root.children[1].children) == before_outer
    assert len(widget._model.root.children[1].children[0].children) == before_inner + 1
    assert widget._model.root.children[1].children[0].children[-1].type == "TextBox"

    widget.canvas.preview_move_target("inner_grp")
    app.processEvents()
    assert widget.canvas._drop_target_id == "inner_grp"


def test_form_designer_canvas_drag_move_highlights_drop_target() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["props"]["layout"] = "absolute"
    payload["form_model"]["root"]["children"][0]["props"] = {"x": 20, "y": 20, "w": 120, "h": 24}
    payload["form_model"]["root"]["children"][1]["props"] = {"layout": "absolute", "x": 40, "y": 60, "w": 240, "h": 160}
    payload["form_model"]["root"]["children"][1]["children"][0]["props"] = {"x": 10, "y": 10, "w": 160, "h": 28}
    payload["form_model"]["root"]["children"][2]["props"] = {"x": 340, "y": 60, "w": 240, "h": 160}
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    mime = QMimeData()
    mime.setData(FORM_CONTROL_MIME, b"TextBox")
    enter_event = QDropEvent(
        QPointF(90.0, 110.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.canvas.dragEnterEvent(enter_event)
    widget.canvas.dragMoveEvent(enter_event)
    app.processEvents()

    assert widget.canvas._drop_target_id == "grp1"

    leave_event = QDragLeaveEvent()
    widget.canvas.dragLeaveEvent(leave_event)
    app.processEvents()

    assert widget.canvas._drop_target_id == ""


def test_form_designer_canvas_preview_move_target_updates_drop_highlight() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["props"]["layout"] = "absolute"
    payload["form_model"]["root"]["children"][0]["props"] = {"x": 20, "y": 20, "w": 120, "h": 24}
    payload["form_model"]["root"]["children"][1]["props"] = {"layout": "absolute", "x": 40, "y": 60, "w": 240, "h": 160}
    payload["form_model"]["root"]["children"][1]["children"][0]["props"] = {"x": 10, "y": 10, "w": 160, "h": 28}
    payload["form_model"]["root"]["children"][2]["props"] = {"x": 340, "y": 60, "w": 240, "h": 160}
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    item = widget.canvas._item_by_id.get("lbl1")
    assert item is not None
    item.setPos(80, 90)
    widget.canvas.preview_move_target("lbl1")
    app.processEvents()

    assert widget.canvas._drop_target_id == "grp1"

    widget.canvas.clear_drop_target()
    app.processEvents()

    assert widget.canvas._drop_target_id == ""


def test_form_designer_preview_allows_switching_tabs_in_live_widget() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload={
            "form_model": {
                "schema_version": 1,
                "id": "f-tabs",
                "name": "Form",
                "title": "Form",
                "root": {
                    "id": "root",
                    "type": "Container",
                    "props": {"layout": "vertical"},
                    "children": [
                        {
                            "id": "tabs-1",
                            "type": "Tabs",
                            "title": "Сторінки",
                            "props": {"pages_representation": "TabsOnTop"},
                            "children": [
                                {
                                    "id": "page-1",
                                    "type": "Container",
                                    "title": "Перша",
                                    "props": {"layout": "vertical"},
                                    "children": [
                                        {
                                            "id": "lbl-1",
                                            "type": "Label",
                                            "title": "One",
                                            "props": {},
                                            "children": [],
                                        }
                                    ],
                                },
                                {
                                    "id": "page-2",
                                    "type": "Container",
                                    "title": "Друга",
                                    "props": {"layout": "vertical"},
                                    "children": [
                                        {
                                            "id": "lbl-2",
                                            "type": "Label",
                                            "title": "Two",
                                            "props": {},
                                            "children": [],
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                },
            }
        },
    )
    widget.show()
    app.processEvents()

    surface = getattr(widget, "_design_runtime_surface", None)
    assert surface is not None
    tabs = surface.findChild(QTabWidget)
    assert tabs is not None
    bar = tabs.tabBar()
    assert bar is not None
    assert tabs.currentIndex() == 0

    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(1).center())
    app.processEvents()

    assert tabs.currentIndex() == 1

    widget._render_design_preview()
    app.processEvents()

    refreshed_tabs = widget._design_runtime_surface.findChild(QTabWidget)
    assert refreshed_tabs is not None
    assert refreshed_tabs.currentIndex() == 1


def test_form_designer_tree_rejects_leaf_parent_and_cycles() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload={
            "form_model": {
                "schema_version": 1,
                "id": "f-tree",
                "root": {
                    "id": "root",
                    "type": "Container",
                    "props": {"layout": "vertical"},
                    "children": [
                        {
                            "id": "group",
                            "type": "Container",
                            "props": {"layout": "vertical"},
                            "children": [
                                {"id": "label", "type": "Label", "title": "Text", "children": []},
                            ],
                        },
                        {"id": "field", "type": "TextBox", "children": []},
                    ],
                },
            }
        },
    )
    widget.show()
    app.processEvents()

    assert widget._can_reparent_tree_node("field", "group") is True
    assert widget._can_reparent_tree_node("field", "label") is False
    assert widget._can_reparent_tree_node("group", "label") is False
    assert widget._can_reparent_tree_node("root", "group") is False


def test_form_designer_new_tabs_has_page_and_accepts_more_pages() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload={
            "form_model": {
                "schema_version": 1,
                "id": "f-tabs-new",
                "root": {"id": "root", "type": "Container", "props": {"layout": "vertical"}, "children": []},
            }
        },
    )
    widget.show()
    app.processEvents()

    widget._add_control_at("Tabs", "root", 0, 0)
    tabs = widget._model.root.children[0]
    assert tabs.type == "Tabs"
    assert len(tabs.children) == 1
    assert tabs.children[0].type == "Container"

    widget._add_control_at("Container", tabs.id, 0, 0)

    assert len(tabs.children) == 2
    assert [page.type for page in tabs.children] == ["Container", "Container"]


def test_form_designer_delete_button_removes_selected_node() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    group_item = root_item.child(1)
    assert group_item is not None
    widget.tree.setCurrentItem(group_item)
    app.processEvents()

    before = len(widget._model.root.children)
    widget._btn_delete_node.click()
    app.processEvents()

    assert len(widget._model.root.children) == before - 1
    assert all(node.id != "grp1" for node in widget._model.root.children)
    rebuilt_root = widget.tree.topLevelItem(0)
    assert rebuilt_root is not None
    assert rebuilt_root.childCount() == 2


def test_form_designer_preview_delete_key_removes_selected_node() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    surface = getattr(widget, "_design_runtime_surface", None)
    assert surface is not None
    target = surface.widget_for_node("grp1")
    assert target is not None

    before = len(widget._model.root.children[1].children)
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)

    handled = surface.eventFilter(target, event)
    app.processEvents()

    assert handled is True
    assert len(widget._model.root.children[1].children) == before - 1
    assert all(ch.id != "f_org" for ch in widget._model.root.children[1].children)


def test_form_designer_move_buttons_reorder_selected_node() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    group_item = root_item.child(1)
    assert group_item is not None
    widget.tree.setCurrentItem(group_item)
    app.processEvents()

    before_ids = [child.id for child in widget._model.root.children]
    assert before_ids == ["lbl1", "grp1", "tbl1"]

    widget._btn_move_up.click()
    app.processEvents()

    after_up_ids = [child.id for child in widget._model.root.children]
    assert after_up_ids == ["grp1", "lbl1", "tbl1"]
    assert widget.tree.topLevelItem(0).child(0).data(0, Qt.ItemDataRole.UserRole) == "grp1"

    widget._btn_move_down.click()
    app.processEvents()

    after_down_ids = [child.id for child in widget._model.root.children]
    assert after_down_ids == ["lbl1", "grp1", "tbl1"]


def test_form_designer_tree_reorder_syncs_model_order() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    moved_item = root_item.takeChild(1)
    assert moved_item is not None
    root_item.insertChild(0, moved_item)
    widget.tree.setCurrentItem(moved_item)
    widget.tree.orderChanged.emit()
    app.processEvents()

    assert [child.id for child in widget._model.root.children] == ["grp1", "lbl1", "tbl1"]
    assert widget.tree.topLevelItem(0).child(0).data(0, Qt.ItemDataRole.UserRole) == "grp1"


def test_form_designer_tree_reparent_syncs_model_parent() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    label_item = root_item.takeChild(0)
    assert label_item is not None
    group_item = root_item.child(0)
    assert group_item is not None
    group_item.insertChild(0, label_item)
    widget.tree.setCurrentItem(label_item)
    widget.tree.orderChanged.emit()
    app.processEvents()

    assert [child.id for child in widget._model.root.children] == ["grp1", "tbl1"]
    assert [child.id for child in widget._model.root.children[0].children] == ["lbl1", "f_org"]
    rebuilt_root = widget.tree.topLevelItem(0)
    assert rebuilt_root is not None
    assert rebuilt_root.data(0, Qt.ItemDataRole.UserRole) == "root"
    assert rebuilt_root.child(0).data(0, Qt.ItemDataRole.UserRole) == "grp1"


def test_form_designer_duplicate_button_clones_selected_subtree() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    group_item = root_item.child(1)
    assert group_item is not None
    widget.tree.setCurrentItem(group_item)
    app.processEvents()

    before_ids = [child.id for child in widget._model.root.children]
    assert before_ids == ["lbl1", "grp1", "tbl1"]

    widget._btn_duplicate_node.click()
    app.processEvents()

    after_ids = [child.id for child in widget._model.root.children]
    assert len(after_ids) == 4
    assert after_ids[0] == "lbl1"
    assert after_ids[1] == "grp1"
    assert after_ids[2] != "grp1"
    assert after_ids[2] not in {"lbl1", "tbl1"}
    assert widget._model.root.children[2].type == "Container"
    assert [ch.type for ch in widget._model.root.children[2].children] == ["TextBox"]
    assert widget._model.root.children[2].children[0].binding == "Organization"
    assert widget.tree.currentItem() is not None


def test_form_designer_clipboard_copy_paste_cut_workflow() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    group_item = root_item.child(1)
    assert group_item is not None
    widget.tree.setCurrentItem(group_item)
    app.processEvents()

    widget._copy_selected()
    clipboard = app.clipboard()
    assert clipboard.text() == "Шапка"
    assert getattr(app, "_mp_form_node_clipboard_payload", "")

    widget.tree.setCurrentItem(root_item)
    app.processEvents()
    before = len(widget._model.root.children)
    widget._paste_selected()
    app.processEvents()

    assert len(widget._model.root.children) == before + 1
    pasted = widget._model.root.children[-1]
    assert pasted.id != "grp1"
    assert pasted.type == "Container"
    assert [ch.type for ch in pasted.children] == ["TextBox"]
    assert pasted.children[0].binding == "Organization"

    widget.tree.setCurrentItem(widget.tree.topLevelItem(0).child(widget.tree.topLevelItem(0).childCount() - 1))
    app.processEvents()
    widget._cut_selected()
    app.processEvents()

    assert len(widget._model.root.children) == before
    assert all(child.id != pasted.id for child in widget._model.root.children)


def test_form_designer_tree_context_menu_routes_to_duplicate() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    group_item = root_item.child(1)
    assert group_item is not None
    widget.tree.setCurrentItem(group_item)
    app.processEvents()

    def _pick_duplicate(menu, *_args, **_kwargs):
        for action in menu.actions():
            if str(action.text()) == "Duplicate":
                return action
        return None

    widget._tree_context_menu_exec = _pick_duplicate
    widget._show_tree_context_menu(widget.tree.visualItemRect(group_item).center())
    app.processEvents()

    assert len(widget._model.root.children) == 4
    assert widget._model.root.children[2].type == "Container"


def test_form_designer_preview_context_menu_routes_to_duplicate() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    surface = getattr(widget, "_design_runtime_surface", None)
    assert surface is not None
    group_wrap = widget._design_wrap_by_id.get("grp1")
    assert group_wrap is not None

    def _pick_duplicate(menu, *_args, **_kwargs):
        for action in menu.actions():
            if str(action.text()) == "Duplicate":
                return action
        return None

    surface._designer_context_menu_exec = _pick_duplicate
    local_pos = QPoint(8, 8)
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        local_pos,
        group_wrap.mapToGlobal(local_pos),
    )
    handled = surface.eventFilter(group_wrap, event)
    app.processEvents()

    assert handled is True
    assert len(widget._model.root.children) == 4
    assert widget._model.root.children[2].type == "Container"


def test_form_designer_canvas_context_menu_routes_to_duplicate() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["props"]["layout"] = "absolute"
    payload["form_model"]["root"]["children"][0]["props"] = {"x": 20, "y": 20, "w": 120, "h": 24}
    payload["form_model"]["root"]["children"][1]["props"] = {"layout": "vertical", "x": 30, "y": 60, "w": 240, "h": 120}
    payload["form_model"]["root"]["children"][1]["children"][0]["props"] = {"x": 10, "y": 10, "w": 160, "h": 28}
    payload["form_model"]["root"]["children"][2]["props"] = {"x": 300, "y": 40, "w": 200, "h": 120}
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    item = widget.canvas._item_by_id.get("grp1")
    assert item is not None

    def _pick_duplicate(menu, *_args, **_kwargs):
        for action in menu.actions():
            if str(action.text()) == "Duplicate":
                return action
        return None

    widget.canvas._canvas_context_menu_exec = _pick_duplicate
    center = item.sceneBoundingRect().center()
    local_pos = widget.canvas.mapFromScene(center)
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        local_pos,
        widget.canvas.viewport().mapToGlobal(local_pos),
    )
    widget.canvas.contextMenuEvent(event)
    app.processEvents()

    assert len(widget._model.root.children) == 4
    assert widget._model.root.children[2].type == "Container"


def test_form_designer_canvas_delete_key_removes_selected_node() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["props"]["layout"] = "absolute"
    payload["form_model"]["root"]["children"][0]["props"] = {"x": 20, "y": 20, "w": 120, "h": 24}
    payload["form_model"]["root"]["children"][1]["props"] = {"layout": "vertical", "x": 30, "y": 60, "w": 240, "h": 120}
    payload["form_model"]["root"]["children"][1]["children"][0]["props"] = {"x": 10, "y": 10, "w": 160, "h": 28}
    payload["form_model"]["root"]["children"][2]["props"] = {"x": 300, "y": 40, "w": 200, "h": 120}
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    widget.canvas.select_node("grp1")
    app.processEvents()

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    widget.canvas.keyPressEvent(event)
    app.processEvents()

    assert [child.id for child in widget._model.root.children] == ["lbl1", "tbl1"]


def test_form_designer_canvas_copy_paste_shortcuts_work() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["props"]["layout"] = "absolute"
    payload["form_model"]["root"]["children"][0]["props"] = {"x": 20, "y": 20, "w": 120, "h": 24}
    payload["form_model"]["root"]["children"][1]["props"] = {"layout": "vertical", "x": 30, "y": 60, "w": 240, "h": 120}
    payload["form_model"]["root"]["children"][1]["children"][0]["props"] = {"x": 10, "y": 10, "w": 160, "h": 28}
    payload["form_model"]["root"]["children"][2]["props"] = {"x": 300, "y": 40, "w": 200, "h": 120}
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    widget.canvas.select_node("grp1")
    app.processEvents()

    copy_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_C,
        Qt.KeyboardModifier.ControlModifier,
    )
    widget.canvas.keyPressEvent(copy_event)
    app.processEvents()

    paste_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_V,
        Qt.KeyboardModifier.ControlModifier,
    )
    widget.canvas.keyPressEvent(paste_event)
    app.processEvents()

    assert len(widget._model.root.children[1].children) == 2
    assert widget._model.root.children[1].children[1].type == "Container"
    assert [ch.type for ch in widget._model.root.children[1].children[1].children] == ["TextBox"]


def test_form_designer_canvas_arrow_keys_nudge_selected_node() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["props"]["layout"] = "absolute"
    payload["form_model"]["root"]["children"][0]["props"] = {"x": 20, "y": 20, "w": 120, "h": 24}
    payload["form_model"]["root"]["children"][1]["props"] = {"layout": "vertical", "x": 30, "y": 60, "w": 240, "h": 120}
    payload["form_model"]["root"]["children"][1]["children"][0]["props"] = {"x": 10, "y": 10, "w": 160, "h": 28}
    payload["form_model"]["root"]["children"][2]["props"] = {"x": 300, "y": 40, "w": 200, "h": 120}
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    widget.canvas.select_node("lbl1")
    app.processEvents()

    right_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Right,
        Qt.KeyboardModifier.ShiftModifier,
    )
    widget.canvas.keyPressEvent(right_event)
    app.processEvents()

    assert widget._model.root.children[0].props["x"] == 30
    assert widget._model.root.children[0].props["y"] == 20


def test_form_designer_canvas_tab_cycles_selection() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["props"]["layout"] = "absolute"
    payload["form_model"]["root"]["children"][0]["props"] = {"x": 20, "y": 20, "w": 120, "h": 24}
    payload["form_model"]["root"]["children"][1]["props"] = {"layout": "vertical", "x": 30, "y": 60, "w": 240, "h": 120}
    payload["form_model"]["root"]["children"][1]["children"][0]["props"] = {"x": 10, "y": 10, "w": 160, "h": 28}
    payload["form_model"]["root"]["children"][2]["props"] = {"x": 300, "y": 40, "w": 200, "h": 120}
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    widget.canvas.select_node("lbl1")
    app.processEvents()
    assert widget.canvas.primary_selected_id() == "lbl1"


def test_form_designer_canvas_f2_focuses_property_panel() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["props"]["layout"] = "absolute"
    payload["form_model"]["root"]["children"][0]["props"] = {"x": 20, "y": 20, "w": 120, "h": 24}
    payload["form_model"]["root"]["children"][1]["props"] = {"layout": "vertical", "x": 30, "y": 60, "w": 240, "h": 120}
    payload["form_model"]["root"]["children"][1]["children"][0]["props"] = {"x": 10, "y": 10, "w": 160, "h": 28}
    payload["form_model"]["root"]["children"][2]["props"] = {"x": 300, "y": 40, "w": 200, "h": 120}
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    widget.canvas.select_node("lbl1")
    app.processEvents()

    f2_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_F2,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.canvas.keyPressEvent(f2_event)
    app.processEvents()

    assert widget.properties_widget() is not None
    assert widget._props_widget.isVisible() is True
    assert widget._props_widget.focusProxy() == widget._ed_name

    tab_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Tab,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.canvas.keyPressEvent(tab_event)
    app.processEvents()
    assert widget.canvas.primary_selected_id() == "grp1"

    shift_tab_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Backtab,
        Qt.KeyboardModifier.ShiftModifier,
    )
    widget.canvas.keyPressEvent(shift_tab_event)
    app.processEvents()
    assert widget.canvas.primary_selected_id() == "lbl1"


def test_form_designer_canvas_move_reparents_node_between_containers() -> None:
    app = QApplication.instance() or QApplication([])
    payload = _make_payload()
    payload["form_model"]["root"]["props"]["layout"] = "absolute"
    payload["form_model"]["root"]["children"][0]["props"] = {"x": 20, "y": 20, "w": 120, "h": 24}
    payload["form_model"]["root"]["children"][1]["props"] = {"layout": "absolute", "x": 40, "y": 60, "w": 240, "h": 160}
    payload["form_model"]["root"]["children"][1]["children"][0]["props"] = {"x": 10, "y": 10, "w": 160, "h": 28}
    payload["form_model"]["root"]["children"][2]["props"] = {"x": 340, "y": 60, "w": 240, "h": 160}
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=payload,
    )
    widget.show()
    app.processEvents()

    item = widget.canvas._item_by_id.get("lbl1")
    assert item is not None
    item.setPos(80, 90)
    widget.canvas.request_geometry_sync("lbl1", finalize=True)
    app.processEvents()

    assert [child.id for child in widget._model.root.children] == ["grp1", "tbl1"]
    assert [child.id for child in widget._model.root.children[0].children] == ["f_org", "lbl1"]
    assert widget._model.root.children[0].children[1].props["x"] == 40
    assert widget._model.root.children[0].children[1].props["y"] == 30


def test_form_designer_rebuilds_design_preview_on_table_column_edit_and_preserves_selection() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    original_surface = getattr(widget, "_design_runtime_surface", None)
    assert original_surface is not None

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    table_item = root_item.child(2)
    assert table_item is not None

    widget.tree.setCurrentItem(table_item)
    app.processEvents()

    table_cell = widget._tbl_columns.item(0, 0)
    assert table_cell is not None
    table_cell.setText("Колонка 2")
    app.processEvents()

    rebuilt_surface = getattr(widget, "_design_runtime_surface", None)
    assert rebuilt_surface is not None
    assert rebuilt_surface is not original_surface
    assert widget._current_node() is not None
    assert widget._current_node().id == "tbl1"

    selected_wrap = widget._design_wrap_by_id.get("tbl1")
    assert selected_wrap is not None
    assert "rgba(37, 99, 235, 0.78)" in selected_wrap.styleSheet()


def test_form_designer_property_edit_stays_draft_only_until_explicit_save() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _SaveVmStub()
    widget = FormDesignerWidget(
        vm=vm,
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_externalized_payload(),
    )
    emitted: list[dict] = []
    widget.saveRequested.connect(lambda patch: emitted.append(dict(patch)))
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    label_item = root_item.child(0)
    assert label_item is not None

    widget.tree.setCurrentItem(label_item)
    app.processEvents()

    widget._ed_title.setText("Заголовок чернетки")
    widget._on_prop_changed()
    app.processEvents()

    assert widget._dirty is True
    assert vm.asset_saves == []
    assert vm.patch_saves == []
    assert emitted == []


def test_form_designer_add_field_button_inserts_textbox_control() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    assert widget._btn_add_field.toolTip()
    assert widget._btn_add_field.accessibleName()
    assert not widget._btn_add_field.icon().isNull()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    initial_count = root_item.childCount()

    widget._btn_add_field.click()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    assert root_item.childCount() == initial_count + 1
    new_item = root_item.child(root_item.childCount() - 1)
    assert new_item is not None
    assert "Text" in new_item.text(0)
    assert widget._current_node() is not None
    assert widget._current_node().type == "TextBox"


def test_form_designer_uses_onec_style_split_workbench_layout() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.resize(1100, 720)
    widget.show()
    app.processEvents()

    assert widget._main_splitter.orientation() == Qt.Orientation.Vertical
    assert widget._main_splitter.count() == 2
    assert widget._main_splitter.widget(0) is widget._top_splitter
    assert widget._main_splitter.widget(1) is widget._center_stack
    assert widget._top_splitter.orientation() == Qt.Orientation.Horizontal
    assert widget._top_splitter.count() == 2
    assert widget._top_splitter.widget(0) is widget._left_tabs
    assert widget._top_splitter.widget(1) is widget._object_tabs
    assert widget._props_widget.minimumWidth() <= 280
    assert widget._left_tabs.count() == 2
    assert widget._object_tabs.count() == 3
    assert widget._center_stack.count() == 2
    assert widget._center_stack.tabPosition() == QTabWidget.TabPosition.South
    assert widget._left_tabs.tabText(0) == t("form_tab_elements")
    assert widget._left_tabs.tabText(1) == t("form_tab_command_interface")
    assert widget._center_stack.tabText(0) == t("form_tab_design")
    assert widget._center_stack.tabText(1) == t("form_tab_module")
    assert widget._top_splitter.isVisible()

    widget._center_stack.setCurrentIndex(1)
    app.processEvents()
    assert not widget._top_splitter.isVisible()
    assert not widget._pane_controls.isVisible()

    widget._center_stack.setCurrentIndex(0)
    app.processEvents()
    assert widget._top_splitter.isVisible()
    assert widget._pane_controls.isVisible()
    assert widget._props_widget.parent() is not widget._main_splitter
    assert all(
        not button.icon().isNull()
        for button in (
            widget._btn_add_selected,
            widget._btn_delete_node,
            widget._btn_duplicate_node,
            widget._btn_move_up,
            widget._btn_move_down,
        )
    )
    assert "QTabWidget#FormDesignerCenterTabs QTabBar::tab" in widget.styleSheet()

    widget.properties_widget()
    widget._btn_toggle_props.click()
    app.processEvents()
    assert not widget._props_widget.isVisible()
    assert widget._btn_toggle_props.accessibleName()
    widget._btn_toggle_props.click()
    app.processEvents()
    assert widget._props_widget.isVisible()


def test_form_designer_save_uses_form_model_asset_when_ref_exists() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _SaveVmStub()
    widget = FormDesignerWidget(
        vm=vm,
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_externalized_payload(),
    )
    emitted: list[dict] = []
    widget.saveRequested.connect(lambda patch: emitted.append(dict(patch)))
    widget.show()
    app.processEvents()

    widget._model.root.title = "Changed"
    widget._set_dirty(True)
    widget._save()

    assert vm.asset_saves
    guid, payload, key, reload = vm.asset_saves[-1]
    assert guid == "form-guid"
    assert key == "form_model"
    assert reload is False
    assert payload["form_model_ref"].endswith("form_model.json")
    assert vm.patch_saves == []
    assert emitted == []
    assert widget._dirty is False


def test_form_designer_keeps_dirty_draft_when_form_asset_save_fails() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _SaveVmStub()
    vm.asset_save_result = False
    widget = FormDesignerWidget(
        vm=vm,
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_externalized_payload(),
    )
    widget.show()
    app.processEvents()

    widget._model.root.title = "Unsaved"
    widget._set_dirty(True)

    assert widget.save() is False
    assert widget._dirty is True
    assert vm.asset_saves
    assert vm.patch_saves == []


def test_form_designer_keeps_module_dirty_when_module_patch_fails() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _SaveVmStub()
    vm.patch_save_result = False
    widget = FormDesignerWidget(
        vm=vm,
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_externalized_payload(),
    )
    widget.show()
    app.processEvents()

    widget._module_editor.setPlainText("Процедура НеЗбережено()\nКінецьПроцедури")
    app.processEvents()

    assert widget.save() is False
    assert widget._dirty is True
    assert widget._module_dirty is True
    assert vm.asset_saves
    assert vm.patch_saves


def test_form_designer_save_patches_form_module_without_resending_form_model() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _SaveVmStub()
    widget = FormDesignerWidget(
        vm=vm,
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_externalized_payload(),
    )
    emitted: list[dict] = []
    widget.saveRequested.connect(lambda patch: emitted.append(dict(patch)))
    widget.show()
    app.processEvents()

    widget._module_editor.setPlainText("Процедура Тест()\nКінецьПроцедури")
    app.processEvents()
    widget._save()

    assert vm.asset_saves
    assert vm.patch_saves == [
        (
            "form-guid",
            {"form_module": "Процедура Тест()\nКінецьПроцедури"},
            False,
        )
    ]
    assert emitted == []
    assert widget._module_dirty is False


def test_form_designer_save_triggers_refresh_from_persisted_payload() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _SaveVmStub()
    widget = FormDesignerWidget(
        vm=vm,
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_externalized_payload(),
    )
    widget.show()
    app.processEvents()

    widget._model.root.children[0].title = "Локальна чернетка"
    widget._set_dirty(True)
    widget._save()
    app.processEvents()

    assert widget._dirty is False
    assert "Збережений стан" in widget.tree.topLevelItem(0).child(0).text(0)
    assert "Процедура Збережено()" in widget._module_editor.toPlainText()


def test_form_designer_preview_refresh_timer_debounces() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload={
            "form_model": {
                "schema_version": 1,
                "id": "f1",
                "name": "Form",
                "title": "Form",
                "root": {
                    "id": "root",
                    "type": "Container",
                    "name": "root",
                    "props": {"layout": "absolute", "w": 300, "h": 200},
                    "children": [],
                },
            }
        },
    )
    timer = widget._preview_refresh_timer
    hits: list[int] = []
    timer.timeout.disconnect()
    timer.timeout.connect(lambda: hits.append(1))

    widget._schedule_preview_refresh(75)
    widget._schedule_preview_refresh(75)
    assert timer.isActive()
    QTest.qWait(120)
    app.processEvents()
    assert hits == [1]


def test_form_designer_edits_stay_in_memory_until_save() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _SaveVmStub()
    storage = _StorageStub()
    widget = FormDesignerWidget(
        vm=vm,
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_externalized_payload(),
        storage_service=storage,
        lock_target=FormLockTarget(lock_key="document/owner-guid/FormModule/FormaDokumenta", description="form lock"),
    )
    widget.show()
    app.processEvents()

    widget._module_editor.setPlainText("Процедура НовийТекст()\nКінецьПроцедури")
    app.processEvents()

    assert vm.asset_saves == []
    assert vm.patch_saves == []
    assert storage.commits == []

    widget._save()

    assert vm.asset_saves
    assert vm.patch_saves
    assert len(storage.commits) == 1
    lock_key, snapshot, message, user_id = storage.commits[0]
    assert lock_key == "document/owner-guid/FormModule/FormaDokumenta"
    assert snapshot["payload"]["form_module"] == "Процедура НовийТекст()\nКінецьПроцедури"
    assert message == "Form save"
    assert user_id == "SYSTEM"


def test_form_designer_refresh_discards_dirty_draft_and_reloads_persisted_payload() -> None:
    app = QApplication.instance() or QApplication([])
    persisted_payload = _make_payload()
    vm = _RefreshVmStub(persisted_payload)
    widget = FormDesignerWidget(
        vm=vm,
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=persisted_payload,
    )
    widget.show()
    app.processEvents()

    root_item = widget.tree.topLevelItem(0)
    assert root_item is not None
    label_item = root_item.child(0)
    assert label_item is not None

    widget._model.root.children[0].title = "Локальна чернетка"
    widget._set_dirty(True)
    app.processEvents()

    refreshed_payload = _make_payload()
    refreshed_payload["form_model"]["root"]["children"][0]["title"] = "Збережений стан"
    refreshed_payload["form_module"] = "Процедура Оновити()\nКінецьПроцедури"
    vm.payload = refreshed_payload

    widget._refresh_from_sources()
    app.processEvents()

    assert widget._dirty is False
    assert widget._model.root.children[0].title == "Збережений стан"
    assert widget._module_editor.toPlainText() == "Процедура Оновити()\nКінецьПроцедури"
    refreshed_root_item = widget.tree.topLevelItem(0)
    assert refreshed_root_item is not None
    refreshed_label_item = refreshed_root_item.child(0)
    assert refreshed_label_item is not None
    assert "Збережений стан" in refreshed_label_item.text(0)


def test_form_designer_properties_widget_has_scroll_body_and_pinned_footer() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="ФормаДокумента",
        form_meta_payload=_make_payload(),
    )
    widget.show()
    app.processEvents()

    props = widget.properties_widget()

    assert props is not None
    assert props.findChildren(QScrollArea)
    help_boxes = [item for item in props.findChildren(QPlainTextEdit) if item.objectName() == "FormDesignerPropsHelp"]
    assert help_boxes


def test_form_designer_generates_object_model_from_owner_metadata_when_payload_missing(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    prev_path, prev_lang = _redirect_i18n_settings(tmp_path)
    try:
        widget = FormDesignerWidget(
            vm=_OwnerMetaVm(subtype="object_form"),
            form_guid="form-guid",
            form_title="ФормаДокумента",
            form_meta_payload={"subtype": "object_form"},
        )
        widget.show()
        app.processEvents()

        controls = list(widget._model.root.children)
        bindings = {str(node.binding or "") for node in controls}
        command_bars = [node for node in controls if node.type == "CommandBar"]
        commands = {
            str((node.props or {}).get("command") or "")
            for bar in command_bars
            for node in bar.children
            if node.type == "Button"
        }

        assert "Number" in bindings
        assert "Date" in bindings
        assert len(command_bars) == 1
        assert "Save" in commands
    finally:
        _restore_i18n_settings(prev_path, prev_lang)


def test_form_designer_generates_list_model_from_owner_metadata_when_payload_missing(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    prev_path, prev_lang = _redirect_i18n_settings(tmp_path)
    try:
        widget = FormDesignerWidget(
            vm=_OwnerMetaVm(subtype="list_form"),
            form_guid="form-guid",
            form_title="ФормаСписка",
            form_meta_payload={"subtype": "list_form"},
        )
        widget.show()
        app.processEvents()

        tables = [node for node in widget._model.root.children if node.type == "Table"]
        command_bars = [node for node in widget._model.root.children if node.type == "CommandBar"]
        commands = {
            str((node.props or {}).get("command") or "")
            for bar in command_bars
            for node in bar.children
            if node.type == "Button"
        }

        assert len(tables) == 1
        assert str(tables[0].binding or "") == "items"
        assert len(command_bars) == 1
        assert "Create" in commands
        assert "Refresh" in commands
    finally:
        _restore_i18n_settings(prev_path, prev_lang)


def test_form_runtime_stretch_anchor_does_not_fix_child_width() -> None:
    app = QApplication.instance() or QApplication([])
    model = {
        "schema_version": 1,
        "id": "f1",
        "name": "Form",
        "title": "Form",
        "root": {
            "id": "root",
            "type": "Container",
            "name": "root",
            "props": {"layout": "vertical"},
            "children": [
                {
                    "id": "field1",
                    "type": "TextBox",
                    "name": "Field1",
                    "title": "Поле",
                    "binding": "Field1",
                    "props": {"group_anchor": "stretch"},
                    "children": [],
                }
            ],
        },
    }
    widget = FormRuntimeWidget(
        model=model,
        embedded=True,
        ctx=ObjContext(obj_guid="owner-guid", obj_type="document", obj_name="Doc", form_kind="object_form"),
        manifest_rows=[],
    )
    line_edit = widget.findChild(QLineEdit)
    assert line_edit is not None
    assert line_edit.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert line_edit.maximumWidth() > 1000
    assert app is not None


def test_form_designer_canvas_clamps_absolute_control_to_form_bounds() -> None:
    app = QApplication.instance() or QApplication([])
    model = FormModel.from_dict(
        {
            "schema_version": 1,
            "id": "bounded-form",
            "name": "Form",
            "title": "Form",
            "root": {
                "id": "root",
                "type": "Container",
                "props": {"layout": "absolute", "w": 300, "h": 200},
                "children": [
                    {
                        "id": "field-1",
                        "type": "TextBox",
                        "title": "Field",
                        "props": {"x": 260, "y": 180, "w": 100, "h": 40},
                        "children": [],
                    }
                ],
            },
        }
    )
    canvas = FormDesignerCanvasView()
    canvas.rebuild(model_root=model.root)
    item = canvas._item_by_id["field-1"]

    assert item.pos().x() + item.rect().width() <= 300
    assert item.pos().y() + item.rect().height() <= 200

    committed: list[tuple[str, int, int, int, int]] = []
    canvas.geometryCommitted.connect(lambda *args: committed.append(args))
    item.setPos(290, 195)
    item.setRect(0, 0, 80, 50)
    canvas.request_geometry_sync("field-1", finalize=True)

    assert committed == [("field-1", 220, 150, 80, 50)]
    assert item.pos().x() + item.rect().width() <= 300
    assert item.pos().y() + item.rect().height() <= 200
    assert app is not None


def test_form_designer_form_surface_has_no_outer_horizontal_scroll() -> None:
    app = QApplication.instance() or QApplication([])
    widget = FormDesignerWidget(
        vm=_DummyVm(),
        form_guid="form-guid",
        form_title="Wide form",
        form_meta_payload={
            "form_model": {
                "schema_version": 1,
                "id": "wide-form",
                "name": "Form",
                "title": "Wide form",
                "root": {
                    "id": "root",
                    "type": "Container",
                    "props": {"layout": "vertical", "w": 1000, "h": 700},
                    "children": [
                        {
                            "id": "wide-field",
                            "type": "TextBox",
                            "title": "Wide field",
                            "binding": "WideField",
                            "props": {"width_chars": 200, "title_location": "left"},
                            "children": [],
                        }
                    ],
                },
            }
        },
    )
    widget.resize(780, 640)
    widget.show()
    app.processEvents()

    scroll = widget._design_window_scroll
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert scroll.horizontalScrollBar().maximum() == 0
    assert widget._design_window_frame.width() <= scroll.viewport().width()
    assert widget._design_window_frame.width() >= scroll.viewport().width() - 2


def test_form_designer_absolute_canvas_fits_design_width_into_viewport() -> None:
    app = QApplication.instance() or QApplication([])
    canvas = FormDesignerCanvasView()
    canvas.set_root_size(1000, 400)
    canvas.resize(320, 400)
    canvas.show()
    app.processEvents()

    right_edge = canvas.mapFromScene(QPointF(1000.0, 0.0)).x()
    assert canvas.horizontalScrollBar().maximum() == 0
    assert 0.0 < canvas.transform().m11() < 1.0
    assert right_edge <= canvas.viewport().width()
    assert app is not None
