from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QRadioButton,
    QButtonGroup,
    QPushButton,
    QTextEdit,
)

from src.ui_qt.i18n import t


@dataclass(frozen=True, slots=True)
class GenerateOptions:
    schema: bool
    forms: bool
    commands: bool
    overwrite: bool


class GenerateDialog(QDialog):
    """Dialog to choose what to generate for a metadata object.

    MVP:
        - Schema: attributes + tabular parts (templates)
        - Forms: List/Object forms based on current schema
        - Commands: typical commands under commands/
    """

    def __init__(self, parent=None, *, preview_provider=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("dlg_generate_title"))
        self.setModal(True)

        self._preview_provider = preview_provider

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        lbl = QLabel(t("dlg_generate_hint"))
        lbl.setWordWrap(True)
        root.addWidget(lbl)

        self.chk_schema = QCheckBox(t("dlg_generate_schema"))
        self.chk_schema.setChecked(True)
        root.addWidget(self.chk_schema)

        self.chk_forms = QCheckBox(t("dlg_generate_forms"))
        self.chk_forms.setChecked(True)
        root.addWidget(self.chk_forms)

        self.chk_commands = QCheckBox(t("dlg_generate_commands"))
        self.chk_commands.setChecked(True)
        root.addWidget(self.chk_commands)

        root.addWidget(QLabel(t("dlg_generate_mode")))

        self.rb_merge = QRadioButton(t("dlg_generate_mode_merge"))
        self.rb_overwrite = QRadioButton(t("dlg_generate_mode_overwrite"))
        self.rb_merge.setChecked(True)

        grp = QButtonGroup(self)
        grp.addButton(self.rb_merge)
        grp.addButton(self.rb_overwrite)

        root.addWidget(self.rb_merge)
        root.addWidget(self.rb_overwrite)

        # Preview (diff-like summary)
        root.addWidget(QLabel(t("dlg_generate_preview")))
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMinimumHeight(150)
        self._preview.setObjectName("generatePreview")
        root.addWidget(self._preview, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)

        self.btn_ok = QPushButton(t("btn_generate"))
        self.btn_cancel = QPushButton(t("btn_cancel"))

        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)

        root.addLayout(btns)

        # Live preview updates
        self.chk_schema.stateChanged.connect(self._refresh_preview)
        self.chk_forms.stateChanged.connect(self._refresh_preview)
        self.chk_commands.stateChanged.connect(self._refresh_preview)
        self.rb_merge.toggled.connect(self._refresh_preview)
        self.rb_overwrite.toggled.connect(self._refresh_preview)
        self._refresh_preview()

    def options(self) -> GenerateOptions:
        return GenerateOptions(
            schema=bool(self.chk_schema.isChecked()),
            forms=bool(self.chk_forms.isChecked()),
            commands=bool(self.chk_commands.isChecked()),
            overwrite=bool(self.rb_overwrite.isChecked()),
        )

    def _refresh_preview(self) -> None:
        if self._preview_provider is None:
            self._preview.setPlainText(t("dlg_generate_preview_unavailable"))
            return
        try:
            txt = self._preview_provider(self.options())
            self._preview.setPlainText(str(txt or ""))
        except Exception:
            self._preview.setPlainText(t("dlg_generate_preview_unavailable"))
