"""Form templates for auto-generated forms.

Generates FormModel compatible with FormRuntimeBuildMixin.
Uses vertical/grid layouts (NOT absolute) so forms are responsive.

List form:   CommandBar  → Table (items)
Object form: CommandBar  → scrollable grid of fields
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .form_model import FormModel, FormNode


# ── Field normalisation ────────────────────────────────────────────────────────

_FIELD_BINDING_ALIASES = {
    "code": "_code",
    "description": "_description",
    "deletionmark": "_deleted",
    "deletion_mark": "_deleted",
    "deleted": "_deleted",
    "predefined": "_predefined",
    "number": "_number",
    "numberprefix": "_number_prefix",
    "number_prefix": "_number_prefix",
    "date": "_date",
    "datetime": "_date",
    "posted": "_posted",
    "comment": "comment",
    "period": "_period",
    "recorder": "_recorder",
    "lineno": "_line_no",
    "line_no": "_line_no",
    "owner": "_owner_guid",
    "active": "_active",
    "recordkind": "_record_kind",
    "record_kind": "_record_kind",
    "kind": "_kind",
}

_BOOL_BINDINGS = {"_deleted", "_predefined", "_posted", "_is_folder", "_active"}
_DATE_BINDINGS = {"_date", "_period"}
_NUM_BINDINGS  = {"_number", "_line_no"}
_HIDDEN        = {"_guid", "_owner_guid", "_recorder"}


def _field_title(field: Dict[str, Any]) -> str:
    """Extract localized title respecting current app locale."""
    from src.ui_qt.i18n import get_lang
    lang = get_lang()
    title = field.get("title")
    if isinstance(title, dict):
        for l in (lang, "uk", "en", "ru"):
            v = str(title.get(l) or "").strip()
            if v:
                return v
        for v in title.values():
            s = str(v or "").strip()
            if s:
                return s
        return ""
    return str(title or "").strip()


def _field_name(field: Dict[str, Any]) -> str:
    return str(
        field.get("name") or field.get("code") or field.get("binding") or ""
    ).strip()


def _field_binding(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    key = re.sub(r"[^a-z0-9_]+", "", raw.casefold())
    if key in _FIELD_BINDING_ALIASES:
        return _FIELD_BINDING_ALIASES[key]
    return raw if raw.startswith("_") else key


def _field_binding_for(field: Dict[str, Any], name: str) -> str:
    explicit = str(field.get("binding") or "").strip()
    if explicit:
        return explicit
    return _field_binding(name)


def _norm_fields(fields: Any) -> List[Dict[str, Any]]:
    if not isinstance(fields, list):
        return []
    out: List[Dict[str, Any]] = []
    for x in fields:
        if not isinstance(x, dict):
            continue
        name = _field_name(x)
        if not name:
            continue
        binding = _field_binding_for(x, name)
        if binding in _HIDDEN:
            continue
        out.append({
            "name":     name,
            "binding":  binding,
            "title":    _field_title(x) or (name[:1].upper() + name[1:]),
            "type":     str(x.get("type") or "string").strip() or "string",
            "required": bool(x.get("required") or False),
        })
    return out


def _widget_type(attr: Dict[str, Any]) -> str:
    binding = str(attr.get("binding") or "")
    typ     = str(attr.get("type") or "string").lower()
    if binding in _BOOL_BINDINGS or typ == "boolean":
        return "CheckBox"
    if binding in _DATE_BINDINGS or typ in ("date", "datetime"):
        return "DateBox"
    if binding in _NUM_BINDINGS or typ in ("number", "integer", "decimal", "float"):
        return "NumberBox"
    return "TextBox"


def _localized_command_title(command: Dict[str, Any]) -> str:
    from src.ui_qt.i18n import get_lang

    raw = command.get("title")
    if isinstance(raw, dict):
        lang = get_lang()
        for key in (lang, "uk", "en", "ru"):
            value = str(raw.get(key) or "").strip()
            if value:
                return value
        for value in raw.values():
            text = str(value or "").strip()
            if text:
                return text
    text = str(raw or "").strip()
    if text:
        return text
    return str(command.get("code") or command.get("command") or command.get("action") or "").strip()


def _command_code(command: Dict[str, Any]) -> str:
    return str(command.get("command") or command.get("code") or command.get("action") or "").strip()


def _button_nodes(commands: Any) -> List[FormNode]:
    cmd_list = commands if isinstance(commands, list) else []
    out: List[FormNode] = []
    for i, c in enumerate(cmd_list, start=1):
        if not isinstance(c, dict):
            continue
        code = _command_code(c)
        title = _localized_command_title(c)
        if not code and not title:
            continue
        role = str(c.get("role") or ("primary" if i == 1 else "")).strip()
        icon = str(c.get("icon") or "").strip()
        out.append(
            FormNode(
                id=f"cmd_{i}",
                type="Button",
                name=code or f"Command{i}",
                title=title or code,
                props={
                    "command": code,
                    "role": role,
                    "icon": icon,
                },
            )
        )
    return out


def _command_bar_node(commands: Any) -> FormNode | None:
    buttons = _button_nodes(commands)
    if not buttons:
        return None
    return FormNode(
        id="cmdbar",
        type="CommandBar",
        name="command_bar",
        props={
            "buttons": [btn.to_dict() for btn in buttons],
            "show_all_actions": True,
        },
        children=[FormNode.from_dict(btn.to_dict()) for btn in buttons],
    )


# ── List form ──────────────────────────────────────────────────────────────────

def build_list_form_model(
    *,
    form_name: str,
    owner_title: str,
    attributes: Any,
    commands: Any = None,
) -> Dict[str, Any]:
    """Generate a list form: CommandBar + Table(items)."""
    attrs = _norm_fields(attributes)

    # Columns for the table: keep business-visible booleans like Posted, but
    # hide technical flags that should not clutter list forms.
    cols: List[Dict[str, Any]] = []
    for a in attrs:
        if a["binding"] in {"_deleted", "_predefined"}:
            continue
        cols.append({"name": a["name"], "title": a["title"], "binding": a["binding"]})
        if len(cols) >= 6:
            break

    # Default list commands
    cmd_list = commands if isinstance(commands, list) else []
    if not cmd_list:
        from src.ui_qt.i18n import t as _t
        cmd_list = [
            {"title": _t("ctx_create"),   "command": "Create",  "role": "primary", "icon": "add"},
            {"title": _t("ctx_open"),      "command": "Edit",    "role": "",        "icon": "edit"},
            {"title": _t("ctx_delete"),    "command": "Delete",  "role": "",        "icon": "delete"},
            {"title": _t("act_refresh"),   "command": "Refresh", "role": "",        "icon": "refresh"},
        ]

    command_bar = _command_bar_node(cmd_list)

    fm = FormModel(id=form_name, name=form_name, title=owner_title)
    fm.root = FormNode(
        id="root",
        type="Container",
        props={"layout": "vertical"},
        children=[
            # ── main table ───────────────────────────────────────────
            *( [command_bar] if command_bar is not None else [] ),
            FormNode(
                id="tbl",
                type="Table",
                name="table",
                binding="items",
                props={"columns": cols},
            ),
        ],
    )
    return fm.to_dict()


# ── Object form ────────────────────────────────────────────────────────────────

def build_object_form_model(
    *,
    form_name: str,
    owner_title: str,
    attributes: Any,
    commands: Any = None,
) -> Dict[str, Any]:
    """Generate an object form: CommandBar + vertical grid of fields."""
    attrs = _norm_fields(attributes)

    # Default object commands
    cmd_list = commands if isinstance(commands, list) else []
    if not cmd_list:
        from src.ui_qt.i18n import t as _t
        cmd_list = [
            {"title": _t("btn_save") + " & " + _t("act_close"), "command": "SaveAndClose",
             "role": "primary", "icon": "save"},
            {"title": _t("btn_save"),  "command": "Save",  "role": "", "icon": ""},
            {"title": _t("act_close"), "command": "Close", "role": "", "icon": "close"},
        ]

    command_bar = _command_bar_node(cmd_list)

    # Build field nodes
    field_nodes: List[FormNode] = []
    for idx, a in enumerate(attrs, start=1):
        wtype = _widget_type(a)
        if wtype == "CheckBox":
            field_nodes.append(FormNode(
                id=f"f_{idx}",
                type="CheckBox",
                name=a["name"],
                binding=a["binding"],
                title=a["title"],
                props={},
            ))
        else:
            field_nodes.append(FormNode(
                id=f"f_{idx}",
                type=wtype,
                name=a["name"],
                binding=a["binding"],
                title=a["title"],
                props={"title_location": "left"},
            ))

    fm = FormModel(id=form_name, name=form_name, title=owner_title)
    fm.root = FormNode(
        id="root",
        type="Container",
        props={"layout": "vertical"},
        children=[
            *( [command_bar] if command_bar is not None else [] ),
            *field_nodes,
        ],
    )
    return fm.to_dict()
