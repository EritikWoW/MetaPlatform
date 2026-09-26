from __future__ import annotations

from src.configurator.domain.technical_names import technical_object_name

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QListWidgetItem

from src.configurator.persistence.manifest_io import sys_object_folder_guid
from src.ui_qt.i18n import t
from src.ui_qt.viewmodels.configurator_vm import NodeInfo


class DocumentEditorChildrenMixin:
    def _form_selector_value(self, combo: QComboBox) -> str:
        idx = combo.currentIndex()
        if idx >= 0:
            data = combo.itemData(idx)
            if data is not None:
                return str(data)
        return str(combo.currentText() or "").strip()

    def _form_selector_display(self, raw_value: str, fallback_title: str = "") -> str:
        title = str(fallback_title or "").strip()
        if title:
            return title
        raw = str(raw_value or "").strip()
        if not raw:
            return t("enum.common.none")
        return raw.rsplit(".", 1)[-1]

    def _form_reference_value(self, item_info: dict[str, Any]) -> str:
        raw_name = str(item_info.get("name") or "").strip()
        if raw_name and hasattr(self, "_document_metadata_ref"):
            base = str(self._document_metadata_ref() or "").strip()
            if base:
                return f"{base}.Form.{raw_name}"
        return str(item_info.get("guid") or item_info.get("title") or raw_name or "").strip()

    def _sync_default_form_selectors(self, forms: list[dict[str, Any]] | None = None) -> None:
        combos = (
            ("default_object_form", getattr(self, "ed_default_object_form", None)),
            ("default_list_form", getattr(self, "ed_default_list_form", None)),
            ("default_choice_form", getattr(self, "ed_default_choice_form", None)),
        )
        valid_forms = forms if isinstance(forms, list) else []
        for key, combo in combos:
            if not isinstance(combo, QComboBox):
                continue
            current_value = str(getattr(self._model, key, "") or "").strip()
            previous = combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItem(t("enum.common.none"), "")
                known_values: set[str] = {""}
                for item_info in valid_forms:
                    value = self._form_reference_value(item_info)
                    if not value or value in known_values:
                        continue
                    combo.addItem(
                        self._form_selector_display(
                            value,
                            str(item_info.get("title") or item_info.get("name") or "").strip(),
                        ),
                        value,
                    )
                    known_values.add(value)
                if current_value and current_value not in known_values:
                    combo.addItem(self._form_selector_display(current_value), current_value)
                    known_values.add(current_value)
                target = combo.findData(current_value)
                combo.setCurrentIndex(target if target >= 0 else 0)
            finally:
                combo.blockSignals(previous)

    def _on_default_form_changed(self, key: str, combo: QComboBox) -> None:
        self._on_text_changed(key, self._form_selector_value(combo))

    def _find_system_folder_guid(self, name: str) -> str:
        vm = getattr(self, "_vm", None)
        obj_guid = getattr(self, "_obj_guid", "")
        if vm is None or not obj_guid:
            return ""
        target_name = str(name or "").strip().lower()
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
        # Some object sections are projected as deterministic virtual folders
        # even when the manifest does not contain a physical folder row.
        # Returning that GUID keeps editor pages and create-actions aligned
        # with tree navigation for empty/new sections.
        return sys_object_folder_guid(parent_guid=obj_guid, section_key=target_name)

    def _collect_children(self, folder_guid: str, *, types: tuple[str, ...]) -> list[dict]:
        vm = getattr(self, "_vm", None)
        if vm is None or not folder_guid:
            return []
        out: list[dict] = []
        try:
            for obj in vm.list_objects() or []:
                try:
                    if str(getattr(obj, "kind", "")) != "object":
                        continue
                    if str(getattr(obj, "parent_guid", "")) != folder_guid:
                        continue
                    obj_type = str(getattr(obj, "type", "")).strip().lower()
                    if obj_type not in types:
                        continue
                    guid = str(getattr(obj, "guid", "") or "").strip()
                    name = str(getattr(obj, "name", "") or "").strip()
                    title = technical_object_name(name, payload=getattr(obj, "payload", None))
                    out.append({"guid": guid, "name": name, "title": title, "type": obj_type})
                except Exception:
                    continue
        except Exception:
            return []
        out.sort(key=lambda item: (item.get("title") or "").casefold())
        return out

    def _selected_form_guid(self) -> str:
        cur = getattr(self, "lst_forms", None).currentItem() if hasattr(self, "lst_forms") else None
        if cur is None:
            return ""
        return str(cur.data(Qt.ItemDataRole.UserRole) or "").strip()

    def _update_forms_buttons(self) -> None:
        has_vm = self._vm is not None and bool(self._obj_guid)
        has_sel = bool(self._selected_form_guid())
        self.btn_form_new.setEnabled(has_vm)
        self.btn_form_refresh.setEnabled(has_vm)
        self.btn_form_open.setEnabled(has_vm and has_sel)
        self.btn_form_delete.setEnabled(has_vm and has_sel)

    def _refresh_forms_list(self, _checked: bool = False, select_guid: str | None = None) -> None:
        self.lst_forms.clear()
        self.lbl_forms_info.setText("")

        if self._vm is None or not self._obj_guid:
            self._sync_default_form_selectors([])
            self.lbl_forms_info.setText(t("obj.forms_no_vm"))
            self._update_forms_buttons()
            return

        folder = self._find_system_folder_guid("forms")
        if not folder:
            self._sync_default_form_selectors([])
            self.lbl_forms_info.setText(t("obj.forms_missing_folder"))
            self._update_forms_buttons()
            return

        forms = self._collect_children(folder, types=("form", "common_form"))
        self._sync_default_form_selectors(forms)
        if not forms:
            self.lbl_forms_info.setText(t("obj.forms_empty"))
            self._update_forms_buttons()
            return

        target = str(select_guid or "").strip()
        for item_info in forms:
            item = QListWidgetItem(str(item_info.get("title") or item_info.get("guid") or ""))
            item.setData(Qt.ItemDataRole.UserRole, str(item_info.get("guid") or ""))
            self.lst_forms.addItem(item)
            if target and str(item_info.get("guid") or "") == target:
                self.lst_forms.setCurrentItem(item)

        if not target and self.lst_forms.count() > 0:
            self.lst_forms.setCurrentRow(0)

        self.lbl_forms_info.setText(t("obj.forms_count").format(count=self.lst_forms.count()))
        self._update_forms_buttons()

    def _on_create_form(self) -> None:
        if self._vm is None or not self._obj_guid:
            return
        folder = self._find_system_folder_guid("forms")
        if not folder:
            return
        new_guid = self._vm.create_object_quick(
            "form",
            parent_guid=folder,
            title=t("obj.forms_new_default"),
        )
        if new_guid:
            self._refresh_forms_list(select_guid=new_guid)
            self._vm.request_open_new(NodeInfo(kind="object", name="", obj_type="form", guid=new_guid))

    def _on_open_selected_form(self) -> None:
        if self._vm is None:
            return
        guid = self._selected_form_guid()
        if not guid:
            return
        self._vm.on_open(NodeInfo(kind="object", name="", obj_type="form", guid=guid))

    def _on_delete_selected_form(self) -> None:
        if self._vm is None:
            return
        guid = self._selected_form_guid()
        if not guid:
            return
        if self._vm.delete_object(guid):
            self._refresh_forms_list()

    def _selected_command_guid(self) -> str:
        cur = getattr(self, "lst_cmds", None).currentItem() if hasattr(self, "lst_cmds") else None
        if cur is None:
            return ""
        return str(cur.data(Qt.ItemDataRole.UserRole) or "").strip()

    def _update_commands_buttons(self) -> None:
        has_vm = self._vm is not None and bool(self._obj_guid)
        has_sel = bool(self._selected_command_guid())
        self.btn_cmd_new.setEnabled(has_vm)
        self.btn_cmd_refresh.setEnabled(has_vm)
        self.btn_cmd_open.setEnabled(has_vm and has_sel)
        self.btn_cmd_delete.setEnabled(has_vm and has_sel)

    def _refresh_commands_list(
        self,
        _checked: bool = False,
        select_guid: str | None = None,
    ) -> None:
        self.lst_cmds.clear()
        self.lbl_cmds_info.setText("")

        if self._vm is None or not self._obj_guid:
            self.lbl_cmds_info.setText(t("obj.commands_no_vm"))
            self._update_commands_buttons()
            return

        folder = self._find_system_folder_guid("commands")
        if not folder:
            self.lbl_cmds_info.setText(t("obj.commands_missing_folder"))
            self._update_commands_buttons()
            return

        commands = self._collect_children(folder, types=("command", "common_command"))
        if not commands:
            self.lbl_cmds_info.setText(t("obj.commands_empty"))
            self._update_commands_buttons()
            return

        target = str(select_guid or "").strip()
        for item_info in commands:
            item = QListWidgetItem(str(item_info.get("title") or item_info.get("guid") or ""))
            item.setData(Qt.ItemDataRole.UserRole, str(item_info.get("guid") or ""))
            self.lst_cmds.addItem(item)
            if target and str(item_info.get("guid") or "") == target:
                self.lst_cmds.setCurrentItem(item)

        if not target and self.lst_cmds.count() > 0:
            self.lst_cmds.setCurrentRow(0)

        self.lbl_cmds_info.setText(t("obj.commands_count").format(count=self.lst_cmds.count()))
        self._update_commands_buttons()

    def _on_create_command(self) -> None:
        if self._vm is None or not self._obj_guid:
            return
        folder = self._find_system_folder_guid("commands")
        if not folder:
            return
        new_guid = self._vm.create_object_quick(
            "command",
            parent_guid=folder,
            title=t("obj.commands_new_default"),
        )
        if new_guid:
            self._refresh_commands_list(select_guid=new_guid)
            self._vm.request_open_new(
                NodeInfo(kind="object", name="", obj_type="command", guid=new_guid)
            )

    def _on_open_selected_command(self) -> None:
        if self._vm is None:
            return
        guid = self._selected_command_guid()
        if not guid:
            return
        self._vm.on_open(NodeInfo(kind="object", name="", obj_type="command", guid=guid))

    def _on_delete_selected_command(self) -> None:
        if self._vm is None:
            return
        guid = self._selected_command_guid()
        if not guid:
            return
        if self._vm.delete_object(guid):
            self._refresh_commands_list()

    def _selected_layout_guid(self) -> str:
        cur = getattr(self, "lst_layouts", None).currentItem() if hasattr(self, "lst_layouts") else None
        if cur is None:
            return ""
        return str(cur.data(Qt.ItemDataRole.UserRole) or "").strip()

    def _update_layouts_buttons(self) -> None:
        has_vm = self._vm is not None and bool(self._obj_guid)
        has_sel = bool(self._selected_layout_guid())
        self.btn_layout_new.setEnabled(has_vm)
        self.btn_layout_refresh.setEnabled(has_vm)
        self.btn_layout_open.setEnabled(has_vm and has_sel)
        self.btn_layout_delete.setEnabled(has_vm and has_sel)

    def _refresh_layouts_list(
        self,
        _checked: bool = False,
        select_guid: str | None = None,
    ) -> None:
        self.lst_layouts.clear()
        self.lbl_layouts_info.setText("")

        if self._vm is None or not self._obj_guid:
            self.lbl_layouts_info.setText(t("obj.layouts_no_vm"))
            self._update_layouts_buttons()
            return

        folder = self._find_system_folder_guid("layouts")
        if not folder:
            self.lbl_layouts_info.setText(t("obj.layouts_missing_folder"))
            self._update_layouts_buttons()
            return

        layouts = self._collect_children(folder, types=("layout", "common_layout"))
        if not layouts:
            self.lbl_layouts_info.setText(t("obj.layouts_empty"))
            self._update_layouts_buttons()
            return

        target = str(select_guid or "").strip()
        for item_info in layouts:
            item = QListWidgetItem(str(item_info.get("title") or item_info.get("guid") or ""))
            item.setData(Qt.ItemDataRole.UserRole, str(item_info.get("guid") or ""))
            self.lst_layouts.addItem(item)
            if target and str(item_info.get("guid") or "") == target:
                self.lst_layouts.setCurrentItem(item)

        if not target and self.lst_layouts.count() > 0:
            self.lst_layouts.setCurrentRow(0)

        self.lbl_layouts_info.setText(
            t("obj.layouts_count").format(count=self.lst_layouts.count())
        )
        self._update_layouts_buttons()

    def _on_create_layout(self) -> None:
        if self._vm is None or not self._obj_guid:
            return
        folder = self._find_system_folder_guid("layouts")
        if not folder:
            return
        new_guid = self._vm.create_object_quick(
            "layout",
            parent_guid=folder,
            title=t("obj.layouts_new_default"),
        )
        if new_guid:
            self._refresh_layouts_list(select_guid=new_guid)
            self._vm.request_open_new(
                NodeInfo(kind="object", name="", obj_type="layout", guid=new_guid)
            )

    def _on_open_selected_layout(self) -> None:
        if self._vm is None:
            return
        guid = self._selected_layout_guid()
        if not guid:
            return
        self._vm.on_open(NodeInfo(kind="object", name="", obj_type="layout", guid=guid))

    def _on_delete_selected_layout(self) -> None:
        if self._vm is None:
            return
        guid = self._selected_layout_guid()
        if not guid:
            return
        if self._vm.delete_object(guid):
            self._refresh_layouts_list()
