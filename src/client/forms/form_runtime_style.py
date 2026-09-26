from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path
from typing import Any, Dict

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QPushButton, QStyle, QWidget

from src.configurator.domain.form_model import FormNode
from src.ui_qt.styles import render_qss_fragments

log = logging.getLogger(__name__)

FORM_SURFACE_BG = "#F8FAFC"
FORM_CARD_BG = "#FFFFFF"
FORM_TEXT = "#0F172A"
FORM_MUTED = "#64748B"
FORM_BORDER = "#E2E8F0"
FORM_BORDER_STRONG = "#CBD5E1"
FORM_PRIMARY = "#2563EB"
FORM_PRIMARY_HOVER = "#1D4ED8"
FORM_PRIMARY_ACTIVE = "#1E40AF"
FORM_PRIMARY_SOFT = "#DBEAFE"
FORM_ACCENT_BG = "#EFF6FF"
FORM_TABLE_HEADER = "#F8FAFC"

_ASSETS = Path(__file__).resolve().parents[3] / "src" / "assets" / "icons" / "svg"
_STYLE_ROOT = Path(__file__).resolve().parent / "styles"
_FORM_SURFACE_FRAGMENTS = (
    "qwidget.qss",
    "qlabel.qss",
    "qscrollarea.qss",
    "qframe.qss",
    "qgroupbox.qss",
    "qlineedit.qss",
    "qtextedit.qss",
    "qcombobox.qss",
    "qdateedit.qss",
    "qabstractspinbox.qss",
    "qcalendarwidget.qss",
    "qcheckbox.qss",
    "qtoolbutton.qss",
    "qpushbutton.qss",
    "qtableview.qss",
    "qtabwidget.qss",
)


def build_form_surface_stylesheet(*, calendar_icon: str) -> str:
    return render_qss_fragments(
        base_dir=_STYLE_ROOT,
        fragments=_FORM_SURFACE_FRAGMENTS,
        tokens={
            "FORM_ACCENT_BG": FORM_ACCENT_BG,
            "FORM_BORDER": FORM_BORDER,
            "FORM_BORDER_STRONG": FORM_BORDER_STRONG,
            "FORM_CARD_BG": FORM_CARD_BG,
            "FORM_MUTED": FORM_MUTED,
            "FORM_PRIMARY": FORM_PRIMARY,
            "FORM_PRIMARY_ACTIVE": FORM_PRIMARY_ACTIVE,
            "FORM_PRIMARY_HOVER": FORM_PRIMARY_HOVER,
            "FORM_PRIMARY_SOFT": FORM_PRIMARY_SOFT,
            "FORM_SURFACE_BG": FORM_SURFACE_BG,
            "FORM_TABLE_HEADER": FORM_TABLE_HEADER,
            "FORM_TEXT": FORM_TEXT,
            "calendar_icon": calendar_icon,
        },
    )


