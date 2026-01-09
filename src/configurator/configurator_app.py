from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit,
    QSplitter, QTreeView, QTabWidget,
    QTableWidget, QTableWidgetItem,
    QHeaderView,
)

from src.ui_qt.theme import apply_dark_theme, set_app_icon
from src.ui_qt.i18n import init_i18n, t


@dataclass(frozen=True)
class NodeInfo:
    kind: str   # root/group/object
    name: str


class ConfiguratorWindow(QMainWindow):
    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self.db_path = db_path

        self.setWindowTitle(f"{t('launcher_title')} — {t('btn_config')}")
        self.resize(1200, 720)
        self.setMinimumSize(980, 620)

        self._node_meta: dict[str, NodeInfo] = {}
        self._open_tabs: dict[str, int] = {}  # key -> tab index

        root = QWidget()
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(10)

        # ---------- Top toolbar ----------
        top = QHBoxLayout()
        outer.addLayout(top)

        left_title = QVBoxLayout()
        top.addLayout(left_title, 1)

        self.lbl_title = QLabel("Configurator")
        self.lbl_title.setStyleSheet("font-size: 12pt; font-weight: 650;")
        left_title.addWidget(self.lbl_title)

        self.lbl_db = QLabel(str(self.db_path))
        self.lbl_db.setStyleSheet("color: #9AA4B2;")
        left_title.addWidget(self.lbl_db)

        actions = QHBoxLayout()
        top.addLayout(actions, 0)

        self.btn_save = QPushButton("Сохранить")
        self.btn_save.clicked.connect(self._stub_save)
        actions.addWidget(self.btn_save)

        self.btn_refresh = QPushButton("Обновить")
        self.btn_refresh.clicked.connect(self._stub_refresh)
        actions.addWidget(self.btn_refresh)

        self.btn_check = QPushButton("Проверка")
        self.btn_check.clicked.connect(self._stub_check)
        actions.addWidget(self.btn_check)

        # ---------- Main splitter ----------
        main = QSplitter(Qt.Horizontal)
        outer.addWidget(main, 1)

        # Left panel (tree + search)
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(8)

        self.lbl_cfg = QLabel("Конфигурация")
        self.lbl_cfg.setStyleSheet("font-weight: 650;")
        left_l.addWidget(self.lbl_cfg)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск...")
        self.search.textChanged.connect(self._filter_tree)
        left_l.addWidget(self.search)

        self.tree = QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QTreeView.NoEditTriggers)
        self.tree.doubleClicked.connect(self._on_tree_open)
        self.tree.clicked.connect(self._on_tree_select)
        left_l.addWidget(self.tree, 1)

        self.tree_model = QStandardItemModel()
        self.tree.setModel(self.tree_model)

        # Right panel (tabs + props)
        right = QSplitter(Qt.Horizontal)
        right.setChildrenCollapsible(False)

        # Workspace tabs
        work = QWidget()
        work_l = QVBoxLayout(work)
        work_l.setContentsMargins(0, 0, 0, 0)
        work_l.setSpacing(8)

        self.tabs = QTabWidget()
        work_l.addWidget(self.tabs, 1)

        home = QWidget()
        home_l = QVBoxLayout(home)
        home_l.setContentsMargins(16, 16, 16, 16)
        home_l.setSpacing(6)

        h1 = QLabel("MetaPlatform Configurator")
        h1.setStyleSheet("font-size: 14pt; font-weight: 700;")
        home_l.addWidget(h1)

        h2 = QLabel("Откройте объект из дерева слева двойным кликом.")
        h2.setStyleSheet("color: #9AA4B2;")
        home_l.addWidget(h2)

        self.tabs.addTab(home, "Рабочая область")

        # Properties
        props = QWidget()
        props_l = QVBoxLayout(props)
        props_l.setContentsMargins(0, 0, 0, 0)
        props_l.setSpacing(8)

        lbl_props = QLabel("Свойства")
        lbl_props.setStyleSheet("font-weight: 650;")
        props_l.addWidget(lbl_props)

        self.props_tbl = QTableWidget(0, 2)
        self.props_tbl.setHorizontalHeaderLabels(["Параметр", "Значение"])
        self.props_tbl.verticalHeader().setVisible(False)
        self.props_tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.props_tbl.setSelectionMode(QTableWidget.NoSelection)
        self.props_tbl.horizontalHeader().setStretchLastSection(True)
        self.props_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.props_tbl.setColumnWidth(0, 160)
        props_l.addWidget(self.props_tbl, 1)

        right.addWidget(work)
        right.addWidget(props)
        right.setSizes([820, 320])

        main.addWidget(left)
        main.addWidget(right)
        main.setSizes([340, 860])

        # ---------- Bottom status ----------
        self.status = QLabel("Готово")
        self.status.setStyleSheet("color: #9AA4B2;")
        outer.addWidget(self.status)

        self._populate_tree()
        self._set_status(f"Открыта БД: {self.db_path}")

    # ---------------- Tree ----------------
    def _populate_tree(self) -> None:
        self.tree_model.clear()
        self._node_meta.clear()

        root_item = QStandardItem(self.db_path.stem)
        root_item.setData("root", Qt.UserRole + 1)
        self.tree_model.appendRow(root_item)

        groups = [
            ("Общее", ["Параметры", "Роли", "Языки"]),
            ("Справочники", ["Контрагенты", "Номенклатура", "Склады"]),
            ("Документы", ["Поступление", "Реализация", "Перемещение"]),
            ("Отчеты", ["Продажи", "Остатки"]),
            ("Регистры", ["Накопления", "Сведений"]),
            ("Сервис", ["Обновление", "Проверка"]),
        ]

        for gname, children in groups:
            g = QStandardItem(gname)
            g.setData("group", Qt.UserRole + 1)
            root_item.appendRow(g)

            for cname in children:
                c = QStandardItem(cname)
                c.setData("object", Qt.UserRole + 1)
                g.appendRow(c)

        self.tree.expand(self.tree_model.indexFromItem(root_item))
        self.tree.setCurrentIndex(self.tree_model.indexFromItem(root_item))
        self._show_properties(NodeInfo("root", self.db_path.stem))

    def _filter_tree(self) -> None:
        q = (self.search.text() or "").strip().lower()
        if not q:
            self._populate_tree()
            return

        self.tree_model.clear()

        root_item = QStandardItem(self.db_path.stem)
        root_item.setData("root", Qt.UserRole + 1)
        self.tree_model.appendRow(root_item)

        groups = [
            ("Общее", ["Параметры", "Роли", "Языки"]),
            ("Справочники", ["Контрагенты", "Номенклатура", "Склады"]),
            ("Документы", ["Поступление", "Реализация", "Перемещение"]),
            ("Отчеты", ["Продажи", "Остатки"]),
            ("Регистры", ["Накопления", "Сведений"]),
            ("Сервис", ["Обновление", "Проверка"]),
        ]

        shown_any = False
        for gname, children in groups:
            matched_children = [c for c in children if q in c.lower() or q in gname.lower()]
            if not matched_children and q not in gname.lower():
                continue

            g = QStandardItem(gname)
            g.setData("group", Qt.UserRole + 1)
            root_item.appendRow(g)

            for cname in matched_children:
                c = QStandardItem(cname)
                c.setData("object", Qt.UserRole + 1)
                g.appendRow(c)
                shown_any = True

        self.tree.expand(self.tree_model.indexFromItem(root_item))
        if not shown_any:
            self._set_status("Ничего не найдено")
        else:
            self._set_status("Фильтр применён")

    def _node_info_from_index(self, idx) -> NodeInfo | None:
        if not idx.isValid():
            return None
        item = self.tree_model.itemFromIndex(idx)
        if item is None:
            return None
        kind = item.data(Qt.UserRole + 1) or "object"
        return NodeInfo(str(kind), item.text())

    def _on_tree_select(self, idx) -> None:
        info = self._node_info_from_index(idx)
        if info:
            self._show_properties(info)

    def _on_tree_open(self, idx) -> None:
        info = self._node_info_from_index(idx)
        if not info or info.kind != "object":
            return
        self._open_object_tab(info)

    # ---------------- Tabs / props ----------------
    def _open_object_tab(self, info: NodeInfo) -> None:
        key = f"{info.kind}:{info.name}"
        if key in self._open_tabs:
            self.tabs.setCurrentIndex(self._open_tabs[key])
            self._set_status(f"Открыто: {info.name}")
            return

        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(16, 16, 16, 16)
        l.setSpacing(6)

        h = QLabel(info.name)
        h.setStyleSheet("font-size: 14pt; font-weight: 700;")
        l.addWidget(h)

        s = QLabel("Редактор (заглушка). Тут будет UI объектов.")
        s.setStyleSheet("color: #9AA4B2;")
        l.addWidget(s)

        tab_index = self.tabs.addTab(page, info.name)
        self.tabs.setCurrentIndex(tab_index)
        self._open_tabs[key] = tab_index
        self._set_status(f"Открыто: {info.name}")

    def _show_properties(self, info: NodeInfo) -> None:
        self.props_tbl.setRowCount(0)

        rows = [
            ("Тип", info.kind),
            ("Имя", info.name),
            ("БД", str(self.db_path)),
        ]

        self.props_tbl.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.props_tbl.setItem(r, 0, QTableWidgetItem(k))
            self.props_tbl.setItem(r, 1, QTableWidgetItem(v))

    # ---------------- Status / stubs ----------------
    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    def _stub_save(self) -> None:
        self._set_status("Сохранение: заглушка (реализацию добавим дальше)")

    def _stub_refresh(self) -> None:
        self._set_status("Обновление: заглушка")
        self._filter_tree()

    def _stub_check(self) -> None:
        self._set_status("Проверка: заглушка")


def run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="Путь к файлу БД (.mpdb)")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    apply_dark_theme(app)
    set_app_icon(app)
    init_i18n(default_lang="uk")

    w = ConfiguratorWindow(Path(args.db).resolve())
    w.show()
    return app.exec()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
