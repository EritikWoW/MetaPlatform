from __future__ import annotations

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication

from src.ui_qt.widgets.raster_image_editor import RasterImageEditorWidget
from src.ui_qt.widgets.svg_editor import SvgEditorWidget


class _SvgVmStub:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.save_calls: list[tuple[str, bytes, str]] = []

    def get_picture_asset(self, asset_key: str):
        self.calls.append(str(asset_key))
        return (
            b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' fill='#0000ff'/></svg>",
            "image/svg+xml",
        )

    def save_picture_asset(self, asset_key: str, data: bytes, mime: str) -> None:
        self.save_calls.append((str(asset_key), bytes(data), str(mime)))

    def show_warning(self, *_args, **_kwargs) -> None:
        return None


class _RasterVmStub(_SvgVmStub):
    def __init__(self, image_bytes: bytes) -> None:
        super().__init__()
        self._image_bytes = bytes(image_bytes)

    def get_picture_asset(self, asset_key: str):
        self.calls.append(str(asset_key))
        return self._image_bytes, "image/png"


def _png_bytes() -> bytes:
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ff0000"))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    try:
        image.save(buffer, "PNG")
        return bytes(buffer.data())
    finally:
        buffer.close()


def test_svg_editor_save_refreshes_from_vm() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _SvgVmStub()
    widget = SvgEditorWidget(vm=vm, asset_key="picture://svg-1", title="Svg")
    app.processEvents()

    reload_calls: list[int] = []

    def _reload_from_vm() -> None:
        reload_calls.append(1)

    widget.reload_from_vm = _reload_from_vm  # type: ignore[method-assign]
    widget._editor.setPlainText(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' fill='#00ff00'/></svg>"
    )
    widget.save()
    app.processEvents()

    assert reload_calls == [1]
    assert vm.save_calls
    assert vm.save_calls[0][0] == "picture://svg-1"


def test_raster_editor_save_refreshes_from_vm() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _RasterVmStub(_png_bytes())
    widget = RasterImageEditorWidget(vm=vm, asset_key="picture://png-1", title="Raster")
    app.processEvents()

    reload_calls: list[int] = []

    def _reload_from_vm() -> None:
        reload_calls.append(1)

    widget.reload_from_vm = _reload_from_vm  # type: ignore[method-assign]
    widget._img = type(
        "_ImageStub",
        (),
        {
            "isNull": lambda self: False,
            "save": lambda self, _buf, _fmt: True,
        },
    )()
    widget.save()
    app.processEvents()

    assert reload_calls == [1]
    assert vm.save_calls
    assert vm.save_calls[0][0] == "picture://png-1"
