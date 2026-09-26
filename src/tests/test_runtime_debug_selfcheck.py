from types import SimpleNamespace

from src.runtime.gateway import RuntimeGateway
from src.runtime.server_handlers_debug import handle_debug_action
from src.runtime.server_state import RpcResponse


def test_debug_selfcheck_handler_hits_breakpoint_and_returns_report() -> None:
    handler = SimpleNamespace()

    response = handle_debug_action(
        handler,
        "debug.selfcheck",
        {
            "session_id": "sid-debug",
            "entry": "Main",
            "module_id": "module://debug-selfcheck",
            "breakpoint_line": 3,
            "strict_entry": True,
        },
    )

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert response.data["session_id"] == "sid-debug"
    assert response.data["module_id"] == "module://debug-selfcheck"
    assert response.data["entry"] == "Main"
    assert response.data["breakpoint_line"] == 3
    assert response.data["pause_count"] == 1
    assert response.data["pauses"][0]["line"] == 3
    assert response.data["context"]["Cancel"] is True


def test_runtime_gateway_debug_selfcheck_uses_rpc_action(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"pause_count": 1, "entry": "Main"}

    monkeypatch.setattr(gw, "_call", _fake_call)

    result = gw.debug_selfcheck(entry="Main", module_id="module://selfcheck", breakpoint_line=7, timeout=9.0)

    assert result == {"pause_count": 1, "entry": "Main"}
    assert captured == [
        (
            "debug.selfcheck",
            {
                "session_id": "sid-1",
                "entry": "Main",
                "module_id": "module://selfcheck",
                "breakpoint_line": 7,
                "strict_entry": True,
            },
            9.0,
        )
    ]
