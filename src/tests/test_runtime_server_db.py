from types import SimpleNamespace

from src.runtime import server_handlers_db
from src.runtime.server_handlers_db import handle_db_action


class _SessionsStub:
    def __init__(self) -> None:
        self.active: dict[str, str] = {}
        self.closed: list[str] = []

    def create(self) -> str:
        return "new-session"

    def close(self, sid: str) -> bool:
        self.closed.append(str(sid))
        return True

    def set_active_db_uid(self, sid: str, uid: str) -> None:
        self.active[str(sid)] = str(uid)


def test_session_close_rpc_releases_session(monkeypatch) -> None:
    sessions = _SessionsStub()
    monkeypatch.setattr(server_handlers_db, "STATE_SESSIONS", sessions)

    response = handle_db_action(None, "session.close", {"session_id": "sid-1"})

    assert response is not None
    assert response.status == "ok"
    assert response.data == {"closed": True}
    assert sessions.closed == ["sid-1"]


def test_db_open_failure_does_not_replace_registered_file(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "production.mpdb"
    original = b"production-data"
    db_path.write_bytes(original)

    class _PoolStub:
        def get(self, _uid: str):
            raise KeyError("not open")

        def open_by_path(self, _path: str):
            raise RuntimeError("header check failed")

    registry = SimpleNamespace(
        get=lambda uid: SimpleNamespace(db_uid=uid, enabled=True, path=str(db_path))
    )
    sessions = _SessionsStub()
    monkeypatch.setattr(server_handlers_db, "STATE_DBS", _PoolStub())
    monkeypatch.setattr(server_handlers_db, "STATE_REGISTRY", registry)
    monkeypatch.setattr(server_handlers_db, "STATE_SESSIONS", sessions)

    response = handle_db_action(
        None,
        "db.open",
        {"session_id": "sid-1", "db_uid": "db-1"},
    )

    assert response is not None
    assert response.status == "error"
    assert "header check failed" in str(response.error)
    assert db_path.read_bytes() == original
    assert list(tmp_path.glob("*.corrupt-*")) == []
    assert sessions.active == {}
