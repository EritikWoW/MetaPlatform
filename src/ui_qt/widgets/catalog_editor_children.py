from __future__ import annotations

from src.configurator.domain.technical_names import technical_object_name

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t
from src.ui_qt.viewmodels.configurator_vm import NodeInfo


_CHILD_SPECS: dict[str, dict[str, Any]] = {
    "forms": {
        "prefix": "form",
        "folder_name": "forms",
        "types": ("form", "common_form"),
        "default_obj_type": "form",
        "create_type": "form",
        "hint_key": "obj.forms_hint",
        "new_key": "obj.forms_new",
        "open_key": "obj.forms_open",
        "delete_key": "obj.forms_delete",
        "refresh_key": "obj.forms_refresh",
        "no_vm_key": "obj.forms_no_vm",
        "missing_folder_key": "obj.forms_missing_folder",
        "empty_key": "obj.forms_empty",
        "count_key": "obj.forms_count",
    },
    "commands": {
        "prefix": "cmd",
        "folder_name": "commands",
        "types": ("command", "common_command"),
        "default_obj_type": "command",
        "create_type": "command",
        "hint_key": "obj.commands_hint",
        "new_key": "obj.commands_new",
        "open_key": "obj.commands_open",
        "delete_key": "obj.commands_delete",
        "refresh_key": "obj.commands_refresh",
        "no_vm_key": "obj.commands_no_vm",
        "missing_folder_key": "obj.commands_missing_folder",
        "empty_key": "obj.commands_empty",
        "count_key": "obj.commands_count",
    },
    "layouts": {
        "prefix": "layout",
        "folder_name": "layouts",
        "types": ("layout", "common_layout"),
        "default_obj_type": "layout",
        "create_type": "layout",
        "hint_key": "obj.layouts_hint",
        "new_key": "obj.layouts_new",
        "open_key": "obj.layouts_open",
        "delete_key": "obj.layouts_delete",
        "refresh_key": "obj.layouts_refresh",
        "no_vm_key": "obj.layouts_no_vm",
        "missing_folder_key": "obj.layouts_missing_folder",
        "empty_key": "obj.layouts_empty",
        "count_key": "obj.layouts_count",
    },
}


