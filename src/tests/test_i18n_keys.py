from __future__ import annotations

import ast
from pathlib import Path

from src.ui_qt.services.object_editor_profiles import EDITOR_PAGE_PROFILES


ROOT = Path(__file__).resolve().parents[2]
I18N_PATH = ROOT / "src" / "ui_qt" / "i18n.py"
CLIENT_UI_ROOTS = (
    ROOT / "src" / "client",
    ROOT / "src" / "ui_qt" / "widgets" / "admin_users_dialog.py",
)
VISIBLE_TEXT_CALLS = {
    "QAction",
    "QCheckBox",
    "QLabel",
    "QPushButton",
    "addAction",
    "addMenu",
    "critical",
    "getText",
    "information",
    "question",
    "setPlaceholderText",
    "setText",
    "setToolTip",
    "setWindowTitle",
    "warning",
}


def _collect_used_i18n_keys() -> set[str]:
    used: set[str] = set()
    src_root = ROOT / "src"
    for path in src_root.rglob("*.py"):
        if path.name in {"i18n.py", "i18n_extra.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "t":
                continue
            if not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                used.add(arg.value)
    return used


def _collect_configurator_context_i18n_keys() -> set[str]:
    used: set[str] = set()
    configurator_root = ROOT / "src" / "configurator"
    for path in configurator_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith("ctx_")
            ):
                used.add(node.value)
    return used


def _load_translations() -> dict[str, dict[str, str]]:
    ns: dict[str, object] = {}
    code = I18N_PATH.read_text(encoding="utf-8")
    exec(compile(code, str(I18N_PATH), "exec"), ns)
    return ns["_TR"]  # type: ignore[return-value]


def _collect_hardcoded_client_ui_text() -> list[str]:
    hits: list[str] = []
    for root in CLIENT_UI_ROOTS:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name):
                    call_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    call_name = node.func.attr
                else:
                    continue
                if call_name not in VISIBLE_TEXT_CALLS:
                    continue
                for arg in node.args[:3]:
                    literals: list[str] = []
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        literals.append(arg.value)
                    elif isinstance(arg, ast.JoinedStr):
                        literals.extend(
                            part.value
                            for part in arg.values
                            if isinstance(part, ast.Constant) and isinstance(part.value, str)
                        )
                    for literal in literals:
                        if any("\u0400" <= char <= "\u04ff" for char in literal):
                            rel = path.relative_to(ROOT)
                            hits.append(f"{rel}:{node.lineno}: {literal!r}")
    return hits


def test_all_used_i18n_keys_exist_for_supported_languages() -> None:
    used = _collect_used_i18n_keys()
    translations = _load_translations()
    for lang in ("en", "uk"):
        missing = sorted(key for key in used if key not in translations.get(lang, {}))
        assert not missing, f"{lang} missing keys: {missing}"


def test_object_editor_profile_titles_exist_for_supported_languages() -> None:
    used = {
        spec.title_i18n
        for profile in EDITOR_PAGE_PROFILES.values()
        for spec in profile
    }
    translations = _load_translations()
    for lang in ("en", "uk"):
        missing = sorted(key for key in used if key not in translations.get(lang, {}))
        assert not missing, f"{lang} missing profile title keys: {missing}"


def test_configurator_context_menu_keys_are_localized() -> None:
    used = _collect_configurator_context_i18n_keys()
    translations = _load_translations()
    for lang in ("en", "uk"):
        table = translations.get(lang, {})
        missing = sorted(key for key in used if key not in table)
        raw = sorted(key for key in used if table.get(key) == key)
        assert not missing, f"{lang} missing Configurator context menu keys: {missing}"
        assert not raw, f"{lang} exposes raw Configurator context menu keys: {raw}"


def test_client_visible_text_is_not_hardcoded_to_one_supported_language() -> None:
    hardcoded = _collect_hardcoded_client_ui_text()
    assert not hardcoded, "client UI text must use t(...):\n" + "\n".join(hardcoded)
