from __future__ import annotations

import time

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QLineEdit, QMdiSubWindow, QWidget

from src.ui_qt.i18n import t
from src.platform.logging_setup import get_logger


_log = get_logger("configurator.props")


class ConfiguratorPropsMixin:
    def _dispatch_focus(self, method: str) -> None:
        w = QApplication.focusWidget()
        if w is None:
            return
        fn = getattr(w, method, None)
        if callable(fn):
            try:
                fn()
                return
            except Exception:
                pass

    def _active_editor_widget(self) -> QWidget | None:
        sub = self.mdi.activeSubWindow()
        if sub is None:
            return None
        return sub.widget()

    def _update_save_enabled(self) -> None:
        try:
            active = self._active_editor_widget()
            dirty = False
            if active is not None:
                if hasattr(active, "is_dirty") and callable(getattr(active, "is_dirty")):
                    dirty = bool(active.is_dirty())
                elif hasattr(active, "_state") and hasattr(active._state, "is_dirty"):
                    dirty = bool(getattr(active._state, "is_dirty", False))
            self.act_save.setEnabled(bool(self._is_dirty or dirty or True))
        except Exception:
            self.act_save.setEnabled(True)

    def _show_manifest_props(self) -> None:
        self._props_stack.setCurrentWidget(self.props_panel)
        self._schedule_normalize_props_dock_width()
        try:
            if self._vm is not None:
                schema_state = getattr(self._vm, "_schema_editor_state", None)
                schema_context = getattr(self._vm, "_schema_editor_context", {})
                if schema_context and getattr(schema_state, "current", None):
                    st = schema_state
                elif hasattr(self._vm, "_editor"):
                    st = self._vm._editor.state
                else:
                    st = None
                if st and st.guid:
                    self.props_panel.update_editor(st)
        except Exception:
            pass

    def _on_subwindow_activated(self, sub: QMdiSubWindow | None) -> None:
        try:
            if sub is None:
                self._show_manifest_props()
                return

            w = sub.widget()
            if w is None:
                self._show_manifest_props()
                return

            props_getter = getattr(w, "properties_widget", None)
            if not callable(props_getter):
                self._show_manifest_props()
                return

            d_id = id(w)
            page = self._form_props_pages.get(d_id)
            if page is None:
                page = props_getter()
                if page is None:
                    self._show_manifest_props()
                    return
                self._props_stack.addWidget(page)
                self._form_props_pages[d_id] = page
                try:
                    w.destroyed.connect(lambda _=None, did=d_id: self._on_form_designer_destroyed(did))
                except Exception:
                    pass

            self._props_stack.setCurrentWidget(page)
            self._schedule_normalize_props_dock_width()
        except Exception:
            self._show_manifest_props()

        try:
            self._route_properties_by_focus(QApplication.focusWidget())
        except Exception:
            pass

    def _is_descendant(self, child: QWidget | None, root: QWidget | None) -> bool:
        if child is None or root is None:
            return False
        if child is root:
            return True
        try:
            return root.isAncestorOf(child)
        except Exception:
            w = child.parentWidget()
            while w is not None:
                if w is root:
                    return True
                w = w.parentWidget()
            return False

    def _route_properties_by_focus(self, focus_widget: QWidget | None) -> None:
        if focus_widget is None:
            return

        if self._is_descendant(focus_widget, self.dock_tree.widget()) or self._is_descendant(
            focus_widget, self.props_panel
        ):
            if self._props_stack.currentWidget() is not self.props_panel:
                self._show_manifest_props()
            return

        sub = self.mdi.activeSubWindow()
        if sub is None:
            return
        editor = sub.widget()
        if editor is None:
            return

        props_getter = getattr(editor, "properties_widget", None)
        if not callable(props_getter):
            if self._is_descendant(focus_widget, editor) and self._props_stack.currentWidget() is not self.props_panel:
                self._show_manifest_props()
            return

        did = id(editor)
        page = self._form_props_pages.get(did)
        if page is None:
            page = props_getter()
            if page is None:
                if self._is_descendant(focus_widget, editor) and self._props_stack.currentWidget() is not self.props_panel:
                    self._show_manifest_props()
                return
            self._props_stack.addWidget(page)
            self._form_props_pages[did] = page
            try:
                editor.destroyed.connect(lambda _=None, _did=did: self._on_form_designer_destroyed(_did))
            except Exception:
                pass

        if self._is_descendant(focus_widget, editor) or self._is_descendant(focus_widget, page):
            if self._props_stack.currentWidget() is not page:
                self._props_stack.setCurrentWidget(page)
                self._schedule_normalize_props_dock_width()

    def _on_focus_changed(self, old: QWidget | None, now: QWidget | None) -> None:
        try:
            self._route_properties_by_focus(now)
        except Exception:
            pass

    def _on_form_designer_destroyed(self, designer_id: int) -> None:
        started_at = time.perf_counter()
        page = self._form_props_pages.pop(int(designer_id), None)
        if page is None:
            return
        try:
            _log.info(
                "props.page_destroy.start editor_id=%s page=%s",
                designer_id,
                type(page).__name__,
            )
        except Exception:
            pass
        try:
            if self._props_stack.currentWidget() is page:
                self._props_stack.setCurrentWidget(self.props_panel)
                self._schedule_normalize_props_dock_width()
        except Exception:
            pass
        try:
            self._props_stack.removeWidget(page)
        except Exception:
            pass
        try:
            page.deleteLater()
        except Exception:
            pass
        try:
            _log.info(
                "props.page_destroy.done editor_id=%s took=%.3fs",
                designer_id,
                time.perf_counter() - started_at,
            )
        except Exception:
            pass

    def _on_editor_state_changed(self, state) -> None:
        is_dirty = bool(getattr(state, "is_dirty", False))
        if is_dirty == self._is_dirty:
            return
        self._is_dirty = is_dirty
        title = self._base_title
        if self._is_dirty:
            title = f"* {title}"
            self.statusBar().showMessage(t("status_modified"))
        else:
            self.statusBar().showMessage("")
        self.setWindowTitle(title)
        try:
            self.act_save.setEnabled(self._is_dirty)
        except Exception:
            pass

    def set_properties_rows(self, rows: list[tuple[str, str]]) -> None:
        self.props_panel.set_properties_rows(rows)

    def set_properties_visible(self, visible: bool) -> None:
        self.dock_props.setVisible(bool(visible))
        self._props_visible = bool(visible)
        if self.act_view_properties is not None:
            self.act_view_properties.blockSignals(True)
            self.act_view_properties.setChecked(self._props_visible)
            self.act_view_properties.blockSignals(False)
        a = getattr(self, "act_toggle_props", None)
        if a is not None:
            try:
                a.blockSignals(True)
                a.setChecked(self._props_visible)
                a.blockSignals(False)
            except Exception:
                pass
