"""Audit imported 1C/BAS modules against the MetaScript frontend."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from src.dsl.compiler import compile_module
from src.dsl.languages import MIXED_PROFILE
from src.dsl.parser import parse
from src.infra.onec.onecd_source import OneCDConfigSource


_INVALID_SOURCE_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]")


def _read_module(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")


def _decode_module(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")


def _iter_modules(root: Path):
    if root.is_dir():
        for path in sorted(root.rglob("*.bsl")):
            yield path.relative_to(root).as_posix(), _read_module(path)
        return

    if root.is_file() and root.suffix.lower() == ".1cd":
        source = OneCDConfigSource(root)
        for relative in sorted(
            path for path in source.list_files() if path.lower().endswith(".bsl")
        ):
            yield relative, _decode_module(source.read_bytes(relative))
        return

    raise ValueError(f"Expected an XMLConf directory or .1CD file: {root}")


def audit_corpus(root: Path) -> dict[str, Any]:
    root = Path(root)
    modules = _iter_modules(root)
    failures: list[dict[str, Any]] = []
    started = time.perf_counter()
    total = 0

    for relative, source in modules:
        total += 1
        invalid_char = _INVALID_SOURCE_CHAR_RE.search(source)
        if invalid_char is not None:
            prefix = source[:invalid_char.start()]
            line = prefix.count("\n") + 1
            line_start = prefix.rfind("\n") + 1
            failures.append(
                {
                    "path": relative,
                    "stage": "source",
                    "line": line,
                    "column": invalid_char.start() - line_start + 1,
                    "message": f"Invalid source character U+{ord(invalid_char.group(0)):04X}",
                }
            )
            continue
        program, diagnostics = parse(source, MIXED_PROFILE)
        errors = [item for item in diagnostics if item.severity == "error"]
        if program is None or errors:
            diagnostic = errors[0] if errors else diagnostics[0]
            failures.append(
                {
                    "path": relative,
                    "stage": "parse",
                    "line": int(diagnostic.span.line),
                    "column": int(diagnostic.span.col),
                    "message": diagnostic.message,
                }
            )
            continue
        try:
            compile_module(program, module_name=relative)
        except Exception as exc:
            failures.append(
                {
                    "path": relative,
                    "stage": "compile",
                    "line": 0,
                    "column": 0,
                    "message": str(exc),
                }
            )

    return {
        "root": str(root.resolve()),
        "total": total,
        "passed": total - len(failures),
        "failed": len(failures),
        "seconds": round(time.perf_counter() - started, 3),
        "failures": failures,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse and compile every .bsl module in XMLConf or a direct .1CD source.",
    )
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path("WorkedData/XMLConf"),
        help="XMLConf root directory or .1CD file (default: WorkedData/XMLConf)",
    )
    parser.add_argument("--json", action="store_true", help="Print the complete JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.root.exists() or (
        not args.root.is_dir() and args.root.suffix.lower() != ".1cd"
    ):
        print(f"DSL corpus source does not exist or is unsupported: {args.root}")
        return 2

    report = audit_corpus(args.root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            "DSL corpus: "
            f"total={report['total']} passed={report['passed']} "
            f"failed={report['failed']} seconds={report['seconds']:.3f}"
        )
        for failure in report["failures"]:
            print(
                f"{failure['stage'].upper()} "
                f"{failure['path']}:{failure['line']}:{failure['column']} "
                f"{failure['message']}"
            )
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
