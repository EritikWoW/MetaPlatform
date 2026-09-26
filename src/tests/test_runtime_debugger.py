from src.runtime.script.compiler import (
    CodeObject,
    Instruction,
    LOAD_CONST,
    RETURN_NONE,
    STORE_NAME,
    ModuleCode,
)
from src.runtime.script.debugger import BreakpointSpec, BreakpointStore, DebugPause, DebugSession
from src.runtime.script.debugger import make_pause_snapshot
from src.runtime.script.vm import run_module
from src.runtime.script.vm import execute_script as execute_runtime_script
from src.client.debug_support import evaluate_debug_expression


def _build_test_module() -> ModuleCode:
    main = CodeObject(
        name="Main",
        params=[],
        by_value=[],
        defaults=[],
        instructions=[
            Instruction(op=LOAD_CONST, arg=True, lineno=3),
            Instruction(op=STORE_NAME, arg="Cancel", lineno=3),
            Instruction(op=RETURN_NONE, lineno=4),
        ],
        locals_=[],
        exported=False,
        is_function=False,
    )
    return ModuleCode(
        name="module://test-module",
        procedures={"Main": main},
        functions={},
        module_vars=[],
    )


def test_run_module_updates_context_globals() -> None:
    ctx = {"Cancel": False}
    run_module(_build_test_module(), entry="Main", initial_globals=ctx)
    assert ctx["Cancel"] is True


def test_debug_session_pauses_once_per_line() -> None:
    pauses = []
    session = DebugSession(
        breakpoints={"module://test-module": {3}},
        pause_handler=lambda pause: pauses.append((pause.module_id, pause.code_name, pause.line)) or "continue",
    )
    run_module(_build_test_module(), entry="Main", initial_globals={"Cancel": False}, debugger=session)
    assert pauses == [("module://test-module", "Main", 3)]


def test_debug_session_plain_breakpoint_fires_again_when_loop_returns_to_exact_line() -> None:
    session = DebugSession(breakpoints={"module://test-module": {3}})
    assert session.should_pause("module://test-module", "Main", 3)
    assert not session.should_pause("module://test-module", "Main", 4)
    assert session.should_pause("module://test-module", "Main", 3)


def test_debug_session_does_not_repeat_caller_breakpoint_after_nested_call_returns() -> None:
    session = DebugSession(
        breakpoints={
            "module://caller": {7},
            "module://callee": {19},
        }
    )
    caller = object()
    callee = object()

    assert session.should_pause(
        "module://caller", "BeforeStart", 7, frame=caller, call_stack=[caller]
    )
    assert session.should_pause(
        "module://callee", "ResolveForm", 19, frame=callee, call_stack=[caller, callee]
    )
    assert not session.should_pause(
        "module://caller", "BeforeStart", 7, frame=caller, call_stack=[caller]
    )


def test_debug_session_conditional_breakpoint_pauses_when_true() -> None:
    pauses = []
    session = DebugSession(
        breakpoints={"module://test-module": [BreakpointSpec(line=3, condition="Cancel = Ложь")]},
        pause_handler=lambda pause: pauses.append(pause.line) or "continue",
    )
    run_module(_build_test_module(), entry="Main", initial_globals={"Cancel": False}, debugger=session)
    assert pauses == [3]


def test_debug_session_conditional_breakpoint_skips_when_false() -> None:
    pauses = []
    session = DebugSession(
        breakpoints={"module://test-module": [BreakpointSpec(line=3, condition="Cancel = Истина")]},
        pause_handler=lambda pause: pauses.append(pause.line) or "continue",
    )
    run_module(_build_test_module(), entry="Main", initial_globals={"Cancel": False}, debugger=session)
    assert pauses == []


def test_debug_session_conditional_breakpoint_supports_metascript_boolean_syntax() -> None:
    pauses = []
    session = DebugSession(
        breakpoints={
            "module://test-module": [
                BreakpointSpec(line=3, condition="Cancel = Хибність Або Cancel = Істина")
            ]
        },
        pause_handler=lambda pause: pauses.append(pause.line) or "continue",
    )
    run_module(_build_test_module(), entry="Main", initial_globals={"Cancel": False}, debugger=session)
    assert pauses == [3]