class CatalogEditorChildrenMixin:
    def _child_spec(self, section: str) -> dict[str, Any]:
        return _CHILD_SPECS[section]

    def _list_widget_name(self, section: str) -> str:
        return f"lst_{section}"

    def _info_label_name(self, section: str) -> str:
        return f"lbl_{section}_info"

    def _button_name(self, section: str, action: str) -> str:
        prefix = str(self._child_spec(section)["prefix"])
        return f"btn_{prefix}_{action}"

    def _build_child_page(self, section: str) -> QWidget:
        spec = self._child_spec(section)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        hint = QLabel(t(spec["hint_key"]))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        btn_new = QPushButton(t(spec["new_key"]))
        btn_open = QPushButton(t(spec["open_key"]))
        btn_delete = QPushButton(t(spec["delete_key"]))
        btn_refresh = QPushButton(t(spec["refresh_key"]))

        setattr(self, self._button_name(section, "new"), btn_new)
        setattr(self, self._button_name(section, "open"), btn_open)
        setattr(self, self._button_name(section, "delete"), btn_delete)
        setattr(self, self._button_name(section, "refresh"), btn_refresh)

        bar.addWidget(btn_new)
        bar.addWidget(btn_open)
        bar.addWidget(btn_delete)
        bar.addStretch(1)
        bar.addWidget(btn_refresh)
        layout.addLayout(bar)

        list_widget = QListWidget()
        list_widget.setObjectName(f"meta{section.capitalize()}List")
        setattr(self, self._list_widget_name(section), list_widget)
        layout.addWidget(list_widget, 1)

        info = QLabel("")
        info.setWordWrap(True)
        info.setObjectName("metaHint")
        setattr(self, self._info_label_name(section), info)
        layout.addWidget(info)

        btn_new.clicked.connect(lambda _checked=False, s=section: self._on_create_child(s))
        btn_open.clicked.connect(lambda _checked=False, s=section: self._on_open_selected_child(s))
        btn_delete.clicked.connect(lambda _checked=False, s=section: self._on_delete_selected_child(s))
        btn_refresh.clicked.connect(lambda _checked=False, s=section: self._refresh_child_list(s))
        list_widget.itemDoubleClicked.connect(lambda _it, s=section: self._on_open_selected_child(s))
        list_widget.currentItemChanged.connect(lambda *_args, s=section: self._update_child_buttons(s))

        def _load_section_once(s: str = section, page: QWidget = widget) -> None:
            if bool(getattr(page, "_mp_section_loaded", False)):
                return
            self._refresh_child_list(s)

        setattr(widget, "_on_section_shown", _load_section_once)
        return widget

    def _find_child_folder_guid(self, section: str) -> str:
        vm = getattr(self, "_vm", None)
        obj_guid = getattr(self, "_obj_guid", "")
        if vm is None or not obj_guid:
            return ""
        target_name = str(self._child_spec(section)["folder_name"]).strip().lower()
        try:
            for obj in vm.list_objects() or []:
                try:
                    if str(getattr(obj, "kind", "")) != "folder":
                        continue
                    if str(getattr(obj, "parent_guid", "")) != obj_guid:
                        continue
                    if str(getattr(obj, "name", "")).strip().lower() != target_name:
                        continue
                    payload = getattr(obj, "payload", None)
                    if isinstance(payload, dict) and payload.get("system"):
                        return str(getattr(obj, "guid", "") or "").strip()
                except Exception:
                    continue
        except Exception:
            return ""
        return ""

    def _collect_children(self, section: str, folder_guid: str) -> list[dict[str, str]]:
        vm = getattr(self, "_vm", None)
        if vm is None or not folder_guid:
            return []
        out: list[dict[str, str]] = []
        allowed = tuple(str(value).lower() for value in self._child_spec(section)["types"])
        try:
            for obj in vm.list_objects() or []:
                try:
                    if str(getattr(obj, "kind", "")) != "object":
                        continue
                    if str(getattr(obj, "parent_guid", "")) != folder_guid:
                        continue
                    obj_type = str(getattr(obj, "type", "")).strip().lower()
                    if obj_type not in allowed:
                        continue
                    guid = str(getattr(obj, "guid", "") or "").strip()
                    title = technical_object_name(getattr(obj, "name", ""), payload=getattr(obj, "payload", None))
                    out.append({"guid": guid, "title": title, "type": obj_type})
                except Exception:
                    continue
        except Exception:
            return []
        out.sort(key=lambda item: (item.get("title") or "").casefold())
        return out

    def _selected_child_guid(self, section: str) -> str:
        widget = getattr(self, self._list_widget_name(section), None)
        if not isinstance(widget, QListWidget):
            return ""
        current = widget.currentItem()
        if current is None:
            return ""
        return str(current.data(Qt.ItemDataRole.UserRole) or "").strip()

    def _update_child_buttons(self, section: str) -> None:
        has_vm = getattr(self, "_vm", None) is not None and bool(getattr(self, "_obj_guid", ""))
        has_sel = bool(self._selected_child_guid(section))
        getattr(self, self._button_name(section, "new")).setEnabled(has_vm)
        getattr(self, self._button_name(section, "refresh")).setEnabled(has_vm)
        getattr(self, self._button_name(section, "open")).setEnabled(has_vm and has_sel)
        getattr(self, self._button_name(section, "delete")).setEnabled(has_vm and has_sel)

    def _refresh_child_list(
        self,
        section: str,
        _checked: bool = False,
        select_guid: str | None = None,
    ) -> None:
        list_widget = getattr(self, self._list_widget_name(section), None)
        info_label = getattr(self, self._info_label_name(section), None)
        if not isinstance(list_widget, QListWidget) or not isinstance(info_label, QLabel):
            return

        vm = getattr(self, "_vm", None)
        obj_guid = getattr(self, "_obj_guid", "")
        spec = self._child_spec(section)

        list_widget.clear()
        info_label.setText("")

        if vm is None or not obj_guid:
            info_label.setText(t(spec["no_vm_key"]))
            self._update_child_buttons(section)
            return

        folder_guid = self._find_child_folder_guid(section)
        if not folder_guid:
            info_label.setText(t(spec["missing_folder_key"]))
            self._update_child_buttons(section)
            return

        items = self._collect_children(section, folder_guid)
        if not items:
            info_label.setText(t(spec["empty_key"]))
            self._update_child_buttons(section)
            return

        target = str(select_guid or "").strip()
        for item_info in items:
            item = QListWidgetItem(str(item_info.get("title") or item_info.get("guid") or ""))
            item.setData(Qt.ItemDataRole.UserRole, str(item_info.get("guid") or ""))
            list_widget.addItem(item)
            if target and str(item_info.get("guid") or "") == target:
                list_widget.setCurrentItem(item)

        if not target and list_widget.count() > 0:
            list_widget.setCurrentRow(0)

        info_label.setText(t(spec["count_key"]).format(count=list_widget.count()))
        self._update_child_buttons(section)

    def _open_child_by_guid(self, section: str, guid: str, *, new_tab: bool = False) -> None:
        vm = getattr(self, "_vm", None)
        if vm is None:
            return
        guid = str(guid or "").strip()
        if not guid:
            return
        meta = vm.get_meta_by_guid(guid)
        if not isinstance(meta, dict):
            return
        title = technical_object_name(meta.get("name"), payload=meta.get("payload"))
        obj_type = str(meta.get("type") or self._child_spec(section)["default_obj_type"]).strip()
        info = NodeInfo(kind="object", name=title, guid=guid, obj_type=obj_type)
        if new_tab:
            vm.request_open_new(info)
        else:
            vm.on_open(info)

    def _on_create_child(self, section: str, _checked: bool = False) -> None:
        vm = getattr(self, "_vm", None)
        obj_guid = getattr(self, "_obj_guid", "")
        if vm is None or not obj_guid:
            return
        folder_guid = self._find_child_folder_guid(section)
        if not folder_guid:
            self._refresh_child_list(section)
            return

        try:
            guid = vm.create_object_quick(str(self._child_spec(section)["create_type"]), folder_guid, None)
        except Exception:
            guid = ""

        if guid:
            self._refresh_child_list(section, select_guid=guid)
            self._open_child_by_guid(section, guid, new_tab=True)
        else:
            self._refresh_child_list(section)

    def _on_open_selected_child(self, section: str, _checked: bool = False) -> None:
        guid = self._selected_child_guid(section)
        if not guid:
            return
        self._open_child_by_guid(section, guid, new_tab=False)

    def _on_delete_selected_child(self, section: str, _checked: bool = False) -> None:
        vm = getattr(self, "_vm", None)
        if vm is None:
            return
        guid = self._selected_child_guid(section)
        if not guid:
            return
        meta = vm.get_meta_by_guid(guid)
        if not isinstance(meta, dict):
            return
        if vm.delete_object(meta):
            self._refresh_child_list(section)

    def _build_forms_page(self) -> QWidget:
        return self._build_child_page("forms")

    def _refresh_forms_list(self, _checked: bool = False, select_guid: str | None = None) -> None:
        self._refresh_child_list("forms", _checked, select_guid)

    def _on_create_form(self, _checked: bool = False) -> None:
        self._on_create_child("forms", _checked)

    def _on_open_selected_form(self, _checked: bool = False) -> None:
        self._on_open_selected_child("forms", _checked)

    def _on_delete_selected_form(self, _checked: bool = False) -> None:
        self._on_delete_selected_child("forms", _checked)

    def _build_commands_page(self) -> QWidget:
        return self._build_child_page("commands")

    def _refresh_commands_list(self, _checked: bool = False, select_guid: str | None = None) -> None:
        self._refresh_child_list("commands", _checked, select_guid)

    def _on_create_command(self, _checked: bool = False) -> None:
        self._on_create_child("commands", _checked)

    def _on_open_selected_command(self, _checked: bool = False) -> None:
        self._on_open_selected_child("commands", _checked)

    def _on_delete_selected_command(self, _checked: bool = False) -> None:
        self._on_delete_selected_child("commands", _checked)

    def _build_layouts_page(self) -> QWidget:
        return self._build_child_page("layouts")

    def _refresh_layouts_list(self, _checked: bool = False, select_guid: str | None = None) -> None:
        self._refresh_child_list("layouts", _checked, select_guid)

    def _on_create_layout(self, _checked: bool = False) -> None:
        self._on_create_child("layouts", _checked)

    def _on_open_selected_layout(self, _checked: bool = False) -> None:
        self._on_open_selected_child("layouts", _checked)

    def _on_delete_selected_layout(self, _checked: bool = False) -> None:
        self._on_delete_selected_child("layouts", _checked)


__all__ = ["CatalogEditorChildrenMixin"]
