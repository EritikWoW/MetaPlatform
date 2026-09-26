"""src.ui_qt.widgets.enumeration_editor — Enumeration metadata editor.

Перерахування (Enumeration) — фіксований список значень.
Редактор: назва, синонім, список значень (name + synonym).
"""
from __future__ import annotations

from src.configurator.domain.technical_names import technical_object_name

from dataclasses import dataclass, field
from typing import Any, Dict, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
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


@dataclass
class EnumValue:
    name:    str = ""
    synonym: str = ""
    comment: str = ""


@dataclass
class EnumerationPayload:
    name:    str = ""
    title:   str = ""
    synonym: str = ""
    comment: str = ""
    values:  List[EnumValue] = field(default_factory=list)

    @classmethod
    def from_payload(cls, p: dict) -> "EnumerationPayload":
        if not isinstance(p, dict):
            return cls()
        raw_vals = p.get("values") or []
        vals = []
        for v in raw_vals:
            if isinstance(v, dict):
                vals.append(EnumValue(
                    name    = str(v.get("name")    or ""),
                    synonym = str(v.get("synonym") or ""),
                    comment = str(v.get("comment") or ""),
                ))
            elif isinstance(v, str):
                vals.append(EnumValue(name=v))
        return cls(
            name    = str(p.get("name")    or ""),
            title   = str(p.get("title")   or ""),
            synonym = str(p.get("synonym") or ""),
            comment = str(p.get("comment") or ""),
            values  = vals,
        )

    def to_patch(self) -> dict:
        return {
            "name":    self.name,
            "title":   self.title,
            "synonym": self.synonym,
            "comment": self.comment,
            "values":  [{"name": v.name, "synonym": v.synonym, "comment": v.comment} for v in self.values],
        }


_COL_NAME    = 0
_COL_SYNONYM = 1
_COL_COMMENT = 2


