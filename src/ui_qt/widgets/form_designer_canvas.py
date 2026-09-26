"""Graphical canvas for Form Designer.

MVP goals:
  - absolute positioning canvas based on QGraphicsView
  - move + resize items with mouse
  - drag&drop add controls from toolbox
  - selection sync with the structure tree

The canvas edits geometry only for nodes that are direct children of
containers with layout == "absolute".

Designer UX additions:
  - Snap-to-grid for move/resize/drop.
  - Multi-selection alignment can be executed by callers via
    :meth:`FormDesignerCanvasView.align_selected`.

Notes:
  - The view uses PySide6 (Qt6). When changing enum values, always use
    scoped enums (e.g. QGraphicsView.DragMode.RubberBandDrag).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QContextMenuEvent,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QMenu,
)

FORM_CONTROL_MIME = "application/x-metaplatform-form-control"
FORM_REQUISITE_MIME = "application/x-metaplatform-form-requisite"


def _rect_handle_size() -> float:
    return 10.0


@dataclass(slots=True)
class CanvasItemInfo:
    node_id: str
    node_type: str
    parent_id: str


class FormControlItem(QGraphicsRectItem):
    """A selectable/movable/resizable rectangle representing a form node."""

    def __init__(
        self,
        *,
        node_id: str,
        node_type: str,
        title: str,
        rect: QRectF,
        view: "FormDesignerCanvasView",
    ) -> None:
        super().__init__(rect)
        self.node_id = str(node_id)
        self.node_type = str(node_type)
        self._title = str(title or "")
        self._view = view

        self._resizing = False
        self._press_scene = QPointF()
        self._orig_rect = QRectF()

        # IMPORTANT: use setFlag() so we don't overwrite previous flags.
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

    def set_title(self, title: str) -> None:
        self._title = str(title or "")
        self.update()

    def _handle_rect(self) -> QRectF:
        s = _rect_handle_size()
        r = self.rect()
        return QRectF(r.right() - s, r.bottom() - s, s, s)

    def _is_on_resize_handle(self, pos: QPointF) -> bool:
        return self._handle_rect().contains(pos)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:  # noqa: ARG002
        r = self.rect()
        painter.save()

        caption = self._title.strip() or f"{self.node_type}"

        if self.node_type == "Label":
            # Labels must look like labels: no white box, no border.
            if self.isSelected():
                pen = QPen(Qt.GlobalColor.black)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(QBrush(Qt.GlobalColor.transparent))
                painter.drawRect(r)
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.drawText(
                r.adjusted(2, 2, -2, -2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                caption,
            )

        elif self.node_type == "CommandBar":
            # Пісочний фон + кнопки
            painter.setPen(QPen(QColor("#b9a467"), 2 if self.isSelected() else 1))
            painter.setBrush(QBrush(QColor("#f4ebcc")))
            painter.drawRect(r)
            # Основна кнопка «Провести і закрити»
            btn_h = min(r.height() - 6, 24.0)
            btn_y = r.top() + (r.height() - btn_h) / 2
            b1 = QRectF(r.left() + 4, btn_y, 130, btn_h)
            painter.setBrush(QBrush(QColor("#5d4a1f")))
            painter.setPen(QPen(QColor("#3d2f12")))
            painter.drawRoundedRect(b1, 3, 3)
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.setFont(painter.font())
            f = painter.font(); f.setBold(True); painter.setFont(f)
            painter.drawText(b1, Qt.AlignmentFlag.AlignCenter, "Провести і закрити")
            f.setBold(False); painter.setFont(f)
            # Звичайна кнопка «Провести»
            b2 = QRectF(b1.right() + 4, btn_y, 68, btn_h)
            painter.setBrush(QBrush(QColor("#efe7cd")))
            painter.setPen(QPen(QColor("#b9a467")))
            painter.drawRoundedRect(b2, 3, 3)
            painter.setPen(QPen(QColor("#5d4a1f")))
            painter.drawText(b2, Qt.AlignmentFlag.AlignCenter, "Провести")
            # Роздільник
            sep_x = b2.right() + 6
            painter.setPen(QPen(QColor("#b9a467")))
            painter.drawLine(QPointF(sep_x, r.top() + 4), QPointF(sep_x, r.bottom() - 4))
            # «Всі дії ▾» справа
            all_w = 72.0
            b_all = QRectF(r.right() - all_w - 4, btn_y, all_w, btn_h)
            painter.setBrush(QBrush(QColor("#efe7cd")))
            painter.setPen(QPen(QColor("#b9a467")))
            painter.drawRoundedRect(b_all, 3, 3)
            painter.setPen(QPen(QColor("#5d4a1f")))
            painter.drawText(b_all, Qt.AlignmentFlag.AlignCenter, "Всі дії ▾")
            if self.isSelected():
                painter.setBrush(QBrush(Qt.GlobalColor.black))
                painter.drawRect(self._handle_rect())

        elif self.node_type == "TablePanel":
            pen = QPen(QColor("#b9a467"), 2 if self.isSelected() else 1)
            painter.setPen(pen)
            painter.setBrush(QBrush(Qt.GlobalColor.white))
            painter.drawRect(r)
            # Тулбар-смужка зверху
            tb_h = min(28.0, r.height() * 0.18)
            tb = QRectF(r.left(), r.top(), r.width(), tb_h)
            painter.setBrush(QBrush(QColor("#efe7cd")))
            painter.setPen(QPen(QColor("#ccb982")))
            painter.drawRect(tb)
            # Кнопки «Додати» / «Видалити»
            btn_h = tb_h - 6
            btn_y = tb.top() + 3
            for i, lbl in enumerate(["Додати", "Видалити"]):
                bx = tb.left() + 4 + i * 72
                br = QRectF(bx, btn_y, 66, btn_h)
                painter.setBrush(QBrush(QColor("#f4ebcc")))
                painter.setPen(QPen(QColor("#b9a467")))
                painter.drawRoundedRect(br, 2, 2)
                painter.setPen(QPen(QColor("#5d4a1f")))
                painter.drawText(br, Qt.AlignmentFlag.AlignCenter, lbl)
            # «Всі дії ▾»
            ba = QRectF(tb.right() - 66, btn_y, 62, btn_h)
            painter.setBrush(QBrush(QColor("#f4ebcc")))
            painter.setPen(QPen(QColor("#b9a467")))
            painter.drawRoundedRect(ba, 2, 2)
            painter.setPen(QPen(QColor("#5d4a1f")))
            painter.drawText(ba, Qt.AlignmentFlag.AlignCenter, "Всі дії ▾")
            # Заголовок таблиці
            hdr_h = min(20.0, (r.height() - tb_h) * 0.15)
            hdr = QRectF(r.left(), r.top() + tb_h, r.width(), hdr_h)
            painter.setBrush(QBrush(QColor("#efe7cd")))
            painter.setPen(QPen(QColor("#ccb982")))
            painter.drawRect(hdr)
            painter.setPen(QPen(QColor("#6b5320")))
            painter.drawText(hdr.adjusted(4, 0, -4, 0),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             "N  Колонка 1  Колонка 2  …")
            if self.isSelected():
                painter.setBrush(QBrush(Qt.GlobalColor.black))
                painter.drawRect(self._handle_rect())

        elif self.node_type == "StatusBar":
            painter.setPen(QPen(QColor("#b9a467"), 2 if self.isSelected() else 1))
            painter.setBrush(QBrush(QColor("#ece8d8")))
            painter.drawRect(r)
            # Підпис + поле ×3
            x = r.right() - 8
            for lbl_text in reversed(["Отримано:", "Витрачено:", "Перевитрата:"]):
                val_w = 72.0
                lbl_w_approx = len(lbl_text) * 6.5
                # value box
                x -= val_w
                val_r = QRectF(x, r.top() + 4, val_w, r.height() - 8)
                painter.setBrush(QBrush(QColor("#fffdf8")))
                painter.setPen(QPen(QColor("#b8aa76")))
                painter.drawRoundedRect(val_r, 2, 2)
                painter.setPen(QPen(QColor("#2e220f")))
                painter.drawText(val_r, Qt.AlignmentFlag.AlignCenter, "0")
                x -= 4
                # label
                x -= lbl_w_approx
                lbl_r = QRectF(x, r.top(), lbl_w_approx, r.height())
                painter.setPen(QPen(QColor("#6b5320")))
                painter.drawText(lbl_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                                 lbl_text)
                x -= 10
            if self.isSelected():
                painter.setBrush(QBrush(Qt.GlobalColor.black))
                painter.drawRect(self._handle_rect())

        else:
            pen = QPen(Qt.GlobalColor.black)
            pen.setWidth(2 if self.isSelected() else 1)
            painter.setPen(pen)
            painter.setBrush(QBrush(Qt.GlobalColor.white))
            painter.drawRect(r)

            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.drawText(
                r.adjusted(6, 4, -6, -4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                caption,
            )

            if self.isSelected():
                painter.setBrush(QBrush(Qt.GlobalColor.black))
                painter.drawRect(self._handle_rect())

        painter.restore()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        # Track last clicked item for alignment operations.
        try:
            self._view.notify_item_activated(self.node_id)
            self._view._set_last_modifiers(event.modifiers())
        except Exception:
            pass

        if event.button() == Qt.MouseButton.LeftButton and self._is_on_resize_handle(event.pos()):
            self._resizing = True
            self._press_scene = event.scenePos()
            self._orig_rect = QRectF(self.rect())
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        try:
            self._view._set_last_modifiers(event.modifiers())
        except Exception:
            pass

        if self._resizing:
            delta = event.scenePos() - self._press_scene
            new_w = max(24.0, self._orig_rect.width() + delta.x())
            new_h = max(24.0, self._orig_rect.height() + delta.y())

            new_w, new_h = self._view.snap_size(new_w, new_h)

            self.setRect(0.0, 0.0, float(new_w), float(new_h))
            self._view.request_geometry_sync(self.node_id, finalize=False)
            event.accept()
            return

        # Normal moving (ItemIsMovable handles it)
        super().mouseMoveEvent(event)
        self._view.snap_item_to_grid(self)
        try:
            self._view.preview_move_target(self.node_id)
        except Exception:
            pass
        self._view.request_geometry_sync(self.node_id, finalize=False)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        try:
            self._view._set_last_modifiers(event.modifiers())
        except Exception:
            pass

        if self._resizing:
            self._resizing = False
            self._view.request_geometry_sync(self.node_id, finalize=True)
            event.accept()
            return

        super().mouseReleaseEvent(event)
        self._view.snap_item_to_grid(self)
        self._view.request_geometry_sync(self.node_id, finalize=True)
        try:
            self._view.clear_drop_target()
        except Exception:
            pass


class RootResizeHandleItem(QGraphicsRectItem):
    """Resize handle for the root form (bottom-right corner)."""

    def __init__(self, view: "FormDesignerCanvasView") -> None:
        s = _rect_handle_size()
        super().__init__(QRectF(0.0, 0.0, s, s))
        self._view = view
        self._resizing = False
        self._press_scene = QPointF()
        self._orig_size: tuple[int, int] = (0, 0)

        self.setZValue(10_000)
        self.setBrush(QBrush(Qt.GlobalColor.black))
        self.setPen(QPen(Qt.GlobalColor.black))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        self._resizing = True
        self._press_scene = event.scenePos()
        self._orig_size = self._view.root_size
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if not self._resizing:
            return super().mouseMoveEvent(event)

        delta = event.scenePos() - self._press_scene
        desired_w = int(round(self._orig_size[0] + delta.x()))
        desired_h = int(round(self._orig_size[1] + delta.y()))

        min_w, min_h = self._view.compute_min_root_size()
        desired_w = max(min_w, desired_w)
        desired_h = max(min_h, desired_h)

        # Smooth preview only; commit on release.
        self._view.update_root_resize_preview(desired_w, desired_h)
        self._view.rootSizeChanged.emit(desired_w, desired_h, False)

        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if not self._resizing:
            return super().mouseReleaseEvent(event)

        self._resizing = False
        w, h = self._view.pending_root_size

        self._view.commit_root_resize(w, h)
        self._view.rootSizeChanged.emit(w, h, True)

        event.accept()


class FormDesignerCanvasView(QGraphicsView):
    """Canvas view used by FormDesignerWidget."""

    # Primary selection ("active" item). Empty string means cleared.
    selectionChanged = Signal(str)  # node_id
    # Selection set info, used to enable/disable alignment actions.
    selectionSetChanged = Signal(int, str)  # count, primary_id

    geometryChanged = Signal(str, int, int, int, int)  # live: node_id, x, y, w, h
    geometryCommitted = Signal(str, int, int, int, int)  # finalize only
    moveRequested = Signal(str, str, int, int, int, int)  # node_id, parent_id, x, y, w, h
    propertiesRequested = Signal(str)
    copyRequested = Signal(str)
    cutRequested = Signal(str)
    pasteRequested = Signal(str)
    duplicateRequested = Signal(str)
    deleteRequested = Signal(str)
    addControlRequested = Signal(str, str, int, int)  # control_type, parent_id, x, y
    addRequisiteRequested = Signal(object, str, int, int)  # requisite_dict, parent_id, x, y
    rootSizeChanged = Signal(int, int, bool)  # w, h, finalize

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        try:
            self.viewport().setAcceptDrops(True)
        except Exception:
            pass
        self.setRenderHints(self.renderHints() | QPainter.RenderHint.Antialiasing)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # Base mode: items can be dragged; rubber-band activates only when dragging empty area.
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        try:
            self.setRubberBandSelectionMode(Qt.ItemSelectionMode.IntersectsItemShape)
        except Exception:
            pass

        try:
            self.setFrameShape(QFrame.Shape.NoFrame)
        except Exception:
            pass
        try:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        except Exception:
            pass

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._scene.selectionChanged.connect(self._on_selection_changed)

        # Transparent scene background: the parent frame draws the window client.
        try:
            self.setBackgroundBrush(QBrush(Qt.GlobalColor.transparent))
            self._scene.setBackgroundBrush(QBrush(Qt.GlobalColor.transparent))
        except Exception:
            pass

        self._item_by_id: dict[str, FormControlItem] = {}
        self._parent_by_id: dict[str, str] = {}

        self._root_size = (1000, 700)
        self._root_border: Optional[QGraphicsPathItem] = None

        self._root_resize_handle: Optional[RootResizeHandleItem] = None
        self._root_resize_preview: Optional[QGraphicsPathItem] = None
        self._pending_root_size: tuple[int, int] = self._root_size

        self._rubber_active = False
        self._drop_target_id = ""

        # Grid/snap settings.
        self._grid_size = 10
        self._grid_snap_enabled = True
        self._grid_visible = True

        # Selection order helper.
        self._last_active_id = ""
        self._last_modifiers: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier

        # Prevent snapping during rebuild/programmatic operations.
        self._snap_suspend = 0

    # ---------------- grid/snap public API ----------------

    def grid_size(self) -> int:
        return int(self._grid_size)

    def set_grid_size(self, size: int) -> None:
        self._grid_size = max(2, int(size))
        self.viewport().update()

    def is_grid_snap_enabled(self) -> bool:
        return bool(self._grid_snap_enabled)

    def set_grid_snap_enabled(self, enabled: bool) -> None:
        self._grid_snap_enabled = bool(enabled)
        # If snapping is on, default to showing the grid.
        if self._grid_snap_enabled and self._grid_visible is False:
            self._grid_visible = True
        self.viewport().update()

    def is_grid_visible(self) -> bool:
        return bool(self._grid_visible)

    def set_grid_visible(self, visible: bool) -> None:
        self._grid_visible = bool(visible)
        self.viewport().update()

    def notify_item_activated(self, node_id: str) -> None:
        self._last_active_id = str(node_id or "").strip()

    # ---------------- internals ----------------

    def _set_last_modifiers(self, mods: Qt.KeyboardModifiers) -> None:
        try:
            self._last_modifiers = mods
        except Exception:
            self._last_modifiers = Qt.KeyboardModifier.NoModifier

    def _snap_enabled_effective(self) -> bool:
        if not self._grid_snap_enabled:
            return False
        # Hold Shift to temporarily disable snapping.
        try:
            return not bool(self._last_modifiers & Qt.KeyboardModifier.ShiftModifier)
        except Exception:
            return True

    def _snap_int(self, v: float) -> int:
        g = max(2, int(self._grid_size))
        return int(round(float(v) / g) * g)

    def snap_item_to_grid(self, item: FormControlItem) -> None:
        """Snap item position to grid, if enabled."""

        if self._snap_suspend > 0:
            return
        if not self._snap_enabled_effective():
            return

        p = item.pos()
        sx = self._snap_int(p.x())
        sy = self._snap_int(p.y())
        if sx != int(round(p.x())) or sy != int(round(p.y())):
            # Use float pos for Qt, but keep integral grid.
            item.setPos(float(sx), float(sy))

    def snap_size(self, w: float, h: float) -> tuple[float, float]:
        """Snap width/height to grid, if enabled."""

        if self._snap_suspend > 0:
            return float(w), float(h)
        if not self._snap_enabled_effective():
            return float(w), float(h)

        sw = max(24.0, float(self._snap_int(w)))
        sh = max(24.0, float(self._snap_int(h)))
        return sw, sh

    # ---------------- public API ----------------

    @property
    def root_size(self) -> tuple[int, int]:
        return int(self._root_size[0]), int(self._root_size[1])

    @property
    def pending_root_size(self) -> tuple[int, int]:
        return int(self._pending_root_size[0]), int(self._pending_root_size[1])

    def set_root_size(self, w: int, h: int) -> None:
        self._root_size = (max(200, int(w)), max(200, int(h)))
        self._scene.setSceneRect(0, 0, float(self._root_size[0]), float(self._root_size[1]))
        self._reposition_root_resize_handle(use_pending=False)
        self.update_responsive_transform()
        self.viewport().update()

    def update_responsive_transform(self) -> None:
        """Fit the design width into the viewport without changing model coordinates."""

        try:
            available_width = max(1, int(self.viewport().width()))
            design_width = max(1, int(self._root_size[0]))
            scale_x = min(1.0, available_width / float(design_width))
            self.resetTransform()
            self.scale(scale_x, 1.0)
        except Exception:
            pass

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.update_responsive_transform()

    def _parent_extent(self, parent_id: str) -> tuple[int, int]:
        parent_id = str(parent_id or "root").strip() or "root"
        if parent_id == "root":
            return self.root_size
        parent_item = self._item_by_id.get(parent_id)
        if parent_item is None:
            return self.root_size
        rect = parent_item.rect()
        return max(1, int(round(rect.width()))), max(1, int(round(rect.height())))

    def _clamp_geometry_to_parent(
        self,
        parent_id: str,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> tuple[int, int, int, int]:
        parent_w, parent_h = self._parent_extent(parent_id)
        w = max(1, min(int(w), parent_w))
        h = max(1, min(int(h), parent_h))
        x = max(0, min(int(x), parent_w - w))
        y = max(0, min(int(y), parent_h - h))
        return x, y, w, h

    def compute_min_root_size(self) -> tuple[int, int]:
        """Minimum root size: hard min + current content bounds."""

        hard_min_w, hard_min_h = 200, 200
        margin = 12.0

        max_right = 0.0
        max_bottom = 0.0

        for it in self._item_by_id.values():
            # Only top-level controls affect root size constraints.
            if self._parent_by_id.get(it.node_id) != "root":
                continue
            r = it.rect()
            max_right = max(max_right, it.pos().x() + r.width())
            max_bottom = max(max_bottom, it.pos().y() + r.height())

        min_w = max(hard_min_w, int(round(max_right + margin)))
        min_h = max(hard_min_h, int(round(max_bottom + margin)))
        return min_w, min_h

    def update_root_resize_preview(self, w: int, h: int) -> None:
        """Show dashed preview for root resize without committing."""

        w = int(w)
        h = int(h)
        self._pending_root_size = (w, h)

        if self._root_resize_preview is None:
            self._root_resize_preview = QGraphicsPathItem()
            self._root_resize_preview.setZValue(9_999)
            pen = QPen(Qt.GlobalColor.black)
            pen.setStyle(Qt.PenStyle.DashLine)
            self._root_resize_preview.setPen(pen)
            self._root_resize_preview.setBrush(QBrush(Qt.GlobalColor.transparent))
            self._scene.addItem(self._root_resize_preview)

        r = 10.0
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, float(w), float(h)), r, r)
        self._root_resize_preview.setPath(path)
        self._root_resize_preview.show()

        # Ensure preview isn't clipped.
        cur = self._scene.sceneRect()
        self._scene.setSceneRect(0, 0, float(max(cur.width(), w)), float(max(cur.height(), h)))

        self._reposition_root_resize_handle(use_pending=True)

    def commit_root_resize(self, w: int, h: int) -> None:
        """Commit root resize and hide preview."""

        self.request_root_resize(int(w), int(h), finalize=True)
        if self._root_resize_preview is not None:
            self._root_resize_preview.hide()

        self._scene.setSceneRect(0, 0, float(self._root_size[0]), float(self._root_size[1]))
        self._reposition_root_resize_handle(use_pending=False)

    def _ensure_root_resize_handle(self) -> None:
        if self._root_resize_handle is not None:
            return
        self._root_resize_handle = RootResizeHandleItem(self)
        self._scene.addItem(self._root_resize_handle)
        self._reposition_root_resize_handle(use_pending=False)

    def _reposition_root_resize_handle(self, *, use_pending: bool = False) -> None:
        if self._root_resize_handle is None:
            return
        size = self._pending_root_size if use_pending else self._root_size
        s = float(self._root_resize_handle.rect().width())
        self._root_resize_handle.setPos(float(size[0]) - s, float(size[1]) - s)

    def request_root_resize(self, w: int, h: int, *, finalize: bool) -> None:
        min_w, min_h = self.compute_min_root_size()
        new_w = max(min_w, int(w))
        new_h = max(min_h, int(h))
        self.set_root_size(new_w, new_h)
        self.rootSizeChanged.emit(self._root_size[0], self._root_size[1], bool(finalize))

    def _is_descendant_or_self(self, node_id: str, candidate_id: str) -> bool:
        nid = str(node_id or "").strip()
        cid = str(candidate_id or "").strip()
        if not nid or not cid:
            return False
        if nid == cid:
            return True
        parent_id = self._parent_by_id.get(cid, "")
        depth = 0
        while parent_id and depth < 64:
            if parent_id == nid:
                return True
            parent_id = self._parent_by_id.get(parent_id, "")
            depth += 1
        return False

    def _absolute_container_id_at_scene_pos(self, scene_pos: QPointF, *, exclude_node_id: str = "") -> str:
        try:
            candidates = self._scene.items(scene_pos)
        except Exception:
            candidates = []

        best_node_id = ""
        best_depth = -1
        best_area = float("inf")
        exclude_id = str(exclude_node_id or "").strip()

        for item in candidates:
            if not isinstance(item, FormControlItem):
                continue
            if item.node_type != "Container":
                continue
            if exclude_id and self._is_descendant_or_self(exclude_id, item.node_id):
                continue
            node = self._model_node_by_id(item.node_id)
            if node is None or str(getattr(node, "type", "") or "") != "Container":
                continue
            layout = str((getattr(node, "props", {}) or {}).get("layout") or "").strip().lower()
            if layout != "absolute":
                continue
            try:
                if not item.sceneBoundingRect().contains(scene_pos):
                    continue
                rect = item.sceneBoundingRect()
                area = float(max(1.0, rect.width() * rect.height()))
            except Exception:
                continue

            depth = 0
            current = item
            while current is not None and depth < 64:
                if isinstance(current, FormControlItem) and current.node_type == "Container":
                    depth += 1
                try:
                    current = current.parentItem()
                except Exception:
                    current = None

            if depth > best_depth or (depth == best_depth and area < best_area):
                best_node_id = item.node_id
                best_depth = depth
                best_area = area

        return best_node_id

    def _container_id_at_scene_pos(self, scene_pos: QPointF, *, exclude_node_id: str = "") -> str:
        """Return the nearest container under the cursor, regardless of layout."""

        try:
            candidates = self._scene.items(scene_pos)
        except Exception:
            candidates = []

        best_node_id = ""
        best_depth = -1
        best_area = float("inf")
        exclude_id = str(exclude_node_id or "").strip()

        for item in candidates:
            if not isinstance(item, FormControlItem):
                continue
            if item.node_type != "Container":
                continue
            if exclude_id and self._is_descendant_or_self(exclude_id, item.node_id):
                continue
            node = self._model_node_by_id(item.node_id)
            if node is None or str(getattr(node, "type", "") or "") != "Container":
                continue
            try:
                rect = item.sceneBoundingRect()
                area = float(max(1.0, rect.width() * rect.height()))
            except Exception:
                continue

            depth = 0
            current = item
            while current is not None and depth < 64:
                if isinstance(current, FormControlItem) and current.node_type == "Container":
                    depth += 1
                try:
                    current = current.parentItem()
                except Exception:
                    current = None

            if depth > best_depth or (depth == best_depth and area < best_area):
                best_node_id = item.node_id
                best_depth = depth
                best_area = area

        return best_node_id

    def _target_parent_id_for_drop(self, node_id: str, scene_pos: QPointF) -> str:
        current_parent = str(self._parent_by_id.get(str(node_id or "").strip(), "root") or "root")
        target_parent = self._container_id_at_scene_pos(scene_pos, exclude_node_id=node_id)
        if not target_parent:
            target_parent = self._absolute_container_id_at_scene_pos(scene_pos, exclude_node_id=node_id)
        if target_parent:
            return target_parent
        return current_parent

    def _model_node_by_id(self, node_id: str) -> Any | None:
        target_id = str(node_id or "").strip()
        if not target_id:
            return None
        root = getattr(self, "_model_root", None)
        if root is None:
            return None

        def walk(node: Any) -> Any | None:
            if str(getattr(node, "id", "") or "").strip() == target_id:
                return node
            for child in getattr(node, "children", []) or []:
                found = walk(child)
                if found is not None:
                    return found
            return None

        try:
            return walk(root)
        except Exception:
            return None

    def _drop_parent_id_for_scene_pos(self, scene_pos: QPointF) -> str:
        target_parent = self._container_id_at_scene_pos(scene_pos)
        if not target_parent:
            target_parent = self._absolute_container_id_at_scene_pos(scene_pos)
        if target_parent:
            return target_parent

        current_selection = self.primary_selected_id()
        if current_selection:
            node = self._model_node_by_id(current_selection)
            if node is not None and str(getattr(node, "type", "") or "") == "Container":
                layout = str((getattr(node, "props", {}) or {}).get("layout") or "").strip().lower()
                if layout == "absolute":
                    return current_selection
        return "root"

    def _set_drop_target_id(self, node_id: str) -> None:
        nid = str(node_id or "").strip()
        if nid == self._drop_target_id:
            return
        self._drop_target_id = nid
        self.viewport().update()

    def clear_drop_target(self) -> None:
        self._set_drop_target_id("")

    def preview_move_target(self, node_id: str) -> None:
        nid = str(node_id or "").strip()
        if not nid:
            return
        item = self._item_by_id.get(nid)
        if item is None:
            return
        try:
            scene_pos = item.mapToScene(item.rect().center())
        except Exception:
            return
        self._set_drop_target_id(self._drop_parent_id_for_scene_pos(scene_pos))

    def rebuild(self, *, model_root: Any) -> None:
        """Rebuild canvas from FormModel root node."""

        self._snap_suspend += 1
        try:
            self._model_root = model_root
            self._scene.clear()
            self._item_by_id.clear()
            self._parent_by_id.clear()
            self._root_resize_handle = None
            self._root_resize_preview = None

            root_props = getattr(model_root, "props", {}) or {}
            w = int(root_props.get("w") or 1000)
            h = int(root_props.get("h") or 700)
            self.set_root_size(w, h)

            self._root_border = None
            self._ensure_root_resize_handle()

            self._render_absolute_children(parent_item=None, parent_node=model_root)
        finally:
            self._snap_suspend = max(0, self._snap_suspend - 1)

    def select_node(self, node_id: str) -> None:
        nid = str(node_id or "").strip()
        it = self._item_by_id.get(nid)
        if it is None:
            return
        for i in self._scene.selectedItems():
            i.setSelected(False)
        it.setSelected(True)
        self.notify_item_activated(it.node_id)
        self.centerOn(it)

    def request_geometry_sync(self, node_id: str, *, finalize: bool = False) -> None:
        it = self._item_by_id.get(str(node_id or "").strip())
        if it is None:
            return
        x = int(round(it.pos().x()))
        y = int(round(it.pos().y()))
        r = it.rect()
        w = int(round(r.width()))
        h = int(round(r.height()))

        if finalize:
            scene_center = it.mapToScene(r.center())
            parent_id = self._target_parent_id_for_drop(it.node_id, scene_center)
            current_parent_id = str(self._parent_by_id.get(it.node_id, "root") or "root")
            if parent_id != current_parent_id:
                target_item = self._item_by_id.get(parent_id)
                if target_item is not None:
                    local = target_item.mapFromScene(it.scenePos())
                    x = int(round(local.x()))
                    y = int(round(local.y()))
                else:
                    x = int(round(it.scenePos().x()))
                    y = int(round(it.scenePos().y()))
                x, y, w, h = self._clamp_geometry_to_parent(parent_id, x, y, w, h)
                self.moveRequested.emit(it.node_id, parent_id, x, y, w, h)
                return
            x, y, w, h = self._clamp_geometry_to_parent(current_parent_id, x, y, w, h)
            it.setPos(float(x), float(y))
            it.setRect(0.0, 0.0, float(w), float(h))
            self.geometryCommitted.emit(it.node_id, x, y, w, h)
        else:
            self.geometryChanged.emit(it.node_id, x, y, w, h)

    def selected_ids(self) -> list[str]:
        return [i.node_id for i in self._scene.selectedItems() if isinstance(i, FormControlItem)]

    def primary_selected_id(self) -> str:
        selected = self.selected_ids()
        if not selected:
            return ""
        if self._last_active_id and self._last_active_id in selected:
            return self._last_active_id
        return selected[0]

    def _ordered_node_ids(self) -> list[str]:
        return [node_id for node_id in self._item_by_id.keys() if str(node_id or "").strip() and str(node_id or "").strip() != "root"]

    def _select_neighbor_node(self, step: int) -> None:
        ids = self._ordered_node_ids()
        if not ids:
            return
        current = self.primary_selected_id()
        if current not in ids:
            next_id = ids[0] if step >= 0 else ids[-1]
            self.select_node(next_id)
            return
        idx = ids.index(current)
        next_idx = (idx + step) % len(ids)
        next_id = ids[next_idx]
        self.select_node(next_id)

    def align_selected(self, edge: str) -> list[tuple[str, int, int, int, int]]:
        """Align selected items by an edge relative to the primary selected.

        Parameters
        ----------
        edge:
            One of: "left", "right", "top", "bottom".

        Returns
        -------
        list of tuples (node_id, x, y, w, h) for items that were moved.

        Notes
        -----
        The method only aligns items that share the same parent as the primary
        selected item, to avoid mixing coordinate systems.
        """

        edge = str(edge or "").strip().lower()
        if edge not in {"left", "right", "top", "bottom"}:
            return []

        items = [i for i in self._scene.selectedItems() if isinstance(i, FormControlItem)]
        if len(items) < 2:
            return []

        ref_id = self.primary_selected_id()
        ref = self._item_by_id.get(ref_id)
        if ref is None:
            return []

        parent_id = self._parent_by_id.get(ref_id, "root")

        ref_pos = ref.pos()
        ref_rect = ref.rect()
        ref_left = ref_pos.x()
        ref_top = ref_pos.y()
        ref_right = ref_left + ref_rect.width()
        ref_bottom = ref_top + ref_rect.height()

        moved: list[tuple[str, int, int, int, int]] = []

        # Alignment commands should be deterministic; do not use Shift modifier
        # as a temporary override here.
        snap_for_command = bool(self._grid_snap_enabled) and self._snap_suspend == 0

        for it in items:
            if it.node_id == ref_id:
                continue
            if self._parent_by_id.get(it.node_id, "root") != parent_id:
                continue

            p = it.pos()
            r = it.rect()
            new_x = p.x()
            new_y = p.y()

            if edge == "left":
                new_x = ref_left
            elif edge == "right":
                new_x = ref_right - r.width()
            elif edge == "top":
                new_y = ref_top
            elif edge == "bottom":
                new_y = ref_bottom - r.height()

            if snap_for_command:
                new_x = float(self._snap_int(new_x))
                new_y = float(self._snap_int(new_y))

            if int(round(new_x)) != int(round(p.x())) or int(round(new_y)) != int(round(p.y())):
                it.setPos(float(new_x), float(new_y))
                moved.append(
                    (
                        it.node_id,
                        int(round(it.pos().x())),
                        int(round(it.pos().y())),
                        int(round(r.width())),
                        int(round(r.height())),
                    )
                )

        return moved

    # ---------------- selection / events ----------------

    def _on_selection_changed(self) -> None:
        selected = [i for i in self._scene.selectedItems() if isinstance(i, FormControlItem)]
        count = len(selected)
        primary = self.primary_selected_id()

        self.selectionSetChanged.emit(count, primary)
        # Keep old signal for single-selection synchronization.
        self.selectionChanged.emit(primary)

    def _node_id_at_view_pos(self, pos) -> str:
        try:
            item = self.itemAt(pos)
        except Exception:
            item = None
        if isinstance(item, FormControlItem):
            return str(item.node_id or "").strip()
        if item is not None:
            try:
                parent = item.parentItem()
            except Exception:
                parent = None
            while parent is not None:
                if isinstance(parent, FormControlItem):
                    return str(parent.node_id or "").strip()
                try:
                    parent = parent.parentItem()
                except Exception:
                    parent = None
        return self.primary_selected_id()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._set_last_modifiers(event.modifiers())

        if event.button() == Qt.MouseButton.LeftButton:
            # Activate rubber band only if click starts on empty area.
            if self.itemAt(event.pos()) is None:
                self._rubber_active = True
                self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            else:
                self._rubber_active = False
                self.setDragMode(QGraphicsView.DragMode.NoDrag)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._set_last_modifiers(event.modifiers())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._set_last_modifiers(event.modifiers())

        super().mouseReleaseEvent(event)
        if self._rubber_active:
            self._rubber_active = False
            self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self._set_last_modifiers(event.modifiers())
        key = int(event.key()) if hasattr(event, "key") else 0
        mods = event.modifiers() if hasattr(event, "modifiers") else Qt.KeyboardModifier.NoModifier

        if bool(mods & Qt.KeyboardModifier.ControlModifier):
            if key == Qt.Key.Key_C:
                node_id = self.primary_selected_id()
                if node_id and node_id != "root":
                    self.copyRequested.emit(node_id)
                    event.accept()
                    return
            if key == Qt.Key.Key_X:
                node_id = self.primary_selected_id()
                if node_id and node_id != "root":
                    self.cutRequested.emit(node_id)
                    event.accept()
                    return
            if key == Qt.Key.Key_V:
                node_id = self.primary_selected_id() or "root"
                self.pasteRequested.emit(node_id)
                event.accept()
                return
            if key == Qt.Key.Key_D:
                node_id = self.primary_selected_id()
                if node_id and node_id != "root":
                    self.duplicateRequested.emit(node_id)
                    event.accept()
                    return
        if key in (Qt.Key.Key_F2, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            node_id = self.primary_selected_id()
            if node_id and node_id != "root":
                self.propertiesRequested.emit(node_id)
                event.accept()
                return
        step = 10 if bool(mods & Qt.KeyboardModifier.ShiftModifier) else 1
        dx = dy = 0
        if key == Qt.Key.Key_Left:
            dx = -step
        elif key == Qt.Key.Key_Right:
            dx = step
        elif key == Qt.Key.Key_Up:
            dy = -step
        elif key == Qt.Key.Key_Down:
            dy = step

        if dx or dy:
            node_id = self.primary_selected_id()
            if node_id and node_id != "root":
                item = self._item_by_id.get(node_id)
                if item is not None:
                    item.setPos(float(item.pos().x() + dx), float(item.pos().y() + dy))
                    self.snap_item_to_grid(item)
                    self.request_geometry_sync(node_id, finalize=True)
                    event.accept()
                    return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            node_id = self.primary_selected_id()
            if node_id and node_id != "root":
                self.deleteRequested.emit(node_id)
                event.accept()
                return
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            step = -1 if bool(mods & Qt.KeyboardModifier.ShiftModifier) or key == Qt.Key.Key_Backtab else 1
            self._select_neighbor_node(step)
            event.accept()
            return

        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        node_id = self._node_id_at_view_pos(event.pos())
        if not node_id:
            return super().contextMenuEvent(event)

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
        exec_fn = getattr(self, "_canvas_context_menu_exec", None)
        if callable(exec_fn):
            chosen = exec_fn(menu, event.globalPos())
        else:
            chosen = menu.exec(event.globalPos())
        if chosen is act_copy:
            self.copyRequested.emit(node_id)
            event.accept()
            return
        if chosen is act_cut:
            self.cutRequested.emit(node_id)
            event.accept()
            return
        if chosen is act_paste:
            self.pasteRequested.emit(node_id)
            event.accept()
            return
        if chosen is act_duplicate:
            self.duplicateRequested.emit(node_id)
            event.accept()
            return
        if chosen is act_delete:
            self.deleteRequested.emit(node_id)
            event.accept()
            return
        super().contextMenuEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawBackground(painter, rect)

        if not self._grid_visible or self._grid_size <= 1:
            return

        g = max(2, int(self._grid_size))
        # Build a subtle grid.
        pen = QPen(QColor(0, 0, 0, 28))
        pen.setCosmetic(True)
        painter.save()
        painter.setPen(pen)

        left = int(math.floor(rect.left() / g) * g)
        right = int(math.ceil(rect.right() / g) * g)
        top = int(math.floor(rect.top() / g) * g)
        bottom = int(math.ceil(rect.bottom() / g) * g)

        x = left
        while x <= right:
            painter.drawLine(float(x), rect.top(), float(x), rect.bottom())
            x += g

        y = top
        while y <= bottom:
            painter.drawLine(rect.left(), float(y), rect.right(), float(y))
            y += g

        painter.restore()

    # ---------------- rendering helpers ----------------

    def _render_absolute_children(self, *, parent_item: Optional[FormControlItem], parent_node: Any) -> None:
        props = getattr(parent_node, "props", {}) or {}
        layout = str(props.get("layout") or "vertical").strip().lower()
        if layout != "absolute":
            return

        for ch in getattr(parent_node, "children", []) or []:
            ch_props = getattr(ch, "props", {}) or {}
            x = int(ch_props.get("x") or 20)
            y = int(ch_props.get("y") or 20)
            w = int(ch_props.get("w") or 160)
            h = int(ch_props.get("h") or 28)
            parent_id = parent_item.node_id if parent_item is not None else "root"
            x, y, w, h = self._clamp_geometry_to_parent(parent_id, x, y, w, h)
            title = str(getattr(ch, "title", "") or getattr(ch, "name", "") or getattr(ch, "type", ""))

            item = FormControlItem(
                node_id=str(getattr(ch, "id", "")),
                node_type=str(getattr(ch, "type", "")),
                title=title,
                rect=QRectF(0, 0, max(1, w), max(1, h)),
                view=self,
            )

            # Do not snap on initial build.
            item.setPos(float(x), float(y))

            if parent_item is None:
                self._scene.addItem(item)
                self._parent_by_id[item.node_id] = "root"
            else:
                item.setParentItem(parent_item)
                self._parent_by_id[item.node_id] = parent_item.node_id

            self._item_by_id[item.node_id] = item

            if str(getattr(ch, "type", "")) == "Container":
                ch_layout = str(ch_props.get("layout") or "vertical").strip().lower()
                if ch_layout == "absolute":
                    self._render_absolute_children(parent_item=item, parent_node=ch)

    # ---------------- drag&drop ----------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(FORM_CONTROL_MIME) or event.mimeData().hasFormat(FORM_REQUISITE_MIME):
            event.acceptProposedAction()
            try:
                self._set_drop_target_id(self._drop_parent_id_for_scene_pos(self.mapToScene(event.position().toPoint())))
            except Exception:
                self._set_drop_target_id("")
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(FORM_CONTROL_MIME) or event.mimeData().hasFormat(FORM_REQUISITE_MIME):
            event.acceptProposedAction()
            try:
                self._set_drop_target_id(self._drop_parent_id_for_scene_pos(self.mapToScene(event.position().toPoint())))
            except Exception:
                self._set_drop_target_id("")
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drop_target_id("")
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        has_control = event.mimeData().hasFormat(FORM_CONTROL_MIME)
        has_req = event.mimeData().hasFormat(FORM_REQUISITE_MIME)
        if not (has_control or has_req):
            return super().dropEvent(event)

        control_type = ""
        req: dict[str, Any] | None = None

        if has_control:
            try:
                raw = bytes(event.mimeData().data(FORM_CONTROL_MIME)).decode("utf-8", errors="ignore").strip()
            except Exception:
                raw = ""
            if not raw:
                return
            control_type = raw
        else:
            try:
                raw = bytes(event.mimeData().data(FORM_REQUISITE_MIME)).decode("utf-8", errors="ignore")
            except Exception:
                raw = ""
            try:
                parsed = json.loads(raw)
                req = parsed if isinstance(parsed, dict) else None
            except Exception:
                req = None
            if not req:
                return

        self._set_last_modifiers(event.modifiers())
        scene_pos = self.mapToScene(event.position().toPoint())
        parent_id = self._drop_parent_id_for_scene_pos(scene_pos)

        if parent_id == "root":
            x = int(scene_pos.x())
            y = int(scene_pos.y())
        else:
            pit = self._item_by_id.get(parent_id)
            if pit is None:
                x = int(scene_pos.x())
                y = int(scene_pos.y())
                parent_id = "root"
            else:
                local = pit.mapFromScene(scene_pos)
                x = int(local.x())
                y = int(local.y())

        if self._snap_enabled_effective():
            x = self._snap_int(x)
            y = self._snap_int(y)

        if req is not None:
            self.addRequisiteRequested.emit(req, parent_id, x, y)
        else:
            self.addControlRequested.emit(control_type, parent_id, x, y)

        self._set_drop_target_id("")
        event.acceptProposedAction()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawForeground(painter, rect)
        target_id = str(self._drop_target_id or "").strip()
        if not target_id:
            return
        item = self._item_by_id.get(target_id)
        if item is None:
            return
        try:
            target_rect = item.sceneBoundingRect().adjusted(-3.0, -3.0, 3.0, 3.0)
        except Exception:
            return
        pen = QPen(QColor(59, 130, 246, 220))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.save()
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(target_rect, 8.0, 8.0)
        painter.restore()

    # ---------------- viewport helpers ----------------

    def reset_scroll(self) -> None:
        """Reset scrollbars to show the origin (0,0)."""

        try:
            self.horizontalScrollBar().setValue(0)
            self.verticalScrollBar().setValue(0)
        except Exception:
            pass

    def ensure_valid_viewport(self) -> None:
        """Ensure the current viewport intersects the root canvas.

        Qt may keep scroll positions after scene rebuilds; if the view ends up
        outside the root canvas, the user sees an empty area.
        """

        try:
            root = QRectF(0, 0, float(self._root_size[0]), float(self._root_size[1]))
            vis = self.mapToScene(self.viewport().rect()).boundingRect()
            if not vis.intersects(root.adjusted(-8.0, -8.0, 8.0, 8.0)):
                self.reset_scroll()
        except Exception:
            pass
