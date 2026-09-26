from __future__ import annotations

from dataclasses import dataclass
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QButtonGroup, QFileDialog, QDialogButtonBox,
    QCheckBox,
)

from src.ui_qt.i18n import t


@dataclass(frozen=True, slots=True)
class LoadConfigChoice:
    mode: str   # "xml" | "archive" | "auto" | "1cd"
    path: str
    migrate_data: bool = False


class LoadConfigDialog(QDialog):
    """1C-like dialog: Load configuration files (XML folder or archive)."""

    def __init__(self, parent=None, *, initial_mode: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(t("dlg_load_cfg_title"))
        self.setModal(True)
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)

        # Mode group
        root.addWidget(QLabel(t("dlg_load_cfg_from")))

        self.rb_xml = QRadioButton(t("dlg_load_cfg_xml"))
        self.rb_db = QRadioButton(t("dlg_load_cfg_database"))
        self.rb_arc = QRadioButton(t("dlg_load_cfg_archive"))
        self.rb_xml.setChecked(True)
        mode = str(initial_mode or "").strip().lower()
        if mode in {"1cd", "db", "database"}:
            self.rb_db.setChecked(True)
        elif mode in {"archive", "zip"}:
            self.rb_arc.setChecked(True)

        group = QButtonGroup(self)
        group.addButton(self.rb_xml)
        group.addButton(self.rb_db)
        group.addButton(self.rb_arc)

        root.addWidget(self.rb_xml)
        root.addWidget(self.rb_db)
        root.addWidget(self.rb_arc)

        self.cb_import_data = QCheckBox(t("dlg_load_cfg_import_data"))
        self.cb_import_data.setEnabled(False)
        root.addWidget(self.cb_import_data)

        # Path
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(t("dlg_load_cfg_path_placeholder"))
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(34)
        btn_browse.clicked.connect(self._browse)

        row.addWidget(self.path_edit, 1)
        row.addWidget(btn_browse, 0)
        root.addLayout(row)
        self.rb_db.toggled.connect(self._sync_data_import_option)
        self.rb_xml.toggled.connect(self._sync_data_import_option)
        self.rb_arc.toggled.connect(self._sync_data_import_option)
        self.path_edit.textChanged.connect(self._sync_data_import_option)

        # Buttons
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Help
        )
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(t("btn_load"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(t("btn_cancel"))
        bb.button(QDialogButtonBox.StandardButton.Help).setText(t("btn_help"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.StandardButton.Help).clicked.connect(self._help)

        root.addWidget(self._hline())
        root.addWidget(bb)

        self._apply_1c_style()
        self._sync_data_import_option()

    def choice(self) -> LoadConfigChoice:
        if self.rb_arc.isChecked():
            mode = "archive"
        elif self.rb_db.isChecked():
            mode = "1cd" if self.path_edit.text().strip().lower().endswith(".1cd") else "auto"
        else:
            mode = "xml"
        return LoadConfigChoice(
            mode=mode,
            path=self.path_edit.text().strip(),
            migrate_data=bool(self.cb_import_data.isEnabled() and self.cb_import_data.isChecked()),
        )

    # Compatibility shim: legacy callers expect (src_kind, src_path).
    def get_result(self) -> tuple[str, str]:
        choice = self.choice()
        return choice.mode, choice.path

    def should_import_data(self) -> bool:
        return bool(self.choice().migrate_data)

    def _sync_data_import_option(self) -> None:
        is_onecd = self.rb_db.isChecked() and self.path_edit.text().strip().lower().endswith(".1cd")
        self.cb_import_data.setEnabled(bool(is_onecd))
        if is_onecd:
            # Business data is only available from .1CD; enable it by default
            # so a normal database import brings records along with metadata.
            if not self.cb_import_data.isChecked():
                self.cb_import_data.setChecked(True)
        else:
            self.cb_import_data.setChecked(False)

    def _browse(self) -> None:
        if self.rb_xml.isChecked():
            p = QFileDialog.getExistingDirectory(self, t("dlg_load_cfg_pick_folder"), self.path_edit.text().strip() or "")
            if p:
                self.path_edit.setText(p)
        elif self.rb_db.isChecked():
            p, _ = QFileDialog.getOpenFileName(
                self,
                t("dlg_load_cfg_pick_database"),
                self.path_edit.text().strip() or "",
                "1C database (*.1CD *.1cd *.dt);;1CD (*.1CD *.1cd);;DT (*.dt);;All files (*.*)",
            )
            if p:
                self.path_edit.setText(p)
        else:
            p, _ = QFileDialog.getOpenFileName(
                self,
                t("dlg_load_cfg_pick_archive"),
                self.path_edit.text().strip() or "",
                "Archive (*.zip *.7z *.rar);;ZIP (*.zip);;All files (*.*)",
            )
            if p:
                self.path_edit.setText(p)

    def accept(self) -> None:
        source_path = self.path_edit.text().strip()
        if not source_path:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, t("dlg_error_title"), t("dlg_load_cfg_path_placeholder"))
            return

        if self.rb_xml.isChecked() or self.rb_db.isChecked():
            from pathlib import Path
            from PySide6.QtWidgets import QMessageBox

            from src.infra.onec.source_compat import detect_onec_source_kind, find_xmlconf_root

            candidate = Path(source_path)
            if not candidate.exists():
                QMessageBox.warning(
                    self,
                    t("dlg_error_title"),
                    f"Шлях не знайдено:\n{candidate}",
                )
                return

            detected = detect_onec_source_kind(str(candidate), "auto")
            if self.rb_db.isChecked() and detected not in {"dt", "1cd"}:
                QMessageBox.warning(
                    self,
                    t("dlg_error_title"),
                    "Оберіть файл 1Cv8.1CD або 1Cv8.dt.",
                )
                return
            if detected == "dt" and find_xmlconf_root(candidate) is None:
                QMessageBox.warning(
                    self,
                    t("dlg_error_title"),
                    "Знайдено файл бази 1С, але поруч не знайдено XMLConf.\n\n"
                    "Прямий semantic import зараз підтримано для 1Cv8.1CD. "
                    "Для 1Cv8.dt потрібна розпакована вивантажена конфігурація XMLConf.",
                )
                return
            if self.rb_xml.isChecked() and detected == "xml" and find_xmlconf_root(candidate) is None:
                QMessageBox.warning(
                    self,
                    t("dlg_error_title"),
                    "Не вдалося розпізнати корінь конфігурації 1С.\n\n"
                    "Оберіть XMLConf, папку з ConfigDumpInfo.xml/Configuration.xml "
                    "або файл 1Cv8.1CD.",
                )
                return
        super().accept()

    def _help(self) -> None:
        # minimal MVP
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, t("info_title"), t("dlg_load_cfg_help"))

    def _hline(self):
        from PySide6.QtWidgets import QFrame
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def _apply_1c_style(self) -> None:
        # Soft "1C-ish" look
        self.setStyleSheet("""
             QRadioButton { padding: 2px; }
             QLineEdit { border: 1px solid; padding: 4px; }
             QPushButton { border: 1px solid; padding: 5px 12px; }
             QRadioButton::indicator {
                 width: 12px;
                 height: 12px;
             }
             QRadioButton::indicator:unchecked {
                 border: 1px solid gray;
                 background-color: white;
                 border-radius: 6px;
             }
             QRadioButton::indicator:checked {
                 border: 1px solid gray;
                 background-color: green;
                 border-radius: 6px;
             }
         """)
