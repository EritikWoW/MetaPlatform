from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QDialogButtonBox,
)

from src.ui_qt.i18n import t


@dataclass(frozen=True)
class CodeTemplate:
    id: str
    title_key: str
    text: str


_DEFAULT_TEMPLATES: list[CodeTemplate] = [
    CodeTemplate(
        "proc",
        "tmpl_proc",
        "Процедура ИмяПроцедуры()\n\nКінецьПроцедури\n",
    ),
    CodeTemplate(
        "func",
        "tmpl_func",
        "Функція ИмяФункції()\n\nПовернути Неопределено;\nКінецьФункції\n",
    ),
    CodeTemplate(
        "if",
        "tmpl_if",
        "Якщо Умова Тоді\n\nКінецьЯкщо;\n",
    ),
    CodeTemplate(
        "foreach",
        "tmpl_foreach",
        "Для Кожного Елемент Із Колекція Цикл\n\nКінецьЦиклу;\n",
    ),
]


class CodeTemplatesDialog(QDialog):
    """Simple "Text templates" window.

    insert_fn(text) is called when user clicks Insert.
    """

    def __init__(self, parent=None, *, insert_fn: Callable[[str], None], templates: Optional[list[CodeTemplate]] = None):
        super().__init__(parent)
        self.setWindowTitle(t("dlg_templates_title"))
        self.setModal(True)
        self.resize(680, 420)

        self._insert_fn = insert_fn
        self._templates = templates or _DEFAULT_TEMPLATES

        root = QHBoxLayout(self)

        self.list = QListWidget(self)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        root.addWidget(self.list, 1)

        right = QVBoxLayout()
        self.preview = QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        right.addWidget(self.preview, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(t("btn_insert"))
        bb.accepted.connect(self._on_insert)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)

        root.addLayout(right, 2)

        for tpl in self._templates:
            it = QListWidgetItem(t(tpl.title_key))
            it.setData(Qt.ItemDataRole.UserRole, tpl.id)
            self.list.addItem(it)

        if self.list.count() > 0:
            self.list.setCurrentRow(0)
            self._update_preview()

        self.list.currentRowChanged.connect(lambda _i: self._update_preview())
        self.list.itemDoubleClicked.connect(lambda _it: self._on_insert())

    def _current_template(self) -> Optional[CodeTemplate]:
        it = self.list.currentItem()
        if it is None:
            return None
        tid = str(it.data(Qt.ItemDataRole.UserRole) or "")
        for tpl in self._templates:
            if tpl.id == tid:
                return tpl
        return None

    def _update_preview(self) -> None:
        tpl = self._current_template()
        self.preview.setPlainText(tpl.text if tpl else "")

    def _on_insert(self) -> None:
        tpl = self._current_template()
        if tpl is None:
            return
        try:
            self._insert_fn(tpl.text)
        except Exception:
            pass
        self.accept()
