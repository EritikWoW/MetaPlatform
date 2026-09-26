from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget, QPushButton,
)

from src.ui_qt.i18n import t
from src.ui_qt.services.object_editor_profiles import build_editor_sections
from src.ui_qt.viewmodels.configurator_vm import ConfiguratorViewModel

from .document_editor_children import DocumentEditorChildrenMixin
from .document_editor_pages import DocumentEditorPagesMixin
from .document_editor_payload import (
    DocumentPayload,
    _display_metadata_ref,
    _localized_enum_label,
    _localized_text,
    _localized_right_name,
    _load_document_payload_from_workspace,
    _load_document_workspace_links,
    _load_document_workspace_roles,
    _merge_missing_payload_fields,
    _normalize_exchange_plan_items,
    _normalize_string_list,
)
from .document_editor_schema import (
    DocumentEditorSchemaMixin,
    _DocumentSchemaPropertiesWidget,
    _ReferenceTargetDialog,
)
from .meta_object_editor_base import MetaObjectEditorBase
from src.configurator.domain.posting_constructor import generate_posting_handler
from src.configurator.domain.technical_names import technical_object_name


_RIGHTS_DISPLAY_ORDER = (
    "Read",
    "Insert",
    "Update",
    "Delete",
    "Posting",
    "UndoPosting",
    "View",
    "InteractiveInsert",
    "Edit",
    "InteractiveSetDeletionMark",
    "InteractiveClearDeletionMark",
    "InteractivePosting",
)


