import importlib.util
import os
import sys
from pathlib import Path

import pytest


# Ensure the project "src" directory is importable in tests.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_PYSIDE6_IMPORT_MARKERS = (
    "from PySide6",
    "import PySide6",
    "from src.ui_qt",
    "import src.ui_qt",
    "from src.client.forms.form_runtime_widget",
    "from src.client.forms.form_runtime",
    "from src.client.client_window",
    "from src.client.client_main_window",
    "from src.configurator.configurator_window",
    "from src.configurator.configurator_main_window",
)


def _has_pyside6() -> bool:
    if os.environ.get("MP_TEST_FORCE_NO_PYSIDE6") == "1":
        return False
    return importlib.util.find_spec("PySide6") is not None


def _test_file_requires_pyside6(path: Path) -> bool:
    if path.suffix != ".py" or path.name == "conftest.py":
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return any(marker in text for marker in _PYSIDE6_IMPORT_MARKERS)


HAS_PYSIDE6 = _has_pyside6()


if HAS_PYSIDE6:
    # CI often runs without a windowing system; force the headless backend
    # unless the caller explicitly selected another platform plugin.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_ignore_collect(collection_path, config) -> bool:
    if HAS_PYSIDE6:
        return False
    path = Path(str(collection_path))
    if "src" not in path.parts or "tests" not in path.parts:
        return False
    return _test_file_requires_pyside6(path)


@pytest.fixture(autouse=True)
def _isolate_i18n_settings_path(tmp_path, monkeypatch):
    """Prevent tests from mutating the user's real %APPDATA% settings.json."""
    import src.ui_qt.i18n as i18n_mod

    monkeypatch.setattr(i18n_mod, "_SETTINGS_PATH", tmp_path / "settings.json", raising=False)
    yield
