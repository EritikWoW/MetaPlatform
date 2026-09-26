from __future__ import annotations

"""Shared expression evaluation for IDE and runtime debugging surfaces."""

import re
from typing import Any, Mapping

from src.dsl.module_introspection import repair_cp1251_mojibake_name


def normalize_expression(expression: str) -> str:
    """Collapse editor line separators without changing MetaScript syntax."""

    return (
        str(expression or "")
        .replace("\u2029", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )


def normalize_python_expression(expression: str) -> str:
    """Translate the simple expression subset accepted directly by Python."""

    text = normalize_expression(expression)
    if not text:
        return ""
    replacements = {
        "<>": "!=",
        "Истина": "True",
        "Ложь": "False",
        "Істина": "True",
        "Хибність": "False",
        "Невизначено": "None",
        "Неопределено": "None",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"(?<![<>=!])=(?!=)", "==", text, count=1)


def build_expression_context(*scopes: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge scopes and expose readable aliases for imported CP1251 names."""

    context: dict[str, Any] = {}
    for scope in scopes:
        if scope:
            context.update(dict(scope))
    for key, value in list(context.items()):
        alias = repair_cp1251_mojibake_name(str(key))
        if alias and alias not in context:
            context[alias] = value
    return context


def evaluate_expression(
    expression: str,
    *,
    context: Mapping[str, Any] | None = None,
    module_name: str = "<debug-expression>",
) -> tuple[Any, list[str]]:
    """Evaluate a debug expression using Python fast-path and MetaScript fallback."""

    text = normalize_expression(expression)
    if not text:
        return None, ["Expression is empty"]
    scope = build_expression_context(context)
    try:
        return eval(normalize_python_expression(text), {"__builtins__": {}}, scope), []
    except Exception:
        pass

    # Import lazily: the VM imports debugger adapters during runtime bootstrap.
    from src.dsl.vm import execute_script

    source = (
        "Функція __MetaPlatformEvaluate__()\n"
        f"    Повернути {text}\n"
        "КінецьФункції\n"
    )
    try:
        result, errors = execute_script(
            source,
            language="mixed",
            entry="__MetaPlatformEvaluate__",
            context=dict(scope),
            module_name=str(module_name or "<debug-expression>"),
            strict_entry=True,
        )
        return result, list(errors or [])
    except Exception as exc:
        return None, [str(exc)]


__all__ = [
    "build_expression_context",
    "evaluate_expression",
    "normalize_expression",
    "normalize_python_expression",
]
