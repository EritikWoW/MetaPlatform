from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel, QLineEdit,
    QTextEdit, QComboBox, QSpinBox, QCheckBox, QPushButton, QToolButton, QSizePolicy
)

from src.ui_qt.viewmodels.configurator_vm import ConfiguratorViewModel
from src.configurator.domain.technical_names import technical_object_name


@dataclass
class ConstantProperties:
    title: str = ""
    synonym: str = ""
    comment: str = ""
    data_type: str = "string"  # string|number|date|boolean
    length: int = 10
    unlimited_length: bool = False


class ConstantPropertiesWidget(QWidget):
    """1C-like 'Properties' editor for a Constant object.

    This is UI-only. Saving is delegated via the applyRequested signal.
    """

    applyRequested = Signal(dict)  # payload patch
    titleChanged = Signal(str)     # new title/name for window/tab

    def __init__(
        self,
        display_name: str,
        payload: Optional[Dict[str, Any]] = None,
        parent: QWidget | None = None,
        *,
        vm: ConfiguratorViewModel | None = None,
        obj_guid: str = "",
    ):
        super().__init__(parent)
        self.setObjectName("ConstantPropertiesWidget")
        self._vm = vm
        self._obj_guid = str(obj_guid or "")
        self._payload = payload or {}
        self._build_ui(display_name)
        self.load_from_payload(self._payload)

    def _build_ui(self, display_name: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Header toolbar (minimal, 1C-like)
        header = QHBoxLayout()
        header.setSpacing(8)

        self.btn_apply = QPushButton("Зберегти")
        self.btn_apply.setDefault(True)
        self.btn_apply.clicked.connect(self._on_apply)

        header.addWidget(QLabel(f"Властивості: {display_name}"))
        header.addStretch(1)
        header.addWidget(self.btn_apply)

        root.addLayout(header)

        # Main group: Основные
        gb_main = QGroupBox("Основні")
        form = QFormLayout(gb_main)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.ed_title = QLineEdit()
        self.ed_syn = QLineEdit()
        self.ed_comment = QLineEdit()

        self.cb_type = QComboBox()
        self.cb_type.addItem("Строка", "string")
        self.cb_type.addItem("Число", "number")
        self.cb_type.addItem("Дата", "date")
        self.cb_type.addItem("Булево", "boolean")

        self.sp_len = QSpinBox()
        self.sp_len.setRange(1, 1000000)
        self.sp_len.setValue(10)

        self.chk_unlimited = QCheckBox("Необмежена довжина")
        self.chk_unlimited.toggled.connect(lambda on: self.sp_len.setEnabled(not on))

        form.addRow("Ім'я", self.ed_title)
        form.addRow("Синонім", self.ed_syn)
        form.addRow("Коментар", self.ed_comment)
        form.addRow("Тип", self.cb_type)
        form.addRow("Довжина", self.sp_len)
        form.addRow("", self.chk_unlimited)

        root.addWidget(gb_main)

        # Data / Presentation stubs (placeholders for future)
        gb_data = QGroupBox("Дані")
        gb_data_l = QVBoxLayout(gb_data)
        gb_data_l.addWidget(QLabel("Налаштування даних буде додано пізніше."))
        root.addWidget(gb_data)

        gb_view = QGroupBox("Представлення")
        gb_view_l = QVBoxLayout(gb_view)
        gb_view_l.addWidget(QLabel("Налаштування представлення буде додано пізніше."))
        root.addWidget(gb_view)

        root.addStretch(1)

        self.ed_title.textChanged.connect(self.titleChanged.emit)

    def load_from_payload(self, payload: Dict[str, Any]) -> None:
        const = payload.get("constant") if isinstance(payload.get("constant"), dict) else {}
        title = str(payload.get("title") or payload.get("name") or "")
        self.ed_title.setText(title)
        self.ed_syn.setText(str(const.get("synonym") or ""))
        self.ed_comment.setText(str(const.get("comment") or ""))

        dt = str(const.get("data_type") or "string")
        # set combobox by data
        for i in range(self.cb_type.count()):
            if self.cb_type.itemData(i) == dt:
                self.cb_type.setCurrentIndex(i)
                break

        length = int(const.get("length") or 10)
        self.sp_len.setValue(max(1, length))
        unlimited = bool(const.get("unlimited_length") or False)
        self.chk_unlimited.setChecked(unlimited)
        self.sp_len.setEnabled(not unlimited)

    def _on_apply(self) -> None:
        patch = {
            "title": self.ed_title.text().strip(),
            "constant": {
                "synonym": self.ed_syn.text().strip(),
                "comment": self.ed_comment.text().strip(),
                "data_type": self.cb_type.currentData(),
                "length": int(self.sp_len.value()),
                "unlimited_length": bool(self.chk_unlimited.isChecked()),
            },
        }
        self.applyRequested.emit(patch)

    def reload_from_vm(self) -> None:
        if self._vm is None or not self._obj_guid:
            return
        try:
            meta = self._vm.get_meta_by_guid(self._obj_guid)
        except Exception:
            meta = None
        if not isinstance(meta, dict):
            return
        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
        self._payload = dict(payload or {})
        title = technical_object_name(meta.get("name"), payload=payload)
        if title:
            try:
                self.setWindowTitle(title)
            except Exception:
                pass
        self.load_from_payload(self._payload)