class FormRuntimeStyleMixin:
    @staticmethod
    @lru_cache(maxsize=1)
    def _form_surface_stylesheet() -> str:
        calendar_icon = str(_ASSETS / "calendar.svg").replace("\\", "/")

        log.info(f"FormRuntimeStyleMixin._form_surface_stylesheet path={calendar_icon} status=loaded")
        return build_form_surface_stylesheet(calendar_icon=calendar_icon)


    @staticmethod
    def _node_props(node: FormNode) -> Dict[str, Any]:
        return node.props if isinstance(node.props, dict) else {}


    @staticmethod
    def _normalize_group_representation(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"", "auto"}:
            return ""
        if raw in {"none", "нет"}:
            return "none"
        if raw in {"weakseparation", "weak", "слабое выделение"}:
            return "weak"
        if raw in {"strongseparation", "strong", "сильное выделение"}:
            return "strong"
        return "usual"


    @staticmethod
    def _normalize_title_location(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"none", "нет"}:
            return "none"
        if raw in {"top", "верх"}:
            return "top"
        return "left"


    @staticmethod
    def _normalize_group_anchor(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"", "auto"}:
            return ""
        if raw in {"start", "left", "top", "початок", "слева", "верх", "ліворуч", "зверху"}:
            return "start"
        if raw in {"center", "centre", "центр"}:
            return "center"
        if raw in {"end", "right", "bottom", "кінець", "справа", "праворуч", "низ", "знизу"}:
            return "end"
        if raw in {"stretch", "fill", "розтягнути", "растянуть"}:
            return "stretch"
        return ""


    @staticmethod
    def _frame_style(level: str) -> str:
        if level == "strong":
            border = FORM_BORDER_STRONG
        elif level == "weak":
            border = "#EDF2F7"
        else:
            border = FORM_BORDER
        return (
            "QFrame{"
            f"border:1px solid {border};"
            "border-radius:10px;"
            f"background:{FORM_CARD_BG};"
            "}"
        )


    @staticmethod
    def _groupbox_style(level: str) -> str:
        if level == "strong":
            border = FORM_BORDER_STRONG
        elif level == "weak":
            border = "#EDF2F7"
        else:
            border = FORM_BORDER
        return (
            "QGroupBox{"
            f"border:1px solid {border}; border-radius:10px; margin-top:14px; padding:12px 12px 12px 12px;"
            f"background:{FORM_CARD_BG};"
            "} "
            f"QGroupBox::title{{subcontrol-origin: margin; left: 10px; padding: 0 6px; color:{FORM_MUTED};}}"
        )


    @staticmethod
    def _mark_form_editor(widget: QWidget) -> None:
        widget.setProperty("mp_form_editor", True)


    @staticmethod
    def _mark_form_table(widget: "QTableView") -> None:
        from src.ui_qt.row_delegate import WholeRowHoverDelegate
        widget.setProperty("mp_form_table", True)
        widget.setItemDelegate(WholeRowHoverDelegate(widget))


    @staticmethod
    def _mark_command_button(
        widget: QPushButton,
        *,
        primary: bool = False,
        variant: str = "outline",
    ) -> None:
        widget.setProperty("mp_form_command", True)
        widget.setProperty("mp_button_variant", "primary" if primary else str(variant or "outline"))
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        try:
            widget.setIconSize(QSize(16, 16))
        except Exception:
            pass
        if primary:
            widget.setProperty("mp_primary_command", True)


    def _apply_command_icon(self, widget: QPushButton, *, command: str = "", title: str = "") -> None:
        hay = f"{command} {title}".strip().lower()
        style = self.style()
        icon = None
        if any(token in hay for token in ("save", "зберег", "сохран")):
            icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        elif any(token in hay for token in ("close", "закр", "закры")):
            icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)
        elif any(token in hay for token in ("add", "дод", "доба", "созд")):
            icon = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        elif any(token in hay for token in ("delete", "видал", "удал")):
            icon = style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        elif any(token in hay for token in ("print", "друк", "печат")):
            icon = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        elif any(token in hay for token in ("up", "вгору", "вверх")):
            icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
        elif any(token in hay for token in ("down", "вниз", "вни")):
            icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        elif any(token in hay for token in ("refresh", "онов", "обнов")):
            icon = style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        if icon is not None:
            widget.setIcon(icon)


    @staticmethod
    def _node_prefers_vertical_stretch(node: FormNode) -> bool:
        """Чи хоче цей тип займати максимум вертикального простору."""
        props = node.props if isinstance(node.props, dict) else {}
        anchor = FormRuntimeStyleMixin._normalize_group_anchor(props.get("group_anchor") or props.get("anchor"))
        if anchor == "stretch":
            return True
        if bool(props.get("vertical_stretch")):
            return True
        return str(node.type or "").strip() in {
            "Table", "Tabs", "TablePanel", "TextArea",
        }

    @staticmethod
    def _node_prefers_horizontal_stretch(node: FormNode) -> bool:
        """Чи хоче цей тип займати максимум горизонтального простору."""
        props = node.props if isinstance(node.props, dict) else {}
        anchor = FormRuntimeStyleMixin._normalize_group_anchor(props.get("group_anchor") or props.get("anchor"))
        if anchor == "stretch":
            return True
        if bool(props.get("horizontal_stretch")):
            return True
        return str(node.type or "").strip() in {
            "Table", "Tabs", "TablePanel", "CommandBar", "StatusBar", "TextBox", "TextArea", "ComboBox",
        }
