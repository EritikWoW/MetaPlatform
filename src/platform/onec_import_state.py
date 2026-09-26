from __future__ import annotations

import json
import time
from typing import Any, Dict

from .paths import get_user_config_dir


_STATE_PATH = get_user_config_dir() / "last_onec_import.json"


def remember_last_onec_import(*, source_path: str, source_kind: str) -> None:
    payload = {
        "source_path": str(source_path or "").strip(),
        "source_kind": str(source_kind or "").strip(),
        "updated_at": time.time(),
    }
    _STATE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_last_onec_import() -> Dict[str, Any]:
    try:
        raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


__all__ = ["remember_last_onec_import", "load_last_onec_import"]
