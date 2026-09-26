from __future__ import annotations

from typing import Any
from pathlib import Path
import time

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, Signal, QThread
from PySide6.QtGui import QAction, QActionGroup, QColor, QBrush, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QDialog,
    QMdiArea,
    QToolBar,
    QTabWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from src.configurator.application.config_storage_service import ConfigStorageService
from src.configurator.configurator_actions import ConfiguratorActionsMixin
from src.configurator.configurator_editors import ConfiguratorEditorsMixin
from src.configurator.configurator_props import ConfiguratorPropsMixin
from src.configurator.configurator_state import ConfiguratorStateMixin
from src.configurator.configurator_storage import ConfiguratorStorageMixin
from src.configurator.configurator_toolbar import ConfiguratorToolbarMixin
from src.configurator.configurator_tree import ConfiguratorTreeMixin
from src.configurator.configurator_window_support import _OnecImportWorker
from src.ui_qt.i18n import t
from src.ui_qt.services.icon_provider import IconProvider
from src.ui_qt.widgets.current_page_stacked_widget import CurrentPageStackedWidget
from src.ui_qt.widgets.manifest_properties_panel import ManifestPropertiesPanel
from src.ui_qt.widgets.workspace_problems_panel import WorkspaceProblemsPanel
from src.client.debug_support import register_debug_host

from .ui.widgets import InlineEditDelegate, NodeInfo


