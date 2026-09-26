"""src.ui_qt.widgets.register_editor — Information/Accumulation register editor.

Регістри накопичення та відомостей:
  - Виміри (dimensions): поля по яких агрегуються дані
  - Ресурси (resources): числові поля що накопичуються
  - Реквізити (attributes): додаткові поля запису
  - Форми і Модулі (спільно з іншими редакторами)
"""
from __future__ import annotations

from src.configurator.domain.technical_names import technical_object_name

from dataclasses import dataclass, field
from typing import Any, Dict, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t
from src.ui_qt.services.object_editor_profiles import build_editor_sections
from src.ui_qt.viewmodels.configurator_vm import ConfiguratorViewModel
from .meta_object_shell import MetaObjectEditorShell
from .meta_object_shell import EditorSection
from .schema_editors import AttributesEditorWidget

# Типи даних для вимірів/ресурсів
_DATA_TYPES = ["string", "number", "boolean", "date", "reference"]


def _payload_text(value: Any) -> str:
    if isinstance(value, str):
        return str(value or "").strip()
    if isinstance(value, dict):
        for lang in ("uk", "en", "ru"):
            text = str(value.get(lang) or "").strip()
            if text:
                return text
        for raw in value.values():
            text = str(raw or "").strip()
            if text:
                return text
    return ""


@dataclass
class RegisterField:
    name:      str = ""
    type:      str = "string"
    synonym:   str = ""
    comment:   str = ""
    required:  bool = False


@dataclass
class RegisterPayload:
    name:         str = ""
    title:        str = ""
    synonym:      str = ""
    comment:      str = ""
    register_type: str = "balance"   # balance | turnover (для accum)
    periodicity:  str = "month"       # none | second | minute | hour | day | month | quarter | year
    dimensions:   List[dict] = field(default_factory=list)
    resources:    List[dict] = field(default_factory=list)
    attributes:   List[dict] = field(default_factory=list)

    @classmethod
    def from_payload(cls, p: dict) -> "RegisterPayload":
        if not isinstance(p, dict):
            return cls()
        title_text = _payload_text(p.get("title"))
        return cls(
            name          = str(p.get("name")          or title_text or ""),
            title         = title_text,
            synonym       = str(p.get("synonym")       or title_text or ""),
            comment       = str(p.get("comment")       or ""),
            register_type = str(p.get("register_type") or "balance"),
            periodicity   = str(p.get("periodicity")   or p.get("number_periodicity") or "month"),
            dimensions    = list(p.get("dimensions")   or []),
            resources     = list(p.get("resources")    or []),
            attributes    = list(p.get("attributes")   or []),
        )

    def to_patch(self) -> dict:
        return {
            "name":          self.name,
            "title":         self.title,
            "synonym":       self.synonym,
            "comment":       self.comment,
            "register_type": self.register_type,
            "periodicity":   self.periodicity,
            "dimensions":    self.dimensions,
            "resources":     self.resources,
            "attributes":    self.attributes,
        }


