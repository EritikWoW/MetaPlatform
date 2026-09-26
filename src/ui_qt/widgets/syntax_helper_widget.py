from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QLabel,
)

from src.ui_qt.i18n import t


@dataclass(frozen=True)
class HelpTopic:
    id: str
    title: str
    html: str
    keywords: tuple[str, ...] = ()


def _default_topics() -> List[HelpTopic]:
    # MVP: short, but structured. Can be extended from files later.
    return [
        HelpTopic(
            "intro",
            "MetaScript",
            "<h2>MetaScript</h2><p>MetaScript — BSL-compatible language for MetaPlatform.</p>"
            "<p>Основные конструкции: Процедура/Функція, Якщо/Тоді, Для/Кожного.</p>",
            ("метаскрипт", "bsl", "procedure", "function"),
        ),
        HelpTopic(
            "syntax.proc",
            "Процедура",
            "<h2>Процедура</h2><pre>Процедура Имя()\n\nКінецьПроцедури</pre>",
            ("процедура", "procedure"),
        ),
        HelpTopic(
            "syntax.func",
            "Функція",
            "<h2>Функція</h2><pre>Функція Имя()\n\nПовернути Неопределено;\nКінецьФункції</pre>",
            ("функція", "function", "return"),
        ),
        HelpTopic(
            "syntax.if",
            "Якщо",
            "<h2>Якщо</h2><pre>Якщо Умова Тоді\n\nІнакше\n\nКінецьЯкщо;</pre>",
            ("якщо", "if", "then", "else"),
        ),
    ]


class SyntaxHelperWidget(QWidget):
    """1C-like Syntax helper (MVP).

    - Tab "Contents": hierarchical tree
    - Tab "Index": flat list
    - Tab "Search": keyword search

    This is intentionally lightweight (no WebEngine). It uses QTextBrowser.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SyntaxHelperWidget")

        self._topics = _default_topics()
        self._topics_by_id: Dict[str, HelpTopic] = {t.id: t for t in self._topics}

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)

        # --- Contents tab ---
        w_contents = QWidget(self)
        lc = QVBoxLayout(w_contents)
        lc.setContentsMargins(0, 0, 0, 0)
        lc.setSpacing(6)

        self.contents_tree = QTreeWidget(w_contents)
        self.contents_tree.setHeaderHidden(True)
        lc.addWidget(self.contents_tree, 1)

        self._build_contents_tree()
        self.contents_tree.currentItemChanged.connect(self._on_tree_select)

        self.tabs.addTab(w_contents, t("syntax_tab_contents"))

        # --- Index tab ---
        w_index = QWidget(self)
        li = QVBoxLayout(w_index)
        li.setContentsMargins(0, 0, 0, 0)
        li.setSpacing(6)

        self.index_list = QListWidget(w_index)
        li.addWidget(self.index_list, 1)
        for tp in self._topics:
            it = QListWidgetItem(tp.title)
            it.setData(Qt.ItemDataRole.UserRole, tp.id)
            self.index_list.addItem(it)
        self.index_list.currentItemChanged.connect(self._on_index_select)

        self.tabs.addTab(w_index, t("syntax_tab_index"))

        # --- Search tab ---
        w_search = QWidget(self)
        ls = QVBoxLayout(w_search)
        ls.setContentsMargins(0, 0, 0, 0)
        ls.setSpacing(6)

        top = QHBoxLayout()
        self.ed_search = QLineEdit(w_search)
        self.ed_search.setPlaceholderText(t("ph_search"))
        self.btn_search = QPushButton(t("btn_search"), w_search)
        top.addWidget(self.ed_search, 1)
        top.addWidget(self.btn_search)
        ls.addLayout(top)

        self.search_results = QListWidget(w_search)
        ls.addWidget(self.search_results, 1)

        self.btn_search.clicked.connect(self._do_search)
        self.ed_search.returnPressed.connect(self._do_search)
        self.search_results.currentItemChanged.connect(self._on_search_select)

        self.tabs.addTab(w_search, t("syntax_tab_search"))

        # --- Viewer ---
        self.viewer = QTextBrowser(self)
        self.viewer.setOpenExternalLinks(True)
        root.addWidget(self.viewer, 2)

        # default topic
        self.open_topic("intro")

    def _build_contents_tree(self) -> None:
        self.contents_tree.clear()
        root = QTreeWidgetItem([t("syntax_root")])
        root.setData(0, Qt.ItemDataRole.UserRole, "intro")

        synt = QTreeWidgetItem([t("syntax_group_syntax")])
        root.addChild(synt)

        for tid in ("syntax.proc", "syntax.func", "syntax.if"):
            tp = self._topics_by_id.get(tid)
            if not tp:
                continue
            it = QTreeWidgetItem([tp.title])
            it.setData(0, Qt.ItemDataRole.UserRole, tp.id)
            synt.addChild(it)

        self.contents_tree.addTopLevelItem(root)
        self.contents_tree.expandAll()
        self.contents_tree.setCurrentItem(root)

    def open_topic(self, topic_id: str) -> None:
        tp = self._topics_by_id.get(str(topic_id))
        if not tp:
            return
        self.viewer.setHtml(tp.html)

    def _on_tree_select(self, cur, _prev) -> None:
        if cur is None:
            return
        tid = str(cur.data(0, Qt.ItemDataRole.UserRole) or "")
        if tid:
            self.open_topic(tid)

    def _on_index_select(self, cur, _prev) -> None:
        if cur is None:
            return
        tid = str(cur.data(Qt.ItemDataRole.UserRole) or "")
        if tid:
            self.open_topic(tid)

    def _do_search(self) -> None:
        q = str(self.ed_search.text() or "").strip().lower()
        self.search_results.clear()
        if not q:
            return
        for tp in self._topics:
            text = (tp.title + " " + " ".join(tp.keywords)).lower()
            if q in text:
                it = QListWidgetItem(tp.title)
                it.setData(Qt.ItemDataRole.UserRole, tp.id)
                self.search_results.addItem(it)
        if self.search_results.count() > 0:
            self.search_results.setCurrentRow(0)

    def _on_search_select(self, cur, _prev) -> None:
        if cur is None:
            return
        tid = str(cur.data(Qt.ItemDataRole.UserRole) or "")
        if tid:
            self.open_topic(tid)
