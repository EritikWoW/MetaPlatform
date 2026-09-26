from __future__ import annotations

from typing import Any

from src.ui_qt.services.object_editor_profiles import build_editor_sections
from src.ui_qt.viewmodels.configurator_vm import ConfiguratorViewModel

from .catalog_editor_children import CatalogEditorChildrenMixin
from .catalog_editor_pages import CatalogEditorPagesMixin
from .catalog_editor_payload import CatalogPayload
from .meta_object_editor_base import MetaObjectEditorBase


class CatalogEditorWidget(
    CatalogEditorChildrenMixin,
    CatalogEditorPagesMixin,
    MetaObjectEditorBase,
):
    """Catalog metadata editor."""

    def __init__(
        self,
        title: str,
        payload: dict | None = None,
        *,
        obj_type: str = "catalog",
        available_subsystems: list[dict] | None = None,
        vm: ConfiguratorViewModel | None = None,
        obj_guid: str = "",
    ) -> None:
        super().__init__(
            title=title,
            payload=payload,
            available_subsystems=available_subsystems,
            vm=vm,
            obj_guid=obj_guid,
            obj_type=obj_type,
        )

    def _rebuild_model_from_payload(self, payload: dict) -> None:
        self._model = CatalogPayload.from_payload(payload)

    def _build_sections(self) -> None:
        self._w_main = self._build_main_page()
        self._w_subsystems = self._build_subsystems_page()
        self._w_data = self._build_data_page()
        self._w_attributes = self._build_attributes_page()
        self._w_tabular_parts = self._build_tabular_parts_page()
        self._w_forms = self._build_forms_page()
        self._w_commands = self._build_commands_page()
        self._w_layouts = self._build_layouts_page()
        self._w_modules = self._build_modules_page()

        self._shell.set_sections(
            build_editor_sections(
                self._obj_type,
                {
                    "main": lambda: self._w_main,
                    "subsystems": lambda: self._w_subsystems,
                    "data": lambda: self._w_data,
                    "attributes": lambda: self._w_attributes,
                    "tabular_parts": lambda: self._w_tabular_parts,
                    "modules": lambda: self._w_modules,
                    "forms": lambda: self._w_forms,
                    "commands": lambda: self._w_commands,
                    "layouts": lambda: self._w_layouts,
                },
            )
        )

    def set_current_section(self, key: str) -> None:
        self._shell.set_current_section(key)

    def _load_to_ui(self) -> None:
        model = self._model
        self.ed_name.setText(model.name)
        self.ed_synonym.setText(model.synonym)
        self.ed_comment.setText(model.comment)
        self.ed_hint.setPlainText(model.hint)

        self.sp_code_len.setValue(int(model.code_length))
        self.sp_name_len.setValue(int(model.name_length))
        idx = self.cb_code_type.findData(model.code_type)
        self.cb_code_type.setCurrentIndex(idx if idx >= 0 else 0)

        if hasattr(self, "lst_subsystems"):
            self._loading_subsystems = True
            try:
                self._rebuild_subsystems_list()
            finally:
                self._loading_subsystems = False

        for _section in ("forms", "commands", "layouts"):
            if hasattr(self, f"lst_{_section}"):
                self._refresh_child_list(_section)

    def _on_text_changed(self, key: str, value: str) -> None:
        self._shell.set_pending_patch({key: str(value)})

    def _on_value_changed(self, key: str, value: Any) -> None:
        self._shell.set_pending_patch({key: value})


__all__ = ["CatalogEditorWidget"]
