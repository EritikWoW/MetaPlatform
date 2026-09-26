"""Dashboard — main landing view matching the pythonic-business-engine design."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from src.ui_qt.i18n import t


# ── Helpers ──────────────────────────────────────────────────────────────────

def _hsl_to_hex(h: int, s: int, l: int) -> str:  # noqa: E741
    """Convert HSL (0-360, 0-100, 0-100) to #RRGGBB."""
    s /= 100; l /= 100
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    h6 = int(h / 60)
    if h6 == 0: r, g, b = c, x, 0
    elif h6 == 1: r, g, b = x, c, 0
    elif h6 == 2: r, g, b = 0, c, x
    elif h6 == 3: r, g, b = 0, x, c
    elif h6 == 4: r, g, b = x, 0, c
    else: r, g, b = c, 0, x
    return "#{:02X}{:02X}{:02X}".format(int((r+m)*255), int((g+m)*255), int((b+m)*255))


# Design tokens (from index.css)
C_BG         = _hsl_to_hex(210, 20, 98)   # #F7F9FC
C_CARD       = "#FFFFFF"
C_FOREGROUND = _hsl_to_hex(220, 25, 10)   # #1A1F2E
C_MUTED_FG   = _hsl_to_hex(215, 15, 45)   # #6B7280
C_BORDER     = _hsl_to_hex(214, 32, 91)   # #E8EBF1
C_PRIMARY    = _hsl_to_hex(217, 91, 50)   # #4D9EFF
C_SUCCESS    = _hsl_to_hex(142, 71, 45)   # #22C55E
C_WARNING    = _hsl_to_hex(38,  92, 50)   # #FDB022
C_DANGER     = _hsl_to_hex(0,   72, 51)   # #EE2B2B
C_CYAN       = "#0891B2"
C_PURPLE     = "#7C3AED"
C_GREEN      = "#059669"


# ── Sub-components ────────────────────────────────────────────────────────────

