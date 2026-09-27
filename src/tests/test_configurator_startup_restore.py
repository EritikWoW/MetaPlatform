from src.configurator.configurator_state import ConfiguratorStateMixin


class _Settings:
    def value(self, key, default=None):
        assert key == "last_open_windows"
        return ["first", "missing", "second"]


class _View(ConfiguratorStateMixin):
    def __init__(self):
        self._settings = _Settings()
        self._vm = self
        self._restore_windows_retries_left = 3
        self.opened = []

    def get_meta_by_guid(self, guid):
        if guid == "missing":
            return None
        return {"guid": guid, "name": guid.title(), "type": "document"}

    def open_object_tab(self, info):
        self.opened.append(info.guid)


def test_saved_editors_restore_one_per_event_and_skip_missing(monkeypatch):
    from src.configurator import configurator_state

    scheduled = []
    monkeypatch.setattr(
        configurator_state.QTimer,
        "singleShot",
        lambda delay, callback: scheduled.append((delay, callback)),
    )
    view = _View()

    view._restore_last_windows_optional()
    assert view.opened == ["first"]
    assert len(scheduled) == 1

    scheduled.pop(0)[1]()
    assert view.opened == ["first"]
    assert len(scheduled) == 1

    scheduled.pop(0)[1]()
    assert view.opened == ["first", "second"]
    assert len(scheduled) == 1

    scheduled.pop(0)[1]()
    assert view.opened == ["first", "second"]
    assert scheduled == [(250, view._restore_last_windows_optional)]
