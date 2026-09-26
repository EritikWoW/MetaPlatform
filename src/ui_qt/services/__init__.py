"""src.ui_qt.services

Сервисы UI-уровня, используемые в нескольких виджетах.

Принцип стабилизации:
    Логику, которая используется в нескольких местах, стараемся держать
    централизованно, чтобы избежать регрессий.

В частности, построение дерева конфигурации вынесено в
:mod:`src.ui_qt.services.tree_builder`.
"""

from .svg_var_resolver import SvgVarResolver, SvgVarResolveResult

__all__ = [
    "IconProvider",
    "SvgVarResolver",
    "SvgVarResolveResult",
    "BuildResult",
    "build_tree_model",
    "prepare_tree_objects",
]


def __getattr__(name: str):
    """Lazy-load Qt-backed services so pure helpers stay importable headless."""
    if name == "IconProvider":
        from .icon_provider import IconProvider

        return IconProvider
    if name in {"BuildResult", "build_tree_model", "prepare_tree_objects"}:
        from .tree_builder import BuildResult, build_tree_model, prepare_tree_objects

        values = {
            "BuildResult": BuildResult,
            "build_tree_model": build_tree_model,
            "prepare_tree_objects": prepare_tree_objects,
        }
        return values[name]
    raise AttributeError(name)
