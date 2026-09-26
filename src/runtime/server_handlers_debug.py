from __future__ import annotations

from typing import Any

from src.runtime.script.compiler import (
    CodeObject,
    Instruction,
    LOAD_CONST,
    ModuleCode,
    RETURN_NONE,
    STORE_NAME,
)
from src.runtime.script.debugger import DebugSession
from src.runtime.script.vm import run_module

from .server_state import RpcResponse


def _build_selfcheck_module(module_id: str, entry: str, breakpoint_line: int) -> ModuleCode:
    instructions = [
        Instruction(op=LOAD_CONST, arg=True, lineno=breakpoint_line),
        Instruction(op=STORE_NAME, arg="Cancel", lineno=breakpoint_line),
        Instruction(op=RETURN_NONE, lineno=breakpoint_line + 1),
    ]
    main = CodeObject(
        name=entry,
        params=[],
        by_value=[],
        defaults=[],
        instructions=instructions,
        locals_=[],
        exported=False,
        is_function=False,
    )
    return ModuleCode(
        name=module_id,
        procedures={entry: main},
        functions={},
        module_vars=[],
    )


def handle_debug_action(_handler, action: str, payload: dict) -> RpcResponse | None:
    if action != "debug.selfcheck":
        return None

    session_id = str(payload.get("session_id") or "").strip()
    entry = str(payload.get("entry") or "Main").strip() or "Main"
    module_id = str(payload.get("module_id") or "module://debug-selfcheck").strip() or "module://debug-selfcheck"
    try:
        breakpoint_line = max(1, int(payload.get("breakpoint_line") or 3))
    except Exception:
        breakpoint_line = 3
    strict_entry = bool(payload.get("strict_entry", True))

    pauses: list[dict[str, Any]] = []

    def _pause_handler(pause) -> str:
        pauses.append(
            {
                "module_id": str(getattr(pause, "module_id", "")),
                "code_name": str(getattr(pause, "code_name", "")),
                "line": int(getattr(pause, "line", 0) or 0),
                "depth": int(getattr(pause, "depth", 0) or 0),
                "locals": dict(getattr(pause, "locals", {}) or {}),
                "globals": dict(getattr(pause, "globals", {}) or {}),
                "stack": list(getattr(pause, "stack", []) or []),
            }
        )
        return "continue"

    session = DebugSession(
        breakpoints={module_id: {breakpoint_line}},
        pause_handler=_pause_handler,
    )
    module = _build_selfcheck_module(module_id, entry, breakpoint_line)
    context: dict[str, Any] = {"Cancel": False}

    try:
        result = run_module(
            module,
            entry=entry,
            initial_globals=context,
            debugger=session,
            strict_entry=strict_entry,
        )
        report = {
            "session_id": session_id,
            "module_id": module_id,
            "entry": entry,
            "strict_entry": strict_entry,
            "breakpoint_line": breakpoint_line,
            "pause_count": len(pauses),
            "pauses": pauses,
            "result": result,
            "context": dict(context),
        }
        if not pauses:
            return RpcResponse("error", error="debug.selfcheck did not hit any breakpoint", data=report)
        return RpcResponse("ok", report)
    except Exception as e:
        return RpcResponse(
            "error",
            error=f"debug.selfcheck: {type(e).__name__}: {e}",
            data={
                "session_id": session_id,
                "module_id": module_id,
                "entry": entry,
                "strict_entry": strict_entry,
                "breakpoint_line": breakpoint_line,
                "pause_count": len(pauses),
                "pauses": pauses,
                "context": dict(context),
            },
        )
