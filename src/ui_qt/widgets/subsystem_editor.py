"""src.ui_qt.widgets.subsystem_editor — Subsystem metadata editor."""
from __future__ import annotations

from src.configurator.domain.technical_names import technical_object_name

import os
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import get_lang, t
from src.ui_qt.services.object_editor_profiles import build_editor_sections
from src.ui_qt.viewmodels.configurator_vm import ConfiguratorViewModel
from src.platform.onec_import_state import load_last_onec_import
from src.infra.onec.onec_requisites_enrich import (
    metadata_ref_for_manifest_object,
    metadata_ref_from_import_origin,
)
from src.infra.onec.importer import (
    ZipSource,
    make_directory_source,
    parse_help_page_contents,
    parse_subsystem_command_interface,
)
from src.infra.onec.source_compat import resolve_onec_source
from .meta_object_shell import MetaObjectEditorShell


@dataclass
class SubsystemPayload:
    name: str = ""
    title: str = ""
    synonym: str = ""
    comment: str = ""
    include_in_command_interface: bool = True
    use_one_command: bool = False
    include_help_in_contents: bool = True
    explanation: Any = field(default_factory=dict)
    picture_ref: str = ""
    picture_guid: str = ""
    help_pages: List[str] = field(default_factory=list)
    help_contents: Dict[str, str] = field(default_factory=dict)
    command_interface: Dict[str, Any] = field(default_factory=dict)
    child_subsystems: List[str] = field(default_factory=list)
    content_refs: List[str] = field(default_factory=list)
    objects: List[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, p: dict) -> "SubsystemPayload":
        if not isinstance(p, dict):
            return cls()
        return cls(
            name=str(p.get("name") or ""),
            title=str(p.get("title") or ""),
            synonym=str(p.get("synonym") or ""),
            comment=str(p.get("comment") or ""),
            include_in_command_interface=bool(p.get("include_in_command_interface", True)),
            use_one_command=bool(p.get("use_one_command", False)),
            include_help_in_contents=bool(p.get("include_help_in_contents", True)),
            explanation=p.get("explanation") or {},
            picture_ref=str(p.get("picture_ref") or ""),
            picture_guid=str(p.get("picture_guid") or ""),
            help_pages=list(p.get("help_pages") or []),
            help_contents={str(k): str(v) for k, v in dict(p.get("help_contents") or {}).items()},
            command_interface=dict(p.get("command_interface") or {}),
            child_subsystems=list(p.get("child_subsystems") or []),
            content_refs=list(p.get("content_refs") or []),
            objects=list(p.get("objects") or []),
        )

    def to_patch(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "synonym": self.synonym,
            "comment": self.comment,
            "include_in_command_interface": self.include_in_command_interface,
            "use_one_command": self.use_one_command,
            "include_help_in_contents": self.include_help_in_contents,
            "explanation": self.explanation,
            "picture_ref": self.picture_ref,
            "picture_guid": self.picture_guid,
            "help_pages": list(self.help_pages),
            "help_contents": dict(self.help_contents),
            "command_interface": dict(self.command_interface),
            "child_subsystems": list(self.child_subsystems),
            "content_refs": list(self.content_refs),
            "objects": list(self.objects),
        }


_FUNCTIONAL_REF_PREFIXES = ("FunctionalOption.", "FunctionalOptionsParameter.")
_EXCLUDED_OBJECT_TYPES = {
    "command",
    "common_command",
    "common_form",
    "common_layout",
    "common_module",
    "common_picture",
    "form",
    "functional_option",
    "functional_option_param",
    "layout",
    "module",
    "subsystem",
}
_OBJECT_GROUP_KEYS = {
    "common_attribute": "group.common",
    "common_command": "group.common",
    "common_form": "group.common",
    "common_layout": "group.common",
    "common_module": "group.common",
    "common_picture": "group.common",
    "constants": "client_nav_constants",
    "catalog": "client_nav_catalogs",
    "document": "client_nav_documents",
    "journal": "group.journal",
    "enumeration": "group.enumeration",
    "report": "client_nav_reports",
    "data_processor": "group.data_processor",
    "chart_of_characteristic_types": "group.chart_of_characteristic_types",
    "chart_of_accounts": "group.chart_of_accounts",
    "chart_of_calculation_types": "group.chart_of_calculation_types",
    "register_info": "group.register_info",
    "register_accum": "group.register_accum",
    "register_accounting": "group.register_accum",
    "register_calc": "group.register_accum",
    "exchange_plan": "folder.exchange_plans",
    "business_process": "group.business_process",
    "task": "group.task",
    "role": "group.common",
    "language": "group.common",
    "sequence": "group.common",
}
_OBJECT_GROUP_ORDER = {
    "group.common": 0,
    "client_nav_constants": 1,
    "client_nav_catalogs": 2,
    "client_nav_documents": 3,
    "group.journal": 4,
    "group.enumeration": 5,
    "client_nav_reports": 6,
    "group.data_processor": 7,
    "group.chart_of_characteristic_types": 8,
    "group.chart_of_accounts": 9,
    "group.chart_of_calculation_types": 10,
    "group.register_info": 11,
    "group.register_accum": 12,
    "group.business_process": 13,
    "group.task": 14,
    "folder.exchange_plans": 15,
    "obj_type_other": 99,
}
_FUNCTIONAL_TYPE_TO_REF_PREFIX = {
    "functional_option": "FunctionalOption",
    "functional_option_param": "FunctionalOptionsParameter",
}


