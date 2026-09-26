from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QBrush, QColor, QPainter, QStandardItem, QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QSizePolicy, QSplitter, QStyledItemDelegate,
    QTableView, QTextEdit, QToolButton, QVBoxLayout, QWidget,
    QPushButton,
)

from src.ui_qt.i18n import t


# ─── Colored status badge delegate ───────────────────────────────────────────

class _StatusDelegate(QStyledItemDelegate):
    """Renders a pill-shaped colored badge for status values."""

    _ACTIVE   = ("#DCFCE7", "#16A34A")
    _INACTIVE = ("#FEE2E2", "#DC2626")

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        is_active = not any(kw in text.lower() for kw in ("неакт", "inactive", "disabled"))
        bg_hex, fg_hex = self._ACTIVE if is_active else self._INACTIVE

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Selection background
        if int(option.state) & 0x0002:  # State_Selected
            painter.fillRect(option.rect, QColor("#EFF6FF"))

        # Badge dimensions
        badge_w = min(option.rect.width() - 16, 100)
        badge_h = 22
        x = option.rect.x() + (option.rect.width() - badge_w) // 2
        y = option.rect.y() + (option.rect.height() - badge_h) // 2

        from PySide6.QtCore import QRectF, QPointF, QRect
        badge_rect = QRectF(x, y, badge_w, badge_h)
        painter.setBrush(QBrush(QColor(bg_hex)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, 11, 11)

        # Dot indicator
        dot_cx = float(x + 14)
        dot_cy = float(y + badge_h / 2)
        painter.setBrush(QBrush(QColor(fg_hex)))
        painter.drawEllipse(QPointF(dot_cx, dot_cy), 3.5, 3.5)

        # Label
        f = painter.font()
        f.setPointSize(9)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor(fg_hex))
        text_rect = QRect(int(x + 24), int(y), int(badge_w - 28), int(badge_h))
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        painter.restore()

    def sizeHint(self, option, index) -> object:  # type: ignore[override]
        from PySide6.QtCore import QSize
        return QSize(110, 36)


# ─── SimpleTableView ─────────────────────────────────────────────────────────

