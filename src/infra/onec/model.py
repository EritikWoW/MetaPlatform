from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class MPXObject:
    """Neutral metadata object (MPX) for round-trips 1C <-> MetaPlatform."""
    obj_type: str
    name: str
    synonym: str = ""
    comment: str = ""
    origin_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class MPXConfig:
    system_name: str = "MetaPlatform"
    objects: list[MPXObject] = field(default_factory=list)
