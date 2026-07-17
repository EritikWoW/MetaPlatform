"""Runtime compatibility layer over the shared DSL VM.

Runtime-specific debugging stays opt-in here via ``DebugSession`` while the
actual interpreter implementation lives in ``src.dsl.vm``.
"""

from __future__ import annotations

from src.dsl.vm import (  # noqa: F401
    BUILTINS,
    Frame,
    MsArray,
    MsException,
    MsMap,
    VM as _BaseVM,
    VmDebugPlugin,
    execute_script as _execute_script,
    run_module as _run_module,
)

from .compiler import CodeObject, Instruction
from .debugger import DebugSession, create_debug_session_from_env, make_pause_snapshot


class _RuntimeDebuggerPlugin:
    def __init__(self, debugger: DebugSession | None) -> None:
        self._debugger = debugger

    def before_instruction(
        self,
        *,
        module_id: str,
        frame: Frame,
        call_stack: list[Frame],
        instr: Instruction,
    ) -> None:
        if self._debugger is None:
            return
        line = int(instr.lineno or 0)
        if line <= 0:
            return
        frame.current_line = line
        if not self._debugger.should_pause(module_id, frame.code.name, line, depth=len(call_stack), frame=frame):
            return
        pause = make_pause_snapshot(
            module_id=module_id,
            code_name=frame.code.name,
            line=line,
            frame=frame,
            call_stack=call_stack,
        )
        self._debugger.on_pause(pause)


def _adapt_debugger(debugger: DebugSession | None) -> VmDebugPlugin | None:
    if debugger is None:
        return None
    return _RuntimeDebuggerPlugin(debugger)


class VM(_BaseVM):
    """Compatibility subclass preserving the historical runtime VM API."""

    def __init__(
        self,
        module=None,
        extra_builtins=None,
        initial_globals=None,
        debugger: DebugSession | None = None,
        module_name: str = "",
    ) -> None:
        super().__init__(
            module=module,
            extra_builtins=extra_builtins,
            initial_globals=initial_globals,
            debug_plugin=_adapt_debugger(debugger),
            module_name=module_name,
        )


def run_module(
    module,
    entry="OnSystemStartup",
    extra_builtins=None,
    initial_globals=None,
    debugger: DebugSession | None = None,
    strict_entry: bool = False,
):
    """Create a VM from a compiled module and call the entry function."""

    return _run_module(
        module,
        entry=entry,
        extra_builtins=extra_builtins,
        initial_globals=initial_globals,
        debug_plugin=_adapt_debugger(debugger),
        module_name=getattr(module, "name", ""),
        strict_entry=strict_entry,
    )


def execute_script(
    source,
    language="uk",
    entry="OnSystemStartup",
    extra_builtins=None,
    context=None,
    module_name: str = "",
    debug_session: DebugSession | None = None,
    strict_entry: bool = False,
):
    """Parse, compile, and execute a MetaScript source string."""

    return _execute_script(
        source,
        language=language,
        entry=entry,
        extra_builtins=extra_builtins,
        context=context,
        module_name=module_name,
        debug_plugin=_adapt_debugger(debug_session or create_debug_session_from_env()),
        strict_entry=strict_entry,
    )


__all__ = [
    "BUILTINS",
    "Frame",
    "MsArray",
    "MsException",
    "MsMap",
    "VM",
    "execute_script",
    "run_module",
]