def test_debug_session_conditional_breakpoint_repairs_mojibake_names() -> None:
    pauses = []
    session = DebugSession(
        breakpoints={
            "module://test-module": [
                BreakpointSpec(line=3, condition="глФормаНачальнойНастройкиПрограммы = \"ready\"")
            ]
        },
        pause_handler=lambda pause: pauses.append(pause.line) or "continue",
    )
    run_module(
        _build_test_module(),
        entry="Main",
        initial_globals={"ãëÔîðìàÍà÷àëüíîéÍàñòðîéêèÏðîãðàììû": "ready", "Cancel": False},
        debugger=session,
    )
    assert pauses == [3]


def test_breakpoint_spec_round_trips_extended_parameters() -> None:
    source = BreakpointSpec(
        line=17,
        condition="Counter > 2",
        description="Trace checkpoint",
        hit_operator="=",
        hit_target=3,
        hits=2,
        caller_name="LoadData",
        log_message=True,
        action_expression="Counter + 1",
        log_call_stack=True,
        log_hit_count=True,
        continue_execution=True,
    )
    restored = BreakpointSpec.from_raw(source.to_raw())
    assert restored is not None
    assert restored.to_raw() == source.to_raw()


def test_debug_session_breakpoint_respects_hit_target() -> None:
    pauses = []
    spec = BreakpointSpec(line=3, hit_operator="=", hit_target=2)
    session = DebugSession(
        breakpoints={"module://test-module": [spec]},
        pause_handler=lambda pause: pauses.append(pause.line) or "continue",
    )
    run_module(_build_test_module(), entry="Main", initial_globals={"Cancel": False}, debugger=session)
    run_module(_build_test_module(), entry="Main", initial_globals={"Cancel": False}, debugger=session)
    assert pauses == [3]
    assert spec.hits == 2


def test_debug_session_breakpoint_can_log_and_continue(caplog) -> None:
    pauses = []
    spec = BreakpointSpec(
        line=3,
        description="startup trace",
        log_message=True,
        action_expression="Cancel = Хибність",
        log_hit_count=True,
        continue_execution=True,
    )
    session = DebugSession(
        breakpoints={"module://test-module": [spec]},
        pause_handler=lambda pause: pauses.append(pause.line) or "continue",
    )
    with caplog.at_level("INFO", logger="runtime.debugger"):
        run_module(_build_test_module(), entry="Main", initial_globals={"Cancel": False}, debugger=session)
    assert pauses == []
    assert "startup trace" in caplog.text
    assert "result=True" in caplog.text
    assert "hits=1" in caplog.text


def test_debug_session_persists_runtime_hit_count(tmp_path) -> None:
    store = BreakpointStore(tmp_path / "breakpoints.json")
    stored = BreakpointSpec(line=3)
    store.set_specs("module://test-module", [stored])
    session_spec = BreakpointSpec.from_raw(stored.to_raw())
    assert session_spec is not None
    session = DebugSession(
        breakpoints={"module://test-module": [session_spec]},
        pause_handler=lambda pause: "continue",
        breakpoint_store=store,
    )
    run_module(_build_test_module(), entry="Main", initial_globals={"Cancel": False}, debugger=session)
    restored = store.specs_for("module://test-module")
    assert len(restored) == 1
    assert restored[0].hits == 1


def test_debug_session_breakpoint_filters_immediate_caller() -> None:
    class Code:
        def __init__(self, name: str) -> None:
            self.name = name

    class Frame:
        def __init__(self, name: str) -> None:
            self.code = Code(name)
            self.globals_ = {}
            self.locals_ = {}

    spec = BreakpointSpec(line=3, caller_name="ExpectedCaller")
    session = DebugSession(breakpoints={"module://test-module": [spec]})
    current = Frame("Target")
    assert session.should_pause(
        "module://test-module",
        "Target",
        3,
        frame=current,
        call_stack=[Frame("ExpectedCaller"), current],
    )

    session = DebugSession(breakpoints={"module://test-module": [BreakpointSpec(line=3, caller_name="ExpectedCaller")]})
    assert not session.should_pause(
        "module://test-module",
        "Target",
        3,
        frame=current,
        call_stack=[Frame("OtherCaller"), current],
    )


