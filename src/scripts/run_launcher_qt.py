from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _bootstrap_import_path() -> None:
    """
    Обеспечивает, что в sys.path есть папка .../src,
    чтобы работали импорты вида: from MetaPlatform....
    """
    # run_launcher_qt.py = .../src/MetaPlatform/scripts/run_launcher_qt.py
    src_dir = Path(__file__).resolve().parents[2]  # .../src
    src_str = str(src_dir)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


def main() -> int:
    _bootstrap_import_path()

    # ВАЖНО: импортируем по каноническому пути, без "src."
    from src.ui_qt.app import run
    args = parse_args()
    return run(debug_ui=args.debug_ui)

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--debug-ui", action="store_true", help="Run configurator in-process for debugging")
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