class ConfiguratorWindow(
    ConfiguratorToolbarMixin,
    ConfiguratorPropsMixin,
    ConfiguratorActionsMixin,
    ConfiguratorTreeMixin,
    ConfiguratorStorageMixin,
    ConfiguratorEditorsMixin,
    ConfiguratorStateMixin,
    QMainWindow,
):
    ROLE_KIND = int(Qt.ItemDataRole.UserRole) + 1
    ROLE_META = int(Qt.ItemDataRole.UserRole) + 2
    _PROPS_DOCK_MIN_WIDTH = 260
    _PROPS_DOCK_MAX_COMPACT_WIDTH = 360
    _PROPS_DOCK_CLAMP_MARGIN = 32

    saveRequested = Signal()
    refreshRequested = Signal()
    checkRequested = Signal()
    mpdbInspectorRequested = Signal()
    sqliteInspectorRequested = Signal()
    searchChanged = Signal(str)
    subsystemFilterChanged = Signal(str)
    treeSelectChanged = Signal(object)
    treeOpenRequested = Signal(object)
    treeContextMenuRequested = Signal(str, object, object, object)
    itemRenamed = Signal(str, str)

    def __init__(self, *, runtime_url: str = "", db_uid: str = "", db_path: Path | None = None) -> None:
        super().__init__()
        self.db_path: Path | None = Path(db_path).resolve() if db_path else None
        self.runtime_url = runtime_url
        self.db_uid_str = db_uid
        self._cfg_storage = ConfigStorageService(settings=QSettings("MetaPlatform", "Configurator"))
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        except Exception:
            pass
        self._editing_guid: str = ""
        self._editing_old_text: str = ""
        self._props_visible: bool = True
        self._props_dock_default_width_applied: bool = False
        self.act_view_properties = None
        self._open_windows: dict[str, object] = {}
        self._debug_client_process = None
        self._debug_f5_guard_until: float = 0.0
        self._restore_windows_retries_left: int = 3
        self._startup_ui_restored: bool = False
        self._menu_windows = None
        self._win_list_actions_group = QActionGroup(self)
        self._win_list_actions_group.setExclusive(True)
        self._settings = QSettings("MetaPlatform", "Configurator")
        self._config_storage = ConfigStorageService(settings=self._settings)

        self._storage_hb_timer = QTimer(self)
        self._storage_hb_timer.setInterval(ConfigStorageService.HEARTBEAT_INTERVAL_MS)
        self._storage_hb_timer.timeout.connect(lambda: self._safe_storage_heartbeat())
        if self._config_storage.connection() is not None:
            self._storage_hb_timer.start()
        self.setWindowTitle(f"{t('launcher_title')} — {t('btn_config')}")
        self._base_title: str = self.windowTitle()
        self._is_dirty: bool = False
        self.resize(1200, 720)
        self.setMinimumSize(980, 620)

        self.mdi = QMdiArea()
        self.mdi.setObjectName("Workspace")
        # Editors are documents of one IDE workspace, not independent
        # floating windows. Form editors already switch between Form/Module
        # internally, so the outer workspace should only manage documents.
        self.mdi.setViewMode(QMdiArea.ViewMode.TabbedView)
        self.mdi.setDocumentMode(True)
        self.mdi.setTabsMovable(True)
        self.mdi.setTabsClosable(False)
        self.mdi.setTabPosition(QTabWidget.TabPosition.North)
        self.mdi.setBackground(QBrush(QColor("#0B1020")))
        self.mdi.setStyleSheet(
            """
            QMdiArea#Workspace { background: #0B1020; border: none; }
            QMdiArea#Workspace QTabBar {
                background: #0F172A;
                qproperty-drawBase: 0;
            }
            QMdiArea#Workspace QTabBar::tab {
                background: #111827;
                color: #9AAFC8;
                border: 1px solid #22304A;
                border-bottom: none;
                padding: 7px 14px;
                min-width: 120px;
            }
            QMdiArea#Workspace QTabBar::tab:selected {
                background: #1F2A44;
                color: #FFFFFF;
                border-top: 2px solid #6366F1;
            }
            QMdiArea#Workspace QTabBar::tab:hover {
                background: #18233B;
                color: #FFFFFF;
            }
            """
        )
        self.setCentralWidget(self.mdi)
        self.mdi.subWindowActivated.connect(self._on_subwindow_activated)
        register_debug_host(self)

        self._tb_icon_provider = IconProvider()
        tb = QToolBar("main")
        tb.setObjectName("tb_main")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(16, 16))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.setContentsMargins(4, 2, 4, 2)
        tb.setStyleSheet(
            """
            QToolBar#tb_main {
                background: #0F172A;
                border: none;
                border-bottom: 1px solid #22304A;
                spacing: 1px;
                padding: 1px 4px;
            }
            QToolBar#tb_main::separator {
                background: transparent;
                width: 6px;
                margin: 0px 1px;
            }
            QToolBar#tb_main QToolButton {
                border: 1px solid transparent;
                border-radius: 4px;
                min-width: 28px;
                min-height: 28px;
                padding: 3px;
                margin: 0px;
                background: transparent;
                color: #E7EAF0;
            }
            QToolBar#tb_main QToolButton:hover {
                background: rgba(91, 91, 214, 0.18);
                border-color: rgba(91, 91, 214, 0.35);
            }
            QToolBar#tb_main QToolButton:checked {
                background: rgba(91, 91, 214, 0.28);
                border-color: rgba(91, 91, 214, 0.55);
            }
            QToolBar#tb_main QLineEdit {
                min-height: 26px;
                max-height: 26px;
                min-width: 260px;
                border: 1px solid #22304A;
                border-radius: 4px;
                padding: 0px 8px;
                background: #0F172A;
                color: #E7EAF0;
                selection-background-color: rgba(91, 91, 214, 0.32);
            }
            QToolBar#tb_main QToolButton#toolbar_customize_btn {
                border: 1px solid #22304A;
                background: #0F172A;
                min-width: 28px;
                min-height: 28px;
            }
            """
        )
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self._tb_main = tb

        self._toolbar_actions: list = []
        self._toolbar_separators: list = []
        self._toolbar_action_ids: dict = {}

        self._build_main_actions()
        self._populate_main_toolbar()
        self._enforce_main_toolbar_icon_only()
        self._restore_toolbar_visibility()
        self._install_debug_client_shortcuts()
        self.mdi.subWindowActivated.connect(lambda _sub=None: self._update_save_enabled())

        tree_host = QWidget()
        left_l = QVBoxLayout(tree_host)
        left_l.setContentsMargins(10, 10, 10, 10)
        left_l.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("ph_search_dots"))
        self.search.textChanged.connect(self.searchChanged.emit)
        left_l.addWidget(self.search)
        self.cb_subsystem_filter = QComboBox()
        self.cb_subsystem_filter.setObjectName("subsystemFilterCombo")
        self.cb_subsystem_filter.setVisible(False)
        self.cb_subsystem_filter.currentIndexChanged.connect(self._on_subsystem_filter_changed)
        left_l.addWidget(self.cb_subsystem_filter)
        self.tree = QTreeView()
        self.tree.setItemDelegate(InlineEditDelegate(self.tree))
        self.tree.setHeaderHidden(True)
        self.tree.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.EditKeyPressed | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.tree.doubleClicked.connect(self._on_tree_open)
        self.tree.clicked.connect(self._on_tree_select)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._act_tree_add = QAction(t("ctx_add"), self)
        self._act_tree_add.setShortcut("Ins")
        self._act_tree_add.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self._act_tree_add.triggered.connect(self._ctx_add_current)
        self.tree.addAction(self._act_tree_add)
        self._act_tree_rename = QAction(t("ctx_rename"), self)
        self._act_tree_rename.setShortcut("F2")
        self._act_tree_rename.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self._act_tree_rename.triggered.connect(self._ctx_rename_current)
        self.tree.addAction(self._act_tree_rename)
        self._act_tree_delete = QAction(t("ctx_delete"), self)
        self._act_tree_delete.setShortcut("Del")
        self._act_tree_delete.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self._act_tree_delete.triggered.connect(self._ctx_delete_current)
        self.tree.addAction(self._act_tree_delete)
        self.tree.setStyleSheet(
            """
        QTreeView { border: none; outline: 0; }
        QTreeView::item { outline: none; }
        QTreeView::item:focus { outline: none; }
        QTreeView::item:selected:focus { border: 1px solid #818CF8; }
        QTreeView QLineEdit { border: none; background: transparent; padding: 0px; margin: 0px; }
        """
        )
        left_l.addWidget(self.tree, 1)
        self.tree_model = QStandardItemModel()
        self.tree.setModel(self.tree_model)
        self.tree.setUniformRowHeights(True)
        self.dock_tree = QDockWidget(t("cfg_tree_title"), self)
        self.dock_tree.setObjectName("dock_tree")
        self.dock_tree.setWidget(tree_host)
        self.dock_tree.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.dock_tree.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_tree)
        try:
            self.dock_tree.visibilityChanged.connect(
                lambda v: getattr(self, "act_toggle_tree", None) and self.act_toggle_tree.setChecked(bool(v))
            )
        except Exception:
            pass

        self.props_panel = ManifestPropertiesPanel()
        self._props_stack = CurrentPageStackedWidget()
        self._props_stack.addWidget(self.props_panel)
        self._props_stack.currentChanged.connect(lambda _index: self._schedule_normalize_props_dock_width())
        self._form_props_pages: dict[int, QWidget] = {}

        self.dock_props = QDockWidget(t("act_properties"), self)
        self.dock_props.setObjectName("dock_props")
        self.dock_props.setWidget(self._props_stack)
        self.dock_props.setMinimumWidth(self._PROPS_DOCK_MIN_WIDTH)
        self.dock_props.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.dock_props.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_props)
        try:
            self.dock_props.visibilityChanged.connect(lambda v: self.set_properties_visible(bool(v)))
        except Exception:
            pass
        try:
            self.dock_props.topLevelChanged.connect(lambda _floating: self._schedule_normalize_props_dock_width())
        except Exception:
            pass

        self.workspace_problems = WorkspaceProblemsPanel(self)
        self.workspace_problems.openRequested.connect(self._open_module_by_guid)
        self.workspace_problems.diagnosticsChanged.connect(
            self._distribute_workspace_diagnostics
        )
        self.dock_problems = QDockWidget(t("workspace_problems_title"), self)
        self.dock_problems.setObjectName("dock_workspace_problems")
        self.dock_problems.setWidget(self.workspace_problems)
        self.dock_problems.setMinimumHeight(150)
        self.dock_problems.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.dock_problems.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock_problems)
        self.dock_problems.setVisible(False)
        self.dock_problems.visibilityChanged.connect(
            self._on_workspace_problems_visibility_changed
        )

        self._build_menu()

        try:
            app = QApplication.instance()
            if isinstance(app, QApplication):
                app.focusChanged.connect(self._on_focus_changed)
        except Exception:
            pass

        self.statusBar().showMessage(t("status_ready"))

        # Прогрес-бар імпорту — бар + текст праворуч— один widget-контейнер
        from PySide6.QtWidgets import QHBoxLayout
        _progress_host = QWidget(self)
        _progress_host.setVisible(False)
        _ph_layout = QHBoxLayout(_progress_host)
        _ph_layout.setContentsMargins(4, 0, 8, 0)
        _ph_layout.setSpacing(6)

        self._import_progress_bar = QProgressBar(_progress_host)
        self._import_progress_bar.setRange(0, 100)
        self._import_progress_bar.setValue(0)
        self._import_progress_bar.setTextVisible(False)
        self._import_progress_bar.setFixedWidth(180)
        self._import_progress_bar.setFixedHeight(18)
        self._import_progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 9px;
                background-color: rgba(91, 91, 214, 0.15);
                padding: 0px;
            }
            QProgressBar::chunk {
                border-radius: 9px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0   #7C7CE8,
                    stop:0.5 #5B5BD6,
                    stop:1   #4747C2
                );
            }
        """)
        _ph_layout.addWidget(self._import_progress_bar)

        self._import_progress_label = QLabel(_progress_host)
        self._import_progress_label.setStyleSheet(
            "color: #374151; font-size: 9pt; background: transparent;"
        )
        self._import_progress_label.setMinimumWidth(60)
        self._import_progress_label.setMaximumWidth(400)
        _ph_layout.addWidget(self._import_progress_label)

        self._import_progress_host = _progress_host
        self.statusBar().addPermanentWidget(_progress_host)

        # Пульсація opacity під час імпорту
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        self._import_pulse_anim = QPropertyAnimation(_progress_host, b"windowOpacity")
        self._import_pulse_anim.setDuration(900)
        self._import_pulse_anim.setStartValue(1.0)
        self._import_pulse_anim.setKeyValueAt(0.5, 0.6)
        self._import_pulse_anim.setEndValue(1.0)
        self._import_pulse_anim.setEasingCurve(QEasingCurve.Type.SineCurve)
        self._import_pulse_anim.setLoopCount(-1)  # безкінецно
        self._import_progress_dialog: QDialog | None = None
        self._import_thread: QThread | None = None
        self._import_worker: _OnecImportWorker | None = None
        self._import_status_timer = QTimer(self)
        self._import_status_timer.setInterval(400)
        self._import_status_timer.timeout.connect(self._poll_onec_import_status)
        self._import_status_gateway = None
        self._import_session_id: str = ""
        self._vm = None

    def bind(self, vm) -> None:
        self._vm = vm
        self._icon_provider = getattr(vm, "icon_provider", None)
        self.tree_model = vm.tree_model
        self.tree.setModel(self.tree_model)
        try:
            vm._before_tree_rebuild = self.begin_tree_rebuild
            vm._after_tree_rebuild = self.end_tree_rebuild
        except Exception:
            pass
        try:
            self.saveRequested.connect(vm.on_save)
            self.refreshRequested.connect(vm.on_refresh)
            self.checkRequested.connect(vm.on_check)
            self.searchChanged.connect(vm.on_search)
            if hasattr(vm, "on_subsystem_filter"):
                self.subsystemFilterChanged.connect(vm.on_subsystem_filter)
            self.treeSelectChanged.connect(vm.on_select)
            self.treeOpenRequested.connect(vm.on_open)
            self.itemRenamed.connect(vm.on_item_renamed)
            vm.statusChanged.connect(self.set_status)
            vm.propertiesRowsChanged.connect(self.props_panel.set_properties_rows)
            vm.expandDefaultRequested.connect(self.expand_default)
            if hasattr(vm, "editorStateChanged"):
                vm.editorStateChanged.connect(self.props_panel.update_editor)
                vm.editorStateChanged.connect(self._on_editor_state_changed)
            self.props_panel.editorFieldChanged.connect(vm.on_editor_field_changed)
            self.props_panel.editorPayloadChanged.connect(vm.on_editor_payload_changed)
            if hasattr(self, "_open_module_ref"):
                self.props_panel.openModuleRequested.connect(lambda key, value: self._open_module_ref(value, key))
            self.props_panel.applyRequested.connect(self.saveRequested.emit)
            self.props_panel.revertRequested.connect(vm.on_editor_revert)
            service = getattr(vm, "_service", None)
            if service is not None:
                self.workspace_problems.set_loader(self._load_workspace_problems)
                self.saveRequested.connect(
                    lambda: QTimer.singleShot(
                        250,
                        self._refresh_workspace_problems_if_visible,
                    )
                )
                self.refreshRequested.connect(
                    lambda: QTimer.singleShot(
                        250,
                        self._refresh_workspace_problems_if_visible,
                    )
                )
            vm.openEditorRequested.connect(self.open_object_tab)
            vm.openEditorNewRequested.connect(self.open_object_tab_new)
            if hasattr(vm, "openPicturesGalleryRequested"):
                vm.openPicturesGalleryRequested.connect(self.open_pictures_gallery)
            if hasattr(vm, "openSvgEditorRequested"):
                vm.openSvgEditorRequested.connect(lambda key, title: self.open_svg_editor(key, title))
            if hasattr(vm, "openPictureEditorRequested"):
                vm.openPictureEditorRequested.connect(lambda key, title, mime: self.open_picture_editor(key, title, mime))
        except Exception:
            pass

    def _on_workspace_problems_visibility_changed(self, visible: bool) -> None:
        action = getattr(self, "act_view_problems", None)
        if action is not None:
            action.setChecked(bool(visible))
        if visible:
            self.workspace_problems.refresh_async()

    def _refresh_workspace_problems_if_visible(self) -> None:
        if self.dock_problems.isVisible():
            self.workspace_problems.refresh_async()

    def _navigate_workspace_problem(self, delta: int) -> bool:
        if not self.dock_problems.isVisible():
            self.dock_problems.setVisible(True)
        return self.workspace_problems.navigate(int(delta or 1))

    def _distribute_workspace_diagnostics(self, diagnostics: object) -> None:
        rows = []
        for item in list(diagnostics or []):
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["display_message"] = WorkspaceProblemsPanel._display_message(row)
            rows.append(row)
        for editor in self.findChildren(QWidget):
            setter = getattr(editor, "set_workspace_diagnostics", None)
            if callable(setter):
                setter(rows)

    def _load_workspace_problems(self) -> dict:
        service = getattr(getattr(self, "_vm", None), "_service", None)
        if service is None:
            return {"generation": 0, "diagnostics": []}
        deadline = time.monotonic() + 90.0
        info = service.get_workspace_semantic_index_info() or {}
        while not bool(info.get("ready")) and time.monotonic() < deadline:
            time.sleep(0.5)
            info = service.get_workspace_semantic_index_info() or {}
        diagnostics = service.get_workspace_semantic_diagnostics(limit=5000)
        info = service.get_workspace_semantic_index_info() or info
        return {
            "generation": int(info.get("generation") or 0),
            "diagnostics": diagnostics,
        }

    def current_selection_info(self):
        try:
            idx = self.tree.currentIndex()
        except Exception:
            return None
        try:
            return self.node_info_from_index(idx)
        except Exception:
            return None

    def current_subsystem_filter_guid(self) -> str:
        try:
            return str(self.cb_subsystem_filter.currentData() or "")
        except Exception:
            return ""

    def find_subsystem_filter_index(self, guid: str) -> int:
        try:
            return int(self.cb_subsystem_filter.findData(str(guid or "").strip()))
        except Exception:
            return -1

    def select_guid(self, guid: str):
        guid = str(guid or "").strip()
        if not guid:
            return None
        model = self.tree_model
        root = model.invisibleRootItem()

        def walk(item):
            for row in range(item.rowCount()):
                child = item.child(row)
                if child is None:
                    continue
                meta = child.data(self.ROLE_META)
                if isinstance(meta, dict) and str(meta.get("guid") or "").strip() == guid:
                    idx = child.index()
                    try:
                        self.tree.setCurrentIndex(idx)
                        self.tree.scrollTo(idx)
                        self.tree.setFocus(Qt.FocusReason.OtherFocusReason)
                    except Exception:
                        pass
                    info = self.node_info_from_index(idx)
                    if info is not None:
                        try:
                            self.treeSelectChanged.emit(info)
                        except Exception:
                            pass
                        try:
                            self._show_manifest_props()
                        except Exception:
                            pass
                    return info
                found = walk(child)
                if found is not None:
                    return found
            return None

        return walk(root)

    def tree_snapshot(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        model = self.tree_model
        root = model.invisibleRootItem()

        def walk(item, depth: int = 0) -> None:
            for row in range(item.rowCount()):
                child = item.child(row)
                if child is None:
                    continue
                meta = child.data(self.ROLE_META)
                kind = str(child.data(self.ROLE_KIND) or "")
                entry: dict[str, Any] = {
                    "depth": int(depth),
                    "text": str(child.text() or ""),
                    "kind": kind,
                    "guid": "",
                    "type": "",
                    "name": "",
                    "title": "",
                    "parent_guid": "",
                    "payload_keys": [],
                }
                if isinstance(meta, dict):
                    entry["guid"] = str(meta.get("guid") or "")
                    entry["type"] = str(meta.get("type") or "")
                    entry["name"] = str(meta.get("name") or "")
                    entry["title"] = str(meta.get("title") or "")
                    entry["parent_guid"] = str(meta.get("parent_guid") or "")
                    payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
                    entry["payload_keys"] = sorted(list(payload.keys()))
                rows.append(entry)
                walk(child, depth + 1)

        walk(root)
        return rows

    def _on_subsystem_filter_changed(self, index: int) -> None:
        guid = str(self.cb_subsystem_filter.currentData() or "")
        self.subsystemFilterChanged.emit(guid)
        vm = getattr(self, "_vm", None)
        if vm is not None and hasattr(vm, "reload"):
            vm.reload()

    def refresh_subsystem_filter_combo(self) -> None:
        vm = getattr(self, "_vm", None)
        if vm is None or not hasattr(vm, "list_subsystems"):
            self.cb_subsystem_filter.setVisible(False)
            return
        subsystems = vm.list_subsystems()
        if not subsystems:
            self.cb_subsystem_filter.setVisible(False)
            return
        self.cb_subsystem_filter.blockSignals(True)
        try:
            current_guid = str(self.cb_subsystem_filter.currentData() or "")
            self.cb_subsystem_filter.clear()
            self.cb_subsystem_filter.addItem(t("tree_filter_all_subsystems"), "")
            for sub in subsystems:
                guid = str(sub.get("guid") or "")
                title = str(sub.get("path") or sub.get("title") or sub.get("name") or guid)
                if guid:
                    self.cb_subsystem_filter.addItem(title, guid)
            idx = self.cb_subsystem_filter.findData(current_guid)
            self.cb_subsystem_filter.setCurrentIndex(max(idx, 0))
        finally:
            self.cb_subsystem_filter.blockSignals(False)
        self.cb_subsystem_filter.setVisible(True)


__all__ = ["ConfiguratorWindow", "NodeInfo"]
