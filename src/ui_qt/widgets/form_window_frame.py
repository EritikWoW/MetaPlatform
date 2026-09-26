from __future__ import annotations

"""Form window frame.

The runtime client shows a form as a top-level window (title bar + client area).
The Form Designer should therefore render and edit the *whole* window, not only
the internal content.

This widget is a lightweight visual wrapper used in the designer to represent
the window chrome. It is not intended to perfectly mimic the OS window manager.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..theme import BORDER, FG, PANEL_2


class FormWindowFrame(QFrame):
    """A simple window-like frame with a title bar and a fixed-size client area."""

    TITLE_BAR_H = 30
    CLIENT_PADDING = 12
    RADIUS = 10

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FormWindowFrame")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Plain)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        self._title_bar = QFrame(self)
        self._title_bar.setObjectName("FormWindowTitleBar")
        self._title_bar.setFixedHeight(self.TITLE_BAR_H)
        tb = QHBoxLayout(self._title_bar)
        tb.setContentsMargins(10, 0, 10, 0)
        tb.setSpacing(8)
        self._title = QLabel("")
        self._title.setObjectName("FormWindowTitle")
        self._title.setMinimumWidth(0)
        self._title.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        tb.addWidget(self._title, 1)
        root.addWidget(self._title_bar, 0)

        # Client
        self._client = QFrame(self)
        self._client.setObjectName("FormWindowClient")
        cl = QVBoxLayout(self._client)
        # Inner padding prevents the designer canvas / preview from visually
        # touching rounded borders (Qt does not clip child backgrounds by
        # border-radius).
        cl.setContentsMargins(self.CLIENT_PADDING, self.CLIENT_PADDING, self.CLIENT_PADDING, self.CLIENT_PADDING)
        cl.setSpacing(0)
        root.addWidget(self._client, 0)

        # Default styling. We keep it minimal and palette-friendly.
        r = self.RADIUS
        self.setStyleSheet(
            f"""
            QFrame#FormWindowFrame {{
                border: 1px solid {BORDER};
                border-radius: {r}px;
                background: transparent;
            }}
            QFrame#FormWindowTitleBar {{
                border-bottom: 1px solid {BORDER};
                border-top-left-radius: {r}px;
                border-top-right-radius: {r}px;
                background: {PANEL_2};
            }}
            QLabel#FormWindowTitle {{
                color: {FG};
                background: transparent;
                border: none;
                padding-left: 2px;
                font-weight: 600;
            }}
            QFrame#FormWindowClient {{
                border-bottom-left-radius: {r}px;
                border-bottom-right-radius: {r}px;
                background: rgba(248,250,252,255);
            }}
            """
        )

    def set_window_title(self, title: str) -> None:
        self._title.setText(str(title or ""))

    def set_client_size(self, w: int, h: int) -> None:
        """Set *inner* client size (usable design/runtime area).

        The actual widget's client frame is larger because we keep a visual
        padding inside the rounded border.
        """

        inner_w = max(200, int(w))
        inner_h = max(200, int(h))
        cw = inner_w + self.CLIENT_PADDING * 2
        ch = inner_h + self.CLIENT_PADDING * 2
        self._client.setMinimumWidth(0)
        self._client.setMaximumWidth(cw)
        self._client.setFixedHeight(ch)
        self._client.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # The frame may shrink below the design width in the IDE viewport. The
        # design size remains an upper bound and is still stored in the model.
        self.setMinimumWidth(0)
        self.setMaximumWidth(cw)
        self.setFixedHeight(ch + self.TITLE_BAR_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_client_widget(self, widget: QWidget) -> None:
        # Remove previous widget if present.
        lay = self._client.layout()
        if lay is not None:
            while lay.count():
                item = lay.takeAt(0)
                if item is None:
                    break
                w = item.widget()
                if w is not None:
                    w.setParent(None)

            widget.setParent(self._client)
            lay.addWidget(widget)
