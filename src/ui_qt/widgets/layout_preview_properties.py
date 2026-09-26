from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t


class _LayoutCellPropertiesWidget(QWidget):
    cellFieldChanged = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._block = False
        self._current_cell: dict[str, Any] | None = None
        self._help_map: dict[QWidget, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QWidget()
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(8)

        self._title = QLabel(t("layout_prop_no_cell"))
        self._title.setStyleSheet("font-weight: 600; font-size: 9pt; padding: 4px 2px;")
        body_l.addWidget(self._title, 0)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        form.setHorizontalSpacing(10)

        self._address = QLabel("—")
        form.addRow(t("layout_prop_cell"), self._address)

        self._selection = QLabel("—")
        form.addRow(t("layout_prop_selection"), self._selection)

        self._fill_type = QComboBox()
        self._fill_type.setEditable(False)
        for value, label_key in (
            ("", "layout_fill_auto"),
            ("Template", "layout_fill_template"),
            ("Parameter", "layout_fill_parameter"),
            ("Value", "layout_fill_value"),
            ("Text", "layout_fill_text"),
        ):
            self._fill_type.addItem(t(label_key), value)
        self._fill_type.currentIndexChanged.connect(self._emit_fill_type)
        form.addRow(t("layout_prop_fill_type"), self._fill_type)

        self._border = QComboBox()
        self._border.setEditable(False)
        for value, label_key in (
            ("", "layout_border_auto"),
            ("none", "layout_border_none"),
            ("solid", "layout_border_solid"),
            ("thick", "layout_border_thick"),
        ):
            self._border.addItem(t(label_key), value)
        self._border.currentIndexChanged.connect(self._emit_border)
        form.addRow(t("layout_prop_border"), self._border)

        self._h_align = QComboBox()
        self._h_align.setEditable(False)
        for value, label_key in (
            ("", "layout_align_auto"),
            ("Left", "layout_align_left"),
            ("Center", "layout_align_center"),
            ("Right", "layout_align_right"),
        ):
            self._h_align.addItem(t(label_key), value)
        self._h_align.currentIndexChanged.connect(self._emit_h_align)
        form.addRow(t("layout_prop_h_align"), self._h_align)

        self._v_align = QComboBox()
        self._v_align.setEditable(False)
        for value, label_key in (
            ("", "layout_align_auto"),
            ("Top", "layout_align_top"),
            ("Center", "layout_align_middle"),
            ("Bottom", "layout_align_bottom"),
        ):
            self._v_align.addItem(t(label_key), value)
        self._v_align.currentIndexChanged.connect(self._emit_v_align)
        form.addRow(t("layout_prop_v_align"), self._v_align)

        self._parameter = QLineEdit()
        self._parameter.editingFinished.connect(self._emit_parameter)
        form.addRow(t("layout_prop_parameter"), self._parameter)

        self._text = QPlainTextEdit()
        self._text.setFixedHeight(88)
        self._text.textChanged.connect(self._emit_text)
        form.addRow(t("layout_prop_text"), self._text)

        self._format = QLabel("—")
        form.addRow(t("layout_prop_format"), self._format)

        self._merge = QLabel("—")
        form.addRow(t("layout_prop_merge"), self._merge)

        self._alignment = QLabel("—")
        form.addRow(t("layout_prop_alignment"), self._alignment)

        body_l.addLayout(form, 0)
        body_l.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self._help = QPlainTextEdit()
        self._help.setReadOnly(True)
        self._help.setFixedHeight(78)
        self._help.setObjectName("LayoutCellPropertiesHelp")
        self._help.setStyleSheet(
            "QPlainTextEdit#LayoutCellPropertiesHelp {"
            "border-top: 1px solid #2d3748;"
            "border-left: none; border-right: none; border-bottom: none;"
            "background: #0D1324;"
            "color: rgba(214, 223, 235, 0.78);"
            "padding: 8px 10px;"
            "}"
        )
        root.addWidget(self._help, 0)

        self._register_help(self._fill_type, "Як клітинка заповнюється: шаблоном, параметром, текстом або значенням.")
        self._register_help(self._border, "Стиль межі для вибраної клітинки.")
        self._register_help(self._h_align, "Горизонтальне вирівнювання вмісту клітинки.")
        self._register_help(self._v_align, "Вертикальне вирівнювання вмісту клітинки.")
        self._register_help(self._parameter, "Ім'я параметра макета, якщо клітинка заповнюється параметром.")
        self._register_help(self._text, "Текстовий вміст вибраної клітинки макета.")
        self._set_help_text("")
        self.set_cell(None)

    def _register_help(self, widget: QWidget, text: str) -> None:
        self._help_map[widget] = str(text or "")
        widget.installEventFilter(self)

    def _set_help_text(self, text: str) -> None:
        self._help.setPlainText(str(text or ""))

    def eventFilter(self, watched: object, event: object) -> bool:
        if isinstance(watched, QWidget) and watched in self._help_map and isinstance(event, QEvent):
            if event.type() == QEvent.Type.FocusIn:
                self._set_help_text(self._help_map.get(watched) or "")
        return super().eventFilter(watched, event)

    def set_cell(self, cell_info: Dict[str, Any] | None) -> None:
        self._block = True
        try:
            self._current_cell = dict(cell_info or {}) if isinstance(cell_info, dict) else None
            if not self._current_cell:
                self._title.setText(t("layout_prop_no_cell"))
                self._address.setText("—")
                self._selection.setText("—")
                self._format.setText("—")
                self._merge.setText("—")
                self._alignment.setText("—")
                self._parameter.clear()
                self._text.clear()
                self._fill_type.setCurrentIndex(0)
                self._border.setCurrentIndex(0)
                self._h_align.setCurrentIndex(0)
                self._v_align.setCurrentIndex(0)
                self._set_help_text("")
                self._set_enabled(False)
                return

            self._set_enabled(True)
            row = int(self._current_cell.get("row") or 0)
            col = int(self._current_cell.get("col") or 0)
            self._title.setText(f'{t("layout_prop_selected")}: R{row + 1}C{col + 1}')
            self._address.setText(f"R{row + 1}C{col + 1}")
            self._selection.setText(str(self._current_cell.get("selection_count") or 1))
            self._format.setText(str(self._current_cell.get("format_index", "—")))
            self._merge.setText(str(self._current_cell.get("merge") or "—"))
            self._alignment.setText(str(self._current_cell.get("alignment") or "—"))
            self._parameter.setText(str(self._current_cell.get("parameter") or ""))
            self._text.setPlainText(str(self._current_cell.get("text") or ""))
            fill_type = str(self._current_cell.get("fill_type") or "")
            idx = self._fill_type.findData(fill_type)
            if idx < 0:
                idx = self._fill_type.findText(fill_type)
            if idx < 0:
                idx = 0
            self._fill_type.setCurrentIndex(idx)
            border_style = str(self._current_cell.get("border_style") or "")
            idx = self._border.findData(border_style)
            self._border.setCurrentIndex(max(0, idx))
            h_align = str(self._current_cell.get("horizontal_alignment") or "")
            idx = self._h_align.findData(h_align)
            self._h_align.setCurrentIndex(max(0, idx))
            v_align = str(self._current_cell.get("vertical_alignment") or "")
            idx = self._v_align.findData(v_align)
            self._v_align.setCurrentIndex(max(0, idx))
        finally:
            self._block = False

    def _set_enabled(self, enabled: bool) -> None:
        self._fill_type.setEnabled(enabled)
        self._border.setEnabled(enabled)
        self._h_align.setEnabled(enabled)
        self._v_align.setEnabled(enabled)
        self._parameter.setEnabled(enabled)
        self._text.setEnabled(enabled)

    def commit_pending_changes(self) -> None:
        if self._block or not self._current_cell:
            return
        self.cellFieldChanged.emit("parameter", self._parameter.text())
        self.cellFieldChanged.emit("text", self._text.toPlainText())

    def _emit_fill_type(self, _index: int) -> None:
        if self._block or not self._current_cell:
            return
        self.cellFieldChanged.emit("fill_type", self._fill_type.currentData())

    def _emit_border(self, _index: int) -> None:
        if self._block or not self._current_cell:
            return
        self.cellFieldChanged.emit("border_style", self._border.currentData())

    def _emit_h_align(self, _index: int) -> None:
        if self._block or not self._current_cell:
            return
        self.cellFieldChanged.emit("horizontal_alignment", self._h_align.currentData())

    def _emit_v_align(self, _index: int) -> None:
        if self._block or not self._current_cell:
            return
        self.cellFieldChanged.emit("vertical_alignment", self._v_align.currentData())

    def _emit_parameter(self) -> None:
        if self._block or not self._current_cell:
            return
        self.cellFieldChanged.emit("parameter", self._parameter.text())

    def _emit_text(self) -> None:
        if self._block or not self._current_cell:
            return
        self.cellFieldChanged.emit("text", self._text.toPlainText())