def _ordered_help_pages(help_pages: Iterable[str], help_contents: Dict[str, str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for page in help_pages:
        key = str(page or "").strip()
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    for key in help_contents.keys():
        page = str(key or "").strip()
        if page and page not in seen:
            seen.add(page)
            ordered.append(page)
    if not ordered:
        ordered.append(get_lang() or "uk")
    return ordered


@dataclass
class _SubsystemCommandEntry:
    name: str
    title: str
    group_key: str
    group_title: str
    placement: str
    common: bool
    order_rank: int


def _command_display_name(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    for marker in (".Command.", ".StandardCommand."):
        if marker in text:
            return text.split(marker, 1)[1]
    return text.rsplit(".", 1)[-1]


def _command_group_title(group_key: str) -> str:
    key = str(group_key or "").strip()
    if not key:
        return t("subsystem.command_group.other")
    known = {
        "NavigationPanelImportant": "subsystem.command_group.navigation_important",
        "NavigationPanelOrdinary": "subsystem.command_group.navigation_ordinary",
        "NavigationPanelSeeAlso": "subsystem.command_group.navigation_see_also",
        "ActionsPanelTools": "subsystem.command_group.actions_tools",
    }
    if key in known:
        return t(known[key])
    if key.startswith("CommandGroup."):
        return key.split(".", 1)[1]
    return key


def _fallback_command_group(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    for marker in (".Command.", ".StandardCommand."):
        if marker in text:
            return text.split(marker, 1)[0]
    if "." in text:
        return text.rsplit(".", 1)[0]
    return ""


def _open_last_onec_source():
    state = load_last_onec_import()
    repo_root = Path(__file__).resolve().parents[3]
    candidates: list[tuple[str, str]] = []

    state_path = str(state.get("source_path") or "").strip()
    state_kind = str(state.get("source_kind") or "").strip()
    if state_path:
        candidates.append((state_path, state_kind or "auto"))

    env_path = str(os.environ.get("META_LAST_ONEC_SOURCE_PATH") or "").strip()
    env_kind = str(os.environ.get("META_LAST_ONEC_SOURCE_KIND") or "").strip()
    if env_path:
        candidates.append((env_path, env_kind or "auto"))

    candidates.extend(
        [
            (str(repo_root / "WorkedData" / "XMLConf"), "auto"),
            (str(repo_root / "XMLConf"), "auto"),
            (str(repo_root), "auto"),
        ]
    )

    seen: set[tuple[str, str]] = set()
    for source_path, source_kind in candidates:
        pair = (str(source_path or "").strip(), str(source_kind or "").strip())
        if not pair[0] or pair in seen:
            continue
        seen.add(pair)
        try:
            resolved = resolve_onec_source(pair[0], pair[1] or "auto")
        except Exception:
            continue
        effective_path = str(resolved.semantic_path or pair[0])
        if str(resolved.semantic_kind or "").strip().lower() == "zip":
            source_ctx = ZipSource(effective_path)
        else:
            root_dir = effective_path
            if os.path.isfile(root_dir):
                root_dir = os.path.dirname(root_dir)
            source_ctx = make_directory_source(root_dir)
        return source_ctx, resolved
    return None, None


def _recover_help_contents_from_last_import(
    *,
    imported: Dict[str, Any],
    help_pages: Iterable[str],
) -> dict[str, str]:
    help_rel = str((imported or {}).get("help_origin") or "").strip()
    if not help_rel:
        return {}
    source_ctx, _resolved = _open_last_onec_source()
    if source_ctx is None:
        return {}
    with source_ctx if hasattr(source_ctx, "__enter__") else nullcontext(source_ctx) as source:
        path_set = set(source.list_files())
        if help_rel not in path_set:
            return {}
        return parse_help_page_contents(
            source,
            help_rel=help_rel,
            help_pages=list(help_pages or []),
            path_set=path_set,
        )


def _recover_command_interface_from_last_import(*, imported: Dict[str, Any]) -> dict[str, Any]:
    command_rel = str((imported or {}).get("command_interface_origin") or "").strip()
    if not command_rel:
        return {}
    source_ctx, _resolved = _open_last_onec_source()
    if source_ctx is None:
        return {}
    with source_ctx if hasattr(source_ctx, "__enter__") else nullcontext(source_ctx) as source:
        path_set = set(source.list_files())
        if command_rel not in path_set:
            return {}
        return parse_subsystem_command_interface(source.read_bytes(command_rel))


class _SubsystemHelpInfoDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        help_pages: Iterable[str],
        help_contents: Dict[str, str] | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{title}: {t('subsystem.help_info')}")
        self.resize(980, 680)
        self._syncing = False
        self._help_contents = {
            str(key or "").strip(): str(value or "")
            for key, value in dict(help_contents or {}).items()
            if str(key or "").strip()
        }
        self._page_keys = _ordered_help_pages(help_pages, self._help_contents)
        self._current_page = self._pick_initial_page()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(8)
        self._lbl_page = QLabel(t("subsystem.help_page") + ":")
        self._cmb_page = QComboBox()
        for page in self._page_keys:
            self._cmb_page.addItem(page, page)
        self._cmb_page.currentIndexChanged.connect(self._on_page_changed)
        top_bar.addWidget(self._lbl_page)
        top_bar.addWidget(self._cmb_page, 0)
        top_bar.addStretch(1)
        root.addLayout(top_bar)

        self._lbl_missing = QLabel()
        self._lbl_missing.setWordWrap(True)
        self._lbl_missing.setObjectName("metaHint")
        root.addWidget(self._lbl_missing)

        self._edit_html = QTextEdit()
        self._edit_html.textChanged.connect(self._on_rich_text_changed)
        self._edit_source = QPlainTextEdit()
        self._edit_source.textChanged.connect(self._on_source_text_changed)
        self._preview = QTextBrowser()
        self._preview.setOpenExternalLinks(False)

        self._mode_bar = QTabBar()
        self._mode_bar.setObjectName("SubsystemHelpModeBar")
        self._mode_bar.setDrawBase(False)
        self._mode_bar.setMovable(False)
        self._mode_bar.setExpanding(False)
        self._mode_bar.addTab(t("subsystem.help_tab_edit"))
        self._mode_bar.addTab(t("subsystem.help_tab_text"))
        self._mode_bar.addTab(t("subsystem.help_tab_preview"))

        self._mode_stack = QStackedWidget()
        self._mode_stack.addWidget(self._edit_html)
        self._mode_stack.addWidget(self._edit_source)
        self._mode_stack.addWidget(self._preview)
        self._mode_bar.currentChanged.connect(self._mode_stack.setCurrentIndex)

        root.addWidget(self._mode_bar, 0)
        root.addWidget(self._mode_stack, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        page_index = max(0, self._cmb_page.findData(self._current_page))
        self._cmb_page.setCurrentIndex(page_index)
        self._load_page(self._current_page)
        self._mode_bar.setCurrentIndex(0)
        self._mode_stack.setCurrentIndex(0)

    def accept(self) -> None:  # noqa: N802
        self._store_current_page()
        super().accept()

    def result_help_contents(self) -> dict[str, str]:
        return dict(self._help_contents)

    def _pick_initial_page(self) -> str:
        lang = str(get_lang() or "").strip()
        if lang and lang in self._page_keys:
            return lang
        for fallback in ("uk", "en", "ru"):
            if fallback in self._page_keys:
                return fallback
        return self._page_keys[0]

    def _current_html(self) -> str:
        return str(self._edit_source.toPlainText() or "")

    def _set_html(self, html: str) -> None:
        self._syncing = True
        try:
            self._edit_source.setPlainText(str(html or ""))
            self._edit_html.setHtml(str(html or ""))
            self._preview.setHtml(str(html or t("subsystem.help_info_empty") or ""))
        finally:
            self._syncing = False

    def _load_page(self, page: str) -> None:
        self._current_page = str(page or "").strip() or self._pick_initial_page()
        html = self._help_contents.get(self._current_page, "")
        self._lbl_missing.setVisible(not str(html or "").strip())
        self._lbl_missing.setText(t("subsystem.help_info_not_imported"))
        self._set_html(html)

    def _store_current_page(self) -> None:
        page = str(self._current_page or "").strip()
        if not page:
            return
        self._help_contents[page] = self._current_html()

    def _on_page_changed(self, _index: int) -> None:
        page = str(self._cmb_page.currentData() or "").strip()
        if not page or page == self._current_page:
            return
        self._store_current_page()
        self._load_page(page)

    def _on_rich_text_changed(self) -> None:
        if self._syncing:
            return
        html = str(self._edit_html.toHtml() or "")
        self._syncing = True
        try:
            self._edit_source.setPlainText(html)
            self._preview.setHtml(html or t("subsystem.help_info_empty") or "")
        finally:
            self._syncing = False

    def _on_source_text_changed(self) -> None:
        if self._syncing:
            return
        html = str(self._edit_source.toPlainText() or "")
        self._syncing = True
        try:
            self._edit_html.setHtml(html)
            self._preview.setHtml(html or t("subsystem.help_info_empty") or "")
        finally:
            self._syncing = False


class _SubsystemCommandInterfaceDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        command_interface: Dict[str, Any] | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{title}: {t('subsystem.command_interface_summary')}")
        self.resize(1120, 720)
        self._model: Dict[str, Any] = dict(command_interface or {})
        self._items_by_name: dict[str, QTreeWidgetItem] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        hint = QLabel(t("subsystem.command_interface_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        root.addWidget(hint)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(
            [
                t("subsystem.command_column_command"),
                t("subsystem.command_column_visible"),
                t("subsystem.command_column_group"),
                t("subsystem.command_column_placement"),
            ]
        )
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(False)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._tree, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._populate_tree()

    def result_command_interface(self) -> dict[str, Any]:
        model = dict(self._model)
        entries: list[dict[str, Any]] = []
        ordered_names = [
            item.data(0, Qt.ItemDataRole.UserRole)
            for item in self._iter_command_items()
        ]
        existing_visibility = {
            str(item.get("name") or "").strip(): dict(item)
            for item in list(model.get("commands_visibility") or [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        for raw_name in ordered_names:
            name = str(raw_name or "").strip()
            if not name:
                continue
            base = dict(existing_visibility.get(name) or {"name": name})
            item = self._items_by_name.get(name)
            if item is not None:
                base["common"] = item.checkState(1) == Qt.CheckState.Checked
            entries.append(base)
        if entries:
            model["commands_visibility"] = entries
        return model

    def _iter_command_items(self) -> list[QTreeWidgetItem]:
        out: list[QTreeWidgetItem] = []
        for i in range(self._tree.topLevelItemCount()):
            group_item = self._tree.topLevelItem(i)
            for j in range(group_item.childCount()):
                out.append(group_item.child(j))
        return out

    def _populate_tree(self) -> None:
        self._tree.clear()
        self._items_by_name.clear()

        commands_visibility = list(self._model.get("commands_visibility") or [])
        commands_order = list(self._model.get("commands_order") or [])
        commands_placement = list(self._model.get("commands_placement") or [])
        groups_order = [
            str(group or "").strip()
            for group in list(self._model.get("groups_order") or [])
            if str(group or "").strip()
        ]

        visibility_map = {
            str(item.get("name") or "").strip(): bool(item.get("common", False))
            for item in commands_visibility
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        order_map = {
            str(item.get("name") or "").strip(): (
                index,
                str(item.get("command_group") or "").strip(),
            )
            for index, item in enumerate(commands_order)
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        placement_map = {
            str(item.get("name") or "").strip(): (
                str(item.get("command_group") or "").strip(),
                str(item.get("placement") or "").strip(),
            )
            for item in commands_placement
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }

        all_names: list[str] = []
        seen_names: set[str] = set()
        for source in (commands_order, commands_placement, commands_visibility):
            for item in source:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                all_names.append(name)

        entries: list[_SubsystemCommandEntry] = []
        for index, name in enumerate(all_names):
            order_rank, ordered_group = order_map.get(name, (index + 100000, ""))
            placement_group, placement = placement_map.get(name, ("", ""))
            group_key = ordered_group or placement_group or _fallback_command_group(name)
            entries.append(
                _SubsystemCommandEntry(
                    name=name,
                    title=_command_display_name(name),
                    group_key=group_key,
                    group_title=_command_group_title(group_key),
                    placement=placement,
                    common=visibility_map.get(name, False),
                    order_rank=order_rank,
                )
            )

        if not entries:
            empty = QTreeWidgetItem([t("subsystem.command_interface_empty"), "", "", ""])
            empty.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._tree.addTopLevelItem(empty)
            return

        group_rank = {group: index for index, group in enumerate(groups_order)}
        grouped: dict[str, list[_SubsystemCommandEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.group_key, []).append(entry)

        for group_key, group_entries in sorted(
            grouped.items(),
            key=lambda item: (
                group_rank.get(item[0], len(group_rank) + 1000),
                _command_group_title(item[0]).casefold(),
            ),
        ):
            group_item = QTreeWidgetItem([_command_group_title(group_key), "", "", ""])
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._tree.addTopLevelItem(group_item)

            for entry in sorted(group_entries, key=lambda item: (item.order_rank, item.title.casefold())):
                child = QTreeWidgetItem(
                    [
                        entry.title,
                        "",
                        entry.group_title,
                        entry.placement,
                    ]
                )
                child.setData(0, Qt.ItemDataRole.UserRole, entry.name)
                child.setFlags(
                    child.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                child.setCheckState(1, Qt.CheckState.Checked if entry.common else Qt.CheckState.Unchecked)
                group_item.addChild(child)
                self._items_by_name[entry.name] = child
            group_item.setExpanded(True)


class SubsystemEditorWidget(QWidget):
    """1C-like subsystem editor."""

    applyRequested = Signal(dict)
    closeRequested = Signal()

    def __init__(
        self,
        title: str,
        payload: dict | None = None,
        *,
        vm: ConfiguratorViewModel | None = None,
        obj_guid: str = "",
    ) -> None:
        super().__init__()
        self._vm = vm
        self._obj_guid = str(obj_guid or "")
        raw_payload = dict(payload or {}) if isinstance(payload, dict) else {}
        self._imported_meta = dict(raw_payload.get("imported") or {})
        if title and not str(raw_payload.get("name") or "").strip():
            raw_payload["name"] = str(title)
        if title and not str(raw_payload.get("title") or "").strip():
            raw_payload["title"] = str(title)
        self._payload = SubsystemPayload.from_payload(raw_payload)
        self._object_items: list[tuple[str, QTreeWidgetItem]] = []
        self._object_group_by_guid: dict[str, str] = {}
        self._object_titles: dict[str, str] = {}
        self._object_refs_by_guid: dict[str, str] = {}
        self._guid_by_object_ref: dict[str, str] = {}
        self._functional_refs: list[str] = []
        self._functional_titles: dict[str, str] = {}
        self._block_object_changes = False
        self._block_functional_changes = False

        self._shell = MetaObjectEditorShell(title=title)
        self._shell.applyRequested.connect(self._on_apply)
        self._shell.closeRequested.connect(self.closeRequested.emit)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._shell, 1)

        self._w_main = self._build_main_page()
        self._w_functional_options = self._build_functional_options_page()
        self._w_objects = self._build_objects_page()
        self._w_other = self._build_other_page()

        self._shell.set_sections(
            build_editor_sections(
                "subsystem",
                {
                    "main": lambda: self._w_main,
                    "functional_options": lambda: self._w_functional_options,
                    "objects": lambda: self._w_objects,
                    "other": lambda: self._w_other,
                },
            )
        )

        def _load_functional_options_once(page: QWidget = self._w_functional_options) -> None:
            if bool(getattr(page, "_mp_section_loaded", False)):
                return
            self._populate_functional_options()

        def _load_objects_once(page: QWidget = self._w_objects) -> None:
            if bool(getattr(page, "_mp_section_loaded", False)):
                return
            self._populate_objects_tree()

        setattr(self._w_functional_options, "_on_section_shown", _load_functional_options_once)
        setattr(self._w_objects, "_on_section_shown", _load_objects_once)
        self._load_to_ui()

    def _ensure_service_payload_recovered(self) -> None:
        if not self._payload.help_contents and self._payload.help_pages:
            try:
                recovered_help = _recover_help_contents_from_last_import(
                    imported=self._imported_meta,
                    help_pages=self._payload.help_pages,
                )
            except Exception:
                recovered_help = {}
            if recovered_help:
                self._payload.help_contents = recovered_help

        needs_command_interface = (
            not isinstance(self._payload.command_interface, dict)
            or not self._payload.command_interface.get("commands_order")
            or not self._payload.command_interface.get("groups_order")
        )
        if needs_command_interface:
            try:
                recovered_ci = _recover_command_interface_from_last_import(
                    imported=self._imported_meta,
                )
            except Exception:
                recovered_ci = {}
            if recovered_ci:
                self._payload.command_interface = recovered_ci

    def _build_main_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(20, 20, 20, 20)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        row = 0
        grid.addWidget(QLabel(t("prop_name") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        self._ed_name = QLineEdit()
        grid.addWidget(self._ed_name, row, 1)
        row += 1

        grid.addWidget(QLabel(t("prop_synonym") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        self._ed_synonym = QLineEdit()
        grid.addWidget(self._ed_synonym, row, 1)
        row += 1

        grid.addWidget(QLabel(t("prop_comment") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        self._ed_comment = QLineEdit()
        grid.addWidget(self._ed_comment, row, 1)
        row += 1

        self._chk_cmd_interface = QCheckBox(t("subsystem.include_in_cmd_interface"))
        grid.addWidget(self._chk_cmd_interface, row, 0, 1, 2)
        row += 1

        self._chk_use_one_command = QCheckBox(t("subsystem.use_one_command"))
        grid.addWidget(self._chk_use_one_command, row, 0, 1, 2)
        row += 1

        self._btn_command_interface = QPushButton(t("subsystem.command_interface_open"))
        self._btn_command_interface.clicked.connect(self._show_command_interface_dialog)
        grid.addWidget(self._btn_command_interface, row, 1, 1, 1, Qt.AlignmentFlag.AlignLeft)
        row += 1

        grid.addWidget(
            QLabel(t("prop_explanation") + ":"),
            row,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
        )
        self._ed_explanation = QTextEdit()
        self._ed_explanation.setMaximumHeight(90)
        grid.addWidget(self._ed_explanation, row, 1)
        row += 1

        grid.addWidget(QLabel(t("subsystem.picture_ref") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        picture_row = QHBoxLayout()
        picture_row.setContentsMargins(0, 0, 0, 0)
        picture_row.setSpacing(6)
        self._ed_picture_ref = QLineEdit()
        self._btn_picture_pick = QPushButton("...")
        self._btn_picture_pick.setFixedWidth(34)
        self._btn_picture_pick.clicked.connect(self._pick_picture_ref)
        self._btn_picture_clear = QPushButton("×")
        self._btn_picture_clear.setFixedWidth(34)
        self._btn_picture_clear.clicked.connect(self._clear_picture_ref)
        picture_row.addWidget(self._ed_picture_ref, 1)
        picture_row.addWidget(self._btn_picture_pick, 0)
        picture_row.addWidget(self._btn_picture_clear, 0)
        grid.addLayout(picture_row, row, 1)
        row += 1

        grid.setRowStretch(row, 1)
        return page

    def _build_functional_options_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        hint = QLabel(t("subsystem.functional_options_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        bar = QHBoxLayout()
        btn_select_all = QPushButton(t("subsystem.select_all"))
        btn_clear_all = QPushButton(t("subsystem.clear_all"))
        btn_select_all.clicked.connect(lambda: self._set_all_functional_options(True))
        btn_clear_all.clicked.connect(lambda: self._set_all_functional_options(False))
        bar.addWidget(btn_select_all)
        bar.addWidget(btn_clear_all)
        bar.addStretch(1)
        layout.addLayout(bar)

        self._lst_functional_options = QListWidget()
        self._lst_functional_options.itemChanged.connect(self._on_functional_option_changed)
        layout.addWidget(self._lst_functional_options, 1)
        return page

    def _build_objects_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        hint = QLabel(t("subsystem.objects_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        bar = QHBoxLayout()
        btn_select_all = QPushButton(t("subsystem.select_all"))
        btn_clear_all = QPushButton(t("subsystem.clear_all"))
        btn_remove = QPushButton(t("subsystem.remove_selected"))
        btn_select_all.clicked.connect(lambda: self._set_all_object_checks(True))
        btn_clear_all.clicked.connect(lambda: self._set_all_object_checks(False))
        btn_remove.clicked.connect(self._remove_selected_objects)
        bar.addWidget(btn_select_all)
        bar.addWidget(btn_clear_all)
        bar.addWidget(btn_remove)
        bar.addStretch(1)
        layout.addLayout(bar)

        available_lbl = QLabel(t("subsystem.available_objects"))
        available_lbl.setObjectName("metaHint")
        layout.addWidget(available_lbl)

        self._tree_objects = QTreeWidget()
        self._tree_objects.setHeaderHidden(True)
        self._tree_objects.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._tree_objects.itemChanged.connect(self._on_object_item_changed)
        layout.addWidget(self._tree_objects, 1)

        selected_lbl = QLabel(t("subsystem.included_objects"))
        selected_lbl.setObjectName("metaHint")
        layout.addWidget(selected_lbl)

        self._tree_selected_objects = QTreeWidget()
        self._tree_selected_objects.setHeaderHidden(True)
        self._tree_selected_objects.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self._tree_selected_objects, 1)
        return page

    def _build_other_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._btn_help_info = QPushButton(t("subsystem.help_info"))
        self._btn_help_info.clicked.connect(self._open_help_info_dialog)
        layout.addWidget(self._btn_help_info, 0, Qt.AlignmentFlag.AlignLeft)

        self._chk_help = QCheckBox(t("subsystem.include_help"))
        layout.addWidget(self._chk_help)

        layout.addStretch(1)
        return page

    def _populate_functional_options(self) -> None:
        self._block_functional_changes = True
        try:
            self._lst_functional_options.clear()
            self._functional_refs = []
            self._functional_titles = {}

            selected_refs = set(self._selected_functional_refs())
            candidates = self._collect_functional_option_candidates()
            self._functional_refs = [ref for ref, _title in candidates]
            self._functional_titles = {ref: title for ref, title in candidates}

            for ref, title in candidates:
                item = QListWidgetItem(title)
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                item.setData(Qt.ItemDataRole.UserRole, ref)
                item.setCheckState(
                    Qt.CheckState.Checked if ref in selected_refs else Qt.CheckState.Unchecked
                )
                self._lst_functional_options.addItem(item)
        finally:
            self._block_functional_changes = False

    def _populate_objects_tree(self) -> None:
        self._block_object_changes = True
        try:
            self._tree_objects.clear()
            self._object_items.clear()
            self._object_group_by_guid.clear()
            self._object_titles.clear()
            self._object_refs_by_guid.clear()
            self._guid_by_object_ref.clear()

            grouped: dict[str, list[tuple[str, str]]] = {}
            for guid, title, group_key in self._collect_available_objects():
                grouped.setdefault(group_key, []).append((title, guid))
                self._object_titles[guid] = title
                self._object_group_by_guid[guid] = group_key
                obj_ref = self._object_refs_by_guid.get(guid, "")
                if obj_ref:
                    self._guid_by_object_ref[obj_ref] = guid
            selected = set(self._payload.objects)
            selected.update(self._resolved_object_guids_from_content_refs())

            for group_key, items in sorted(
                grouped.items(),
                key=lambda item: (
                    _OBJECT_GROUP_ORDER.get(item[0], _OBJECT_GROUP_ORDER["obj_type_other"]),
                    t(item[0]).casefold(),
                ),
            ):
                group_item = QTreeWidgetItem([t(group_key)])
                group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self._tree_objects.addTopLevelItem(group_item)
                for title, guid in sorted(items, key=lambda item: item[0].casefold()):
                    child = QTreeWidgetItem([title])
                    child.setData(0, Qt.ItemDataRole.UserRole, guid)
                    child.setFlags(
                        child.flags()
                        | Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                    )
                    child.setCheckState(
                        0,
                        Qt.CheckState.Checked if guid in selected else Qt.CheckState.Unchecked,
                    )
                    group_item.addChild(child)
                    self._object_items.append((guid, child))
                group_item.setExpanded(True)
        finally:
            self._block_object_changes = False
        self._refresh_selected_objects_list()

    def _refresh_selected_objects_list(self) -> None:
        selected_guids = [guid for guid, item in self._object_items if item.checkState(0) == Qt.CheckState.Checked]
        self._payload.objects = list(selected_guids)
        self._tree_selected_objects.clear()

        grouped: dict[str, list[tuple[str, str]]] = {}
        for guid in selected_guids:
            title = self._object_titles.get(guid, guid)
            group_key = self._object_group_by_guid.get(guid, "obj_type_other")
            grouped.setdefault(group_key, []).append((title, guid))

        for group_key, items in sorted(
            grouped.items(),
            key=lambda item: (
                _OBJECT_GROUP_ORDER.get(item[0], _OBJECT_GROUP_ORDER["obj_type_other"]),
                t(item[0]).casefold(),
            ),
        ):
            group_item = QTreeWidgetItem([t(group_key)])
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._tree_selected_objects.addTopLevelItem(group_item)
            for title, guid in sorted(items, key=lambda item: item[0].casefold()):
                child = QTreeWidgetItem([title])
                child.setData(0, Qt.ItemDataRole.UserRole, guid)
                group_item.addChild(child)
            group_item.setExpanded(True)

    def _collect_available_objects(self) -> list[tuple[str, str, str]]:
        if self._vm is None:
            return []
        try:
            all_objs = self._vm.list_objects() or []
        except Exception:
            return []

        out: list[tuple[str, str, str]] = []
        for obj in all_objs:
            if str(getattr(obj, "kind", "") or "") != "object":
                continue
            guid = str(getattr(obj, "guid", "") or "").strip()
            if not guid or guid == self._obj_guid:
                continue
            obj_type = str(getattr(obj, "type", "") or "").strip().lower()
            if obj_type in _EXCLUDED_OBJECT_TYPES:
                continue
            title = technical_object_name(getattr(obj, "name", ""), payload=getattr(obj, "payload", None))
            group_key = _OBJECT_GROUP_KEYS.get(obj_type, "obj_type_other")
            name = str(getattr(obj, "name", "") or "").strip()
            origin_path = ""
            metadata_ref = ""
            payload = getattr(obj, "payload", None)
            if isinstance(payload, dict):
                metadata_ref = str(payload.get("metadata_ref") or "").strip()
                imported = payload.get("imported")
                if isinstance(imported, dict):
                    origin_path = str(imported.get("origin") or "").strip()
            if name:
                try:
                    obj_ref = metadata_ref or (metadata_ref_from_import_origin(origin_path) if origin_path else "")
                    if not obj_ref:
                        obj_ref = metadata_ref_for_manifest_object(
                            obj_type=obj_type,
                            name=name,
                            origin_path=origin_path,
                        )
                except Exception:
                    obj_ref = ""
                if obj_ref:
                    self._object_refs_by_guid[guid] = obj_ref
            out.append((guid, title, group_key))
        return out

    def _resolved_object_guids_from_content_refs(self) -> set[str]:
        resolved: set[str] = set()
        for ref in self._payload.content_refs:
            if self._is_functional_ref(ref):
                continue
            guid = self._guid_by_object_ref.get(str(ref or "").strip(), "")
            if guid:
                resolved.add(guid)
        return resolved

    def _collect_functional_option_candidates(self) -> list[tuple[str, str]]:
        items: dict[str, str] = {}
        if self._vm is not None:
            try:
                for obj in self._vm.list_objects() or []:
                    if str(getattr(obj, "kind", "") or "") != "object":
                        continue
                    obj_type = str(getattr(obj, "type", "") or "").strip().lower()
                    prefix = _FUNCTIONAL_TYPE_TO_REF_PREFIX.get(obj_type, "")
                    if not prefix:
                        continue
                    name = str(getattr(obj, "name", "") or "").strip()
                    if not name:
                        continue
                    ref = f"{prefix}.{name}"
                    title = technical_object_name(name, payload=getattr(obj, "payload", None))
                    items[ref] = title
            except Exception:
                items = {}

        for ref in self._selected_functional_refs():
            items.setdefault(ref, ref)

        return sorted(items.items(), key=lambda item: item[1].casefold())

    def _selected_functional_refs(self) -> list[str]:
        return [
            ref
            for ref in self._payload.content_refs
            if self._is_functional_ref(ref)
        ]

    @staticmethod
    def _is_functional_ref(ref: str) -> bool:
        text = str(ref or "").strip()
        return any(text.startswith(prefix) for prefix in _FUNCTIONAL_REF_PREFIXES)

    def _set_all_functional_options(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._block_functional_changes = True
        try:
            for index in range(self._lst_functional_options.count()):
                item = self._lst_functional_options.item(index)
                if item is not None:
                    item.setCheckState(state)
        finally:
            self._block_functional_changes = False

    def _set_all_object_checks(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._block_object_changes = True
        try:
            for _guid, item in self._object_items:
                item.setCheckState(0, state)
        finally:
            self._block_object_changes = False
        self._refresh_selected_objects_list()

    def _remove_selected_objects(self) -> None:
        selected_guids = [
            str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
            for item in self._tree_selected_objects.selectedItems()
            if item.childCount() == 0
        ]
        if not selected_guids:
            return
        self._block_object_changes = True
        try:
            for guid, item in self._object_items:
                if guid in selected_guids:
                    item.setCheckState(0, Qt.CheckState.Unchecked)
        finally:
            self._block_object_changes = False
        self._refresh_selected_objects_list()

    def _pick_picture_ref(self) -> None:
        if self._vm is None:
            return
        candidates: list[tuple[str, str, str]] = []
        try:
            for obj in self._vm.list_objects() or []:
                if str(getattr(obj, "kind", "") or "") != "object":
                    continue
                if str(getattr(obj, "type", "") or "").strip().lower() != "common_picture":
                    continue
                guid = str(getattr(obj, "guid", "") or "").strip()
                name = str(getattr(obj, "name", "") or "").strip()
                if not guid or not name:
                    continue
                title = technical_object_name(name, payload=getattr(obj, "payload", None))
                candidates.append((title, guid, f"CommonPicture.{name}"))
        except Exception:
            return
        if not candidates:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(t("subsystem.picture_ref"))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        lst = QListWidget()
        current_ref = str(self._ed_picture_ref.text() or "").strip()
        for title, guid, ref in sorted(candidates, key=lambda item: item[0].casefold()):
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, (guid, ref))
            lst.addItem(item)
            if ref == current_ref:
                lst.setCurrentItem(item)
        layout.addWidget(lst, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        item = lst.currentItem()
        if item is None:
            return
        guid, ref = item.data(Qt.ItemDataRole.UserRole)
        self._ed_picture_ref.setText(str(ref or ""))
        self._payload.picture_guid = str(guid or "")

    def _clear_picture_ref(self) -> None:
        self._ed_picture_ref.clear()
        self._payload.picture_guid = ""

    def _open_help_info_dialog(self) -> None:
        self._ensure_service_payload_recovered()
        title = self._ed_name.text().strip() or self._payload.name or self._payload.title or self.windowTitle()
        dialog = _SubsystemHelpInfoDialog(
            title=title,
            help_pages=self._payload.help_pages,
            help_contents=self._payload.help_contents,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._payload.help_contents = dialog.result_help_contents()

    def _show_command_interface_dialog(self) -> None:
        self._ensure_service_payload_recovered()
        title = self._ed_name.text().strip() or self._payload.name or self._payload.title or self.windowTitle()
        dialog = _SubsystemCommandInterfaceDialog(
            title=title,
            command_interface=self._payload.command_interface,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._payload.command_interface = dialog.result_command_interface()

    def _on_functional_option_changed(self, _item: QListWidgetItem) -> None:
        if self._block_functional_changes:
            return
        selected_refs: list[str] = []
        for index in range(self._lst_functional_options.count()):
            item = self._lst_functional_options.item(index)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            ref = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if ref:
                selected_refs.append(ref)
        non_functional_refs = [
            ref for ref in self._payload.content_refs if not self._is_functional_ref(ref)
        ]
        self._payload.content_refs = non_functional_refs + selected_refs

    def _on_object_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._block_object_changes:
            return
        if item.childCount() > 0:
            return
        self._refresh_selected_objects_list()

    def _load_to_ui(self) -> None:
        self._ensure_service_payload_recovered()
        if self._vm is not None and self._obj_guid:
            meta = None
            full_payload: dict[str, Any] = {}
            service = getattr(self._vm, "_service", None)
            getter = getattr(service, "manifest_get_payload", None)
            if callable(getter):
                try:
                    full_payload = getter(self._obj_guid) or {}
                except Exception:
                    full_payload = {}
            if not full_payload:
                try:
                    meta = self._vm.get_meta_by_guid(self._obj_guid)
                except Exception:
                    meta = None
                if isinstance(meta, dict):
                    payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
                    full_payload = dict(payload or {})
            if full_payload or isinstance(meta, dict):
                merged = dict(full_payload or {})
                if isinstance(meta, dict):
                    for key in ("name", "title", "parent_guid", "type", "kind"):
                        value = meta.get(key)
                        if value not in (None, ""):
                            merged.setdefault(key, value)
                merged.setdefault("imported", dict(self._imported_meta))
                self._imported_meta = dict(merged.get("imported") or self._imported_meta)
                self._payload = SubsystemPayload.from_payload(merged)
        self._ed_name.setText(self._payload.name)
        self._ed_synonym.setText(self._payload.synonym)
        self._ed_comment.setText(self._payload.comment)
        self._chk_cmd_interface.setChecked(self._payload.include_in_command_interface)
        self._chk_use_one_command.setChecked(self._payload.use_one_command)
        self._ed_explanation.setPlainText(self._localized_text(self._payload.explanation))
        self._ed_picture_ref.setText(self._payload.picture_ref)
        self._btn_command_interface.setEnabled(True)

        self._chk_help.setChecked(self._payload.include_help_in_contents)
        if hasattr(self, "_tree_selected_objects"):
            self._populate_objects_tree()

    def reload_from_vm(self) -> None:
        if self._vm is None or not self._obj_guid:
            return
        try:
            meta = self._vm.get_meta_by_guid(self._obj_guid)
        except Exception:
            meta = None
        if isinstance(meta, dict):
            title = technical_object_name(meta.get("name"), payload=meta.get("payload"))
            if title:
                try:
                    self._shell.set_title(title)
                except Exception:
                    pass
        self._load_to_ui()

    def _collect_payload(self) -> dict:
        self._payload.name = self._ed_name.text().strip()
        self._payload.synonym = self._ed_synonym.text().strip()
        self._payload.comment = self._ed_comment.text().strip()
        self._payload.include_in_command_interface = self._chk_cmd_interface.isChecked()
        self._payload.use_one_command = self._chk_use_one_command.isChecked()
        self._payload.include_help_in_contents = self._chk_help.isChecked()
        self._payload.explanation = self._merge_localized_text(
            self._payload.explanation,
            self._ed_explanation.toPlainText().strip(),
        )
        self._payload.picture_ref = self._ed_picture_ref.text().strip()
        if not self._payload.picture_ref:
            self._payload.picture_guid = ""

        selected_functional_refs: list[str] = []
        for index in range(self._lst_functional_options.count()):
            item = self._lst_functional_options.item(index)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            ref = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if ref:
                selected_functional_refs.append(ref)

        selected_guids = [
            guid for guid, item in self._object_items if item.checkState(0) == Qt.CheckState.Checked
        ]
        selected_object_refs = [
            self._object_refs_by_guid.get(guid, "")
            for guid in selected_guids
            if self._object_refs_by_guid.get(guid, "")
        ]
        non_functional_refs = [
            ref for ref in self._payload.content_refs if not self._is_functional_ref(ref)
        ]
        merged_refs: list[str] = []
        seen_refs: set[str] = set()
        for ref in non_functional_refs + selected_object_refs + selected_functional_refs:
            ref = str(ref or "").strip()
            if not ref or ref in seen_refs:
                continue
            seen_refs.add(ref)
            merged_refs.append(ref)
        self._payload.content_refs = merged_refs
        self._payload.objects = selected_guids
        return self._payload.to_patch()

    def _on_apply(self, _patch: dict) -> None:
        self.applyRequested.emit(self._collect_payload())

    @staticmethod
    def _localized_text(value: Any) -> str:
        if isinstance(value, dict):
            lang = get_lang()
            direct = str(value.get(lang) or "").strip()
            if direct:
                return direct
            for fallback in ("uk", "en", "ru"):
                text = str(value.get(fallback) or "").strip()
                if text:
                    return text
            for text in value.values():
                text_value = str(text or "").strip()
                if text_value:
                    return text_value
            return ""
        return str(value or "").strip()

    @staticmethod
    def _merge_localized_text(existing: Any, text: str) -> Any:
        if isinstance(existing, dict):
            updated = dict(existing)
            lang = get_lang()
            if text:
                updated[lang] = text
            else:
                updated.pop(lang, None)
            return updated
        return text


__all__ = ["SubsystemEditorWidget", "SubsystemPayload"]
