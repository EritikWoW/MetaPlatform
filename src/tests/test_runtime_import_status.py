from __future__ import annotations

from src.runtime import server_handlers_import as import_handlers
from src.runtime.server_handlers_import import handle_import_action
from src.runtime.server_state import ImportStatusStore


def test_import_status_store_tracks_history_and_listing() -> None:
    store = ImportStatusStore()
    store.set(
        "sid-1",
        {"progress": 5, "phase": "start", "message": "preparing"},
        meta={"source_path": "F:/MetaPlatform/WorkedData/1Cv8.1CD"},
    )
    store.append_event("sid-1", "log", message="opening source")
    store.set(
        "sid-1",
        {"progress": 100, "phase": "done", "message": "finished", "failed": False},
    )

    snapshot = store.snapshot("sid-1", history_limit=2)
    assert snapshot["session_id"] == "sid-1"
    assert snapshot["source_path"] == "F:/MetaPlatform/WorkedData/1Cv8.1CD"
    assert snapshot["progress"] == 100
    assert snapshot["status"] == "done"
    assert snapshot["active"] is False
    assert snapshot["event_count"] == 3
    assert len(snapshot["history"]) == 2
    assert snapshot["history"][-1]["kind"] == "state"

    sessions = store.list()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "sid-1"


def test_import_action_exposes_sessions_and_history(monkeypatch) -> None:
    store = ImportStatusStore()
    store.set(
        "sid-active",
        {"progress": 12, "phase": "manifest", "message": "manifest"},
        meta={"source_kind": "1cd"},
    )
    store.append_event("sid-active", "log", message="import manifest objects")
    store.set(
        "sid-finished",
        {"progress": 99, "phase": "done", "message": "done", "failed": False},
        meta={"source_kind": "1cd"},
    )
    store.set(
        "sid-finished",
        {"progress": 99, "phase": "done", "message": "done", "failed": False},
    )

    monkeypatch.setattr(import_handlers, "STATE_IMPORTS", store)

    sessions_res = handle_import_action(None, "onec.import_sessions", {"active_only": True})
    assert sessions_res is not None
    assert sessions_res.status == "ok"
    sessions = sessions_res.data["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "sid-active"
    assert sessions[0]["status"] == "active"

    status_res = handle_import_action(
        None,
        "onec.import_status",
        {"session_id": "sid-finished", "history_limit": 1},
    )
    assert status_res is not None
    assert status_res.status == "ok"
    status = status_res.data
    assert status["session_id"] == "sid-finished"
    assert status["status"] == "done"
    assert len(status["history"]) == 1
    assert status["history"][0]["kind"] == "state"