class SimpleTableView(QWidget):
    """Demo catalog list view with toolbar + inline form panel."""

    # language=CSS
    _CSS = """
        QFrame#Toolbar {
            background: #FFFFFF;
            border-bottom: 1px solid rgba(0,0,0,0.07);
        }
        QFrame#FormPanel {
            background: #FFFFFF;
            border-left: 1px solid rgba(0,0,0,0.08);
        }
        QPushButton#BtnPrimary {
            background: #2563EB;
            color: #FFFFFF;
            border: none;
            border-radius: 8px;
            padding: 0 16px;
            font-weight: 600;
            font-size: 10pt;
        }
        QPushButton#BtnPrimary:hover  { background: #1D4ED8; }
        QPushButton#BtnPrimary:pressed { background: #1E40AF; }
        QPushButton#BtnSecondary, QToolButton#BtnSecondary {
            background: #FFFFFF;
            color: #374151;
            border: 1px solid rgba(0,0,0,0.14);
            border-radius: 8px;
            padding: 0 14px;
            font-size: 10pt;
        }
        QPushButton#BtnSecondary:hover, QToolButton#BtnSecondary:hover {
            background: #F1F5F9;
        }
        QLineEdit {
            background: #FFFFFF;
            border: 1px solid rgba(0,0,0,0.14);
            border-radius: 8px;
            padding: 5px 10px;
            color: #0F172A;
            font-size: 10pt;
        }
        QLineEdit:focus { border-color: #2563EB; }
        QTextEdit {
            background: #FFFFFF;
            border: 1px solid rgba(0,0,0,0.14);
            border-radius: 8px;
            padding: 6px;
            color: #0F172A;
            font-size: 10pt;
        }
        QCheckBox {
            color: #0F172A;
            font-size: 10pt;
            spacing: 8px;
        }
        QCheckBox::indicator {
            width: 16px; height: 16px;
            border: 2px solid rgba(0,0,0,0.2);
            border-radius: 4px;
            background: #FFFFFF;
        }
        QCheckBox::indicator:checked {
            background: #2563EB;
            border-color: #2563EB;
        }
        QTableView {
            background: #FFFFFF;
            border: none;
            gridline-color: transparent;
            alternate-background-color: #F8FAFC;
            selection-background-color: #EFF6FF;
            selection-color: #0F172A;
            font-size: 10pt;
        }
        QTableView::item { padding: 4px 12px; }
        QHeaderView::section {
            background: #F8FAFC;
            color: #374151;
            padding: 8px 12px;
            border: none;
            border-bottom: 2px solid rgba(0,0,0,0.07);
            font-weight: 600;
            font-size: 10pt;
        }
    """

    def __init__(self, *, title: str) -> None:
        super().__init__()
        self.title = title
        self.setStyleSheet(self._CSS)
        self._build_ui()

    # ── Build UI ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_separator())
        root.addWidget(self._build_body(), 1)

    def _build_separator(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setMaximumHeight(1)
        f.setStyleSheet("background: rgba(0,0,0,0.07);")
        return f

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("Toolbar")
        bar.setFixedHeight(52)
        l = QHBoxLayout(bar)
        l.setContentsMargins(16, 8, 16, 8)
        l.setSpacing(6)

        self._btn_create = QPushButton("+ " + t("client_btn_create"))
        self._btn_create.setObjectName("BtnPrimary")
        self._btn_create.setFixedHeight(34)

        def _sec(label: str) -> QPushButton:
            b = QPushButton(label)
            b.setObjectName("BtnSecondary")
            b.setFixedHeight(34)
            return b

        self._btn_edit   = _sec("✏  " + t("btn_edit"))
        self._btn_delete = _sec("🗑  " + t("btn_delete"))
        self._btn_update = _sec("↻  " + t("act_refresh"))

        for btn in (self._btn_create, self._btn_edit, self._btn_delete, self._btn_update):
            l.addWidget(btn)

        l.addStretch()

        self._search = QLineEdit()
        self._search.setPlaceholderText(t("client_search_ph"))
        self._search.setFixedHeight(34)
        self._search.setFixedWidth(220)
        l.addWidget(self._search)

        btn_more = QToolButton()
        btn_more.setText(t("client_more") + " ▾")
        btn_more.setObjectName("BtnSecondary")
        btn_more.setFixedHeight(34)
        btn_more.setFixedWidth(72)
        l.addWidget(btn_more)

        return bar

    def _build_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background: rgba(0,0,0,0.07); }")

        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_form_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        return splitter

    def _build_table(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet("QWidget { background: #FFFFFF; }")
        l = QVBoxLayout(container)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        model = QStandardItemModel(self)
        model.setHorizontalHeaderLabels([
            t("client_table_col_id") or "Код",
            t("client_table_col_name") or "Наименование",
            "Группа",
            "Статус",
        ])

        _groups   = ["Группа A", "Группа A", "Группа B", "Группа B",
                     "Группа C", "Группа C", "Группа A"]
        _statuses = ["Активен", "Активен", "Неактивен", "Активен",
                     "Активен", "Неактивен", "Активен"]

        for i in range(7):
            row = [
                QStandardItem(f"{i + 1:06d}"),
                QStandardItem(f"Элемент {i + 1}"),
                QStandardItem(_groups[i]),
                QStandardItem(_statuses[i]),
            ]
            for it in row:
                it.setEditable(False)
            model.appendRow(row)

        self.table.setModel(model)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 120)
        for r in range(model.rowCount()):
            self.table.setRowHeight(r, 40)

        self.table.setItemDelegateForColumn(3, _StatusDelegate())

        sel = self.table.selectionModel()
        sel.selectionChanged.connect(self._on_row_selected)
        # Select first row by default
        if model.rowCount():
            self.table.selectRow(0)

        l.addWidget(self.table)
        return container

    def _build_form_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("FormPanel")
        panel.setMinimumWidth(260)
        panel.setMaximumWidth(400)

        l = QVBoxLayout(panel)
        l.setContentsMargins(20, 16, 20, 16)
        l.setSpacing(12)

        # Header
        title = QLabel(t("client_catalog_item"))
        title.setStyleSheet("font-size: 11pt; font-weight: 700; color: #0F172A;")
        l.addWidget(title)

        # Action buttons
        btns = QHBoxLayout()
        btns.setSpacing(6)
        self._fp_btn_save_close = QPushButton(t("btn_save_close"))
        self._fp_btn_save_close.setObjectName("BtnPrimary")
        self._fp_btn_save_close.setFixedHeight(32)
        self._fp_btn_save = QPushButton(t("btn_save"))
        self._fp_btn_save.setObjectName("BtnSecondary")
        self._fp_btn_save.setFixedHeight(32)
        btn_more2 = QToolButton()
        btn_more2.setText(t("client_more") + " ▾")
        btn_more2.setObjectName("BtnSecondary")
        btn_more2.setFixedHeight(32)
        btn_more2.setFixedWidth(60)
        for b in (self._fp_btn_save_close, self._fp_btn_save, btn_more2):
            btns.addWidget(b)
        l.addLayout(btns)

        # Fields
        def _field_row(label: str, widget: QWidget) -> None:
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(label)
            lbl.setFixedWidth(100)
            lbl.setStyleSheet("color: #64748B; font-size: 10pt;")
            row.addWidget(lbl)
            row.addWidget(widget, 1)
            l.addLayout(row)

        self._fp_code = QLineEdit()
        self._fp_name = QLineEdit()
        _field_row(t("client_field_code"), self._fp_code)
        _field_row(t("client_field_name"), self._fp_name)

        comment_lbl = QLabel(t("client_field_comment"))
        comment_lbl.setStyleSheet("color: #64748B; font-size: 10pt;")
        l.addWidget(comment_lbl)
        self._fp_comment = QTextEdit()
        self._fp_comment.setFixedHeight(72)
        l.addWidget(self._fp_comment)

        self._fp_active      = QCheckBox(t("client_field_active"))
        self._fp_predefined  = QCheckBox(t("client_field_predefined"))
        self._fp_active.setChecked(True)
        l.addWidget(self._fp_active)
        l.addWidget(self._fp_predefined)

        l.addStretch()
        return panel

    # ── Interaction ──────────────────────────────────────────────────────────

    def _on_row_selected(self, selected, _deselected) -> None:
        indexes = selected.indexes()
        if not indexes:
            return
        row = indexes[0].row()
        model = self.table.model()

        def _cell(col: int) -> str:
            it = model.item(row, col)
            return it.text() if it else ""

        self._fp_code.setText(_cell(0))
        self._fp_name.setText(_cell(1))
        status = _cell(3)
        is_active = not any(kw in status.lower() for kw in ("неакт", "inactive"))
        self._fp_active.setChecked(is_active)
        self._fp_predefined.setChecked(False)
        self._fp_comment.setPlainText(f"Пример элемента справочника.")
