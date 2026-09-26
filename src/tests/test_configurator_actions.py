from __future__ import annotations

from dataclasses import dataclass, field

from src.configurator.configurator_actions import ConfiguratorActionsMixin


@dataclass
class _VmStub:
    calls: list[str] = field(default_factory=list)

    def reopen_db(self) -> None:
        self.calls.append("reopen_db")


@dataclass
class _SignalStub:
    calls: list[str] = field(default_factory=list)

    def emit(self) -> None:
        self.calls.append("emit")


@dataclass
class _ActionsStub(ConfiguratorActionsMixin):
    _vm: _VmStub | None = None
    refreshRequested: _SignalStub = field(default_factory=_SignalStub)
    progress: list[tuple[int, str]] = field(default_factory=list)
    infos: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    cleanup_calls: int = 0
    end_calls: int = 0

    def _set_onec_import_progress(self, *, progress: int, message: str, phase_text: str = "") -> None:
        self.progress.append((int(progress), str(message)))

    def _end_onec_import_ui(self) -> None:
        self.end_calls += 1

    def _cleanup_onec_import_worker(self) -> None:
        self.cleanup_calls += 1

    def show_info(self, title: str, text: str) -> None:
        self.infos.append((str(title), str(text)))

    def show_warning(self, title: str, text: str) -> None:
        self.warnings.append((str(title), str(text)))


@dataclass
class _SaveWidgetStub:
    calls: list[str] = field(default_factory=list)

    def save(self):
        self.calls.append("save")
        return True

    def reload_from_vm(self) -> None:
        self.calls.append("reload")


@dataclass
class _SaveActionsStub(_ActionsStub):
    widget: _SaveWidgetStub | None = None
    refreshRequested: _SignalStub = field(default_factory=_SignalStub)

    def _active_editor_widget(self):
        return self.widget


def test_onec_import_finished_triggers_reopen_and_refresh() -> None:
    vm = _VmStub()
    actions = _ActionsStub(_vm=vm)

    ConfiguratorActionsMixin._onec_import_finished(actions, "ok")

    assert vm.calls == ["reopen_db"]
    assert actions.refreshRequested.calls == ["emit"]
    assert actions.progress[-1][0] == 100
    assert actions.end_calls == 1
    assert actions.cleanup_calls == 1
    assert actions.infos
    assert not actions.warnings


def test_on_save_refreshes_widget_after_successful_save() -> None:
    actions = _SaveActionsStub(widget=_SaveWidgetStub())

    ConfiguratorActionsMixin._on_save(actions)

    assert actions.widget is not None
    assert actions.widget.calls == ["save", "reload"]
    assert actions.refreshRequested.calls == ["emit"]


def test_on_save_uses_refresh_when_reload_alias_is_missing() -> None:
    @dataclass
    class _RefreshWidgetStub:
        calls: list[str] = field(default_factory=list)

        def save(self):
            self.calls.append("save")
            return True

        def refresh(self) -> None:
            self.calls.append("refresh")

    actions = _SaveActionsStub(widget=_RefreshWidgetStub())

    ConfiguratorActionsMixin._on_save(actions)

    assert actions.widget is not None
    assert actions.widget.calls == ["save", "refresh"]
    assert actions.refreshRequested.calls == ["emit"]


def test_on_save_propagates_viewmodel_save_failure_without_active_editor() -> None:
    @dataclass
    class _FailingSaveVm:
        calls: list[str] = field(default_factory=list)

        def on_save(self) -> bool:
            self.calls.append("save")
            return False

    vm = _FailingSaveVm()
    actions = _SaveActionsStub(_vm=vm, widget=None)

    assert ConfiguratorActionsMixin._on_save(actions) is False
    assert vm.calls == ["save"]
