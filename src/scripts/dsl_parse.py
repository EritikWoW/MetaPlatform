"""CLI helper: parse DSL file and print diagnostics.

Usage:
    python -m src.scripts.dsl_parse <file.dsl> --lang uk|en
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.dsl import parse_dsl


def main() -> int:
    p = argparse.ArgumentParser(description="Parse MetaPlatform DSL")
    p.add_argument("path", type=str, help="Path to DSL file")
    p.add_argument("--lang", choices=["uk", "en"], default="uk")
    args = p.parse_args()

    text = Path(args.path).read_text(encoding="utf-8")
    res = parse_dsl(text, language=args.lang)

    if not res.diagnostics:
        print("OK")
        return 0

    ok = True
    for d in res.diagnostics:
        print(f"{d.severity.upper()}: {d.message} @ {d.span.line}:{d.span.col}")
        if d.severity == "error":
            ok = False
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
