"""Build a reproducible MetaPlatform wheel and source release bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOP_LEVEL_FILES = (
    "README.md",
    "ARCHITECTURE.md",
    "SECURITY.md",
    "AGENTS.md",
    "CLAUDE.md",
    "pyproject.toml",
    "requirements.lock",
    "Server.bat",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_source_files():
    for path in sorted((ROOT / "src").rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if "__pycache__" in rel.parts or ".pytest_cache" in rel.parts:
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        yield path, rel
    for name in TOP_LEVEL_FILES:
        path = ROOT / name
        if path.is_file():
            yield path, Path(name)
    docs = ROOT / "docs"
    if docs.is_dir():
        for path in sorted(docs.rglob("*")):
            if path.is_file():
                yield path, path.relative_to(ROOT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(project["project"]["version"])
    name = str(project["project"]["name"])
    bundle = output / f"{name}-{version}-windows-source.zip"

    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-w", str(output)],
        check=True,
        cwd=ROOT,
    )

    metadata = {
        "name": name,
        "version": version,
        "python": project["project"]["requires-python"],
        "entry_points": dict(project["project"].get("scripts") or {}),
        "dependency_lock": "requirements.lock",
        "rollback": "Install the previous wheel/source bundle and restore the pre-import mpdb backup.",
    }
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, rel in _iter_source_files():
            archive.write(path, rel.as_posix())
        archive.writestr(
            "VERSION.json",
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        )

    artifacts = [
        path for path in output.iterdir()
        if path.is_file() and path.suffix in {".whl", ".zip"}
    ]
    checksums = {path.name: _sha256(path) for path in sorted(artifacts)}
    checksum_path = output / "SHA256SUMS.json"
    checksum_path.write_text(
        json.dumps(checksums, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "ok", "version": version, "artifacts": checksums}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
