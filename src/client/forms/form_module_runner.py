"""Form module runner — executes MetaScript form modules.

FormContext  — proxy object exposed to MetaScript as ThisForm / ЦяФорма.
FormModuleRunner — loads, compiles, and dispatches calls into a MetaScript module.
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger("client.form_module")

# Sentinel for "procedure not found" (distinct from None return value)
_NOT_FOUND = object()


class FormContext:
    """Proxy object exposed to MetaScript as ThisForm / ЦяФорма.

    Field access example (in MetaScript):
        ThisForm.Description = "New value";
        Сума = ThisForm.Amount;

    Methods:
        ThisForm.Write()   — save current record
        ThisForm.Close()   — close form
        ThisForm.Refresh() — reload list
        ThisForm.Message("text") — show info dialog
    """

    def __init__(self, form_widget: Any) -> None:
        object.__setattr__(self, "_fw", form_widget)

    def __getattr__(self, name: str) -> Any:
        fw = object.__getattribute__(self, "_fw")
        return fw._record_value_for_binding(fw._record, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        fw = object.__getattribute__(self, "_fw")
        key = fw._record_key_for_binding(name)
        fw._record[key] = value
        w = fw._bound_inputs.get(name)
        if w is not None:
            fw._set_val(w, value)

    # ── Commands ─────────────────────────────────────────────────────────────

    def Close(self) -> None:
        object.__getattribute__(self, "_fw")._emit_command_raw("close")

    def Write(self) -> None:
        object.__getattribute__(self, "_fw")._emit_command_raw("save")

    def Refresh(self) -> None:
        object.__getattribute__(self, "_fw").reload_list()

    def Message(self, text: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(None, "", str(text or ""))

    # Ukrainian aliases
    Закрити = Close
    Записати = Write
    Оновити = Refresh
    Повідомити = Message

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def Object(self) -> dict:
        return dict(object.__getattribute__(self, "_fw")._record)

    @property
    def Modified(self) -> bool:
        return True


class FormModuleRunner:
    """Loads, compiles, and dispatches calls into a MetaScript form module."""

    def __init__(
        self,
        source_text: str,
        context: FormContext,
        language: str = "uk",
        extra_builtins: dict[str, Any] | None = None,
    ) -> None:
        self._compiled: Any = None
        self._vm: Any = None
        self._errors: list[str] = []

        src = str(source_text or "").strip()
        if not src:
            return

        try:
            from src.dsl.languages import get_profile
            from src.dsl.parser import parse
            from src.dsl.compiler import compile_module
            from src.dsl.vm import VM

            lang = str(language or "uk").strip().lower()
            if lang not in {"uk", "en"}:
                lang = "uk"

            profile = get_profile(lang)
            prog, diags = parse(src, profile)
            errors = [
                f"L{d.span.line}:{d.span.col} {d.message}"
                for d in diags
                if d.severity == "error"
            ]
            if errors or prog is None:
                self._errors = errors
                logger.warning("Form module parse errors for %s: %s", language, errors)
                return

            self._compiled = compile_module(prog, module_name="FormModule")
            builtins = dict(extra_builtins or {})
            builtins.update(
                {
                    "ThisForm": context,
                    "ЦяФорма": context,
                    "Форма": context,
                }
            )
            self._vm = VM(
                module=self._compiled,
                extra_builtins=builtins,
            )
            logger.debug(
                "Form module loaded ok — procedures=%s functions=%s",
                sorted(self._compiled.procedures),
                sorted(self._compiled.functions),
            )
        except Exception as exc:
            self._errors = [str(exc)]
            logger.warning("Form module load error: %s", exc, exc_info=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def has_handler(self, name: str) -> bool:
        if self._compiled is None:
            return False
        return bool(
            self._compiled.functions.get(name)
            or self._compiled.procedures.get(name)
        )

    def call_handler(self, name: str, *args: Any) -> tuple[bool, Any]:
        """Call a handler by name. Returns (found, result)."""
        if not self.has_handler(name):
            return False, None
        try:
            result = self._vm.call(name, *args)
            return True, result
        except Exception as exc:
            logger.warning("Form module runtime error in %s(): %s", name, exc)
            return True, None

    @property
    def is_loaded(self) -> bool:
        return self._vm is not None

    @property
    def has_errors(self) -> bool:
        return bool(self._errors)

    @property
    def errors(self) -> list[str]:
        return list(self._errors)
