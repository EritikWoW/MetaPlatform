from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_import_path() -> None:
    """
    Ensure the repository src/ directory is importable.
    """
    src_dir = Path(__file__).resolve().parents[2]
    src_str = str(src_dir)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


def main() -> int:
    _bootstrap_import_path()
    from src.scripts.configurator_autopilot import main as autopilot_main

    return autopilot_main()


if __name__ == "__main__":
    raise SystemExit(main())
