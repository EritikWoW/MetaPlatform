from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from src.infra.onec.backend import load_backend
from src.infra.onec.data_migration import _load_parse1cd_backend as load_data_backend
from src.infra.onec.physical_schema import _load_parse1cd_backend as load_schema_backend


def test_semantic_and_data_import_share_the_bundled_backend(monkeypatch, tmp_path):
    # A stale setting from the standalone program must not select another parser.
    monkeypatch.setenv("META_PARSE1CD_PARSER", str(tmp_path / "missing-external-parser"))
    data_backend = load_data_backend()
    schema_root, schema_backend = load_schema_backend()

    assert data_backend is load_backend()
    assert data_backend.database_parser is schema_backend
    assert schema_root == data_backend.parser_root
    assert schema_backend.__name__ == "src.infra.onec.parser.database_parser"
    assert schema_root == Path(__file__).resolve().parents[1] / "infra" / "onec" / "parser"


def test_backend_import_does_not_replace_unrelated_global_modules(tmp_path):
    # Run from an unrelated cwd in a fresh interpreter, with conflicting generic
    # module names: the old dynamic loader temporarily replaced these modules.
    script = """
import sys
from types import ModuleType
names = ('models', 'utils', 'database_parser', 'schema_reader', 'value_decoder', 'reference_resolver')
sentinels = {name: ModuleType(name) for name in names}
sys.modules.update(sentinels)
before = list(sys.path)
from concurrent.futures import ThreadPoolExecutor
from src.infra.onec.backend import load_backend
with ThreadPoolExecutor(max_workers=8) as pool:
    backends = list(pool.map(lambda _: load_backend(), range(32)))
assert all(backend.database_parser is backends[0].database_parser for backend in backends)
assert all(sys.modules[name] is module for name, module in sentinels.items())
assert sys.path == before
assert not any(name.startswith(('PySide6', 'PyQt6')) for name in sys.modules)
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    env["META_PARSE1CD_PARSER"] = str(tmp_path / "missing-external-parser")
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
