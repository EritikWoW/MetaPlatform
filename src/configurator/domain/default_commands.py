from __future__ import annotations

"""Default (typical) commands for metadata objects.

In MetaPlatform MVP, commands are stored as separate metadata objects under
the owner's system folder `commands/`.

Rationale:
    - deterministic config diffs (commands are explicit objects)
    - forms can reference commands by `code` (toolbar/buttons)
    - runtime can map actions to client behavior

Payload schema (command object):
    {
        "code": "Save",
        "title": {"uk": "Зберегти", "en": "Save"},
        "action": "save",
        "scope": "form"|"object",
        "system": true,
        "enabled": true,
        "hotkey": "Ctrl+S"   # optional
    }
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class CommandSpec:
    code: str
    title_uk: str
    title_en: str
    action: str
    scope: str = "form"  # 'form'|'object'
    system: bool = True
    enabled: bool = True
    hotkey: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "code": self.code,
            "title": {"uk": self.title_uk, "en": self.title_en},
            "action": self.action,
            "scope": self.scope,
            "system": bool(self.system),
            "enabled": bool(self.enabled),
        }
        if self.hotkey:
            out["hotkey"] = str(self.hotkey)
        return out


def _object_form_common() -> List[CommandSpec]:
    return [
        CommandSpec("Save",         "Зберегти",          "Save",       "save",        hotkey="Ctrl+S"),
        CommandSpec("SaveAndClose", "Зберегти і закрити","Save&Close", "saveandclose",hotkey="Ctrl+Enter"),
        CommandSpec("Copy",         "Копіювати",         "Copy",       "copy"),
        CommandSpec("Delete",       "Видалити",          "Delete",     "delete"),
        CommandSpec("Close",        "Закрити",           "Close",      "close",       hotkey="Esc"),
    ]


def _object_form_document() -> List[CommandSpec]:
    return [
        *_object_form_common(),
        CommandSpec("Post", "Провести", "Post", "post", hotkey="Ctrl+P"),
        CommandSpec(
            "Unpost",
            "Скасувати проведення",
            "Unpost",
            "unpost",
            hotkey="Ctrl+Shift+P",
        ),
    ]


def _list_form_common() -> List[CommandSpec]:
    return [
        CommandSpec("Create",  "Створити",    "Create",  "create",  scope="object", hotkey="Ins"),
        CommandSpec("Edit",    "Відкрити",    "Open",    "edit",    scope="object", hotkey="Enter"),
        CommandSpec("Copy",    "Копіювати",   "Copy",    "copy",    scope="object"),
        CommandSpec("Delete",  "Видалити",    "Delete",  "delete",  scope="object", hotkey="Del"),
        CommandSpec("Refresh", "Оновити",     "Refresh", "refresh", scope="form",   hotkey="F5"),
        CommandSpec("Close",   "Закрити",     "Close",   "close",   scope="form",   hotkey="Esc"),
    ]


def default_commands_for_context(*, obj_type: str, context: str) -> List[Dict[str, Any]]:
    """Return default commands for a specific UI context.

    context:
        - 'object_form'
        - 'list_form'
    """

    t = (obj_type or "").strip().lower()
    ctx = (context or "").strip().lower()

    specs: List[CommandSpec] = []
    if ctx == "list_form":
        specs = _list_form_common()
    elif ctx == "object_form":
        if t == "document":
            specs = _object_form_document()
        else:
            # Catalog, report, etc.
            specs = _object_form_common()
    else:
        specs = _object_form_common()

    return [s.to_dict() for s in specs]


def merge_commands(existing: Any, defaults: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge defaults into an existing commands list (by 'code')."""

    existing_list = existing if isinstance(existing, list) else []
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for item in existing_list:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code or code in seen:
            continue
        out.append(item)
        seen.add(code)

    for d in defaults:
        code = str(d.get("code") or "").strip()
        if code and code not in seen:
            out.append(d)
            seen.add(code)

    return out

def default_commands_for_object(*, obj_type: str, subtype: str | None = None) -> List[Dict[str, Any]]:
    t = (obj_type or "").strip().lower()
    if t not in ("catalog", "document", "register_accum", "register_info"):
        return []
    return default_commands_for_context(obj_type=t, context="object_form")
