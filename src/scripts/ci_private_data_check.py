"""Fail CI when tracked files contain private database artifacts or obvious secrets."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


FORBIDDEN_SUFFIXES = {
    ".1cd",
    ".mpdb",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".bak",
    ".pem",
    ".pfx",
    ".p12",
    ".key",
}
SECRET_PATTERNS = {
    "private_key": re.compile(re.escape(b"-----BEGIN " + b"PRIVATE KEY-----")),
    "github_token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "github_pat": re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "aws_access_key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
}


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [
        Path(item.decode("utf-8"))
        for item in result.stdout.split(b"\0")
        if item
    ]


def main() -> int:
    violations: list[str] = []
    for path in _tracked_files():
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            violations.append(f"private artifact: {path}")
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(data):
                violations.append(f"{name}: {path}")
    if violations:
        raise SystemExit(
            "Tracked private data/secret scan failed:\n- " + "\n- ".join(violations)
        )
    print("Tracked private data/secret scan: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
