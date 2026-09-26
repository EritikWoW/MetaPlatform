from __future__ import annotations

import json
import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("runtime.debugger")

try:
    from src.dsl.module_introspection import repair_cp1251_mojibake_name
except Exception:  # pragma: no cover - debugger must stay importable during early bootstrap
    def repair_cp1251_mojibake_name(name: str) -> str:
        return ""

try:
    from src.dsl.expression_eval import evaluate_expression
except Exception:  # pragma: no cover - debugger must stay importable during early bootstrap
    evaluate_expression = None


def _default_debug_dir() -> Path:
    base = os.environ.get("META_DEBUG_DIR") or os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "MetaPlatform" / "debug"


def _json_safe(value: Any, *, limit: int = 200) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        text = value if not isinstance(value, str) else value[:limit]
        return text
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:25]:
            out[str(key)] = _json_safe(item, limit=limit)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, limit=limit) for item in list(value)[:25]]
    text = repr(value)
    return text[:limit]


def _add_readable_aliases(raw: dict[str, Any], safe: dict[str, Any]) -> None:
    """Expose repaired CP1251-mojibake keys next to original debug names."""

    for key, value in list(raw.items()):
        if callable(value):
            continue
        alias = repair_cp1251_mojibake_name(str(key))
        if not alias or alias in raw or alias in safe:
            continue
        safe[alias] = _json_safe(value)


def _is_executable_debug_symbol(value: Any) -> bool:
    """Return True for procedure/function objects that are not data globals."""

    if callable(value):
        return True
    return (
        type(value).__name__ == "CodeObject"
        and hasattr(value, "instructions")
        and hasattr(value, "params")
    )


@dataclass(slots=True)
class DebugPause:
    module_id: str
    code_name: str
    line: int
    depth: int = 0
    locals: dict[str, Any] = field(default_factory=dict)
    globals: dict[str, Any] = field(default_factory=dict)
    stack: list[dict[str, Any]] = field(default_factory=list)
    locals_raw: dict[str, Any] = field(default_factory=dict, repr=False)
    globals_raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class BreakpointSpec:
    line: int
    enabled: bool = True
    condition: str = ""
    description: str = ""
    hit_operator: str = ""
    hit_target: int = 0
    hits: int = 0
    caller_name: str = ""
    log_message: bool = False
    action_expression: str = ""
    log_call_stack: bool = False
    log_hit_count: bool = False
    continue_execution: bool = False

    @classmethod
    def from_raw(cls, raw: Any) -> "BreakpointSpec | None":
        if isinstance(raw, BreakpointSpec):
            return raw
        if isinstance(raw, int):
            return cls(line=int(raw))
        if isinstance(raw, str) and raw.strip().isdigit():
            return cls(line=int(raw.strip()))
        if not isinstance(raw, dict):
            return None
        try:
            line = int(raw.get("line") or 0)
        except Exception:
            line = 0
        if line <= 0:
            return None
        return cls(
            line=line,
            enabled=bool(raw.get("enabled", True)),
            condition=str(raw.get("condition") or ""),
            description=str(raw.get("description") or ""),
            hit_operator=str(raw.get("hit_operator") or ""),
            hit_target=int(raw.get("hit_target") or 0),
            hits=int(raw.get("hits") or 0),
            caller_name=str(raw.get("caller_name") or ""),
            log_message=bool(raw.get("log_message", False)),
            action_expression=str(raw.get("action_expression") or ""),
            log_call_stack=bool(raw.get("log_call_stack", False)),
            log_hit_count=bool(raw.get("log_hit_count", False)),
            continue_execution=bool(raw.get("continue_execution", False)),
        )

    def to_raw(self) -> dict[str, Any]:
        return {
            "line": int(self.line),
            "enabled": bool(self.enabled),
            "condition": str(self.condition or ""),
            "description": str(self.description or ""),
            "hit_operator": str(self.hit_operator or ""),
            "hit_target": int(self.hit_target or 0),
            "hits": int(self.hits or 0),
            "caller_name": str(self.caller_name or ""),
            "log_message": bool(self.log_message),
            "action_expression": str(self.action_expression or ""),
            "log_call_stack": bool(self.log_call_stack),
            "log_hit_count": bool(self.log_hit_count),
            "continue_execution": bool(self.continue_execution),
        }


class BreakpointStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_debug_dir() / "breakpoints.json"

    def load(self) -> dict[str, list[int]]:
        if not self.breakpoints_enabled():
            return {}
        specs = self.load_specs()
        return {
            module_id: sorted({int(bp.line) for bp in items if bp.enabled and int(bp.line) > 0})
            for module_id, items in specs.items()
        }

    def _load_raw(self) -> dict[str, Any]:
        try:
            if not self.path.exists():
                return {}
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            return raw
        except Exception:
            return {}

    def save(self, data: dict[str, list[int]]) -> None:
        specs = {
            module_id: [BreakpointSpec(line=int(line)) for line in lines]
            for module_id, lines in (data or {}).items()
        }
        self.save_specs(specs)

    def breakpoints_enabled(self) -> bool:
        raw = self._load_raw()
        meta = raw.get("__meta__")
        if isinstance(meta, dict):
            return bool(meta.get("enabled", True))
        return bool(raw.get("__enabled__", True))

    def set_breakpoints_enabled(self, enabled: bool) -> None:
        raw = self._load_raw()
        meta = raw.get("__meta__")
        if not isinstance(meta, dict):
            meta = {}
        meta["enabled"] = bool(enabled)
        raw["__meta__"] = meta
        self._save_raw(raw)

    def load_specs(self) -> dict[str, list[BreakpointSpec]]:
        raw = self._load_raw()
        out: dict[str, list[BreakpointSpec]] = {}
        for key, items in raw.items():
            key_s = str(key or "")
            if key_s.startswith("__"):
                continue
            source = items
            if isinstance(items, dict):
                source = items.get("breakpoints") or items.get("lines") or []
            if not isinstance(source, list):
                continue
            specs: list[BreakpointSpec] = []
            for item in source:
                spec = BreakpointSpec.from_raw(item)
                if spec is not None and spec.line > 0:
                    specs.append(spec)
            if specs:
                out[key_s] = sorted(specs, key=lambda bp: int(bp.line))
        return out

    def save_specs(self, data: dict[str, list[BreakpointSpec]]) -> None:
        raw = self._load_raw()
        meta = raw.get("__meta__")
        if not isinstance(meta, dict):
            meta = {"enabled": bool(raw.get("__enabled__", True))}
        out: dict[str, Any] = {"__meta__": meta}
        for module_id, items in (data or {}).items():
            key = str(module_id or "").strip()
            if not key:
                continue
            clean = [bp.to_raw() for bp in sorted(items, key=lambda item: int(item.line)) if int(bp.line) > 0]
            if clean:
                out[key] = clean
        self._save_raw(out)

    def _save_raw(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def lines_for(self, module_id: str) -> set[int]:
        return {int(bp.line) for bp in self.specs_for(module_id)}

    def specs_for(self, module_id: str) -> list[BreakpointSpec]:
        return list(self.load_specs().get(str(module_id or ""), []))

    def set_lines(self, module_id: str, lines: set[int]) -> None:
        data = self.load_specs()
        key = str(module_id or "").strip()
        if not key:
            return
        existing = {int(bp.line): bp for bp in data.get(key, [])}
        clean = sorted({int(x) for x in lines if int(x) > 0})
        if clean:
            data[key] = [existing.get(line, BreakpointSpec(line=line)) for line in clean]
        else:
            data.pop(key, None)
        self.save_specs(data)

    def set_specs(self, module_id: str, specs: list[BreakpointSpec]) -> None:
        data = self.load_specs()
        key = str(module_id or "").strip()
        if not key:
            return
        clean = [bp for bp in specs if int(bp.line) > 0]
        if clean:
            data[key] = clean
        else:
            data.pop(key, None)
        self.save_specs(data)

    def toggle_line(self, module_id: str, line: int) -> set[int]:
        lines = self.lines_for(module_id)
        if int(line) in lines:
            lines.remove(int(line))
        else:
            lines.add(int(line))
        self.set_lines(module_id, lines)
        return lines

    def clear_all(self) -> None:
        raw = self._load_raw()
        meta = raw.get("__meta__")
        if not isinstance(meta, dict):
            meta = {"enabled": bool(raw.get("__enabled__", True))}
        self._save_raw({"__meta__": meta})


class DebugSession:
    def __init__(
        self,
        *,
        breakpoints: dict[str, Any] | None = None,
        pause_handler: Callable[[DebugPause], str] | None = None,
        breakpoint_store: BreakpointStore | None = None,
    ) -> None:
        self.breakpoints = breakpoints or {}
        self.pause_handler = pause_handler
        self._breakpoint_store = breakpoint_store
        self.step_mode: str = ""
        self._step_target_depth: int | None = None
        self._last_key: tuple[str, str, int] | None = None
        self._last_seen_key: tuple[str, str, int] | None = None
        self._last_seen_by_frame: dict[int, tuple[str, str, int]] = {}
        self._last_bp_key: tuple[str, str, int] | None = None

    def update_breakpoints(self, breakpoints: dict[str, Any]) -> None:
        self.breakpoints = breakpoints

    @staticmethod
    def _module_key_candidates(module_id: str) -> set[str]:
        raw = str(module_id or "").strip()
        if not raw:
            return set()
        candidates = {raw}
        if raw.startswith("module://"):
            tail = raw.split("://", 1)[1].strip()
            if tail:
                candidates.add(tail)
        else:
            tail = raw.rsplit("/", 1)[-1].strip()
            if tail:
                candidates.add(tail)
            if "://" in raw:
                candidates.add(raw.split("://", 1)[1].strip())
        return {item for item in candidates if item}

    def _breakpoint_entries_for_module(self, module_id: str) -> list[BreakpointSpec]:
        keys = self._module_key_candidates(module_id)
        if not keys:
            return []
        matched: list[BreakpointSpec] = []
        for key, raw_items in (self.breakpoints or {}).items():
            key_candidates = self._module_key_candidates(str(key or ""))
            if keys.intersection(key_candidates):
                if isinstance(raw_items, set):
                    matched.extend(BreakpointSpec(line=int(x)) for x in raw_items if int(x) > 0)
                elif isinstance(raw_items, list):
                    for item in raw_items:
                        spec = BreakpointSpec.from_raw(item)
                        if spec is not None:
                            matched.append(spec)
                else:
                    spec = BreakpointSpec.from_raw(raw_items)
                    if spec is not None:
                        matched.append(spec)
        return matched

    def _breakpoints_for_module(self, module_id: str) -> set[int]:
        matched: set[int] = set()
        for spec in self._breakpoint_entries_for_module(module_id):
            if spec.enabled:
                matched.add(int(spec.line))
        return matched

    @staticmethod
    def _line_breakpoint_match(line: int, breakpoints: list[BreakpointSpec]) -> BreakpointSpec | None:
        for spec in breakpoints:
            if int(spec.line) == int(line) and bool(spec.enabled):
                return spec
        for candidate in (line, line - 1, line + 1):
            for spec in breakpoints:
                is_parameterized = bool(
                    str(spec.condition or "").strip()
                    or str(spec.caller_name or "").strip()
                    or int(spec.hit_target or 0) > 0
                    or str(spec.action_expression or "").strip()
                    or spec.log_message
                    or spec.log_call_stack
                    or spec.log_hit_count
                    or spec.continue_execution
                )
                if is_parameterized:
                    continue
                if int(spec.line) == int(candidate) and bool(spec.enabled):
                    return spec
        return None

    @staticmethod
    def _breakpoint_caller_allows(spec: BreakpointSpec, call_stack: list[Any] | None) -> bool:
        expected = str(spec.caller_name or "").strip()
        if not expected:
            return True
        frames = list(call_stack or [])
        if len(frames) < 2:
            return False
        caller = str(getattr(getattr(frames[-2], "code", None), "name", "") or "").strip()
        return caller.casefold() == expected.casefold()

    def _breakpoint_condition_allows(
        self,
        spec: BreakpointSpec,
        frame: Any | None,
        call_stack: list[Any] | None = None,
        module_id: str = "",
    ) -> bool:
        condition = str(spec.condition or "").strip()
        if not self._breakpoint_caller_allows(spec, call_stack):
            return False
        spec.hits = int(spec.hits or 0) + 1
        self._persist_breakpoint_hits(module_id, spec)
        if spec.hit_target > 0:
            op = str(spec.hit_operator or ">=").strip() or ">="
            hits = int(spec.hits or 0)
            target = int(spec.hit_target or 0)
            if op == "=" and hits != target:
                return False
            if op == ">" and hits <= target:
                return False
            if op == ">=" and hits < target:
                return False
        if not condition:
            return True
        if frame is None:
            return False
        scope: dict[str, Any] = {}
        try:
            scope.update(dict(getattr(frame, "globals_", {}) or {}))
            scope.update(dict(getattr(frame, "locals_", {}) or {}))
            for key, value in list(scope.items()):
                alias = repair_cp1251_mojibake_name(str(key))
                if alias and alias not in scope:
                    scope[alias] = value
        except Exception:
            return False
        if evaluate_expression is None:
            logger.warning("debug.breakpoint.expression_service_unavailable")
            return False
        result, errors = evaluate_expression(condition, context=scope, module_name="<breakpoint-condition>")
        if errors:
            logger.info(
                "debug.breakpoint.condition_failed condition=%s errors=%s",
                condition,
                errors,
            )
            return False
        return bool(result)

    def _persist_breakpoint_hits(self, module_id: str, spec: BreakpointSpec) -> None:
        store = self._breakpoint_store
        if store is None:
            return
        target_keys = self._module_key_candidates(module_id)
        try:
            data = store.load_specs()
            for stored_module_id, items in data.items():
                if not target_keys.intersection(self._module_key_candidates(stored_module_id)):
                    continue
                changed = False
                for stored in items:
                    if int(stored.line) == int(spec.line):
                        stored.hits = int(spec.hits or 0)
                        changed = True
                        break
                if changed:
                    store.save_specs(data)
                    return
        except Exception:
            logger.info(
                "debug.breakpoint.hit_persist_failed module=%s line=%s",
                module_id,
                int(spec.line),
                exc_info=True,
            )

    @staticmethod
    def _breakpoint_scope(frame: Any | None) -> dict[str, Any]:
        if frame is None:
            return {}
        scope: dict[str, Any] = {}
        scope.update(dict(getattr(frame, "globals_", {}) or {}))
        scope.update(dict(getattr(frame, "locals_", {}) or {}))
        for key, value in list(scope.items()):
            alias = repair_cp1251_mojibake_name(str(key))
            if alias and alias not in scope:
                scope[alias] = value
        return scope

    def _run_breakpoint_actions(
        self,
        spec: BreakpointSpec,
        *,
        module_id: str,
        code_name: str,
        line: int,
        frame: Any | None,
        call_stack: list[Any] | None,
    ) -> None:
        if spec.log_message:
            logger.info(
                "debug.breakpoint.message module=%s code=%s line=%s description=%s",
                module_id,
                code_name,
                line,
                str(spec.description or ""),
            )
        expression = str(spec.action_expression or "").strip()
        if expression and evaluate_expression is not None:
            result, errors = evaluate_expression(
                expression,
                context=self._breakpoint_scope(frame),
                module_name=str(module_id or "<breakpoint-action>"),
            )
            logger.info(
                "debug.breakpoint.expression module=%s code=%s line=%s expression=%s result=%r errors=%s",
                module_id,
                code_name,
                line,
                expression,
                result,
                errors,
            )
        if spec.log_call_stack:
            stack_names = [
                str(getattr(getattr(item, "code", None), "name", "") or "")
                for item in list(call_stack or [])
            ]
            logger.info(
                "debug.breakpoint.stack module=%s code=%s line=%s stack=%s",
                module_id,
                code_name,
                line,
                stack_names,
            )
        if spec.log_hit_count:
            logger.info(
                "debug.breakpoint.hits module=%s code=%s line=%s hits=%s",
                module_id,
                code_name,
                line,
                int(spec.hits or 0),
            )

    def should_pause(
        self,
        module_id: str,
        code_name: str,
        line: int,
        *,
        depth: int = 0,
        frame: Any | None = None,
        call_stack: list[Any] | None = None,
    ) -> bool:
        if line <= 0:
            return False
        key = (str(module_id or ""), str(code_name or ""), int(line))
        if frame is not None:
            frame_id = id(frame)
            if self._last_seen_by_frame.get(frame_id) == key:
                return False
            self._last_seen_by_frame[frame_id] = key
            if len(self._last_seen_by_frame) > 1024:
                self._last_seen_by_frame.pop(next(iter(self._last_seen_by_frame)), None)
        else:
            if key == self._last_seen_key:
                return False
            self._last_seen_key = key
        mode = str(self.step_mode or "").strip().lower()
        bp = self._breakpoint_entries_for_module(module_id)
        matched_bp = self._line_breakpoint_match(int(line), bp)
        matched_bp_line = int(matched_bp.line) if matched_bp is not None else 0
        bp_key = (str(module_id or ""), str(code_name or ""), matched_bp_line)
        exact_breakpoint_line = bool(matched_bp is not None and matched_bp_line == int(line))
        try:
            logger.info(
                "debug.should_pause module=%s code=%s line=%s depth=%s bp_hit=%s mode=%s",
                module_id,
                code_name,
                line,
                depth,
                bool(matched_bp_line),
                mode or "",
            )
        except Exception:
            pass
        if (
            matched_bp_line
            and (exact_breakpoint_line or bp_key != self._last_bp_key)
            and self._breakpoint_condition_allows(
                matched_bp,
                frame,
                call_stack,
                module_id=str(module_id or ""),
            )
        ):
            self._last_key = key
            self._last_bp_key = bp_key
            self._run_breakpoint_actions(
                matched_bp,
                module_id=str(module_id or ""),
                code_name=str(code_name or ""),
                line=int(line),
                frame=frame,
                call_stack=call_stack,
            )
            if matched_bp.continue_execution:
                return False
            return True
        if not matched_bp_line:
            self._last_bp_key = None
        if mode == "step_into":
            self._last_key = key
            return True
        target_depth = self._step_target_depth
        if mode in {"step_over", "step_out"}:
            if target_depth is None:
                target_depth = max(int(depth), 0)
                self._step_target_depth = target_depth
            if int(depth) <= int(target_depth):
                self._last_key = key
                return True
        return False

    def on_pause(self, pause: DebugPause) -> str:
        if self.pause_handler is None:
            return "continue"
        try:
            cmd = str(self.pause_handler(pause) or "continue").strip().lower()
        except Exception:
            cmd = "continue"
        try:
            logger.info(
                "debug.on_pause module=%s code=%s line=%s depth=%s cmd=%s",
                getattr(pause, "module_id", ""),
                getattr(pause, "code_name", ""),
                getattr(pause, "line", 0),
                getattr(pause, "depth", 0),
                cmd,
            )
        except Exception:
            pass
        if cmd in {"step", "step_into"}:
            self.step_mode = "step_into"
            self._step_target_depth = int(getattr(pause, "depth", 0) or 0)
        elif cmd == "step_over":
            self.step_mode = "step_over"
            self._step_target_depth = int(getattr(pause, "depth", 0) or 0)
        elif cmd == "step_out":
            self.step_mode = "step_out"
            self._step_target_depth = max(int(getattr(pause, "depth", 0) or 0) - 1, 0)
        else:
            self.step_mode = ""
            self._step_target_depth = None
        return cmd


def _env_pause_handler(pause: DebugPause) -> str:
    if os.environ.get("META_CLIENT_DEBUG", "").strip() != "1":
        return "continue"
    try:
        from src.client.debug_support import show_debug_pause

        return show_debug_pause(pause)
    except Exception:
        return "continue"


def create_debug_session_from_env() -> DebugSession | None:
    if os.environ.get("META_DEBUG_ENABLED", "").strip() != "1":
        return None
    store = BreakpointStore()
    raw = store.load_specs() if store.breakpoints_enabled() else {}
    breakpoints = {key: list(items) for key, items in raw.items()}
    return DebugSession(
        breakpoints=breakpoints,
        pause_handler=_env_pause_handler,
        breakpoint_store=store,
    )


def make_pause_snapshot(*, module_id: str, code_name: str, line: int, frame: Any, call_stack: list[Any]) -> DebugPause:
    raw_locals = dict(getattr(frame, "locals_", {}) or {})
    raw_globals = dict(getattr(frame, "globals_", {}) or {})
    locals_map = {str(k): _json_safe(v) for k, v in raw_locals.items()}
    _add_readable_aliases(raw_locals, locals_map)
    globals_map = {}
    for key, value in raw_globals.items():
        if _is_executable_debug_symbol(value):
            continue
        if str(key).startswith("__mp_"):
            continue
        globals_map[str(key)] = _json_safe(value)
        if len(globals_map) >= 250:
            break
    _add_readable_aliases(raw_globals, globals_map)
    stack = []
    for fr in call_stack:
        stack.append(
            {
                "code_name": str(getattr(getattr(fr, "code", None), "name", "")),
                "line": int(getattr(fr, "current_line", 0) or 0),
            }
        )
    return DebugPause(
        module_id=str(module_id or ""),
        code_name=str(code_name or ""),
        line=int(line or 0),
        depth=len(call_stack or []),
        locals=locals_map,
        globals=globals_map,
        stack=stack,
        locals_raw=raw_locals,
        globals_raw=raw_globals,
    )
