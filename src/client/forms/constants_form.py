from __future__ import annotations

"""src.client.forms.constants_form

Runtime UI for editing *values* of configuration Constants.

Important (1C-like invariant):
- Constant *definitions* live in the configuration Manifest (Configurator).
- Constant *values* live in runtime data tables.

This widget is a lightweight value editor. It does not change the manifest.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t


TABLE_CONSTANTS = "data_constants"


def _ensure_constants_table(db) -> None:
    """Create a simple runtime table for constant values if missing."""
    try:
        db.table(TABLE_CONSTANTS)
        return
    except Exception:
        pass

    schema = {
        "key": {"type": "str", "unique": True, "indexed": True},
        "value": {"type": "json"},
    }
    try:
        db.create_table(TABLE_CONSTANTS, schema=schema)
    except Exception:
        # Table may have been created concurrently.
        pass


def _find_constants(manifest_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in manifest_rows or []:
        if not isinstance(r, dict):
            continue
        if str(r.get("kind") or "").lower() != "object":
            continue
        if str(r.get("type") or "").lower() not in {"constant", "constants"}:
            continue
        out.append(r)
    # stable order by title/name
    out.sort(key=lambda x: (str(x.get("title") or x.get("name") or "").casefold(), str(x.get("name") or "").casefold()))
    return out


def _const_def(r: Dict[str, Any]) -> Dict[str, Any]:
    p = r.get("payload")
    if isinstance(p, dict) and isinstance(p.get("constant"), dict):
        return dict(p.get("constant") or {})
    return {}


class ConstantsForm(QWidget):
    """Value editor for Constants."""

    saved = Signal()

    def __init__(self, *, db=None, manifest_rows: Optional[List[Dict[str, Any]]] = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConstantsForm")
        self._db = db
        self._mrows = manifest_rows or []
        self._editors: dict[str, QWidget] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Header
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(QLabel(t("client_nav_constants")))
        header.addStretch(1)

        self.btn_save = QPushButton(t("btn_save"))
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._on_save)
        header.addWidget(self.btn_save)

        root.addLayout(header)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll, 1)

        host = QWidget()
        scroll.setWidget(host)
        self._form = QFormLayout(host)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        self._form.setHorizontalSpacing(12)
        self._form.setVerticalSpacing(8)

        self._build()

    # ---------------- UI build ----------------

    def _build(self) -> None:
        for i in reversed(range(self._form.rowCount())):
            self._form.removeRow(i)
        self._editors.clear()

        if self._db is None:
            self._form.addRow(QLabel(t("client_err_db_not_open")))
            self.btn_save.setEnabled(False)
            return

        _ensure_constants_table(self._db)

        constants = _find_constants(self._mrows)
        if not constants:
            self._form.addRow(QLabel(t("constants_form_no_constants")))
            self.btn_save.setEnabled(False)
            return

        self.btn_save.setEnabled(True)

        values = self._load_values()

        for r in constants:
            name = str(r.get("name") or "").strip()
            if not name:
                continue
            title = str(r.get("title") or name).strip()

            cdef = _const_def(r)
            dtype = str(cdef.get("data_type") or "string").strip().lower()

            editor = self._make_editor(dtype)
            self._editors[name] = editor

            # set current value
            if name in values:
                self._set_editor_value(editor, values.get(name))

            self._form.addRow(title + ":", editor)

    # ---------------- value i/o ----------------

    def _load_values(self) -> Dict[str, Any]:
        if self._db is None:
            return {}
        try:
            rows = self._db.table(TABLE_CONSTANTS).select() or []
        except Exception:
            return {}
        out: Dict[str, Any] = {}
        for r in rows:
            try:
                k = str(r.get("key") or "").strip()
                if not k:
                    continue
                out[k] = r.get("value")
            except Exception:
                continue
        return out

    def _on_save(self) -> None:
        if self._db is None:
            return

        _ensure_constants_table(self._db)
        # Upsert values
        for key, w in self._editors.items():
            val = self._get_editor_value(w)
            try:
                rows = self._db.table(TABLE_CONSTANTS).select(where={"key": key}) or []
                if rows:
                    self._db.table(TABLE_CONSTANTS).update({"key": key}, {"value": val})
                else:
                    self._db.table(TABLE_CONSTANTS).insert({"key": key, "value": val})
            except Exception:
                # best-effort: do not block saving all constants
                continue

        self.saved.emit()

    # ---------------- editor helpers ----------------

    @staticmethod
    def _make_editor(dtype: str) -> QWidget:
        if dtype == "number":
            sp = QDoubleSpinBox()
            sp.setDecimals(6)
            sp.setMinimum(-999_999_999)
            sp.setMaximum(999_999_999)
            sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return sp
        if dtype == "boolean":
            cb = QCheckBox("")
            cb.setTristate(False)
            return cb
        if dtype == "date":
            from PySide6.QtCore import QDate
            de = QDateEdit()
            de.setCalendarPopup(True)
            de.setDisplayFormat("dd.MM.yyyy")
            de.setDate(QDate.currentDate())
            de.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return de
        ed = QLineEdit()
        ed.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return ed

    @staticmethod
    def _set_editor_value(w: QWidget, val: Any) -> None:
        old = w.blockSignals(True)
        try:
            if isinstance(w, QLineEdit):
                w.setText("" if val is None else str(val))
            elif isinstance(w, QDoubleSpinBox):
                try:
                    w.setValue(float(val or 0))
                except Exception:
                    w.setValue(0.0)
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(val))
            elif isinstance(w, QDateEdit):
                from PySide6.QtCore import QDate
                d = QDate.fromString(str(val or ""), "yyyy-MM-dd")
                if d.isValid():
                    w.setDate(d)
        finally:
            w.blockSignals(old)

    @staticmethod
    def _get_editor_value(w: QWidget) -> Any:
        if isinstance(w, QLineEdit):
            return w.text()
        if isinstance(w, QDoubleSpinBox):
            return w.value()
        if isinstance(w, QCheckBox):
            return bool(w.isChecked())
        if isinstance(w, QDateEdit):
            return w.date().toString("yyyy-MM-dd")
        return ""
