from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t, get_lang, set_lang, all_lang_displays, display_to_lang, lang_to_display


class SettingsView(QWidget):
    """Application settings: language, DB connection info."""

    def __init__(
        self,
        *,
        db_path: Path | None = None,
        runtime_url: str = "",
        db_uid: str = "",
        on_lang_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.title = t("client_nav_settings")
        self._on_lang_changed = on_lang_changed

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        h = QLabel(t("client_nav_settings"), self)
        h.setStyleSheet("font-size: 13pt; font-weight: 700;")
        root.addWidget(h)

        # ── Language section ─────────────────────────────────────────────
        lang_box = self._section(t("regional_ui_lang"))
        lang_form = QFormLayout()
        lang_form.setContentsMargins(0, 8, 0, 0)
        lang_form.setSpacing(10)

        self._lang_combo = QComboBox()
        for disp in all_lang_displays():
            self._lang_combo.addItem(disp)
        current_disp = lang_to_display(get_lang())
        idx = self._lang_combo.findText(current_disp)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)

        lang_apply = QPushButton(t("btn_activate"))
        lang_apply.setFixedWidth(100)
        lang_apply.clicked.connect(self._apply_lang)

        lang_row = QHBoxLayout()
        lang_row.setContentsMargins(0, 0, 0, 0)
        lang_row.setSpacing(8)
        lang_row.addWidget(self._lang_combo)
        lang_row.addWidget(lang_apply)
        lang_row.addStretch(1)

        lang_form.addRow(t("regional_ui_lang") + ":", lang_row)
        lang_box.layout().addLayout(lang_form)
        root.addWidget(lang_box)

        # ── Connection section ───────────────────────────────────────────
        db_box = self._section(t("infobase_db_info"))
        db_form = QFormLayout()
        db_form.setContentsMargins(0, 8, 0, 0)
        db_form.setSpacing(10)

        _url_lbl = QLabel(runtime_url if runtime_url else t("client_status_no_db"))
        _url_lbl.setStyleSheet("color: rgba(15,23,42,0.65);")
        db_form.addRow(t("dlg_runtime_url") + ":", _url_lbl)

        if db_uid:
            _uid_lbl = QLabel(db_uid)
            _uid_lbl.setStyleSheet("color: rgba(15,23,42,0.65); font-size: 8pt;")
            _uid_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            db_form.addRow("DB UID:", _uid_lbl)

        db_box.layout().addLayout(db_form)
        root.addWidget(db_box)

        root.addStretch(1)

    @staticmethod
    def _section(title: str) -> QFrame:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        box.setStyleSheet(
            "QFrame { background: #F8FAFC; border: 1px solid rgba(0,0,0,0.08);"
            " border-radius: 12px; }"
        )
        l = QVBoxLayout(box)
        l.setContentsMargins(16, 12, 16, 12)
        l.setSpacing(4)
        lbl = QLabel(f"<b>{title}</b>")
        l.addWidget(lbl)
        return box

    def _apply_lang(self) -> None:
        disp = self._lang_combo.currentText()
        code = display_to_lang(disp)
        set_lang(code)  # triggers all bind() observers automatically
