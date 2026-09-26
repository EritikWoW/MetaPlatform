from __future__ import annotations

from copy import deepcopy
import time
from typing import Any, Dict

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QTableWidgetSelectionRange
from src.platform.logging_setup import get_logger


_log = get_logger("ui.layout_preview")


class LayoutPreviewStateMixin:
    def _mark_dirty(self) -> None:
        self._dirty = True

    def _commit_pending_ui_changes(self) -> None:
        props = getattr(self, "_sheet_props", None)
        commit_props = getattr(props, "commit_pending_changes", None)
        if callable(commit_props):
            try:
                commit_props()
            except Exception:
                pass
        tool_text = getattr(self, "_tool_text", None)
        selected = self._selected_cell_info() or {}
        if tool_text is not None and selected:
            current_text = str(selected.get("text") or "")
            editor_text = str(tool_text.text() or "")
            if editor_text != current_text:
                self._on_cell_property_changed("text", editor_text)


    def prepare_for_close(self) -> None:
        if getattr(self, "_close_prepared", False):
            return
        started_at = time.perf_counter()
        try:
            _log.info(
                "layout_preview.prepare_close.start guid=%s title=%r",
                self._obj_guid,
                getattr(self, "_title", ""),
            )
        except Exception:
            pass
        self._commit_pending_ui_changes()
        force_flush = bool(self._dirty or self._save_timer.isActive())
        self._closing = True
        self._close_prepared = True
        self._flush_pending_save(force=force_flush)
        self._teardown_table_before_close()
        try:
            _log.info(
                "layout_preview.prepare_close.done guid=%s took=%.3fs",
                self._obj_guid,
                time.perf_counter() - started_at,
            )
        except Exception:
            pass


    def _teardown_table_before_close(self) -> None:
        table = self._table
        if table is None:
            return
        started_at = time.perf_counter()
        try:
            table.blockSignals(True)
            table.setUpdatesEnabled(False)
            try:
                table.currentCellChanged.disconnect(self._on_current_cell_changed)
            except Exception:
                pass
            try:
                table.itemSelectionChanged.disconnect(self._on_selection_changed)
            except Exception:
                pass
            try:
                table.customContextMenuRequested.disconnect(self._show_cell_context_menu)
            except Exception:
                pass
            try:
                table.setItemDelegate(None)
            except Exception:
                pass
            try:
                table.clearSpans()
            except Exception:
                pass
            try:
                table.clearSelection()
            except Exception:
                pass
            try:
                table.clearContents()
            except Exception:
                pass
            try:
                table.setRowCount(0)
                table.setColumnCount(0)
            except Exception:
                pass
        finally:
            self._table = None
            try:
                table.deleteLater()
            except Exception:
                pass
            try:
                _log.info(
                    "layout_preview.teardown_table guid=%s took=%.3fs",
                    self._obj_guid,
                    time.perf_counter() - started_at,
                )
            except Exception:
                pass


    def _schedule_persist(self) -> None:
        if self._vm is None or not self._obj_guid:
            return
        if getattr(self, "_closing", False):
            _log.info("layout_preview.schedule_skip guid=%s reason=closing", self._obj_guid)
            return
        self._mark_dirty()
        self._save_timer.start()


    def _named_areas(self) -> list[Dict[str, Any]]:
        areas = self._layout_model.get("named_areas")
        if isinstance(areas, list):
            return areas
        areas = []
        self._layout_model["named_areas"] = areas
        return areas


    def _area_editor_text(self) -> str:
        combo = self._tool_area
        if combo is None:
            return ""
        line_edit = combo.lineEdit()
        if line_edit is not None:
            return str(line_edit.text() or "").strip()
        return str(combo.currentText() or "").strip()


    def _set_area_editor_text(self, text: str) -> None:
        combo = self._tool_area
        if combo is None:
            return
        line_edit = combo.lineEdit()
        if line_edit is not None:
            line_edit.setText(str(text or ""))
            return
        combo.setEditText(str(text or ""))


    def _matched_area_name(self, rect: tuple[int, int, int, int] | None) -> str:
        if rect is None:
            return ""
        top, left, bottom, right = rect
        for area in self._named_areas():
            if not isinstance(area, dict):
                continue
            if (
                self._safe_int(area.get("begin_row"), -1) == top
                and self._safe_int(area.get("begin_column"), -1) == left
                and self._safe_int(area.get("end_row"), -1) == bottom
                and self._safe_int(area.get("end_column"), -1) == right
            ):
                return str(area.get("name") or "").strip()
        return ""


    def _refresh_area_tools(self, preferred_text: str = "") -> None:
        combo = self._tool_area
        if combo is None:
            return
        current_text = self._area_editor_text()
        matched_name = self._matched_area_name(self._selected_rect())
        area_names = []
        seen: set[str] = set()
        for area in self._named_areas():
            if not isinstance(area, dict):
                continue
            name = str(area.get("name") or "").strip()
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            area_names.append(name)
        combo.blockSignals(True)
        try:
            combo.clear()
            for name in sorted(area_names, key=str.casefold):
                combo.addItem(name, name)
            self._set_area_editor_text(str(preferred_text or matched_name or current_text))
        finally:
            combo.blockSignals(False)


    def _assign_selected_area(self) -> None:
        rect = self._selected_rect()
        combo = self._tool_area
        if rect is None or combo is None:
            return
        name = self._area_editor_text()
        if not name:
            return
        top, left, bottom, right = rect
        areas = self._named_areas()
        replaced = False
        for idx, area in enumerate(list(areas)):
            if not isinstance(area, dict):
                continue
            if str(area.get("name") or "").strip().casefold() != name.casefold():
                continue
            areas[idx] = {
                "name": name,
                "type": str(area.get("type") or "area"),
                "begin_row": top,
                "end_row": bottom,
                "begin_column": left,
                "end_column": right,
            }
            replaced = True
            break
        if not replaced:
            areas.append(
                {
                    "name": name,
                    "type": "area",
                    "begin_row": top,
                    "end_row": bottom,
                    "begin_column": left,
                    "end_column": right,
                }
            )
        self._refresh_area_tools(name)
        self._schedule_persist()
        self._sync_selected_cell_props()


    def _goto_selected_area(self) -> None:
        combo = self._tool_area
        table = self._table
        if combo is None or table is None:
            return
        name = self._area_editor_text()
        if not name:
            return
        for area in self._named_areas():
            if not isinstance(area, dict):
                continue
            if str(area.get("name") or "").strip().casefold() != name.casefold():
                continue
            top = self._safe_int(area.get("begin_row"), -1)
            left = self._safe_int(area.get("begin_column"), -1)
            bottom = self._safe_int(area.get("end_row"), -1)
            right = self._safe_int(area.get("end_column"), -1)
            if top < 0 or left < 0 or bottom < top or right < left:
                return
            table.clearSelection()
            table.setRangeSelected(QTableWidgetSelectionRange(top, left, bottom, right), True)
            sel_model = table.selectionModel()
            if sel_model is not None:
                idx = table.model().index(top, left)
                if idx.isValid():
                    sel_model.setCurrentIndex(
                        idx,
                        QItemSelectionModel.SelectionFlag.Current
                        | QItemSelectionModel.SelectionFlag.NoUpdate,
                    )
            item = table.item(top, left)
            if item is not None:
                table.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
            self._sync_selected_cell_props()
            return


    def _remove_selected_area(self) -> None:
        combo = self._tool_area
        if combo is None:
            return
        name = self._area_editor_text()
        rect = self._selected_rect()
        areas = self._named_areas()
        kept: list[Dict[str, Any]] = []
        removed = False
        for area in areas:
            if not isinstance(area, dict):
                continue
            area_name = str(area.get("name") or "").strip()
            matches_name = bool(name) and area_name.casefold() == name.casefold()
            matches_rect = False
            if rect is not None:
                top, left, bottom, right = rect
                matches_rect = (
                    self._safe_int(area.get("begin_row"), -1) == top
                    and self._safe_int(area.get("begin_column"), -1) == left
                    and self._safe_int(area.get("end_row"), -1) == bottom
                    and self._safe_int(area.get("end_column"), -1) == right
                )
            if matches_name or matches_rect:
                removed = True
                continue
            kept.append(dict(area))
        if not removed:
            return
        self._layout_model["named_areas"] = kept
        self._refresh_area_tools()
        self._schedule_persist()
        self._sync_selected_cell_props()


    def _flush_pending_save(self, *, force: bool = False) -> None:
        started_at = time.perf_counter()
        had_timer = self._save_timer.isActive()
        if had_timer:
            self._save_timer.stop()
        if self._vm is None or not self._obj_guid:
            return
        if not force and not self._dirty and not had_timer:
            _log.info(
                "layout_preview.flush_skip guid=%s reason=clean took=%.3fs",
                self._obj_guid,
                time.perf_counter() - started_at,
            )
            return
        payload = dict(self._payload)
        payload["layout_model"] = deepcopy(self._layout_model)
        kind = str(self._layout_model.get("kind") or self._payload.get("layout_kind") or "").strip()
        if kind:
            payload["layout_kind"] = kind
        signature = self._layout_save_signature()
        if signature == getattr(self, "_saved_layout_signature", ""):
            self._payload = payload
            self._dirty = False
            _log.info(
                "layout_preview.flush_skip guid=%s reason=unchanged took=%.3fs",
                self._obj_guid,
                time.perf_counter() - started_at,
            )
            return
        save_asset_fn = getattr(self._vm, "save_externalized_payload_asset", None)
        layout_ref = str(payload.get("layout_model_ref") or "").strip()
        if layout_ref and callable(save_asset_fn):
            ok = bool(
                save_asset_fn(
                    self._obj_guid,
                    payload,
                    key="layout_model",
                    reload=False,
                )
            )
            _log.info(
                "layout_preview.flush_asset_save guid=%s kind=%s ref=%s ok=%s took=%.3fs",
                self._obj_guid,
                kind or "",
                layout_ref,
                ok,
                time.perf_counter() - started_at,
            )
            if ok:
                self._payload = payload
                self._dirty = False
                self._saved_layout_signature = signature
            return
        save_fn = getattr(self._vm, "save_object_payload", None)
        if callable(save_fn):
            ok = bool(save_fn(self._obj_guid, payload, reload=False))
            _log.info(
                "layout_preview.flush_save guid=%s kind=%s ok=%s took=%.3fs",
                self._obj_guid,
                kind or "",
                ok,
                time.perf_counter() - started_at,
            )
            if ok:
                self._payload = payload
                self._dirty = False
                self._saved_layout_signature = signature
            return
        set_fn = getattr(self._vm, "set_object_payload", None)
        if callable(set_fn):
            try:
                set_fn(self._obj_guid, payload)
                self._payload = payload
                self._dirty = False
                self._saved_layout_signature = signature
                _log.info(
                    "layout_preview.flush_set guid=%s kind=%s took=%.3fs",
                    self._obj_guid,
                    kind or "",
                    time.perf_counter() - started_at,
                )
            except Exception:
                return


    def closeEvent(self, event) -> None:  # type: ignore[override]
        started_at = time.perf_counter()
        try:
            _log.info(
                "layout_preview.close.start guid=%s title=%r",
                self._obj_guid,
                getattr(self, "_title", ""),
            )
        except Exception:
            pass
        self.prepare_for_close()
        try:
            _log.info(
                "layout_preview.close.after_save guid=%s took=%.3fs",
                self._obj_guid,
                time.perf_counter() - started_at,
            )
        except Exception:
            pass
        super().closeEvent(event)
        try:
            _log.info(
                "layout_preview.close.done guid=%s total=%.3fs",
                self._obj_guid,
                time.perf_counter() - started_at,
            )
        except Exception:
            pass
