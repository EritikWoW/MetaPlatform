from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .layout_preview_build import LayoutPreviewBuildMixin
from .layout_preview_interaction import LayoutPreviewInteractionMixin
from .layout_preview_properties import _LayoutCellPropertiesWidget
from .layout_preview_state import LayoutPreviewStateMixin
from .layout_preview_style import LayoutPreviewStyleMixin


class LayoutPreviewWidget(
    LayoutPreviewBuildMixin,
    LayoutPreviewInteractionMixin,
    LayoutPreviewStateMixin,
    LayoutPreviewStyleMixin,
    QWidget,
):
    """Spreadsheet layout preview/editor for imported 1C layouts."""

    def __init__(
        self,
        *,
        title: str,
        payload: Dict[str, Any] | None = None,
        vm: Any | None = None,
        obj_guid: str = "",
    ) -> None:
        super().__init__()
        self._title = str(title or "")
        self._payload = dict(payload or {})
        self._vm = vm
        self._obj_guid = str(obj_guid or "")
        self._layout_model = self._resolve_layout_model()
        self._dirty = False
        self._closing = False
        self._close_prepared = False
        self._saved_layout_signature = self._layout_save_signature()
        self._table: QTableWidget | None = None
        self._sheet_formats: dict[int, dict[str, Any]] = {}
        self._sheet_cells: dict[tuple[int, int], dict[str, Any]] = {}
        self._sheet_merges: dict[tuple[int, int], dict[str, int]] = {}
        self._toolbar_block = False
        self._tool_range: QLineEdit | None = None
        self._tool_text: QLineEdit | None = None
        self._tool_fill: QComboBox | None = None
        self._tool_border: QComboBox | None = None
        self._tool_h_align: QComboBox | None = None
        self._tool_v_align: QComboBox | None = None
        self._tool_font_size: QComboBox | None = None
        self._tool_bold: QToolButton | None = None
        self._tool_italic: QToolButton | None = None
        self._tool_underline: QToolButton | None = None
        self._tool_merge: QToolButton | None = None
        self._tool_unmerge: QToolButton | None = None
        self._tool_area: QComboBox | None = None
        self._tool_area_assign: QToolButton | None = None
        self._tool_area_remove: QToolButton | None = None
        self._tool_area_goto: QToolButton | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(450)
        self._save_timer.timeout.connect(self._flush_pending_save)
        self._sheet_props = _LayoutCellPropertiesWidget()
        self._sheet_props.cellFieldChanged.connect(self._on_cell_property_changed)
        self._preview_page = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self._title_lbl = QLabel(self._title)
        self._title_lbl.setStyleSheet("font-size: 14pt; font-weight: 700;")
        root.addWidget(self._title_lbl, 0)

        self._preview_page = self._build_preview_page()
        root.addWidget(self._preview_page, 1)


    def _layout_save_signature(self) -> str:
        kind = str(self._layout_model.get("kind") or self._payload.get("layout_kind") or "").strip()
        body = {
            "kind": kind,
            "layout_model": self._layout_model,
        }
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha1(raw).hexdigest()


    def properties_widget(self) -> QWidget | None:
        return self._sheet_props


    def reload_from_vm(self) -> None:
        if self._vm is None or not self._obj_guid:
            return
        getter = getattr(self._vm, "get_meta_by_guid", None)
        meta = None
        if callable(getter):
            try:
                meta = getter(self._obj_guid)
            except Exception:
                meta = None
        if isinstance(meta, dict):
            payload = meta.get("payload")
            if isinstance(payload, dict):
                self._payload = dict(payload)
            title = str(meta.get("title") or meta.get("name") or "").strip()
            if title:
                self._title = title
                title_lbl = getattr(self, "_title_lbl", None)
                if title_lbl is not None:
                    try:
                        title_lbl.setText(title)
                    except Exception:
                        pass
        self._layout_model = self._resolve_layout_model()
        self._saved_layout_signature = self._layout_save_signature()
        self._dirty = False
        self._closing = False
        self._close_prepared = False

        root = self.layout()
        if root is None:
            return

        old_page = getattr(self, "_preview_page", None)
        sheet_props = getattr(self, "_sheet_props", None)
        if sheet_props is not None:
            try:
                sheet_props.setParent(self)
            except Exception:
                pass
        if old_page is not None:
            try:
                root.removeWidget(old_page)
            except Exception:
                pass
            try:
                old_page.setParent(None)
            except Exception:
                pass
            try:
                old_page.deleteLater()
            except Exception:
                pass

        self._preview_page = self._build_preview_page()
        root.addWidget(self._preview_page, 1)
