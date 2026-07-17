from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QColor, QPalette
from PySide6.QtWidgets import QApplication, QMdiSubWindow, QWidget

from .styles import render_qss_fragments

arrow = (Path(__file__).resolve().parents[2] / "src" / "assets" / "icons" / "arrow_down.png").as_posix()


BG = "#0B1020"
PANEL = "#0F172A"
PANEL_2 = "#111C33"
FG = "#E7EAF0"
SUBTLE = "#9AA4B2"
BORDER = "#22304A"
ACCENT = "#5B5BD6"

# Toolbar / action icons are rendered from monochrome SVG (lucide) where
# stroke/fill often uses `currentColor`. Our IconProvider replaces `currentColor`
# with QApplication.palette().color(QPalette.ButtonText). Поэтому важно, чтобы
# ButtonText корректно соответствовал теме.
DARK_BUTTON_TEXT = "#FFFFFF"   # dark theme: white icons/text on buttons
LIGHT_BUTTON_TEXT = "#0B1020"  # light theme (future): dark navy icons/text
_BRAND_FONT_CACHE: str | None = None
_APP_ICON_BINDER: QObject | None = None
_STYLE_ROOT = Path(__file__).resolve().parent / "styles"
_DARK_THEME_FRAGMENTS = (
    "qmenu.qss",
    "qwidget.qss",
    "qlineedit.qss",
    "qtreeview.qss",
    "qpushbutton.qss",
    "qcombobox.qss",
    "qtableview.qss",
    "qheaderview.qss",
)
_HYBRID_THEME_FRAGMENTS = (
    "qmdiarea.qss",
    "qscrollarea.qss",
    "qgraphicsview.qss",
    "qframe.qss",
    "qlineedit.qss",
    "qtextedit.qss",
    "qplaintextedit.qss",
    "qspinbox.qss",
    "qdoublespinbox.qss",
    "qdateedit.qss",
    "qtimeedit.qss",
    "qdatetimeedit.qss",
    "qcombobox.qss",
    "qpushbutton.qss",
    "qtableview.qss",
    "qheaderview.qss",
)


class _AppIconBinder(QObject):
    def __init__(self, icon: QIcon) -> None:
        super().__init__()
        self._icon = QIcon(icon)

    def _apply_icon(self, obj: object) -> None:
        if not isinstance(obj, QWidget):
            return
        if not obj.isWindow():
            return
        if isinstance(obj, QMdiSubWindow):
            return
        try:
            if bool(obj.property("mp_preserve_window_icon")):
                return
        except Exception:
            pass
        try:
            obj.setWindowIcon(self._icon)
        except Exception:
            pass

    def eventFilter(self, obj: object, event: object) -> bool:
        if isinstance(event, QEvent) and event.type() in (QEvent.Type.Polish, QEvent.Type.Show):
            self._apply_icon(obj)
        return False


def _set_button_text_palette(app: QApplication, *, color_hex: str) -> None:
    """Force palette ButtonText color.

    QSS doesn't reliably affect QPalette roles, but our SVG icon renderer relies
    on QPalette.ButtonText to compute the final stroke/fill color for lucide.
    """

    if not isinstance(app, QApplication):
        return

    col = QColor(color_hex)
    pal = app.palette()
    for grp in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        pal.setColor(grp, QPalette.ColorRole.ButtonText, col)
    app.setPalette(pal)


