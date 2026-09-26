from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSizePolicy, QStyle, QToolButton, QWidget

from src.ui_qt.i18n import t
from src.ui_qt.services.icon_provider import IconProvider, IconRenderOptions
from src.ui_qt.widgets.toolbar_customize_dialog import ToolbarCustomizeDialog, ToolbarItem


class ConfiguratorToolbarMixin:
    @staticmethod
    def _icons_dir() -> Path:
        return Path(__file__).resolve().parents[1] / "assets" / "icons" / "svg"

    def _tb_icon(self, name: str, *, size: int = 18) -> QIcon:
        p = self._icons_dir() / f"{name}.svg"
        if not p.exists():
            return QIcon()
        try:
            data = p.read_bytes()
            ip = getattr(self, "_icon_provider", None)
            if ip is None:
                ip = getattr(self, "_tb_icon_provider", None) or IconProvider()
            pm = ip.svg_bytes_to_pixmap(data, opts=IconRenderOptions(size=int(size), transparent=True))
            return QIcon(pm)
        except Exception:
            return QIcon()

    def _tb_set_icon(self, action: QAction, icon_name: str, *, size: int = 18) -> None:
        try:
            action.setProperty("mp_icon_name", str(icon_name))
            action.setProperty("mp_icon_size", int(size))
        except Exception:
            pass
        try:
            action.setIcon(self._tb_icon(icon_name, size=size))
        except Exception:
            pass

    def _tb_set_widget_icon(self, w: QWidget, icon_name: str, *, size: int = 18) -> None:
        try:
            w.setProperty("mp_icon_name", str(icon_name))
            w.setProperty("mp_icon_size", int(size))
        except Exception:
            pass
        try:
            if hasattr(w, "setIcon"):
                w.setIcon(self._tb_icon(icon_name, size=size))
        except Exception:
            pass

    def _tb_refresh_icons(self) -> None:
        for a in getattr(self, "_toolbar_actions", []) or []:
            try:
                icon_name = a.property("mp_icon_name")
                if not icon_name:
                    continue
                size = a.property("mp_icon_size") or 18
                self._tb_set_icon(a, str(icon_name), size=int(size))
            except Exception:
                continue

        for w in (
            getattr(self, "_tb_customize_btn", None),
            getattr(self, "_tb_find_btn", None),
        ):
            if w is None:
                continue
            try:
                icon_name = w.property("mp_icon_name")
                if not icon_name:
                    continue
                size = w.property("mp_icon_size") or 18
                self._tb_set_widget_icon(w, str(icon_name), size=int(size))
            except Exception:
                continue

        for a in (
            getattr(self, "act_toggle_tree", None),
            getattr(self, "act_toggle_props", None),
        ):
            if a is None:
                continue
            try:
                icon_name = a.property("mp_icon_name")
                if not icon_name:
                    continue
                size = a.property("mp_icon_size") or 18
                self._tb_set_icon(a, str(icon_name), size=int(size))
            except Exception:
                continue

    def _enforce_main_toolbar_icon_only(self) -> None:
        tb = getattr(self, "_tb_main", None)
        if tb is None:
            return
        try:
            tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        except Exception:
            pass

        for a in tb.actions():
            w = tb.widgetForAction(a)
            if isinstance(w, QToolButton):
                try:
                    w.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                except Exception:
                    pass
                try:
                    w.setText("")
                except Exception:
                    pass
                try:
                    if a is not None and a.text():
                        w.setToolTip(a.text())
                except Exception:
                    pass

    def _register_tb_action(self, a: QAction, action_id: str) -> QAction:
        a.setObjectName(str(action_id))
        try:
            a.setIconText("")
        except Exception:
            pass
        self._toolbar_actions.append(a)
        self._toolbar_action_ids[a] = str(action_id)
        return a

    def _build_main_actions(self) -> None:
        self.act_new = self._register_tb_action(QAction(t("act_new"), self), "tb_new")
        self.act_new.setShortcut("Ctrl+N")
        self._tb_set_icon(self.act_new, "file-plus")
        self.act_new.triggered.connect(self._on_new_document)

        self.act_open = self._register_tb_action(QAction(t("act_open"), self), "tb_open")
        self.act_open.setShortcut("Ctrl+O")
        self._tb_set_icon(self.act_open, "folder-open")
        self.act_open.triggered.connect(self._on_open_file)

        self.act_save = self._register_tb_action(QAction(t("act_save"), self), "tb_save")
        self.act_save.setShortcut("Ctrl+S")
        self._tb_set_icon(self.act_save, "save")
        self.act_save.triggered.connect(self._on_save)

        self.act_import_1cd = self._register_tb_action(QAction(t("cfg_import_1cd"), self), "tb_import_1cd")
        self.act_import_1cd.setShortcut("Ctrl+Alt+I")
        self._tb_set_icon(self.act_import_1cd, "database")
        self.act_import_1cd.triggered.connect(self._load_onecd_database)

        self.act_subsystem_report = self._register_tb_action(
            QAction(t("cfg_subsystem_membership_report"), self),
            "tb_subsystem_membership_report",
        )
        self._tb_set_icon(self.act_subsystem_report, "list-tree")
        self.act_subsystem_report.triggered.connect(self._show_subsystem_membership_report)

        self.act_structure_compare = self._register_tb_action(
            QAction(t("cfg_source_structure_compare"), self),
            "tb_source_structure_compare",
        )
        self._tb_set_icon(self.act_structure_compare, "git-compare")
        self.act_structure_compare.triggered.connect(self._show_source_structure_compare_report)

        self.act_structure_repair = self._register_tb_action(
            QAction(t("cfg_source_structure_compare_repair"), self),
            "tb_source_structure_repair",
        )
        self._tb_set_icon(self.act_structure_repair, "wrench")
        self.act_structure_repair.triggered.connect(self._repair_source_structure_from_last_import)

        self.act_cut = self._register_tb_action(QAction(t("act_cut"), self), "tb_cut")
        self.act_cut.setShortcut("Ctrl+X")
        self._tb_set_icon(self.act_cut, "scissors")
        self.act_cut.triggered.connect(lambda: self._dispatch_focus("cut"))

        self.act_copy = self._register_tb_action(QAction(t("act_copy"), self), "tb_copy")
        self.act_copy.setShortcut("Ctrl+C")
        self._tb_set_icon(self.act_copy, "copy")
        self.act_copy.triggered.connect(lambda: self._dispatch_focus("copy"))

        self.act_paste = self._register_tb_action(QAction(t("act_paste"), self), "tb_paste")
        self.act_paste.setShortcut("Ctrl+V")
        self._tb_set_icon(self.act_paste, "clipboard-paste")
        self.act_paste.triggered.connect(lambda: self._dispatch_focus("paste"))

        self.act_undo = self._register_tb_action(QAction(t("act_undo"), self), "tb_undo")
        self.act_undo.setShortcut("Ctrl+Z")
        self._tb_set_icon(self.act_undo, "undo")
        self.act_undo.triggered.connect(lambda: self._dispatch_focus("undo"))

        self.act_redo = self._register_tb_action(QAction(t("act_redo"), self), "tb_redo")
        self.act_redo.setShortcut("Ctrl+Shift+Z")
        self._tb_set_icon(self.act_redo, "redo")
        self.act_redo.triggered.connect(lambda: self._dispatch_focus("redo"))

        self.act_print = self._register_tb_action(QAction(t("act_print"), self), "tb_print")
        self.act_print.setShortcut("Ctrl+P")
        self._tb_set_icon(self.act_print, "printer")
        self.act_print.triggered.connect(lambda: self._on_print(preview=False))

        self.act_print_preview = self._register_tb_action(QAction(t("act_print_preview"), self), "tb_preview")
        self._tb_set_icon(self.act_print_preview, "eye")
        self.act_print_preview.triggered.connect(lambda: self._on_print(preview=True))

        self.act_global_search = self._register_tb_action(QAction(t("act_global_search"), self), "tb_global_search")
        self.act_global_search.setShortcut("Ctrl+Shift+F")
        self._tb_set_icon(self.act_global_search, "search")
        self.act_global_search.triggered.connect(self._on_global_search)

        self.act_find_meta = self._register_tb_action(QAction(t("act_find_meta"), self), "tb_find_meta")
        self.act_find_meta.setShortcut("Ctrl+F")
        self._tb_set_icon(self.act_find_meta, "search")
        self.act_find_meta.triggered.connect(self._open_meta_search_dialog)

        self.act_find_next = self._register_tb_action(QAction(t("act_find_next"), self), "tb_find_next")
        self.act_find_next.setShortcut("F3")
        self._tb_set_icon(self.act_find_next, "arrow-down")
        self.act_find_next.triggered.connect(lambda: self._meta_find_next(prev=False))

        self.act_find_prev = self._register_tb_action(QAction(t("act_find_prev"), self), "tb_find_prev")
        self.act_find_prev.setShortcut("Shift+F3")
        self._tb_set_icon(self.act_find_prev, "arrow-up")
        self.act_find_prev.triggered.connect(lambda: self._meta_find_next(prev=True))

        self.act_windows_list = self._register_tb_action(QAction(t("act_windows_list"), self), "tb_windows")
        self._tb_set_icon(self.act_windows_list, "app-window")
        self.act_windows_list.triggered.connect(self._on_windows_list)

        self.act_syntax_help = self._register_tb_action(QAction(t("act_syntax_help"), self), "tb_syntax")
        self._tb_set_icon(self.act_syntax_help, "book-open-text")
        self.act_syntax_help.triggered.connect(self._on_syntax_helper)

        self.act_syntax_help_search = self._register_tb_action(
            QAction(t("act_syntax_help_search"), self), "tb_syntax_search"
        )
        self._tb_set_icon(self.act_syntax_help_search, "book-search")
        self.act_syntax_help_search.triggered.connect(self._on_syntax_helper_search)

        self.act_templates = self._register_tb_action(QAction(t("act_templates"), self), "tb_templates")
        self._tb_set_icon(self.act_templates, "braces")
        self.act_templates.triggered.connect(self._on_templates)

        self.act_about = self._register_tb_action(QAction(t("act_about"), self), "tb_about")
        self._tb_set_icon(self.act_about, "badge-info")
        self.act_about.triggered.connect(self._on_about)

        self.act_refresh = self._register_tb_action(QAction(t("act_refresh"), self), "tb_refresh")
        self._tb_set_icon(self.act_refresh, "refresh-cw")
        self.act_refresh.triggered.connect(self.refreshRequested.emit)

        self.act_check = self._register_tb_action(QAction(t("menu_check"), self), "tb_check")
        self._tb_set_icon(self.act_check, "circle-check")
        self.act_check.triggered.connect(self.checkRequested.emit)

        self.act_run_client = QAction(f"{t('btn_client')}", self)
        self.act_run_client.triggered.connect(lambda: self._launch_client(debug=False))
        self.act_run_client_debug = QAction(f"{t('btn_client')} (Debug)", self)
        self.act_run_client_debug.triggered.connect(self._launch_or_restart_debug_client)

    def _populate_main_toolbar(self) -> None:
        tb = self._tb_main

        self._tb_customize_btn = QToolButton(self)
        self._tb_customize_btn.setObjectName("toolbar_customize_btn")
        self._tb_set_widget_icon(self._tb_customize_btn, "info")
        self._tb_customize_btn.setToolTip(t("act_toolbar_customize"))
        self._tb_customize_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._tb_customize_menu = QMenu(self)
        self._tb_customize_btn.setMenu(self._tb_customize_menu)
        self._tb_customize_btn.setAutoRaise(True)

        def _sep():
            s = tb.addSeparator()
            self._toolbar_separators.append(s)
            return s

        tb.addAction(self.act_new)
        tb.addAction(self.act_open)
        tb.addAction(self.act_save)
        tb.addAction(self.act_import_1cd)
        tb.addAction(self.act_subsystem_report)
        tb.addAction(self.act_structure_compare)
        tb.addAction(self.act_structure_repair)
        _sep()
        tb.addAction(self.act_cut)
        tb.addAction(self.act_copy)
        tb.addAction(self.act_paste)
        _sep()
        tb.addAction(self.act_print)
        tb.addAction(self.act_print_preview)
        _sep()
        tb.addAction(self.act_undo)
        tb.addAction(self.act_redo)
        _sep()
        tb.addAction(self.act_global_search)

        self._tb_find_edit = self._make_tb_find_edit()
        tb.addWidget(self._tb_find_edit)

        self._tb_find_btn = QToolButton(self)
        self._tb_set_widget_icon(self._tb_find_btn, "search")
        self._tb_find_btn.setToolTip(t("act_find_meta"))
        self._tb_find_btn.clicked.connect(self._open_meta_search_dialog)
        tb.addWidget(self._tb_find_btn)

        tb.addAction(self.act_find_prev)
        tb.addAction(self.act_find_next)

        _sep()
        tb.addAction(self.act_windows_list)
        tb.addAction(self.act_syntax_help)
        tb.addAction(self.act_syntax_help_search)
        tb.addAction(self.act_templates)
        tb.addAction(self.act_about)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        self.act_toggle_tree = QAction(t("cfg_tree_title"), self)
        self.act_toggle_tree.setCheckable(True)
        self.act_toggle_tree.setChecked(True)
        self._tb_set_icon(self.act_toggle_tree, "panel-left")
        try:
            self.act_toggle_tree.setIconText("")
        except Exception:
            pass
        self.act_toggle_tree.triggered.connect(lambda checked: self.dock_tree.setVisible(bool(checked)))
        tb.addAction(self.act_toggle_tree)

        self.act_toggle_props = QAction(t("act_properties"), self)
        self.act_toggle_props.setCheckable(True)
        self.act_toggle_props.setChecked(self._props_visible)
        self._tb_set_icon(self.act_toggle_props, "sliders-horizontal")
        try:
            self.act_toggle_props.setIconText("")
        except Exception:
            pass
        self.act_toggle_props.setShortcut("F4")
        self.act_toggle_props.triggered.connect(lambda checked: self.set_properties_visible(bool(checked)))
        tb.addAction(self.act_toggle_props)

        tb.addWidget(self._tb_customize_btn)

        self._rebuild_toolbar_customize_menu()
        self._update_save_enabled()

    def _make_tb_find_edit(self):
        from PySide6.QtWidgets import QLineEdit

        edit = QLineEdit(self)
        edit.setPlaceholderText(t("ph_search"))
        edit.setClearButtonEnabled(True)
        edit.setMaximumWidth(340)
        edit.returnPressed.connect(lambda: self._meta_find_from_toolbar())
        return edit

    def _rebuild_toolbar_customize_menu(self) -> None:
        m = getattr(self, "_tb_customize_menu", None)
        if m is None:
            return
        m.clear()
        act_list = QAction(t("act_windows_list"), self)
        act_list.triggered.connect(self._on_windows_list)
        m.addAction(act_list)
        m.addSeparator()
        hdr = m.addAction(t("act_toolbar_customize"))
        hdr.setEnabled(False)
        m.addSeparator()

        for a in self._toolbar_actions:
            if a in (getattr(self, "act_toggle_tree", None), getattr(self, "act_toggle_props", None)):
                continue
            if not a.text().strip():
                continue
            it = m.addAction(a.icon(), a.text())
            it.setCheckable(True)
            it.setChecked(self._is_toolbar_action_visible(a))

            def _mk_toggle(act=a, menu_act=it):
                def _toggle():
                    self._set_toolbar_action_visible(act, menu_act.isChecked())
                    self._save_toolbar_visibility()

                return _toggle

            it.triggered.connect(_mk_toggle())

        m.addSeparator()
        m.addAction(t("btn_reset"), self._reset_toolbar_visibility)
        m.addAction(t("dlg_toolbar_customize_title") + "…", self._open_toolbar_customize_dialog)

    def _toolbar_items_provider(self):
        items = []
        for a in self._toolbar_actions:
            if not a.text().strip():
                continue
            aid = self._toolbar_action_ids.get(a) or a.objectName()
            items.append(ToolbarItem(id=str(aid), title=str(a.text()), checked=self._is_toolbar_action_visible(a)))
        return items

    def _open_toolbar_customize_dialog(self) -> None:
        dlg = ToolbarCustomizeDialog(
            self,
            items_provider=self._toolbar_items_provider,
            set_checked=self._set_toolbar_visible_by_id,
            reset_fn=self._reset_toolbar_visibility,
        )
        dlg.exec()
        self._rebuild_toolbar_customize_menu()

    def _set_toolbar_visible_by_id(self, action_id: str, checked: bool) -> None:
        action_id = str(action_id or "")
        for a, aid in self._toolbar_action_ids.items():
            if aid == action_id:
                self._set_toolbar_action_visible(a, bool(checked))
                self._save_toolbar_visibility()
                break

    def _is_toolbar_action_visible(self, a: QAction) -> bool:
        tb = self._tb_main
        w = tb.widgetForAction(a)
        if w is not None:
            return w.isVisible()
        return a.isVisible()

    def _set_toolbar_action_visible(self, a: QAction, visible: bool) -> None:
        tb = self._tb_main
        w = tb.widgetForAction(a)
        if w is not None:
            w.setVisible(bool(visible))
        a.setVisible(bool(visible))

    def _restore_toolbar_visibility(self) -> None:
        schema_key = "2026-05-1cd-import"
        try:
            raw = self._settings.value("ui/toolbar_main_visible", "")
            if not raw:
                return
            if isinstance(raw, (list, tuple)):
                visible_ids = {str(x) for x in raw}
            else:
                visible_ids = set(json.loads(str(raw)))
        except Exception:
            return

        try:
            if str(self._settings.value("ui/toolbar_main_visible_schema", "") or "") != schema_key:
                visible_ids.add("tb_import_1cd")
                self._settings.setValue("ui/toolbar_main_visible_schema", schema_key)
                self._settings.setValue("ui/toolbar_main_visible", json.dumps(sorted(visible_ids)))
        except Exception:
            pass

        for a, aid in self._toolbar_action_ids.items():
            self._set_toolbar_action_visible(a, aid in visible_ids)

        self._rebuild_toolbar_customize_menu()

    def _save_toolbar_visibility(self) -> None:
        try:
            visible_ids = []
            for a, aid in self._toolbar_action_ids.items():
                if self._is_toolbar_action_visible(a):
                    visible_ids.append(aid)
            import json

            self._settings.setValue("ui/toolbar_main_visible", json.dumps(visible_ids))
            self._settings.setValue("ui/toolbar_main_visible_schema", "2026-05-1cd-import")
        except Exception:
            pass

    def _reset_toolbar_visibility(self) -> None:
        default = {
            "tb_new",
            "tb_open",
            "tb_save",
            "tb_import_1cd",
            "tb_source_structure_compare",
            "tb_source_structure_repair",
            "tb_cut",
            "tb_copy",
            "tb_paste",
            "tb_print",
            "tb_preview",
            "tb_undo",
            "tb_redo",
            "tb_global_search",
            "tb_find_next",
            "tb_find_prev",
            "tb_windows",
            "tb_syntax",
            "tb_templates",
            "tb_about",
            "tb_refresh",
            "tb_check",
            "tb_find_meta",
        }
        for a, aid in self._toolbar_action_ids.items():
            self._set_toolbar_action_visible(a, aid in default)
        self._save_toolbar_visibility()
        self._rebuild_toolbar_customize_menu()

    def _build_menu(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        menubar = self.menuBar()
        menubar.clear()
        m_file = menubar.addMenu(t("menu_file"))
        m_file.addAction(self.act_new)
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_save)
        m_file.addSeparator()
        m_file.addAction(self.act_print)
        m_file.addAction(self.act_print_preview)
        m_file.addSeparator()
        m_file.addAction(self.act_refresh)
        m_file.addSeparator()
        act_close = QAction(t("act_close"), self)
        act_close.setShortcut("Ctrl+W")
        act_close.triggered.connect(self.close)
        m_file.addAction(act_close)

        m_edit = menubar.addMenu(t("menu_edit"))
        m_edit.addAction(self.act_undo)
        m_edit.addAction(self.act_redo)
        m_edit.addSeparator()
        m_edit.addAction(self.act_cut)
        m_edit.addAction(self.act_copy)
        m_edit.addAction(self.act_paste)
        m_edit.addSeparator()
        m_edit.addAction(self.act_find_meta)
        m_edit.addAction(self.act_find_next)
        m_edit.addAction(self.act_find_prev)
        m_edit.addSeparator()
        m_edit.addAction(self.act_global_search)

        m_view = menubar.addMenu(t("menu_view"))
        m_cfg = menubar.addMenu(t("menu_configuration"))

        m_cfg.addAction(self.act_import_1cd)
        m_cfg.addAction(self.act_subsystem_report)
        m_cfg.addAction(self.act_structure_compare)
        m_cfg.addAction(self.act_structure_repair)
        act_load_cfg_files = QAction(t("cfg_load_from_files"), self)
        act_load_cfg_files.triggered.connect(self._load_configuration_from_files)
        m_cfg.addAction(act_load_cfg_files)
        m_cfg.addSeparator()

        m_cfg.addAction(self.act_run_client)
        m_cfg.addAction(self.act_run_client_debug)
        m_cfg.addSeparator()

        act_dsl_editor = QAction(t("cfg_dsl_editor"), self)
        act_dsl_editor.setShortcut("Ctrl+Alt+D")
        act_dsl_editor.triggered.connect(self._open_dsl_editor)
        m_cfg.addAction(act_dsl_editor)
        act_normalize_modules = QAction(t("cfg_modules_normalize_locale"), self)
        act_normalize_modules.triggered.connect(self._normalize_modules_to_current_locale)
        m_cfg.addAction(act_normalize_modules)

        m_cfg_storage = m_cfg.addMenu(t("menu_config_storage"))
        act_cfg_storage_connect = QAction(t("ctx_storage_connect"), self)
        act_cfg_storage_connect.triggered.connect(self._storage_connect_dialog)
        m_cfg_storage.addAction(act_cfg_storage_connect)
        act_cfg_storage_disconnect = QAction(t("cfg_storage_disconnect"), self)
        act_cfg_storage_disconnect.triggered.connect(self._cfg_storage_disconnect)
        m_cfg_storage.addAction(act_cfg_storage_disconnect)
        m_cfg_storage.addSeparator()
        act_cfg_storage_status = QAction(t("cfg_storage_status"), self)
        act_cfg_storage_status.triggered.connect(self._cfg_storage_status)
        m_cfg_storage.addAction(act_cfg_storage_status)
        act_cfg_storage_history = QAction(t("cfg_storage_history"), self)
        act_cfg_storage_history.triggered.connect(self._cfg_storage_history_storage)
        m_cfg_storage.addAction(act_cfg_storage_history)
        act_cfg_storage_admin = QAction(t("cfg_storage_admin"), self)
        act_cfg_storage_admin.triggered.connect(self._cfg_storage_admin)
        m_cfg_storage.addAction(act_cfg_storage_admin)

        act_view_tree = QAction(t("cfg_tree_title"), self)
        act_view_tree.setCheckable(True)
        act_view_tree.setChecked(self.dock_tree.isVisible())
        act_view_tree.triggered.connect(lambda checked: self.dock_tree.setVisible(bool(checked)))
        m_view.addAction(act_view_tree)
        self.act_view_properties = QAction(t("act_properties"), self)
        self.act_view_properties.setCheckable(True)
        self.act_view_properties.setChecked(self._props_visible)
        self.act_view_properties.setShortcut("F4")
        self.act_view_properties.triggered.connect(lambda checked: self.set_properties_visible(bool(checked)))
        m_view.addAction(self.act_view_properties)
        self.act_view_problems = QAction(t("workspace_problems_title"), self)
        self.act_view_problems.setCheckable(True)
        self.act_view_problems.setChecked(self.dock_problems.isVisible())
        self.act_view_problems.setShortcut("Ctrl+Alt+P")
        self.act_view_problems.triggered.connect(
            lambda checked: self.dock_problems.setVisible(bool(checked))
        )
        m_view.addAction(self.act_view_problems)
        self.act_next_problem = QAction(t("workspace_problems_next"), self)
        self.act_next_problem.setShortcut("F8")
        self.act_next_problem.triggered.connect(
            lambda: self._navigate_workspace_problem(1)
        )
        m_view.addAction(self.act_next_problem)
        self.act_previous_problem = QAction(t("workspace_problems_previous"), self)
        self.act_previous_problem.setShortcut("Shift+F8")
        self.act_previous_problem.triggered.connect(
            lambda: self._navigate_workspace_problem(-1)
        )
        m_view.addAction(self.act_previous_problem)
        m_view.addSeparator()
        m_view.addAction(self.act_windows_list)

        m_admin = menubar.addMenu(t("menu_admin"))

        def _stub(_action_key: str) -> None:
            self.show_info(t("info_title"), t("info_not_implemented"))

        act_users = QAction(t("admin_users"), self)
        act_users.triggered.connect(lambda: self.open_admin_users(active_only=False))
        m_admin.addAction(act_users)

        act_active_users = QAction(t("admin_active_users"), self)
        act_active_users.triggered.connect(lambda: self.open_admin_users(active_only=True))
        m_admin.addAction(act_active_users)
        m_admin.addSeparator()

        act_reg_log = QAction(t("admin_reg_log"), self)
        act_reg_log.triggered.connect(self.open_admin_audit_log)
        m_admin.addAction(act_reg_log)

        act_auth_locks = QAction(t("admin_auth_locks"), self)
        act_auth_locks.triggered.connect(lambda: _stub("admin_auth_locks"))
        m_admin.addAction(act_auth_locks)
        m_admin.addSeparator()
        act_module_browser = QAction(t("admin_module_browser"), self)
        act_module_browser.setShortcut("Ctrl+Shift+M")
        act_module_browser.triggered.connect(self._open_module_browser)
        m_admin.addAction(act_module_browser)

        m_admin.addSeparator()
        act_update_db = QAction(t("admin_update_db"), self)
        act_update_db.setShortcut("Ctrl+Shift+U")
        act_update_db.setToolTip(t("admin_update_db_tooltip"))
        act_update_db.triggered.connect(self._run_update_db)
        m_admin.addAction(act_update_db)

        m_admin.addSeparator()
        m_repo = m_admin.addMenu(t("admin_repo_menu"))
        act_repo_configure = QAction(t("admin_repo_configure"), self)
        act_repo_configure.triggered.connect(self.configure_main_db_for_repo)
        m_repo.addAction(act_repo_configure)
        m_repo.addSeparator()
        act_repo_checkout = QAction(t("admin_repo_checkout"), self)
        act_repo_checkout.triggered.connect(self.repo_checkout_selected)
        m_repo.addAction(act_repo_checkout)
        act_repo_submit = QAction(t("admin_repo_submit"), self)
        act_repo_submit.triggered.connect(self.repo_submit_selected)
        m_repo.addAction(act_repo_submit)
        m_repo.addSeparator()
        act_repo_force_unlock = QAction(t("admin_repo_force_unlock"), self)
        act_repo_force_unlock.triggered.connect(self.repo_force_unlock_selected)
        m_repo.addAction(act_repo_force_unlock)

        m_admin.addSeparator()
        act_unload = QAction(t("admin_unload_db"), self)
        act_unload.triggered.connect(self._run_unload_db)
        m_admin.addAction(act_unload)
        act_load = QAction(t("admin_load_db"), self)
        act_load.triggered.connect(self._run_load_db)
        m_admin.addAction(act_load)

        m_admin.addSeparator()
        act_web_publish = QAction(t("admin_web_publish"), self)
        act_web_publish.triggered.connect(lambda: _stub("admin_web_publish"))
        m_admin.addAction(act_web_publish)

        m_admin.addSeparator()
        act_test_repair = QAction(t("admin_test_repair"), self)
        act_test_repair.triggered.connect(self._open_test_repair)
        m_admin.addAction(act_test_repair)

        m_admin.addSeparator()
        act_log_settings = QAction(t("admin_log_settings"), self)
        act_log_settings.triggered.connect(self._open_log_settings)
        m_admin.addAction(act_log_settings)
        act_regional = QAction(t("admin_regional_settings"), self)
        act_regional.triggered.connect(self._open_regional_settings)
        m_admin.addAction(act_regional)
        act_auth_settings = QAction(t("admin_auth_settings"), self)
        act_auth_settings.triggered.connect(self._open_auth_settings)
        m_admin.addAction(act_auth_settings)
        act_client_lic = QAction(t("admin_client_licensing"), self)
        act_client_lic.triggered.connect(lambda: _stub("admin_client_licensing"))
        m_admin.addAction(act_client_lic)
        act_binary = QAction(t("admin_binary_storage"), self)
        act_binary.triggered.connect(lambda: _stub("admin_binary_storage"))
        m_admin.addAction(act_binary)
        act_pwd = QAction(t("admin_get_stored_password"), self)
        act_pwd.triggered.connect(lambda: _stub("admin_get_stored_password"))
        m_admin.addAction(act_pwd)
        act_params = QAction(t("admin_infobase_params"), self)
        act_params.triggered.connect(self._open_infobase_params)
        m_admin.addAction(act_params)

        self._menu_windows = menubar.addMenu(t("menu_windows"))
        m_win = self._menu_windows
        m_win.aboutToShow.connect(self._rebuild_windows_menu_list)

        m_pics = menubar.addMenu(t("menu_pictures"))
        self.act_pics_view = QAction(t("pictures_view"), self)
        self.act_pics_view.triggered.connect(self.open_pictures_gallery)
        m_pics.addAction(self.act_pics_view)
        self.act_pics_edit = QAction(t("pictures_open_editor"), self)
        self.act_pics_edit.triggered.connect(self.open_svg_editor_for_selection)
        m_pics.addAction(self.act_pics_edit)
        self.act_pics_upload = QAction(t("pictures_upload"), self)
        self.act_pics_upload.triggered.connect(self.upload_pictures_via_dialog)
        m_pics.addAction(self.act_pics_upload)

        m_help = menubar.addMenu(t("menu_help"))
        m_help.addAction(self.act_syntax_help)
        m_help.addAction(self.act_syntax_help_search)
        m_help.addSeparator()
        m_help.addAction(self.act_templates)
        m_help.addSeparator()
        m_help.addAction(self.act_about)

    def _rebuild_windows_menu_list(self) -> None:
        m = getattr(self, "_menu_windows", None)
        if m is None:
            return
        m.clear()
        act_list = QAction(t("act_windows_list"), self)
        act_list.triggered.connect(self._on_windows_list)
        m.addAction(act_list)
        m.addSeparator()
        act_cascade = QAction(t("win_cascade"), self)
        act_cascade.triggered.connect(self.mdi.cascadeSubWindows)
        m.addAction(act_cascade)
        act_tile = QAction(t("win_tile"), self)
        act_tile.triggered.connect(self.mdi.tileSubWindows)
        m.addAction(act_tile)
        m.addSeparator()
        act_close_active = QAction(t("win_close"), self)
        act_close_active.setShortcut("Ctrl+F4")
        act_close_active.triggered.connect(lambda: self.mdi.closeActiveSubWindow())
        m.addAction(act_close_active)
        act_close_all = QAction(t("win_close_all"), self)
        act_close_all.triggered.connect(self.mdi.closeAllSubWindows)
        m.addAction(act_close_all)
        m.addSeparator()
        subs = self.mdi.subWindowList()
        active = self.mdi.activeSubWindow()
        if not subs:
            act_empty = QAction(t("win_no_windows"), self)
            act_empty.setEnabled(False)
            m.addAction(act_empty)
            return
        if not hasattr(self, "_win_list_actions_group") or self._win_list_actions_group is None:
            from PySide6.QtGui import QActionGroup

            self._win_list_actions_group = QActionGroup(self)
            self._win_list_actions_group.setExclusive(True)
        for i, sub in enumerate(subs, start=1):
            title = sub.windowTitle() or t("win_untitled")
            act = QAction(f"{i}. {title}", self)
            act.setCheckable(True)
            act.setChecked(sub is active)
            act.setActionGroup(self._win_list_actions_group)
            act.triggered.connect(lambda checked=False, s=sub: self._activate_subwindow(s))
            m.addAction(act)

    def _activate_subwindow(self, sub) -> None:
        if sub is None:
            return
        self.mdi.setActiveSubWindow(sub)
        try:
            sub.showNormal()
            sub.raise_()
        except Exception:
            pass
