from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QEvent, QMimeData, QModelIndex, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QStyleOptionViewItem,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QTabBar,
    QTabWidget,
    QWidget,
)

from src.client.forms.form_runtime_widget import FormRuntimeWidget
from src.configurator.domain.form_model import FormNode, form_node_is_visible
from src.ui_qt.i18n import t
from src.ui_qt.theme import ACCENT, BORDER, FG, PANEL, PANEL_2, SUBTLE
from src.ui_qt.widgets.form_designer_canvas import FORM_CONTROL_MIME, FORM_REQUISITE_MIME


@dataclass(frozen=True, slots=True)
class FormLockTarget:
    """Resolved storage lock target for a form component."""

    lock_key: str
    description: str


@dataclass(frozen=True, slots=True)
class FormElementTypeSpec:
    """A user-facing form element type and its initial model properties."""

    code: str
    control_type: str
    caption_key: str
    default_props: tuple[tuple[str, Any], ...] = ()
    default_title_key: str = ""

    def props(self) -> dict[str, Any]:
        return dict(self.default_props)

    def default_title(self) -> str:
        return t(self.default_title_key) if self.default_title_key else ""


FORM_ELEMENT_TYPE_SPECS: tuple[FormElementTypeSpec, ...] = (
    FormElementTypeSpec(
        "group_usual",
        "Container",
        "form_element_group_usual",
        (("layout", "vertical"), ("representation", "usual"), ("show_title", True)),
        "form_element_default_group_title",
    ),
    FormElementTypeSpec(
        "group_plain",
        "Container",
        "form_element_group_plain",
        (("layout", "vertical"), ("representation", "none"), ("show_title", False)),
    ),
    FormElementTypeSpec("group_pages", "Tabs", "form_element_group_pages"),
    FormElementTypeSpec("group_command_bar", "CommandBar", "form_element_group_command_bar"),
    FormElementTypeSpec("field", "TextBox", "form_element_field"),
    FormElementTypeSpec("button", "Button", "form_element_button"),
    FormElementTypeSpec("table", "Table", "form_element_table"),
    FormElementTypeSpec("decoration_label", "Label", "form_element_decoration_label"),
    FormElementTypeSpec("decoration_picture", "Picture", "form_element_decoration_picture"),
    FormElementTypeSpec("text_area", "TextArea", "form_ctl_textarea"),
    FormElementTypeSpec("number_field", "NumberBox", "form_ctl_numberbox"),
    FormElementTypeSpec("date_field", "DateBox", "form_ctl_datebox"),
    FormElementTypeSpec("choice_field", "ComboBox", "form_ctl_combobox"),
    FormElementTypeSpec("checkbox", "CheckBox", "form_ctl_checkbox"),
    FormElementTypeSpec("table_part", "TablePanel", "form_ctl_table_panel"),
    FormElementTypeSpec("status_bar", "StatusBar", "form_ctl_status_bar"),
)