class _InputByStringFieldDialog(QDialog):
    def __init__(
        self,
        *,
        fields: list[tuple[str, str]],
        current_value: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("doc.input_by_string_dialog_title"))
        self.resize(560, 420)
        self._selected_value = str(current_value or "").strip()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        hint = QLabel(t("doc.input_by_string_dialog_hint"), self)
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.lst_fields = QListWidget(self)
        for label, value in fields:
            item = QListWidgetItem(str(label or value), self.lst_fields)
            item.setData(Qt.ItemDataRole.UserRole, str(value or "").strip())
            if str(value or "").strip() == self._selected_value:
                self.lst_fields.setCurrentItem(item)
        root.addWidget(self.lst_fields, 1)

        self.bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        root.addWidget(self.bb)

        self.lst_fields.itemDoubleClicked.connect(lambda *_args: self._accept_current())
        self.lst_fields.currentItemChanged.connect(lambda *_args: self._update_ok_enabled())
        self.bb.accepted.connect(self._accept_current)
        self.bb.rejected.connect(self.reject)
        self._update_ok_enabled()

    def selected_value(self) -> str:
        return self._selected_value

    def _update_ok_enabled(self) -> None:
        current = self.lst_fields.currentItem()
        value = str(current.data(Qt.ItemDataRole.UserRole) or "").strip() if current is not None else ""
        self.bb.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(value))

    def _accept_current(self) -> None:
        current = self.lst_fields.currentItem()
        if current is None:
            return
        value = str(current.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not value:
            return
        self._selected_value = value
        self.accept()


class _ValueListDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        hint: str,
        values: list[tuple[str, str]],
        current_values: list[str] | None = None,
        multi_select: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 420)
        self._multi_select = bool(multi_select)
        self._labels_by_value = {
            str(value or "").strip(): str(label or value).strip()
            for label, value in values
            if str(value or "").strip()
        }
        self._selected_values: list[str] = []
        for raw in current_values or []:
            value = str(raw or "").strip()
            if value and value not in self._selected_values:
                self._selected_values.append(value)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        hint_label = QLabel(hint, self)
        hint_label.setWordWrap(True)
        root.addWidget(hint_label)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        self.lst_available = QListWidget(self)
        self.lst_selected = QListWidget(self)
        body.addWidget(self.lst_available, 1)

        controls = QVBoxLayout()
        controls.setSpacing(8)
        controls.addStretch(1)
        self.btn_add = QPushButton(">")
        self.btn_remove = QPushButton("<")
        controls.addWidget(self.btn_add)
        controls.addWidget(self.btn_remove)
        controls.addStretch(1)
        body.addLayout(controls)

        body.addWidget(self.lst_selected, 1)

        self.bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        root.addWidget(self.bb)

        self.btn_add.clicked.connect(self._add_current)
        self.btn_remove.clicked.connect(self._remove_current)
        self.lst_available.itemDoubleClicked.connect(lambda *_args: self._add_current())
        self.lst_selected.itemDoubleClicked.connect(lambda *_args: self._remove_current())
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)

        self._rebuild_lists()

    def selected_values(self) -> list[str]:
        return list(self._selected_values)

    def _rebuild_lists(self) -> None:
        self.lst_available.clear()
        self.lst_selected.clear()
        selected_set = {value.casefold() for value in self._selected_values}
        available_items = sorted(
            (
                (label, value)
                for value, label in self._labels_by_value.items()
                if value.casefold() not in selected_set
            ),
            key=lambda item: item[0].casefold(),
        )
        for label, value in available_items:
            item = QListWidgetItem(label, self.lst_available)
            item.setData(Qt.ItemDataRole.UserRole, value)
        for value in self._selected_values:
            label = self._labels_by_value.get(value, value)
            item = QListWidgetItem(label, self.lst_selected)
            item.setData(Qt.ItemDataRole.UserRole, value)

    def _add_current(self) -> None:
        current = self.lst_available.currentItem()
        if current is None:
            return
        value = str(current.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not value:
            return
        if self._multi_select:
            if value not in self._selected_values:
                self._selected_values.append(value)
        else:
            self._selected_values = [value]
        self._rebuild_lists()

    def _remove_current(self) -> None:
        current = self.lst_selected.currentItem()
        if current is None:
            return
        value = str(current.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not value:
            return
        self._selected_values = [item for item in self._selected_values if item != value]
        self._rebuild_lists()


class DocumentEditorWidget(
    DocumentEditorChildrenMixin,
    DocumentEditorSchemaMixin,
    DocumentEditorPagesMixin,
    MetaObjectEditorBase,
):
    """Document metadata editor."""

    postingModuleRequested = Signal(str)

    def __init__(
        self,
        title: str,
        payload: dict | None = None,
        *,
        available_subsystems: list[dict] | None = None,
        vm: ConfiguratorViewModel | None = None,
        obj_guid: str = "",
    ) -> None:
        raw_payload = dict(payload or {}) if isinstance(payload, dict) else {}
        if title and not str(raw_payload.get("name") or "").strip():
            raw_payload["name"] = str(title)
        imported = (
            raw_payload.get("imported")
            if isinstance(raw_payload.get("imported"), dict)
            else {}
        )
        origin = str(imported.get("origin") or "").strip()
        if origin:
            raw_payload = _merge_missing_payload_fields(
                raw_payload,
                _load_document_payload_from_workspace(origin),
            )

        self._schema_props = _DocumentSchemaPropertiesWidget()
        self._schema_props.itemFieldChanged.connect(self._on_schema_field_changed)
        self._schema_selection: dict[str, Any] | None = None

        super().__init__(
            title=title,
            payload=raw_payload,
            available_subsystems=available_subsystems,
            vm=vm,
            obj_guid=obj_guid,
            obj_type="document",
        )
        self._schema_props.set_reference_targets(self._collect_reference_targets())

    def _rebuild_model_from_payload(self, payload: dict) -> None:
        self._model = DocumentPayload.from_payload(payload)

    def reload_from_vm(self) -> None:
        if self._vm is None or not self._obj_guid:
            return
        raw_payload: dict[str, Any] = {}
        try:
            meta = self._vm.get_meta_by_guid(self._obj_guid)
        except Exception:
            meta = None
        if isinstance(meta, dict):
            payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
            raw_payload = dict(payload or {})
        if not raw_payload:
            return
        if self._model is not None and str(self._model.name or "").strip() and not str(raw_payload.get("name") or "").strip():
            raw_payload["name"] = str(self._model.name or "")
        imported = raw_payload.get("imported") if isinstance(raw_payload.get("imported"), dict) else {}
        origin = str(imported.get("origin") or "").strip()
        if origin:
            raw_payload = _merge_missing_payload_fields(
                raw_payload,
                _load_document_payload_from_workspace(origin),
            )
        self._payload_raw = raw_payload
        self._rebuild_model_from_payload(raw_payload)
        self._schema_props.set_reference_targets(self._collect_reference_targets())
        try:
            self._load_to_ui()
        except Exception:
            pass

    def _build_sections(self) -> None:
        self._w_main = self._build_main_page()
        self._w_subsystems = self._build_subsystems_page()
        self._w_functional_options = self._build_functional_options_page()
        self._w_data = self._build_data_page()
        self._w_numbering = self._build_numbering_page()
        self._w_movements = self._build_movements_page()
        self._w_sequences = self._build_sequences_page()
        self._w_journals = self._build_journals_page()
        self._w_forms = self._build_forms_page()
        self._w_input_by_string = self._build_input_by_string_page()
        self._w_commands = self._build_commands_page()
        self._w_layouts = self._build_layouts_page()
        self._w_based_on = self._build_based_on_page()
        self._w_rights = self._build_rights_page()
        self._w_exchange = self._build_exchange_page()
        self._w_other = self._build_other_page()

        self._shell.set_sections(
            build_editor_sections(
                "document",
                {
                    "main": lambda: self._w_main,
                    "subsystems": lambda: self._w_subsystems,
                    "functional_options": lambda: self._w_functional_options,
                    "data": lambda: self._w_data,
                    "numbering": lambda: self._w_numbering,
                    "movements": lambda: self._w_movements,
                    "sequences": lambda: self._w_sequences,
                    "journals": lambda: self._w_journals,
                    "forms": lambda: self._w_forms,
                    "input_by_string": lambda: self._w_input_by_string,
                    "commands": lambda: self._w_commands,
                    "layouts": lambda: self._w_layouts,
                    "based_on": lambda: self._w_based_on,
                    "rights": lambda: self._w_rights,
                    "exchange": lambda: self._w_exchange,
                    "other": lambda: self._w_other,
                },
            )
        )
        self._shell._sections.currentRowChanged.connect(self._on_shell_section_changed)

    def properties_widget(self) -> QWidget | None:
        return self._schema_props

    def _set_combo_data(self, combo: QComboBox, value: str, default: str = "") -> None:
        target = str(value or default or "").strip().lower()
        idx = combo.findData(target)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _fill_list_widget(self, widget: QListWidget, values: list[str]) -> None:
        widget.clear()
        for value in values:
            item = QListWidgetItem(_display_metadata_ref(value, vm=self._vm))
            item.setData(Qt.ItemDataRole.UserRole, str(value or "").strip())
            widget.addItem(item)

    def _fill_checkable_list_widget(
        self,
        widget: QListWidget,
        values: list[str],
        selected: list[str],
    ) -> None:
        selected_map = {
            str(item or "").strip().casefold()
            for item in selected
            if str(item or "").strip()
        }
        widget.blockSignals(True)
        widget.clear()
        for value in values:
            raw = str(value or "").strip()
            if not raw:
                continue
            item = QListWidgetItem(_display_metadata_ref(raw, vm=self._vm))
            item.setData(Qt.ItemDataRole.UserRole, raw)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(
                Qt.CheckState.Checked
                if raw.casefold() in selected_map
                else Qt.CheckState.Unchecked
            )
            widget.addItem(item)
        widget.blockSignals(False)

    def _checked_values_from_list_widget(self, widget: QListWidget) -> list[str]:
        out: list[str] = []
        for i in range(widget.count()):
            item = widget.item(i)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            value = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if value and value not in out:
                out.append(value)
        return out

    def _reload_register_records_tree(self) -> None:
        tree = getattr(self, "tree_register_records", None)
        if not isinstance(tree, QTreeWidget):
            return
        selected = {
            str(item or "").strip()
            for item in (self._model.register_records or [])
            if str(item or "").strip()
        }
        group_specs = [
            ("InformationRegister", "register_info", t("group.register_info")),
            ("AccumulationRegister", "register_accum", t("group.register_accum")),
            ("AccountingRegister", "register_accounting", t("group.register_accounting")),
            ("CalculationRegister", "register_calc", t("group.register_calc")),
        ]
        by_group: dict[str, list[tuple[str, str]]] = {key: [] for key, _typ, _title in group_specs}
        seen: set[str] = set()
        if self._vm is not None:
            try:
                prefix_by_type = {
                    "register_info": "InformationRegister",
                    "register_accum": "AccumulationRegister",
                    "register_accounting": "AccountingRegister",
                    "register_calc": "CalculationRegister",
                }
                for obj in self._vm.list_objects() or []:
                    if str(getattr(obj, "kind", "") or "").strip().lower() != "object":
                        continue
                    obj_type = str(getattr(obj, "type", "") or "").strip().lower()
                    prefix = prefix_by_type.get(obj_type)
                    if not prefix:
                        continue
                    payload = obj.payload if isinstance(getattr(obj, "payload", None), dict) else {}
                    name = technical_object_name(getattr(obj, "name", ""), payload=payload)
                    if not name:
                        continue
                    ref_value = str(payload.get("metadata_ref") or f"{prefix}.{name}")
                    aliases = {ref_value.casefold(), f"{prefix}.{name}".casefold(),
                               f"{prefix}.{getattr(obj, 'name', '')}".casefold()}
                    # Retain the stored reference rather than duplicating an imported
                    # register whose physical and source names differ.
                    stored = sorted((value for value in selected if value.casefold() in aliases))
                    if stored:
                        ref_value = stored[0]
                    by_group[prefix].append((name, ref_value))
                    seen.update(aliases)
                    seen.add(ref_value.casefold())
            except Exception:
                pass
        for raw in selected:
            if raw.casefold() in seen:
                continue
            prefix = raw.split(".", 1)[0] if "." in raw else ""
            title = raw.rsplit(".", 1)[-1]
            by_group.setdefault(prefix, []).append((title, raw))

        for prefix in by_group:
            if prefix not in {key for key, _, _ in group_specs}:
                group_specs.append((prefix, "", t("doc_register_unresolved")))

        self._loading_register_records = True
        try:
            tree.blockSignals(True)
            tree.clear()
            for prefix, _obj_type, title in group_specs:
                items = sorted(by_group.get(prefix) or [], key=lambda item: item[0].casefold())
                if not items:
                    continue
                group_item = QTreeWidgetItem([title])
                group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                tree.addTopLevelItem(group_item)
                for label, ref_value in items:
                    child = QTreeWidgetItem([label])
                    child.setData(0, Qt.ItemDataRole.UserRole, ref_value)
                    child.setToolTip(0, ref_value)
                    child.setFlags(
                        child.flags()
                        | Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                    )
                    child.setCheckState(
                        0,
                        Qt.CheckState.Checked if ref_value.casefold() in {s.casefold() for s in selected} else Qt.CheckState.Unchecked,
                    )
                    group_item.addChild(child)
                group_item.setExpanded(any(child_ref in selected for _, child_ref in items))
        finally:
            tree.blockSignals(False)
            self._loading_register_records = False

        self._filter_registers(self.ed_register_search.text())
        self._refresh_movements_preview()

    def _checked_register_records(self) -> list[str]:
        tree = getattr(self, "tree_register_records", None)
        if not isinstance(tree, QTreeWidget):
            return []
        out: list[str] = []
        for i in range(tree.topLevelItemCount()):
            group = tree.topLevelItem(i)
            if group is None:
                continue
            for j in range(group.childCount()):
                child = group.child(j)
                if child is None or child.checkState(0) != Qt.CheckState.Checked:
                    continue
                value = str(child.data(0, Qt.ItemDataRole.UserRole) or "").strip()
                if value and value not in out:
                    out.append(value)
        return out

    def _on_register_record_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if getattr(self, "_loading_register_records", False):
            return
        value = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        if not value:
            return
        records = self._checked_register_records()
        self._payload_raw["register_records"] = records
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({"register_records": records})
        self._refresh_movements_preview()

    def _filter_registers(self, query: str) -> None:
        query = query.strip().casefold()
        for i in range(self.tree_register_records.topLevelItemCount()):
            group = self.tree_register_records.topLevelItem(i)
            visible = False
            for j in range(group.childCount()):
                child = group.child(j)
                matches = not query or query in (child.text(0) + " " + child.toolTip(0)).casefold()
                child.setHidden(not matches)
                visible = visible or matches
            group.setHidden(not visible)
            if query and visible:
                group.setExpanded(True)

    def _remove_selected_movements(self) -> None:
        refs = {self.table_movements.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
                for index in self.table_movements.selectionModel().selectedRows()}
        for i in range(self.tree_register_records.topLevelItemCount()):
            group = self.tree_register_records.topLevelItem(i)
            for j in range(group.childCount()):
                child = group.child(j)
                if child.data(0, Qt.ItemDataRole.UserRole) in refs:
                    child.setCheckState(0, Qt.CheckState.Unchecked)

    def _refresh_movements_preview(self) -> None:
        table = getattr(self, "table_movements", None)
        if table is None:
            return
        records = self._checked_register_records()
        table.setRowCount(0)
        for ref in records:
            row = table.rowCount()
            table.insertRow(row)
            item = QTableWidgetItem(ref.rsplit(".", 1)[-1])
            item.setData(Qt.ItemDataRole.UserRole, ref)
            item.setToolTip(ref)
            table.setItem(row, 0, item)
            table.setItem(row, 1, QTableWidgetItem(t("doc_movement_write")))
        self._update_posting_buttons()

    def _update_posting_buttons(self) -> None:
        records = self._checked_register_records()
        self.btn_generate_posting.setEnabled(bool(records))
        self.btn_configure_posting.setEnabled(bool(records and self._vm and self._obj_guid))
        self.btn_remove_movement.setEnabled(bool(self.table_movements.selectionModel().selectedRows()))
        preview_records = self._payload_raw.get("posting_handler_registers", [])
        self.btn_insert_posting.setEnabled(
            bool(self._obj_guid and self._vm and self.ed_posting_handler.toPlainText().strip())
            and set(records) == set(preview_records) and bool(records)
        )

    def _on_posting_text_changed(self) -> None:
        code = self.ed_posting_handler.toPlainText()
        self._payload_raw["posting_handler"] = code
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({"posting_handler": code})
        self._update_posting_buttons()

    def _generate_posting_handler(self) -> None:
        records = self._checked_register_records()
        try:
            plan = self._payload_raw.get("posting_mappings")
            if plan is not None:
                from src.configurator.domain.posting_mapping import generate_mapped_posting
                code = generate_mapped_posting(plan, self._posting_mapping_schema(),
                                               language=self.cb_posting_language.currentData())
            else:
                code = generate_posting_handler(records, language=self.cb_posting_language.currentData())
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, t("doc_generate_posting"), t("doc_posting_invalid") + "\n" + str(exc))
            return
        self._set_posting_draft(code, records)

    def _set_posting_draft(self, code, records, *, plan=None):
        if self.ed_posting_handler.toPlainText().strip() and self.ed_posting_handler.toPlainText() != code:
            if QMessageBox.question(self, t("doc_generate_posting"), t("doc_posting_replace_preview"),
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        if plan is not None:
            self._payload_raw["posting_mappings"] = plan
            self._shell.set_pending_patch({"posting_mappings": plan})
        self._payload_raw["posting_handler_registers"] = records
        self._shell.set_pending_patch({"posting_handler_registers": records})
        self.ed_posting_handler.setPlainText(code)
        self._on_posting_text_changed()

    def _posting_mapping_schema(self):
        from src.configurator.domain.posting_mapping import PostingMappingSchema
        rows = []
        for obj in self._vm.list_objects():
            row = dict(obj) if isinstance(obj, dict) else {
                key: getattr(obj, key, None) for key in ("guid", "name", "kind", "type", "parent_guid", "payload")
            }
            if row["guid"] == self._obj_guid:
                row["payload"] = {**(row.get("payload") or {}), **self._payload_raw}
            rows.append(row)
        refs = self._checked_register_records()
        selected_names = {ref.rsplit(".", 1)[-1].casefold() for ref in refs}
        relevant = {self._obj_guid}
        for row in rows:
            if str(row.get("type") or "").startswith("register_"):
                names = {str(row.get("name") or ""), technical_object_name(row.get("name"), payload=row.get("payload"))}
                if selected_names & {name.casefold() for name in names}:
                    relevant.add(row["guid"])
        while True:
            descendants = {row["guid"] for row in rows if row.get("parent_guid") in relevant}
            if descendants <= relevant:
                break
            relevant.update(descendants)
        # Hydrate only selected metadata owners, never modules or business rows.
        for row in rows:
            payload = row.get("payload") or {}
            if row["guid"] in relevant and any(payload.get(key + "_ref") and key not in payload
                    for key in ("attributes", "requisites", "dimensions", "resources", "fields", "columns", "tabular_parts")):
                loaded = self._vm.manifest_get_payload(row["guid"])
                row["payload"] = {**loaded, **payload}
        return PostingMappingSchema.from_manifest(rows, self._obj_guid, refs)

    def _configure_posting_mappings(self):
        from .posting_mapping_dialog import PostingMappingDialog
        try:
            dialog = PostingMappingDialog(self._posting_mapping_schema(),
                plan=self._payload_raw.get("posting_mappings"),
                language=self.cb_posting_language.currentData(), parent=self)
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            QMessageBox.warning(self, t("posting_map_title"), str(exc))
            return
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_posting_draft(dialog.preview.toPlainText(), self._checked_register_records(), plan=dialog.plan())
        dialog.deleteLater()

    def _insert_posting_handler(self) -> None:
        self._update_posting_buttons()
        if self.btn_insert_posting.isEnabled():
            if self._payload_raw.get("posting_mappings") is not None:
                from src.configurator.domain.posting_mapping import generate_mapped_posting
                try:
                    generate_mapped_posting(self._payload_raw["posting_mappings"], self._posting_mapping_schema(),
                                            language=self.cb_posting_language.currentData())
                except (ValueError, RuntimeError) as exc:
                    QMessageBox.warning(self, t("posting_map_title"), str(exc))
                    return
            self.postingModuleRequested.emit(self.ed_posting_handler.toPlainText())

    def _on_sequence_item_changed(self, _item: QListWidgetItem) -> None:
        self._set_list_payload(
            "sequence_memberships",
            self._checked_values_from_list_widget(self.lst_sequences),
        )

    def _on_journal_item_changed(self, _item: QListWidgetItem) -> None:
        self._set_list_payload(
            "document_journals",
            self._checked_values_from_list_widget(self.lst_journals),
        )

    def _document_metadata_ref(self) -> str:
        name = str(self._model.name or "").strip()
        if not name:
            imported = (
                self._payload_raw.get("imported")
                if isinstance(self._payload_raw.get("imported"), dict)
                else {}
            )
            origin = str(imported.get("origin") or "").strip()
            if origin:
                name = Path(origin).stem
        return f"Document.{name}" if name else ""

    def _workspace_links(self) -> dict[str, Any]:
        return _load_document_workspace_links(self._document_metadata_ref())

    def _workspace_roles(self) -> list[dict[str, Any]]:
        return _load_document_workspace_roles(self._document_metadata_ref())

    def _on_shell_section_changed(self, row: int) -> None:
        if row < 0 or row >= self._shell._sections.count():
            return
        item = self._shell._sections.item(row)
        key = str(item.data(Qt.ItemDataRole.UserRole) or "") if item is not None else ""
        if key == "rights":
            self._ensure_rights_loaded()

    def _reload_role_rights_view(self) -> None:
        if not hasattr(self, "lst_role_rights") or not hasattr(self, "lst_roles"):
            return
        self.lst_role_rights.clear()
        self.lbl_role_rights_info.setText("")
        if hasattr(self, "tree_role_restrictions"):
            self.tree_role_restrictions.clear()
        current = self.lst_roles.currentItem()
        if current is None:
            return
        info = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(info, dict):
            return
        rights = info.get("rights") if isinstance(info.get("rights"), list) else []
        rights_map = {
            str(right_name or "").strip(): bool(enabled)
            for right_name, enabled in rights
            if str(right_name or "").strip()
        }
        ordered_rights: list[str] = list(_RIGHTS_DISPLAY_ORDER)
        for right_name in sorted(rights_map, key=str.casefold):
            if right_name not in ordered_rights:
                ordered_rights.append(right_name)
        for right_name in ordered_rights:
            if not right_name:
                continue
            item = QListWidgetItem(_localized_right_name(right_name), self.lst_role_rights)
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if rights_map.get(right_name, False)
                else Qt.CheckState.Unchecked
            )
        restrictions = info.get("restrictions") if isinstance(info.get("restrictions"), list) else []
        if hasattr(self, "tree_role_restrictions"):
            for item in restrictions:
                if not isinstance(item, dict):
                    continue
                row = QTreeWidgetItem(
                    [
                        str(item.get("field") or "").strip(),
                        str(item.get("rule") or "").strip(),
                    ]
                )
                self.tree_role_restrictions.addTopLevelItem(row)
        if info.get("has_related"):
            self.lbl_role_rights_info.setText(t("doc.rights_related_hint"))
        elif not rights and not restrictions:
            self.lbl_role_rights_info.setText(t("obj.rights_empty"))

    def _ensure_rights_loaded(self) -> None:
        if not hasattr(self, "lst_roles"):
            return
        if getattr(self, "_rights_loaded", False):
            return
        self.lst_roles.clear()
        for role in self._workspace_roles():
            if not isinstance(role, dict):
                continue
            item = QListWidgetItem(str(role.get("name") or ""))
            item.setData(Qt.ItemDataRole.UserRole, role)
            self.lst_roles.addItem(item)
        if self.lst_roles.count() > 0:
            self.lst_roles.setCurrentRow(0)
        self._rights_loaded = True
        self._reload_role_rights_view()

    def _derive_based_for_refs(self) -> list[str]:
        target_ref = f"Document.{self._model.name}".strip()
        if not target_ref or self._vm is None:
            return []
        out: list[str] = []
        try:
            list_by_type = getattr(self._vm, "list_objects_by_type", None)
            objects = (
                list_by_type("document", "business_process", "task")
                if callable(list_by_type)
                else self._vm.list_objects() or []
            )
            for obj in objects:
                obj_type = str(getattr(obj, "type", "") or "").strip().lower()
                if obj_type not in {"document", "business_process", "task"}:
                    continue
                if str(getattr(obj, "guid", "") or "").strip() == self._obj_guid:
                    continue
                obj_guid_str = str(getattr(obj, "guid", "") or "").strip()
                payload = getattr(obj, "payload", None)
                payload = payload if isinstance(payload, dict) else {}
                if "based_on" not in payload and obj_guid_str and hasattr(self._vm, "get_meta_by_guid"):
                    try:
                        full_meta = self._vm.get_meta_by_guid(obj_guid_str)
                        if isinstance(full_meta, dict) and isinstance(full_meta.get("payload"), dict):
                            payload = full_meta["payload"]
                    except Exception:
                        pass
                based_on = _normalize_string_list(payload.get("based_on"))
                if target_ref in based_on:
                    title = technical_object_name(getattr(obj, "name", ""), payload=getattr(obj, "payload", None))
                    if title and title not in out:
                        out.append(title)
        except Exception:
            return []
        return out

    def _reload_reference_lists(self) -> None:
        links = self._workspace_links()
        if hasattr(self, "tree_register_records"):
            self._reload_register_records_tree()
        if hasattr(self, "lst_based_on"):
            self._fill_list_widget(self.lst_based_on, self._model.based_on)
        if hasattr(self, "lst_based_for"):
            self._fill_list_widget(self.lst_based_for, self._derive_based_for_refs())
        self._update_based_on_buttons()
        if hasattr(self, "lst_sequences"):
            sequences = list(self._model.sequence_memberships or []) or list(links.get("sequences") or [])
            available = list(links.get("sequences") or [])
            for value in sequences:
                if value not in available:
                    available.append(value)
            self._fill_checkable_list_widget(self.lst_sequences, available, sequences)
        if hasattr(self, "lst_journals"):
            journals = list(self._model.document_journals or []) or list(links.get("journals") or [])
            available = list(links.get("journals") or [])
            for value in journals:
                if value not in available:
                    available.append(value)
            self._fill_checkable_list_widget(self.lst_journals, available, journals)
        if hasattr(self, "lst_functional_options"):
            self._fill_list_widget(
                self.lst_functional_options,
                list(links.get("functional_options") or []),
            )
        if hasattr(self, "lst_exchange_plans"):
            self._fill_list_widget(
                self.lst_exchange_plans,
                list(links.get("exchange_plans") or []),
            )
        if hasattr(self, "tree_exchange_plans"):
            items = list(self._model.exchange_plans or []) or _normalize_exchange_plan_items(
                links.get("exchange_plans")
            )
            self._reload_exchange_plans_tree(items)

    def _load_to_ui(self) -> None:
        self.ed_name.setText(self._model.name)
        self.ed_synonym.setText(self._model.synonym)
        self.ed_comment.setText(self._model.comment)
        self.ed_object_presentation.setText(self._model.object_presentation)
        self.ed_object_presentation_ext.setText(self._model.extended_object_presentation)
        self.ed_list_presentation.setText(self._model.list_presentation)
        self.ed_list_presentation_ext.setText(self._model.extended_list_presentation)
        self.ed_explanation.setPlainText(self._model.explanation)
        if hasattr(self, "ed_posting_handler"):
            blocked = self.ed_posting_handler.blockSignals(True)
            try:
                self.ed_posting_handler.setPlainText(self._model.posting_handler)
            finally:
                self.ed_posting_handler.blockSignals(blocked)
        blockers = []
        for name in (
            "sp_number_length",
            "ed_numerator",
            "chk_check_unique",
            "cb_number_type",
            "cb_number_periodicity",
            "chk_autonumbering",
            "cb_posting",
            "cb_real_time_posting",
            "cb_register_records_deletion",
            "cb_register_records_writing",
            "chk_post_privileged",
            "chk_unpost_privileged",
            "cb_sequence_filling",
            "cb_create_on_input",
            "ed_input_by_string_field",
            "cb_search_string_mode",
            "cb_full_text_search_on_input",
            "cb_choice_data_get_mode",
            "cb_choice_history_on_input",
            "chk_use_standard_commands",
            "cb_full_text_search",
            "cb_data_history",
            "chk_update_data_history",
            "chk_execute_after_write_history",
            "chk_include_help_in_contents",
            "ed_data_lock_fields",
            "cb_data_lock_control_mode",
            "ed_default_object_form",
            "ed_default_list_form",
            "ed_default_choice_form",
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                blockers.append((widget, widget.blockSignals(True)))
        try:
            if hasattr(self, "sp_number_length"):
                self.sp_number_length.setValue(max(1, int(self._model.number_length or 1)))
            if hasattr(self, "ed_numerator"):
                self.ed_numerator.setText(self._model.numerator)
            if hasattr(self, "chk_check_unique"):
                self.chk_check_unique.setChecked(bool(self._model.check_unique))
            if hasattr(self, "chk_autonumbering"):
                self.chk_autonumbering.setChecked(bool(self._model.autonumbering))
            if hasattr(self, "cb_posting"):
                self._set_combo_data(self.cb_posting, self._model.posting, "allow")
            if hasattr(self, "cb_real_time_posting"):
                self._set_combo_data(
                    self.cb_real_time_posting,
                    self._model.real_time_posting,
                    "allow",
                )
            if hasattr(self, "cb_register_records_deletion"):
                self._set_combo_data(
                    self.cb_register_records_deletion,
                    self._model.register_records_deletion,
                    "auto_delete_off",
                )
            if hasattr(self, "cb_register_records_writing"):
                self._set_combo_data(
                    self.cb_register_records_writing,
                    self._model.register_records_writing_on_post,
                    "write_selected",
                )
            if hasattr(self, "chk_post_privileged"):
                self.chk_post_privileged.setChecked(bool(self._model.post_in_privileged_mode))
            if hasattr(self, "chk_unpost_privileged"):
                self.chk_unpost_privileged.setChecked(
                    bool(self._model.unpost_in_privileged_mode)
                )
            if hasattr(self, "cb_sequence_filling"):
                self._set_combo_data(
                    self.cb_sequence_filling,
                    self._model.sequence_filling,
                    "auto_fill_off",
                )
            if hasattr(self, "cb_create_on_input"):
                self._set_combo_data(
                    self.cb_create_on_input,
                    self._model.create_on_input,
                    "use",
                )
            if hasattr(self, "ed_input_by_string_field"):
                self.ed_input_by_string_field.setText(
                    self._model.input_by_string_field or self._model.input_by_string
                )
            if hasattr(self, "cb_search_string_mode"):
                self._set_combo_data(
                    self.cb_search_string_mode,
                    self._model.search_string_mode_on_input_by_string,
                    "begin",
                )
            if hasattr(self, "cb_full_text_search_on_input"):
                self._set_combo_data(
                    self.cb_full_text_search_on_input,
                    self._model.full_text_search_on_input_by_string,
                    "dont_use",
                )
            if hasattr(self, "cb_choice_data_get_mode"):
                self._set_combo_data(
                    self.cb_choice_data_get_mode,
                    self._model.choice_data_get_mode_on_input_by_string,
                    "directly",
                )
            if hasattr(self, "cb_choice_history_on_input"):
                self._set_combo_data(
                    self.cb_choice_history_on_input,
                    self._model.choice_history_on_input,
                    "dont_use",
                )
            if hasattr(self, "chk_use_standard_commands"):
                self.chk_use_standard_commands.setChecked(
                    bool(self._model.use_standard_commands)
                )
            if hasattr(self, "cb_number_type"):
                self._set_combo_data(
                    self.cb_number_type,
                    self._model.number_type,
                    "string",
                )
            if hasattr(self, "cb_number_periodicity"):
                self._set_combo_data(
                    self.cb_number_periodicity,
                    self._model.number_periodicity,
                    "year",
                )
            if hasattr(self, "cb_full_text_search"):
                self._set_combo_data(
                    self.cb_full_text_search,
                    self._model.full_text_search,
                    "dont_use",
                )
            if hasattr(self, "cb_data_history"):
                self._set_combo_data(
                    self.cb_data_history,
                    self._model.data_history,
                    "dont_use",
                )
            if hasattr(self, "chk_update_data_history"):
                self.chk_update_data_history.setChecked(
                    bool(self._model.update_data_history_immediately_after_write)
                )
            if hasattr(self, "chk_execute_after_write_history"):
                self.chk_execute_after_write_history.setChecked(
                    bool(self._model.execute_after_write_data_history_version_processing)
                )
            if hasattr(self, "chk_include_help_in_contents"):
                self.chk_include_help_in_contents.setChecked(
                    bool(self._model.include_help_in_contents)
                )
            if hasattr(self, "ed_data_lock_fields"):
                self.ed_data_lock_fields.setText(self._model.data_lock_fields)
            if hasattr(self, "cb_data_lock_control_mode"):
                self._set_combo_data(
                    self.cb_data_lock_control_mode,
                    self._model.data_lock_control_mode,
                    "automatic",
                )
        finally:
            for widget, state in reversed(blockers):
                widget.blockSignals(state)
        self._reload_data_tree()
        self._reload_reference_lists()
        if hasattr(self, "lst_forms"):
            self._refresh_forms_list()
        elif not hasattr(self, "ed_default_object_form"):
            self._sync_default_form_selectors([])
        if hasattr(self, "lst_layouts"):
            self._refresh_layouts_list()
        if hasattr(self, "lst_cmds"):
            self._refresh_commands_list()

    def _on_text_changed(self, key: str, value: str) -> None:
        self._shell.set_pending_patch({key: str(value)})

    def _on_value_changed(self, key: str, value: Any) -> None:
        self._shell.set_pending_patch({key: value})

    def _set_list_payload(self, key: str, values: list[str]) -> None:
        normalized = [str(item or "").strip() for item in values if str(item or "").strip()]
        self._payload_raw[key] = normalized
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({key: normalized})
        self._reload_reference_lists()

    def _set_exchange_plans_payload(self, values: list[dict[str, str]]) -> None:
        normalized = _normalize_exchange_plan_items(values)
        self._payload_raw["exchange_plans"] = normalized
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({"exchange_plans": normalized})
        self._reload_reference_lists()

    def _on_add_based_on(self) -> None:
        dlg = _ReferenceTargetDialog(
            targets=self._collect_reference_targets(),
            current_values=list(self._model.based_on or []),
            current_value=(self._model.based_on[0] if self._model.based_on else ""),
            allowed_prefixes={"Document", "BusinessProcess", "Task"},
            multi_select=True,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._set_list_payload("based_on", dlg.selected_values())

    def _on_remove_based_on(self) -> None:
        current = self.lst_based_on.currentItem() if hasattr(self, "lst_based_on") else None
        if current is None:
            return
        raw = str(current.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not raw:
            raw = next(
                (
                    value
                    for value in (self._model.based_on or [])
                    if _display_metadata_ref(value, vm=self._vm) == current.text()
                ),
                "",
            )
        remaining = [value for value in (self._model.based_on or []) if value != raw]
        self._set_list_payload("based_on", remaining)

    def _update_based_on_buttons(self) -> None:
        if hasattr(self, "btn_based_on_remove"):
            self.btn_based_on_remove.setEnabled(
                hasattr(self, "lst_based_on") and self.lst_based_on.currentItem() is not None
            )

    def _on_open_based_on_constructor(self) -> None:
        QMessageBox.information(
            self,
            t("info"),
            t("doc.based_on_constructor_hint"),
        )

    def _available_input_by_string_fields(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        doc_name = str(self._model.name or self._payload_raw.get("name") or "").strip()
        if doc_name:
            out.append((t("doc.input_field_number"), f"Document.{doc_name}.StandardAttribute.Number"))
            out.append((t("doc.input_field_date"), f"Document.{doc_name}.StandardAttribute.Date"))
        for req in self._model.requisites or []:
            if not isinstance(req, dict):
                continue
            name = str(req.get("name") or "").strip()
            if not name or not doc_name:
                continue
            title = _localized_text(req.get("title") or req.get("synonym") or name) or name
            out.append((title, f"Document.{doc_name}.Attribute.{name}"))
        return out

    def _available_data_lock_fields(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = [
            (t("doc.data_lock_field_number"), "Number"),
            (t("doc.data_lock_field_date"), "Date"),
            (t("doc.data_lock_field_deletion_mark"), "DeletionMark"),
        ]
        seen = {value.casefold() for _label, value in out}
        for req in self._model.requisites or []:
            if not isinstance(req, dict):
                continue
            name = str(req.get("name") or "").strip()
            if not name or name.casefold() in seen:
                continue
            title = _localized_text(req.get("title") or req.get("synonym") or name) or name
            out.append((title, name))
            seen.add(name.casefold())
        return out

    def _parse_data_lock_fields(self, value: Any) -> list[str]:
        raw = str(value or "")
        normalized = raw.replace(";", ",").replace("\n", ",")
        return [part.strip() for part in normalized.split(",") if part.strip()]

    def _sync_data_lock_fields(self, values: list[str]) -> None:
        text = ", ".join(str(value or "").strip() for value in values if str(value or "").strip())
        self.ed_data_lock_fields.setText(text)
        self._payload_raw["data_lock_fields"] = text
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({"data_lock_fields": text})

    def _reload_exchange_plans_tree(self, selected_items: list[dict[str, str]]) -> None:
        tree = getattr(self, "tree_exchange_plans", None)
        if not isinstance(tree, QTreeWidget):
            return
        selected_map = {
            str(item.get("name") or "").strip(): str(item.get("auto_record") or "").strip()
            for item in selected_items
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        available: list[tuple[str, str]] = []
        seen: set[str] = set()
        if self._vm is not None:
            try:
                for obj in self._vm.list_objects() or []:
                    if str(getattr(obj, "type", "") or "").strip().lower() != "exchange_plan":
                        continue
                    if str(getattr(obj, "kind", "") or "").strip().lower() != "object":
                        continue
                    name = str(getattr(obj, "name", "") or "").strip()
                    if not name or name.casefold() in seen:
                        continue
                    title = technical_object_name(name, payload=getattr(obj, "payload", None))
                    available.append((title, name))
                    seen.add(name.casefold())
            except Exception:
                pass
        for item in selected_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name.casefold() in seen:
                continue
            available.append((name, name))
            seen.add(name.casefold())

        tree.blockSignals(True)
        try:
            tree.clear()
            for title, name in sorted(available, key=lambda item: item[0].casefold()):
                auto_record = selected_map.get(name, "")
                row = QTreeWidgetItem(
                    [title, _localized_enum_label("auto_record", auto_record) if auto_record else ""]
                )
                row.setData(0, Qt.ItemDataRole.UserRole, {"name": name, "auto_record": auto_record})
                row.setFlags(
                    row.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                row.setCheckState(
                    0,
                    Qt.CheckState.Checked if name in selected_map else Qt.CheckState.Unchecked,
                )
                tree.addTopLevelItem(row)
        finally:
            tree.blockSignals(False)
        tree.resizeColumnToContents(0)

    def _checked_exchange_plan_items(self) -> list[dict[str, str]]:
        tree = getattr(self, "tree_exchange_plans", None)
        if not isinstance(tree, QTreeWidget):
            return []
        out: list[dict[str, str]] = []
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item is None or item.checkState(0) != Qt.CheckState.Checked:
                continue
            info = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(info, dict):
                continue
            name = str(info.get("name") or "").strip()
            auto_record = str(info.get("auto_record") or "").strip()
            if name:
                out.append({"name": name, "auto_record": auto_record})
        return out

    def _on_pick_input_by_string_field(self) -> None:
        dlg = _InputByStringFieldDialog(
            fields=self._available_input_by_string_fields(),
            current_value=str(self.ed_input_by_string_field.text() or "").strip(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        value = dlg.selected_value()
        self.ed_input_by_string_field.setText(value)
        self._payload_raw["input_by_string_field"] = value
        self._payload_raw["input_by_string"] = value
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({"input_by_string_field": value, "input_by_string": value})

    def _on_clear_input_by_string_field(self) -> None:
        self.ed_input_by_string_field.clear()
        self._payload_raw["input_by_string_field"] = ""
        self._payload_raw["input_by_string"] = ""
        self._rebuild_model_from_payload(self._payload_raw)
        self._shell.set_pending_patch({"input_by_string_field": "", "input_by_string": ""})

    def _on_pick_data_lock_fields(self) -> None:
        dlg = _ValueListDialog(
            title=t("doc.data_lock_fields_dialog_title"),
            hint=t("doc.data_lock_fields_dialog_hint"),
            values=self._available_data_lock_fields(),
            current_values=self._parse_data_lock_fields(self.ed_data_lock_fields.text()),
            multi_select=True,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._sync_data_lock_fields(dlg.selected_values())

    def _on_clear_data_lock_fields(self) -> None:
        self._sync_data_lock_fields([])

    def _on_exchange_plan_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        info = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(info, dict):
            return
        self._set_exchange_plans_payload(self._checked_exchange_plan_items())
