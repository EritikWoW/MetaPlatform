from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox, QVBoxLayout, QWidget

from src.ui_qt.i18n import t


class FormRuntimeWindow(QDialog):
    """Resizable top-level host for forms configured as separate windows."""

    def __init__(
        self,
        *,
        view_id: str,
        title: str,
        content_widget: QWidget,
        model: dict,
        lock_mode: str = "none",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.view_id = str(view_id or "")
        self.content_widget = content_widget
        self.form_widget = getattr(content_widget, "_form_widget", content_widget)
        self._base_title = str(title or "")
        self._dirty = False
        self._allow_dirty_close = False

        flags = (
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(self._base_title)

        lock = str(lock_mode or "none").strip().lower()
        if lock == "interface":
            self.setWindowModality(Qt.WindowModality.ApplicationModal)
        elif lock == "owner":
            self.setWindowModality(Qt.WindowModality.WindowModal)
        else:
            self.setWindowModality(Qt.WindowModality.NonModal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(content_widget, 1)

        root = model.get("root") if isinstance(model, dict) else {}
        props = root.get("props") if isinstance(root, dict) and isinstance(root.get("props"), dict) else {}
        try:
            width = max(320, int(props.get("w") or 900))
        except (TypeError, ValueError):
            width = 900
        try:
            height = max(240, int(props.get("h") or 650))
        except (TypeError, ValueError):
            height = 650
        screen = self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            width = min(width, max(320, int(area.width() * 0.9)))
            height = min(height, max(240, int(area.height() * 0.9)))
        self.resize(width, height)

    def activate(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def set_dirty(self, *_args) -> None:
        if self._dirty:
            return
        self._dirty = True
        self.setWindowTitle(f"* {self._base_title}")

    def clear_dirty(self) -> None:
        self._dirty = False
        self.setWindowTitle(self._base_title)

    def set_base_title(self, title: str) -> None:
        self._base_title = str(title or "")
        self.setWindowTitle(f"* {self._base_title}" if self._dirty else self._base_title)

    def discard_and_close(self) -> None:
        self._allow_dirty_close = True
        self.close()

    def closeEvent(self, event) -> None:
        if self._dirty and not self._allow_dirty_close:
            answer = QMessageBox.question(
                self,
                t("dlg_unsaved_title"),
                t("form_window_unsaved_close"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()
