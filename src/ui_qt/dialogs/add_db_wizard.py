from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QEvent
from PySide6.QtGui import QPalette, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.platform.paths import DB_EXT
from src.runtime.gateway import RuntimeGateway
from src.ui_qt.i18n import t


@dataclass
class AddDbWizardResult:
    action: str  # "create_local" | "add_local" | "add_remote"
    name: str
    path: str
    runtime_url: str
    db_uid: str


class AddDbWizard(QDialog):
    """Wizard-style dialog for adding/creating a database entry (1C-like flow).

    MVP supports:
    - Create new local DB (create file)
    - Add existing local DB (pick file)
    - Add remote DB (pick runtime URL + choose DB from server registry)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("wizard_add_title"))
        self.setModal(True)
        self.setMinimumSize(640, 420)

        self._result: AddDbWizardResult | None = None

        # State
        self._action: str = "create_local"
        self._remote_rows: list[dict] = []

        # Layout skeleton
        root = QVBoxLayout(self)
        self._pages = QStackedWidget(self)
        root.addWidget(self._pages, 1)

        # Nav
        nav = QHBoxLayout()
        self._btn_back = QPushButton(t("wizard_back"))
        self._btn_next = QPushButton(t("wizard_next"))
        self._btn_cancel = QPushButton(t("wizard_cancel"))
        nav.addWidget(self._btn_back)
        nav.addWidget(self._btn_next)
        nav.addItem(QSpacerItem(10, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        nav.addWidget(self._btn_cancel)
        root.addLayout(nav)

        self._btn_back.clicked.connect(self._on_back)
        self._btn_next.clicked.connect(self._on_next)
        self._btn_cancel.clicked.connect(self.reject)

        # Pages
        self._page_choice = self._build_page_choice()
        self._page_create = self._build_page_create()
        self._page_add_local = self._build_page_add_local()
        self._page_remote = self._build_page_remote()

        self._pages.addWidget(self._page_choice)
        self._pages.addWidget(self._page_create)
        self._pages.addWidget(self._page_add_local)
        self._pages.addWidget(self._page_remote)

        self._apply_theme_styles()
        self._goto(0)

    def result_data(self) -> AddDbWizardResult | None:
        return self._result


    def _apply_theme_styles(self) -> None:
        """Apply small wizard-local styles derived from the current palette.

        We keep this palette-driven (not hard-coded) so light theme will work later.
        """
        pal = self.palette()
        fg = pal.color(QPalette.ColorRole.Text).name()
        mid = pal.color(QPalette.ColorRole.Mid).name()
        base = pal.color(QPalette.ColorRole.Base).name()
        hl = pal.color(QPalette.ColorRole.Highlight).name()

        ss = f"""
        QLabel#wizardTitle {{
            font-size: 16px;
            font-weight: 600;
            color: {fg};
        }}
        QLabel#wizardHint {{
            color: {mid};
        }}
        QRadioButton {{
            color: {fg};
        }}
        QRadioButton::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 8px;
            border: 1px solid {mid};
            background: {base};
        }}
        QRadioButton::indicator:checked {{
            border: 2px solid {hl};
            background: {hl};
        }}
        """

        # Merge with any existing stylesheet (if global theme sets one)
        self.setStyleSheet((self.styleSheet() or "") + ss)

    def _hint(self, text: str) -> QLabel:
        lb = QLabel(text)
        lb.setObjectName("wizardHint")
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return lb

    def _option_block(self, rb: QRadioButton, description: str) -> QWidget:
        wrap = QWidget(self)
        v = QVBoxLayout(wrap)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(4)
        v.addWidget(rb)
        v.addWidget(self._hint(description))
        return wrap

    class OptionCard(QFrame):
        """Clickable option row (1C-like) with a radio indicator and description."""

        def __init__(
            self,
            parent: QWidget,
            rb: QRadioButton,
            title: str,
            description: str,
        ) -> None:
            super().__init__(parent)
            self._rb = rb
            self._title = QLabel(title, self)
            self._desc = QLabel(description, self)

            self.setObjectName("wizardOptionCard")
            self.setFrameShape(QFrame.Shape.StyledPanel)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setAutoFillBackground(False)

            self._rb.setText("")
            self._rb.toggled.connect(self._on_toggled)

            self._title.setObjectName("wizardOptionTitle")
            self._title.setWordWrap(True)
            self._title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

            self._desc.setObjectName("wizardOptionDesc")
            self._desc.setWordWrap(True)
            self._desc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

            row = QHBoxLayout(self)
            row.setContentsMargins(12, 10, 12, 10)
            row.setSpacing(10)
            row.addWidget(self._rb, 0, Qt.AlignmentFlag.AlignTop)

            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(4)
            col.addWidget(self._title)
            col.addWidget(self._desc)
            row.addLayout(col, 1)

            self._sync_fonts()
            self._apply_palette_dependent_styles()
            self._on_toggled(self._rb.isChecked())

        def _sync_fonts(self) -> None:
            # Title: slightly stronger; Desc: slightly smaller
            f_title = self._title.font()
            f_title.setBold(True)
            self._title.setFont(f_title)

            f_desc = self._desc.font()
            f_desc.setPointSize(max(8, f_desc.pointSize() - 1))
            self._desc.setFont(f_desc)

        def _apply_palette_dependent_styles(self) -> None:
            pal = self.palette()
            text = pal.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Text)
            disabled = pal.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)

            self._title.setStyleSheet(f"color: {text.name()};")
            self._desc.setStyleSheet(f"color: {disabled.name()};")

            # Make radio indicator visible on both dark/light themes.
            base = pal.color(QPalette.ColorRole.Base)
            hl = pal.color(QPalette.ColorRole.Highlight)

            # Use palette-derived colors (no hardcoded).
            ss = f"""
            QRadioButton::indicator {{
                width: 14px;
                height: 14px;
                border-radius: 7px;
                border: 2px solid {disabled.name()};
                background: {base.name()};
            }}
            QRadioButton::indicator:checked {{
                border: 2px solid {hl.name()};
                background: {hl.name()};
            }}
            """
            self._rb.setStyleSheet(ss)

        def _on_toggled(self, checked: bool) -> None:
            self.setProperty("selected", checked)
            self.update()

        def mousePressEvent(self, event) -> None:  # noqa: N802
            if event.button() == Qt.MouseButton.LeftButton:
                self._rb.setChecked(True)
                event.accept()
                return
            super().mousePressEvent(event)

        def paintEvent(self, event) -> None:  # noqa: N802
            super().paintEvent(event)

            pal = self.palette()
            base = pal.color(QPalette.ColorRole.Base)
            window = pal.color(QPalette.ColorRole.Window)
            hl = pal.color(QPalette.ColorRole.Highlight)
            border = pal.color(QPalette.ColorRole.Mid)

            selected = bool(self.property("selected"))
            bg = base if selected else window
            pen = hl if selected else border

            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(pen)
            p.setBrush(bg)
            r = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
            p.drawRoundedRect(r, 8.0, 8.0)
            p.end()

        def changeEvent(self, event) -> None:  # noqa: N802
            # Re-apply palette-driven styles when theme/palette changes.
            if event.type() in (
                QEvent.Type.PaletteChange,
                QEvent.Type.StyleChange,
                QEvent.Type.ThemeChange,
            ):
                self._apply_palette_dependent_styles()
                self.update()
            super().changeEvent(event)

    # ---------------- Pages ----------------

    def _build_page_choice(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setSpacing(12)

        title = QLabel(t("wizard_step1_title"))
        title.setObjectName("wizardTitle")
        lay.addWidget(title)

        gb = QGroupBox(t("wizard_step1_group"))
        gbl = QVBoxLayout(gb)
        gbl.setSpacing(10)

        # Radios are used only for state; text/description are rendered by OptionCard.
        self._rb_create = QRadioButton("")
        self._rb_add_local = QRadioButton("")
        self._rb_remote = QRadioButton("")

        self._rb_create.setChecked(True)

        self._action_group = QButtonGroup(self)
        self._action_group.addButton(self._rb_create)
        self._action_group.addButton(self._rb_add_local)
        self._action_group.addButton(self._rb_remote)

        # 1C-like clickable cards
        gbl.addWidget(
            self.OptionCard(
                gb,
                self._rb_create,
                t("wizard_action_create"),
                t("wizard_action_create_desc"),
            )
        )
        gbl.addWidget(
            self.OptionCard(
                gb,
                self._rb_add_local,
                t("wizard_action_add_local"),
                t("wizard_action_add_local_desc"),
            )
        )
        gbl.addWidget(
            self.OptionCard(
                gb,
                self._rb_remote,
                t("wizard_action_add_remote"),
                t("wizard_action_add_remote_desc"),
            )
        )

        lay.addWidget(gb)
        lay.addStretch(1)
        return w


    def _build_page_create(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)

        title = QLabel(t("wizard_step_create_title"))
        title.setObjectName("wizardTitle")
        lay.addWidget(title)

        form = QFormLayout()
        self._create_name = QLineEdit()
        self._create_name.setPlaceholderText(t("wizard_name_ph"))
        self._create_path = QLineEdit()
        self._create_path.setPlaceholderText(t("wizard_path_ph"))
        btn_browse = QPushButton(t("wizard_browse"))
        btn_browse.clicked.connect(self._browse_create_path)

        row = QHBoxLayout()
        row.addWidget(self._create_path, 1)
        row.addWidget(btn_browse)

        form.addRow(t("wizard_name_lbl"), self._create_name)
        form.addRow(t("wizard_path_lbl"), row)
        lay.addLayout(form)

        hint = QLabel(t("wizard_create_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("wizardHint")
        lay.addWidget(hint)

        lay.addStretch(1)
        return w

    def _build_page_add_local(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)

        title = QLabel(t("wizard_step_add_local_title"))
        title.setObjectName("wizardTitle")
        lay.addWidget(title)

        form = QFormLayout()
        self._local_name = QLineEdit()
        self._local_name.setPlaceholderText(t("wizard_name_ph"))
        self._local_path = QLineEdit()
        self._local_path.setPlaceholderText(t("wizard_pick_file_ph"))
        btn_pick = QPushButton(t("wizard_browse"))
        btn_pick.clicked.connect(self._browse_existing_file)

        row = QHBoxLayout()
        row.addWidget(self._local_path, 1)
        row.addWidget(btn_pick)

        form.addRow(t("wizard_name_lbl"), self._local_name)
        form.addRow(t("wizard_file_lbl"), row)
        lay.addLayout(form)

        hint = QLabel(t("wizard_add_local_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("wizardHint")
        lay.addWidget(hint)

        lay.addStretch(1)
        return w

    def _build_page_remote(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)

        title = QLabel(t("wizard_step_remote_title"))
        title.setObjectName("wizardTitle")
        lay.addWidget(title)

        form = QFormLayout()
        self._remote_url = QLineEdit()
        self._remote_url.setPlaceholderText("http://127.0.0.1:8765")
        self._remote_url.setText("http://127.0.0.1:8765")

        self._remote_list = QListWidget()
        self._remote_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

        btn_refresh = QPushButton(t("wizard_refresh"))
        btn_refresh.clicked.connect(self._remote_refresh)

        form.addRow(t("wizard_runtime_url_lbl"), self._remote_url)
        lay.addLayout(form)

        lay.addWidget(btn_refresh, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self._remote_list, 1)

        hint = QLabel(t("wizard_remote_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("wizardHint")
        lay.addWidget(hint)

        return w

    # ---------------- Navigation ----------------

    def _goto(self, idx: int) -> None:
        self._pages.setCurrentIndex(idx)
        self._btn_back.setEnabled(idx != 0)

        # Button labels
        if idx == 0:
            self._btn_next.setText(t("wizard_next"))
        else:
            self._btn_next.setText(t("wizard_finish") if self._is_last_page(idx) else t("wizard_next"))

    def _is_last_page(self, idx: int) -> bool:
        # last page depends on action
        act = self._get_action()
        if act == "create_local":
            return idx == 1
        if act == "add_local":
            return idx == 2
        return idx == 3

    def _get_action(self) -> str:
        if self._rb_create.isChecked():
            return "create_local"
        if self._rb_add_local.isChecked():
            return "add_local"
        return "add_remote"

    def _on_back(self) -> None:
        idx = self._pages.currentIndex()
        if idx <= 0:
            return
        # Wizard MVP: any step goes back to the initial action choice (1C-like)
        self._goto(0)

    def _on_next(self) -> None:
        idx = self._pages.currentIndex()

        if idx == 0:
            act = self._get_action()
            if act == "create_local":
                self._goto(1)
            elif act == "add_local":
                self._goto(2)
            else:
                self._goto(3)
                # auto refresh once when entering
                if not self._remote_rows:
                    self._remote_refresh()
            return

        # Finish
        if self._is_last_page(idx):
            self._try_finish()
            return

        self._goto(idx + 1)

    # ---------------- Page actions ----------------

    def _browse_create_path(self) -> None:
        # For "Create new" we must pick a *directory* (1C-like), not a file.
        base_dir = QFileDialog.getExistingDirectory(
            self,
            t("wizard_pick_folder_title"),
            str(Path.home()),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not base_dir:
            return
        self._create_path.setText(str(Path(base_dir)))

    def _browse_existing_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("wizard_pick_file_title"), str(Path.home()), f"*{DB_EXT}")
        if not path:
            return
        self._local_path.setText(str(Path(path)))
        if not self._local_name.text().strip():
            self._local_name.setText(Path(path).stem)

    def _remote_refresh(self) -> None:
        url = self._remote_url.text().strip().rstrip("/")
        if not url:
            QMessageBox.warning(self, t("wizard_step_remote_title"), t("wizard_runtime_url_empty"))
            return
        try:
            gw = RuntimeGateway(url)
            if not gw.health():
                QMessageBox.warning(self, t("wizard_step_remote_title"), t("wizard_remote_unreachable"))
                return
            self._remote_rows = gw.list_databases()
        except Exception as e:
            QMessageBox.critical(self, t("wizard_step_remote_title"), str(e))
            return

        self._remote_list.clear()
        for row in self._remote_rows:
            nm = str(row.get("name") or "")
            uid = str(row.get("db_uid") or "")
            text = f"{nm}  [{uid}]" if uid else nm
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, row)
            self._remote_list.addItem(it)

        if self._remote_list.count() > 0:
            self._remote_list.setCurrentRow(0)

    # ---------------- Finish ----------------

    def _try_finish(self) -> None:
        act = self._get_action()

        if act == "create_local":
            name = self._create_name.text().strip()
            path = self._create_path.text().strip()
            if not name:
                QMessageBox.warning(self, t("wizard_step_create_title"), t("wizard_err_name"))
                return
            if not path:
                QMessageBox.warning(self, t("wizard_step_create_title"), t("wizard_err_path"))
                return
            # Path here is a directory where MetaDB/metabase.mpdb will be created.
            p = Path(path)
            if p.suffix.lower() == DB_EXT:
                # User might have pasted a file path; normalize to its parent.
                p = p.parent
            path = str(p)
            self._result = AddDbWizardResult(
                action="create_local",
                name=name,
                path=path,
                runtime_url="",
                db_uid="",
            )
            self.accept()
            return

        if act == "add_local":
            name = self._local_name.text().strip()
            path = self._local_path.text().strip()
            if not name:
                QMessageBox.warning(self, t("wizard_step_add_local_title"), t("wizard_err_name"))
                return
            if not path:
                QMessageBox.warning(self, t("wizard_step_add_local_title"), t("wizard_err_file"))
                return
            p = Path(path)
            if not p.exists():
                QMessageBox.warning(self, t("wizard_step_add_local_title"), t("wizard_err_no_file"))
                return
            self._result = AddDbWizardResult(
                action="add_local",
                name=name,
                path=str(p),
                runtime_url="",
                db_uid="",
            )
            self.accept()
            return

        # add_remote
        url = self._remote_url.text().strip().rstrip("/")
        if not url:
            QMessageBox.warning(self, t("wizard_step_remote_title"), t("wizard_runtime_url_empty"))
            return
        it = self._remote_list.currentItem()
        if it is None:
            QMessageBox.warning(self, t("wizard_step_remote_title"), t("wizard_remote_pick"))
            return
        row = it.data(Qt.ItemDataRole.UserRole) or {}
        db_uid = str(row.get("db_uid") or "").strip()
        db_name = str(row.get("name") or "").strip() or "Remote"
        if not db_uid:
            QMessageBox.warning(self, t("wizard_step_remote_title"), t("wizard_remote_no_uid"))
            return

        self._result = AddDbWizardResult(
            action="add_remote",
            name=db_name,
            path="",
            runtime_url=url,
            db_uid=db_uid,
        )
        self.accept()