def _resolve_brand_font_family() -> str:
    global _BRAND_FONT_CACHE
    if _BRAND_FONT_CACHE:
        return _BRAND_FONT_CACHE

    families = {str(name) for name in QFontDatabase.families()}
    for candidate in ("Roboto", "Roboto Flex", "Segoe UI"):
        if candidate in families:
            _BRAND_FONT_CACHE = candidate
            return candidate

    font_dirs = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts",
    ]
    patterns = ("Roboto*.ttf", "Roboto*.otf")
    for font_dir in font_dirs:
        try:
            if not font_dir.exists():
                continue
            font_paths = []
            for pattern in patterns:
                font_paths.extend(font_dir.glob(pattern))
        except OSError:
            continue
        for font_path in font_paths:
            try:
                QFontDatabase.addApplicationFont(str(font_path))
            except Exception:
                continue

    families = {str(name) for name in QFontDatabase.families()}
    for candidate in ("Roboto", "Roboto Flex", "Segoe UI"):
        if candidate in families:
            _BRAND_FONT_CACHE = candidate
            return candidate

    _BRAND_FONT_CACHE = "Segoe UI"
    return _BRAND_FONT_CACHE


def _apply_brand_font(app: QApplication) -> None:
    if not isinstance(app, QApplication):
        return
    font = QFont(_resolve_brand_font_family(), 10)
    app.setFont(font)


def build_dark_theme_stylesheet() -> str:
    return render_qss_fragments(
        base_dir=_STYLE_ROOT / "dark",
        fragments=_DARK_THEME_FRAGMENTS,
        tokens={
            "ACCENT": ACCENT,
            "BG": BG,
            "BORDER": BORDER,
            "FG": FG,
            "PANEL": PANEL,
            "PANEL_2": PANEL_2,
            "SUBTLE": SUBTLE,
            "arrow_icon": arrow,
        },
    )


def build_hybrid_theme_stylesheet() -> str:
    return render_qss_fragments(
        base_dir=_STYLE_ROOT / "hybrid",
        fragments=_HYBRID_THEME_FRAGMENTS,
        tokens={
            "FORM_PRIMARY": "#2563EB",
            "FORM_PRIMARY_ACTIVE": "#1E40AF",
            "FORM_PRIMARY_HOVER": "#1D4ED8",
            "border_soft": "rgba(0,0,0,35)",
            "light_bg": "#FFFFFF",
            "light_panel": "#FFFFFF",
            "text_dark": "#0F172A",
        },
    )


def apply_dark_theme(app) -> None:
    _apply_brand_font(app)
    qss = build_dark_theme_stylesheet()
    app.setStyleSheet(qss)
    # Ensure lucide icons (currentColor) are visible on dark shell.
    _set_button_text_palette(app, color_hex=DARK_BUTTON_TEXT)
    # Make the active theme discoverable for services that can't reliably
    # infer it from QPalette (QSS does not update palette roles).
    try:
        app.setProperty("mp_theme", "dark")
    except Exception:
        pass


def apply_light_theme(app: QApplication) -> None:
    """Placeholder for a future light theme.

    Пока светлой темы нет, но заранее фиксируем ключевой инвариант:
    для светлой темы ButtonText (а значит и lucide-иконки) должны быть тёмно-синие.
    """

    # Leave existing QSS as-is for now, only palette role matters for icons.
    _set_button_text_palette(app, color_hex=LIGHT_BUTTON_TEXT)
    try:
        app.setProperty("mp_theme", "light")
    except Exception:
        pass


def set_app_icon(app) -> None:
    # app icon lives under src/assets/icons
    global _APP_ICON_BINDER
    root = Path(__file__).resolve().parents[2]  # .../MetaPlatform
    icon_path = root / "src" / "assets" / "icons" / "mp.png"  # .../src/assets/icons/mp.png
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        app.setWindowIcon(icon)
        if _APP_ICON_BINDER is None:
            _APP_ICON_BINDER = _AppIconBinder(icon)
            app.installEventFilter(_APP_ICON_BINDER)
        for widget in app.topLevelWidgets():
            if isinstance(widget, QMdiSubWindow):
                continue
            try:
                widget.setWindowIcon(icon)
            except Exception:
                pass


def apply_hybrid_theme(app: QApplication) -> None:
    """Apply a hybrid theme: dark shell + light canvas/editor surfaces."""
    apply_dark_theme(app)
    qss = app.styleSheet() + "\n\n" + build_hybrid_theme_stylesheet()
    app.setStyleSheet(qss)
