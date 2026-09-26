from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.ui_qt.widgets.pictures_gallery import PicturesGalleryWidget


class _GalleryVmStub:
    def __init__(self) -> None:
        self.reload_calls = 0
        self.update_calls: list[tuple[str, str, str, str]] = []

    def list_pictures(self):
        self.reload_calls += 1
        return [
            {
                "guid": "pic-1",
                "title": "Updated title" if self.reload_calls > 1 else "Original title",
                "tags": "tag-1",
                "category": "cat-1",
                "asset_key": "picture://1",
                "mime": "image/png",
            }
        ]

    def get_picture_asset(self, _asset_key: str):
        return b"", "image/png"

    def update_picture_metadata(self, guid: str, *, title: str, tags: str, category: str) -> None:
        self.update_calls.append((str(guid), str(title), str(tags), str(category)))

    def open_picture_editor_for_picture(self, *_args, **_kwargs):
        return None

    def import_pictures(self, *_args, **_kwargs):
        return []


def test_pictures_gallery_apply_metadata_refreshes_from_vm() -> None:
    app = QApplication.instance() or QApplication([])
    vm = _GalleryVmStub()
    widget = PicturesGalleryWidget(vm=vm)
    app.processEvents()

    assert widget._list.count() == 1
    widget._list.setCurrentRow(0)
    app.processEvents()

    widget._prop_title.setText("Updated title")
    widget._apply_metadata()
    app.processEvents()

    assert vm.update_calls == [("pic-1", "Updated title", "tag-1", "cat-1")]
    assert vm.reload_calls >= 2
    assert widget._list.currentItem() is not None
    assert widget._list.currentItem().text() == "Updated title"
