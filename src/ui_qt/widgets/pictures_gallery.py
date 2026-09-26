from __future__ import annotations

import os
from typing import Any, Dict, List

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFileDialog,
    QAbstractItemView,
    QFormLayout,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QLineEdit,
    QGroupBox,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t
from src.ui_qt.widgets.picture_preview import PicturePreview
from src.ui_qt.services.icon_provider import IconProvider


class PicturesList(QListWidget):
    """Icon-mode list with drag&drop import."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)
        self.setIconSize(QPixmap(96, 96).size())
        self.setMovement(QListWidget.Static)
        self.setSpacing(10)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.parent()._on_drop_urls(event.mimeData())  # type: ignore[attr-defined]
            return
        super().dropEvent(event)


class PicturesGalleryWidget(QWidget):
    """Pictures library UI backed by manifest objects + mpdb assets."""

    def __init__(self, *, vm, parent: QWidget | None = None):
        super().__init__(parent)
        self._vm = vm
        self._icons = getattr(vm, "icon_provider", None) or IconProvider()

        self._title = QLabel(t("pictures_title"), self)
        self._title.setObjectName("h1")
        self._hint = QLabel(t("pictures_hint"), self)
        self._hint.setWordWrap(True)

        self._list = PicturesList(self)
        self._preview = PicturePreview(self)

        # "Constructor"-like metadata editor (dictionary) for selected picture
        self._props_box = QGroupBox(t("pictures_props"), self)
        self._prop_title = QLineEdit(self)
        self._prop_tags = QLineEdit(self)
        self._prop_category = QComboBox(self)
        self._prop_category.setEditable(True)
        self._prop_asset_key = QLineEdit(self)
        self._prop_asset_key.setReadOnly(True)
        self._prop_mime = QLineEdit(self)
        self._prop_mime.setReadOnly(True)

        form = QFormLayout()
        form.addRow(t("pictures_prop_title"), self._prop_title)
        form.addRow(t("pictures_prop_tags"), self._prop_tags)
        form.addRow(t("pictures_prop_category"), self._prop_category)
        form.addRow(t("pictures_prop_asset_key"), self._prop_asset_key)
        form.addRow(t("pictures_prop_mime"), self._prop_mime)
        self._props_box.setLayout(form)

        self._current_guid: str = ""
        self._metadata_guard = False

        self._btn_upload = QPushButton(t("pictures_upload"), self)
        self._btn_edit = QPushButton(t("pictures_open_editor"), self)
        self._btn_refresh = QPushButton(t("pictures_refresh"), self)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_upload)
        btn_row.addWidget(self._btn_edit)
        btn_row.addStretch(1)
        btn_row.addWidget(self._btn_refresh)

        main = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(self._title)
        left.addWidget(self._hint)
        left.addWidget(self._list, 1)
        left.addLayout(btn_row)

        right = QVBoxLayout()
        right.addWidget(QLabel(t("pictures_preview"), self))
        right.addWidget(self._preview, 1)
        right.addWidget(self._props_box)
        main.addLayout(left, 2)
        main.addLayout(right, 1)
        self.setLayout(main)

        self._btn_edit.setEnabled(False)

        self._btn_upload.clicked.connect(self.upload)
        self._btn_refresh.clicked.connect(self.reload)
        self._btn_edit.clicked.connect(self.open_selected_editor)
        self._list.itemSelectionChanged.connect(self._on_select)
        self._list.itemDoubleClicked.connect(lambda *_: self.open_selected_editor())

        # Save metadata on edits
        self._prop_title.editingFinished.connect(self._apply_metadata)
        self._prop_tags.editingFinished.connect(self._apply_metadata)
        self._prop_category.currentTextChanged.connect(lambda *_: self._apply_metadata())

        self.reload()

    # ---------------- public API ----------------
    def reload(self) -> None:
        self._list.clear()
        entries = self._vm.list_pictures()
        for e in entries:
            it = QListWidgetItem(str(e.get("title") or ""))
            it.setData(Qt.ItemDataRole.UserRole, e)
            icon = self._build_icon(e)
            if icon is not None:
                it.setIcon(icon)
            self._list.addItem(it)
        self._btn_edit.setEnabled(bool(self._list.selectedItems()))
        if self._list.count() and not self._list.selectedItems():
            self._list.setCurrentRow(0)

        # Keep properties panel consistent
        self._on_select()

    def reload_from_vm(self) -> None:
        self.reload()

    def upload(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            t("pictures_upload"),
            "",
            "Images (*.svg *.png *.jpg *.jpeg *.ico);;All files (*.*)",
        )
        if not paths:
            return
        self._import(paths)

    def open_selected_editor(self) -> None:
        it = self._current_item()
        if not it:
            return
        e = it.data(Qt.ItemDataRole.UserRole) or {}
        guid = str(e.get("guid") or "").strip()
        if not guid:
            return
        self._vm.open_picture_editor_for_picture(guid)

    # ---------------- internals ----------------
    def _current_item(self) -> QListWidgetItem | None:
        items = self._list.selectedItems()
        return items[0] if items else None

    def _on_select(self) -> None:
        it = self._current_item()
        self._btn_edit.setEnabled(bool(it))
        if not it:
            self._preview.clear()
            self._current_guid = ""
            self._metadata_guard = True
            try:
                self._fill_props(None)
            finally:
                self._metadata_guard = False
            return
        e = it.data(Qt.ItemDataRole.UserRole) or {}
        self._current_guid = str(e.get("guid") or "").strip()
        self._metadata_guard = True
        try:
            self._fill_props(e)
        finally:
            self._metadata_guard = False
        asset_key = str(e.get("asset_key") or "").strip()
        mime = str(e.get("mime") or "").strip()
        if not asset_key:
            self._preview.set_svg_bytes(b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'/>")
            return
        try:
            data, _m = self._vm.get_picture_asset(asset_key)
            if (mime or _m) == "image/svg+xml" or asset_key.lower().endswith(".svg"):
                self._preview.set_svg_bytes(data)
            else:
                self._preview.set_raster_bytes(data)
        except Exception:
            self._preview.set_svg_bytes(b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><text x='6' y='34' font-size='10'>Error</text></svg>")

    def _fill_props(self, e: Dict[str, Any] | None) -> None:
        """Populate metadata editor from list entry."""
        if not e:
            self._prop_title.setText("")
            self._prop_tags.setText("")
            self._prop_category.setCurrentText("")
            self._prop_asset_key.setText("")
            self._prop_mime.setText("")
            return

        self._prop_title.setText(str(e.get("title") or ""))
        # Tags/category are stored in payload.picture.meta; list_pictures returns only basic fields.
        # We keep a lightweight UX: user can still edit tags/category and it will be persisted.
        self._prop_tags.setText(str(e.get("tags") or ""))
        self._prop_category.setCurrentText(str(e.get("category") or ""))
        self._prop_asset_key.setText(str(e.get("asset_key") or ""))
        self._prop_mime.setText(str(e.get("mime") or ""))

    def _apply_metadata(self) -> None:
        """Persist metadata changes to manifest payload."""
        if self._metadata_guard:
            return
        guid = str(self._current_guid or "").strip()
        if not guid:
            return
        current_item = self._current_item()
        title = self._prop_title.text().strip()
        tags = self._prop_tags.text().strip()
        category = self._prop_category.currentText().strip()
        try:
            self._vm.update_picture_metadata(guid, title=title, tags=tags, category=category)
            self._metadata_guard = True
            self.reload_from_vm()
            if current_item is not None:
                self._current_guid = guid
                for row in range(self._list.count()):
                    item = self._list.item(row)
                    data = item.data(Qt.ItemDataRole.UserRole) or {}
                    if str(data.get("guid") or "").strip() == guid:
                        self._list.setCurrentItem(item)
                        break
        except Exception:
            pass
        finally:
            self._metadata_guard = False

    def _build_icon(self, e: Dict[str, Any]) -> QIcon | None:
        asset_key = str(e.get("asset_key") or "").strip()
        mime = str(e.get("mime") or "").strip()
        if not asset_key:
            return None
        try:
            data, _m = self._vm.get_picture_asset(asset_key)
            m = mime or _m
            return self._icons.build_icon(data=data, mime=m, asset_key=asset_key, size=96)
        except Exception:
            return None

    def _import(self, paths: List[str]) -> None:
        created = self._vm.import_pictures(paths)
        if created:
            self.reload()

    def _on_drop_urls(self, mime: QMimeData) -> None:
        paths: List[str] = []
        for url in mime.urls():
            p = url.toLocalFile()
            if p and os.path.isfile(p):
                paths.append(p)
        if not paths:
            return
        self._import(paths)
