"""src.client.forms.register_viewer — Register balance/turnover viewer.

Shows data from accumulation and information registers:
  - Balance view (залишки): groups by dimensions, shows totals
  - Turnover view (обороти): shows movements per period
  - Raw view: all rows sorted by date

Layout:
  ┌─────────────────────────────────────────────────────────┐
  │ Register: <title>          [Period: YYYY-MM] [Refresh]  │
  ├─────────────────────────────────────────────────────────┤
  │ Tab: Balance | Turnover | All movements                  │
  ├─────────────────────────────────────────────────────────┤
  │ <table with rows>                                        │
  └─────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QSortFilterProxyModel
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t


def _reg_tbl(reg_name: str) -> str:
    return f"data_reg_{reg_name.strip().lower()}"


class RegisterViewerWidget(QWidget):
    """Read-only viewer for an accumulation or info register."""

    def __init__(
        self,
        *,
        reg_name: str,
        reg_title: str = "",
        reg_type: str = "register_accum",   # register_accum | register_info
        db=None,
        manifest_rows: List[Dict] | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._name    = reg_name
        self._title   = reg_title or reg_name
        self._type    = reg_type
        self._db      = db
        self._mrows   = manifest_rows or []
        self.setObjectName("RegisterViewerWidget")
        self._build_ui()
        self.refresh()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Toolbar
        bar = QHBoxLayout()
        bar.addWidget(QLabel(f"<b>{self._title}</b>"), 1)

        bar.addWidget(QLabel(t("reg_period") + ":"))
        self._period_combo = QComboBox()
        self._period_combo.setFixedWidth(110)
        self._populate_period_combo()
        bar.addWidget(self._period_combo)

        btn_refresh = QPushButton(t("btn_reload"))
        btn_refresh.setFixedWidth(80)
        btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(btn_refresh)
        root.addLayout(bar)

        # Tabs
        self._tabs = QTabWidget()
        if self._type == "register_accum":
            self._tab_balance  = self._make_table_tab()
            self._tab_turnover = self._make_table_tab()
            self._tabs.addTab(self._tab_balance,  t("reg_tab_balance"))
            self._tabs.addTab(self._tab_turnover, t("reg_tab_turnover"))
        self._tab_all = self._make_table_tab()
        self._tabs.addTab(self._tab_all, t("reg_tab_all"))
        root.addWidget(self._tabs, 1)

        # Status
        self._status = QLabel()
        root.addWidget(self._status)

    def _make_table_tab(self) -> QTableView:
        from src.ui_qt.row_delegate import WholeRowHoverDelegate
        tv = QTableView()
        tv.setAlternatingRowColors(True)
        tv.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        tv.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        tv.verticalHeader().setVisible(False)
        tv.setSortingEnabled(True)
        tv.setItemDelegate(WholeRowHoverDelegate(tv))
        tv.setStyleSheet("""
            QTableView {
                selection-background-color: #DBEAFE;
                selection-color: #0F172A;
            }
            QTableView::item:selected {
                background: #DBEAFE;
                color: #0F172A;
            }
            QTableView::item:selected:hover {
                background: #DBEAFE;
                color: #0F172A;
            }
        """)
        return tv

    def _populate_period_combo(self) -> None:
        from datetime import date
        today = date.today()
        self._period_combo.clear()
        self._period_combo.addItem(t("reg_period_all"), "")
        for m in range(12):
            mo = (today.month - m - 1) % 12 + 1
            yr = today.year if today.month - m > 0 else today.year - 1
            label = f"{yr}-{mo:02d}"
            self._period_combo.addItem(label, label)

    # ── Data ──────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        period = self._period_combo.currentData() or ""
        rows = self._load_rows(period)
        self._populate_all(rows)
        if self._type == "register_accum":
            self._populate_balance(rows)
            self._populate_turnover(rows)
        self._status.setText(t("reg_total_rows").format(n=len(rows)))

    def _load_rows(self, period: str) -> List[Dict[str, Any]]:
        if self._db is None:
            return []
        try:
            tbl = self._db.table(_reg_tbl(self._name))
            all_rows = tbl.select() or []
            if period:
                all_rows = [r for r in all_rows
                            if str(r.get("_period") or r.get("_date") or "").startswith(period)]
            # Exclude deleted
            all_rows = [r for r in all_rows if not r.get("_deleted")]
            return all_rows
        except Exception:
            return []

    def _get_schema(self) -> Dict[str, List[str]]:
        """Return dimension and resource field names from manifest payload."""
        dims: List[str] = []
        resources: List[str] = []
        for r in self._mrows:
            if str(r.get("name") or "").lower() == self._name.lower():
                pay = r.get("payload") or {}
                if isinstance(pay, dict):
                    for attr in pay.get("attributes") or []:
                        if isinstance(attr, dict):
                            role = str(attr.get("role") or "dimension").lower()
                            name = str(attr.get("name") or attr.get("code") or attr.get("binding") or "").strip()
                            if role in ("dimension", "dim"):
                                dims.append(name)
                            else:
                                resources.append(name)
        return {"dims": dims, "resources": resources}

    def _populate_all(self, rows: List[Dict]) -> None:
        if not rows:
            self._tab_all.setModel(QStandardItemModel())
            return
        # Auto-discover columns from first row, put system cols first
        sys_cols = ["_period", "_date", "_doc_name", "_doc_guid", "_kind"]
        all_keys = list({k for row in rows for k in row.keys()})
        data_cols = [k for k in all_keys if k not in sys_cols and not k.startswith("_")]
        display_cols = [c for c in sys_cols if c in all_keys] + data_cols

        m = QStandardItemModel(len(rows), len(display_cols))
        m.setHorizontalHeaderLabels(display_cols)
        for ri, row in enumerate(rows):
            for ci, col in enumerate(display_cols):
                val = row.get(col, "")
                item = QStandardItem(str(val) if val is not None else "")
                item.setEditable(False)
                m.setItem(ri, ci, item)

        proxy = QSortFilterProxyModel()
        proxy.setSourceModel(m)
        self._tab_all.setModel(proxy)
        self._tab_all.resizeColumnsToContents()

    def _populate_balance(self, rows: List[Dict]) -> None:
        schema = self._get_schema()
        dims = schema["dims"] or [k for k in (rows[0].keys() if rows else [])
                                  if not k.startswith("_")][:3]
        resources = schema["resources"] or []

        if not dims:
            self._tab_balance.setModel(QStandardItemModel())
            return

        # Aggregate: group by dims, sum resources
        groups: Dict[tuple, Dict[str, float]] = {}
        for row in rows:
            key = tuple(str(row.get(d) or "") for d in dims)
            if key not in groups:
                groups[key] = {r: 0.0 for r in resources}
            for res in resources:
                try:
                    groups[key][res] += float(row.get(res) or 0)
                except (TypeError, ValueError):
                    pass

        cols = dims + resources
        m = QStandardItemModel(len(groups), len(cols))
        m.setHorizontalHeaderLabels(cols)
        for ri, (key, sums) in enumerate(sorted(groups.items())):
            for ci, dim in enumerate(dims):
                m.setItem(ri, ci, QStandardItem(key[ci]))
            for ci, res in enumerate(resources):
                m.setItem(ri, len(dims) + ci, QStandardItem(f"{sums[res]:,.2f}"))

        proxy = QSortFilterProxyModel()
        proxy.setSourceModel(m)
        self._tab_balance.setModel(proxy)
        self._tab_balance.resizeColumnsToContents()

    def _populate_turnover(self, rows: List[Dict]) -> None:
        """Group by period + dims, show in/out."""
        schema = self._get_schema()
        dims = schema["dims"] or []
        resources = schema["resources"] or []

        period_col = "_period" if any("_period" in r for r in rows) else "_date"
        group_by = [period_col] + dims

        groups: Dict[tuple, Dict[str, float]] = {}
        for row in rows:
            key = tuple(str(row.get(c) or "")[:7] for c in group_by)
            if key not in groups:
                groups[key] = {r: 0.0 for r in resources}
            for res in resources:
                try:
                    groups[key][res] += float(row.get(res) or 0)
                except (TypeError, ValueError):
                    pass

        cols = group_by + resources
        m = QStandardItemModel(len(groups), len(cols))
        m.setHorizontalHeaderLabels(cols)
        for ri, (key, sums) in enumerate(sorted(groups.items())):
            for ci, val in enumerate(key):
                m.setItem(ri, ci, QStandardItem(val))
            for ci, res in enumerate(resources):
                m.setItem(ri, len(group_by) + ci, QStandardItem(f"{sums[res]:,.2f}"))

        proxy = QSortFilterProxyModel()
        proxy.setSourceModel(m)
        self._tab_turnover.setModel(proxy)
        self._tab_turnover.resizeColumnsToContents()
