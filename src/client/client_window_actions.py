from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QInputDialog, QMessageBox

from src.ui_qt.i18n import t, bind


class ClientWindowActionsMixin:

    def _install_actions(self) -> None:
        """Install main window menu bar — all labels from i18n."""
        self._build_menu_bar()
        # Rebuild on language change
        bind(self._rebuild_menu_bar, self)

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()
        mb.clear()

        # ── Файл / File ───────────────────────────────────────────────
        m_file = mb.addMenu(t("client_menu_file"))

        act_open_form = QAction(t("client_act_open_form"), self)
        act_open_form.triggered.connect(self._open_form_by_guid_dialog)
        m_file.addAction(act_open_form)
        m_file.addSeparator()

        act_exit = QAction(t("act_close"), self)
        act_exit.setShortcut(QKeySequence.StandardKey.Quit)
        act_exit.triggered.connect(self.close)
        m_file.addAction(act_exit)

        # ── Правка / Edit ─────────────────────────────────────────────
        m_edit = mb.addMenu(t("menu_edit"))

        act_find = QAction(t("act_find_meta") or "Пошук", self)
        act_find.setShortcut(QKeySequence("Ctrl+F"))
        act_find.triggered.connect(self._focus_search)
        m_edit.addAction(act_find)

        act_refresh = QAction(t("act_refresh") or "Оновити", self)
        act_refresh.setShortcut(QKeySequence("F5"))
        act_refresh.triggered.connect(self._refresh_current_view)
        m_edit.addAction(act_refresh)

        act_load_structure = QAction(t("client_act_load_structure"), self)
        act_load_structure.setShortcut(QKeySequence("Ctrl+Alt+R"))
        act_load_structure.triggered.connect(self._load_manifest_structure)
        m_edit.addAction(act_load_structure)

        act_new = QAction(t("client_btn_create"), self)
        act_new.setShortcut(QKeySequence("Ctrl+N"))
        act_new.triggered.connect(self._on_header_create)
        m_edit.addAction(act_new)

        # ── Вид / View ────────────────────────────────────────────────
        m_view = mb.addMenu(t("menu_view"))

        act_full = QAction(t("win_tile"), self)
        act_full.setShortcut(QKeySequence("F11"))
        m_view.addAction(act_full)

        act_structure = QAction(t("client_act_form_structure"), self)
        act_structure.setShortcut(QKeySequence("Ctrl+Alt+I"))
        act_structure.triggered.connect(self._show_current_structure_inspector)
        m_view.addAction(act_structure)

        act_object_structure = QAction(t("client_act_object_structure"), self)
        act_object_structure.setShortcut(QKeySequence("Ctrl+Alt+Shift+I"))
        act_object_structure.triggered.connect(self._open_structure_by_guid_dialog)
        m_view.addAction(act_object_structure)

        # ── Сервис / Service ──────────────────────────────────────────
        m_srv = mb.addMenu(t("menu_admin"))
        m_srv.addAction(QAction(t("admin_infobase_params") + "…", self))
        act_admin = QAction(t("admin_users") + "…", self)
        m_srv.addAction(act_admin)

        # ── Окна / Windows ────────────────────────────────────────────
        m_win = mb.addMenu(t("menu_windows"))

        act_close_tab = QAction(t("btn_close_window"), self)
        act_close_tab.setShortcut(QKeySequence("Ctrl+W"))
        act_close_tab.triggered.connect(self._close_current_tab)
        m_win.addAction(act_close_tab)

        # ── Справка / Help ────────────────────────────────────────────
        m_help = mb.addMenu(t("menu_help"))
        m_help.addAction(QAction(t("about_title") + "…", self))

    def _rebuild_menu_bar(self) -> None:
        """Called on language change — rebuild the entire menu bar."""
        self._build_menu_bar()

    # ── Actions ───────────────────────────────────────────────────────

    def _focus_search(self) -> None:
        """Ctrl+F — focus the header search bar."""
        if hasattr(self, "_hdr_search"):
            self._hdr_search.setFocus()
            self._hdr_search.selectAll()

    def _refresh_current_view(self) -> None:
        """F5 — refresh the active view."""
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
            form._emit_command("refresh")

    def _close_current_tab(self) -> None:
        idx = self._tab_widget.currentIndex()
        if idx >= 0:
            self._on_tab_close_requested(idx)

    def _show_current_structure_inspector(self) -> None:
        """Open the structure inspector tab for the active form, if any."""
        from src.client.forms.form_runtime import FormRuntimeWidget
        from PySide6.QtWidgets import QTabWidget

        w = self._tab_widget.currentWidget()
        if w is None:
            return
        form = None
        if isinstance(w, FormRuntimeWidget):
            form = w
        elif w is not None:
            for child in w.findChildren(FormRuntimeWidget):
                form = child
                break
        if form is None:
            return
        tabs = form.parentWidget().findChild(QTabWidget, "ClientFormTabs") if form.parentWidget() else None
        if tabs is None:
            return
        if tabs.count() > 1:
            tabs.setCurrentIndex(1)

    def _open_structure_by_guid_dialog(self) -> None:
        if self._db is None:
            QMessageBox.warning(self, t("dlg_error_title"), t("client_err_db_not_open"))
            return

        guid, ok = QInputDialog.getText(
            self, t("client_act_object_structure"), t("client_prompt_object_guid")
        )
        if not ok:
            return
        guid = str(guid or "").strip()
        if not guid:
            return

        row = self._manifest_row_by_guid(guid)
        if not row:
            QMessageBox.information(self, t("dlg_error_title"), t("client_err_form_not_found").format(guid=guid))
            return

        self._open_structure_for_guid(guid)

    def _open_form_by_guid_dialog(self) -> None:
        if self._db is None:
            QMessageBox.warning(self, t("dlg_error_title"), t("client_err_db_not_open"))
            return

        guid, ok = QInputDialog.getText(
            self, t("client_act_open_form"), t("client_prompt_form_guid")
        )
        if not ok:
            return
        guid = str(guid or "").strip()
        if not guid:
            return

        try:
            row = self._manifest_row_by_guid(guid)
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), str(e))
            return

        if not row:
            QMessageBox.information(
                self, t("dlg_error_title"),
                t("client_err_form_not_found").format(guid=guid),
            )
            return

        if str(row.get("type") or "").strip().lower() not in ("form", "common_form"):
            QMessageBox.information(self, t("dlg_error_title"), t("client_err_not_a_form"))
            return

        title = str(row.get("title") or row.get("name") or guid)

        if hasattr(self, "_can_access_row") and not self._can_access_row(row, action="open"):
            if hasattr(self, "_deny_access"):
                self._deny_access(t("dlg_error_title"), title)
            return

        payload = self._manifest_payload_for_row(row)
        model = self._payload_form_model(payload)
        if not isinstance(model, dict) or not model:
            QMessageBox.information(self, t("dlg_error_title"), t("client_err_form_no_model"))
            return

        view_id = f"form:{guid}"
        if view_id in self._views:
            self._select_view(view_id)
            return
        if self._activate_form_window(view_id):
            return
        self._present_form(
            view_id=view_id,
            widget=self._build_runtime_form_view(
                title=title, guid=guid, model=model, ctx=None,
            ),
            title=title,
            model=model,
            owner_type=str(row.get("type") or ""),
        )