class EnumerationEditorWidget(QWidget):
    """Редактор перерахування."""

    applyRequested = Signal(dict)
    closeRequested = Signal()

    def __init__(
        self,
        title: str,
        payload: dict | None = None,
        *,
        vm: ConfiguratorViewModel | None = None,
        obj_guid: str = "",
    ) -> None:
        super().__init__()
        self._vm       = vm
        self._obj_guid = str(obj_guid or "")
        self._payload  = EnumerationPayload.from_payload(payload or {})

        self._shell = MetaObjectEditorShell(title=title)
        self._shell.applyRequested.connect(self._on_apply)
        self._shell.closeRequested.connect(self.closeRequested.emit)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._shell, 1)

        self._shell.set_sections(
            build_editor_sections(
                "enumeration",
                {
                    "main": self._build_main_page,
                    "values": self._build_values_page,
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

        g.addWidget(QLabel(t("prop_comment") + ":"), row, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self._ed_comment = QTextEdit(); self._ed_comment.setMaximumHeight(80)
        g.addWidget(self._ed_comment, row, 1); row += 1

        g.setRowStretch(row, 1)
        return w

    def _build_values_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Toolbar
        bar = QHBoxLayout()
        btn_add    = QPushButton("＋ " + t("btn_add"))
        btn_delete = QPushButton("－ " + t("btn_delete"))
        btn_up     = QPushButton("▲")
        btn_down   = QPushButton("▼")
        btn_up.setFixedWidth(32); btn_down.setFixedWidth(32)
        btn_add.clicked.connect(self._on_add_value)
        btn_delete.clicked.connect(self._on_delete_value)
        btn_up.clicked.connect(self._on_move_up)
        btn_down.clicked.connect(self._on_move_down)
        bar.addWidget(btn_add); bar.addWidget(btn_delete)
        bar.addStretch(1)
        bar.addWidget(btn_up); bar.addWidget(btn_down)
        layout.addLayout(bar)

        # Table
        self._values_model = QStandardItemModel(0, 3)
        self._values_model.setHorizontalHeaderLabels([
            t("prop_name"), t("prop_synonym"), t("prop_comment"),
        ])
        self._values_table = QTableView()
        self._values_table.setModel(self._values_model)
        self._values_table.horizontalHeader().setSectionResizeMode(
            _COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        self._values_table.horizontalHeader().setSectionResizeMode(
            _COL_SYNONYM, QHeaderView.ResizeMode.Stretch)
        self._values_table.horizontalHeader().setSectionResizeMode(
            _COL_COMMENT, QHeaderView.ResizeMode.Stretch)
        self._values_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        layout.addWidget(self._values_table, 1)

        self._fill_values_table()
        return w

    # ── Data ──────────────────────────────────────────────────────────────────

    def _fill_values_table(self) -> None:
        self._values_model.removeRows(0, self._values_model.rowCount())
        for v in self._payload.values:
            self._values_model.appendRow([
                QStandardItem(v.name),
                QStandardItem(v.synonym),
                QStandardItem(v.comment),
            ])

    def _selected_row(self) -> int:
        idx = self._values_table.currentIndex()
        return idx.row() if idx.isValid() else -1

    def _on_add_value(self) -> None:
        row = self._values_model.rowCount()
        self._values_model.appendRow([
            QStandardItem(f"Value{row + 1}"),
            QStandardItem(""),
            QStandardItem(""),
        ])
        self._values_table.setCurrentIndex(self._values_model.index(row, 0))
        self._values_table.edit(self._values_model.index(row, 0))

    def _on_delete_value(self) -> None:
        r = self._selected_row()
        if r >= 0:
            self._values_model.removeRow(r)

    def _on_move_up(self) -> None:
        r = self._selected_row()
        if r > 0:
            row = [self._values_model.takeItem(r, c) for c in range(3)]
            self._values_model.removeRow(r)
            self._values_model.insertRow(r - 1, row)
            self._values_table.setCurrentIndex(self._values_model.index(r - 1, 0))

    def _on_move_down(self) -> None:
        r = self._selected_row()
        if 0 <= r < self._values_model.rowCount() - 1:
            row = [self._values_model.takeItem(r, c) for c in range(3)]
            self._values_model.removeRow(r)
            self._values_model.insertRow(r + 1, row)
            self._values_table.setCurrentIndex(self._values_model.index(r + 1, 0))

    # ── Load / Save ───────────────────────────────────────────────────────────

    def _load_to_ui(self) -> None:
        self._ed_name.setText(self._payload.name)
        self._ed_synonym.setText(self._payload.synonym)
        self._ed_comment.setPlainText(self._payload.comment)

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
        self._payload = EnumerationPayload.from_payload(payload or {})
        title = technical_object_name(meta.get("name"), payload=payload)
        if title:
            try:
                self._shell.set_title(title)
            except Exception:
                pass
        self._shell.set_sections(
            build_editor_sections(
                "enumeration",
                {
                    "main": self._build_main_page,
                    "values": self._build_values_page,
                },
            )
        )
        self._load_to_ui()

    def _collect_payload(self) -> dict:
        self._payload.name    = self._ed_name.text().strip()
        self._payload.synonym = self._ed_synonym.text().strip()
        self._payload.comment = self._ed_comment.toPlainText().strip()
        vals = []
        for r in range(self._values_model.rowCount()):
            name    = (self._values_model.item(r, _COL_NAME)    or QStandardItem()).text().strip()
            synonym = (self._values_model.item(r, _COL_SYNONYM) or QStandardItem()).text().strip()
            comment = (self._values_model.item(r, _COL_COMMENT) or QStandardItem()).text().strip()
            if name:
                vals.append(EnumValue(name=name, synonym=synonym, comment=comment))
        self._payload.values = vals
        return self._payload.to_patch()

    def _on_apply(self, _patch: dict) -> None:
        self.applyRequested.emit(self._collect_payload())
