from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget


class _CircularProgressRing(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0
        self.setMinimumSize(116, 116)

    def setValue(self, value: int) -> None:
        self._value = max(0, min(100, int(value)))
        self.update()

    def value(self) -> int:
        return int(self._value)

    def sizeHint(self) -> QSize:
        return QSize(116, 116)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(10, 10, self.width() - 20, self.height() - 20)
        base_pen = QPen(QColor("#22304A"), 10)
        base_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(base_pen)
        painter.drawArc(rect, 0, 360 * 16)

        accent_pen = QPen(QColor("#5B5BD6"), 10)
        accent_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(accent_pen)
        span = int(-360 * 16 * (self._value / 100.0))
        painter.drawArc(rect, 90 * 16, span)

        painter.setPen(QColor("#E7EAF0"))
        percent_font = QFont(self.font())
        percent_font.setPointSize(max(11, percent_font.pointSize() + 4))
        percent_font.setBold(True)
        painter.setFont(percent_font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{self._value}%")


class CircularProgressDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._message_text = ""
        self._phase_text = ""
        self.setObjectName("CircularProgressDialog")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setModal(True)
        self.setFixedWidth(340)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(10)

        self._message_label = QLabel(self)
        self._message_label.setWordWrap(False)
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setFixedHeight(self._single_line_height(self._message_label))
        layout.addWidget(self._message_label)

        self._ring = _CircularProgressRing(self)
        layout.addWidget(self._ring, 0, Qt.AlignmentFlag.AlignCenter)

        self._phase_label = QLabel(self)
        self._phase_label.setWordWrap(False)
        self._phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._phase_label.setStyleSheet("color: #9AA4B2;")
        self._phase_label.setFixedHeight(self._single_line_height(self._phase_label))
        layout.addWidget(self._phase_label)

        self.setStyleSheet(
            """
            QDialog#CircularProgressDialog {
                background: #0F172A;
                color: #E7EAF0;
                border: 1px solid #22304A;
                border-radius: 14px;
            }
            QLabel {
                background: transparent;
                color: #E7EAF0;
            }
            """
        )

    @staticmethod
    def _single_line_height(label: QLabel) -> int:
        return label.fontMetrics().height() + 6

    def _apply_elided_text(self, label: QLabel, text: str) -> None:
        width = max(label.width(), self.width() - 40, 40)
        rendered = label.fontMetrics().elidedText(
            str(text or "").strip(),
            Qt.TextElideMode.ElideMiddle,
            width,
        )
        label.setText(rendered)
        label.setToolTip(str(text or "").strip())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elided_text(self._message_label, self._message_text)
        self._apply_elided_text(self._phase_label, self._phase_text)

    def setValue(self, value: int) -> None:
        self._ring.setValue(value)

    def setLabelText(self, text: str) -> None:
        self._message_text = str(text or "").strip()
        self._apply_elided_text(self._message_label, self._message_text)

    def setPhaseText(self, text: str) -> None:
        self._phase_text = str(text or "").strip()
        self._apply_elided_text(self._phase_label, self._phase_text)
