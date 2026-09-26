from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

from src.ui_qt.services.icon_provider import IconProvider, IconRenderOptions


def _icons_dir() -> Path:
    # .../src/assets/icons/svg
    return Path(__file__).resolve().parents[1] / "assets" / "icons" / "svg"


def _load_svg_icon(icon_provider: IconProvider, name: str, *, size: int = 16) -> QIcon:
    """Load a lucide-style svg icon by filename (without extension)."""
    p = _icons_dir() / f"{name}.svg"
    if not p.exists():
        # Some icons in the pack contain spaces or different casing.
        # We keep the default fallback to an empty icon for robustness.
        return QIcon()

    try:
        data = p.read_bytes()
        pm = icon_provider.svg_bytes_to_pixmap(data, opts=IconRenderOptions(size=size, transparent=True))
        return QIcon(pm)
    except Exception:
        return QIcon()
