"""src.ui_qt.widgets.module_browser — All-modules browser for configurator.

Shows a flat, searchable list of every module in the project:
  ObjectModule / ManagerModule / FormModule / CommandModule / CommonModule

Double-click or Enter → opens CodeEditorWidget in parent MDI.

Layout:
  ┌────────────────────────────────────────────┐
  │ [🔍 Filter…]         [Refresh]             │
  ├────────────┬───────────────┬───────────────┤
  │ Object     │ Module kind   │ Lines  Modified│
  ├────────────┴───────────────┴───────────────┤
  │  Catalog.Товар / ObjectModule          245  │
  │  Document.Рахунок / FormModule  «Форма» 18  │
  │  …                                          │
  └────────────────────────────────────────────┘
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QSortFilterProxyModel, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t
from src.ui_qt.module_titles import localized_module_title


class ModuleBrowserWidget(QWidget):
    """Searchable flat list of all modules in the configurator database.

    Signals:
        open_module_requested(guid, title) — emitted on double-click / Enter
    """

    open_module_requested = Signal(str, str)   # guid, display-title

    # ── Column indices ──────────────────────────────────────────────────────
    COL_OWNER  = 0
    COL_MODULE = 1
    COL_LINES  = 2
    COL_VER    = 3

    def __init__(self, *, vm=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self.setObjectName("ModuleBrowserWidget")
        self._build_ui()
        self.refresh()

    # ── Public ──────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload modules from the database."""
        self._populate()

    def reload_from_vm(self) -> None:
        self.refresh()

    # ── Build ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # Toolbar
        bar = QHBoxLayout()
        self._filter = QLineEdit()
        self._filter.setPlaceholderText(t("module_browser_filter"))
        self._filter.textChanged.connect(self._on_filter)
        bar.addWidget(self._filter, 1)

        btn_refresh = QPushButton(t("btn_reload"))
        btn_refresh.setFixedWidth(80)
        btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(btn_refresh)

        btn_open = QPushButton(t("module_browser_open"))
        btn_open.setFixedWidth(80)
        btn_open.clicked.connect(self._on_open)
        bar.addWidget(btn_open)

        root.addLayout(bar)

        # Table
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels([
            t("module_browser_col_owner"),
            t("module_browser_col_kind"),
            t("module_browser_col_lines"),
            t("module_browser_col_version"),
        ])

        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)   # search all columns

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(True)
        self._table.doubleClicked.connect(self._on_open)
        root.addWidget(self._table, 1)

        # Status
        self._status_lbl = QLabel()
        root.addWidget(self._status_lbl)

    # ── Data ─────────────────────────────────────────────────────────────────

    def _populate(self) -> None:
        self._model.removeRows(0, self._model.rowCount())

        rows = self._load_module_rows()
        for row in rows:
            owner_item   = QStandardItem(row["owner_label"])
            kind_item    = QStandardItem(row["module_kind"])
            lines_item   = QStandardItem(str(row["lines"]) if row["lines"] >= 0 else "")
            ver_item     = QStandardItem(str(row["version"]) if row["version"] > 0 else "")

            # Store guid for opening
            owner_item.setData(row["guid"],  Qt.ItemDataRole.UserRole)
            owner_item.setData(row["title"], Qt.ItemDataRole.UserRole + 1)

            lines_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            ver_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self._model.appendRow([owner_item, kind_item, lines_item, ver_item])

        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setStretchLastSection(True)

        n = self._model.rowCount()
        self._status_lbl.setText(
            t("module_browser_count").format(n=n)
        )

    def _load_module_rows(self) -> List[Dict[str, Any]]:
        """Build flat list from manifest + modules table."""
        result: List[Dict[str, Any]] = []
        if self._vm is None:
            return result

        try:
            db = self._vm._service.require_db()
        except Exception:
            return result

        # Load manifest rows
        try:
            manifest = db.table("manifest").select() or []
        except Exception:
            return result

        # Build guid → owner label map
        obj_map: Dict[str, str] = {}
        for r in manifest:
            g = str(r.get("guid") or "")
            rtype = str(r.get("type") or "").lower()
            if rtype in ("catalog", "document", "report", "register_info",
                         "register_accum", "common_module", "common",
                         "data_processor", "form", "common_form"):
                payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
                if rtype == "common_module":
                    from src.ui_qt.module_titles import localized_code_name
                    label = localized_code_name(payload, r.get("name") or g)
                else:
                    label = str(r.get("title") or r.get("name") or g)
                obj_map[g] = f"{rtype.capitalize()}.{label}"

        # Load modules DAO rows
        try:
            from src.configurator.persistence.modules_dao import list_modules_by_owner
            all_guids = list(obj_map.keys())
        except Exception:
            all_guids = []

        # Also find module stubs in manifest
        for r in manifest:
            rtype = str(r.get("type") or "").lower()
            if rtype != "module":
                continue
            g = str(r.get("guid") or "")
            name = str(r.get("name") or "")
            pay = r.get("payload") or {}
            if isinstance(pay, dict):
                owner_g = str(pay.get("owner_guid") or "")
            else:
                owner_g = str(r.get("parent_guid") or "")

            # Find parent of parent (modules folder → object)
            # Walk up: stub.parent = modules_folder, modules_folder.parent = object
            parent_g = str(r.get("parent_guid") or "")
            folder_row = next((x for x in manifest
                               if str(x.get("guid") or "") == parent_g), None)
            obj_parent_g = str(folder_row.get("parent_guid") or "") if folder_row else ""
            owner_label = obj_map.get(obj_parent_g) or obj_map.get(owner_g) or owner_g

            # Try to get module text stats from modules_dao
            lines = -1
            version = 0
            try:
                from src.configurator.persistence.modules_dao import get_module_text
                text = get_module_text(db, module_guid=g)
                if text:
                    lines = text.count("\n") + 1
            except Exception:
                pass

            module_title = localized_module_title(name, payload=pay, fallback=name)
            display_title = f"{owner_label} / {module_title}"
            result.append({
                "guid":        g,
                "title":       display_title,
                "owner_label": owner_label,
                "module_kind": module_title,
                "lines":       lines,
                "version":     version,
            })

        result.sort(key=lambda x: (x["owner_label"], x["module_kind"]))
        return result

    # ── Actions ──────────────────────────────────────────────────────────────

    def _on_filter(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)

    def _on_open(self, *_) -> None:
        idx = self._table.currentIndex()
        if not idx.isValid():
            return
        src_idx = self._proxy.mapToSource(idx)
        item = self._model.item(src_idx.row(), self.COL_OWNER)
        if item is None:
            return
        guid  = str(item.data(Qt.ItemDataRole.UserRole) or "")
        title = str(item.data(Qt.ItemDataRole.UserRole + 1) or item.text())
        if guid:
            self.open_module_requested.emit(guid, title)
