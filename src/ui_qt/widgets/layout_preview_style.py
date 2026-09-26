from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox


class LayoutPreviewStyleMixin:
    def _cell_paint_state(
        self,
        row: int,
        col: int,
        *,
        selected: bool,
        current: bool,
    ) -> tuple[QColor, QColor, int]:
        cell = self._sheet_cells.get((row, col)) or {}
        fmt = self._format_for_cell(cell)
        fill_type = str(cell.get("fill_type") or fmt.get("fillType") or "").strip().lower()
        base = QColor("#FFFFFF")
        if fill_type == "parameter":
            base = QColor("#FFFDEA")
        elif fill_type == "template":
            base = QColor("#F8FAFC")
        elif fill_type == "value":
            base = QColor("#F9FAFB")
        if selected:
            base = QColor("#D6E8FF")

        border_preset = self._border_preset_from_fmt(fmt)
        border_color = QColor("#E5E7EB")
        border_width = 1
        if border_preset == "solid":
            border_color = QColor("#94A3B8")
        elif border_preset == "thick":
            border_color = QColor("#64748B")
            border_width = 2
        if current:
            border_color = QColor("#2563EB")
            border_width = max(border_width, 2)
        elif selected:
            border_color = QColor("#3B82F6")
            border_width = max(border_width, 2)
        return base, border_color, border_width


    @staticmethod
    def _border_preset_from_fmt(fmt: Dict[str, Any]) -> str:
        present = False
        max_value = 0
        for key in ("border", "topBorder", "bottomBorder", "leftBorder", "rightBorder"):
            if key not in fmt:
                continue
            present = True
            max_value = max(max_value, LayoutPreviewStyleMixin._safe_int(fmt.get(key), 0))
        if not present:
            return ""
        if max_value <= 0:
            return "none"
        if max_value >= 2:
            return "thick"
        return "solid"


    @staticmethod
    def _apply_border_preset(cell: Dict[str, Any], preset: str) -> None:
        preset = str(preset or "").strip().lower()
        for key in ("border_style", "border", "top_border", "bottom_border", "left_border", "right_border"):
            cell.pop(key, None)
        if not preset:
            return
        cell["border_style"] = preset
        if preset == "none":
            border_value = 0
        elif preset == "thick":
            border_value = 2
        else:
            border_value = 1
        cell["border"] = border_value
        cell["top_border"] = border_value
        cell["bottom_border"] = border_value
        cell["left_border"] = border_value
        cell["right_border"] = border_value


    def _cell_font_height(self, cell: Dict[str, Any]) -> int | str:
        if "font_height" in cell:
            return self._safe_int(cell.get("font_height"), 0)
        fmt = self._format_for_cell(cell)
        font_idx = self._safe_int(fmt.get("font"), -1)
        fonts = self._layout_model.get("fonts") if isinstance(self._layout_model.get("fonts"), list) else []
        if 0 <= font_idx < len(fonts):
            font_info = fonts[font_idx]
            if isinstance(font_info, dict):
                try:
                    return int(float(font_info.get("height") or 0))
                except Exception:
                    return ""
        return ""


    @staticmethod
    def _set_combo_data(combo: QComboBox | None, value: object) -> None:
        if combo is None:
            return
        idx = combo.findData(value)
        if idx < 0:
            idx = 0
        combo.setCurrentIndex(idx)


    @staticmethod
    def _cell_alignment(fmt: Dict[str, Any]) -> Qt.AlignmentFlag:
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        h = str(fmt.get("horizontalAlignment") or "").strip().lower()
        v = str(fmt.get("verticalAlignment") or "").strip().lower()
        if h == "center":
            align = (align & ~Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignHCenter
        elif h == "right":
            align = (align & ~Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignRight
        if v == "top":
            align = (align & ~Qt.AlignmentFlag.AlignVCenter) | Qt.AlignmentFlag.AlignTop
        elif v == "bottom":
            align = (align & ~Qt.AlignmentFlag.AlignVCenter) | Qt.AlignmentFlag.AlignBottom
        return align


    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            if value is None:
                return int(default)
            return int(value)
        except Exception:
            return int(default)


    @staticmethod
    def _sheet_width_to_px(value: Any) -> int:
        raw = LayoutPreviewStyleMixin._safe_int(value, 80)
        return max(18, min(320, int(round(raw * 0.42))))
