from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class _SplashCanvas(QFrame):
    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap(pixmap)
        self.setObjectName("SplashCanvas")

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        if not self._pixmap.isNull():
            painter.drawPixmap(self.rect(), self._pixmap)
        else:
            painter.fillRect(self.rect(), Qt.GlobalColor.black)
        super().paintEvent(event)


class AppSplash(QWidget):
    TITLE_H = 34

    def __init__(self, pixmap: QPixmap):
        super().__init__(
            None,
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint,
        )
        self.setObjectName("AppSplash")
        self.setWindowTitle("MetaPlatform")
        self._pixmap = QPixmap(pixmap)
        self._bar_phase: float = 0.0
        self._drag_offset: QPoint | None = None

        if not self._pixmap.isNull():
            self.setFixedSize(self._pixmap.width(), self._pixmap.height() + self.TITLE_H)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setStyleSheet(
            """
            QWidget#AppSplash {
                background: #081225;
                border: 1px solid rgba(255,255,255,20);
                border-radius: 10px;
            }
            QFrame#SplashTitleBar {
                background: #0A1426;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                border-bottom: 1px solid rgba(255,255,255,20);
            }
            QLabel#SplashTitle {
                color: #E7EAF0;
                font-size: 10pt;
                font-weight: 600;
                background: transparent;
            }
            QPushButton#SplashMinimize {
                background: transparent;
                color: #9FB0C8;
                border: none;
                border-radius: 6px;
                font-size: 12pt;
                font-weight: 700;
                min-width: 28px;
                max-width: 28px;
                min-height: 24px;
                max-height: 24px;
            }
            QPushButton#SplashMinimize:hover {
                background: rgba(255,255,255,18);
                color: #FFFFFF;
            }
            QPushButton#SplashMinimize:pressed {
                background: rgba(255,255,255,26);
            }
            QFrame#SplashCanvas {
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
                background: transparent;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._title_bar = QFrame(self)
        self._title_bar.setObjectName("SplashTitleBar")
        self._title_bar.setFixedHeight(self.TITLE_H)
        title_row = QHBoxLayout(self._title_bar)
        title_row.setContentsMargins(12, 0, 8, 0)
        title_row.setSpacing(8)

        self._title = QLabel("MetaPlatform", self._title_bar)
        self._title.setObjectName("SplashTitle")
        title_row.addWidget(self._title, 1)

        self._btn_min = QPushButton("—", self._title_bar)
        self._btn_min.setObjectName("SplashMinimize")
        self._btn_min.clicked.connect(self.showMinimized)
        title_row.addWidget(self._btn_min, 0, Qt.AlignmentFlag.AlignRight)
        root.addWidget(self._title_bar, 0)

        self._canvas = _SplashCanvas(self._pixmap, self)
        root.addWidget(self._canvas, 1)

        self._label = QLabel(self._canvas)
        self._label.setObjectName("SplashText")
        self._label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._label.setStyleSheet(
            "color: #E7EAF0; "
            "font-size: 9pt; "
            "font-weight: 600; "
            "background: transparent;"
        )

        self._bar = QProgressBar(self._canvas)
        self._bar.setObjectName("SplashProgress")
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)

        self._anim = QTimer(self)
        self._anim.setInterval(70)
        self._anim.timeout.connect(self._animate_bar)
        self._anim.start()

        self._apply_bar_style()
        self._relayout()

    def _apply_bar_style(self) -> None:
        phase = max(0.0, min(1.0, float(self._bar_phase)))
        band_a = max(0.0, phase - 0.18)
        band_b = max(0.0, phase - 0.06)
        band_c = min(1.0, phase + 0.06)
        band_d = min(1.0, phase + 0.18)
        self._bar.setStyleSheet(
            f"""
            QProgressBar {{
                background: rgba(255,255,255,24);
                border: 1px solid rgba(255,255,255,42);
                border-radius: 7px;
            }}
            QProgressBar::chunk {{
                border-radius: 7px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1E7BFF,
                    stop:{band_a:.3f} #1E7BFF,
                    stop:{band_b:.3f} #39C4FF,
                    stop:{phase:.3f} #8B64FF,
                    stop:{band_c:.3f} #39C4FF,
                    stop:{band_d:.3f} #1E7BFF,
                    stop:1 #1E7BFF
                );
            }}
            """
        )

    def _animate_bar(self) -> None:
        self._bar_phase += 0.035
        if self._bar_phase > 1.0:
            self._bar_phase = 0.0
        self._apply_bar_style()

    def _relayout(self) -> None:
        if self._pixmap.isNull():
            w = self._canvas.width()
            h = self._canvas.height()
        else:
            w = self._canvas.width()
            h = self._canvas.height()

        bw = int(w * 0.74)
        bh = 14
        bx = (w - bw) // 2
        by = int(h * 0.855)
        self._bar.setGeometry(QRect(bx, by, bw, bh))
        self._label.setGeometry(int(w * 0.14), by + bh + 14, int(w * 0.72), 20)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._relayout()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._title_bar.geometry().contains(event.position().toPoint()):
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def set_progress(self, percent: int, text: str = "") -> None:
        percent = max(0, min(100, int(percent)))
        self._bar.setValue(percent)
        if text:
            self._label.setText(text)
        QApplication.processEvents()

    def finish(self, _window: QWidget | None = None) -> None:
        self._anim.stop()
        self.hide()
        self.close()
