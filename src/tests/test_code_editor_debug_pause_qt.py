from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from src.ui_qt.widgets.code_editor_widget import CodeEditorWidget
from src.client.debug_support import get_last_debug_pause


class _EditorVmStub:
    def __init__(self) -> None:
        self._text = "\n".join(f"line {line}" for line in range(1, 41))

    def get_text_asset(self, asset_key: str):
        return self._text, "text/plain", str(asset_key)

    def save_text_asset(self, asset_key: str, text: str, *, mime: str = "text/plain") -> None:
        self._text = str(text)


def _make_pause(*, line: int, module_id: str = "module://debug-pause-test"):
    return SimpleNamespace(
        module_id=module_id,
        code_name="TestProcedure",
        line=int(line),
        depth=1,
        stack=[
            {
                "module_id": "module://debug-pause-test",
                "code_name": "TestProcedure",
                "line": int(line),
            }
        ],
        locals={"Counter": 7},
        globals={"ApplicationName": "MetaPlatform"},
    )


def _has_debug_arrow(widget: CodeEditorWidget) -> bool:
    image = widget._edit._gutter.grab().toImage()
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.red() >= 200 and color.green() >= 140 and color.blue() <= 90:
                return True
    return False


def _build_widget() -> tuple[QApplication, CodeEditorWidget]:
    app = QApplication.instance() or QApplication([])
    widget = CodeEditorWidget(
        vm=_EditorVmStub(),
        asset_key="module://debug-pause-test",
        title="Debug pause test",
    )
    widget.resize(900, 620)
    widget.show()
    widget._edit.setFocus()
    app.processEvents()
    return app, widget


def test_debug_pause_focuses_line_renders_arrow_and_continue_clears_pause() -> None:
    app, widget = _build_widget()
    commands: list[str] = []
    widget.debugCommandRequested.connect(commands.append)

    widget.focus_debug_location(24, pause=_make_pause(line=24))
    app.processEvents()

    assert widget._edit.textCursor().blockNumber() + 1 == 24
    assert widget._debug_banner.isVisible()
    assert widget._debug_controls.isVisible()
    assert widget._debug_context_tabs.isVisible()
    assert _has_debug_arrow(widget)

    QTest.keyClick(widget._edit, Qt.Key.Key_F5)
    app.processEvents()

    assert commands == ["continue"]
    assert not widget._debug_banner.isVisible()
    assert not widget._debug_controls.isVisible()
    assert not widget._debug_context_tabs.isVisible()
    assert widget._edit._debug_line == 0
    assert widget._current_debug_pause is None
    assert not _has_debug_arrow(widget)
    assert get_last_debug_pause() is None
    widget.close()


def test_debug_step_shortcuts_are_registered_and_emit_commands_while_paused() -> None:
    app, widget = _build_widget()
    registered = {
        shortcut.key().toString(QKeySequence.SequenceFormat.PortableText)
        for shortcut in widget.findChildren(QShortcut)
    }
    assert {
        "F9",
        "Ctrl+F9",
        "Ctrl+Shift+F9",
        "Shift+F9",
        "F10",
        "F11",
        "Shift+F11",
    }.issubset(registered)
    assert "F5" not in registered
    assert "Shift+F5" not in registered

    commands: list[str] = []
    widget.debugCommandRequested.connect(commands.append)
    widget.focus_debug_location(18, pause=_make_pause(line=18))
    app.processEvents()

    QTest.keyClick(widget._edit, Qt.Key.Key_F10)
    app.processEvents()
    assert widget._current_debug_pause is None
    assert not _has_debug_arrow(widget)

    widget.focus_debug_location(19, pause=_make_pause(line=19))
    QTest.keyClick(widget._edit, Qt.Key.Key_F11)
    app.processEvents()
    assert widget._current_debug_pause is None
    assert not _has_debug_arrow(widget)

    widget.focus_debug_location(20, pause=_make_pause(line=20))
    QTest.keyClick(
        widget._edit,
        Qt.Key.Key_F11,
        Qt.KeyboardModifier.ShiftModifier,
    )
    app.processEvents()

    assert commands == ["step_over", "step_into", "step_out"]
    assert not widget._debug_controls.isVisible()
    assert widget._edit._debug_line == 0
    assert not _has_debug_arrow(widget)
    widget.close()


def test_new_pause_in_another_module_clears_previous_editor_marker() -> None:
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    layout = QVBoxLayout(host)
    first = CodeEditorWidget(
        vm=_EditorVmStub(),
        asset_key="module://managed-module",
        title="Managed module",
    )
    second = CodeEditorWidget(
        vm=_EditorVmStub(),
        asset_key="module://ordinary-module",
        title="Ordinary module",
    )
    layout.addWidget(first)
    layout.addWidget(second)
    host.resize(900, 900)
    host.show()

    first.focus_debug_location(
        18,
        pause=_make_pause(line=18, module_id="module://managed-module"),
    )
    app.processEvents()
    assert first._current_debug_pause is not None
    assert _has_debug_arrow(first)

    second.focus_debug_location(
        25,
        pause=_make_pause(line=25, module_id="module://ordinary-module"),
    )
    app.processEvents()

    assert first._current_debug_pause is None
    assert first._edit._debug_line == 0
    assert not _has_debug_arrow(first)
    assert second._current_debug_pause is not None
    assert second._edit._debug_line == 25
    assert _has_debug_arrow(second)
    host.close()
