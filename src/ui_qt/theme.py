from __future__ import annotations

from pathlib import Path
from PySide6.QtGui import QIcon

arrow = (Path(__file__).resolve().parents[2] / "src" / "assets" / "icon" / "arrow_down.png").as_posix()


BG = "#0B1020"
PANEL = "#0F172A"
PANEL_2 = "#111C33"
FG = "#E7EAF0"
SUBTLE = "#9AA4B2"
BORDER = "#22304A"
ACCENT = "#5B5BD6"


def apply_dark_theme(app) -> None:
    # простой QSS, можно расширять
    qss = f"""
    QWidget {{
        background: {BG};
        color: {FG};
        font-family: "Segoe UI";
        font-size: 10pt;
    }}

    QLineEdit {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 6px 10px;
    }}

    QPushButton {{
        background: {PANEL_2};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 8px 10px;
    }}
    QPushButton:hover {{
        border-color: {ACCENT};
    }}
    QPushButton:disabled {{
        color: {SUBTLE};
    }}

    QComboBox {{
        background: #111C33;
        color: #E7EAF0;
        border: 1px solid #22304A;
        padding: 5px 6px 6px 5px;
        border-radius: 8px;
        text-align: center;
    }}
    QComboBox::drop-down {{
        border: 0px;
        width: 20px;
    }}
    QComboBox::down-arrow {{
        image: url({arrow}); /* если хочешь свою стрелку — можно через qrc/png */
        padding: 5px 8px 2px 0px;
        width: 12px;
        height: 12px;
    }}
    QComboBox QAbstractItemView {{
        background: #0F172A;
        color: #E7EAF0;
        selection-background-color: #5B5BD6;
        border: 1px solid #22304A;
        outline: 0;
    }}
    
    QTableView {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 16px;
        gridline-color: {BORDER};
        selection-background-color: {ACCENT};
        selection-color: white;
    }}
    QHeaderView::section {{
        background: {PANEL_2};
        border: none;
        padding: 8px;
        font-weight: 600;
    }}
    """
    app.setStyleSheet(qss)


def set_app_icon(app) -> None:
    # твой путь: assets/icon/mp.png
    root = Path(__file__).resolve().parents[2]  # .../MetaPlatform
    icon_path = root / "src" / "assets" / "icon" / "mp.png"  # .../src/assets/icon/mp.png
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
