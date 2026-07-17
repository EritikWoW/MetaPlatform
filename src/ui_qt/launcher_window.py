from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QEvent, QRect, Qt, QSize
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QStyledItemDelegate,
    QStyle,
    QVBoxLayout,
    QWidget,
    QInputDialog, QStyleOptionViewItem, QDialog,
)

from PySide6.QtGui import QPainter, QIcon

from src.platform.db_catalog import (
    DbEntry,
    add_entry,
    create_new_metadb_in_directory,
    load_catalog,
    remove_entry_by_path,
    save_catalog,
)
from src.platform.locale_detect import detect_system_lang
from src.platform.logging_setup import get_logger, setup_logging
from src.platform.paths import DB_EXT
from src.runtime.gateway import RuntimeGateway
from src.ui_qt.i18n import (
    all_lang_displays,
    bind,
    display_to_lang,
    get_lang,
    init_i18n,
    lang_to_display,
    set_lang,
    t,
)

from .models import DbListModel
from src.ui_qt.dialogs.add_db_wizard import AddDbWizard
from .theme import apply_dark_theme, set_app_icon


def _file_exists(p: str) -> bool:
    try:
        return Path(p).exists()
    except Exception:
        return False


class _DbRowDelegate(QStyledItemDelegate):
    """Renders DB list rows with a compact status indicator."""

    IND_SIZE = 10
    IND_PAD_R = 12
    KIND_PAD_R = 16
    KIND_PAD_L = 12
    KIND_MIN_W = 56
    KIND_MAX_W = 110

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        painter.save()

        # Base item rendering (selection, background).
        # IMPORTANT: we ask Qt to draw the item chrome (selection/background),
        # but we must prevent it from drawing the text too, otherwise we'll get
        # duplicated text (Qt text + our custom text).
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        display_text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else None
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        # Layout
        rect = opt.rect
        ind = self._indicator_rect(rect)
        entry = index.data(DbListModel.RoleDb)
        name = str(getattr(entry, "name", "") or display_text or "")
        kind = str(getattr(entry, "kind", "") or "")
        kind_text = self._kind_text(kind)

        metrics = painter.fontMetrics()
        kind_w = 0
        kind_rect = QRect()
        if kind_text:
            kind_w = max(self.KIND_MIN_W, metrics.horizontalAdvance(kind_text) + self.KIND_PAD_L)
            kind_w = min(self.KIND_MAX_W, kind_w)
            kind_rect = QRect(
                ind.left() - self.KIND_PAD_R - kind_w,
                rect.top(),
                kind_w,
                rect.height(),
            )

        text_rect = QRect(rect)
        text_rect.setLeft(text_rect.left() + 6)
        text_rect.setRight((kind_rect.left() - 10) if kind_w > 0 else (ind.left() - 8))

        painter.setPen(opt.palette.text().color())
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            metrics.elidedText(name, Qt.TextElideMode.ElideRight, max(24, text_rect.width())),
        )

        if kind_w > 0:
            painter.setPen(opt.palette.windowText().color().lighter(140))
            painter.drawText(
                kind_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                metrics.elidedText(kind_text, Qt.TextElideMode.ElideRight, max(24, kind_rect.width())),
            )

        # Indicator (right)
        code = str(index.data(DbListModel.RoleStatusCode) or "")
        color = None
        if code == "ok":
            color = Qt.GlobalColor.green
        elif code in ("warn", "no_file"):
            color = Qt.GlobalColor.yellow
        elif code == "error":
            color = Qt.GlobalColor.red
        else:
            color = Qt.GlobalColor.gray

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(ind)

        painter.restore()

    def _indicator_rect(self, item_rect: QRect) -> QRect:
        x = item_rect.right() - self.IND_PAD_R - self.IND_SIZE
        y = item_rect.center().y() - (self.IND_SIZE // 2)
        return QRect(x, y, self.IND_SIZE, self.IND_SIZE)

    @staticmethod
    def _kind_text(kind: str) -> str:
        kind_norm = str(kind or "").strip().lower()
        if kind_norm == "local":
            return t("db_kind_local")
        if kind_norm == "remote":
            return t("db_kind_remote")
        return str(kind or "")

    @classmethod
    def indicator_rect_for(cls, item_rect: QRect) -> QRect:
        x = item_rect.right() - cls.IND_PAD_R - cls.IND_SIZE
        y = item_rect.center().y() - (cls.IND_SIZE // 2)
        return QRect(x, y, cls.IND_SIZE, cls.IND_SIZE)


class LauncherWindow(QMainWindow):
    log = get_logger("launcher")

    def __init__(self, debug_ui: bool = False, parent=None):
        super().__init__(parent)
        self._debug_ui = debug_ui

        setup_logging(detect_system_lang())
        init_i18n(default_lang=detect_system_lang())

        app = self._app()
        apply_dark_theme(app)
        set_app_icon(app)

        self.dbs: list[DbEntry] = load_catalog()
        self.filtered: list[DbEntry] = []
        self.status_codes: list[str] = []
        self.status_tips: list[str] = []
        self._last_status_tooltip: str = ""

        self.setWindowTitle(t("launcher_title"))
        self.resize(860, 460)
        self.setMinimumSize(820, 420)

        root = QWidget(self)
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(10)

        # Header
        header = QHBoxLayout()
        self.lbl_subtitle = QLabel()
        self.lbl_subtitle.setStyleSheet("color: #9AA4B2;")
        header.addWidget(self.lbl_subtitle, 1)

        self.cmb_lang = QComboBox()
        self.cmb_lang.setIconSize(QSize(18, 18))
        # Keep language items with flag icons (legacy UX)
        icons_dir = Path(__file__).resolve().parents[2] / "src" / "assets" / "icons"
        flag_ua = icons_dir / "flag_ua.png"
        flag_us = icons_dir / "flag_us.png"
        for disp in all_lang_displays():
            lang = display_to_lang(disp)
            if lang in ("uk", "ua"):
                ic = QIcon(str(flag_ua)) if flag_ua.exists() else QIcon()
            elif lang in ("en",):
                ic = QIcon(str(flag_us)) if flag_us.exists() else QIcon()
            else:
                ic = QIcon()
            self.cmb_lang.addItem(ic, disp)
        self.cmb_lang.currentTextChanged.connect(self._on_lang_changed)
        header.addWidget(self.cmb_lang, 0, Qt.AlignmentFlag.AlignRight)
        outer.addLayout(header)

        # Search row
        row = QHBoxLayout()
        self.lbl_list = QLabel()
        self.lbl_list.setStyleSheet("font-size: 11pt; font-weight: 600;")
        row.addWidget(self.lbl_list, 0)

        self.search = QLineEdit()
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search, 1)

        outer.addLayout(row)

        # Body: list + right-side buttons (as in the legacy launcher)
        body = QHBoxLayout()
        body.setSpacing(12)
        outer.addLayout(body, 1)

        # Left: list of DBs (single-line rows; details shown below)
        left = QVBoxLayout()
        left.setSpacing(8)
        body.addLayout(left, 1)

        self.list = QListView()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.doubleClicked.connect(self.run_configurator)
        self.list.setMouseTracking(True)
        self.list.setStyleSheet("QListView::item { height: 50px; }")

        self.model = DbListModel()
        self.list.setModel(self.model)
        self.list.setItemDelegate(_DbRowDelegate(self.list))
        self.list.viewport().installEventFilter(self)
        left.addWidget(self.list, 1)

        # Selected DB details (path / url) under the list
        self.lbl_target = QLabel()
        self.lbl_target.setStyleSheet("color: #9AA4B2;")
        self.lbl_target.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_target.setAlignment(Qt.AlignmentFlag.AlignLeft)
        left.addWidget(self.lbl_target, 0)

        # Right: buttons (full height, exit pinned to bottom)
        right_widget = QWidget()
        right_widget.setFixedWidth(170)
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        body.addWidget(right_widget, 0)

        self.btn_client = QPushButton()
        self.btn_client.clicked.connect(self.run_client)
        self.btn_client.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right.addWidget(self.btn_client)

        self.btn_config = QPushButton()
        self.btn_config.clicked.connect(self.run_configurator)
        self.btn_config.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right.addWidget(self.btn_config)

        self.btn_autopilot = QPushButton()
        self.btn_autopilot.clicked.connect(self.run_autopilot)
        self.btn_autopilot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right.addWidget(self.btn_autopilot)

        right.addSpacing(16)

        self.btn_add = QPushButton()
        self.btn_add.clicked.connect(self.add_db)
        self.btn_add.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right.addWidget(self.btn_add)

        self.btn_edit = QPushButton()
        self.btn_edit.clicked.connect(self.edit_db)
        self.btn_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right.addWidget(self.btn_edit)

        self.btn_remove = QPushButton()
        self.btn_remove.clicked.connect(self.remove_db)
        self.btn_remove.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right.addWidget(self.btn_remove)

        self.btn_settings = QPushButton()
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right.addWidget(self.btn_settings)

        right.addSpacing(16)
        right.addStretch(1)

        self.btn_exit = QPushButton()
        self.btn_exit.clicked.connect(self.close)
        self.btn_exit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right.addWidget(self.btn_exit)

        bind(self.apply_i18n, self)
        self.apply_i18n()
        self.refresh()

        # Selection changes update the details label
        try:
            self.list.selectionModel().selectionChanged.connect(lambda *_: self._update_details())
        except Exception:
            pass
        self._update_details()

    # ---------------- Qt helpers ----------------
    def _app(self):
        from PySide6.QtWidgets import QApplication
        return QApplication.instance()

    def _on_lang_changed(self, display_text: str) -> None:
        set_lang(display_to_lang(display_text))
        self.apply_i18n()

    def apply_i18n(self) -> None:
        self.setWindowTitle(t("launcher_title"))
        self.lbl_subtitle.setText(t("launcher_subtitle"))
        self.lbl_list.setText(t("list_label"))
        self.search.setPlaceholderText(t("ph_search"))

        self.btn_client.setText(t("btn_client"))
        self.btn_config.setText(t("btn_config"))
        self.btn_autopilot.setText(t("btn_autopilot"))
        self.btn_add.setText(t("btn_add"))
        self.btn_edit.setText(t("btn_edit"))
        self.btn_remove.setText(t("btn_remove"))
        self.btn_settings.setText(t("btn_settings"))
        self.btn_exit.setText(t("btn_exit"))

        self.cmb_lang.blockSignals(True)
        self.cmb_lang.setCurrentText(lang_to_display(get_lang()))
        self.cmb_lang.blockSignals(False)

    # ---------------- Data ----------------
    def refresh(self) -> None:
        q = (self.search.text() or "").strip().lower()
        rows = list(self.dbs)
        if q:
            rows = [x for x in rows if q in x.name.lower() or q in (x.path or "").lower() or q in (x.runtime_url or "").lower()]
        self.filtered = rows

        self.status_codes = []
        self.status_tips = []
        for x in self.filtered:
            if x.kind == "local":
                if _file_exists(x.path):
                    self.status_codes.append("ok")
                    self.status_tips.append(t("status_ok"))
                else:
                    self.status_codes.append("no_file")
                    self.status_tips.append(f"{t('status_no_file')}: {x.path}")
            else:
                # Remote availability is checked at open time; show a neutral indicator in the list.
                self.status_codes.append("remote")
                self.status_tips.append(t("status_remote"))

        self.model.set_data(self.filtered, self.status_codes, self.status_tips)
        self._update_details()

    def current_db(self) -> DbEntry | None:
        sm = self.list.selectionModel()
        if sm is None:
            return None
        idxs = sm.selectedIndexes()
        if not idxs:
            return None
        row = idxs[0].row()
        return self.filtered[row] if 0 <= row < len(self.filtered) else None

    def _update_details(self) -> None:
        """Shows the selected DB connection address under the list."""
        db = self.current_db()
        if not db:
            self.lbl_target.setText("")
            return

        if db.kind == "local":
            self.lbl_target.setText(str(db.path or ""))
        else:
            parts: list[str] = []
            if db.runtime_url:
                parts.append(db.runtime_url)
            if db.db_uid:
                parts.append(f"uid={db.db_uid}")
            self.lbl_target.setText("    ".join(parts))

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        """Show error details only when hovering the status indicator."""
        if obj is self.list.viewport():
            et = event.type()
            if et == QEvent.Type.Leave:
                self._last_status_tooltip = ""
                QToolTip.hideText()
            elif et == QEvent.Type.MouseMove:
                pos = event.pos()
                idx = self.list.indexAt(pos)
                if not idx.isValid():
                    if self._last_status_tooltip:
                        self._last_status_tooltip = ""
                        QToolTip.hideText()
                    return False

                rect = self.list.visualRect(idx)
                ind = _DbRowDelegate.indicator_rect_for(rect)
                if ind.contains(pos):
                    tip = str(idx.data(DbListModel.RoleStatusTip) or "")
                    if tip and tip != self._last_status_tooltip:
                        self._last_status_tooltip = tip
                        QToolTip.showText(event.globalPos(), tip, self.list)
                else:
                    if self._last_status_tooltip:
                        self._last_status_tooltip = ""
                        QToolTip.hideText()

        return super().eventFilter(obj, event)

    # ---------------- Runtime glue ----------------
    def _ensure_runtime(self, runtime_url: str, *, autostart: bool) -> bool:
        url = runtime_url.rstrip("/")
        gw = RuntimeGateway(url)
        if gw.health():
            return True
        if not autostart:
            return False
        try:
            parsed = urlparse(url)
            host = parsed.hostname or "127.0.0.1"
            port = int(parsed.port or 8765)
            py = sys.executable
            script = str((Path(__file__).resolve().parents[1] / "scripts" / "run_runtime_server_cmd.py").resolve())
            subprocess.Popen(
                [py, script, "--host", host, "--port", str(port)],
                creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0,
                cwd=str(Path(__file__).resolve().parents[2]),
            )
        except Exception:
            return False
        for _ in range(30):
            if gw.health(timeout=0.5):
                return True
            time.sleep(0.2)
        return False

    def _open_db_via_runtime(self, entry: DbEntry) -> tuple[str, str] | None:
        url = entry.runtime_url.rstrip("/")
        if not self._ensure_runtime(url, autostart=(entry.kind == "local" and bool(entry.autostart))):
            QMessageBox.warning(self, t("dlg_config_title"), t("dlg_runtime_unavailable"))
            return None

        gw = RuntimeGateway(url)
        try:
            sid = gw.ensure_session()
            db_uid = ""
            db_name = entry.name
            if entry.kind == "local":
                data = gw.open_by_path(entry.path)
                actual_uid = str(data.get("db_uid") or "")
                if entry.db_uid and actual_uid and entry.db_uid != actual_uid:
                    # UID mismatch — DB was recreated (e.g. after import hard-reset).
                    from PySide6.QtWidgets import QMessageBox
                    answer = QMessageBox.question(
                        self,
                        t("dlg_db_uid"),
                        t("dlg_db_uid_mismatch") + "\n\n"
                        + t("dlg_db_uid_mismatch_update").format(
                            old=entry.db_uid, new=actual_uid
                        ),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    if answer == QMessageBox.StandardButton.No:
                        return None
                    self._update_db_uid(entry, actual_uid)
                    entry = self.current_db() or entry  # refresh
                if actual_uid and not entry.db_uid:
                    self._update_db_uid(entry, actual_uid)
                db_uid = actual_uid or entry.db_uid
                db_name = str(data.get("name") or entry.name)
            else:
                if not entry.db_uid:
                    # MVP: still allow manual uid; server registry step will replace this.
                    QMessageBox.warning(self, t("dlg_config_title"), t("dlg_remote_missing_uid"))
                    return None
                gw.open_by_uid(entry.db_uid)
                db_uid = entry.db_uid

            os.environ["META_RUNTIME_URL"] = url
            os.environ["META_SESSION_ID"]  = sid
            os.environ["META_DB_UID"]      = db_uid
            os.environ["META_DB_NAME"]     = db_name
            # Transitional bridge: keep META_DB_PATH for configurator code not yet on RPC.
            if entry.kind == "local":
                os.environ["META_DB_PATH"] = str(entry.path)
            return (url, sid)
        except Exception as e:
            QMessageBox.critical(self, t("dlg_config_title"), str(e))
            return None

    def _update_db_uid(self, entry: DbEntry, db_uid: str) -> None:
        updated: list[DbEntry] = []
        for x in self.dbs:
            if x.kind == entry.kind and x.path == entry.path and x.runtime_url == entry.runtime_url:
                updated.append(DbEntry(name=x.name, kind=x.kind, path=x.path, runtime_url=x.runtime_url, autostart=x.autostart, db_uid=db_uid))
            else:
                updated.append(x)
        self.dbs = updated
        save_catalog(self.dbs)
        self.refresh()

    # ---------------- Actions ----------------
    def add_db(self) -> None:
        wiz = AddDbWizard(self)
        if wiz.exec() != QDialog.DialogCode.Accepted:
            return
        res = wiz.result_data()
        if res is None:
            return

        # --- Create new local DB ---
        if res.action == "create_local":
            try:
                db_file = create_new_metadb_in_directory(Path(res.path))
            except Exception as e:
                # Localize the most common case: the selected folder already contains MetaDB
                if isinstance(e, FileExistsError):
                    QMessageBox.warning(self, t("dlg_add_title"), t("dlg_add_exists_folder"))
                else:
                    QMessageBox.critical(self, t("dlg_add_title"), str(e))
                return
            entry = DbEntry(name=res.name, kind="local", path=str(db_file))
            self.dbs = add_entry(self.dbs, entry)
            save_catalog(self.dbs)
            self.refresh()
            return

        # --- Add existing local DB ---
        if res.action == "add_local":
            entry = DbEntry(name=res.name, kind="local", path=res.path)
            self.dbs = add_entry(self.dbs, entry)
            save_catalog(self.dbs)
            self.refresh()
            return

        # --- Add remote DB ---
        entry = DbEntry(
            name=res.name,
            kind="remote",
            path="",
            runtime_url=res.runtime_url,
            autostart=False,
            db_uid=res.db_uid,
        )
        self.dbs = add_entry(self.dbs, entry)
        save_catalog(self.dbs)
        self.refresh()

    
    def add_remote_db(self) -> None:
        name, ok = QInputDialog.getText(self, t("dlg_add_remote_title"), t("dlg_name"))
        if not ok or not str(name).strip():
            return
        url, ok = QInputDialog.getText(self, t("dlg_add_remote_title"), t("dlg_runtime_url"))
        if not ok or not str(url).strip():
            return
        db_uid, ok = QInputDialog.getText(self, t("dlg_add_remote_title"), t("dlg_db_uid"))
        if not ok:
            return
        entry = DbEntry(
            name=str(name).strip(),
            kind="remote",
            path="",
            runtime_url=str(url).strip().rstrip("/"),
            autostart=False,
            db_uid=str(db_uid).strip(),
        )
        self.dbs = add_entry(self.dbs, entry)
        save_catalog(self.dbs)
        self.refresh()

    def open_settings(self) -> None:
        QMessageBox.information(self, t("dlg_settings_title"), t("dlg_settings_not_impl"))

    def edit_db(self) -> None:
        db = self.current_db()
        if not db:
            return
        name, ok = QInputDialog.getText(self, t("dlg_edit_title"), t("dlg_name"), text=db.name)
        if not ok or not str(name).strip():
            return
        url, ok = QInputDialog.getText(self, t("dlg_edit_title"), t("dlg_runtime_url"), text=db.runtime_url)
        if not ok or not str(url).strip():
            return
        new_uid = db.db_uid
        if db.kind == "remote":
            uid, ok = QInputDialog.getText(self, t("dlg_edit_title"), t("dlg_db_uid"), text=db.db_uid)
            if ok:
                new_uid = str(uid).strip()
        updated: list[DbEntry] = []
        for x in self.dbs:
            if x == db:
                updated.append(DbEntry(name=str(name).strip(), kind=db.kind, path=db.path, runtime_url=str(url).strip().rstrip("/"), autostart=db.autostart, db_uid=new_uid))
            else:
                updated.append(x)
        self.dbs = updated
        save_catalog(self.dbs)
        self.refresh()

    def remove_db(self) -> None:
        db = self.current_db()
        if not db:
            return
        if db.kind == "local":
            self.dbs = remove_entry_by_path(self.dbs, db.path)
        else:
            # remote: remove by (runtime_url, db_uid or name)
            self.dbs = [x for x in self.dbs if not (x.kind == "remote" and x.runtime_url == db.runtime_url and (x.db_uid or x.name) == (db.db_uid or db.name))]
        save_catalog(self.dbs)
        self.refresh()

    def _spawn_module(self, module: str) -> None:
        project_root = Path(__file__).resolve().parents[2]
        # Pass os.environ explicitly so META_RUNTIME_URL / META_DB_UID
        # set just before this call are guaranteed to reach the child process.
        subprocess.Popen(
            [sys.executable, "-m", module],
            cwd=str(project_root),
            env=os.environ.copy(),
        )
        self.close()

    def run_configurator(self) -> None:
        db = self.current_db()
        if not db:
            QMessageBox.information(self, t("dlg_config_title"), t("dlg_pick_db_first"))
            return
        if db.kind == "local" and not _file_exists(db.path):
            QMessageBox.warning(self, t("dlg_config_title"), t("dlg_bad_db_file"))
            return
        if not self._open_db_via_runtime(db):
            return
        self._spawn_module("src.configurator.configurator_app")

    def run_autopilot(self) -> None:
        db = self.current_db()
        if not db:
            QMessageBox.information(self, t("dlg_config_title"), t("dlg_pick_db_first"))
            return
        if db.kind == "local" and not _file_exists(db.path):
            QMessageBox.warning(self, t("dlg_config_title"), t("dlg_bad_db_file"))
            return
        if not self._open_db_via_runtime(db):
            return
        self._spawn_module("src.scripts.run_configurator_autopilot")

    def run_client(self) -> None:
        db = self.current_db()
        if not db:
            QMessageBox.information(self, t("dlg_client_title"), t("dlg_pick_db_first"))
            return
        if db.kind == "local" and not _file_exists(db.path):
            QMessageBox.warning(self, t("dlg_client_title"), t("dlg_bad_db_file"))
            return
        if not self._open_db_via_runtime(db):
            return
        self._spawn_module("src.client.client_app")
