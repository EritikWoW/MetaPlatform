from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_import_path() -> None:
    # Ensure .../src is in sys.path
    src_dir = Path(__file__).resolve().parents[1]
    src_str = str(src_dir)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


def main(argv: list[str] | None = None) -> int:
    _bootstrap_import_path()
    from src.mpdb.doctor import check

    ap = argparse.ArgumentParser(description="mpdb doctor: offline integrity checker")
    ap.add_argument("path", help="Path to .mpdb file")
    ap.add_argument("--max-pages", type=int, default=None, help="Limit number of pages to scan")
    ap.add_argument("--json", action="store_true", help="Print report as JSON")
    args = ap.parse_args(argv)

    rep = check(args.path, max_pages=args.max_pages)
    if args.json:
        print(json.dumps(rep.__dict__, ensure_ascii=False, default=lambda o: o.__dict__, indent=2))
    else:
        print(f"Path: {rep.path}")
        print(f"OK: {rep.ok}")
        print(f"File size: {rep.file_size} bytes")
        print(f"Format: v{rep.format_major}.{rep.format_rev}")
        print(f"Page size: {rep.page_size}")
        print(f"Pages checked: {rep.pages_checked}/{rep.pages_total} (bad: {rep.pages_bad})")
        print(f"WAL records readable: {rep.wal_records_ok}")
        if rep.issues:
            print("Issues:")
            for it in rep.issues:
                pid = f" page={it.page_id}" if it.page_id is not None else ""
                print(f" - [{it.code}]{pid}: {it.message}")

    return 0 if rep.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
