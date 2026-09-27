"""Verify that release artifacts are byte-reproducible in one clean source tree."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _build(output: Path) -> dict[str, str]:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "src.scripts.build_release",
            "--output",
            str(output),
        ],
        check=True,
    )
    return json.loads((output / "SHA256SUMS.json").read_text(encoding="utf-8"))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="metaplatform-release-repro-") as tmp:
        root = Path(tmp)
        first = _build(root / "first")
        second = _build(root / "second")
        if first != second:
            raise AssertionError(
                "release artifacts are not reproducible: "
                + json.dumps({"first": first, "second": second}, sort_keys=True)
            )
    print(json.dumps({"status": "ok", "artifacts": first}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
