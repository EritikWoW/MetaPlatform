from __future__ import annotations
from __future__ import annotations

import sys
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QMessageBox, QComboBox,
    QTableView, QAbstractItemView, QHeaderView, QFileDialog, QInputDialog,
)

from src.ui_qt.i18n import (
    init_i18n, t, get_lang, set_lang,
    all_lang_displays, lang_to_display, display_to_lang, bind,
)

from src.platform.db_catalog import load_catalog, save_catalog, add_entry, remove_entry_by_path, DbEntry
from src.platform.paths import DB_EXT

from .models import DbTableModel
from .row_delegate import WholeRowHoverDelegate
from .theme import apply_dark_theme, set_app_icon

import json
from datetime import datetime


def _file_exists(p: str) -> bool:
    return Path(p).exists()


def _assets_icon_dir() -> Path:
    # ui_qt/launcher_window.py -> parents[2] = .../src
    return Path(__file__).resolve().parents[2] / "src" / "assets" / "icon"


class HoverTableView(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hovered_row: int = -1
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)  # ВАЖНО

    def mouseMoveEvent(self, event):
        idx = self.indexAt(event.pos())
        new_row = idx.row() if idx.isValid() else -1
        if new_row != self.hovered_row:
            self.hovered_row = new_row
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self.hovered_row != -1:
            self.hovered_row = -1
            self.viewport().update()
        super().leaveEvent(event)


class LauncherWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        app = self._app()
        apply_dark_theme(app)
        set_app_icon(app)

        init_i18n(default_lang="uk")

        self.dbs: list[DbEntry] = load_catalog()
        self.filtered: list[DbEntry] = []
        self.statuses: list[str] = []

        self.setWindowTitle(t("launcher_title"))
        self.resize(760, 420)
        self.setMinimumSize(720, 400)

        root = QWidget(self)
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(10)

        # -------- Header --------
        header = QHBoxLayout()
        self.lbl_subtitle = QLabel()
        self.lbl_subtitle.setStyleSheet("color: #9AA4B2;")
        header.addWidget(self.lbl_subtitle, 1, Qt.AlignLeft | Qt.AlignVCenter)
        outer.addLayout(header)

        # -------- Top row: title + search + language (right) --------
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.lbl_list = QLabel()
        self.lbl_list.setStyleSheet("font-size: 11pt; font-weight: 600;")
        row.addWidget(self.lbl_list, 0)

        self.search = QLineEdit()
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search, 1)  # растягивается

        self.lbl_lang = QLabel()
        self.lbl_lang.setStyleSheet("color: #9AA4B2;")
        row.addWidget(self.lbl_lang, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.lang_box = QComboBox()
        self.lang_box.setCursor(Qt.PointingHandCursor)
        self.lang_box.setIconSize(QSize(18, 18))
        self.lang_box.setFixedWidth(80)
        self.lang_box.currentTextChanged.connect(self._on_lang_changed)

        displays = all_lang_displays()
        icon_dir = _assets_icon_dir()
        ua_icon = QIcon(str(icon_dir / "flag_ua.png"))
        us_icon = QIcon(str(icon_dir / "flag_us.png"))

        self.lang_box.addItem(ua_icon, displays[0])
        self.lang_box.addItem(us_icon, displays[1])

        current_display = lang_to_display(get_lang())
        idx = self.lang_box.findText(current_display)
        self.lang_box.setCurrentIndex(idx if idx >= 0 else 0)

        row.addWidget(self.lang_box, 0, Qt.AlignRight | Qt.AlignVCenter)
        outer.addLayout(row)

        # -------- Main split: table + buttons --------
        main = QHBoxLayout()
        outer.addLayout(main, 1)

        # TABLE (как ты и хотел)
        self.table = HoverTableView()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(False)

        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)

        # чтобы не было "рамки/фокуса" на ячейке
        self.table.setFocusPolicy(Qt.NoFocus)

        # делегат, который рисует hover всей строки
        self.table.setItemDelegate(WholeRowHoverDelegate(self.table))

        # Убираем сетку = нет линий между ячейками/колонками
        self.table.setShowGrid(False)

        # Чтобы строки не "вылезали" и не было горизонтального скролла
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)

        # Вертикальный header не нужен
        self.table.verticalHeader().setVisible(False)

        # Модель
        self.model = DbTableModel([], [])
        self.table.setModel(self.model)

        # Делегат: hover всей строки
        self.table.setItemDelegate(WholeRowHoverDelegate(self.table))

        # Header поведения и ширины
        h = self.table.horizontalHeader()
        h.setHighlightSections(False)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setStretchLastSection(False)

        # В PySide6 ResizeMode лежит в QHeaderView.ResizeMode
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)

        h.resizeSection(0, 180)
        h.resizeSection(2, 90)

        # Стили: без бордеров на item и header, selection на всю строку
        self.table.setStyleSheet("""
        QTableView {
            background: #0F172A;
            color: #E7EAF0;
            border: none;
            outline: 0;
            selection-background-color: #5B5BD6;
            selection-color: white;
        }

        QTableView::item {
            border: none;            /* убирает разделение ячеек */
            padding: 6px 10px;
        }

        QHeaderView::section {
            background: #111C33;
            color: #E7EAF0;
            border: none;            /* убирает разделители в header */
            padding: 8px 10px;
            font-weight: 600;
        }

        QHeaderView {
            border: none;
        }
        """)

        sm = self.table.selectionModel()
        if sm is not None:
            sm.selectionChanged.connect(lambda *_: self.on_select())


        main.addWidget(self.table, 1)

        # Buttons
        right = QVBoxLayout()
        right.setSpacing(10)

        self.btn_client = QPushButton()
        self.btn_client.clicked.connect(self.run_client)
        right.addWidget(self.btn_client)

        self.btn_config = QPushButton()
        self.btn_config.clicked.connect(self.run_configurator)
        right.addWidget(self.btn_config)

        right.addStretch(1)

        self.btn_add = QPushButton()
        self.btn_add.clicked.connect(self.add_db)
        right.addWidget(self.btn_add)

        self.btn_remove = QPushButton()
        self.btn_remove.clicked.connect(self.remove_db)
        right.addWidget(self.btn_remove)

        self.btn_open = QPushButton()
        self.btn_open.clicked.connect(self.open_folder)
        right.addWidget(self.btn_open)

        main.addLayout(right)

        # -------- Bottom status --------
        self.lbl_status = QLabel()
        self.lbl_status.setStyleSheet("color: #9AA4B2;")
        outer.addWidget(self.lbl_status)

        bind(self.apply_i18n, widget=self)
        self.apply_i18n()
        self.refresh()

    def add_db(self) -> None:
        # 1) спросим: подключить существующую или создать новую
        res = QMessageBox.question(
            self,
            t("dlg_add_title"),
            t("dlg_add_question"),
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if res == QMessageBox.Cancel:
            return

        # 2) спросим имя в списке
        name, ok = QInputDialog.getText(self, t("dlg_db_name_title"), t("dlg_db_name_prompt"))
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return

        # 3) выберем путь
        db_file: Path | None = None

        if res == QMessageBox.Yes:
            # Подключить существующую
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                t("dlg_pick_db"),
                str(Path.home()),
                f"MetaPlatform DB (*{DB_EXT});;All files (*.*)",
            )
            if not file_path:
                return
            db_file = Path(file_path).resolve()

        else:
            # Создать новую: выбрать папку -> создать MetaDB/database.mpdb
            folder = QFileDialog.getExistingDirectory(self, t("dlg_create_db"), str(Path.home()))
            if not folder:
                return
            base_dir = Path(folder).resolve()
            try:
                db_file = self.create_metadb_folder(base_dir, db_name=name)
            except FileExistsError:
                QMessageBox.warning(self, t("dlg_add_title"), "MetaDB already exists in выбранной папке.")
                return
            except Exception as e:
                QMessageBox.critical(self, t("dlg_add_title"), f"Ошибка создания БД:\n{e}")
                return

        # 4) обновим каталог
        entry = DbEntry(name=name, path=str(db_file))
        self.dbs = add_entry(self.dbs, entry)
        try:
            save_catalog(self.dbs)
        except Exception as e:
            QMessageBox.critical(self, t("dlg_add_title"), f"Не удалось сохранить каталог:\n{e}")
            return

        # 5) обновим UI, выделим добавленную строку
        self.refresh()
        self._select_db_by_path(str(db_file))
        self.lbl_status.setText(t("status_added", name=name))

    def remove_db(self) -> None:
        db = self.current_db()
        if not db:
            QMessageBox.information(self, t("dlg_remove_title"), t("dlg_remove_pick"))
            return

        confirm = QMessageBox.question(
            self,
            t("dlg_remove_confirm_title"),
            t("dlg_remove_confirm_text", name=db.name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self.dbs = remove_entry_by_path(self.dbs, db.path)
        try:
            save_catalog(self.dbs)
        except Exception as e:
            QMessageBox.critical(self, t("dlg_remove_title"), f"Не удалось сохранить каталог:\n{e}")
            return

        self.refresh()
        self.lbl_status.setText(t("status_removed", name=db.name))

    def _select_db_by_path(self, path: str) -> None:
        # Ищем строку в self.filtered, выделяем её
        norm = str(Path(path).resolve()).lower()
        for i, x in enumerate(self.filtered):
            if str(Path(x.path).resolve()).lower() == norm:
                idx = self.model.index(i, 0)
                if idx.isValid():
                    self.table.scrollTo(idx)
                    self.table.selectRow(i)
                break

    # ---------------- i18n ----------------
    def _on_lang_changed(self, display_text: str) -> None:
        set_lang(display_to_lang(display_text))

    def apply_i18n(self) -> None:
        self.setWindowTitle(t("launcher_title"))

        self.lbl_subtitle.setText(t("launcher_subtitle"))
        self.lbl_list.setText(t("list_label"))
        self.lbl_lang.setText(t("lbl_language"))
        self.search.setPlaceholderText(t("ph_search"))

        # Заголовки таблицы (если хочешь i18n headers)
        self.model.set_headers([t("col_name"), t("col_path"), t("col_status")])

        h = self.table.horizontalHeader()

        # по умолчанию пусть будет слева
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # а "Статус" — по центру (index 2)
        h.model().setHeaderData(2, Qt.Horizontal, int(Qt.AlignCenter), Qt.TextAlignmentRole)

        self.btn_client.setText(t("btn_client"))
        self.btn_config.setText(t("btn_config"))
        self.btn_add.setText(t("btn_add"))
        self.btn_remove.setText(t("btn_remove"))
        self.btn_open.setText(t("btn_open_folder"))

        self.refresh()

    # ---------------- Qt helpers ----------------
    def _app(self):
        from PySide6.QtWidgets import QApplication
        return QApplication.instance()

    # ---------------- Data ----------------
    def refresh(self) -> None:
        q = (self.search.text() or "").strip().lower()
        all_dbs = list(self.dbs)

        if q:
            all_dbs = [x for x in all_dbs if q in x.name.lower() or q in x.path.lower()]

        self.filtered = all_dbs
        self.statuses = [t("status_ok") if _file_exists(x.path) else t("status_no_file") for x in self.filtered]

        self.model.set_data(self.filtered, self.statuses)

        self.lbl_status.setText(t("count_line", total=len(self.dbs), shown=len(self.filtered)))
        self.sync_buttons()

    def current_db(self) -> DbEntry | None:
        sm = self.table.selectionModel()
        if sm is None:
            return None
        idxs = sm.selectedRows()
        if not idxs:
            return None
        row = idxs[0].row()
        if 0 <= row < len(self.filtered):
            return self.filtered[row]
        return None

    def on_select(self) -> None:
        self.sync_buttons()

    def sync_buttons(self) -> None:
        db = self.current_db()
        enabled = bool(db and _file_exists(db.path))
        self.btn_client.setEnabled(enabled)
        self.btn_config.setEnabled(enabled)
        self.btn_open.setEnabled(bool(db))

    # ---------------- Actions ----------------
    def open_folder(self) -> None:
        db = self.current_db()
        if not db:
            QMessageBox.information(self, t("dlg_open_title"), t("dlg_open_pick"))
            return
        p = Path(db.path)
        if p.exists():
            subprocess.Popen(["explorer", str(p.parent)])
        else:
            QMessageBox.warning(self, t("dlg_open_title"), t("dlg_open_missing"))

    def _spawn_module(self, module: str, db_path: str) -> None:
        project_root = Path(__file__).resolve().parents[2]
        cmd = [sys.executable, "-m", module, "--db", db_path]
        subprocess.Popen(cmd, cwd=str(project_root))

    def run_client(self) -> None:
        db = self.current_db()
        if not db:
            QMessageBox.information(self, t("dlg_client_title"), t("dlg_pick_db_first"))
            return
        if not _file_exists(db.path):
            QMessageBox.warning(self, t("dlg_client_title"), t("dlg_bad_db_file"))
            return
        self._spawn_module("src.configurator.configurator_app", db.path)

    def run_configurator(self) -> None:
        db = self.current_db()
        if not db:
            QMessageBox.information(self, t("dlg_config_title"), t("dlg_pick_db_first"))
            return
        if not _file_exists(db.path):
            QMessageBox.warning(self, t("dlg_config_title"), t("dlg_bad_db_file"))
            return
        self._spawn_module("src.configurator.configurator_app", db.path)

    # Заглушки
    def add_db_stub(self):
        QMessageBox.information(self, t("dlg_add_title"), f"{t('btn_add')}: {t('status_ready')} ({DB_EXT})")

    def remove_db_stub(self):
        QMessageBox.information(self, t("dlg_remove_title"), f"{t('btn_remove')}: {t('status_ready')}")


    @staticmethod
    def create_metadb_folder(base_dir: Path, *, db_name: str) -> Path:
        metadb_dir = base_dir / "MetaDB"
        logs_dir = metadb_dir / "logs"
        tmp_dir = metadb_dir / "tmp"
        wal_dir = metadb_dir / "wal"

        metadb_dir.mkdir(parents=True, exist_ok=False)
        logs_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        wal_dir.mkdir(parents=True, exist_ok=True)

        db_path = metadb_dir / "database.mpdb"
        wal_path = wal_dir / "database.wal"

        # TODO: тут позже подключим реальный mpdb-движок.
        # Пока создаём файл, чтобы он существовал.
        db_path.write_bytes(b"")

        meta = {
            "name": db_name,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "db_file": str(db_path),
            "wal_file": str(wal_path),
        }
        (metadb_dir / "db.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return db_path
