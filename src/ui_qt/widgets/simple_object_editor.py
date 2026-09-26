"""src.ui_qt.widgets.simple_object_editor — Simple editor for objects without complex sections.

Використовується для:
  - Role (роль): назва, права (таблиця)
  - ScheduledJob (регламентне завдання): назва, метод, розклад
  - EventSubscription (підписка на подію): подія, обробник
  - CommonModule (загальний модуль): відкриває одразу редактор коду
  - SessionParameter: назва, тип
"""
from __future__ import annotations

from src.configurator.domain.technical_names import technical_object_name

from dataclasses import dataclass, field
from typing import Any, Dict, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t
from src.ui_qt.services.object_editor_profiles import build_editor_sections
from src.ui_qt.viewmodels.configurator_vm import ConfiguratorViewModel
from .meta_object_shell import MetaObjectEditorShell
from .meta_object_shell import EditorSection


class _SimpleMainPage(QWidget):
    """Головна сторінка — назва + синонім + коментар."""
    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(20, 20, 20, 20)
        g.setSpacing(10)
        g.setColumnStretch(1, 1)

        row = 0
        g.addWidget(QLabel(t("prop_name") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        self.ed_name = QLineEdit(str(payload.get("name") or ""))
        g.addWidget(self.ed_name, row, 1); row += 1

        g.addWidget(QLabel(t("prop_synonym") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        self.ed_synonym = QLineEdit(str(payload.get("synonym") or ""))
        g.addWidget(self.ed_synonym, row, 1); row += 1

        g.addWidget(QLabel(t("prop_comment") + ":"), row, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.ed_comment = QTextEdit()
        self.ed_comment.setPlainText(str(payload.get("comment") or ""))
        self.ed_comment.setMaximumHeight(80)
        g.addWidget(self.ed_comment, row, 1); row += 1

        g.setRowStretch(row, 1)

    def collect(self) -> dict:
        return {
            "name":    self.ed_name.text().strip(),
            "synonym": self.ed_synonym.text().strip(),
            "comment": self.ed_comment.toPlainText().strip(),
        }


_ROLE_FAMILY_I18N = {
    "Constant": "client_nav_constants",
    "Catalog": "client_nav_catalogs",
    "Document": "client_nav_documents",
    "DocumentJournal": "group.journal",
    "Enum": "group.enumeration",
    "Report": "client_nav_reports",
    "DataProcessor": "group.data_processor",
    "InformationRegister": "group.register_info",
    "AccumulationRegister": "group.register_accum",
    "AccountingRegister": "group.register_accounting",
    "CalculationRegister": "group.register_calc",
    "ChartOfCharacteristicTypes": "group.chart_of_characteristic_types",
    "ChartOfAccounts": "group.chart_of_accounts",
    "ChartOfCalculationTypes": "group.chart_of_calculation_types",
    "BusinessProcess": "group.business_process",
    "Task": "group.task",
    "ExchangePlan": "folder.exchange_plans",
    "Subsystem": "folder.subsystems",
    "Role": "folder.roles",
    "SessionParameter": "folder.session_params",
    "CommonModule": "folder.common_modules",
    "CommonCommand": "folder.common_commands",
    "CommonForm": "folder.common_forms",
    "CommonTemplate": "folder.common_layouts",
    "CommonPicture": "folder.common_pictures",
    "CommonAttribute": "folder.common_attributes",
    "CommandGroup": "folder.command_groups",
    "DocumentNumerator": "tree.document_numerators",
    "Sequence": "group.common",
    "Language": "folder.languages",
}

_ROLE_SEGMENT_I18N = {
    "Attribute": "tree.attributes",
    "Command": "tree.commands",
    "Dimension": "tree.dimensions",
    "Form": "tree.forms",
    "Resource": "tree.resources",
    "StandardAttribute": "role.segment_standard_attribute",
    "TabularSection": "tree.tabularParts",
}

_ROLE_VM_REF_ROOTS = {
    "business_process": "BusinessProcess",
    "catalog": "Catalog",
    "chart_of_accounts": "ChartOfAccounts",
    "chart_of_calculation_types": "ChartOfCalculationTypes",
    "chart_of_characteristic_types": "ChartOfCharacteristicTypes",
    "common_attribute": "CommonAttribute",
    "common_command": "CommonCommand",
    "common_form": "CommonForm",
    "common_layout": "CommonTemplate",
    "common_module": "CommonModule",
    "common_picture": "CommonPicture",
    "command_group": "CommandGroup",
    "constants": "Constant",
    "data_processor": "DataProcessor",
    "document": "Document",
    "document_numerator": "DocumentNumerator",
    "enumeration": "Enum",
    "exchange_plan": "ExchangePlan",
    "functional_option": "FunctionalOption",
    "functional_option_param": "FunctionalOptionsParameter",
    "journal": "DocumentJournal",
    "language": "Language",
    "register_accum": "AccumulationRegister",
    "register_accounting": "AccountingRegister",
    "register_calc": "CalculationRegister",
    "register_info": "InformationRegister",
    "report": "Report",
    "role": "Role",
    "sequence": "Sequence",
    "session_param": "SessionParameter",
    "subsystem": "Subsystem",
    "task": "Task",
}

_ROLE_DEFAULT_RIGHTS = [
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
    "InteractiveDeleteMarked",
    "InputByString",
    "Use",
    "Get",
    "Set",
    "TotalsControl",
]

_ROLE_RIGHT_I18N = {
    "Delete": "right.delete",
    "Edit": "right.edit",
    "Insert": "right.insert",
    "InteractiveClearDeletionMark": "right.interactive_clear_deletion_mark",
    "InteractiveInsert": "right.interactive_insert",
    "InteractivePosting": "right.interactive_posting",
    "InteractiveSetDeletionMark": "right.interactive_set_deletion_mark",
    "Posting": "right.posting",
    "Read": "right.read",
    "UndoPosting": "right.undo_posting",
    "Update": "right.update",
    "View": "right.view",
}


class RoleEditorWidget(QWidget):
    """Редактор ролі у більш 1С-подібній структурі."""

    applyRequested = Signal(dict)
    closeRequested = Signal()

    def __init__(self, title: str, payload: dict | None = None,
                 *, vm: ConfiguratorViewModel | None = None, obj_guid: str = "") -> None:
        super().__init__()
        self._vm = vm
        self._obj_guid = str(obj_guid or "")
        self._payload = dict(payload or {}) if isinstance(payload, dict) else {}
        if title and not str(self._payload.get("name") or "").strip():
            self._payload["name"] = str(title)
        if title and not str(self._payload.get("title") or "").strip():
            self._payload["title"] = str(title)
        self._role_rights = self._normalize_rights(self._payload.get("rights") or [])
        self._restriction_templates = self._normalize_templates(
            self._payload.get("restriction_templates") or []
        )
        self._tree_nodes_by_ref: Dict[str, QTreeWidgetItem] = {}
        self._current_object_ref = ""

        self._shell = MetaObjectEditorShell(title=title)
        self._shell.applyRequested.connect(self._on_apply)
        self._shell.closeRequested.connect(self.closeRequested.emit)

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._shell, 1)

        self._main_page = _SimpleMainPage(self._payload)
        self._rights_page = self._build_rights_page()
        self._shell.set_sections(
            build_editor_sections(
                "role",
                {
                    "main": lambda: self._main_page,
                    "rights": lambda: self._rights_page,
                },
            )
        )
        self._load_role_state()

    def _build_rights_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        hint = QLabel(t("role.rights_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        root.addWidget(hint)

        bar = QHBoxLayout()
        btn_gen = QPushButton(t("role.generate_from_manifest"))
        btn_gen.clicked.connect(self._generate_rights)
        bar.addWidget(btn_gen)
        bar.addStretch(1)
        root.addLayout(bar)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_rights_tab(), t("role.rights"))
        self._tabs.addTab(self._build_templates_tab(), t("role.restriction_templates"))
        root.addWidget(self._tabs, 1)

        self._chk_set_for_new_objects = QCheckBox(t("role.set_for_new_objects"))
        self._chk_set_for_attributes_by_default = QCheckBox(t("role.set_for_attributes_by_default"))
        self._chk_independent_rights = QCheckBox(t("role.independent_rights_of_child_objects"))
        root.addWidget(self._chk_set_for_new_objects)
        root.addWidget(self._chk_set_for_attributes_by_default)
        root.addWidget(self._chk_independent_rights)

        return page

    def _build_rights_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        layout.addLayout(top, 1)

        left_box = QGroupBox(t("role.objects_tree"))
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(8, 8, 8, 8)
        self._objects_tree = QTreeWidget()
        self._objects_tree.setHeaderHidden(True)
        self._objects_tree.itemSelectionChanged.connect(self._on_rights_object_changed)
        left_layout.addWidget(self._objects_tree, 1)
        top.addWidget(left_box, 1)

        right_box = QGroupBox(t("role.object_rights"))
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(8, 8, 8, 8)
        self._selected_object_label = QLabel("")
        self._selected_object_label.setObjectName("metaHint")
        self._selected_object_label.setWordWrap(True)
        right_layout.addWidget(self._selected_object_label)
        self._rights_list = QListWidget()
        self._rights_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._rights_list.itemChanged.connect(self._on_right_item_changed)
        right_layout.addWidget(self._rights_list, 1)
        top.addWidget(right_box, 1)

        restrictions_box = QGroupBox(t("role.restrictions"))
        restrictions_layout = QVBoxLayout(restrictions_box)
        restrictions_layout.setContentsMargins(8, 8, 8, 8)

        restrictions_bar = QHBoxLayout()
        btn_add_restriction = QPushButton(t("role.add_restriction"))
        btn_duplicate_restriction = QPushButton(t("role.duplicate_restriction"))
        btn_remove_restriction = QPushButton(t("role.remove_restriction"))
        btn_add_restriction.clicked.connect(self._add_restriction)
        btn_duplicate_restriction.clicked.connect(self._duplicate_restriction)
        btn_remove_restriction.clicked.connect(self._remove_restrictions)
        restrictions_bar.addWidget(btn_add_restriction)
        restrictions_bar.addWidget(btn_duplicate_restriction)
        restrictions_bar.addWidget(btn_remove_restriction)
        restrictions_bar.addStretch(1)
        restrictions_layout.addLayout(restrictions_bar)

        self._restrictions_model = QStandardItemModel(0, 2)
        self._restrictions_model.setHorizontalHeaderLabels(
            [t("role.restriction_right"), t("role.restriction_condition")]
        )
        self._restrictions_model.itemChanged.connect(self._on_restriction_item_changed)
        self._restrictions_view = QTableView()
        self._restrictions_view.setObjectName("restrictionsView")
        self._restrictions_view.setModel(self._restrictions_model)
        self._restrictions_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._restrictions_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._restrictions_view.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # self._restrictions_view.horizontalHeader().setStyleSheet("""
        #     QHeaderView{
        #         border-top-left-radius: 16px;
        #         border-top-right-radius: 16px;
        #     }
        #     QHeaderView::section:first {
        #         border-top-left-radius: 16px;
        #     }
        #     QHeaderView::section:last {
        #         border-top-right-radius: 16px;
        #     }
        # """)
        self._restrictions_view.viewport().setStyleSheet(
            "border-bottom-left-radius: 16px; "
            "border-bottom-right-radius: 16px;"
        )
        restrictions_layout.addWidget(self._restrictions_view, 1)
        layout.addWidget(restrictions_box, 1)

        return tab

    def _build_templates_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        hint = QLabel(t("role.templates_hint"))
        hint.setObjectName("metaHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        bar = QHBoxLayout()
        btn_add = QPushButton(t("role.add_template"))
        btn_dup = QPushButton(t("role.duplicate_template"))
        btn_remove = QPushButton(t("role.remove_template"))
        btn_add.clicked.connect(self._add_restriction_template)
        btn_dup.clicked.connect(self._duplicate_restriction_template)
        btn_remove.clicked.connect(self._remove_restriction_template)
        bar.addWidget(btn_add)
        bar.addWidget(btn_dup)
        bar.addWidget(btn_remove)
        bar.addStretch(1)
        layout.addLayout(bar)

        self._templates_model = QStandardItemModel(0, 2)
        self._templates_model.setHorizontalHeaderLabels(
            [t("role.col_template_name"), t("role.col_template_text")]
        )
        self._templates_view = QTableView()
        self._templates_view.setModel(self._templates_model)
        self._templates_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._templates_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._templates_view.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._templates_view, 1)
        return tab

    def _generate_rights(self) -> None:
        """Заповнюємо каркас прав по об'єктах manifest."""
        if self._vm is None:
            return
        try:
            all_objs = self._vm.list_objects() or []
        except Exception:
            return
        for o in all_objs:
            if str(getattr(o, "kind", "")) != "object":
                continue
            ot = str(getattr(o, "type", "") or "").lower()
            ref_root = _ROLE_VM_REF_ROOTS.get(ot, "")
            name = str(getattr(o, "name", "") or "").strip()
            if not ref_root or not name:
                continue
            ref = f"{ref_root}.{name}"
            self._ensure_role_entry(ref)
        self._populate_rights_tree()
        if self._current_object_ref:
            self._select_role_object_ref(self._current_object_ref)

    @staticmethod
    def _normalize_rights(raw: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not isinstance(raw, list):
            return out
        for item in raw:
            if not isinstance(item, dict):
                continue
            object_ref = str(item.get("object") or "").strip()
            if not object_ref:
                continue
            rights_map = item.get("rights")
            normalized_rights: Dict[str, bool] = {}
            if isinstance(rights_map, dict):
                for key, value in rights_map.items():
                    right_name = str(key or "").strip()
                    if right_name:
                        normalized_rights[right_name] = bool(value)
            else:
                for legacy_key, right_name in (
                    ("read", "Read"),
                    ("write", "Update"),
                    ("create", "Insert"),
                    ("delete", "Delete"),
                    ("execute", "Use"),
                ):
                    if legacy_key in item:
                        normalized_rights[right_name] = bool(item.get(legacy_key))
            restrictions: List[Dict[str, str]] = []
            for restriction in item.get("restrictions") or []:
                if not isinstance(restriction, dict):
                    continue
                right_name = str(restriction.get("right") or "").strip()
                condition = str(restriction.get("condition") or "").strip()
                field_name = str(restriction.get("field") or "").strip()
                if right_name and condition:
                    row = {"right": right_name, "condition": condition}
                    if field_name:
                        row["field"] = field_name
                    restrictions.append(row)
            out.append(
                {
                    "object": object_ref,
                    "rights": normalized_rights,
                    "restrictions": restrictions,
                }
            )
        out.sort(key=lambda entry: str(entry.get("object") or "").casefold())
        return out

    @staticmethod
    def _normalize_templates(raw: Any) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        if not isinstance(raw, list):
            return out
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            condition = str(item.get("condition") or "").strip()
            if not name and not condition:
                continue
            out.append({"name": name, "condition": condition})
        return out

    def _load_role_state(self) -> None:
        self._populate_templates_model()
        self._populate_rights_tree()
        self._chk_set_for_new_objects.setChecked(bool(self._payload.get("set_for_new_objects", False)))
        self._chk_set_for_attributes_by_default.setChecked(
            bool(self._payload.get("set_for_attributes_by_default", True))
        )
        self._chk_independent_rights.setChecked(
            bool(self._payload.get("independent_rights_of_child_objects", False))
        )
        if self._tree_nodes_by_ref:
            first_ref = next(iter(self._tree_nodes_by_ref))
            self._select_role_object_ref(first_ref)

    def reload_from_vm(self) -> None:
        if self._vm is None or not self._obj_guid:
            return
        try:
            meta = self._vm.get_meta_by_guid(self._obj_guid)
        except Exception:
            meta = None
        if not isinstance(meta, dict):
            return
        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
        self._payload = dict(payload or {})
        title = technical_object_name(meta.get("name"), payload=payload)
        if title:
            try:
                self._shell.set_title(title)
            except Exception:
                pass
        self._role_rights = self._normalize_rights(self._payload.get("rights") or [])
        self._restriction_templates = self._normalize_templates(
            self._payload.get("restriction_templates") or []
        )
        self._load_role_state()

    def _populate_templates_model(self) -> None:
        self._templates_model.removeRows(0, self._templates_model.rowCount())
        for item in self._restriction_templates:
            self._templates_model.appendRow(
                [
                    QStandardItem(str(item.get("name") or "")),
                    QStandardItem(str(item.get("condition") or "")),
                ]
            )

    def _collect_role_object_refs(self) -> List[str]:
        refs: set[str] = set()
        for item in self._role_rights:
            object_ref = str(item.get("object") or "").strip()
            if object_ref:
                refs.add(object_ref)
        if self._vm is not None:
            try:
                for obj in self._vm.list_objects() or []:
                    if str(getattr(obj, "kind", "") or "") != "object":
                        continue
                    obj_type = str(getattr(obj, "type", "") or "").strip().lower()
                    ref_root = _ROLE_VM_REF_ROOTS.get(obj_type, "")
                    name = str(getattr(obj, "name", "") or "").strip()
                    if ref_root and name:
                        refs.add(f"{ref_root}.{name}")
            except Exception:
                pass
        return sorted(refs, key=str.casefold)

    def _populate_rights_tree(self) -> None:
        previous_ref = self._current_object_ref
        self._tree_nodes_by_ref.clear()
        self._objects_tree.clear()

        root_item = QTreeWidgetItem([t("cfg_tree_title")])
        root_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self._objects_tree.addTopLevelItem(root_item)

        for object_ref in self._collect_role_object_refs():
            self._append_role_ref(root_item, object_ref)

        root_item.setExpanded(True)
        if previous_ref:
            self._select_role_object_ref(previous_ref)

    def _append_role_ref(self, root_item: QTreeWidgetItem, object_ref: str) -> None:
        parts = [part for part in str(object_ref or "").split(".") if part]
        if len(parts) < 2:
            return

        family = parts[0]
        family_node = None
        for index in range(root_item.childCount()):
            child = root_item.child(index)
            if str(child.data(0, Qt.ItemDataRole.UserRole) or "") == f"family:{family}":
                family_node = child
                break
        if family_node is None:
            family_title = t(_ROLE_FAMILY_I18N.get(family, "obj_type_other"))
            family_node = QTreeWidgetItem([family_title])
            family_node.setData(0, Qt.ItemDataRole.UserRole, f"family:{family}")
            family_node.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            root_item.addChild(family_node)

        parent = family_node
        current_ref_parts = [family]
        for segment in parts[1:]:
            current_ref_parts.append(segment)
            full_ref = ".".join(current_ref_parts)
            node = None
            for index in range(parent.childCount()):
                child = parent.child(index)
                if str(child.data(0, Qt.ItemDataRole.UserRole) or "") == full_ref:
                    node = child
                    break
            if node is None:
                label = self._display_role_segment(segment)
                node = QTreeWidgetItem([label])
                node.setData(0, Qt.ItemDataRole.UserRole, full_ref)
                node.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                parent.addChild(node)
            parent = node
        self._tree_nodes_by_ref[object_ref] = parent

    def _display_role_segment(self, segment: str) -> str:
        key = _ROLE_SEGMENT_I18N.get(str(segment or "").strip(), "")
        if key:
            return t(key)
        return str(segment or "").strip()

    def _select_role_object_ref(self, object_ref: str) -> None:
        node = self._tree_nodes_by_ref.get(str(object_ref or "").strip())
        if node is None:
            return
        self._objects_tree.setCurrentItem(node)
        current = node
        while current is not None:
            current.setExpanded(True)
            current = current.parent()

    def _on_rights_object_changed(self) -> None:
        item = self._objects_tree.currentItem()
        if item is None:
            return
        object_ref = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        if not object_ref or object_ref.startswith("family:") or object_ref == t("cfg_tree_title"):
            return
        self._current_object_ref = object_ref
        self._selected_object_label.setText(object_ref)
        self._reload_rights_list_for_object(object_ref)
        self._reload_restrictions_for_object(object_ref)

    def _reload_rights_list_for_object(self, object_ref: str) -> None:
        entry = self._ensure_role_entry(object_ref)
        rights_map = dict(entry.get("rights") or {})
        available_rights = self._available_right_names(object_ref)
        self._rights_list.blockSignals(True)
        try:
            self._rights_list.clear()
            for right_name in available_rights:
                item = QListWidgetItem(self._display_right_name(right_name))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                item.setData(Qt.ItemDataRole.UserRole, right_name)
                item.setCheckState(
                    Qt.CheckState.Checked if bool(rights_map.get(right_name, False)) else Qt.CheckState.Unchecked
                )
                self._rights_list.addItem(item)
        finally:
            self._rights_list.blockSignals(False)

    def _reload_restrictions_for_object(self, object_ref: str) -> None:
        self._restrictions_model.blockSignals(True)
        self._restrictions_model.removeRows(0, self._restrictions_model.rowCount())
        entry = self._find_role_entry(object_ref)
        if not entry:
            self._restrictions_model.blockSignals(False)
            return
        try:
            for restriction in entry.get("restrictions") or []:
                if not isinstance(restriction, dict):
                    continue
                self._append_restriction_row(
                    str(restriction.get("right") or ""),
                    str(restriction.get("condition") or ""),
                    str(restriction.get("field") or ""),
                )
        finally:
            self._restrictions_model.blockSignals(False)

    def _available_right_names(self, object_ref: str) -> List[str]:
        names: List[str] = []
        seen: set[str] = set()
        for right_name in _ROLE_DEFAULT_RIGHTS:
            if right_name not in seen:
                names.append(right_name)
                seen.add(right_name)
        for entry in self._role_rights:
            rights_map = entry.get("rights") or {}
            if not isinstance(rights_map, dict):
                continue
            for right_name in rights_map.keys():
                name = str(right_name or "").strip()
                if name and name not in seen:
                    names.append(name)
                    seen.add(name)
        entry = self._find_role_entry(object_ref)
        if entry:
            for right_name in (entry.get("rights") or {}).keys():
                name = str(right_name or "").strip()
                if name and name not in seen:
                    names.append(name)
                    seen.add(name)
        return names

    def _display_right_name(self, right_name: str) -> str:
        key = _ROLE_RIGHT_I18N.get(str(right_name or "").strip(), "")
        if key:
            return t(key)
        raw = str(right_name or "").strip()
        if not raw:
            return ""
        pieces: List[str] = []
        current = raw[0]
        for ch in raw[1:]:
            if ch.isupper() and (not current.endswith(" ") and not current[-1].isupper()):
                pieces.append(current)
                current = ch
            else:
                current += ch
        pieces.append(current)
        return " ".join(piece.strip() for piece in pieces if piece.strip())

    def _on_right_item_changed(self, item: QListWidgetItem) -> None:
        object_ref = str(self._current_object_ref or "").strip()
        if not object_ref:
            return
        entry = self._ensure_role_entry(object_ref)
        rights_map = dict(entry.get("rights") or {})
        right_name = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not right_name:
            return
        rights_map[right_name] = item.checkState() == Qt.CheckState.Checked
        entry["rights"] = rights_map

    def _find_role_entry(self, object_ref: str) -> Dict[str, Any] | None:
        target = str(object_ref or "").strip()
        for entry in self._role_rights:
            if str(entry.get("object") or "").strip() == target:
                return entry
        return None

    def _ensure_role_entry(self, object_ref: str) -> Dict[str, Any]:
        entry = self._find_role_entry(object_ref)
        if entry is not None:
            return entry
        entry = {"object": str(object_ref or "").strip(), "rights": {}, "restrictions": []}
        self._role_rights.append(entry)
        self._role_rights.sort(key=lambda item: str(item.get("object") or "").casefold())
        return entry

    def _add_restriction_template(self) -> None:
        self._templates_model.appendRow([QStandardItem(""), QStandardItem("")])

    def _append_restriction_row(self, right_name: str, condition: str, field_name: str = "") -> None:
        raw_right_name = str(right_name or "").strip()
        raw_field_name = str(field_name or "").strip()
        display_name = raw_field_name or self._display_right_name(raw_right_name)
        right_item = QStandardItem(display_name)
        right_item.setData(raw_right_name, Qt.ItemDataRole.UserRole)
        right_item.setData(raw_field_name, Qt.ItemDataRole.UserRole + 1)
        if raw_field_name and raw_right_name:
            right_item.setToolTip(f"{self._display_right_name(raw_right_name)} • {raw_field_name}")
        right_item.setEditable(False)
        condition_item = QStandardItem(str(condition or ""))
        self._restrictions_model.appendRow([right_item, condition_item])

    def _restriction_rows(self) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for row in range(self._restrictions_model.rowCount()):
            right_item = self._restrictions_model.item(row, 0) or QStandardItem()
            condition_item = self._restrictions_model.item(row, 1) or QStandardItem()
            right_name = str(
                right_item.data(Qt.ItemDataRole.UserRole)
                or right_item.text()
                or ""
            ).strip()
            field_name = str(right_item.data(Qt.ItemDataRole.UserRole + 1) or "").strip()
            condition = str(condition_item.text() or "").strip()
            if right_name and condition:
                row = {"right": right_name, "condition": condition}
                if field_name:
                    row["field"] = field_name
                rows.append(row)
        return rows

    def _sync_current_restrictions_from_model(self) -> None:
        object_ref = str(self._current_object_ref or "").strip()
        if not object_ref:
            return
        entry = self._ensure_role_entry(object_ref)
        entry["restrictions"] = self._restriction_rows()

    def _default_restriction_right(self) -> str:
        object_ref = str(self._current_object_ref or "").strip()
        if not object_ref:
            return ""
        entry = self._ensure_role_entry(object_ref)
        rights_map = dict(entry.get("rights") or {})
        for right_name, enabled in rights_map.items():
            if bool(enabled):
                return str(right_name or "").strip()
        available = self._available_right_names(object_ref)
        return str(available[0] if available else "")

    def _add_restriction(self) -> None:
        right_name = self._default_restriction_right()
        if not right_name:
            return
        self._append_restriction_row(right_name, "")
        row = self._restrictions_model.rowCount() - 1
        self._restrictions_view.selectRow(row)
        self._restrictions_view.setCurrentIndex(self._restrictions_model.index(row, 1))
        self._sync_current_restrictions_from_model()

    def _duplicate_restriction(self) -> None:
        index = self._restrictions_view.currentIndex()
        if not index.isValid():
            return
        row = index.row()
        right_item = self._restrictions_model.item(row, 0) or QStandardItem()
        condition_item = self._restrictions_model.item(row, 1) or QStandardItem()
        self._append_restriction_row(
            str(right_item.data(Qt.ItemDataRole.UserRole) or right_item.text() or ""),
            str(condition_item.text() or ""),
            str(right_item.data(Qt.ItemDataRole.UserRole + 1) or ""),
        )
        new_row = self._restrictions_model.rowCount() - 1
        self._restrictions_view.selectRow(new_row)
        self._sync_current_restrictions_from_model()

    def _remove_restrictions(self) -> None:
        selection = self._restrictions_view.selectionModel()
        if selection is None:
            return
        rows = sorted({index.row() for index in selection.selectedRows()}, reverse=True)
        for row in rows:
            self._restrictions_model.removeRow(row)
        self._sync_current_restrictions_from_model()

    def _on_restriction_item_changed(self, _item: QStandardItem) -> None:
        self._sync_current_restrictions_from_model()

    def _duplicate_restriction_template(self) -> None:
        index = self._templates_view.currentIndex()
        if not index.isValid():
            return
        row = index.row()
        self._templates_model.appendRow(
            [
                QStandardItem(str((self._templates_model.item(row, 0) or QStandardItem()).text())),
                QStandardItem(str((self._templates_model.item(row, 1) or QStandardItem()).text())),
            ]
        )

    def _remove_restriction_template(self) -> None:
        indexes = sorted({index.row() for index in self._templates_view.selectionModel().selectedRows()}, reverse=True)
        for row in indexes:
            self._templates_model.removeRow(row)

    def _collect_rights(self) -> List[dict]:
        out: List[dict] = []
        for entry in self._role_rights:
            object_ref = str(entry.get("object") or "").strip()
            if not object_ref:
                continue
            rights_map = {
                str(key): bool(value)
                for key, value in dict(entry.get("rights") or {}).items()
                if str(key or "").strip()
            }
            restrictions: List[Dict[str, str]] = []
            for item in entry.get("restrictions") or []:
                if not isinstance(item, dict):
                    continue
                right_name = str(item.get("right") or "").strip()
                condition = str(item.get("condition") or "").strip()
                field_name = str(item.get("field") or "").strip()
                if right_name and condition:
                    row = {"right": right_name, "condition": condition}
                    if field_name:
                        row["field"] = field_name
                    restrictions.append(row)
            out.append(
                {
                    "object": object_ref,
                    "rights": rights_map,
                    "restrictions": restrictions,
                }
            )
        return out

    def _collect_restriction_templates(self) -> List[dict]:
        out: List[dict] = []
        for row in range(self._templates_model.rowCount()):
            name = str((self._templates_model.item(row, 0) or QStandardItem()).text() or "").strip()
            condition = str((self._templates_model.item(row, 1) or QStandardItem()).text() or "").strip()
            if not name and not condition:
                continue
            out.append({"name": name, "condition": condition})
        return out

    def _on_apply(self, _) -> None:
        patch = self._main_page.collect()
        patch["title"] = patch["name"] or str(self._payload.get("title") or "")
        patch["rights"] = self._collect_rights()
        patch["restriction_templates"] = self._collect_restriction_templates()
        patch["set_for_new_objects"] = self._chk_set_for_new_objects.isChecked()
        patch["set_for_attributes_by_default"] = self._chk_set_for_attributes_by_default.isChecked()
        patch["independent_rights_of_child_objects"] = self._chk_independent_rights.isChecked()
        self.applyRequested.emit(patch)


class ScheduledJobEditorWidget(QWidget):
    """Редактор регламентного завдання."""

    applyRequested = Signal(dict)
    closeRequested = Signal()

    def __init__(self, title: str, payload: dict | None = None,
                 *, vm: ConfiguratorViewModel | None = None, obj_guid: str = "") -> None:
        super().__init__()
        self._payload = dict(payload or {})
        self._shell = MetaObjectEditorShell(title=title)
        self._shell.applyRequested.connect(self._on_apply)
        self._shell.closeRequested.connect(self.closeRequested.emit)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._shell, 1)
        self._main_page = _SimpleMainPage(self._payload)
        self._shell.set_sections(
            build_editor_sections(
                "scheduled_job",
                {
                    "main": lambda: self._main_page,
                    "schedule": self._build_schedule_page,
                },
            )
        )

    def _build_schedule_page(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w); g.setContentsMargins(20, 20, 20, 20); g.setSpacing(10)
        g.setColumnStretch(1, 1)
        row = 0

        g.addWidget(QLabel(t("scheduled_job.method") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        self._ed_method = QLineEdit(str(self._payload.get("method_name") or ""))
        self._ed_method.setPlaceholderText("CommonModule.MethodName")
        g.addWidget(self._ed_method, row, 1); row += 1

        g.addWidget(QLabel(t("scheduled_job.repeat_period") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        self._ed_period = QLineEdit(str(self._payload.get("repeat_period") or "3600"))
        g.addWidget(self._ed_period, row, 1); row += 1

        self._chk_use = QCheckBox(t("scheduled_job.use"))
        self._chk_use.setChecked(bool(self._payload.get("use", True)))
        g.addWidget(self._chk_use, row, 0, 1, 2); row += 1

        g.setRowStretch(row, 1)
        return w

    def _on_apply(self, _) -> None:
        patch = self._main_page.collect()
        patch["method_name"]   = self._ed_method.text().strip()
        patch["repeat_period"] = int(self._ed_period.text().strip() or 0)
        patch["use"] = self._chk_use.isChecked()
        self.applyRequested.emit(patch)

    def reload_from_vm(self) -> None:
        if self._vm is None or not self._obj_guid:
            return
        try:
            meta = self._vm.get_meta_by_guid(self._obj_guid)
        except Exception:
            meta = None
        if not isinstance(meta, dict):
            return
        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
        self._payload = dict(payload or {})
        title = technical_object_name(meta.get("name"), payload=payload)
        if title:
            try:
                self._shell.set_title(title)
            except Exception:
                pass
        self._main_page = _SimpleMainPage(self._payload)
        self._shell.set_sections(
            build_editor_sections(
                "scheduled_job",
                {
                    "main": lambda: self._main_page,
                    "schedule": self._build_schedule_page,
                },
            )
        )


class EventSubscriptionEditorWidget(QWidget):
    """Редактор підписки на подію."""

    applyRequested = Signal(dict)
    closeRequested = Signal()

    def __init__(self, title: str, payload: dict | None = None,
                 *, vm: ConfiguratorViewModel | None = None, obj_guid: str = "") -> None:
        super().__init__()
        self._payload = dict(payload or {})
        self._shell = MetaObjectEditorShell(title=title)
        self._shell.applyRequested.connect(self._on_apply)
        self._shell.closeRequested.connect(self.closeRequested.emit)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._shell, 1)
        self._main_page = _SimpleMainPage(self._payload)
        self._shell.set_sections(
            build_editor_sections(
                "event_subscription",
                {
                    "main": lambda: self._main_page,
                    "event": self._build_event_page,
                },
            )
        )

    def _build_event_page(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w); g.setContentsMargins(20, 20, 20, 20); g.setSpacing(10)
        g.setColumnStretch(1, 1); row = 0

        g.addWidget(QLabel(t("event_subscription.event_type") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        self._cmb_event = QComboBox()
        events = [
            "BeforeWrite", "OnWrite", "BeforeDelete", "OnDelete",
            "BeforePost", "OnPost", "BeforeUnpost", "OnUnpost",
            "OnSetNewObjectCode", "BeforeClose", "OnClose",
        ]
        for e in events:
            self._cmb_event.addItem(e, e)
        cur = str(self._payload.get("event") or "")
        if cur in events:
            self._cmb_event.setCurrentIndex(events.index(cur))
        g.addWidget(self._cmb_event, row, 1); row += 1

        g.addWidget(QLabel(t("event_subscription.handler") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        self._ed_handler = QLineEdit(str(self._payload.get("handler") or ""))
        self._ed_handler.setPlaceholderText("CommonModule.Handler")
        g.addWidget(self._ed_handler, row, 1); row += 1

        g.setRowStretch(row, 1)
        return w

    def _on_apply(self, _) -> None:
        patch = self._main_page.collect()
        patch["event"]   = self._cmb_event.currentData() or ""
        patch["handler"] = self._ed_handler.text().strip()
        self.applyRequested.emit(patch)

    def reload_from_vm(self) -> None:
        if self._vm is None or not self._obj_guid:
            return
        try:
            meta = self._vm.get_meta_by_guid(self._obj_guid)
        except Exception:
            meta = None
        if not isinstance(meta, dict):
            return
        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
        self._payload = dict(payload or {})
        title = technical_object_name(meta.get("name"), payload=payload)
        if title:
            try:
                self._shell.set_title(title)
            except Exception:
                pass
        self._main_page = _SimpleMainPage(self._payload)
        self._shell.set_sections(
            build_editor_sections(
                "event_subscription",
                {
                    "main": lambda: self._main_page,
                    "event": self._build_event_page,
                },
            )
        )
