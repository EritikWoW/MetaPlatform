from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QSizePolicy, QTabBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from src.ui_qt.i18n import t

from .client_window_helpers import _load_svg_icon
from .client_window_runtime import logger


_HEADER_BTN_PRIMARY = """
QPushButton {
    background: #4D9EFF; color: #FFFFFF; border: none;
    border-radius: 6px; padding: 0 16px;
    font-size: 10pt; font-weight: 600; min-height: 34px;
}
QPushButton:hover   { background: #2D7FD9; }
QPushButton:pressed { background: #1E6EC5; }
QPushButton:disabled { background: #CBD5E1; color: #94A3B8; }
"""
_HEADER_BTN_OUTLINE = """
QPushButton {
    background: transparent; color: #334155;
    border: 1px solid #E2E8F0; border-radius: 6px;
    padding: 0 14px; font-size: 10pt; min-height: 34px;
}
QPushButton:hover { border-color: #4D9EFF; color: #4D9EFF; }
"""
_HEADER_BTN_GHOST = """
QToolButton {
    background: transparent; border: none;
    border-radius: 6px; padding: 6px;
    color: #64748B;
}
QToolButton:hover { background: #F1F5F9; color: #334155; }
"""


class ClientWindowUiMixin:
    def _resolve_window_title(self) -> str:
        # Prefer launcher-provided DB name.
        db_name = ""
        if self._runtime is not None and getattr(self._runtime, "db_name", ""):
            db_name = str(self._runtime.db_name).strip()
        if not db_name and self._db_path is not None:
            db_name = self._db_path.stem

        if db_name:
            return t("client_title_with_db").format(db=db_name)
        return t("client_title")


    def _apply_light_workspace_style(self, main_col: QWidget) -> None:
        """Override dark app theme for the client workspace area only."""
        css = """
        QWidget#ClientMain { background: #F1F5F9; }
        QWidget#ClientMain QWidget { background: transparent; }
        QWidget#ClientMain, QWidget#ClientMain * { color: #0F172A; }

        /* ── Tab widget ─────────────────────────────────────── */
        QTabWidget#ClientTabs::pane {
            border: none;
            background: #FFFFFF;
        }
        QTabWidget#ClientTabs > QTabBar {
            background: #F1F5F9;
        }
        QTabBar::tab {
            background: #F1F5F9;
            color: #64748B;
            border: none;
            border-right: 1px solid rgba(0,0,0,0.06);
            padding: 10px 14px 10px 18px;
            font-size: 10pt;
            min-width: 80px;
            font-family: 'Roboto', 'Segoe UI', sans-serif;
        }
        QTabBar::tab:selected {
            background: #FFFFFF;
            color: #1A2744;
            font-weight: 600;
            border-bottom: 2px solid #4D9EFF;
        }
        QTabBar::tab:hover:!selected {
            background: #E2E8F0;
            color: #0F172A;
        }
        QTabBar::close-button {
            subcontrol-position: right;
            margin-left: 4px;
            width: 14px;
            height: 14px;
        }
        QTabBar::close-button:hover {
            background: rgba(0,0,0,0.10);
            border-radius: 3px;
        }
        /* Dirty tabs (*) — orange accent */
        QTabBar::tab[text^="* "] {
            color: #D97706;
        }

        /* ── Common inputs ──────────────────────────────────── */
        QWidget#ClientMain QLineEdit {
            background: #FFFFFF;
            border: 1px solid rgba(0,0,0,0.14);
            border-radius: 8px;
            padding: 5px 10px;
            color: #0F172A;
        }
        QWidget#ClientMain QLineEdit:focus { border-color: #2563EB; }

        /* ── Tables ─────────────────────────────────────────── */
        QWidget#ClientMain QTableView {
            background: #FFFFFF;
            border: none;
            gridline-color: transparent;
            alternate-background-color: #F8FAFC;
            selection-background-color: #EFF6FF;
            selection-color: #0F172A;
        }
        QWidget#ClientMain QTableView::item { padding: 4px 12px; }
        QWidget#ClientMain QHeaderView::section {
            background: #F8FAFC;
            color: #374151;
            padding: 8px 12px;
            border: none;
            border-bottom: 2px solid rgba(0,0,0,0.08);
            font-weight: 600;
        }
        """
        main_col.setStyleSheet(css)


    def _populate_nav_tree_loading(self) -> None:
        """Show dashboard + loading placeholder before real data arrives."""
        self._nav.clear()
        dash = QTreeWidgetItem()
        dash.setText(0, t("client_nav_dashboard"))
        dash.setData(0, Qt.ItemDataRole.UserRole, "dashboard")
        dash.setIcon(0, _load_svg_icon(self._icon_provider, "layout-dashboard", size=16))
        self._nav.addTopLevelItem(dash)
        self._nav.setCurrentItem(dash)

        loading = QTreeWidgetItem()
        loading.setText(0, f"  ⏳  {t('client_nav_loading')}")
        loading.setFlags(Qt.ItemFlag.NoItemFlags)
        self._nav.addTopLevelItem(loading)


    def _build_header_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("ClientHeaderBar")
        bar.setFixedHeight(56)
        bar.setStyleSheet("""
            QFrame#ClientHeaderBar {
                background: #FFFFFF;
                border-bottom: 1px solid #E8EBF1;
            }
        """)
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(20, 0, 16, 0)
        hl.setSpacing(10)

        self._hdr_title = QLabel(t("client_nav_dashboard"), bar)
        self._hdr_title.setStyleSheet(
            "font-size: 13pt; font-weight: 700; color: #1A2744; background: transparent;"
        )
        hl.addWidget(self._hdr_title)
        hl.addStretch(1)

        # Search
        self._hdr_search = QLineEdit(bar)
        self._hdr_search.setPlaceholderText(t("client_search_placeholder"))
        self._hdr_search.setFixedWidth(220)
        self._hdr_search.setFixedHeight(34)
        self._hdr_search.setStyleSheet("""
            QLineEdit {
                background: #F1F5F9; border: 1px solid #E2E8F0;
                border-radius: 6px; padding: 0 10px;
                font-size: 10pt; color: #1A2744;
            }
            QLineEdit:focus { border-color: #4D9EFF; background: #FFFFFF; }
        """)
        self._hdr_search.textChanged.connect(self._on_header_search)
        hl.addWidget(self._hdr_search)

        # Create button
        self._hdr_create = QPushButton("+ " + t("client_btn_create"), bar)
        self._hdr_create.setStyleSheet(_HEADER_BTN_PRIMARY)
        self._hdr_create.clicked.connect(self._on_header_create)
        hl.addWidget(self._hdr_create)

        # Configurator button
        cfg_btn = QPushButton("⚙ " + t("client_btn_configurator"), bar)
        cfg_btn.setStyleSheet(_HEADER_BTN_OUTLINE)
        cfg_btn.clicked.connect(self._on_open_configurator)
        hl.addWidget(cfg_btn)

        # Icon buttons
        for icon_text, tip in [("🔔", t("client_notifications")), ("❓", t("menu_help"))]:
            btn = QToolButton(bar)
            btn.setText(icon_text)
            btn.setToolTip(tip)
            btn.setStyleSheet(_HEADER_BTN_GHOST)
            btn.setFixedSize(34, 34)
            hl.addWidget(btn)

        return bar


    def _update_header_bar(self) -> None:
        """Оновити заголовок та стан кнопок header-бару."""
        if not hasattr(self, "_hdr_title"):
            return
        w = self._tab_widget.currentWidget() if hasattr(self, "_tab_widget") else None
        view_id = next((vid for vid, vw in self._views.items() if vw is w), "") if w else ""

        # Title
        title = ""
        if w is not None and hasattr(w, "title"):
            try:
                title = str(getattr(w, "title") or "")
            except Exception:
                pass
        if not title:
            title = self._titles.get(view_id, "")
        if not title and view_id:
            title = view_id.split(":")[0].capitalize()
        self._hdr_title.setText(title or t("client_nav_dashboard"))

        # Create button: active only for list/object forms
        is_form = view_id.startswith(("list:", "obj:"))
        self._hdr_create.setEnabled(is_form)

        # Search sync: focus the active form's search if it's a list
        # (actual forwarding happens in _on_header_search)


    def _on_header_create(self) -> None:
        """Натискання глобальної кнопки «Створити»."""
        from src.client.forms.form_runtime import FormRuntimeWidget
        w = self._tab_widget.currentWidget()
        form = None
        if isinstance(w, FormRuntimeWidget):
            form = w
        elif w is not None:
            for child in w.findChildren(FormRuntimeWidget):
                form = child
                break
        if form and hasattr(form, "_emit_command"):
            form._emit_command("create")


    def _on_header_search(self, text: str) -> None:
        """Global search: filter the active list or the metadata navigation."""
        from src.client.forms.form_runtime import FormRuntimeWidget
        w = self._tab_widget.currentWidget()
        if w is None:
            if hasattr(self, "_nav_search"):
                self._nav_search.setText(text)
            return
        form = None
        if isinstance(w, FormRuntimeWidget):
            form = w
        elif w is not None:
            for child in w.findChildren(FormRuntimeWidget):
                form = child
                break
        if form and hasattr(form, "_list_table") and form._list_table is not None:
            proxy = getattr(form._list_table, "_filter_proxy", None)
            if proxy is not None:
                proxy.setFilterWildcard(text)
                return

        # On dashboard/reports/settings the same field searches the metadata
        # projection, matching the reference client's single global search.
        if hasattr(self, "_nav_search"):
            self._nav_search.setText(text)


    def _on_open_configurator(self) -> None:
        """Запуск конфігуратора як окремого процесу (якщо є)."""
        import subprocess, sys
        try:
            subprocess.Popen([sys.executable, "-m", "src.configurator.main"],
                             cwd=str(__import__("pathlib").Path(__file__).parents[2]))
        except Exception:
            pass


    def _build_sidebar(self) -> QWidget:
        w = QFrame(self)
        w.setMinimumWidth(180)
        w.setMaximumWidth(420)
        w.setFrameShape(QFrame.Shape.NoFrame)
        w.setStyleSheet("""
            QFrame { background: #1F2942; }
            QTreeWidget#ClientNav {
                background: transparent;
                border: none;
                color: #C8D0E0;
                outline: none;
                font-size: 10pt;
                padding: 4px 0;
            }
            QTreeWidget#ClientNav::item {
                border-radius: 8px;
                padding: 7px 10px;
                margin: 1px 8px;
                color: #C8D0E0;
            }
            QTreeWidget#ClientNav::item:selected {
                background: #4D9EFF;
                color: #FFFFFF;
            }
            QTreeWidget#ClientNav::item:hover:!selected {
                background: rgba(255,255,255,0.07);
                color: #E5EAF5;
            }
            QTreeWidget#ClientNav::branch {
                background: transparent;
            }
        """)

        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)

        # Top / "logo" block
        top = QFrame(w)
        top.setFixedHeight(56)
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(12, 10, 12, 10)
        top_l.setSpacing(10)

        logo = QLabel(top)
        logo.setFixedSize(32, 32)
        logo.setScaledContents(True)
        # Use app icon as logo if possible
        app_ico = self.windowIcon()
        if not app_ico.isNull():
            logo.setPixmap(app_ico.pixmap(32, 32))
        top_l.addWidget(logo)

        txt_box = QVBoxLayout()
        txt_box.setContentsMargins(0, 0, 0, 0)
        txt_box.setSpacing(1)

        title = QLabel(t("client_product_name"), top)
        title.setStyleSheet("font-weight: 700; color: #E5EAF5;")
        subtitle = QLabel("v1.0", top)
        subtitle.setStyleSheet("color: rgba(200,208,224,0.65); font-size: 9pt;")

        txt_box.addWidget(title)
        txt_box.addWidget(subtitle)
        top_l.addLayout(txt_box)
        top_l.addStretch(1)

        l.addWidget(top)

        # Nav search
        nav_search = QLineEdit(w)
        nav_search.setPlaceholderText("🔍  " + t("client_search_menu_placeholder"))
        nav_search.setStyleSheet("""
            QLineEdit {
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 6px;
                padding: 5px 10px;
                color: #C8D0E0;
                font-size: 9pt;
                margin: 4px 8px;
            }
            QLineEdit:focus { border-color: #4D9EFF; background: rgba(255,255,255,0.12); }
        """)
        nav_search.textChanged.connect(self._on_nav_search)
        self._nav_search = nav_search
        l.addWidget(nav_search)

        # Nav tree
        self._nav = QTreeWidget(w)
        self._nav.setHeaderHidden(True)
        self._nav.setIndentation(18)
        self._nav.setRootIsDecorated(True)
        self._nav.setExpandsOnDoubleClick(True)
        self._nav.setUniformRowHeights(True)
        self._nav.setAnimated(True)
        self._nav.setObjectName("ClientNav")
        self._nav.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._nav.customContextMenuRequested.connect(self._on_nav_context_menu)

        l.addWidget(self._nav, 1)

        # Show minimal nav immediately; real data loaded in _deferred_init
        self._populate_nav_tree_loading()
        self._nav.itemSelectionChanged.connect(self._on_nav_selection_changed)

        # Footer / user
        footer = QFrame(w)
        footer.setFixedHeight(64)
        f_l = QHBoxLayout(footer)
        f_l.setContentsMargins(12, 10, 12, 10)
        f_l.setSpacing(10)

        avatar = QLabel(footer)
        avatar.setFixedSize(32, 32)
        avatar.setStyleSheet("border-radius: 16px; background: rgba(255,255,255,0.10);")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setText("A")
        f_l.addWidget(avatar)

        user_box = QVBoxLayout()
        user_box.setContentsMargins(0, 0, 0, 0)
        user_box.setSpacing(1)

        u_name = QLabel(t("client_user_name"), footer)
        u_name.setStyleSheet("color: #E5EAF5; font-size: 9.5pt; font-weight: 600;")
        # Show DB name as subtitle
        db_name = ""
        if self._runtime is not None:
            db_name = str(getattr(self._runtime, "db_name", "") or "").strip()
        u_mail = QLabel(db_name or t("client_status_no_db"), footer)
        u_mail.setStyleSheet("color: rgba(200,210,230,0.65); font-size: 8.5pt;")
        user_box.addWidget(u_name)
        user_box.addWidget(u_mail)
        f_l.addLayout(user_box, 1)

        # Connection indicator dot
        self._conn_dot = QLabel("●", footer)
        self._conn_dot.setStyleSheet("color: #22C55E; font-size: 10pt;")
        self._conn_dot.setToolTip(t("client_runtime_connected"))
        f_l.addWidget(self._conn_dot)

        l.addWidget(footer)

        return w



    def _populate_nav_tree(self) -> None:
        self._nav.setUpdatesEnabled(False)
        self._nav.blockSignals(True)
        try:
            self._nav.clear()

            # Prefer metadata-driven navigation when DB is available.
            # If manifest has no user objects yet, fall back to the static demo menu.
            if self._populate_nav_tree_from_manifest():
                return

            # No user objects in manifest yet — show minimal nav with fixed sections only
            def add_fixed(node_id: str, title_key: str, icon: str) -> QTreeWidgetItem:
                node = QTreeWidgetItem()
                node.setText(0, t(title_key))
                node.setData(0, Qt.ItemDataRole.UserRole, node_id)
                node.setIcon(0, _load_svg_icon(self._icon_provider, icon, size=16))
                self._nav.addTopLevelItem(node)
                return node

            add_fixed("dashboard", "client_nav_dashboard", "layout-dashboard")
            add_fixed("reports",   "client_nav_reports",   "bar-chart-3")
            add_fixed("settings",  "client_nav_settings",  "settings")
            # Select dashboard by default
            if self._nav.topLevelItemCount():
                self._nav.setCurrentItem(self._nav.topLevelItem(0))
        finally:
            self._nav.blockSignals(False)
            self._nav.setUpdatesEnabled(True)


    def _populate_nav_tree_from_manifest(self) -> bool:
        """Build navigation tree from manifest objects (MVP).

        Strategy:
          - Always show Dashboard.
          - If there are Subsystems: group objects by subsystem assignment.
          - Otherwise: show Catalogs/Documents groups.

        Item IDs:
          - group:* are non-navigational.
          - meta:<obj_guid>:list opens the object's list form.
        """
        started = time.perf_counter()
        user_objs, subsystems, report_objs = self._manifest_nav_rows()
        # If there are no user objects, do not switch to metadata mode.
        if not user_objs:
            return False

        def add_node(parent: QTreeWidgetItem | None, *, title: str, node_id: str, icon: str | None = None) -> QTreeWidgetItem:
            it = QTreeWidgetItem()
            it.setText(0, title)
            it.setData(0, Qt.ItemDataRole.UserRole, node_id)
            if icon:
                it.setIcon(0, _load_svg_icon(self._icon_provider, icon, size=16))
            if parent is None:
                self._nav.addTopLevelItem(it)
            else:
                parent.addChild(it)
            return it

        # Always: Dashboard.
        dash = add_node(None, title=t("client_nav_dashboard"), node_id="dashboard", icon="layout-dashboard")
        self._nav.setCurrentItem(dash)

        # Grouping.
        guid_to_sub = {str(s.get("guid") or ""): s for s in subsystems if str(s.get("guid") or "")}

        def obj_title(row: dict[str, object]) -> str:
            return self._row_title(row) or "Object"

        catalog_doc_objs = [
            row for row in user_objs
            if str(row.get("type") or "").lower() in {"catalog", "document", "register_accum", "register_info"}
        ]

        # Build nav even if there are no catalogs/docs yet
        if subsystems:
            type_order = ["catalog", "document", "register_accum", "register_info"]
            type_labels = {
                "catalog":        t("client_nav_catalogs")   or "Довідники",
                "document":       t("client_nav_documents")  or "Документи",
                "register_accum": t("client_nav_reg_accum")  or "Регістри накопичення",
                "register_info":  t("client_nav_reg_info")   or "Регістри відомостей",
            }
            type_icons = {
                "catalog":        "book-open",
                "document":       "file-text",
                "register_accum": "trending-up",
                "register_info":  "database",
            }

            sorted_subs = sorted(subsystems, key=lambda s: obj_title(s).casefold())

            # Build reverse map object_guid → [subsystem_guid, ...]
            # Membership is stored in the SUBSYSTEM payload: payload.objects = [obj_guid, ...].
            # Slim manifest rows already include subsystem membership as `objects`;
            # if not present, fall back to the lightweight membership RPC.
            _gw = getattr(self._db, "_gw", None) if self._db is not None else None

            def _sub_objects(sub_row: dict) -> list[str]:
                objs = sub_row.get("objects") if isinstance(sub_row, dict) else None
                if isinstance(objs, list):
                    return [str(g).strip() for g in (objs or []) if str(g).strip()]
                # Membership may be externalized — fetch only the object GUIDs.
                if _gw is not None and hasattr(_gw, "manifest_get_objects"):
                    guid_key = str(sub_row.get("guid") or "").strip()
                    if guid_key:
                        try:
                            objs = _gw.manifest_get_objects(guid_key)
                            return [str(g).strip() for g in (objs or []) if str(g).strip()]
                        except Exception:
                            pass
                # Backward-compatible fallback for older runtimes.
                if _gw is not None and hasattr(_gw, "manifest_get_payload"):
                    guid_key = str(sub_row.get("guid") or "").strip()
                    if guid_key:
                        try:
                            full = _gw.manifest_get_payload(guid_key)
                            if isinstance(full, dict):
                                objs = full.get("objects") or []
                                return [str(g).strip() for g in objs if str(g).strip()]
                        except Exception:
                            pass
                return []

            obj_to_sub_guids: dict[str, list[str]] = {}
            for sub in subsystems:
                sg = str(sub.get("guid") or "").strip()
                if not sg:
                    continue
                for obj_guid in _sub_objects(sub):
                    obj_to_sub_guids.setdefault(obj_guid, []).append(sg)

            # Group objects by type
            buckets: dict[str, list] = {t_: [] for t_ in type_order}
            for o in catalog_doc_objs:
                tpe = str(o.get("type") or "").lower()
                if tpe in buckets:
                    buckets[tpe].append(o)

            for tpe in type_order:
                items = buckets[tpe]
                if not items:
                    continue

                grp = add_node(None, title=type_labels[tpe], node_id=f"group:{tpe}", icon=type_icons[tpe])

                # Map subsystem guid → objects assigned to it
                sub_buckets: dict[str, list] = {str(s.get("guid") or ""): [] for s in sorted_subs}
                unassigned: list = []

                for o in sorted(items, key=lambda x: obj_title(x).casefold()):
                    o_guid = str(o.get("guid") or "").strip()
                    sub_guids = obj_to_sub_guids.get(o_guid, [])
                    if sub_guids:
                        for sg in sub_guids:
                            if sg in sub_buckets:
                                sub_buckets[sg].append(o)
                    else:
                        unassigned.append(o)

                # Add subsystem sub-groups (only non-empty ones)
                for sub in sorted_subs:
                    sg = str(sub.get("guid") or "")
                    objs_in_sub = sub_buckets.get(sg) or []
                    if not objs_in_sub:
                        continue
                    sub_grp = add_node(grp, title=obj_title(sub), node_id=f"group:sub:{sg}:{tpe}")
                    for o in objs_in_sub:
                        add_node(sub_grp, title=obj_title(o), node_id=f"meta:{o.get('guid')}:list")
                    self._nav.expandItem(sub_grp)

                # Objects not assigned to any subsystem — add directly under type group
                for o in unassigned:
                    add_node(grp, title=obj_title(o), node_id=f"meta:{o.get('guid')}:list")

                self._nav.expandItem(grp)

            self._add_fixed_nav_sections(report_objs)
            logger.info(
                "nav.populate source=manifest rows=%s catalogs_docs=%s reports=%s subsystems=%s total=%.3fs",
                len(user_objs),
                len(catalog_doc_objs),
                len(report_objs),
                len(subsystems),
                time.perf_counter() - started,
            )
            return True

        # No subsystems: group by type.
        if catalog_doc_objs:
            grp_cat = add_node(None, title=t("client_nav_catalogs"), node_id="group:catalogs", icon="book-open")
            grp_doc = add_node(None, title=t("client_nav_documents"), node_id="group:documents", icon="file-text")

            for o in sorted(catalog_doc_objs, key=lambda x: (str(x.get("type") or "").lower(), obj_title(x).casefold())):
                tpe = str(o.get("type") or "").lower()
                parent = grp_cat if tpe == "catalog" else grp_doc
                add_node(parent, title=obj_title(o), node_id=f"meta:{o.get('guid')}:list")

            self._nav.expandItem(grp_cat)
            self._nav.expandItem(grp_doc)

        self._add_fixed_nav_sections(report_objs)
        logger.info(
            "nav.populate source=manifest rows=%s catalogs_docs=%s reports=%s subsystems=%s total=%.3fs",
            len(user_objs),
            len(catalog_doc_objs),
            len(report_objs),
            len(subsystems),
            time.perf_counter() - started,
        )
        return True


    def _add_fixed_nav_sections(self, report_rows: list[dict[str, object]] | None = None) -> None:
        """Add Reports and Settings as fixed bottom items in the nav tree."""
        sep = QTreeWidgetItem()
        sep.setFlags(Qt.ItemFlag.NoItemFlags)
        sep.setData(0, Qt.ItemDataRole.UserRole, "group:sep")
        self._nav.addTopLevelItem(sep)

        # Reports node — with report objects as children if any exist
        rpt_node = QTreeWidgetItem()
        rpt_node.setText(0, t("client_nav_reports"))
        rpt_node.setData(0, Qt.ItemDataRole.UserRole, "reports")
        rpt_node.setIcon(0, _load_svg_icon(self._icon_provider, "bar-chart-3", size=16))
        self._nav.addTopLevelItem(rpt_node)

        rpt_objs = list(report_rows or [])
        for o in sorted(rpt_objs, key=lambda x: self._row_title(x).casefold()):
            ch = QTreeWidgetItem()
            ch.setText(0, self._row_title(o))
            ch.setData(0, Qt.ItemDataRole.UserRole, f"meta:{o.get('guid')}:list")
            rpt_node.addChild(ch)
        if rpt_objs:
            self._nav.expandItem(rpt_node)

        # Settings
        cfg_node = QTreeWidgetItem()
        cfg_node.setText(0, t("client_nav_settings"))
        cfg_node.setData(0, Qt.ItemDataRole.UserRole, "settings")
        cfg_node.setIcon(0, _load_svg_icon(self._icon_provider, "settings", size=16))
        self._nav.addTopLevelItem(cfg_node)


    def _on_lang_changed(self) -> None:
        """Refresh UI after language change — nav tree + tab titles + window title."""
        # Clear manifest cache so _row_title re-resolves with new language
        self._manifest_rows_cache = []
        self._manifest_by_guid_cache = {}

        # 1. Rebuild navigation tree
        self._populate_nav_tree()

        # 2. Update titles of ALL open tabs
        for view_id, w in self._views.items():
            new_title = self._resolve_title(view_id)
            self._titles[view_id] = new_title
            idx = self._tab_widget.indexOf(w)
            if idx >= 0:
                self._tab_widget.setTabText(idx, new_title)

        # 3. Window title
        self.setWindowTitle(self._resolve_window_title())

        # 4. Status bar
        if hasattr(self, "_sb_status"):
            from src.ui_qt.i18n import t as _t
            self._sb_status.setText(_t("status_ready"))


    def _on_nav_search(self, text: str) -> None:
        """Filter nav tree items by search text."""
        query = text.strip().casefold()

        def _set_visible(item, visible: bool) -> None:
            item.setHidden(not visible)

        def _filter(item) -> bool:
            """Return True if item or any child matches query."""
            label = item.text(0).casefold()
            matched = not query or query in label
            child_match = False
            for i in range(item.childCount()):
                if _filter(item.child(i)):
                    child_match = True
            visible = matched or child_match
            _set_visible(item, visible)
            if child_match:
                self._nav.expandItem(item)
            return visible

        for i in range(self._nav.topLevelItemCount()):
            _filter(self._nav.topLevelItem(i))


    def _find_nav_item(self, parent, node_id: str):
        """Рекурсивно шукає nav-елемент за node_id."""
        from PySide6.QtWidgets import QTreeWidgetItem
        count = parent.topLevelItemCount() if hasattr(parent, "topLevelItemCount") else parent.childCount()
        for i in range(count):
            item = parent.topLevelItem(i) if hasattr(parent, "topLevelItem") else parent.child(i)
            if item is None:
                continue
            if str(item.data(0, Qt.ItemDataRole.UserRole) or "") == node_id:
                return item
            found = self._find_nav_item(item, node_id)
            if found:
                return found
        return None

    def _sync_nav_to_view(self, view_id: str) -> None:
        """Підсвічує відповідний елемент nav-дерева для поточної вкладки."""
        node_id = ""
        if view_id in ("dashboard", "reports", "settings"):
            node_id = view_id
        elif view_id.startswith("list:"):
            guid = view_id[5:]
            node_id = f"meta:{guid}:list"
        # object form and others — no direct nav item, keep current selection

        if not node_id:
            return
        item = self._find_nav_item(self._nav, node_id)
        if item and self._nav.currentItem() is not item:
            self._nav.blockSignals(True)
            self._nav.setCurrentItem(item)
            self._nav.blockSignals(False)

    def _on_nav_selection_changed(self) -> None:
        items = self._nav.selectedItems()
        if not items:
            return
        view_id = str(items[0].data(0, Qt.ItemDataRole.UserRole) or "")
        if not view_id:
            return

        # Metadata navigation: open typical form for the selected object.
        if view_id.startswith("meta:"):
            parts = view_id.split(":", 2)
            if len(parts) >= 3:
                obj_guid = parts[1]
                mode = parts[2]
                self._open_meta_object(obj_guid, mode=mode)
            return

        # Groups expand/collapse; separators and unknown IDs are ignored.
        if view_id.startswith("group:") or not view_id:
            item = items[0]
            index = self._nav.indexFromItem(item)
            if item.childCount() > 0:
                if self._nav.isExpanded(index):
                    self._nav.collapse(index)
                else:
                    self._nav.expand(index)
            return

        self._select_view(view_id)

    def _on_nav_context_menu(self, pos) -> None:
        item = self._nav.itemAt(pos)
        if item is None:
            return
        view_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        menu = QMenu(self._nav)

        if view_id.startswith("meta:"):
            parts = view_id.split(":", 2)
            if len(parts) >= 3:
                obj_guid = parts[1]
                mode = parts[2]
                act_open = QAction(t("client_act_open_form"), self._nav)
                act_open.triggered.connect(lambda _=False, g=obj_guid, m=mode: self._open_meta_object(g, mode=m))
                menu.addAction(act_open)

                act_struct = QAction(t("client_act_object_structure"), self._nav)
                act_struct.triggered.connect(lambda _=False, g=obj_guid: self._open_structure_for_guid(g))
                menu.addAction(act_struct)
        elif view_id in ("dashboard", "reports", "settings"):
            act_open = QAction(t("act_open"), self._nav)
            act_open.triggered.connect(lambda _=False, v=view_id: self._select_view(v))
            menu.addAction(act_open)

        if menu.actions():
            menu.exec(self._nav.viewport().mapToGlobal(pos))


    def _on_tab_close_requested(self, index: int) -> None:
        """Close a tab and clean up the associated view."""
        from PySide6.QtWidgets import QMessageBox
        w = self._tab_widget.widget(index)
        view_id_to_remove = None
        for vid, vw in list(self._views.items()):
            if vw is w:
                view_id_to_remove = vid
                break
        # Never close fixed views
        if view_id_to_remove in ("dashboard", "reports", "settings", None):
            return
        # Warn if tab has unsaved changes (dirty marker)
        title = self._tab_widget.tabText(index)
        if title.startswith("* "):
            answer = QMessageBox.question(
                self,
                t("dlg_unsaved_title"),
                t("client_unsaved_close").format(title=title[2:]),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._views.pop(view_id_to_remove, None)
        self._titles.pop(view_id_to_remove, None)
        self._tab_widget.removeTab(index)
        if w:
            w.deleteLater()

    def _make_close_btn(self, idx: int) -> "QToolButton":
        """Close button with a painted ✕ icon — no PNG files needed."""
        from src.client.close_tab_button import make_close_button
        btn = make_close_button(self._tab_widget)
        btn.clicked.connect(
            lambda: self._on_tab_close_requested(
                self._tab_widget.indexOf(
                    self._tab_widget.widget(
                        self._tab_widget.currentIndex()
                        if idx >= self._tab_widget.count()
                        else idx
                    )
                )
            )
        )
        return btn

    def _register_view(self, view_id: str, w: QWidget) -> None:
        self._views[view_id] = w
        title = self._resolve_title(view_id)
        self._titles[view_id] = title
        idx = self._tab_widget.addTab(w, title)
        self._tab_widget.tabBar().setTabToolTip(idx, title)  # full title on hover

        if view_id in ("dashboard", "reports", "settings"):
            self._tab_widget.tabBar().setTabButton(idx, QTabBar.ButtonPosition.RightSide, None)
            self._tab_widget.tabBar().setTabButton(idx, QTabBar.ButtonPosition.LeftSide, None)
        else:
            btn = self._make_close_btn(idx)
            self._tab_widget.tabBar().setTabButton(idx, QTabBar.ButtonPosition.RightSide, btn)

        self._connect_list_stats(w)


    def _resolve_title(self, view_id: str) -> str:
        # If the registered view defines its own title attribute, use it.
        v = self._views.get(view_id)
        if v is not None and hasattr(v, "title"):
            try:
                title = str(getattr(v, "title"))
                if title:
                    return title
            except Exception:
                pass

        # For GUID-based views: extract object title from manifest
        for prefix in ("register:", "report:", "list:", "form:", "object:"):
            if view_id.startswith(prefix):
                guid = view_id[len(prefix):]
                row = self._manifest_row_by_guid(guid) if hasattr(self, "_manifest_row_by_guid") else None
                if isinstance(row, dict):
                    t_ = str(row.get("title") or row.get("name") or "")
                    if t_:
                        return t_
                break

        # Fallback: use i18n keys for fixed views.
        mapping = {
            "dashboard": "client_nav_dashboard",
            "reports":   "client_nav_reports",
            "settings":  "client_nav_settings",
        }
        key = mapping.get(view_id)
        return t(key) if key else view_id


    def _select_view(self, view_id: str) -> None:
        w = self._views.get(view_id)
        if w is None:
            w = self._views.get("dashboard")
            view_id = "dashboard"
        if w:
            self._tab_widget.setCurrentWidget(w)
            self._update_header_bar()
