from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class StructureInspectorWidget(QWidget):
    def __init__(self, *, title: str = "", guid: str = "", payload: dict[str, Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = str(title or "").strip()
        self._guid = str(guid or "").strip()
        self._payload = dict(payload or {})
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        head = QFrame(self)
        head.setObjectName("StructureInspectorHeader")
        head.setStyleSheet("""
            QFrame#StructureInspectorHeader {
                background: #FFFFFF;
                border: 1px solid rgba(0,0,0,0.08);
                border-radius: 10px;
            }
        """)
        head_l = QVBoxLayout(head)
        head_l.setContentsMargins(12, 10, 12, 10)
        head_l.setSpacing(4)

        title = QLabel(self._title or "Structure", head)
        title.setStyleSheet("font-size: 12pt; font-weight: 700; color: #0F172A;")
        meta = QLabel(self._guid or "No GUID", head)
        meta.setStyleSheet("color: #475569;")
        self._refs = QLabel("", head)
        self._refs.setObjectName("StructureInspectorRefs")
        self._refs.setStyleSheet("color: #64748B; font-size: 9pt;")
        head_l.addWidget(title)
        head_l.addWidget(meta)
        head_l.addWidget(self._refs)

        search_row = QHBoxLayout()
        self._search = QLineEdit(head)
        self._search.setObjectName("StructureInspectorSearch")
        self._search.setPlaceholderText("Search structure...")
        self._search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search, 1)
        head_l.addLayout(search_row)
        root.addWidget(head)

        splitter = QSplitter(Qt.Orientation.Vertical, self)

        form_page = QWidget(self)
        form_l = QVBoxLayout(form_page)
        form_l.setContentsMargins(0, 0, 0, 0)
        form_l.setSpacing(6)

        self._tree = QTreeWidget(form_page)
        self._tree.setObjectName("StructureInspectorTree")
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Key", "Value"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setRootIsDecorated(True)
        form_l.addWidget(self._tree, 1)
        layout_page = QWidget(self)
        layout_l = QVBoxLayout(layout_page)
        layout_l.setContentsMargins(0, 0, 0, 0)
        layout_l.setSpacing(6)

        self._layout_cells = QTableWidget(layout_page)
        self._layout_cells.setObjectName("StructureInspectorLayoutCells")
        self._layout_cells.setColumnCount(4)
        self._layout_cells.setHorizontalHeaderLabels(["row", "col", "text", "type"])
        self._layout_cells.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._layout_cells.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._layout_cells.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._layout_cells.setAlternatingRowColors(True)
        self._layout_cells.verticalHeader().setVisible(False)
        layout_l.addWidget(self._layout_cells, 1)

        self._layout_tree = QTreeWidget(layout_page)
        self._layout_tree.setObjectName("StructureInspectorLayoutTree")
        self._layout_tree.setColumnCount(2)
        self._layout_tree.setHeaderLabels(["Key", "Value"])
        self._layout_tree.setAlternatingRowColors(True)
        self._layout_tree.setUniformRowHeights(True)
        self._layout_tree.setRootIsDecorated(True)
        layout_l.addWidget(self._layout_tree, 1)
        raw_page = QWidget(self)
        raw_l = QVBoxLayout(raw_page)
        raw_l.setContentsMargins(0, 0, 0, 0)
        raw_l.setSpacing(6)

        self._module_text = QPlainTextEdit(raw_page)
        self._module_text.setObjectName("StructureInspectorModuleText")
        self._module_text.setReadOnly(True)
        self._module_text.setPlaceholderText("Module text is not available")
        self._module_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._module_text.setStyleSheet("background: #FFFFFF; border: 1px solid rgba(0,0,0,0.08); border-radius: 10px;")
        raw_l.addWidget(self._module_text, 1)
        diff_page = QWidget(self)
        diff_l = QVBoxLayout(diff_page)
        diff_l.setContentsMargins(0, 0, 0, 0)
        diff_l.setSpacing(6)

        self._diff_text = QPlainTextEdit(diff_page)
        self._diff_text.setObjectName("StructureInspectorDiffText")
        self._diff_text.setReadOnly(True)
        self._diff_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._diff_text.setStyleSheet("background: #FFFFFF; border: 1px solid rgba(0,0,0,0.08); border-radius: 10px;")
        diff_l.addWidget(self._diff_text, 1)
        self._mode_bar = QTabBar(self)
        self._mode_bar.setObjectName("StructureInspectorModeBar")
        self._mode_bar.setDrawBase(False)
        self._mode_bar.setMovable(False)
        self._mode_bar.setExpanding(False)
        self._mode_bar.addTab("Form Model")
        self._mode_bar.addTab("Layout Model")
        self._mode_bar.addTab("Module")
        self._mode_bar.addTab("Compare")

        self._mode_stack = QStackedWidget(self)
        self._mode_stack.addWidget(form_page)
        self._mode_stack.addWidget(layout_page)
        self._mode_stack.addWidget(raw_page)
        self._mode_stack.addWidget(diff_page)
        self._mode_bar.currentChanged.connect(self._mode_stack.setCurrentIndex)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(self._mode_bar, 0)
        root.addWidget(self._mode_stack, 1)

    def _populate(self) -> None:
        self._tree.clear()
        self._layout_tree.clear()
        self._layout_cells.setRowCount(0)
        if not self._payload:
            empty = QTreeWidgetItem(["payload", "empty"])
            self._tree.addTopLevelItem(empty)
            self._layout_tree.addTopLevelItem(QTreeWidgetItem(["layout", "empty"]))
            self._module_text.setPlainText("")
            self._diff_text.setPlainText("")
            self._refs.setText("")
            return

        form_item = QTreeWidgetItem(["form_model", self._value_preview(self._payload.get("form_model"))])
        layout_item = QTreeWidgetItem(["layout_model", self._value_preview(self._payload.get("layout_model"))])
        self._tree.addTopLevelItem(form_item)
        self._tree.addTopLevelItem(layout_item)
        self._populate_value(form_item, self._payload.get("form_model"))
        self._populate_value(layout_item, self._payload.get("layout_model"))

        self._populate_layout_view(self._payload.get("layout_model"))

        for key in sorted(self._payload.keys(), key=lambda x: str(x)):
            if key in {"module_text", "form_model", "layout_model"}:
                continue
            item = QTreeWidgetItem([str(key), self._value_preview(self._payload.get(key))])
            self._tree.addTopLevelItem(item)
            self._populate_value(item, self._payload.get(key))

        module_text = str(self._payload.get("module_text") or "").strip()
        if module_text:
            self._module_text.setPlainText(module_text)
        else:
            self._module_text.setPlainText("")

        refs: list[str] = []
        for key in ("form_model_ref", "layout_model_ref", "module_asset_key"):
            value = str(self._payload.get(key) or "").strip()
            if value:
                refs.append(f"{key}: {value}")
        self._refs.setText(" | ".join(refs))
        self._diff_text.setPlainText(self._build_diff_text())

        self._tree.expandToDepth(1)
        self._layout_tree.expandToDepth(1)

    def _populate_value(self, parent: QTreeWidgetItem, value: Any) -> None:
        if isinstance(value, dict):
            for key in sorted(value.keys(), key=lambda x: str(x)):
                child = QTreeWidgetItem([str(key), self._value_preview(value.get(key))])
                parent.addChild(child)
                self._populate_value(child, value.get(key))
        elif isinstance(value, list):
            for index, item_value in enumerate(value):
                child = QTreeWidgetItem([f"[{index}]", self._value_preview(item_value)])
                parent.addChild(child)
                self._populate_value(child, item_value)

    def _populate_layout_view(self, value: Any) -> None:
        if isinstance(value, dict):
            cells = value.get("cells")
            if isinstance(cells, list) and cells:
                self._layout_cells.setRowCount(len(cells))
                for row_idx, cell in enumerate(cells):
                    if not isinstance(cell, dict):
                        cell = {"value": cell}
                    self._layout_cells.setItem(row_idx, 0, QTableWidgetItem(str(cell.get("row") or "")))
                    self._layout_cells.setItem(row_idx, 1, QTableWidgetItem(str(cell.get("col") or "")))
                    self._layout_cells.setItem(row_idx, 2, QTableWidgetItem(str(cell.get("text") or cell.get("value") or "")))
                    self._layout_cells.setItem(row_idx, 3, QTableWidgetItem(str(cell.get("kind") or cell.get("type") or "")))
            layout_root = QTreeWidgetItem(["layout_model", self._value_preview(value)])
            self._layout_tree.addTopLevelItem(layout_root)
            self._populate_value(layout_root, value)
        elif isinstance(value, list):
            for index, item_value in enumerate(value):
                child = QTreeWidgetItem([f"[{index}]", self._value_preview(item_value)])
                self._layout_tree.addTopLevelItem(child)
                self._populate_value(child, item_value)
        else:
            self._layout_tree.addTopLevelItem(QTreeWidgetItem(["layout_model", self._value_preview(value)]))

    def _apply_filter(self, text: str) -> None:
        query = str(text or "").strip().casefold()
        self._filter_tree(self._tree, query)
        self._filter_tree(self._layout_tree, query)

    def _filter_tree(self, tree: QTreeWidget, query: str) -> None:
        def walk(item: QTreeWidgetItem) -> bool:
            label = f"{item.text(0)} {item.text(1)}".casefold()
            matched = not query or query in label
            child_match = False
            for idx in range(item.childCount()):
                if walk(item.child(idx)):
                    child_match = True
            visible = matched or child_match
            item.setHidden(not visible)
            if child_match:
                tree.expandItem(item)
            return visible

        for idx in range(tree.topLevelItemCount()):
            walk(tree.topLevelItem(idx))

    def _build_diff_text(self) -> str:
        form_value = self._payload.get("form_model")
        layout_value = self._payload.get("layout_model")
        form_paths = self._collect_paths(form_value, root_name="form_model")
        layout_paths = self._collect_paths(layout_value, root_name="layout_model")
        only_form = sorted(form_paths - layout_paths)
        only_layout = sorted(layout_paths - form_paths)
        common = len(form_paths & layout_paths)

        lines = [
            f"form_model paths: {len(form_paths)}",
            f"layout_model paths: {len(layout_paths)}",
            f"common paths: {common}",
            "",
            "Only in form_model:",
        ]
        lines.extend(f"  - {p}" for p in only_form[:80] or ["  (none)"])
        lines.append("")
        lines.append("Only in layout_model:")
        lines.extend(f"  - {p}" for p in only_layout[:80] or ["  (none)"])
        return "\n".join(lines)

    def _collect_paths(self, value: Any, *, root_name: str, max_depth: int = 4) -> set[str]:
        paths: set[str] = set()

        def walk(node: Any, prefix: str, depth: int) -> None:
            if depth > max_depth:
                return
            if isinstance(node, dict):
                if prefix:
                    paths.add(prefix)
                for key, child in node.items():
                    child_prefix = f"{prefix}.{key}" if prefix else str(key)
                    paths.add(child_prefix)
                    walk(child, child_prefix, depth + 1)
            elif isinstance(node, list):
                if prefix:
                    paths.add(prefix)
                for idx, child in enumerate(node):
                    child_prefix = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
                    paths.add(child_prefix)
                    walk(child, child_prefix, depth + 1)
            else:
                if prefix:
                    paths.add(prefix)

        walk(value, root_name, 0)
        return paths

    @staticmethod
    def _value_preview(value: Any) -> str:
        if isinstance(value, dict):
            if "kind" in value:
                return f"dict(kind={value.get('kind')!s})"
            if "type" in value:
                return f"dict(type={value.get('type')!s})"
            return f"dict({len(value)})"
        if isinstance(value, list):
            return f"list({len(value)})"
        if value is None:
            return ""
        return str(value)