def test_debugger_pauses_inside_module_initializer() -> None:
    pauses = []
    session = DebugSession(
        breakpoints={"module://initializer-debug": {1}},
        pause_handler=lambda pause: pauses.append((pause.code_name, pause.line)) or "continue",
    )
    result, errors = execute_runtime_script(
        "Counter = Counter + 1;\n"
        "Функція Main()\n"
        "    Повернути Counter;\n"
        "КінецьФункції\n",
        language="mixed",
        entry="Main",
        context={"Counter": 0},
        module_name="module://initializer-debug",
        debug_session=session,
    )

    assert errors == []
    assert result == 1
    assert pauses == [("__module_init__", 1)]


def test_evaluate_debug_expression_uses_pause_scope() -> None:
    pause = DebugPause(
        module_id="module://test-module",
        code_name="Main",
        line=3,
        locals_raw={"Counter": 41},
        globals_raw={"Name": "Test"},
    )
    result, errors = evaluate_debug_expression(pause, "Counter + 1")
    assert errors == []
    assert result == 42


def test_evaluate_debug_expression_uses_control_api_safe_scope() -> None:
    pause = DebugPause(
        module_id="module://test-module",
        code_name="Main",
        line=3,
        locals={"Counter": 41},
        globals={"Name": "Test"},
    )
    result, errors = evaluate_debug_expression(pause, "Counter + 1")
    assert errors == []
    assert result == 42


def test_evaluate_debug_expression_falls_back_to_metascript_syntax() -> None:
    pause = DebugPause(
        module_id="module://test-module",
        code_name="Main",
        line=3,
        locals_raw={"Counter": 41},
    )
    result, errors = evaluate_debug_expression(pause, "Counter = 41 Або Counter = 42")
    assert errors == []
    assert result is True


def test_evaluate_debug_expression_repairs_mojibake_scope_names() -> None:
    pause = DebugPause(
        module_id="module://test-module",
        code_name="Main",
        line=3,
        globals_raw={"ãëÔîðìàÍà÷àëüíîéÍàñòðîéêèÏðîãðàììû": "ready"},
    )
    result, errors = evaluate_debug_expression(pause, "глФормаНачальнойНастройкиПрограммы")
    assert errors == []
    assert result == "ready"


def test_debug_pause_snapshot_exposes_readable_mojibake_aliases() -> None:
    class Frame:
        locals_ = {"ãëÔîðìàÍà÷àëüíîéÍàñòðîéêèÏðîãðàììû": "local"}
        globals_ = {"ãëÏàðàìåòðûÏðèëîæåíèÿ": "global"}

    pause = make_pause_snapshot(
        module_id="module://test-module",
        code_name="Main",
        line=3,
        frame=Frame(),
        call_stack=[],
    )

    assert pause.locals["глФормаНачальнойНастройкиПрограммы"] == "local"
    assert pause.globals["глПараметрыПриложения"] == "global"


def test_debug_pause_snapshot_filters_executable_globals_before_limit() -> None:
    target_name = "глФормаНачальнойНастройкиПрограммы"

    class Frame:
        locals_ = {}
        globals_ = {
            **{f"Procedure{idx}": (lambda: None) for idx in range(30)},
            target_name: None,
        }

    pause = make_pause_snapshot(
        module_id="module://startup-module",
        code_name="ПередНачаломРаботыСистемы",
        line=87,
        frame=Frame(),
        call_stack=[],
    )
    transported = DebugPause(
        module_id=pause.module_id,
        code_name=pause.code_name,
        line=pause.line,
        globals=dict(pause.globals),
    )

    assert target_name in pause.globals
    result, errors = evaluate_debug_expression(transported, target_name)
    assert errors == []
    assert result is None


def test_debug_session_step_over_and_out_use_depth() -> None:
    commands = iter(["step_over", "step_out", "continue"])
    session = DebugSession(
        pause_handler=lambda pause: next(commands, "continue"),
    )

    first_pause = DebugPause(module_id="module://test-module", code_name="Main", line=3, depth=1)
    assert session.on_pause(first_pause) == "step_over"
    assert session.should_pause("module://test-module", "Main", 4, depth=2) is False
    assert session.should_pause("module://test-module", "Main", 5, depth=1) is True

    second_pause = DebugPause(module_id="module://test-module", code_name="Main", line=6, depth=2)
    assert session.on_pause(second_pause) == "step_out"
    assert session.should_pause("module://test-module", "Main", 7, depth=2) is False
    assert session.should_pause("module://test-module", "Main", 8, depth=1) is True
