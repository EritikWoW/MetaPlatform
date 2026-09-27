"""Build deterministic MetaPlatform wheel and source release bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATE_EPOCH = "946684800"  # 2000-01-01T00:00:00Z
ZIP_DATE_TIME = (2000, 1, 1, 0, 0, 0)
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


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_DATE_TIME)
    info.create_system = 3
    info.external_attr = (0o644 & 0xFFFF) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _write_zip_bytes(
    archive: zipfile.ZipFile,
    name: str,
    data: bytes,
) -> None:
    archive.writestr(
        _zip_info(name),
        data,
        compress_type=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    )


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

    env = os.environ.copy()
    env.setdefault("SOURCE_DATE_EPOCH", SOURCE_DATE_EPOCH)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(ROOT),
            "--no-deps",
            "--no-build-isolation",
            "-w",
            str(output),
        ],
        check=True,
        cwd=ROOT,
        env=env,
    )

    metadata = {
        "name": name,
        "version": version,
        "python": project["project"]["requires-python"],
        "entry_points": dict(project["project"].get("scripts") or {}),
        "dependency_lock": "requirements.lock",
        "source_date_epoch": env["SOURCE_DATE_EPOCH"],
        "rollback": "Install the previous wheel/source bundle and restore the pre-import mpdb backup.",
    }
    with zipfile.ZipFile(bundle, "w") as archive:
        for path, rel in _iter_source_files():
            _write_zip_bytes(archive, rel.as_posix(), path.read_bytes())
        _write_zip_bytes(
            archive,
            "VERSION.json",
            (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

    wheel_prefix = name.replace("-", "_") + "-" + version + "-"
    wheels = sorted(
        path
        for path in output.glob("*.whl")
        if path.name.startswith(wheel_prefix)
    )
    if len(wheels) != 1:
        raise RuntimeError(
            f"expected exactly one wheel for {name} {version}, found {[p.name for p in wheels]}"
        )
    artifacts = [wheels[0], bundle]
    checksums = {path.name: _sha256(path) for path in artifacts}
    checksum_path = output / "SHA256SUMS.json"
    checksum_path.write_text(
        json.dumps(checksums, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"status": "ok", "version": version, "artifacts": checksums},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
