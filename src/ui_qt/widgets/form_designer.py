from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.configurator.domain.default_commands import default_commands_for_context
from src.dsl.module_introspection import introspect_module_source
from src.ui_qt.i18n import bind, get_lang, t
from src.ui_qt.widgets.code_editor_widget import (
    _ce_icon,
    common_module_completion_members_from_vm,
    create_metascript_code_edit,
    identifier_chain_at,
    metadata_completion_objects_from_vm,
    resolve_definition_target,
)
from src.ui_qt.widgets.form_designer_canvas import FormDesignerCanvasView
from src.ui_qt.widgets.form_designer_interaction import FormDesignerInteractionMixin
from src.ui_qt.widgets.form_designer_model import FormDesignerModelMixin
from src.ui_qt.widgets.form_designer_preview import FormDesignerPreviewMixin
from src.ui_qt.widgets.form_designer_properties import FormDesignerPropertiesMixin
from src.ui_qt.widgets.form_designer_styling import FormDesignerStylingMixin
from src.ui_qt.widgets.form_designer_support import (
    FormElementTypeDialog,
    FormLockTarget,
    FormDesignerTreeWidget,
    FormRequisitesList,
    FormToolboxList,
)
from src.ui_qt.widgets.form_window_frame import FormWindowFrame


class FormDesignerWidget(
    FormDesignerPreviewMixin,
    FormDesignerPropertiesMixin,
    FormDesignerInteractionMixin,
    FormDesignerModelMixin,
    FormDesignerStylingMixin,
    QWidget,
):
    """Visual form designer (graphical)."""

    dirtyChanged = Signal(bool)
    saveRequested = Signal(dict)
    definitionRequested = Signal(dict)
    usagesRequested = Signal(dict)

    def _new_object_tree(self, header_keys: tuple[str, str]) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels([t(header_keys[0]), t(header_keys[1])])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(False)
        tree.setUniformRowHeights(True)
        tree.setIndentation(16)
        tree.setAnimated(False)
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        return tree

    def __init__(
        self,
        *,
        vm: Any,
        form_guid: str,
        form_title: str,
        form_meta_payload: dict[str, Any],
        storage_service: Any | None = None,
        lock_target: FormLockTarget | None = None,
    ) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._vm = vm
        self._form_guid = str(form_guid or "")
        self._form_title = str(form_title or "")
        self._storage = storage_service
        self._lock_target = lock_target
        self._dirty = False

        payload = dict(form_meta_payload or {})
        payload = self._merge_payload_from_storage_latest(payload)
        self._payload = dict(payload or {})
        imported = self._payload.get("imported") if isinstance(self._payload.get("imported"), dict) else {}
        self._is_onec_imported = str(imported.get("source") or "").strip().lower() == "1c"
        self._model = self._load_model(form_title=form_title, payload=payload)
        self._module_text = self._load_form_module_text(payload)
        self._saved_module_text = self._module_text
        self._module_dirty = False
        self._form_meta_cache: dict[str, Any] | None = None
        self._forms_folder_meta_cache: dict[str, Any] | None = None
        self._owner_meta_cache: dict[str, Any] | None = None
        self._available_requisites_cache: list[dict[str, Any]] | None = None
        self._node_by_id: dict[str, Any] = {}
        self._parent_by_id: dict[str, str] = {}
        self._tree_item_by_id: dict[str, Any] = {}
        self._ui_guard = False
        self._preview_refresh_timer = QTimer(self)
        self._preview_refresh_timer.setSingleShot(True)
        self._preview_refresh_timer.timeout.connect(self._render_preview)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setObjectName("FormDesignerRoot")

        split = QSplitter(Qt.Orientation.Vertical)
        self._main_splitter = split
        self._workbench_splitter = split
        split.setObjectName("FormDesignerWorkbenchSplit")
        split.setHandleWidth(5)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        top_split = QSplitter(Qt.Orientation.Horizontal)
        self._top_splitter = top_split
        top_split.setObjectName("FormDesignerTopSplit")
        top_split.setHandleWidth(5)
        top_split.setChildrenCollapsible(False)
        split.addWidget(top_split)

        left_tabs = QTabWidget()
        self._left_tabs = left_tabs
        left_tabs.setObjectName("FormDesignerLeftTabs")
        left_tabs.setDocumentMode(True)
        left_tabs.setMinimumWidth(280)
        top_split.addWidget(left_tabs)

        elements_page = QWidget()
        elements_page.setObjectName("FormDesignerElementsPage")
        elements_layout = QVBoxLayout(elements_page)
        elements_layout.setContentsMargins(0, 0, 0, 0)
        elements_layout.setSpacing(0)

        elements_toolbar = QToolBar(elements_page)
        self._elements_toolbar = elements_toolbar
        elements_toolbar.setObjectName("FormElementsToolbar")
        elements_toolbar.setMovable(False)
        elements_toolbar.setFloatable(False)

        self.toolbox = FormToolboxList(elements_page)
        self._populate_toolbox()
        self.toolbox.itemDoubleClicked.connect(self._on_toolbox_double_clicked)
        self.toolbox.currentItemChanged.connect(lambda *_: self._sync_toolbox_hint())
        self.toolbox.hide()

        self._toolbox_combo = QComboBox(elements_toolbar)
        self._toolbox_combo.setObjectName("FormElementTypeCombo")
        for index in range(self.toolbox.count()):
            item = self.toolbox.item(index)
            self._toolbox_combo.addItem(item.text(), item.data(Qt.ItemDataRole.UserRole))
        self._toolbox_combo.currentIndexChanged.connect(self._on_toolbox_combo_changed)
        if self._toolbox_combo.count() > 0:
            self._toolbox_combo.setCurrentIndex(0)
            self.toolbox.setCurrentRow(0)
        # The actual type is selected in the Add dialog. Keep this private
        # combo only as a compatibility bridge for legacy toolbox callers.
        self._toolbox_combo.hide()

        def _elements_button(icon_name: str, tooltip_key: str, handler, color: str = "#AFC4DF") -> QToolButton:
            button = QToolButton(elements_toolbar)
            button.setIcon(_ce_icon(icon_name, color, 16))
            button.setToolTip(t(tooltip_key))
            button.setAccessibleName(t(tooltip_key))
            button.setAutoRaise(True)
            button.clicked.connect(handler)
            elements_toolbar.addWidget(button)
            return button

        self._btn_tree_add = _elements_button("plus", "form_add_selected_tool", self._show_add_element_dialog, "#86EFAC")
        self._btn_tree_delete = _elements_button("trash-2", "form_delete_selected", self._delete_selected, "#F87171")
        self._btn_tree_up = _elements_button("arrow-up", "form_move_selected_up", lambda: self._move_selected(-1))
        self._btn_tree_down = _elements_button("arrow-down", "form_move_selected_down", lambda: self._move_selected(1))
        elements_layout.addWidget(elements_toolbar, 0)

        self.tree = FormDesignerTreeWidget()
        self.tree.set_drop_validator(self._can_reparent_tree_node)
        self.tree.currentItemChanged.connect(self._on_tree_selection)
        self.tree.installEventFilter(self)
        self.tree.orderChanged.connect(self._on_tree_order_changed)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_tree_context_menu)
        elements_layout.addWidget(self.tree, 1)
        left_tabs.addTab(elements_page, t("form_tab_elements"))

        self._command_interface_tree = QTreeWidget()
        self._command_interface_tree.setObjectName("FormDesignerCommandInterface")
        self._command_interface_tree.setHeaderHidden(True)
        self._command_interface_tree.setIndentation(18)
        self._command_interface_tree.setUniformRowHeights(True)
        self._command_interface_tree.setAnimated(False)
        self._command_interface_tree.currentItemChanged.connect(self._on_command_interface_selection)
        left_tabs.addTab(self._command_interface_tree, t("form_tab_command_interface"))

        object_tabs = QTabWidget()
        self._object_tabs = object_tabs
        object_tabs.setObjectName("FormDesignerObjectTabs")
        object_tabs.setDocumentMode(True)
        object_tabs.setMinimumWidth(360)
        top_split.addWidget(object_tabs)

        self.requisites = FormRequisitesList()
        self.requisites.itemChanged.connect(self._on_requisite_item_changed)
        object_tabs.addTab(self.requisites, t("form_tab_requisites"))

        command_tabs = QTabWidget()
        self._command_scope_tabs = command_tabs
        command_tabs.setObjectName("FormDesignerCommandScopeTabs")
        self._form_commands_tree = self._new_object_tree(("form_col_command", "form_col_action"))
        self._standard_commands_tree = self._new_object_tree(("form_col_command", "form_col_action"))
        self._global_commands_tree = self._new_object_tree(("form_col_command", "form_col_action"))
        for command_tree in (self._form_commands_tree, self._standard_commands_tree, self._global_commands_tree):
            command_tree.itemDoubleClicked.connect(self._add_command_to_form)
        command_tabs.addTab(self._form_commands_tree, t("form_commands_form"))
        command_tabs.addTab(self._standard_commands_tree, t("form_commands_standard"))
        command_tabs.addTab(self._global_commands_tree, t("form_commands_global"))
        object_tabs.addTab(command_tabs, t("form_tab_commands"))

        self._parameters_tree = self._new_object_tree(("form_col_parameter", "form_col_type"))
        object_tabs.addTab(self._parameters_tree, t("form_tab_parameters"))

        top_split.setStretchFactor(0, 1)
        top_split.setStretchFactor(1, 1)
        top_split.setSizes([560, 640])

        center_tabs = QTabWidget()
        self._center_stack = center_tabs
        self._center_tabs = center_tabs
        center_tabs.setObjectName("FormDesignerCenterTabs")
        center_tabs.setDocumentMode(True)
        center_tabs.setTabPosition(QTabWidget.TabPosition.South)
        center_tabs.setMinimumHeight(320)
        self._center_tabbar = center_tabs.tabBar()
        self._center_tabbar.setObjectName("FormDesignerModeTabs")
        self._center_tabbar.setExpanding(False)
        self._form_split_sizes = [300, 620]
        split.addWidget(center_tabs)

        pane_controls = QWidget(center_tabs)
        pane_controls_layout = QHBoxLayout(pane_controls)
        pane_controls_layout.setContentsMargins(0, 0, 4, 0)
        pane_controls_layout.setSpacing(2)
        self._pane_controls = pane_controls
        self._btn_toggle_left = QToolButton(pane_controls)
        self._btn_toggle_left.setObjectName("FormDesignerPaneToggle")
        self._btn_toggle_left.setIcon(_ce_icon("panel-left-close", "#9FB4CF", 16))
        self._btn_toggle_left.setToolTip(t("form_hide_structure"))
        self._btn_toggle_left.setAccessibleName(t("form_hide_structure"))
        self._btn_toggle_left.clicked.connect(self._toggle_left_panel)
        pane_controls_layout.addWidget(self._btn_toggle_left)

        self._btn_toggle_props = QToolButton(pane_controls)
        self._btn_toggle_props.setObjectName("FormDesignerPaneToggle")
        self._btn_toggle_props.setIcon(_ce_icon("panel-right-close", "#9FB4CF", 16))
        self._btn_toggle_props.setToolTip(t("form_hide_properties"))
        self._btn_toggle_props.setAccessibleName(t("form_hide_properties"))
        self._btn_toggle_props.clicked.connect(self._toggle_properties_panel)
        pane_controls_layout.addWidget(self._btn_toggle_props)
        center_tabs.setCornerWidget(pane_controls, Qt.Corner.BottomRightCorner)
        center_tabs.currentChanged.connect(self._on_workspace_tab_changed)

        design_host = QWidget()
        design_host.setObjectName("FormDesignerDesignTab")
        try:
            design_host.setStyleSheet("background: transparent;")
        except Exception:
            pass
        design_l = QVBoxLayout(design_host)
        design_l.setContentsMargins(8, 8, 8, 8)
        design_l.setSpacing(8)

        # These compatibility controls keep the existing editing actions wired,
        # but no longer occupy the form surface. The tree toolbar and direct
        # manipulation provide the same commands without duplicating UI chrome.
        self._design_hint = QLabel("", design_host)
        self._design_hint.setObjectName("FormDesignerHint")
        self._design_hint.setWordWrap(True)
        self._design_hint.hide()

        self._design_toolbar = QToolBar(design_host)
        self._design_toolbar.setObjectName("FormDesignToolbar")
        self._design_toolbar.setMovable(False)
        self._design_toolbar.setFloatable(False)
        self._design_toolbar.setIconSize(self._design_toolbar.iconSize())

        self._act_snap_grid = self._design_toolbar.addAction(t("form_snap_to_grid"))
        self._act_snap_grid.setIcon(_ce_icon("grid-3x3", "#8FB7FF", 16))
        self._act_snap_grid.setCheckable(True)
        self._act_snap_grid.setChecked(True)
        self._act_snap_grid.toggled.connect(lambda v: self._on_snap_grid_toggled(bool(v)))

        self._design_toolbar.addSeparator()

        def _tool_button(icon_name: str, tooltip_key: str, *, color: str = "#AFC4DF") -> QToolButton:
            button = QToolButton(self._design_toolbar)
            button.setIcon(_ce_icon(icon_name, color, 16))
            button.setIconSize(self._design_toolbar.iconSize())
            button.setToolTip(t(tooltip_key))
            button.setAccessibleName(t(tooltip_key))
            button.setAutoRaise(True)
            return button

        self._btn_add_field = _tool_button("file-plus", "form_add_text_field", color="#86EFAC")
        self._btn_add_field.clicked.connect(lambda: self._add_control("TextBox"))
        self._design_toolbar.addWidget(self._btn_add_field)

        self._btn_add_selected = _tool_button("plus", "form_add_selected_tool", color="#86EFAC")
        self._btn_add_selected.clicked.connect(self._show_add_element_dialog)
        self._design_toolbar.addWidget(self._btn_add_selected)

        self._btn_add_label = _tool_button("type", "form_add_label", color="#86EFAC")
        self._btn_add_label.clicked.connect(lambda: self._add_control("Label"))
        self._design_toolbar.addWidget(self._btn_add_label)

        self._btn_delete_node = _tool_button("trash-2", "form_delete_selected", color="#F87171")
        self._btn_delete_node.clicked.connect(self._delete_selected)
        self._design_toolbar.addWidget(self._btn_delete_node)

        self._btn_duplicate_node = _tool_button("copy", "form_duplicate_selected")
        self._btn_duplicate_node.clicked.connect(self._duplicate_selected)
        self._design_toolbar.addWidget(self._btn_duplicate_node)

        self._btn_move_up = _tool_button("arrow-up", "form_move_selected_up")
        self._btn_move_up.clicked.connect(lambda: self._move_selected(-1))
        self._design_toolbar.addWidget(self._btn_move_up)

        self._btn_move_down = _tool_button("arrow-down", "form_move_selected_down")
        self._btn_move_down.clicked.connect(lambda: self._move_selected(1))
        self._design_toolbar.addWidget(self._btn_move_down)

        self._design_toolbar.addSeparator()

        self._lbl_design_grid = QLabel(t("form_grid_size"))
        self._design_toolbar.addWidget(self._lbl_design_grid)
        self._sp_design_grid = QSpinBox()
        self._sp_design_grid.setRange(2, 200)
        self._sp_design_grid.setValue(10)
        self._sp_design_grid.valueChanged.connect(lambda v: self._on_grid_size_changed(int(v)))
        self._design_toolbar.addWidget(self._sp_design_grid)

        self._design_toolbar.addSeparator()

        self._act_align_left = self._design_toolbar.addAction(t("form_align_left"))
        self._act_align_right = self._design_toolbar.addAction(t("form_align_right"))
        self._act_align_top = self._design_toolbar.addAction(t("form_align_top"))
        self._act_align_bottom = self._design_toolbar.addAction(t("form_align_bottom"))
        self._act_align_left.triggered.connect(lambda: self._align_selected("left"))
        self._act_align_right.triggered.connect(lambda: self._align_selected("right"))
        self._act_align_top.triggered.connect(lambda: self._align_selected("top"))
        self._act_align_bottom.triggered.connect(lambda: self._align_selected("bottom"))
        try:
            for action in (self._act_align_left, self._act_align_right, self._act_align_top, self._act_align_bottom):
                action.setEnabled(False)
        except Exception:
            pass
        self._design_toolbar.hide()

        self._design_stack = QStackedWidget()
        self._design_window_scroll = QScrollArea()
        self._design_window_scroll.setObjectName("CanvasScroll")
        self._design_window_scroll.setWidgetResizable(True)
        self._design_window_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._design_window_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        try:
            self._design_window_scroll.setStyleSheet("background: #F8FAFC;")
            self._design_window_scroll.viewport().setStyleSheet("background: #F8FAFC;")
        except Exception:
            pass
        design_l.addWidget(self._design_window_scroll, 1)

        self._design_window_center = QWidget()
        self._design_window_center.setMinimumWidth(0)
        self._design_window_center.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        center_l = QVBoxLayout(self._design_window_center)
        center_l.setContentsMargins(0, 0, 0, 0)
        center_l.setSpacing(0)
        center_l.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._design_window_scroll.setWidget(self._design_window_center)

        self._design_window_frame = FormWindowFrame()
        center_l.addWidget(self._design_window_frame, 0, Qt.AlignmentFlag.AlignTop)
        self._design_window_frame.set_client_widget(self._design_stack)

        self.canvas = FormDesignerCanvasView()
        self.canvas.setObjectName("FormCanvas")
        self.canvas.setFrameShape(QFrame.Shape.NoFrame)
        try:
            self.canvas.setStyleSheet("background: transparent;")
            self.canvas.viewport().setStyleSheet("background: transparent;")
        except Exception:
            pass
        self.canvas.selectionChanged.connect(self._on_canvas_selection)
        self.canvas.selectionSetChanged.connect(self._on_canvas_selection_set_changed)
        try:
            self.canvas.set_grid_size(int(self._sp_design_grid.value()))
            self.canvas.set_grid_snap_enabled(bool(self._act_snap_grid.isChecked()))
            self.canvas.set_grid_visible(bool(self._act_snap_grid.isChecked()))
        except Exception:
            pass
        self.canvas.geometryChanged.connect(self._on_canvas_geometry_changed_live)
        self.canvas.geometryCommitted.connect(self._on_canvas_geometry_changed_commit)
        self.canvas.moveRequested.connect(self._on_canvas_move_requested)
        self.canvas.propertiesRequested.connect(self._focus_properties_for_node)
        self.canvas.copyRequested.connect(self._copy_node_by_id)
        self.canvas.cutRequested.connect(self._cut_node_by_id)
        self.canvas.pasteRequested.connect(self._paste_to_node)
        self.canvas.duplicateRequested.connect(self._duplicate_node_by_id)
        self.canvas.deleteRequested.connect(self._delete_node_by_id)
        self.canvas.rootSizeChanged.connect(self._on_canvas_root_size_changed)
        self.canvas.addControlRequested.connect(self._on_canvas_add_control)
        self.canvas.addRequisiteRequested.connect(self._on_canvas_add_requisite)
        self._design_stack.addWidget(self.canvas)

        self._design_preview_scroll = QScrollArea()
        self._design_preview_scroll.setObjectName("CanvasScroll")
        self._design_preview_scroll.setWidgetResizable(True)
        self._design_preview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._design_preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        try:
            self._design_preview_scroll.setStyleSheet("background: transparent;")
            self._design_preview_scroll.viewport().setStyleSheet("background: transparent;")
        except Exception:
            pass
        self._design_preview_host = QFrame()
        self._design_preview_host.setFrameShape(QFrame.Shape.NoFrame)
        self._design_preview_layout = QVBoxLayout(self._design_preview_host)
        self._design_preview_layout.setContentsMargins(0, 0, 0, 0)
        self._design_preview_layout.setSpacing(8)
        self._design_preview_scroll.setWidget(self._design_preview_host)
        self._design_stack.addWidget(self._design_preview_scroll)

        self._shortcut_copy = QShortcut(QKeySequence.StandardKey.Copy, self)
        self._shortcut_cut = QShortcut(QKeySequence.StandardKey.Cut, self)
        self._shortcut_paste = QShortcut(QKeySequence.StandardKey.Paste, self)
        for shortcut, handler in (
            (self._shortcut_copy, self._copy_selected),
            (self._shortcut_cut, self._cut_selected),
            (self._shortcut_paste, self._paste_selected),
        ):
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(handler)

        self._design_wrap_by_id: dict[str, QWidget] = {}
        self._props_help_map: dict[QWidget, str] = {}
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        try:
            self.preview_scroll.setStyleSheet("background: transparent;")
            self.preview_scroll.viewport().setStyleSheet("background: transparent;")
        except Exception:
            pass
        self.preview_host = QFrame()
        self.preview_host.setFrameShape(QFrame.Shape.NoFrame)
        self._preview_layout = QVBoxLayout(self.preview_host)
        self._preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_layout.setSpacing(8)
        self.preview_scroll.setWidget(self.preview_host)

        preview_tab = QWidget()
        self._preview_tab = preview_tab
        preview_l = QVBoxLayout(preview_tab)
        preview_l.setContentsMargins(8, 8, 8, 8)
        preview_l.setSpacing(8)

        self._preview_window_scroll = QScrollArea()
        self._preview_window_scroll.setObjectName("CanvasScroll")
        self._preview_window_scroll.setWidgetResizable(True)
        self._preview_window_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._preview_window_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        try:
            self._preview_window_scroll.setStyleSheet("background: #F8FAFC;")
            self._preview_window_scroll.viewport().setStyleSheet("background: #F8FAFC;")
        except Exception:
            pass
        preview_l.addWidget(self._preview_window_scroll, 1)

        self._preview_window_center = QWidget()
        self._preview_window_center.setMinimumWidth(0)
        self._preview_window_center.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        pc_l = QVBoxLayout(self._preview_window_center)
        pc_l.setContentsMargins(0, 0, 0, 0)
        pc_l.setSpacing(0)
        pc_l.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._preview_window_scroll.setWidget(self._preview_window_center)

        self._preview_window_frame = FormWindowFrame()
        pc_l.addWidget(self._preview_window_frame, 0, Qt.AlignmentFlag.AlignTop)
        self._preview_window_frame.set_client_widget(self.preview_scroll)

        module_tab = QWidget()
        self._module_tab = module_tab
        ml = QVBoxLayout(module_tab)
        ml.setContentsMargins(8, 8, 8, 8)
        ml.setSpacing(8)

        self._module_editor, self._module_highlighter = create_metascript_code_edit(
            parent=module_tab,
            placeholder=t("form_module_placeholder"),
            dark=True,
            autocomplete=True,
        )
        self._module_editor.setObjectName("FormModuleEditor")
        self._module_editor._definition_handler = self._go_to_form_module_definition
        self._module_editor._usages_handler = self._find_form_module_usages
        self._module_editor._rename_handler = self._rename_form_module_symbol
        self._module_editor.set_autocomplete_metadata_objects(metadata_completion_objects_from_vm(self._vm))
        self._module_editor.set_autocomplete_namespace_provider(
            lambda namespace: common_module_completion_members_from_vm(
                self._vm,
                namespace,
            )
        )
        self._module_editor.setPlainText(self._module_text)
        self._module_introspection_timer = QTimer(self)
        self._module_introspection_timer.setSingleShot(True)
        self._module_introspection_timer.setInterval(300)
        self._module_introspection_timer.timeout.connect(self._refresh_form_module_completion)
        self._module_editor.textChanged.connect(lambda: self._on_module_changed())
        self._module_editor.textChanged.connect(self._module_introspection_timer.start)
        self._module_editor.cursorPositionChanged.connect(self._module_introspection_timer.start)
        ml.addWidget(self._module_editor, 1)
        self._center_stack.addTab(design_host, t("form_tab_design"))
        self._center_stack.addTab(module_tab, t("form_tab_module"))
        self._center_stack.setCurrentIndex(0)
        self._on_workspace_tab_changed(0)

        prop_host = QWidget()
        prop_host.setObjectName("FormDesignerPropsBody")
        prop_l = QVBoxLayout(prop_host)
        prop_l.setContentsMargins(8, 8, 8, 8)
        prop_l.setSpacing(10)

        props_title = QLabel(t("form_properties"))
        self._props_title = props_title
        props_title.setObjectName("FormDesignerPanelTitle")
        props_title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        prop_l.addWidget(props_title, 0)

        self._form_layout = QFormLayout()
        self._ed_form_title = QLineEdit()
        self._ed_name = QLineEdit()
        self._ed_title = QLineEdit()
        self._ed_binding = QLineEdit()
        self._cb_open_mode = QComboBox()
        self._cb_open_mode.addItem(t("form_open_mode_auto"), "auto")
        self._cb_open_mode.addItem(t("form_open_mode_workspace"), "workspace")
        self._cb_open_mode.addItem(t("form_open_mode_window"), "window")
        self._cb_window_lock_mode = QComboBox()
        self._cb_window_lock_mode.addItem(t("form_window_lock_none"), "none")
        self._cb_window_lock_mode.addItem(t("form_window_lock_owner"), "owner")
        self._cb_window_lock_mode.addItem(t("form_window_lock_interface"), "interface")
        self._cb_layout = QComboBox()
        self._cb_layout.addItems(["absolute", "vertical", "horizontal", "grid"])
        self._sp_grid_cols = QSpinBox()
        self._sp_grid_cols.setRange(1, 24)
        self._cb_representation = QComboBox()
        self._cb_representation.addItem(t("form_repr_auto"), "")
        self._cb_representation.addItem(t("form_repr_none"), "none")
        self._cb_representation.addItem(t("form_repr_weak"), "weak")
        self._cb_representation.addItem(t("form_repr_usual"), "usual")
        self._cb_representation.addItem(t("form_repr_strong"), "strong")
        self._chk_show_title = QCheckBox()
        self._cb_title_location = QComboBox()
        self._cb_title_location.addItem(t("form_title_loc_left"), "left")
        self._cb_title_location.addItem(t("form_title_loc_top"), "top")
        self._cb_title_location.addItem(t("form_title_loc_none"), "none")
        self._cb_group_anchor = QComboBox()
        self._cb_group_anchor.addItem(t("form_anchor_auto"), "")
        self._cb_group_anchor.addItem(t("form_anchor_start"), "start")
        self._cb_group_anchor.addItem(t("form_anchor_center"), "center")
        self._cb_group_anchor.addItem(t("form_anchor_end"), "end")
        self._cb_group_anchor.addItem(t("form_anchor_stretch"), "stretch")
        self._sp_width_chars = QSpinBox()
        self._sp_width_chars.setRange(0, 200)
        self._sp_height_rows = QSpinBox()
        self._sp_height_rows.setRange(0, 100)
        self._chk_visible = QCheckBox()
        self._cb_decoration_kind = QComboBox()
        self._cb_decoration_kind.addItem(t("form_decoration_label"), "label")
        self._cb_decoration_kind.addItem(t("form_decoration_picture"), "picture")
        self._chk_enabled = QCheckBox()
        self._ed_tooltip = QLineEdit()
        self._cb_decoration_halign = QComboBox()
        self._cb_decoration_halign.addItem(t("form_align_start"), "left")
        self._cb_decoration_halign.addItem(t("form_align_center"), "center")
        self._cb_decoration_halign.addItem(t("form_align_end"), "right")
        self._cb_decoration_valign = QComboBox()
        self._cb_decoration_valign.addItem(t("form_align_start"), "top")
        self._cb_decoration_valign.addItem(t("form_align_center"), "center")
        self._cb_decoration_valign.addItem(t("form_align_end"), "bottom")
        self._chk_hstretch = QCheckBox()
        self._chk_vstretch = QCheckBox()
        self._ed_command = QLineEdit()

        self._form_layout.addRow(t("form_window_title"), self._ed_form_title)
        self._form_layout.addRow(t("lbl_name"), self._ed_name)
        self._form_layout.addRow(t("lbl_title"), self._ed_title)
        self._form_layout.addRow(t("form_binding"), self._ed_binding)
        self._form_layout.addRow(t("form_prop_open_mode"), self._cb_open_mode)
        self._form_layout.addRow(t("form_prop_window_lock_mode"), self._cb_window_lock_mode)
        self._form_layout.addRow(t("form_layout"), self._cb_layout)
        self._form_layout.addRow(t("form_grid_columns"), self._sp_grid_cols)
        self._form_layout.addRow(t("form_prop_representation"), self._cb_representation)
        self._form_layout.addRow(t("form_prop_show_title"), self._chk_show_title)
        self._form_layout.addRow(t("form_prop_title_location"), self._cb_title_location)
        self._form_layout.addRow(t("form_prop_group_anchor"), self._cb_group_anchor)
        self._form_layout.addRow(t("form_prop_width_chars"), self._sp_width_chars)
        self._form_layout.addRow(t("form_prop_height_rows"), self._sp_height_rows)
        self._form_layout.addRow(t("form_prop_visible_client"), self._chk_visible)
        self._form_layout.addRow(t("form_prop_decoration_kind"), self._cb_decoration_kind)
        self._form_layout.addRow(t("form_prop_enabled"), self._chk_enabled)
        self._form_layout.addRow(t("form_prop_tooltip"), self._ed_tooltip)
        self._form_layout.addRow(t("form_prop_horizontal_alignment"), self._cb_decoration_halign)
        self._form_layout.addRow(t("form_prop_vertical_alignment"), self._cb_decoration_valign)
        self._form_layout.addRow(t("form_prop_hstretch"), self._chk_hstretch)
        self._form_layout.addRow(t("form_prop_vstretch"), self._chk_vstretch)
        self._form_layout.addRow(t("form_prop_command"), self._ed_command)
        prop_l.addLayout(self._form_layout, 0)

        self._grp_canvas = QGroupBox(t("form_canvas_size"))
        gl = QFormLayout(self._grp_canvas)
        self._sp_canvas_w = QSpinBox()
        self._sp_canvas_w.setRange(200, 5000)
        self._sp_canvas_h = QSpinBox()
        self._sp_canvas_h.setRange(200, 5000)
        gl.addRow(t("form_canvas_w"), self._sp_canvas_w)
        gl.addRow(t("form_canvas_h"), self._sp_canvas_h)
        prop_l.addWidget(self._grp_canvas, 0)

        self._grp_geom = QGroupBox(t("form_geometry"))
        flg = QFormLayout(self._grp_geom)
        self._sp_x = QSpinBox()
        self._sp_x.setRange(-10000, 10000)
        self._sp_y = QSpinBox()
        self._sp_y.setRange(-10000, 10000)
        self._sp_w = QSpinBox()
        self._sp_w.setRange(10, 5000)
        self._sp_h = QSpinBox()
        self._sp_h.setRange(10, 5000)
        flg.addRow(t("form_pos_x"), self._sp_x)
        flg.addRow(t("form_pos_y"), self._sp_y)
        flg.addRow(t("form_size_w"), self._sp_w)
        flg.addRow(t("form_size_h"), self._sp_h)
        prop_l.addWidget(self._grp_geom, 0)

        self._grp_gridpos = QGroupBox(t("form_grid_position"))
        flgp = QFormLayout(self._grp_gridpos)
        self._sp_row = QSpinBox()
        self._sp_row.setRange(0, 999)
        self._sp_col = QSpinBox()
        self._sp_col.setRange(0, 999)
        self._sp_rowspan = QSpinBox()
        self._sp_rowspan.setRange(1, 99)
        self._sp_colspan = QSpinBox()
        self._sp_colspan.setRange(1, 99)
        flgp.addRow(t("form_row"), self._sp_row)
        flgp.addRow(t("form_col"), self._sp_col)
        flgp.addRow(t("form_rowspan"), self._sp_rowspan)
        flgp.addRow(t("form_colspan"), self._sp_colspan)
        prop_l.addWidget(self._grp_gridpos, 0)

        self._lbl_table_columns = QLabel(t("form_table_columns"))
        prop_l.addWidget(self._lbl_table_columns, 0)
        self._tbl_columns = QTableWidget(0, 1)
        self._tbl_columns.setHorizontalHeaderLabels([t("form_column")])
        self._tbl_columns.horizontalHeader().setStretchLastSection(True)
        self._tbl_columns.verticalHeader().setVisible(False)
        prop_l.addWidget(self._tbl_columns, 1)
        prop_l.addStretch(1)

        props_scroll = QScrollArea()
        props_scroll.setWidgetResizable(True)
        props_scroll.setFrameShape(QFrame.Shape.NoFrame)
        props_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        props_scroll.setWidget(prop_host)

        self._props_help = QPlainTextEdit()
        self._props_help.setReadOnly(True)
        self._props_help.setFixedHeight(78)
        self._props_help.setObjectName("FormDesignerPropsHelp")
        self._props_help.setPlainText("")

        props_page = QWidget()
        props_page.setObjectName("FormDesignerProps")
        props_page_l = QVBoxLayout(props_page)
        props_page_l.setContentsMargins(0, 0, 0, 0)
        props_page_l.setSpacing(0)
        props_page_l.addWidget(props_scroll, 1)
        props_page_l.addWidget(self._props_help, 0)

        self._register_props_help(self._ed_form_title, "Заголовок вікна runtime-форми.")
        self._register_props_help(self._ed_name, "Внутрішнє ім'я вузла форми для посилань і коду.")
        self._register_props_help(self._ed_title, "Підпис елемента, який бачить користувач у формі.")
        self._register_props_help(self._ed_binding, "Прив'язка елемента до реквізиту, табличної частини або колонки.")
        self._register_props_help(self._cb_open_mode, t("form_prop_open_mode_help"))
        self._register_props_help(self._cb_window_lock_mode, t("form_prop_window_lock_mode_help"))
        self._register_props_help(self._cb_layout, "Тип розміщення дочірніх елементів контейнера.")
        self._register_props_help(self._sp_grid_cols, "Кількість колонок у grid-контейнері.")
        self._register_props_help(self._cb_representation, "Як контейнер показує свою рамку або заголовок.")
        self._register_props_help(self._chk_show_title, "Чи відображати заголовок групи або контейнера.")
        self._register_props_help(self._cb_title_location, "Положення підпису відносно елемента.")
        self._register_props_help(self._cb_group_anchor, "Як елемент притискається всередині батьківської групи.")
        self._register_props_help(self._sp_width_chars, "Ширина поля у символах.")
        self._register_props_help(self._sp_height_rows, "Висота поля у рядках.")
        self._register_props_help(self._chk_visible, t("form_prop_visible_client_help"))
        self._register_props_help(self._cb_decoration_kind, t("form_prop_decoration_kind_help"))
        self._register_props_help(self._chk_enabled, t("form_prop_enabled_help"))
        self._register_props_help(self._ed_tooltip, t("form_prop_tooltip_help"))
        self._register_props_help(self._cb_decoration_halign, t("form_prop_horizontal_alignment_help"))
        self._register_props_help(self._cb_decoration_valign, t("form_prop_vertical_alignment_help"))
        self._register_props_help(self._chk_hstretch, "Чи розтягувати елемент по ширині.")
        self._register_props_help(self._chk_vstretch, "Чи розтягувати елемент по висоті.")
        self._register_props_help(self._ed_command, "Команда, яку виконує кнопка.")
        self._register_props_help(self._sp_canvas_w, "Ширина полотна форми.")
        self._register_props_help(self._sp_canvas_h, "Висота полотна форми.")
        self._register_props_help(self._sp_x, "Координата X для absolute-розміщення.")
        self._register_props_help(self._sp_y, "Координата Y для absolute-розміщення.")
        self._register_props_help(self._sp_w, "Ширина елемента.")
        self._register_props_help(self._sp_h, "Висота елемента.")
        self._register_props_help(self._sp_row, "Рядок у grid-розміщенні.")
        self._register_props_help(self._sp_col, "Колонка у grid-розміщенні.")
        self._register_props_help(self._sp_rowspan, "Скільки рядків grid займає елемент.")
        self._register_props_help(self._sp_colspan, "Скільки колонок grid займає елемент.")
        self._register_props_help(self._tbl_columns, "Список колонок табличного елемента.")

        self._props_widget = props_page
        self._props_widget.setVisible(False)
        self._props_widget.setMinimumWidth(280)
        self._props_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes(self._form_split_sizes)

        self.requisites.itemDoubleClicked.connect(self._on_requisite_double_clicked)
        self._ed_form_title.textEdited.connect(lambda _: self._on_form_title_changed())
        self._ed_name.textEdited.connect(lambda _: self._on_prop_changed())
        self._ed_title.textEdited.connect(lambda _: self._on_prop_changed())
        self._ed_binding.textEdited.connect(lambda _: self._on_prop_changed())
        self._cb_open_mode.currentIndexChanged.connect(lambda _i: self._on_prop_changed())
        self._cb_window_lock_mode.currentIndexChanged.connect(lambda _i: self._on_prop_changed())
        self._cb_layout.currentTextChanged.connect(lambda _: self._on_prop_changed())
        self._sp_grid_cols.valueChanged.connect(lambda _v: self._on_prop_changed())
        self._cb_representation.currentIndexChanged.connect(lambda _i: self._on_prop_changed())
        self._chk_show_title.toggled.connect(lambda _v: self._on_prop_changed())
        self._cb_title_location.currentIndexChanged.connect(lambda _i: self._on_prop_changed())
        self._cb_group_anchor.currentIndexChanged.connect(lambda _i: self._on_prop_changed())
        self._sp_width_chars.valueChanged.connect(lambda _v: self._on_prop_changed())
        self._sp_height_rows.valueChanged.connect(lambda _v: self._on_prop_changed())
        self._chk_visible.toggled.connect(lambda _v: self._on_prop_changed())
        self._cb_decoration_kind.currentIndexChanged.connect(lambda _i: self._on_prop_changed())
        self._chk_enabled.toggled.connect(lambda _v: self._on_prop_changed())
        self._ed_tooltip.textEdited.connect(lambda _: self._on_prop_changed())
        self._cb_decoration_halign.currentIndexChanged.connect(lambda _i: self._on_prop_changed())
        self._cb_decoration_valign.currentIndexChanged.connect(lambda _i: self._on_prop_changed())
        self._chk_hstretch.toggled.connect(lambda _v: self._on_prop_changed())
        self._chk_vstretch.toggled.connect(lambda _v: self._on_prop_changed())
        self._ed_command.textEdited.connect(lambda _: self._on_prop_changed())

        self._sp_canvas_w.valueChanged.connect(lambda _v: self._on_canvas_size_changed())
        self._sp_canvas_h.valueChanged.connect(lambda _v: self._on_canvas_size_changed())

        for spin in (self._sp_x, self._sp_y, self._sp_w, self._sp_h):
            spin.valueChanged.connect(lambda _v: self._on_geometry_spin_changed())
        for spin in (self._sp_row, self._sp_col, self._sp_rowspan, self._sp_colspan):
            spin.valueChanged.connect(lambda _v: self._on_gridpos_spin_changed())
        self._tbl_columns.itemChanged.connect(lambda _: self._on_columns_changed())

        self._ui_guard = True
        try:
            self._ed_form_title.setText(str(self._model.title or ""))
        finally:
            self._ui_guard = False

        self._reload_requisites_panel()
        self._refresh_workspace_panels()
        self._maybe_autofill_empty_form()

        self._apply_designer_chrome()
        self._rebuild_tree()
        self._update_window_frames()
        self._refresh_canvas()
        self._maybe_auto_checkout()
        self._apply_edit_guard()
        self._retranslate_ui()
        bind(self._retranslate_ui, self)
        self._sync_toolbox_hint()
        self._schedule_preview_refresh(0)

    def _sync_center_mode_tabs(self, index: int) -> None:
        try:
            tabbar = getattr(self, "_center_tabbar", None)
            if tabbar is not None:
                tabbar.blockSignals(True)
                tabbar.setCurrentIndex(int(index))
                tabbar.blockSignals(False)
        except Exception:
            pass

    def _on_workspace_tab_changed(self, index: int) -> None:
        self._sync_center_mode_tabs(index)
        module_mode = int(index) == 1
        if module_mode and self._top_splitter.isVisible():
            sizes = [int(value) for value in self._main_splitter.sizes()]
            if len(sizes) == 2 and sizes[0] > 0:
                self._form_split_sizes = sizes
        self._top_splitter.setVisible(not module_mode)
        self._pane_controls.setVisible(not module_mode)
        if not module_mode:
            QTimer.singleShot(0, lambda: self._main_splitter.setSizes(self._form_split_sizes))

    def _on_toolbox_combo_changed(self, index: int) -> None:
        try:
            self.toolbox.setCurrentRow(int(index))
        except Exception:
            pass

    def _sync_toolbox_combo(self) -> None:
        combo = getattr(self, "_toolbox_combo", None)
        if combo is None:
            return
        current_type = str(combo.currentData() or "")
        combo.blockSignals(True)
        try:
            combo.clear()
            for index in range(self.toolbox.count()):
                item = self.toolbox.item(index)
                combo.addItem(item.text(), item.data(Qt.ItemDataRole.UserRole))
            selected = combo.findData(current_type)
            combo.setCurrentIndex(selected if selected >= 0 else (0 if combo.count() else -1))
        finally:
            combo.blockSignals(False)
        if combo.currentIndex() >= 0:
            self._on_toolbox_combo_changed(combo.currentIndex())

    def _iter_form_nodes(self):
        stack = [self._model.root]
        while stack:
            node = stack.pop(0)
            yield node
            stack[0:0] = list(node.children or [])

    def _localized_value(self, value: object, fallback: str = "") -> str:
        if isinstance(value, dict):
            lang = get_lang()
            return str(value.get(lang) or value.get("uk") or value.get("en") or fallback or "").strip()
        text = str(value or "").strip()
        return text or str(fallback or "").strip()

    def _command_specs(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        form_specs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for node in self._iter_form_nodes():
            if str(node.type or "") != "Button":
                continue
            props = node.props if isinstance(node.props, dict) else {}
            code = str(props.get("command") or node.name or node.id or "").strip()
            if not code or code.casefold() in seen:
                continue
            seen.add(code.casefold())
            form_specs.append({"code": code, "title": node.title or node.name or code, "action": code})

        owner = self._resolve_owner_meta() or {}
        owner_payload = owner.get("payload") if isinstance(owner.get("payload"), dict) else {}
        standard_specs = owner_payload.get("commands") if isinstance(owner_payload.get("commands"), list) else []
        if not standard_specs:
            standard_specs = default_commands_for_context(
                obj_type=str(owner.get("type") or ""),
                context=self._infer_form_kind(form_title=self._form_title, payload=self._payload),
            )
        globals_raw = self._payload.get("global_commands")
        global_specs = globals_raw if isinstance(globals_raw, list) else []
        return form_specs, [item for item in standard_specs if isinstance(item, dict)], [
            item for item in global_specs if isinstance(item, dict)
        ]

    def _fill_command_tree(self, tree: QTreeWidget, specs: list[dict[str, Any]]) -> None:
        tree.clear()
        for spec in specs:
            code = str(spec.get("code") or spec.get("name") or "").strip()
            if not code:
                continue
            title = self._localized_value(spec.get("title"), code)
            action = str(spec.get("action") or spec.get("handler") or code).strip()
            item = QTreeWidgetItem([title, action])
            item.setData(0, Qt.ItemDataRole.UserRole, dict(spec))
            tree.addTopLevelItem(item)

    def _refresh_command_interface_tree(self) -> None:
        tree = self._command_interface_tree
        tree.clear()
        root = QTreeWidgetItem([self._form_title or t("form_tab_design")])
        root.setData(0, Qt.ItemDataRole.UserRole, self._model.root.id)
        tree.addTopLevelItem(root)

        def append(parent_item: QTreeWidgetItem, node) -> None:
            if str(node.type or "") in {"CommandBar", "Button"}:
                item = QTreeWidgetItem([self._node_tree_name(node)])
                item.setData(0, Qt.ItemDataRole.UserRole, node.id)
                parent_item.addChild(item)
                parent_item = item
            for child in node.children or []:
                append(parent_item, child)

        for child in self._model.root.children or []:
            append(root, child)
        tree.expandAll()

    def _on_command_interface_selection(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        node_id = str(current.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        if node_id:
            self._select_node_by_id(node_id)

    def _refresh_parameters_tree(self) -> None:
        self._parameters_tree.clear()
        raw = self._payload.get("parameters")
        if not isinstance(raw, list):
            model_raw = self._payload.get("form_model")
            raw = model_raw.get("parameters") if isinstance(model_raw, dict) else []
        for spec in raw if isinstance(raw, list) else []:
            if not isinstance(spec, dict):
                continue
            name = str(spec.get("name") or spec.get("code") or "").strip()
            if not name:
                continue
            type_name = str(spec.get("type") or spec.get("data_type") or "").strip()
            item = QTreeWidgetItem([name, type_name])
            item.setData(0, Qt.ItemDataRole.UserRole, dict(spec))
            self._parameters_tree.addTopLevelItem(item)

    def _refresh_workspace_panels(self) -> None:
        if not hasattr(self, "_command_interface_tree"):
            return
        self._refresh_command_interface_tree()
        form_specs, standard_specs, global_specs = self._command_specs()
        self._fill_command_tree(self._form_commands_tree, form_specs)
        self._fill_command_tree(self._standard_commands_tree, standard_specs)
        self._fill_command_tree(self._global_commands_tree, global_specs)
        self._refresh_parameters_tree()
        self._refresh_form_module_completion()

    def _refresh_form_module_completion(self) -> None:
        editor = getattr(self, "_module_editor", None)
        if editor is None:
            return
        words: set[str] = set()
        try:
            info = introspect_module_source(editor.toPlainText(), language="mixed")
            words.update(info.runtime_names)
            words.update(info.module_vars)
            words.update(info.procedures)
            words.update(info.functions)
            line = editor.textCursor().blockNumber() + 1
            for scope in info.scopes:
                if scope.contains_line(line):
                    words.update(scope.params)
                    words.update(scope.locals)
        except Exception:
            pass
        for req in self._available_requisites():
            words.add(str(req.get("code") or req.get("name") or "").strip())
        for specs in self._command_specs():
            for spec in specs:
                words.add(str(spec.get("code") or spec.get("name") or "").strip())
        raw_parameters = self._payload.get("parameters")
        for spec in raw_parameters if isinstance(raw_parameters, list) else []:
            if isinstance(spec, dict):
                words.add(str(spec.get("name") or spec.get("code") or "").strip())
        editor.set_autocomplete_words({word for word in words if word})

    def _go_to_form_module_definition(self) -> None:
        editor = getattr(self, "_module_editor", None)
        if editor is None:
            return
        info = introspect_module_source(editor.toPlainText(), language="mixed")
        target = resolve_definition_target(
            editor.toPlainText(),
            editor.textCursor().position(),
            introspection=info,
            vm=self._vm,
        )
        if target is None:
            return
        if target.kind == "local" and target.line > 0:
            editor.navigate_to_line(target.line)
            editor.setFocus()
            return
        self.definitionRequested.emit(target.as_dict())

    def _find_form_module_usages(self) -> None:
        editor = getattr(self, "_module_editor", None)
        if editor is None:
            return
        chain = identifier_chain_at(editor.toPlainText(), editor.textCursor().position())
        if not chain:
            return
        module_guid = ""
        if len(chain) == 1:
            asset_key = str(getattr(self, "_module_asset_key", "") or "")
            if asset_key.startswith("module://"):
                module_guid = asset_key.split("://", 1)[1].strip()
        self.usagesRequested.emit(
            {
                "term": ".".join(chain),
                "whole_word": True,
                "module_guid": module_guid,
                "title": t("code_editor_find_usages"),
            }
        )

    def _rename_form_module_symbol(self) -> None:
        editor = getattr(self, "_module_editor", None)
        if editor is None:
            return
        from src.ui_qt.widgets.semantic_rename_dialog import (
            apply_semantic_rename_plan,
            request_semantic_rename,
        )

        plan = request_semantic_rename(
            source=editor.toPlainText(),
            cursor_position=editor.textCursor().position(),
            language="mixed",
            parent=self,
        )
        if plan is None:
            return
        apply_semantic_rename_plan(editor, plan)
        self._refresh_form_module_completion()

    def _add_command_to_form(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        spec = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(spec, dict) or not self._is_edit_enabled():
            return
        self._add_control("Button")
        node = self._current_node()
        if node is None or str(node.type or "") != "Button":
            return
        code = str(spec.get("code") or spec.get("name") or "").strip()
        node.name = code or node.name
        node.title = self._localized_value(spec.get("title"), code or node.title)
        node.props["command"] = str(spec.get("action") or code).strip()
        self._set_dirty(True)
        self._rebuild_tree(keep_selected_id=node.id)
        self._refresh_canvas()

    def _toggle_left_panel(self) -> None:
        visible = bool(self._left_tabs.isVisible())
        self._left_tabs.setVisible(not visible)
        key = "form_show_structure" if visible else "form_hide_structure"
        icon = "panel-left-open" if visible else "panel-left-close"
        self._btn_toggle_left.setIcon(_ce_icon(icon, "#9FB4CF", 16))
        self._btn_toggle_left.setToolTip(t(key))
        self._btn_toggle_left.setAccessibleName(t(key))

    def _toggle_properties_panel(self) -> None:
        visible = bool(self._props_widget.isVisible())
        self._props_widget.setVisible(not visible)
        key = "form_show_properties" if visible else "form_hide_properties"
        icon = "panel-right-open" if visible else "panel-right-close"
        self._btn_toggle_props.setIcon(_ce_icon(icon, "#9FB4CF", 16))
        self._btn_toggle_props.setToolTip(t(key))
        self._btn_toggle_props.setAccessibleName(t(key))

    def properties_widget(self) -> QWidget | None:
        w = getattr(self, "_props_widget", None)
        if w is None:
            return None
        try:
            w.setVisible(True)
        except Exception:
            pass
        return w

    def _add_selected_toolbox_item(self) -> None:
        item = self.toolbox.currentItem()
        if item is None:
            return
        control_type = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not control_type:
            return
        self._add_control(control_type)

    def _show_add_element_dialog(self) -> None:
        if not self._is_edit_enabled():
            return
        dialog = FormElementTypeDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        spec = dialog.selected_spec()
        if spec is None:
            return
        self._add_control(
            spec.control_type,
            default_props=spec.props(),
            default_title=spec.default_title(),
        )

    def _sync_toolbox_hint(self) -> None:
        try:
            if getattr(self, "_toolbox_combo", None) is not None and self._toolbox_combo.isHidden():
                self._design_hint.setText(t("form_element_type_dialog_hint"))
                return
            current = self.toolbox.currentItem()
            control_type = str(current.data(Qt.ItemDataRole.UserRole) or "").strip() if current is not None else ""
            if control_type:
                self._design_hint.setText(
                    t("form_toolbox_hint_selected").format(control_type=control_type)
                )
            else:
                self._design_hint.setText(t("form_toolbox_hint_empty"))
        except Exception:
            pass
