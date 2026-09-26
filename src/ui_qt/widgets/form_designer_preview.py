from __future__ import annotations

import json
import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QSizePolicy, QTabWidget, QWidget

from src.client.forms.form_runtime_widget import FormRuntimeWidget, ObjContext
from src.ui_qt.i18n import t
from src.ui_qt.widgets.form_designer_support import _DesignerRuntimeSurface


class FormDesignerPreviewMixin:
    @staticmethod
    def _capture_runtime_tab_state(root: QWidget | None) -> dict[str, int]:
        state: dict[str, int] = {}
        if root is None:
            return state
        for tabs in root.findChildren(QTabWidget):
            current: QWidget | None = tabs
            node_id = ""
            depth = 0
            while current is not None and depth < 12:
                node_id = str(current.property("form_node_id") or "").strip()
                if node_id:
                    break
                parent = current.parent()
                current = parent if isinstance(parent, QWidget) else None
                depth += 1
            if node_id:
                state[node_id] = int(tabs.currentIndex())
        return state

    @staticmethod
    def _restore_runtime_tab_state(root: QWidget | None, state: dict[str, int]) -> None:
        if root is None or not state:
            return
        for tabs in root.findChildren(QTabWidget):
            current: QWidget | None = tabs
            node_id = ""
            depth = 0
            while current is not None and depth < 12:
                node_id = str(current.property("form_node_id") or "").strip()
                if node_id:
                    break
                parent = current.parent()
                current = parent if isinstance(parent, QWidget) else None
                depth += 1
            if node_id not in state or tabs.count() <= 0:
                continue
            tabs.setCurrentIndex(max(0, min(int(state[node_id]), tabs.count() - 1)))

    def _schedule_preview_refresh(self, delay_ms: int = 0) -> None:
        timer = getattr(self, "_preview_refresh_timer", None)
        if timer is None:
            self._render_preview()
            return
        try:
            timer.stop()
            timer.start(max(0, int(delay_ms)))
        except Exception:
            self._render_preview()

    def _current_preview_node_id(self) -> str:
        try:
            cur = self._current_node()
        except Exception:
            cur = None
        if cur is None:
            return ""
        return str(cur.id or "").strip()

    def _design_surface_signature(self) -> tuple[str, str]:
        root_layout = str((self._model.root.props or {}).get("layout") or "vertical").strip().lower()
        try:
            payload = self._model.to_dict()
        except Exception:
            payload = {}
        try:
            model_key = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            model_key = repr(payload)
        return root_layout, model_key

    def _restore_design_focus(self, node_id: str) -> None:
        nid = str(node_id or "").strip()
        if not nid:
            return

        root_layout = str((self._model.root.props or {}).get("layout") or "vertical").strip().lower()
        if root_layout == "absolute":
            try:
                self.canvas.select_node(nid)
            except Exception:
                pass
            try:
                self.canvas.ensure_valid_viewport()
            except Exception:
                pass
            return

        self._highlight_design_preview(nid)
        try:
            widget = self._design_wrap_by_id.get(nid)
        except Exception:
            widget = None
        if widget is not None:
            try:
                self._design_preview_scroll.ensureWidgetVisible(widget)
            except Exception:
                pass

    def _on_center_tab_changed(self, index: int) -> None:
        if index != 1:
            return
        if getattr(self, "_preview_rendered", False):
            return
        self._render_preview()
        self._preview_rendered = True

    def _preview_runtime_kwargs(self) -> dict:
        owner_meta = None
        try:
            owner_meta = self._resolve_owner_meta()
        except Exception:
            owner_meta = None

        manifest_rows = [owner_meta] if isinstance(owner_meta, dict) else []

        form_kind = "object_form"
        try:
            form_meta = getattr(self, "_form_meta_cache", None)
            if not isinstance(form_meta, dict):
                form_meta = self._vm.get_meta_by_guid(self._form_guid)
                if isinstance(form_meta, dict):
                    self._form_meta_cache = form_meta
            if isinstance(form_meta, dict):
                payload = form_meta.get("payload") if isinstance(form_meta.get("payload"), dict) else {}
                subtype = str(payload.get("subtype") or "").strip().lower()
                form_name = str(form_meta.get("name") or "").strip().lower()
                if subtype in {"list_form", "choice_form"}:
                    form_kind = "list_form"
                elif subtype == "object_form":
                    form_kind = "object_form"
                elif any(marker in form_name for marker in ("spysk", "list", "спис", "выбор", "вибір")):
                    form_kind = "list_form"
        except Exception:
            pass

        ctx = ObjContext(
            obj_guid=str((owner_meta or {}).get("guid") or ""),
            obj_type=str((owner_meta or {}).get("type") or ""),
            obj_name=str((owner_meta or {}).get("name") or ""),
            form_kind=form_kind,
        )

        def _access_checker(action: str) -> bool:
            action = str(action or "").strip().lower()
            if not action:
                return True
            if getattr(self, "_is_edit_enabled", lambda: True)():
                return True
            return action in {"open", "refresh", "close", "form.close", "form.refresh", "back", "form.back"}

        return {
            "ctx": ctx,
            "manifest_rows": manifest_rows,
            "access_checker": _access_checker,
        }

    def _on_canvas_geometry_changed_live(self, node_id: str, x: int, y: int, w: int, h: int) -> None:
        if self._ui_guard or not self._is_edit_enabled():
            return

        node = self._node_by_id.get(str(node_id or ""))
        if not node:
            return

        props = getattr(node, "props", {}) or {}
        props["x"], props["y"], props["w"], props["h"] = int(x), int(y), int(w), int(h)
        node.props = props

        if getattr(self, "_grp_geom", None) is not None and self._grp_geom.isVisible():
            self._ui_guard = True
            try:
                for spin in (self._sp_x, self._sp_y, self._sp_w, self._sp_h):
                    spin.blockSignals(True)
                self._sp_x.setValue(int(x))
                self._sp_y.setValue(int(y))
                self._sp_w.setValue(int(w))
                self._sp_h.setValue(int(h))
            finally:
                for spin in (self._sp_x, self._sp_y, self._sp_w, self._sp_h):
                    spin.blockSignals(False)
                self._ui_guard = False

        self._schedule_preview_refresh(75)

    def _on_canvas_geometry_changed_commit(self, node_id: str, x: int, y: int, w: int, h: int) -> None:
        if self._ui_guard or not self._is_edit_enabled():
            return
        self._on_canvas_geometry_changed_live(node_id, x, y, w, h)
        self._set_dirty(True)
        self._render_preview()

    def _on_canvas_move_requested(self, node_id: str, parent_id: str, x: int, y: int, w: int, h: int) -> None:
        if self._ui_guard or not self._is_edit_enabled():
            return

        nid = str(node_id or "").strip()
        pid = str(parent_id or "").strip() or "root"
        if not nid or nid == self._model.root.id:
            return

        node = self._node_by_id.get(nid)
        parent = self._node_by_id.get(pid)
        if node is None or parent is None or parent.type != "Container":
            return
        if node is parent:
            return

        def is_descendant(candidate: object, target_id: str) -> bool:
            try:
                for child in getattr(candidate, "children", []) or []:
                    if str(getattr(child, "id", "") or "") == target_id:
                        return True
                    if is_descendant(child, target_id):
                        return True
            except Exception:
                return False
            return False

        if is_descendant(node, pid):
            return

        old_parent = self._parent_node(nid)
        if old_parent is None:
            return

        try:
            old_parent.children = [child for child in old_parent.children if child.id != nid]
        except Exception:
            return

        node.props = dict(node.props or {})
        parent_layout = str((parent.props or {}).get("layout") or "vertical").strip().lower()
        if parent_layout == "absolute":
            node.props["x"] = int(x)
            node.props["y"] = int(y)
            node.props["w"] = int(w)
            node.props["h"] = int(h)
        elif parent_layout == "grid":
            cols = max(1, int((parent.props or {}).get("grid_columns") or 2))
            idx = len(parent.children)
            node.props["grid"] = {
                "row": idx // cols,
                "col": idx % cols,
                "rowspan": 1,
                "colspan": 1,
            }
            node.props.pop("x", None)
            node.props.pop("y", None)
            node.props.pop("w", None)
            node.props.pop("h", None)
        else:
            node.props.pop("x", None)
            node.props.pop("y", None)
            node.props.pop("w", None)
            node.props.pop("h", None)
            node.props.pop("grid", None)

        try:
            parent.children.append(node)
        except Exception:
            return

        self._set_dirty(True)
        self._rebuild_tree(keep_selected_id=nid)
        self._refresh_canvas()
        self._render_preview()
        try:
            QTimer.singleShot(0, lambda nid=nid: self._select_node_by_id(nid))
        except Exception:
            pass

    def _refresh_design_surface(self) -> None:
        focus_node_id = self._current_preview_node_id()
        signature = self._design_surface_signature()
        if signature == getattr(self, "_design_surface_signature_cache", None):
            self._restore_design_focus(focus_node_id)
            self._update_design_toolbar_state()
            return

        root_layout = str((self._model.root.props or {}).get("layout") or "vertical").strip().lower()
        try:
            self._design_surface_signature_cache = signature
            if root_layout == "absolute":
                self._design_stack.setCurrentIndex(0)
                self._design_hint.setText("")
                self.canvas.rebuild(model_root=self._model.root)
                QTimer.singleShot(0, lambda nid=focus_node_id: self._restore_design_focus(nid))
            else:
                self._design_stack.setCurrentIndex(1)
                self._design_hint.setText(t("form_design_non_absolute_hint"))
                if getattr(self, "_design_preview_rendered", False):
                    self._render_design_preview(focus_node_id=focus_node_id)
                else:
                    QTimer.singleShot(0, lambda nid=focus_node_id: self._render_design_preview(focus_node_id=nid))

            self._update_design_toolbar_state()
        except Exception:
            self._design_surface_signature_cache = None
            logging.getLogger(__name__).exception("Form designer surface refresh failed")

    def _clear_preview(self) -> None:
        lay = self.preview_host.layout()
        if lay is None:
            return
        while lay.count():
            item = lay.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout is not None:
                while child_layout.count():
                    it2 = child_layout.takeAt(0)
                    if it2 is None:
                        break
                    w2 = it2.widget()
                    if w2 is not None:
                        w2.setParent(None)
                        w2.deleteLater()

    def _clear_design_preview(self) -> None:
        lay = self._design_preview_host.layout()
        if lay is None:
            return
        while lay.count():
            item = lay.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout is not None:
                while child_layout.count():
                    it2 = child_layout.takeAt(0)
                    if it2 is None:
                        break
                    w2 = it2.widget()
                    if w2 is not None:
                        w2.setParent(None)
                        w2.deleteLater()

    def _render_preview(self) -> None:
        tab_state = self._capture_runtime_tab_state(getattr(self, "_preview_runtime_widget", None))
        self._clear_preview()
        host_l = self._preview_layout
        runtime_kwargs = self._preview_runtime_kwargs()
        self._preview_runtime_widget = FormRuntimeWidget(
            model=self._model,
            embedded=True,
            ctx=runtime_kwargs["ctx"],
            manifest_rows=runtime_kwargs["manifest_rows"],
            access_checker=runtime_kwargs.get("access_checker"),
            parent=self.preview_host,
        )
        self._preview_runtime_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        host_l.addWidget(self._preview_runtime_widget, 1)
        host_l.addStretch(1)
        self._restore_runtime_tab_state(self._preview_runtime_widget, tab_state)
        try:
            self.preview_scroll.horizontalScrollBar().setValue(0)
            self.preview_scroll.verticalScrollBar().setValue(0)
        except Exception:
            pass
        self._preview_rendered = True
        self._refresh_design_surface()

    def _render_design_preview(self, focus_node_id: str | None = None) -> None:
        if not hasattr(self, "_design_preview_layout"):
            return
        tab_state = self._capture_runtime_tab_state(getattr(self, "_design_runtime_surface", None))
        self._clear_design_preview()
        self._design_wrap_by_id.clear()
        runtime_kwargs = self._preview_runtime_kwargs()
        self._design_runtime_surface = _DesignerRuntimeSurface(
            model=self._model,
            ctx=runtime_kwargs["ctx"],
            manifest_rows=runtime_kwargs["manifest_rows"],
            access_checker=runtime_kwargs.get("access_checker"),
            parent=self._design_preview_host,
        )
        self._design_runtime_surface.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._design_runtime_surface.nodeActivated.connect(self._select_node_by_id)
        self._design_runtime_surface.addControlRequested.connect(self._on_canvas_add_control)
        self._design_runtime_surface.addRequisiteRequested.connect(self._on_canvas_add_requisite)
        self._design_runtime_surface.copyRequested.connect(self._copy_node_by_id)
        self._design_runtime_surface.cutRequested.connect(self._cut_node_by_id)
        self._design_runtime_surface.pasteRequested.connect(self._paste_to_node)
        self._design_runtime_surface.duplicateRequested.connect(self._duplicate_node_by_id)
        self._design_runtime_surface.deleteRequested.connect(self._delete_node_by_id)
        self._design_wrap_by_id = dict(self._design_runtime_surface.wrap_by_id)
        self._design_preview_layout.addWidget(self._design_runtime_surface, 1)
        self._design_preview_layout.addStretch(1)
        self._restore_runtime_tab_state(self._design_runtime_surface, tab_state)
        focus_id = str(focus_node_id or self._current_preview_node_id() or "").strip()
        self._restore_design_focus(focus_id)
        self._design_preview_rendered = True

    def _highlight_design_preview(self, node_id: str) -> None:
        try:
            if getattr(self, "_design_runtime_surface", None) is not None:
                self._design_runtime_surface.highlight_node(node_id)
        except Exception:
            pass
