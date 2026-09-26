from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QScrollArea,
    QLabel,
    QFrame,
    QPushButton,
)

from src.ui_qt.i18n import bind, t


@dataclass(frozen=True, slots=True)
class EditorSection:
    """UI section for a metadata-object editor.

    Notes:
        This registry is intentionally UI-only (unlike core.object_policies.SECTIONS).
        The goal is a universal shell (1C-like) where a left navigation list is
        dynamically built per object type, while the actual widgets are provided
        by a concrete editor (Catalog, Document, etc.).
    """

    key: str
    title_i18n: str
    build: Callable[[], QWidget]
    icon_key: str = ""


class MetaObjectEditorShell(QWidget):
    """Universal shell for metadata object editors.

    Responsibilities:
        - Provide a consistent layout (left sections list + stacked pages).
        - Provide a single sidebar for section switching.
        - Provide common bottom actions (Back/Next/Close/Help) for future parity.
        - Keep the editor widgets focused on business/UI logic.
    """

    applyRequested = Signal(dict)  # payload patch
    generateRequested = Signal()
    closeRequested = Signal()

    def __init__(self, title: str = ""):
        super().__init__()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        self._title_lbl = QLabel(title)
        self._title_lbl.setObjectName("metaObjectEditorTitle")
        header.addWidget(self._title_lbl, 1)
        self._btn_generate = QPushButton(t("btn_generate"))
        self._btn_generate.setObjectName("btnGenerate")
        self._btn_generate.clicked.connect(self.generateRequested.emit)
        header.addWidget(self._btn_generate, 0)


        self._btn_apply = QPushButton(t("btn_apply"))
        self._btn_apply.setObjectName("btnApply")
        self._btn_apply.clicked.connect(self._on_apply_clicked)
        header.addWidget(self._btn_apply, 0)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(12)

        self._sections = QListWidget()
        self._sections.setObjectName("metaObjectSections")
        self._sections.setFixedWidth(230)
        self._sections.currentRowChanged.connect(self._on_section_changed)
        body.addWidget(self._sections, 0)

        self._stack = QStackedWidget()
        self._stack.setObjectName("metaObjectPages")
        center = QVBoxLayout()
        center.setSpacing(8)

        center.addWidget(self._stack, 1)

        center_wrap = QWidget()
        center_wrap.setLayout(center)
        body.addWidget(center_wrap, 1)

        root.addLayout(body, 1)

        # Bottom bar (future parity with 1C-like wizard navigation)
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addStretch(1)

        self._btn_back = QPushButton(t("btn_back"))
        self._btn_next = QPushButton(t("btn_next"))
        self._btn_close = QPushButton(t("btn_close"))
        self._btn_help = QPushButton(t("btn_help"))

        self._btn_back.clicked.connect(lambda: self.set_current_index(self.current_index() - 1))
        self._btn_next.clicked.connect(lambda: self.set_current_index(self.current_index() + 1))
        self._btn_close.clicked.connect(self.closeRequested.emit)

        bottom.addWidget(self._btn_back)
        bottom.addWidget(self._btn_next)
        bottom.addWidget(self._btn_close)
        bottom.addWidget(self._btn_help)

        root.addLayout(bottom)

        self._sections_def: list[EditorSection] = []
        self._pending_patch: dict = {}
        bind(self._retranslate_ui, self)

    def set_title(self, title: str) -> None:
        self._title_lbl.setText(str(title or ""))

    def title_text(self) -> str:
        """Return current header title text."""

        return str(self._title_lbl.text() or "").strip()

    def set_sections(self, sections: list[EditorSection]) -> None:
        """Rebuild navigation and pages."""

        self._sections_def = list(sections or [])
        self._sections.clear()
        while self._stack.count():
            w = self._stack.widget(0)
            self._stack.removeWidget(w)
            w.deleteLater()

        for sec in self._sections_def:
            item = QListWidgetItem(t(sec.title_i18n))
            item.setSizeHint(QSize(0, max(28, self._sections.fontMetrics().height() + 12)))
            item.setData(Qt.ItemDataRole.UserRole, sec.key)
            self._sections.addItem(item)
            self._stack.addWidget(self._wrap_section_page(sec.build()))

        if self._sections.count():
            self._sections.setCurrentRow(0)
            self._notify_section_visible(0)

        self._sync_nav_buttons()

    def _wrap_section_page(self, page: QWidget) -> QWidget:
        """Wrap section pages in a vertical scroll area for 1C-like right panel UX."""

        if isinstance(page, QScrollArea):
            return page
        scroll = QScrollArea()
        scroll.setObjectName("metaObjectPageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

    def _retranslate_ui(self) -> None:
        self._btn_generate.setText(t("btn_generate"))
        self._btn_apply.setText(t("btn_apply"))
        self._btn_back.setText(t("btn_back"))
        self._btn_next.setText(t("btn_next"))
        self._btn_close.setText(t("btn_close"))
        self._btn_help.setText(t("btn_help"))
        for i, sec in enumerate(self._sections_def):
            item = self._sections.item(i)
            if item is not None:
                item.setText(t(sec.title_i18n))

    def current_index(self) -> int:
        return int(self._stack.currentIndex())

    def set_current_index(self, index: int) -> None:
        if self._stack.count() <= 0:
            return
        idx = max(0, min(int(index), self._stack.count() - 1))
        was_blocked = self._sections.blockSignals(True)
        try:
            self._sections.setCurrentRow(idx)
        finally:
            self._sections.blockSignals(was_blocked)
        self._on_section_changed(idx)

    def set_current_section(self, key: str) -> None:
        """Select a section by its logical key.

        Used by tree navigation (virtual schema nodes and system folders).
        """

        k = str(key or "").strip()
        if not k:
            return
        for i in range(self._sections.count()):
            it = self._sections.item(i)
            if it is None:
                continue
            if str(it.data(Qt.ItemDataRole.UserRole) or "") == k:
                self.set_current_index(i)
                return

    def set_pending_patch(self, patch: dict) -> None:
        """Accumulate a payload patch to be emitted via Apply."""

        if not isinstance(patch, dict) or not patch:
            return
        self._pending_patch.update(patch)

    def clear_pending_patch(self) -> None:
        self._pending_patch = {}

    def pending_patch(self) -> dict:
        return dict(self._pending_patch)

    def _on_section_changed(self, row: int) -> None:
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)
            self._notify_section_visible(row)
        self._sync_nav_buttons()

    def _notify_section_visible(self, row: int) -> None:
        if row < 0 or row >= self._stack.count():
            return
        page = self._stack.widget(row)
        if page is None:
            return
        inner = page.widget() if isinstance(page, QScrollArea) else page
        if inner is None:
            return
        if bool(getattr(inner, "_mp_section_loaded", False)):
            return
        callback = getattr(inner, "_on_section_shown", None)
        if not callable(callback):
            return
        try:
            callback()
        except Exception:
            return
        try:
            setattr(inner, "_mp_section_loaded", True)
        except Exception:
            pass

    def _sync_nav_buttons(self) -> None:
        total = self._stack.count()
        idx = self._stack.currentIndex() if total else 0
        self._btn_back.setEnabled(total > 0 and idx > 0)
        self._btn_next.setEnabled(total > 0 and idx < total - 1)

    def _on_apply_clicked(self) -> None:
        patch = dict(self._pending_patch)
        self.applyRequested.emit(patch)
