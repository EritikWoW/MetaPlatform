from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
    QPushButton,
    QGroupBox,
    QGridLayout,
)

from src.ui_qt.i18n import t


@dataclass(frozen=True)
class MetadataSearchOptions:
    in_names: bool = True
    in_synonyms: bool = True
    in_comments: bool = True
    match_case: bool = False
    whole_word: bool = False


class MetadataSearchDialog(QDialog):
    """1C-like "Metadata objects search" dialog.

    Callback signature:
        on_search(text: str, opts: MetadataSearchOptions) -> None

    The window itself is "thin" — all actual navigation/search lives in the caller.
    """

    def __init__(self, parent=None, *, on_search: Callable[[str, MetadataSearchOptions], None]):
        super().__init__(parent)
        self.setWindowTitle(t("dlg_meta_search_title"))
        self.setModal(True)
        self.resize(520, 210)

        self._on_search = on_search

        root = QVBoxLayout(self)

        # Row: text + button
        row = QHBoxLayout()
        row.addWidget(QLabel(t("lbl_find"), self))
        self.ed = QLineEdit(self)
        self.ed.setPlaceholderText(t("ph_search"))
        row.addWidget(self.ed, 1)
        self.btn_search = QPushButton(t("btn_search"), self)
        row.addWidget(self.btn_search)
        root.addLayout(row)

        # Options
        gb = QGroupBox(t("lbl_search_area"), self)
        g = QGridLayout(gb)
        self.cb_names = QCheckBox(t("search_in_names"), gb)
        self.cb_syn = QCheckBox(t("search_in_synonyms"), gb)
        self.cb_cmt = QCheckBox(t("search_in_comments"), gb)
        self.cb_names.setChecked(True)
        self.cb_syn.setChecked(True)
        self.cb_cmt.setChecked(True)

        self.cb_case = QCheckBox(t("search_match_case"), gb)
        self.cb_word = QCheckBox(t("search_whole_word"), gb)

        g.addWidget(self.cb_names, 0, 0)
        g.addWidget(self.cb_syn, 1, 0)
        g.addWidget(self.cb_cmt, 2, 0)
        g.addWidget(self.cb_case, 0, 1)
        g.addWidget(self.cb_word, 1, 1)

        root.addWidget(gb)

        # Bottom buttons
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_close = QPushButton(t("btn_close"), self)
        bottom.addWidget(self.btn_close)
        root.addLayout(bottom)

        self.btn_search.clicked.connect(self._fire_search)
        self.ed.returnPressed.connect(self._fire_search)
        self.btn_close.clicked.connect(self.accept)

    def _opts(self) -> MetadataSearchOptions:
        return MetadataSearchOptions(
            in_names=self.cb_names.isChecked(),
            in_synonyms=self.cb_syn.isChecked(),
            in_comments=self.cb_cmt.isChecked(),
            match_case=self.cb_case.isChecked(),
            whole_word=self.cb_word.isChecked(),
        )

    def _fire_search(self) -> None:
        text = str(self.ed.text() or "").strip()
        if not text:
            return
        try:
            self._on_search(text, self._opts())
        except Exception:
            pass
