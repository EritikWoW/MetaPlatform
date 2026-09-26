from __future__ import annotations

from dataclasses import dataclass, field

from src.configurator.configurator_storage import ConfiguratorStorageMixin


@dataclass
class _SignalStub:
    calls: list[str] = field(default_factory=list)

    def emit(self) -> None:
        self.calls.append("emit")


@dataclass
class _StorageStub:
    checkout_calls: list[tuple[str, str, str, str, str]] = field(default_factory=list)
    release_calls: list[tuple[str, str]] = field(default_factory=list)
    force_calls: list[tuple[str, str]] = field(default_factory=list)

    def checkout(self, *, object_type: str, object_id: str, component_type: str, component_id: str, comment: str, user_id: str = "SYSTEM") -> None:
        self.checkout_calls.append((object_type, object_id, component_type, component_id, comment))

    def release_my_locks_for_object(self, *, object_type: str, object_id: str) -> int:
        self.release_calls.append((object_type, object_id))
        return 1

    def force_release_locks_for_object(self, *, object_type: str, object_id: str) -> int:
        self.force_calls.append((object_type, object_id))
        return 1


@dataclass
class _StorageActionsStub(ConfiguratorStorageMixin):
    _vm: object | None = object()
    _config_storage: _StorageStub = field(default_factory=_StorageStub)
    refreshRequested: _SignalStub = field(default_factory=_SignalStub)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    infos: list[tuple[str, str]] = field(default_factory=list)

    def show_warning(self, title: str, text: str) -> None:
        self.warnings.append((str(title), str(text)))

    def confirm(self, *_args, **_kwargs) -> bool:
        return True


def test_storage_checkout_emits_refresh(monkeypatch) -> None:
    from src.configurator import configurator_storage as module

    monkeypatch.setattr(module.QInputDialog, "getText", lambda *args, **kwargs: ("note", True))
    monkeypatch.setattr(module.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *args, **kwargs: None)

    actions = _StorageActionsStub()
    actions._storage_checkout("Catalog", "guid-1", "Object", "-")

    assert actions._config_storage.checkout_calls == [("Catalog", "guid-1", "Object", "-", "note")]
    assert actions.refreshRequested.calls == ["emit"]


def test_storage_abandon_emits_refresh(monkeypatch) -> None:
    from src.configurator import configurator_storage as module

    monkeypatch.setattr(module.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *args, **kwargs: None)

    actions = _StorageActionsStub()
    actions._storage_abandon_all_for_object("Catalog", "guid-1")

    assert actions._config_storage.release_calls == [("Catalog", "guid-1")]
    assert actions.refreshRequested.calls == ["emit"]


def test_storage_force_unlock_emits_refresh(monkeypatch) -> None:
    from src.configurator import configurator_storage as module

    monkeypatch.setattr(module.QMessageBox, "question", lambda *args, **kwargs: module.QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(module.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *args, **kwargs: None)

    actions = _StorageActionsStub()
    actions._storage_force_unlock_dialog("Catalog", "guid-1")

    assert actions._config_storage.force_calls == [("Catalog", "guid-1")]
    assert actions.refreshRequested.calls == ["emit"]
