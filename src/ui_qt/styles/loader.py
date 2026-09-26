from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Mapping, Sequence


def render_qss_fragments(
    *,
    base_dir: Path,
    fragments: Sequence[str],
    tokens: Mapping[str, object],
) -> str:
    prepared = {key: str(value) for key, value in tokens.items()}
    rendered: list[str] = []
    for fragment_name in fragments:
        fragment_path = base_dir / fragment_name
        fragment_text = fragment_path.read_text(encoding="utf-8")
        rendered.append(Template(fragment_text).safe_substitute(prepared).strip())
    return "\n\n".join(part for part in rendered if part)
