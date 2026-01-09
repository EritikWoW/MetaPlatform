# MetaPlatform/platform/i18n.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
import weakref

from src.platform.paths import get_user_config_dir


# ----------------- supported langs -----------------
SUPPORTED = ("uk", "en")

_LANG_TO_DISPLAY = {
    "uk": "UA",
    "en": "EN",
}
DISPLAY_TO_LANG = {v: k for k, v in _LANG_TO_DISPLAY.items()}


def all_lang_displays() -> list[str]:
    return [_LANG_TO_DISPLAY["uk"], _LANG_TO_DISPLAY["en"]]


def lang_display(code: str) -> str:
    return _LANG_TO_DISPLAY.get(code, _LANG_TO_DISPLAY["en"])


# ----------------- storage -----------------
_SETTINGS_PATH = get_user_config_dir() / "settings.json"

def display_to_lang(display: str) -> str:
    return DISPLAY_TO_LANG.get(display, "en")


def lang_to_display(code: str) -> str:
    return lang_display(code)

def _load_settings() -> dict[str, Any]:
    try:
        if _SETTINGS_PATH.exists():
            return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_settings(data: dict[str, Any]) -> None:
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ----------------- translations -----------------
_TR: dict[str, dict[str, str]] = {
    "en": {
        "launcher_title": "MetaPlatform",
        "launcher_subtitle": "Database selector",
        "ph_search": "Search",

        "list_label": "Connected databases:",
        "lbl_status": "Status:",
        "lbl_language": "Language:",

        "col_name": "Database",
        "col_path": "Path",
        "col_status": "Status",

        "btn_client": "Client",
        "btn_config": "Configurator",
        "btn_add": "Add DB",
        "btn_remove": "Remove DB",
        "btn_open_folder": "Open folder",

        "status_ready": "Ready",
        "status_ok": "OK",
        "status_no_file": "Missing",
        "status_file_found": "File found",
        "status_file_missing": "File NOT found",

        "count_line": "Databases: {total} (shown: {shown})",

        "dlg_add_title": "Add database",
        "dlg_add_question": "Connect an existing DB?\n\nYes — pick an existing file\nNo — create a new DB file",
        "dlg_pick_db": "Select database file",
        "dlg_create_db": "Create database file",

        "dlg_db_name_title": "Database name",
        "dlg_db_name_prompt": "Enter a name for the list:",

        "status_added": "Added DB: {name}",
        "status_removed": "Removed from list: {name}",

        "dlg_remove_title": "Remove",
        "dlg_remove_pick": "Select a DB in the list.",
        "dlg_remove_confirm_title": "Remove from list",
        "dlg_remove_confirm_text": "Remove '{name}' from the list?\n\nThe file on disk will NOT be deleted.",

        "dlg_open_title": "Open",
        "dlg_open_pick": "Select a DB in the list.",
        "dlg_open_missing": "DB file not found on disk.",

        "dlg_client_title": "Client",
        "dlg_config_title": "Configurator",
        "dlg_pick_db_first": "Select a DB in the list.",
        "dlg_bad_db_file": "DB file not found. Please select a valid file.",
    },
    "uk": {
        "launcher_title": "MetaPlatform",
        "launcher_subtitle": "Вибір бази даних",
        "ph_search": "Пошук",

        "list_label": "Підключені бази:",
        "lbl_status": "Статус:",
        "lbl_language": "Мова:",

        "col_name": "База",
        "col_path": "Шлях",
        "col_status": "Статус",

        "btn_client": "Клієнт",
        "btn_config": "Конфігуратор",
        "btn_add": "Додати БД",
        "btn_remove": "Видалити БД",
        "btn_open_folder": "Відкрити папку",

        "status_ready": "Готово",
        "status_ok": "OK",
        "status_no_file": "Немає файла",
        "status_file_found": "Файл знайдено",
        "status_file_missing": "Файл НЕ знайдено",

        "count_line": "Баз у списку: {total} (показано: {shown})",

        "dlg_add_title": "Додати БД",
        "dlg_add_question": "Підключити існуючу БД?\n\nТак — обрати існуючий файл\nНі — створити новий файл БД",
        "dlg_pick_db": "Оберіть файл бази даних",
        "dlg_create_db": "Створити файл бази даних",

        "dlg_db_name_title": "Назва БД",
        "dlg_db_name_prompt": "Введіть назву для списку:",

        "status_added": "Додано БД: {name}",
        "status_removed": "Видалено зі списку: {name}",

        "dlg_remove_title": "Видалити",
        "dlg_remove_pick": "Оберіть БД у списку.",
        "dlg_remove_confirm_title": "Видалити зі списку",
        "dlg_remove_confirm_text": "Видалити '{name}' зі списку?\n\nФайл на диску НЕ буде видалено.",

        "dlg_open_title": "Відкрити",
        "dlg_open_pick": "Оберіть БД у списку.",
        "dlg_open_missing": "Файл бази не знайдено на диску.",

        "dlg_client_title": "Клієнт",
        "dlg_config_title": "Конфігуратор",
        "dlg_pick_db_first": "Оберіть БД у списку.",
        "dlg_bad_db_file": "Файл бази не знайдено. Оберіть коректний файл.",
    },
}


# ----------------- runtime state -----------------
_lang: str = "en"
_inited = False

# observers: entries with optional widget weakref (auto-remove on destroy)
_observers: list[dict[str, Any]] = []


def init_i18n(default_lang: str = "en") -> None:
    """Load language once for the whole program (from settings.json)."""
    global _inited, _lang
    if _inited:
        return
    data = _load_settings()
    lang = str(data.get("lang") or default_lang)
    if lang not in SUPPORTED:
        lang = "en"
    _lang = lang
    _inited = True


def get_lang() -> str:
    return _lang


def set_lang(lang: str) -> None:
    global _lang
    if lang not in SUPPORTED:
        lang = "en"
    if _lang == lang:
        return
    _lang = lang

    # persist
    data = _load_settings()
    data["lang"] = _lang
    _save_settings(data)

    # notify
    _notify()


def t(key: str, **kwargs: Any) -> str:
    table = _TR.get(_lang) or _TR["en"]
    s = table.get(key) or _TR["en"].get(key) or key
    if kwargs:
        try:
            return s.format(**kwargs)
        except Exception:
            return s
    return s


def bind(callback: Callable[[], None], widget=None) -> None:
    """
    Bind callback to language changes.
    If widget is provided, callback auto-unbinds when widget is destroyed.
    """
    entry: dict[str, Any] = {"cb": callback, "wref": None}
    if widget is not None:
        entry["wref"] = weakref.ref(widget)

        def _on_destroy(_e=None):
            try:
                _observers.remove(entry)
            except ValueError:
                pass

        try:
            widget.bind("<Destroy>", _on_destroy, add="+")
        except Exception:
            pass

    _observers.append(entry)


def _notify() -> None:
    dead: list[dict[str, Any]] = []
    for entry in list(_observers):
        wref = entry.get("wref")
        if wref is not None and wref() is None:
            dead.append(entry)
            continue
        cb = entry.get("cb")
        try:
            cb()
        except Exception:
            # не ломаем программу из-за одного слушателя
            pass

    for d in dead:
        try:
            _observers.remove(d)
        except ValueError:
            pass
