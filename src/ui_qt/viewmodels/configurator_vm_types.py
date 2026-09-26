from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class Dialogs(Protocol):
    """Minimal dialog API expected from the View."""

    def show_info(self, title: str, text: str) -> None: ...

    def show_warning(self, title: str, text: str) -> None: ...

    def confirm(self, title: str, text: str) -> bool: ...


@dataclass(frozen=True)
class NodeInfo:
    """Tree node descriptor used when opening editors or folders."""

    kind: str
    name: str
    guid: str = ""
    obj_type: str = ""


ObjectLike = Any
