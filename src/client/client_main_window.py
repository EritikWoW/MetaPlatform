from __future__ import annotations

import logging
import threading
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QMessageBox, QSplitter, QTabWidget, QVBoxLayout, QWidget

from src.runtime.gateway import GatewayDb, RuntimeGateway
from src.ui_qt.i18n import t, bind
from src.ui_qt.services.icon_provider import IconProvider

from .client_window_actions import ClientWindowActionsMixin
from .client_window_runtime import ClientWindowRuntimeMixin
from .client_window_ui import ClientWindowUiMixin
from .runtime_context import RuntimeContext
from .views import DashboardView, ReportsView, SettingsView

logger = logging.getLogger("client.window")


class ClientWindow(
    ClientWindowActionsMixin,
    ClientWindowRuntimeMixin,
    ClientWindowUiMixin,
    QMainWindow,
):
    create_requested = Signal(str)  # view_id

    def __init__(self, *, runtime: RuntimeContext | None, db_path: Path | None) -> None:
        super().__init__()
        self._runtime = runtime
        self._db_path = db_path
        self._manifest_rows_cache: list = []
        self._manifest_nav_rows_cache: list = []
        self._manifest_by_guid_cache: dict[str, dict[str, object]] = {}
        self._manifest_refresh_fingerprint: str = ""

        # Window title should reflect the selected DB name (from launcher).
        self.setWindowTitle(self._resolve_window_title())
        self.resize(1280, 820)

        self._icon_provider = IconProvider()

        # Connect to runtime server via RPC — no direct Mpdb access
        self._db: GatewayDb | None = None
        _runtime_url = (getattr(self._runtime, "runtime_url", "")
                        or os.environ.get("META_RUNTIME_URL", "")).strip()
        _db_uid      = (getattr(self._runtime, "db_uid", "")
                        or os.environ.get("META_DB_UID", "")).strip()
        _session_id  = (getattr(self._runtime, "session_id", "")
                        or os.environ.get("META_SESSION_ID", "")).strip()

        if _runtime_url and _db_uid:
            try:
                _gw = RuntimeGateway(_runtime_url)
                if _session_id:
                    _gw.session_id = _session_id
                # Always bind the target DB for this process. If the passed
                # session is stale or not registered on the server, fall back
                # to a fresh session instead of starting "connected" but empty.
                try:
                    _gw.open_by_uid(_db_uid)
                except Exception:
                    if _session_id:
                        _gw.session_id = None
                        _gw.open_by_uid(_db_uid)
                self._db = GatewayDb(_gw)
            except Exception as _e:
                import traceback as _tb; _tb.print_exc()
                self._db = None

        # --- layout ---
        root = QWidget(self)
        root_l = QHBoxLayout(root)
        root_l.setContentsMargins(0, 0, 0, 0)
        root_l.setSpacing(0)
        self.setCentralWidget(root)

        splitter = QSplitter(Qt.Orientation.Horizontal, root)
        splitter.setChildrenCollapsible(False)
        root_l.addWidget(splitter)

        # Sidebar
        self._sidebar = self._build_sidebar()
        splitter.addWidget(self._sidebar)
        splitter.setStretchFactor(0, 0)
        splitter.setSizes([260, 1020])

        # Main column (top header + tab pages)
        main_col = QWidget(splitter)
        main_col.setObjectName("ClientMain")
        main_l = QVBoxLayout(main_col)
        main_l.setContentsMargins(0, 0, 0, 0)
        main_l.setSpacing(0)

        # ── Top header bar ────────────────────────────────────────────────
        self._header_bar = self._build_header_bar()
        main_l.addWidget(self._header_bar)

        self._tab_widget = QTabWidget(main_col)
        self._tab_widget.setObjectName("ClientTabs")
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setMovable(True)
        self._tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)
        main_l.addWidget(self._tab_widget)

        splitter.addWidget(main_col)
        splitter.setStretchFactor(1, 1)

        # Light (white) workspace for list/dashboard pages; navigation remains dark.
        self._apply_light_workspace_style(main_col)

        # --- views ---
        self._views: dict[str, QWidget] = {}
        self._titles: dict[str, str] = {}
        self._form_windows: dict[str, object] = {}

        def _open_by_guid(obj_guid: str) -> None:
            # Dashboard actions must carry the stable manifest identity. Names
            # are localized/display values and are not safe lookup keys.
            guid = str(obj_guid or "").strip()
            if guid:
                self._open_meta_object(guid, mode="list")

        # Start with empty manifest — deferred init will refresh
        self._register_view("dashboard", DashboardView(
            db=self._db, manifest_rows=[], on_open=_open_by_guid))
        self._register_view("reports", ReportsView(
            db=self._db, manifest_rows=[],
            on_open=lambda guid: self._open_meta_object(guid),
        ))
        self._register_view("settings", SettingsView(
            db_path=self._db_path,
            runtime_url=getattr(self._runtime, "runtime_url", "") if self._runtime else "",
            db_uid=getattr(self._runtime, "db_uid", "") if self._runtime else "",
            on_lang_changed=self._on_lang_changed,
        ))

        # Initial view
        self._select_view("dashboard")

        self._install_actions()  # строит меню + регистрирует bind на смену языка

        # Bind _on_lang_changed to language changes globally
        # (covers both SettingsView button and any other language-change path)
        from src.ui_qt.i18n import bind as _bind
        _bind(self._on_lang_changed, self)

        # Status bar
        self._sb_status  = QLabel(t("status_ready"))
        self._sb_count   = QLabel("")
        self._sb_sel     = QLabel("")
        self._sb_dt      = QLabel("")

        _sb_lbl_css = "background: transparent; color: #1E293B; font-size: 9pt; padding: 0 8px;"
        for lbl in (self._sb_status, self._sb_count, self._sb_sel, self._sb_dt):
            lbl.setStyleSheet(_sb_lbl_css)

        self.statusBar().addWidget(self._sb_status)
        self.statusBar().addPermanentWidget(self._sb_count)
        self.statusBar().addPermanentWidget(self._sb_sel)
        self.statusBar().addPermanentWidget(self._sb_dt)
        self.statusBar().setStyleSheet("""
            QStatusBar {
                background: #F1F5F9;
                border-top: 1px solid rgba(0,0,0,0.08);
            }
            QStatusBar::item { border: none; }
            QStatusBar QLabel {
                background: transparent;
                color: #1E293B;
                font-size: 9pt;
                padding: 0 8px;
            }
        """)

        # Clock timer
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

        self._runtime_refresh_timer = QTimer(self)
        self._runtime_refresh_timer.timeout.connect(self._refresh_runtime_data)
        self._runtime_refresh_timer.start(3000)

        # Update stats on tab switch
        self._tab_widget.currentChanged.connect(self._on_tab_switched)

        # Deferred init: load manifest, build nav, deploy schema — all after window shows
        QTimer.singleShot(0, self._deferred_init)

    def closeEvent(self, event) -> None:
        """Confirm exit if there are unsaved changes."""
        dirty = [
            self._tab_widget.tabText(self._tab_widget.indexOf(w))[2:]
            for vid, w in self._views.items()
            if vid not in ("dashboard", "reports", "settings")
            and self._tab_widget.indexOf(w) >= 0
            and self._tab_widget.tabText(self._tab_widget.indexOf(w)).startswith("* ")
        ]
        dirty_windows = [
            str(window.windowTitle() or "").removeprefix("* ")
            for window in getattr(self, "_form_windows", {}).values()
            if bool(getattr(window, "is_dirty", False))
        ]
        dirty.extend(dirty_windows)
        if dirty:
            names = ", ".join(dirty[:3]) + (f" +{len(dirty)-3}" if len(dirty) > 3 else "")
            ans = QMessageBox.question(
                self, t("dlg_unsaved_title"),
                t("client_unsaved_exit").format(names=names),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        for window in list(getattr(self, "_form_windows", {}).values()):
            try:
                if bool(getattr(window, "is_dirty", False)):
                    window.discard_and_close()
                else:
                    window.close()
            except Exception:
                pass
        event.accept()

    def _deferred_init(self) -> None:
        """Runs after the event loop starts: loads data and builds nav."""
        # Try to connect if db is None (e.g., after hot-reload or env var late-set)
        if self._db is None:
            self._try_reconnect_db()

        if self._db is not None:
            # Update window title and status bar with DB name
            self.setWindowTitle(self._resolve_window_title())
            db_name = getattr(self._runtime, "db_name", "") if self._runtime else ""
            if hasattr(self, "_sb_status"):
                self._sb_status.setText(
                    t("client_status_db_loading_structure").format(db=db_name)
                    if db_name else t("client_status_loading_structure")
                )
                self._sb_status.setStyleSheet(
                    "color: #1E293B; font-size: 9pt; padding: 0 8px;")
            if hasattr(self, "_conn_dot"):
                self._conn_dot.setStyleSheet("color: #22C55E; font-size: 10pt;")
                self._conn_dot.setToolTip(
                    t("client_runtime_connected_name").format(name=db_name or "Runtime")
                )

            # Deploy schema in background
            self._deploy_schema_on_open()
            # Load manifest structure asynchronously for the client nav tree.
            # Runtime stays a long-lived service; the client only binds to it.
            self._start_manifest_bootstrap()
            if hasattr(self, "_sb_status"):
                self._sb_status.setText(
                    t("client_status_db").format(db=db_name) if db_name else t("status_ready")
                )
        else:
            # No DB — show connection error and retry in 3 seconds
            self._show_connection_error()
            QTimer.singleShot(3000, self._deferred_init)

    def _start_pre_startup_async(self) -> None:
        """Run pre-startup modules after the window is visible.

        Startup code can resolve modules and metadata over Runtime RPC.  Running
        it before ``show()`` made a slow module look like a client launch
        failure.  Keep the cancellation result, but do the work off the Qt
        thread and let the bootstrap poller wait before running the post phase.
        """
        if self._db is None or getattr(self, "_startup_pre_active", False):
            return
        self._startup_pre_active = True
        self._startup_pre_done = False
        self._startup_pre_result = True
        logger.info("startup pre phase queued after client window show")

        def _run() -> None:
            try:
                result = bool(self._run_startup_modules(phase="pre"))
            except Exception:
                logger.exception("startup pre phase failed")
                result = True
            self._startup_pre_result = result
            self._startup_pre_done = True

        threading.Thread(target=_run, name="client-startup-pre", daemon=True).start()
        QTimer.singleShot(50, self._poll_pre_startup)

    def _poll_pre_startup(self) -> None:
        if not getattr(self, "_startup_pre_active", False):
            return
        if not getattr(self, "_startup_pre_done", False):
            QTimer.singleShot(100, self._poll_pre_startup)
            return
        self._startup_pre_active = False
        if not bool(getattr(self, "_startup_pre_result", True)):
            logger.info("startup pre phase cancelled client launch")
            self.close()
            return
        if getattr(self, "_post_startup_pending", False):
            self._post_startup_pending = False
            try:
                self._run_startup_modules(phase="post")
            except Exception:
                logger.exception("startup post phase failed")

    def _start_manifest_bootstrap(self, *, force: bool = False) -> None:
        """Load manifest rows in the background and apply the UI once ready."""
        if getattr(self, "_manifest_bootstrap_active", False) and not force:
            return
        self._manifest_bootstrap_active = True
        self._manifest_bootstrap_done = False
        self._manifest_bootstrap_rows = []

        if force:
            self._manifest_rows_cache = []
            self._manifest_nav_rows_cache = []
            self._manifest_by_guid_cache = {}

        def _run() -> None:
            try:
                if hasattr(self, "_manifest_nav_rows"):
                    user_rows, subsystem_rows, report_rows = self._manifest_nav_rows()  # type: ignore[misc]
                    rows = [*user_rows, *subsystem_rows, *report_rows]
                    self._manifest_nav_rows_cache = list(rows)
                else:
                    rows = []
            except Exception:
                rows = []
            self._manifest_bootstrap_rows = list(rows)
            self._manifest_bootstrap_done = True

        threading.Thread(target=_run, daemon=True).start()
        QTimer.singleShot(0, self._poll_manifest_bootstrap)

    def _poll_manifest_bootstrap(self) -> None:
        """Apply manifest bootstrap results once the background load completes."""
        if not getattr(self, "_manifest_bootstrap_active", False):
            return
        if not getattr(self, "_manifest_bootstrap_done", False):
            QTimer.singleShot(100, self._poll_manifest_bootstrap)
            return

        self._manifest_bootstrap_active = False
        rows = list(getattr(self, "_manifest_bootstrap_rows", []) or [])
        if self._db is None:
            return
        if rows:
            # Build nav from manifest
            self._populate_nav_tree()

            # Navigation must not wait for arbitrary user startup code.  Only
            # the post-startup execution itself is ordered after pre-startup.
            if getattr(self, "_startup_pre_active", False):
                self._post_startup_pending = True
            else:
                try:
                    self._run_startup_modules(phase="post")
                except Exception:
                    logger.exception("startup module execution failed")

            # Refresh dashboard with real data
            dash = self._views.get("dashboard")
            if dash is not None and hasattr(dash, "refresh"):
                dash.refresh(rows)

            # Refresh reports view
            rpt = self._views.get("reports")
            if rpt is not None and hasattr(rpt, "reload"):
                rpt.reload(manifest_rows=rows)

            try:
                self._manifest_refresh_fingerprint = self._manifest_refresh_key()
            except Exception:
                self._manifest_refresh_fingerprint = ""

            if hasattr(self, "_sb_status"):
                db_name = getattr(self._runtime, "db_name", "") if self._runtime else ""
                self._sb_status.setText(f"БД: {db_name}" if db_name else t("status_ready"))

            # If nav still shows minimal (connection was fast but manifest empty), retry once
            if self._nav.topLevelItemCount() <= 4:
                QTimer.singleShot(2000, self._retry_nav_populate)
        else:
            if hasattr(self, "_sb_status"):
                self._sb_status.setText(t("status_ready"))

    def _retry_nav_populate(self) -> None:
        """Retry nav population if it's still minimal."""
        if self._nav.topLevelItemCount() <= 4:
            self._populate_nav_tree()

    def _try_reconnect_db(self) -> None:
        """Try to establish DB connection from env vars."""
        _runtime_url = os.environ.get("META_RUNTIME_URL", "").strip()
        _db_uid      = os.environ.get("META_DB_UID", "").strip()
        _session_id  = os.environ.get("META_SESSION_ID", "").strip()
        if not _runtime_url or not _db_uid:
            return
        try:
            from src.runtime.gateway import RuntimeGateway, GatewayDb
            _gw = RuntimeGateway(_runtime_url)
            if _session_id:
                _gw.session_id = _session_id
            else:
                _gw.open_by_uid(_db_uid)
            self._db = GatewayDb(_gw)
        except Exception:
            self._db = None

    def _show_connection_error(self) -> None:
        """Show connection error in status bar and sidebar indicator."""
        if hasattr(self, "_sb_status"):
            self._sb_status.setText("⚠ " + t("client_runtime_disconnected_hint"))
            self._sb_status.setStyleSheet("color: #DC2626; font-size: 9pt; padding: 0 8px;")
        if hasattr(self, "_conn_dot"):
            self._conn_dot.setStyleSheet("color: #EF4444; font-size: 10pt;")
            self._conn_dot.setToolTip(t("client_runtime_disconnected"))

    def _update_clock(self) -> None:
        from PySide6.QtCore import QDateTime
        now = QDateTime.currentDateTime()
        self._sb_dt.setText(
            f"📅 {now.toString('dd.MM.yyyy')}   ⏰ {now.toString('HH:mm:ss')}"
        )

    def _on_tab_switched(self, index: int) -> None:
        w = self._tab_widget.widget(index)
        self._connect_list_stats(w)
        self._refresh_list_stats(w)
        view_id = next((vid for vid, vw in self._views.items() if vw is w), "")
        if view_id:
            self._sync_nav_to_view(view_id)
        self._update_header_bar()

    def _find_form_widget(self, w) -> "FormRuntimeWidget | None":
        """Find FormRuntimeWidget in a tab widget (direct or nested)."""
        if w is None:
            return None
        from src.client.forms.form_runtime import FormRuntimeWidget
        if isinstance(w, FormRuntimeWidget):
            return w
        if hasattr(w, "_form_widget") and isinstance(w._form_widget, FormRuntimeWidget):
            return w._form_widget
        for child in w.findChildren(FormRuntimeWidget):
            return child
        return None

    def _connect_list_stats(self, w) -> None:
        """Connect list_stats_changed + data_changed signals from FormRuntimeWidget."""
        form = self._find_form_widget(w)
        if form is None:
            return
        try:
            form.list_stats_changed.connect(self._on_list_stats_changed)
        except Exception:
            pass
        # Dirty-state: mark tab with * on unsaved changes
        try:
            view_id = next((vid for vid, vw in self._views.items() if vw is w), "")
            if view_id.startswith("obj:"):
                form.data_changed.connect(lambda: self._mark_tab_dirty(w))
        except Exception:
            pass

    def _mark_tab_dirty(self, w) -> None:
        """Add * prefix to tab title to indicate unsaved changes."""
        idx = self._tab_widget.indexOf(w)
        if idx < 0:
            return
        title = self._tab_widget.tabText(idx)
        if not title.startswith("* "):
            self._tab_widget.setTabText(idx, f"* {title}")

    def _refresh_list_stats(self, w) -> None:
        from src.client.forms.form_runtime import FormRuntimeWidget
        form = None
        if isinstance(w, FormRuntimeWidget):
            form = w
        elif w is not None:
            for child in w.findChildren(FormRuntimeWidget):
                form = child
                break
        if form is not None and hasattr(form, "_list_table") and form._list_table is not None:
            m = form._list_table.model()
            total = m.rowCount() if m else 0
            sel = len(form._list_table.selectionModel().selectedRows()) if form._list_table.selectionModel() else 0
            self._on_list_stats_changed(total, sel)
        else:
            self._sb_count.setText("")
            self._sb_sel.setText("")

    def _on_list_stats_changed(self, total: int, selected: int) -> None:
        # total here = visible (filtered) rows; get source total from active list
        w = self._tab_widget.currentWidget()
        form = self._find_form_widget(w)
        source_total = total
        if form is not None and hasattr(form, "_list_table") and form._list_table is not None:
            proxy = getattr(form._list_table, "_filter_proxy", None)
            if proxy is not None:
                src = proxy.sourceModel()
                source_total = src.rowCount() if src else total

        if source_total != total:
            count_text = t("client_status_filtered_count").format(
                visible=total,
                total=source_total,
            )
        else:
            count_text = str(total)
        self._sb_count.setText(t("client_status_records").format(count=count_text))
        self._sb_sel.setText(
            t("client_status_selected").format(count=selected) if selected else ""
        )
