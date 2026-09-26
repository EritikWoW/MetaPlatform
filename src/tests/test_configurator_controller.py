from __future__ import annotations

from dataclasses import dataclass, field

from src.configurator.configurator_controller import ConfiguratorController


@dataclass
class _EditorStub:
    calls: list[str] = field(default_factory=list)

    def reload_from_vm(self) -> None:
        self.calls.append("reload")


@dataclass
class _ViewStub:
    editor: _EditorStub | None = None
    status: list[str] = field(default_factory=list)

    def _active_editor_widget(self):
        return self.editor

    def set_status(self, text: str) -> None:
        self.status.append(str(text))


class _ControllerStub:
    def __init__(self) -> None:
        self.view = _ViewStub(editor=_EditorStub())
        self.reload_calls = 0
        self.progress_calls: list[tuple[int, str]] = []
        self.pulse_calls: list[bool] = []
        self.populate_calls: list[str] = []
        self._service = self
        self.objects: list[str] = ["obj-1"]

    def reload(self) -> None:
        self.reload_calls += 1
        ConfiguratorController.reload(self)

    def _progress(self, percent: int, text: str = "") -> None:
        self.progress_calls.append((int(percent), str(text)))

    def _pulse_ui(self, force: bool = False) -> None:
        self.pulse_calls.append(bool(force))

    def list_objects(self):
        return list(self.objects)

    def _populate_tree(self, objs) -> None:
        self.populate_calls.append(",".join(str(x) for x in objs))

    def _refresh_active_editor_widget(self) -> None:
        self.view.editor.calls.append("reload")


def test_controller_reload_refreshes_active_editor() -> None:
    controller = _ControllerStub()

    ConfiguratorController.reload(controller)

    assert controller.view.editor is not None
    assert controller.view.editor.calls == ["reload"]
    assert controller.reload_calls == 0
    assert controller.progress_calls[0][0] == 60
    assert controller.populate_calls == ["obj-1"]


def test_controller_on_save_refreshes_active_editor_and_tree() -> None:
    controller = _ControllerStub()

    ConfiguratorController.on_save(controller)

    assert controller.view.editor is not None
    assert controller.view.editor.calls == ["reload", "reload"]
    assert controller.reload_calls == 1
    assert controller.view.status == ["Готово", "Сохранено"]
