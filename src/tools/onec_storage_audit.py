from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.infra.onec.storage_alignment import build_storage_alignment_report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a MetaPlatform vs 1C storage-alignment report.",
    )
    parser.add_argument("source_path", help="Path to XMLConf, 1Cv8.dt or 1Cv8.1CD")
    parser.add_argument(
        "--source-kind",
        default="auto",
        help="Source kind override: auto, xml, zip, dt, 1cd",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Optional path to write the JSON report.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = build_storage_alignment_report(args.source_path, args.source_kind)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