class StatCard(QFrame):
    """Metric card with title, large value, and change indicator."""

    def __init__(
        self,
        title: str,
        value: str,
        change: str = "",
        change_type: str = "neutral",   # positive | negative | neutral
        icon: str = "",
        color: str = C_PRIMARY,
    ) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("StatCard")
        self.setStyleSheet(f"""
            QFrame#StatCard {{
                background: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 12px;
            }}
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(110)

        hl = QHBoxLayout(self)
        hl.setContentsMargins(20, 16, 20, 16)
        hl.setSpacing(12)

        # Left: texts
        left = QVBoxLayout()
        left.setSpacing(4)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(f"color: {C_MUTED_FG}; font-size: 9pt;")
        left.addWidget(t_lbl)

        v_lbl = QLabel(value)
        v_lbl.setStyleSheet(f"color: {color}; font-size: 20pt; font-weight: 800;")
        left.addWidget(v_lbl)

        if change:
            change_color = C_SUCCESS if change_type == "positive" else (
                C_DANGER if change_type == "negative" else C_MUTED_FG)
            c_lbl = QLabel(change)
            c_lbl.setStyleSheet(f"color: {change_color}; font-size: 8pt;")
            left.addWidget(c_lbl)

        hl.addLayout(left, 1)

        # Right: icon badge
        if icon:
            badge = QLabel(icon)
            badge.setFixedSize(44, 44)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(f"""
                QLabel {{
                    background: {color}22;
                    border-radius: 10px;
                    font-size: 18pt;
                }}
            """)
            hl.addWidget(badge)


class SectionCard(QFrame):
    """Generic card container with optional header."""

    def __init__(self, title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("SectionCard")
        self.setStyleSheet(f"""
            QFrame#SectionCard {{
                background: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 12px;
            }}
        """)
        self._vl = QVBoxLayout(self)
        self._vl.setContentsMargins(20, 16, 20, 16)
        self._vl.setSpacing(12)

        if title:
            hdr = QLabel(title)
            hdr.setStyleSheet(f"font-size: 11pt; font-weight: 700; color: {C_FOREGROUND};")
            self._vl.addWidget(hdr)

            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"border: none; border-top: 1px solid {C_BORDER};")
            sep.setFixedHeight(1)
            self._vl.addWidget(sep)

    def body_layout(self) -> QVBoxLayout:
        return self._vl


class QuickActionButton(QPushButton):
    def __init__(self, icon: str, label: str, color: str = C_PRIMARY) -> None:
        super().__init__()
        self.setFixedHeight(56)
        self.setStyleSheet(f"""
            QPushButton {{
                background: {C_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 9.5pt;
                color: {C_FOREGROUND};
                text-align: left;
            }}
            QPushButton:hover {{
                background: {color}11;
                border-color: {color}88;
            }}
            QPushButton:pressed {{ background: {color}22; }}
        """)
        hl = QHBoxLayout(self)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(10)

        icon_lbl = QLabel(icon)
        icon_lbl.setFixedSize(28, 28)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"""
            QLabel {{
                background: {color}22;
                border-radius: 6px;
                font-size: 14pt;
            }}
        """)
        hl.addWidget(icon_lbl)

        txt_lbl = QLabel(label)
        txt_lbl.setStyleSheet(f"color: {C_FOREGROUND}; font-size: 9pt; font-weight: 500;")
        hl.addWidget(txt_lbl, 1)


# ── Main Dashboard ────────────────────────────────────────────────────────────

class DashboardView(QWidget):
    def __init__(
        self,
        db=None,
        manifest_rows=None,
        on_open: Optional[Callable[[str], None]] = None,
        **_kwargs,
    ) -> None:
        super().__init__()
        self.title = t("client_nav_dashboard")
        self._db = db
        self._on_open = on_open

        # Count objects by type
        rows = list(manifest_rows or [])
        if not rows and self._db is not None:
            try:
                gw = getattr(self._db, "_gw", None)
                if gw is not None and hasattr(gw, "manifest_nav"):
                    rows = [r for r in gw.manifest_nav() if isinstance(r, dict)]
            except Exception:
                rows = []
        n_cat = n_doc = n_sub = n_rep = 0
        catalogs: list[dict] = []
        documents: list[dict] = []
        for r in rows:
            tp = str((r.get("type") if isinstance(r, dict) else getattr(r, "type", "")) or "").lower()
            kd = str((r.get("kind") if isinstance(r, dict) else getattr(r, "kind", "")) or "").lower()
            nm = str((r.get("name") if isinstance(r, dict) else getattr(r, "name", "")) or "")
            tt = str((r.get("title") if isinstance(r, dict) else getattr(r, "title", "")) or nm)
            if kd != "object":
                continue
            if tp == "catalog":
                n_cat += 1
                if len(catalogs) < 4:
                    catalogs.append({"guid": str(r.get("guid") or ""), "name": nm, "title": tt, "type": tp})
            elif tp == "document":
                n_doc += 1
                if len(documents) < 4:
                    documents.append({"guid": str(r.get("guid") or ""), "name": nm, "title": tt, "type": tp})
            elif tp == "subsystem":
                n_sub += 1
            elif tp == "report":
                n_rep += 1

        self._build_ui(n_cat, n_doc, n_sub, n_rep, catalogs, documents)

    def _build_ui(
        self,
        n_cat: int, n_doc: int, n_sub: int, n_rep: int,
        catalogs: list, documents: list,
    ) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setStyleSheet(f"background: {C_BG};")
        vl = QVBoxLayout(content)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(20)

        # ── Stat cards (4-column grid) ─────────────────────────────────────
        cards_grid = QGridLayout()
        cards_grid.setHorizontalSpacing(14)
        cards_grid.setVerticalSpacing(14)

        stat_data = [
            (t("client_nav_catalogs") or "Довідники",
             str(n_cat), "", "neutral", "📚", C_PRIMARY),
            (t("client_nav_documents") or "Документи",
             str(n_doc), "", "neutral", "📄", C_CYAN),
            (t("client_nav_subsystems") or "Subsystems",
             str(n_sub), "", "neutral", "🗂", C_PURPLE),
            (t("client_nav_reports") or "Звіти",
             str(n_rep), "", "neutral", "📊", C_GREEN),
        ]
        for i, (title, val, change, ctype, icon, color) in enumerate(stat_data):
            card = StatCard(title, val, change, ctype, icon, color)
            cards_grid.addWidget(card, 0, i)

        vl.addLayout(cards_grid)

        # ── Main 2-column layout ───────────────────────────────────────────
        main_grid = QGridLayout()
        main_grid.setHorizontalSpacing(16)
        main_grid.setColumnStretch(0, 3)
        main_grid.setColumnStretch(1, 2)

        # Left: Quick open + recent
        left_vl = QVBoxLayout()
        left_vl.setSpacing(16)

        # Catalog quick-open card
        if catalogs or documents:
            open_card = SectionCard(t("client_dashboard_quick_access"))
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            all_items = [(r, C_PRIMARY) for r in catalogs] + [(r, C_CYAN) for r in documents]
            for i, (item, color) in enumerate(all_items[:8]):
                title = item.get("title") or item.get("name") or ""
                icon = "📚" if item.get("type") == "catalog" else "📄"
                btn = QuickActionButton(icon, title, color)
                obj_guid = item.get("guid", "")
                if obj_guid and self._on_open:
                    btn.clicked.connect(lambda _, g=obj_guid: self._on_open(g))
                grid.addWidget(btn, i // 2, i % 2)
            open_card.body_layout().addLayout(grid)
            left_vl.addWidget(open_card)

        # Welcome text if nothing configured yet
        if not catalogs and not documents:
            welcome = SectionCard(t("client_dashboard_setup_title"))
            info = QLabel(t("client_dashboard_setup_body"))
            info.setStyleSheet(f"color: {C_MUTED_FG}; font-size: 10pt; line-height: 160%;")
            info.setWordWrap(True)
            welcome.body_layout().addWidget(info)
            left_vl.addWidget(welcome)

        left_vl.addStretch(1)
        main_grid.addLayout(left_vl, 0, 0)

        # Right: System info card
        right_vl = QVBoxLayout()
        right_vl.setSpacing(16)

        info_card = SectionCard(t("client_dashboard_system"))
        db_name = ""
        if self._db is not None:
            try:
                db_name = str(getattr(getattr(self._db, "_gw", None), "session_id", "")[:8] or "")
            except Exception:
                pass

        rows_info = [
            (f"{t('client_nav_catalogs')}:", f"{n_cat}"),
            (f"{t('client_nav_documents')}:", f"{n_doc}"),
            (f"{t('client_nav_subsystems')}:", str(n_sub)),
            (f"{t('client_nav_reports')}:", str(n_rep)),
        ]
        for label, val in rows_info:
            row_w = QWidget()
            rh = QHBoxLayout(row_w)
            rh.setContentsMargins(0, 2, 0, 2)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {C_MUTED_FG}; font-size: 9pt;")
            val_lbl = QLabel(val)
            val_lbl.setStyleSheet(f"color: {C_FOREGROUND}; font-size: 9pt; font-weight: 600;")
            rh.addWidget(lbl)
            rh.addStretch(1)
            rh.addWidget(val_lbl)
            info_card.body_layout().addWidget(row_w)

        right_vl.addWidget(info_card)
        right_vl.addStretch(1)
        main_grid.addLayout(right_vl, 0, 1)

        vl.addLayout(main_grid)
        vl.addStretch(1)

        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._scroll = scroll

    def refresh(self, manifest_rows) -> None:
        """Rebuild dashboard content with updated manifest data."""
        rows = list(manifest_rows or [])
        n_cat = n_doc = n_sub = n_rep = 0
        catalogs: list[dict] = []
        documents: list[dict] = []
        for r in rows:
            tp = str((r.get("type") if isinstance(r, dict) else getattr(r, "type", "")) or "").lower()
            kd = str((r.get("kind") if isinstance(r, dict) else getattr(r, "kind", "")) or "").lower()
            nm = str((r.get("name") if isinstance(r, dict) else getattr(r, "name", "")) or "")
            tt = str((r.get("title") if isinstance(r, dict) else getattr(r, "title", "")) or nm)
            if kd != "object":
                continue
            if tp == "catalog":
                n_cat += 1
                if len(catalogs) < 4:
                    catalogs.append({"guid": str(r.get("guid") or ""), "name": nm, "title": tt, "type": tp})
            elif tp == "document":
                n_doc += 1
                if len(documents) < 4:
                    documents.append({"guid": str(r.get("guid") or ""), "name": nm, "title": tt, "type": tp})
            elif tp == "subsystem":
                n_sub += 1
            elif tp == "report":
                n_rep += 1

        # Remove old scroll content and rebuild
        old_widget = self._scroll.takeWidget()
        if old_widget:
            old_widget.deleteLater()

        # Rebuild UI (reuse _build_ui but need a new scroll setup)
        content = QWidget()
        content.setStyleSheet(f"background: {C_BG};")
        vl = QVBoxLayout(content)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(20)

        cards_grid = QGridLayout()
        cards_grid.setHorizontalSpacing(14)
        cards_grid.setVerticalSpacing(14)
        stat_data = [
            (t("client_nav_catalogs") or "Довідники",  str(n_cat), "", "neutral", "📚", C_PRIMARY),
            (t("client_nav_documents") or "Документи", str(n_doc), "", "neutral", "📄", C_CYAN),
            (t("client_nav_subsystems") or "Subsystems", str(n_sub), "", "neutral", "🗂", C_PURPLE),
            (t("client_nav_reports") or "Reports", str(n_rep), "", "neutral", "📊", C_GREEN),
        ]
        for i, (title, val, change, ctype, icon, color) in enumerate(stat_data):
            cards_grid.addWidget(StatCard(title, val, change, ctype, icon, color), 0, i)
        vl.addLayout(cards_grid)

        if catalogs or documents:
            open_card = SectionCard(t("client_dashboard_quick_access"))
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            all_items = [(r, C_PRIMARY) for r in catalogs] + [(r, C_CYAN) for r in documents]
            for i, (item, color) in enumerate(all_items[:8]):
                btn = QuickActionButton(
                    "📚" if item.get("type") == "catalog" else "📄",
                    item.get("title") or item.get("name") or "", color,
                )
                obj_guid = item.get("guid", "")
                if obj_guid and self._on_open:
                    btn.clicked.connect(lambda _, g=obj_guid: self._on_open(g))
                grid.addWidget(btn, i // 2, i % 2)
            open_card.body_layout().addLayout(grid)
            vl.addWidget(open_card)
        elif rows:
            info_card = SectionCard(t("client_dashboard_system"))
            for label, val in [
                (f"{t('client_nav_catalogs')}:", f"{n_cat}"),
                (f"{t('client_nav_documents')}:", f"{n_doc}"),
                (f"{t('client_nav_subsystems')}:", str(n_sub)),
            ]:
                row_w = QWidget()
                rh = QHBoxLayout(row_w)
                rh.setContentsMargins(0, 2, 0, 2)
                lbl = QLabel(label)
                lbl.setStyleSheet(f"color: {C_MUTED_FG}; font-size: 9pt;")
                val_lbl = QLabel(val)
                val_lbl.setStyleSheet(f"color: {C_FOREGROUND}; font-size: 9pt; font-weight: 600;")
                rh.addWidget(lbl); rh.addStretch(1); rh.addWidget(val_lbl)
                info_card.body_layout().addWidget(row_w)
            vl.addWidget(info_card)

        vl.addStretch(1)
        self._scroll.setWidget(content)