class _FieldsTableWidget(QWidget):
    """Редагована таблиця полів (виміри/ресурси/реквізити)."""

    def __init__(self, initial: List[dict] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.set_data(initial or [])

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        bar = QHBoxLayout()
        btn_add    = QPushButton("＋ " + t("btn_add"))
        btn_delete = QPushButton("－ " + t("btn_delete"))
        btn_up     = QPushButton("▲"); btn_up.setFixedWidth(32)
        btn_down   = QPushButton("▼"); btn_down.setFixedWidth(32)
        btn_add.clicked.connect(self._add_row)
        btn_delete.clicked.connect(self._delete_row)
        btn_up.clicked.connect(self._move_up)
        btn_down.clicked.connect(self._move_down)
        bar.addWidget(btn_add); bar.addWidget(btn_delete)
        bar.addStretch(1)
        bar.addWidget(btn_up); bar.addWidget(btn_down)
        layout.addLayout(bar)

        self._model = QStandardItemModel(0, 4)
        self._model.setHorizontalHeaderLabels([
            t("prop_name"), t("prop_type"), t("prop_synonym"), t("prop_comment"),
        ])
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        layout.addWidget(self._table, 1)

    def set_data(self, rows: List[dict]) -> None:
        self._model.removeRows(0, self._model.rowCount())
        for r in rows:
            self._model.appendRow([
                QStandardItem(str(r.get("name")    or "")),
                QStandardItem(str(r.get("type")    or "string")),
                QStandardItem(str(r.get("synonym") or "")),
                QStandardItem(str(r.get("comment") or "")),
            ])

    def get_data(self) -> List[dict]:
        out = []
        for r in range(self._model.rowCount()):
            name = (self._model.item(r, 0) or QStandardItem()).text().strip()
            if name:
                out.append({
                    "name":    name,
                    "type":    (self._model.item(r, 1) or QStandardItem()).text().strip() or "string",
                    "synonym": (self._model.item(r, 2) or QStandardItem()).text().strip(),
                    "comment": (self._model.item(r, 3) or QStandardItem()).text().strip(),
                })
        return out

    def _selected_row(self) -> int:
        idx = self._table.currentIndex()
        return idx.row() if idx.isValid() else -1

    def _add_row(self) -> None:
        r = self._model.rowCount()
        self._model.appendRow([
            QStandardItem(f"Field{r + 1}"),
            QStandardItem("string"),
            QStandardItem(""),
            QStandardItem(""),
        ])
        self._table.setCurrentIndex(self._model.index(r, 0))
        self._table.edit(self._model.index(r, 0))

    def _delete_row(self) -> None:
        r = self._selected_row()
        if r >= 0:
            self._model.removeRow(r)

    def _move_up(self) -> None:
        r = self._selected_row()
        if r > 0:
            row = [self._model.takeItem(r, c) for c in range(4)]
            self._model.removeRow(r)
            self._model.insertRow(r - 1, row)
            self._table.setCurrentIndex(self._model.index(r - 1, 0))

    def _move_down(self) -> None:
        r = self._selected_row()
        if 0 <= r < self._model.rowCount() - 1:
            row = [self._model.takeItem(r, c) for c in range(4)]
            self._model.removeRow(r)
            self._model.insertRow(r + 1, row)
            self._table.setCurrentIndex(self._model.index(r + 1, 0))


class RegisterEditorWidget(QWidget):
    """Редактор регістру (інформаційного або накопичення)."""

    applyRequested = Signal(dict)
    closeRequested = Signal()

    def __init__(
        self,
        title: str,
        payload: dict | None = None,
        *,
        obj_type: str = "register_info",   # register_info | register_accum
        vm: ConfiguratorViewModel | None = None,
        obj_guid: str = "",
    ) -> None:
        super().__init__()
        self._vm        = vm
        self._obj_guid  = str(obj_guid or "")
        self._obj_type  = obj_type
        self._payload   = RegisterPayload.from_payload(payload or {})

        self._shell = MetaObjectEditorShell(title=title)
        self._shell.applyRequested.connect(self._on_apply)
        self._shell.closeRequested.connect(self.closeRequested.emit)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._shell, 1)

        self._shell.set_sections(
            build_editor_sections(
                self._obj_type,
                {
                    "main": self._build_main_page,
                    "dimensions": self._build_dimensions_page,
                    "resources": self._build_resources_page,
                    "attributes": self._build_attributes_page,
                },
            )
        )
        self._load_to_ui()

    # ── Pages ─────────────────────────────────────────────────────────────────

    def _build_main_page(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(20, 20, 20, 20)
        g.setSpacing(10)
        g.setColumnStretch(1, 1)

        row = 0
        g.addWidget(QLabel(t("prop_name") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        self._ed_name = QLineEdit(); g.addWidget(self._ed_name, row, 1); row += 1

        g.addWidget(QLabel(t("prop_synonym") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        self._ed_synonym = QLineEdit(); g.addWidget(self._ed_synonym, row, 1); row += 1

        # Periodicity
        g.addWidget(QLabel(t("register.periodicity") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
        self._cmb_periodicity = QComboBox()
        for key in ("none", "second", "minute", "hour", "day", "month", "quarter", "year"):
            self._cmb_periodicity.addItem(t(f"register.period_{key}"), key)
        g.addWidget(self._cmb_periodicity, row, 1); row += 1

        # Register type (only for accum)
        if self._obj_type == "register_accum":
            g.addWidget(QLabel(t("register.type") + ":"), row, 0, Qt.AlignmentFlag.AlignRight)
            self._cmb_reg_type = QComboBox()
            self._cmb_reg_type.addItem(t("register.type_balance"),  "balance")
            self._cmb_reg_type.addItem(t("register.type_turnover"), "turnover")
            g.addWidget(self._cmb_reg_type, row, 1); row += 1

        g.addWidget(QLabel(t("prop_comment") + ":"), row, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self._ed_comment = QTextEdit(); self._ed_comment.setMaximumHeight(80)
        g.addWidget(self._ed_comment, row, 1); row += 1

        g.setRowStretch(row, 1)
        return w

    def _build_dimensions_page(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(10, 10, 10, 10)
        hint = QLabel(t("register.dimensions_hint"))
        hint.setWordWrap(True); hint.setObjectName("metaHint")
        l.addWidget(hint)
        self._w_dims = _FieldsTableWidget(self._payload.dimensions)
        l.addWidget(self._w_dims, 1)
        return w

    def _build_resources_page(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(10, 10, 10, 10)
        hint = QLabel(t("register.resources_hint"))
        hint.setWordWrap(True); hint.setObjectName("metaHint")
        l.addWidget(hint)
        self._w_resources = _FieldsTableWidget(self._payload.resources)
        l.addWidget(self._w_resources, 1)
        return w

    def _build_attributes_page(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(10, 10, 10, 10)
        hint = QLabel(t("register.attributes_hint"))
        hint.setWordWrap(True); hint.setObjectName("metaHint")
        l.addWidget(hint)
        self._w_attrs = _FieldsTableWidget(self._payload.attributes)
        l.addWidget(self._w_attrs, 1)
        return w

    # ── Load / Save ───────────────────────────────────────────────────────────

    def _load_to_ui(self) -> None:
        self._ed_name.setText(self._payload.name)
        self._ed_synonym.setText(self._payload.synonym)
        self._ed_comment.setPlainText(self._payload.comment)
        # Periodicity
        for i in range(self._cmb_periodicity.count()):
            if self._cmb_periodicity.itemData(i) == self._payload.periodicity:
                self._cmb_periodicity.setCurrentIndex(i)
                break
        if self._obj_type == "register_accum" and hasattr(self, "_cmb_reg_type"):
            for i in range(self._cmb_reg_type.count()):
                if self._cmb_reg_type.itemData(i) == self._payload.register_type:
                    self._cmb_reg_type.setCurrentIndex(i)
                    break

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
        self._payload = RegisterPayload.from_payload(payload or {})
        title = technical_object_name(meta.get("name"), payload=payload)
        if title:
            try:
                self._shell.set_title(title)
            except Exception:
                pass
        self._shell.set_sections(
            build_editor_sections(
                self._obj_type,
                {
                    "main": self._build_main_page,
                    "dimensions": self._build_dimensions_page,
                    "resources": self._build_resources_page,
                    "attributes": self._build_attributes_page,
                },
            )
        )
        self._load_to_ui()

    def _collect_payload(self) -> dict:
        self._payload.name       = self._ed_name.text().strip()
        self._payload.synonym    = self._ed_synonym.text().strip()
        self._payload.comment    = self._ed_comment.toPlainText().strip()
        self._payload.periodicity = self._cmb_periodicity.currentData() or "month"
        if self._obj_type == "register_accum" and hasattr(self, "_cmb_reg_type"):
            self._payload.register_type = self._cmb_reg_type.currentData() or "balance"
        self._payload.dimensions  = self._w_dims.get_data()
        self._payload.resources   = self._w_resources.get_data()
        self._payload.attributes  = self._w_attrs.get_data()
        return self._payload.to_patch()

    def _on_apply(self, _patch: dict) -> None:
        self.applyRequested.emit(self._collect_payload())
