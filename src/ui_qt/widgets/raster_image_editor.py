from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import QBuffer, QIODevice, QTimer, Qt
from PySide6.QtGui import QAction, QImage, QTransform
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t
from src.ui_qt.widgets.picture_preview import PicturePreview


@dataclass
class RasterEditorState:
    asset_key: str
    title: str
    mime: str = "image/png"


_EXT_TO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}


class RasterImageEditorWidget(QWidget):
    """A minimal raster picture editor.

    UX requirement: keep the *form* close to SvgEditorWidget (toolbar + info + split view).
    The editor differs: it operates on QImage and persists bytes back to mpdb assets.
    """

    def __init__(self, *, vm, asset_key: str, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._vm = vm
        self._state = RasterEditorState(asset_key=asset_key, title=title or asset_key)

        self._dirty = False
        self._reload_guard = False

        self._toolbar = QToolBar(self)
        self._toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)

        self._act_save = QAction(t("img_save"), self)
        self._act_reload = QAction(t("img_reload"), self)
        self._act_replace = QAction(t("img_replace"), self)
        self._act_rot_l = QAction(t("img_rotate_left"), self)
        self._act_rot_r = QAction(t("img_rotate_right"), self)

        self._act_save.setShortcut("Ctrl+S")
        self._act_reload.setShortcut("Ctrl+R")
        self._act_replace.setShortcut("Ctrl+O")
        self._act_rot_l.setShortcut("Ctrl+Alt+Left")
        self._act_rot_r.setShortcut("Ctrl+Alt+Right")

        for a in (self._act_save, self._act_reload, self._act_replace):
            self._toolbar.addAction(a)
        self._toolbar.addSeparator()
        for a in (self._act_rot_l, self._act_rot_r):
            self._toolbar.addAction(a)

        self._info = QLabel("", self)
        self._info.setWordWrap(True)
        self._info.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._preview = PicturePreview(self)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.addWidget(self._preview)
        split.setStretchFactor(0, 1)

        lay = QVBoxLayout(self)
        lay.addWidget(self._toolbar)
        lay.addWidget(self._info)
        lay.addWidget(split, 1)
        self.setLayout(lay)

        self._img: QImage | None = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(50)
        self._refresh_timer.timeout.connect(self._render_preview)

        # signals
        self._act_save.triggered.connect(self.save)
        self._act_reload.triggered.connect(self.reload)
        self._act_replace.triggered.connect(self.replace_from_file)
        self._act_rot_l.triggered.connect(lambda: self.rotate(-90))
        self._act_rot_r.triggered.connect(lambda: self.rotate(90))

        self.reload()

    def title(self) -> str:
        return self._state.title

    # ---------------- loading/saving ----------------
    def reload(self) -> None:
        try:
            data, mime = self._vm.get_picture_asset(self._state.asset_key)
            self._state.mime = (mime or self._guess_mime(self._state.asset_key) or "image/png")
        except Exception as e:
            self._vm.show_warning(t("pictures_title"), f"{t('img_load_failed')}: {e}")
            data = b""

        self._reload_guard = True
        try:
            self._img = QImage.fromData(data) if data else QImage()
            self._dirty = False
        finally:
            self._reload_guard = False

        self._render_preview()
        self._update_info()

    def reload_from_vm(self) -> None:
        self.reload()

    def save(self) -> None:
        if self._img is None or self._img.isNull():
            return

        ext = os.path.splitext(self._state.asset_key.lower())[1]
        mime = self._state.mime or self._guess_mime(self._state.asset_key) or "image/png"
        fmt = self._mime_to_qimage_format(mime, ext)

        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        try:
            ok = self._img.save(buf, fmt)
            if not ok:
                raise RuntimeError("QImage.save returned False")
            data = bytes(buf.data())
        finally:
            buf.close()

        try:
            self._vm.save_picture_asset(self._state.asset_key, data, mime)
            self._dirty = False
            self._update_info(saved=True)
            self.reload_from_vm()
        except Exception as e:
            self._vm.show_warning(t("pictures_title"), f"{t('img_save_failed')}: {e}")

    # ---------------- editing actions ----------------
    def replace_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("img_replace"),
            "",
            "Images (*.png *.jpg *.jpeg *.ico *.bmp *.webp);;All files (*.*)",
        )
        if not path:
            return
        data = None
        try:
            data = open(path, "rb").read()
        except Exception as e:
            self._vm.show_warning(t("pictures_title"), f"{t('img_load_failed')}: {e}")
            return
        img = QImage.fromData(data)
        if img.isNull():
            self._vm.show_warning(t("pictures_title"), t("img_invalid"))
            return
        self._img = img
        # keep mime/format of current asset by default
        self._dirty = True
        self._refresh_timer.start()
        self._update_info()

    def rotate(self, degrees: int) -> None:
        if self._img is None or self._img.isNull():
            return
        tr = QTransform()
        tr.rotate(degrees)
        self._img = self._img.transformed(tr, Qt.TransformationMode.SmoothTransformation)
        self._dirty = True
        self._refresh_timer.start()
        self._update_info()

    # ---------------- internals ----------------
    def _render_preview(self) -> None:
        if self._img is None or self._img.isNull():
            self._preview.clear()
            return
        from PySide6.QtGui import QPixmap

        self._preview.set_pixmap(QPixmap.fromImage(self._img))

    def _update_info(self, saved: bool = False) -> None:
        status = t("img_status_saved") if saved else (t("img_status_dirty") if self._dirty else t("img_status_clean"))
        self._info.setText(f"{self._state.asset_key} — {status}")

    @staticmethod
    def _guess_mime(asset_key: str) -> str | None:
        ext = os.path.splitext((asset_key or "").lower())[1]
        return _EXT_TO_MIME.get(ext)

    @staticmethod
    def _mime_to_qimage_format(mime: str, ext: str) -> bytes:
        mime = (mime or "").lower().strip()
        if mime == "image/jpeg" or ext in (".jpg", ".jpeg"):
            return b"JPG"
        if mime == "image/png" or ext == ".png":
            return b"PNG"
        if mime in ("image/x-icon", "image/vnd.microsoft.icon") or ext == ".ico":
            return b"ICO"
        if mime == "image/webp" or ext == ".webp":
            return b"WEBP"
        if mime == "image/bmp" or ext == ".bmp":
            return b"BMP"
        # fall back
        return b"PNG"