class FormElementTypeDialog(QDialog):
    """1C-style modal chooser used by the form structure Add command."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        specs: tuple[FormElementTypeSpec, ...] = FORM_ELEMENT_TYPE_SPECS,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FormElementTypeDialog")
        self.setWindowTitle(t("form_element_type_dialog_title"))
        self.setModal(True)
        self.setMinimumSize(420, 430)
        self.resize(460, 500)
        self._specs_by_code = {spec.code: spec for spec in specs}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.type_list = QListWidget(self)
        self.type_list.setObjectName("FormElementTypeList")
        self.type_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.type_list.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.type_list.setMinimumSize(0, 220)
        self.type_list.setStyleSheet(
            f"""
            QListWidget#FormElementTypeList {{
                background: {PANEL_2};
                color: {FG};
                border: 1px solid {BORDER};
                border-radius: 6px;
                outline: none;
                padding: 4px;
            }}
            QListWidget#FormElementTypeList::item {{
                color: {FG};
                border-radius: 4px;
                padding: 7px 9px;
                margin: 1px;
            }}
            QListWidget#FormElementTypeList::item:hover {{
                background: {PANEL};
                color: {FG};
            }}
            QListWidget#FormElementTypeList::item:selected {{
                background: {ACCENT};
                color: white;
            }}
            QListWidget#FormElementTypeList::item:disabled {{
                color: {SUBTLE};
            }}
            """
        )
        for spec in specs:
            item = QListWidgetItem(t(spec.caption_key))
            item.setData(Qt.ItemDataRole.UserRole, spec.code)
            self.type_list.addItem(item)
        self.type_list.itemActivated.connect(lambda _item: self.accept())
        self.type_list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.type_list, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Help,
            parent=self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("btn_ok"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("btn_cancel"))
        self.buttons.button(QDialogButtonBox.StandardButton.Help).setText(t("btn_help"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.helpRequested.connect(self._show_help)
        layout.addWidget(self.buttons)

        if self.type_list.count():
            self.type_list.setCurrentRow(0)
            self.type_list.setFocus()

    def selected_spec(self) -> FormElementTypeSpec | None:
        item = self.type_list.currentItem()
        code = str(item.data(Qt.ItemDataRole.UserRole) or "").strip() if item is not None else ""
        return self._specs_by_code.get(code)

    def accept(self) -> None:
        if self.selected_spec() is None:
            return
        super().accept()

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            t("form_element_type_dialog_title"),
            t("form_element_type_dialog_help"),
        )


class FormToolboxList(QListWidget):
    """Toolbox that drags a control type via a custom mime."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FormDesignerToolbox")
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def startDrag(self, supportedActions: Qt.DropActions) -> None:  # noqa: N802
        it = self.currentItem()
        if it is None:
            return
        control_type = str(it.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not control_type:
            return
        drag = QDrag(self)
        md = QMimeData()
        md.setData(FORM_CONTROL_MIME, control_type.encode("utf-8"))
        drag.setMimeData(md)
        drag.exec(Qt.DropAction.CopyAction)


class FormRequisitesList(QTreeWidget):
    """Hierarchical object requisites panel with drag support."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FormDesignerRequisites")
        self.setColumnCount(3)
        self.setHeaderLabels(["Requisite", "Use always", "Type"])
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.setRootIsDecorated(True)
        self.setAlternatingRowColors(False)
        self.setUniformRowHeights(True)
        self.setIndentation(16)
        self.setAnimated(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    # QListWidget compatibility is retained for existing editor integrations.
    def addItem(self, item: QTreeWidgetItem) -> None:  # noqa: N802
        self.addTopLevelItem(item)

    def count(self) -> int:
        return self.topLevelItemCount()

    def item(self, index: int) -> QTreeWidgetItem | None:
        return self.topLevelItem(int(index))

    def setCurrentRow(self, index: int) -> None:  # noqa: N802
        self.setCurrentItem(self.topLevelItem(int(index)))

    def startDrag(self, supportedActions: Qt.DropActions) -> None:  # noqa: N802
        it = self.currentItem()
        if it is None:
            return
        req = it.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(req, dict) or not str(req.get("code") or "").strip():
            return

        drag = QDrag(self)
        md = QMimeData()
        try:
            payload = json.dumps(req, ensure_ascii=False)
        except Exception:
            payload = "{}"
        md.setData(FORM_REQUISITE_MIME, payload.encode("utf-8"))
        drag.setMimeData(md)
        drag.exec(Qt.DropAction.CopyAction)


class FormDesignerTreeWidget(QTreeWidget):
    """Tree view with internal drag-reorder support."""

    orderChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FormDesignerStructure")
        self.setHeaderHidden(True)
        self.setIndentation(18)
        self.setUniformRowHeights(True)
        self.setAnimated(False)
        self.setMouseTracking(True)
        self._hovered_branch = QModelIndex()
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._drop_validator: Callable[[str, str], bool] | None = None

    @staticmethod
    def _branch_button_rect(item_rect: QRect) -> QRect:
        side = max(10, min(14, item_rect.height() - 4))
        return QRect(
            item_rect.left() - side - 3,
            item_rect.center().y() - side // 2,
            side,
            side,
        )

    def drawBranches(self, painter: QPainter, rect: QRect, index: QModelIndex) -> None:  # noqa: N802
        if not index.isValid() or not self.model().hasChildren(index):
            return
        item_rect = self.visualRect(index)
        button = self._branch_button_rect(item_rect)
        hovered = index == self._hovered_branch
        expanded = self.isExpanded(index)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#40547A") if hovered else QColor("#2C3D5D"), 1.0))
        painter.setBrush(QBrush(QColor("#24345A") if hovered else QColor("#17233B")))
        painter.drawRoundedRect(QRectF(button), 3.0, 3.0)

        cx = float(button.center().x())
        cy = float(button.center().y())
        radius = 3.0
        points = (
            QPolygonF(
                [
                    QPointF(cx - radius, cy - 1.5),
                    QPointF(cx, cy + 1.5),
                    QPointF(cx + radius, cy - 1.5),
                ]
            )
            if expanded
            else QPolygonF(
                [
                    QPointF(cx - 1.5, cy - radius),
                    QPointF(cx + 1.5, cy),
                    QPointF(cx - 1.5, cy + radius),
                ]
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#D8E2F2"), 1.4))
        painter.drawPolyline(points)
        painter.restore()

    def drawRow(self, painter: QPainter, options: QStyleOptionViewItem, index: QModelIndex) -> None:  # noqa: N802
        selected = bool(self.selectionModel() and self.selectionModel().isSelected(index))
        if not selected:
            super().drawRow(painter, options, index)
            return

        item_rect = self.visualRect(index).adjusted(2, 0, -2, 0)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(91, 91, 214, 58)))
        painter.drawRoundedRect(QRectF(item_rect), 3.0, 3.0)
        painter.restore()

        clean_options = QStyleOptionViewItem(options)
        clean_options.state &= ~QStyle.StateFlag.State_Selected
        super().drawRow(painter, clean_options, index)

        # QTreeView still paints the selected decoration lane before the
        # delegate on some native styles. Clear that lane after the row is
        # rendered, then restore only our compact disclosure button.
        lane = QRect(
            0,
            item_rect.top(),
            max(0, item_rect.left()),
            item_rect.height(),
        )
        painter.fillRect(lane, QColor(PANEL_2))
        self.drawBranches(painter, lane, index)

    def _branch_index_at(self, pos) -> QModelIndex:
        index = self.indexAt(pos)
        if not index.isValid() or not self.model().hasChildren(index):
            return QModelIndex()
        return index if self._branch_button_rect(self.visualRect(index)).contains(pos) else QModelIndex()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        index = self._branch_index_at(event.position().toPoint())
        if index != self._hovered_branch:
            self._hovered_branch = QModelIndex(index)
            self.viewport().update()
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if index.isValid() else Qt.CursorShape.ArrowCursor
        )
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered_branch = QModelIndex()
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        index = self.indexAt(pos)
        branch_index = self._branch_index_at(pos)
        if branch_index.isValid() and event.button() == Qt.MouseButton.LeftButton:
            self.setExpanded(branch_index, not self.isExpanded(branch_index))
            event.accept()
            return
        if index.isValid() and pos.x() < self.visualRect(index).left():
            event.accept()
            return
        super().mousePressEvent(event)

    def set_drop_validator(self, validator: Callable[[str, str], bool] | None) -> None:
        self._drop_validator = validator

    def dropEvent(self, event) -> None:  # noqa: N802
        source = self.currentItem()
        try:
            target = self.itemAt(event.position().toPoint())
        except Exception:
            target = None
        parent = target
        if target is not None and self.dropIndicatorPosition() in {
            QAbstractItemView.DropIndicatorPosition.AboveItem,
            QAbstractItemView.DropIndicatorPosition.BelowItem,
        }:
            parent = target.parent()
        if parent is None:
            parent = self.topLevelItem(0)
        source_id = str(source.data(0, Qt.ItemDataRole.UserRole) or "").strip() if source is not None else ""
        parent_id = str(parent.data(0, Qt.ItemDataRole.UserRole) or "").strip() if parent is not None else ""
        if callable(self._drop_validator) and not self._drop_validator(source_id, parent_id):
            event.ignore()
            return
        super().dropEvent(event)
        if event.isAccepted():
            self.orderChanged.emit()


class _DesignerRuntimeSurface(FormRuntimeWidget):
    """Embedded runtime renderer with node selection hooks for the designer."""

    nodeActivated = Signal(str)
    addControlRequested = Signal(str, str, int, int)
    addRequisiteRequested = Signal(object, str, int, int)
    copyRequested = Signal(str)
    cutRequested = Signal(str)
    pasteRequested = Signal(str)
    duplicateRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(
        self,
        *,
        model: dict[str, Any],
        ctx=None,
        manifest_rows: list[dict[str, Any]] | None = None,
        access_checker=None,
        parent: QWidget | None = None,
    ) -> None:
        self._designer_wrap_by_id: dict[str, QWidget] = {}
        self._designer_active_node_id = ""
        super().__init__(
            model=model,
            embedded=True,
            show_hidden_controls=True,
            ctx=ctx,
            manifest_rows=manifest_rows,
            access_checker=access_checker,
            parent=parent,
        )
        self.setAcceptDrops(True)
        self.installEventFilter(self)

    @property
    def wrap_by_id(self) -> dict[str, QWidget]:
        return self._designer_wrap_by_id

    def widget_for_node(self, node_id: str) -> QWidget | None:
        return self._designer_wrap_by_id.get(str(node_id or ""))

    def _iter_direct_widgets(self, root: QWidget) -> list[QWidget]:
        try:
            return list(root.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly))
        except Exception:
            return []

    def _node_by_id(self, node_id: str) -> FormNode | None:
        target_id = str(node_id or "").strip()
        if not target_id:
            return None

        def walk(node: FormNode) -> FormNode | None:
            if str(node.id or "").strip() == target_id:
                return node
            for child in node.children:
                found = walk(child)
                if found is not None:
                    return found
            return None

        try:
            return walk(self._model.root)
        except Exception:
            return None

    def _node_chain_for_id(self, node_id: str) -> list[FormNode]:
        target_id = str(node_id or "").strip()
        if not target_id:
            return []

        def walk(node: FormNode) -> list[FormNode]:
            if str(node.id or "").strip() == target_id:
                return [node]
            for child in node.children:
                chain = walk(child)
                if chain:
                    return [node, *chain]
            return []

        try:
            return walk(self._model.root)
        except Exception:
            return []

    def _parent_id_for_node(self, node_id: str) -> str:
        chain = self._node_chain_for_id(node_id)
        if not chain:
            return "root"
        for node in reversed(chain):
            if str(node.type or "").strip() in {"Container", "Tabs"}:
                return str(node.id or "root").strip() or "root"
        return "root"

    def _drop_target_parent_id(self, obj: object) -> str:
        current = obj
        depth = 0
        while current is not None and depth < 12:
            node_id = ""
            if hasattr(current, "property"):
                try:
                    node_id = str(current.property("form_node_id") or "").strip()
                except Exception:
                    node_id = ""
            if node_id:
                parent_id = self._parent_id_for_node(node_id)
                return parent_id or "root"
            current = current.parent() if hasattr(current, "parent") else None
            depth += 1
        return "root"

    def _widget_at_drop_pos(self, obj: object, event: QEvent) -> object:
        """Return the most relevant widget under the drop point."""

        try:
            pos = event.position().toPoint() if hasattr(event, "position") else None
        except Exception:
            pos = None
        if pos is None:
            return obj

        candidate = None
        if isinstance(obj, QWidget):
            try:
                candidate = obj.childAt(pos) or obj
            except Exception:
                candidate = obj
        if candidate is None:
            try:
                candidate = self.childAt(pos)
            except Exception:
                candidate = None

        current = candidate
        depth = 0
        while current is not None and depth < 16:
            try:
                node_id = str(current.property("form_node_id") or "").strip() if hasattr(current, "property") else ""
            except Exception:
                node_id = ""
            if node_id:
                return current
            current = current.parent() if hasattr(current, "parent") else None
            depth += 1
        return candidate or obj

    def _handle_designer_drop(self, obj: object, event: QEvent) -> bool:
        mime = event.mimeData() if hasattr(event, "mimeData") else None
        if mime is None:
            return False
        has_control = bool(mime.hasFormat(FORM_CONTROL_MIME))
        has_req = bool(mime.hasFormat(FORM_REQUISITE_MIME))
        if not (has_control or has_req):
            return False

        try:
            pos = event.position().toPoint() if hasattr(event, "position") else None
        except Exception:
            pos = None
        x = int(pos.x()) if pos is not None else 0
        y = int(pos.y()) if pos is not None else 0

        drop_obj = self._widget_at_drop_pos(obj, event)
        parent_id = self._drop_target_parent_id(drop_obj)
        target_node = self._node_by_id(parent_id)
        if target_node is None:
            parent_id = "root"
            target_node = self._node_by_id("root")

        parent_layout = str((target_node.props or {}).get("layout") or "vertical").strip().lower() if target_node else "vertical"
        if parent_layout != "absolute":
            x = 0
            y = 0

        if has_control:
            try:
                raw = mime.data(FORM_CONTROL_MIME).data().decode("utf-8", errors="ignore").strip()
            except Exception:
                raw = ""
            if not raw:
                return False
            self.addControlRequested.emit(raw, parent_id, x, y)
        else:
            try:
                raw = mime.data(FORM_REQUISITE_MIME).data().decode("utf-8", errors="ignore")
                parsed = json.loads(raw)
            except Exception:
                parsed = None
            if not isinstance(parsed, dict):
                return False
            self.addRequisiteRequested.emit(parsed, parent_id, x, y)

        try:
            event.acceptProposedAction()
        except Exception:
            pass
        return True

    def _active_node_id_for(self, obj: object) -> str:
        node_id = ""
        if hasattr(obj, "property"):
            try:
                node_id = str(obj.property("form_node_id") or "").strip()
            except Exception:
                node_id = ""
        if node_id:
            self._designer_active_node_id = node_id
            return node_id
        return str(self._designer_active_node_id or "").strip()

    def _bind_click_targets(self, node_id: str, widget: QWidget) -> None:
        for target in [widget, *self._iter_direct_widgets(widget)]:
            existing = str(target.property("form_node_id") or "").strip()
            if existing and existing != node_id:
                continue
            target.setProperty("form_node_id", node_id)
            try:
                target.setAcceptDrops(True)
            except Exception:
                pass
            if not bool(target.property("form_node_click_bound")):
                target.installEventFilter(self)
                target.setProperty("form_node_click_bound", True)
            for child in self._iter_direct_widgets(target):
                self._bind_click_targets(node_id, child)

    def _wrap_built_node(self, node: FormNode, widget: QWidget) -> QWidget:
        frame = QFrame()
        frame.setObjectName("FormDesignerNodeWrap")
        frame.setFrameShape(QFrame.Shape.NoFrame)
        frame.setSizePolicy(widget.sizePolicy())
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(widget)
        group_variant = str(widget.property("mp_form_group_variant") or "")
        if group_variant:
            frame.setProperty("mp_form_group_variant", group_variant)
        frame.setProperty("form_node_id", str(node.id or ""))
        hidden_in_client = not form_node_is_visible(node)
        frame.setProperty("form_hidden_in_client", hidden_in_client)
        if hidden_in_client:
            frame.setToolTip(t("form_hidden_in_client_help"))
            frame.setStyleSheet(
                "QFrame#FormDesignerNodeWrap{background: rgba(245, 158, 11, 0.05); "
                "border: 1px dashed rgba(245, 158, 11, 0.76); border-radius: 10px;}"
            )
        else:
            frame.setStyleSheet(
                "QFrame#FormDesignerNodeWrap{background: transparent; border: 1px solid transparent; border-radius: 10px;}"
            )
        self._designer_wrap_by_id[str(node.id or "")] = frame
        self._bind_click_targets(str(node.id or ""), frame)
        return frame

    def _register_field_title_label(self, node: FormNode, label: QLabel) -> QLabel:
        label.setProperty("form_node_id", str(node.id or ""))
        if not bool(label.property("form_node_click_bound")):
            label.installEventFilter(self)
            label.setProperty("form_node_click_bound", True)
        return label

    def highlight_node(self, node_id: str) -> None:
        selected_id = str(node_id or "").strip()
        for nid, widget in list(self._designer_wrap_by_id.items()):
            if widget is None:
                continue
            if nid == selected_id:
                border_style = "dashed" if bool(widget.property("form_hidden_in_client")) else "solid"
                widget.setStyleSheet(
                    "QFrame#FormDesignerNodeWrap{background: rgba(37, 99, 235, 0.04); "
                    + "border: 1px " + border_style
                    + " rgba(37, 99, 235, 0.78); border-radius: 10px;}"
                )
            elif bool(widget.property("form_hidden_in_client")):
                widget.setStyleSheet(
                    "QFrame#FormDesignerNodeWrap{background: rgba(245, 158, 11, 0.05); "
                    "border: 1px dashed rgba(245, 158, 11, 0.76); border-radius: 10px;}"
                )
            else:
                widget.setStyleSheet(
                    "QFrame#FormDesignerNodeWrap{background: transparent; border: 1px solid transparent; border-radius: 10px;}"
                )

    def _is_tab_interaction_target(self, obj: object) -> bool:
        if isinstance(obj, (QTabWidget, QTabBar)):
            return True
        parent = obj.parent() if hasattr(obj, "parent") else None
        depth = 0
        while parent is not None and depth < 8:
            try:
                if bool(parent.property("mp_form_tabs")):
                    return True
            except Exception:
                pass
            parent = parent.parent() if hasattr(parent, "parent") else None
            depth += 1
        return False

    def eventFilter(self, obj: object, event: QEvent) -> bool:  # noqa: N802
        try:
            if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                mime = event.mimeData() if hasattr(event, "mimeData") else None
                if mime is not None and (mime.hasFormat(FORM_CONTROL_MIME) or mime.hasFormat(FORM_REQUISITE_MIME)):
                    try:
                        event.acceptProposedAction()
                    except Exception:
                        pass
                    return True
            if event.type() == QEvent.Type.Drop:
                if self._handle_designer_drop(obj, event):
                    return True
            if event.type() == QEvent.Type.KeyPress:
                key = int(event.key()) if hasattr(event, "key") else 0
                if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    node_id = self._active_node_id_for(obj)
                    if node_id and node_id != "root":
                        self.deleteRequested.emit(node_id)
                        return True
            if event.type() == QEvent.Type.ContextMenu:
                node_id = self._active_node_id_for(obj)
                if node_id:
                    menu = QMenu(self)
                    act_copy = menu.addAction("Copy")
                    act_cut = menu.addAction("Cut")
                    act_paste = menu.addAction("Paste")
                    act_duplicate = menu.addAction("Duplicate")
                    act_delete = menu.addAction("Delete")
                    can_edit_node = node_id != "root"
                    act_copy.setEnabled(can_edit_node)
                    act_cut.setEnabled(can_edit_node)
                    act_duplicate.setEnabled(can_edit_node)
                    act_delete.setEnabled(can_edit_node)
                    exec_fn = getattr(self, "_designer_context_menu_exec", None)
                    if callable(exec_fn):
                        chosen = exec_fn(menu, event.globalPos()) if hasattr(event, "globalPos") else exec_fn(menu, None)
                    else:
                        chosen = menu.exec(event.globalPos()) if hasattr(event, "globalPos") else None
                    if chosen is act_copy:
                        self.copyRequested.emit(node_id)
                        return True
                    if chosen is act_cut:
                        self.cutRequested.emit(node_id)
                        return True
                    if chosen is act_paste:
                        self.pasteRequested.emit(node_id)
                        return True
                    if chosen is act_duplicate:
                        self.duplicateRequested.emit(node_id)
                        return True
                    if chosen is act_delete:
                        self.deleteRequested.emit(node_id)
                        return True
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
                node_id = ""
                if hasattr(obj, "property"):
                    node_id = str(obj.property("form_node_id") or "").strip()
                if node_id:
                    self._designer_active_node_id = node_id
                    self.nodeActivated.emit(node_id)
                    if self._is_tab_interaction_target(obj):
                        return False
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)
