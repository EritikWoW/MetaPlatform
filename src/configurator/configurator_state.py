from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import QMessageBox

from src.ui_qt.i18n import t
from src.configurator.ui.widgets import NodeInfo


class ConfiguratorStateMixin:
    def _resize_props_dock_to(self, target: int) -> None:
        try:
            self.resizeDocks([self.dock_props], [int(target)], Qt.Orientation.Horizontal)
        except Exception:
            pass

    def _reset_props_dock_constraints(self) -> None:
        try:
            self.dock_props.setMinimumWidth(0)
            self._props_stack.setMinimumWidth(0)
            self.dock_props.setMaximumWidth(16777215)
            self._props_stack.setMaximumWidth(16777215)
        except Exception:
            pass

    def _props_dock_compact_width(self, preferred: int | None = None) -> int:
        preferred_width = int(preferred or 0)
        if preferred_width <= 0:
            preferred_width = self._PROPS_DOCK_MIN_WIDTH
        window_cap = int(max(self._PROPS_DOCK_MIN_WIDTH, self.width() * 0.30))
        cap = min(self._PROPS_DOCK_MAX_COMPACT_WIDTH, window_cap)
        return max(self._PROPS_DOCK_MIN_WIDTH, min(cap, preferred_width))

    def _apply_props_dock_constraints(self, target: int | None = None) -> None:
        if not self.dock_props.isVisible() or self.dock_props.isFloating():
            self._reset_props_dock_constraints()
            return
        try:
            self.dock_props.setMinimumWidth(self._PROPS_DOCK_MIN_WIDTH)
            self._props_stack.setMinimumWidth(self._PROPS_DOCK_MIN_WIDTH)
            self.dock_props.setMaximumWidth(16777215)
            self._props_stack.setMaximumWidth(16777215)
        except Exception:
            pass

    def begin_tree_rebuild(self) -> None:
        try:
            self.tree.setUpdatesEnabled(False)
        except Exception:
            pass
        try:
            self.tree.blockSignals(True)
        except Exception:
            pass
        try:
            self.tree.setAnimated(False)
        except Exception:
            pass

    def end_tree_rebuild(self) -> None:
        try:
            self.tree.blockSignals(False)
        except Exception:
            pass
        try:
            self.tree.setUpdatesEnabled(True)
            self.tree.viewport().update()
        except Exception:
            pass
        if hasattr(self, "refresh_subsystem_filter_combo"):
            try:
                self.refresh_subsystem_filter_combo()
            except Exception:
                pass
        self._build_menu()
        self.set_properties_visible(True)
        if not self._startup_ui_restored:
            self._startup_ui_restored = True
            self._restore_ui_state()
            if self.isVisible():
                QTimer.singleShot(0, self._restore_last_windows_optional)
            else:
                self._restore_last_windows_optional()

    def _restore_ui_state(self) -> None:
        try:
            geo = self._settings.value("geometry")
            if geo is not None:
                self.restoreGeometry(geo)
            st = self._settings.value("window_state")
            if st is not None:
                self.restoreState(st)
            props_vis = self._settings.value("dock_props_visible", None)
            if props_vis is None:
                props_visible = True
            elif isinstance(props_vis, str):
                props_visible = props_vis.strip().casefold() not in {"0", "false", "no", "off"}
            else:
                props_visible = bool(props_vis)
            self.set_properties_visible(props_visible)
            self._props_dock_default_width_applied = False
            self._schedule_normalize_props_dock_width(force=True)
        except Exception:
            pass

    def _schedule_normalize_props_dock_width(self, force: bool = False) -> None:
        try:
            QTimer.singleShot(0, lambda: self._normalize_props_dock_width(force=force))
            QTimer.singleShot(60, lambda: self._normalize_props_dock_width(force=force))
            QTimer.singleShot(180, lambda: self._normalize_props_dock_width(force=force))
            QTimer.singleShot(420, lambda: self._normalize_props_dock_width(force=force))
            QTimer.singleShot(900, lambda: self._normalize_props_dock_width(force=force))
        except Exception:
            pass

    def _normalize_props_dock_width(self, force: bool = False) -> None:
        if not self.dock_props.isVisible() or self.dock_props.isFloating():
            self._reset_props_dock_constraints()
            return
        page = self._props_stack.currentWidget()
        if page is None:
            return
        try:
            base_hint = page.minimumSizeHint().width()
        except Exception:
            base_hint = 0
        if base_hint <= 0:
            try:
                base_hint = page.sizeHint().width()
            except Exception:
                base_hint = 0
        if base_hint <= 0:
            return
        target = max(
            self._PROPS_DOCK_MIN_WIDTH,
            min(self._PROPS_DOCK_MAX_COMPACT_WIDTH, int(base_hint) + self._PROPS_DOCK_CLAMP_MARGIN),
        )
        self._apply_props_dock_constraints(target)
        current = max(self.dock_props.width(), self._props_stack.width())
        oversized = current > max(
            int(self.width() * 0.44),
            target + 96,
            int(target * 1.8),
        )
        if force or not self._props_dock_default_width_applied or current <= 0 or oversized:
            self._resize_props_dock_to(target)
        self._props_dock_default_width_applied = True

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._schedule_normalize_props_dock_width()

    def _save_ui_state(self) -> None:
        try:
            self._settings.setValue("geometry", self.saveGeometry())
            self._settings.setValue("window_state", self.saveState())
            self._settings.setValue("dock_props_visible", bool(self.dock_props.isVisible()))
        except Exception:
            pass

    def changeEvent(self, event) -> None:
        try:
            if event is not None and event.type() in (
                QEvent.Type.PaletteChange,
                QEvent.Type.ApplicationPaletteChange,
            ):
                self._tb_refresh_icons()
        except Exception:
            pass
        super().changeEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._import_thread is not None and self._import_thread.isRunning():
            self.show_warning(t("dlg_error_title"), t("dlg_onec_import_close_blocked"))
            event.ignore()
            return
        for sub in list(getattr(self, "_open_windows", {}).values()):
            try:
                widget = sub.widget()
                confirm = getattr(widget, "confirm_close", None)
                if callable(confirm) and not bool(confirm()):
                    event.ignore()
                    return
            except Exception:
                event.ignore()
                return
        if self._is_dirty:
            res = QMessageBox.question(
                self,
                t("dlg_unsaved_title"),
                t("dlg_unsaved_text"),
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if res == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if res == QMessageBox.StandardButton.Save and self._vm is not None:
                try:
                    self._vm.on_save()
                except Exception:
                    event.ignore()
                    return
                if getattr(getattr(self._vm, "_editor", None), "state", None) is not None:
                    try:
                        if bool(getattr(self._vm._editor.state, "is_dirty", False)):
                            event.ignore()
                            return
                    except Exception:
                        event.ignore()
                        return
        try:
            self._stop_debug_client(force=True, notify=False)
        except Exception:
            pass
        control_server = getattr(self, "_control_api_server", None)
        if control_server is not None:
            try:
                control_server.shutdown()
            except Exception:
                pass
            try:
                control_server.server_close()
            except Exception:
                pass
        self._save_ui_state()
        try:
            self._settings.setValue("last_open_windows", list(self._open_windows.keys()))
        except Exception:
            pass
        try:
            self._storage_hb_timer.stop()
        except Exception:
            pass
        try:
            self._config_storage.close()
        except Exception:
            pass
        try:
            if self._vm is not None:
                self._vm.close_db()
        except Exception:
            pass
        super().closeEvent(event)

    def _safe_storage_heartbeat(self) -> None:
        try:
            if self._config_storage.connection() is None:
                return
            self._config_storage.heartbeat(user_id="SYSTEM")
        except Exception:
            return

    def _restore_last_windows_optional(self) -> None:
        try:
            keys = self._settings.value("last_open_windows", [])
            if not keys:
                return

            pending: list[str] = []
            for k in keys[:20]:
                guid = str(k or "").strip()
                if not guid:
                    continue

                meta = self._vm.get_meta_by_guid(guid) if self._vm else None
                if not isinstance(meta, dict):
                    pending.append(guid)
                    continue

                title = str(meta.get("title") or meta.get("name") or guid)
                obj_type = str(meta.get("type") or "").strip() or "structure"
                info = NodeInfo(kind="object", name=title, guid=guid, obj_type=obj_type)
                self.open_object_tab(info)

            if pending and self._restore_windows_retries_left > 0:
                self._restore_windows_retries_left -= 1
                QTimer.singleShot(250, self._restore_last_windows_optional)
        except Exception:
            return
