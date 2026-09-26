from __future__ import annotations

"""Form model (MVP).

The long-term goal is to provide a stable, versioned JSON schema that:
  - is easy to store in MetaPlatform configuration metadata
  - supports deterministic diffs in configuration storage
  - can be rendered by the runtime client
  - can be edited visually in Configurator

This MVP intentionally keeps the schema compact.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


SchemaVersion = Literal[1]


ControlType = Literal[
    "Container",
    "Tabs",
    "Label",
    "Picture",
    "TextBox",
    "TextArea",
    "NumberBox",
    "CheckBox",
    "ComboBox",
    "DateBox",
    "Button",
    "Table",
    "CommandBar",
    "TablePanel",
    "StatusBar",
    "Separator",
]


ContainerLayout = Literal["absolute", "vertical", "horizontal", "grid"]


_FORM_OPEN_MODE_ALIASES = {
    "": "auto",
    "auto": "auto",
    "automatic": "auto",
    "workspace": "workspace",
    "clientworkspace": "workspace",
    "workarea": "workspace",
    "main": "workspace",
    "tab": "workspace",
    "embedded": "workspace",
    "window": "window",
    "separate": "window",
    "separatewindow": "window",
    "dialog": "window",
}
_FORM_WINDOW_LOCK_ALIASES = {
    "": "none",
    "none": "none",
    "dontuse": "none",
    "independent": "none",
    "owner": "owner",
    "lockownerwindow": "owner",
    "window": "owner",
    "interface": "interface",
    "lockwholeinterface": "interface",
    "application": "interface",
}


def normalize_form_open_mode(value: Any) -> str:
    """Return the stable form placement mode used by IDE and client."""

    key = str(value or "").strip().replace("_", "").replace("-", "").casefold()
    return _FORM_OPEN_MODE_ALIASES.get(key, "auto")


def normalize_form_window_lock_mode(value: Any) -> str:
    """Normalize MetaPlatform and 1C WindowOpeningMode values."""

    key = str(value or "").strip().replace("_", "").replace("-", "").casefold()
    return _FORM_WINDOW_LOCK_ALIASES.get(key, "none")


_FORM_NODE_VISIBILITY_KEYS = (
    "visible",
    "is_visible",
    "user_visible",
    "visibility",
)
_FORM_BOOL_TRUE = {"1", "true", "yes", "y", "on", "так", "да", "істина", "истина"}
_FORM_BOOL_FALSE = {"0", "false", "no", "n", "off", "ні", "нет", "ложь", "хибність"}


def coerce_form_bool(value: Any, *, default: bool = False) -> bool:
    """Convert persisted/imported form booleans without Python string truthiness."""

    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().casefold()
    if text in _FORM_BOOL_TRUE:
        return True
    if text in _FORM_BOOL_FALSE:
        return False
    return bool(default)


def form_node_is_visible(node_or_props: Any) -> bool:
    """Return client visibility for a FormNode or a raw props mapping."""

    if isinstance(node_or_props, FormNode):
        props = node_or_props.props
    elif isinstance(node_or_props, dict):
        props = node_or_props
    else:
        props = getattr(node_or_props, "props", {})
    if not isinstance(props, dict):
        return True
    for key in _FORM_NODE_VISIBILITY_KEYS:
        if key in props:
            return coerce_form_bool(props.get(key), default=True)
    return True


def _normalize_form_node_visibility(props: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(props or {})
    for key in _FORM_NODE_VISIBILITY_KEYS:
        if key not in normalized:
            continue
        normalized["visible"] = coerce_form_bool(normalized.get(key), default=True)
        for alias in _FORM_NODE_VISIBILITY_KEYS[1:]:
            normalized.pop(alias, None)
        break
    return normalized


@dataclass(slots=True)
class FormNode:
    """A single node in the form tree."""

    id: str
    type: ControlType
    name: str = ""
    title: str = ""
    binding: str = ""
    props: Dict[str, Any] = field(default_factory=dict)
    children: List["FormNode"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        props = dict(self.props or {})
        if self.type == "CommandBar" and self.children:
            buttons = _command_button_defs(self.children, existing=props.get("buttons"))
            if buttons:
                props["buttons"] = buttons
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "title": self.title,
            "binding": self.binding,
            "props": props,
            "children": [c.to_dict() for c in self.children],
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "FormNode":
        """Deserialize from a dict.

        Raises:
            ValueError: if required fields are missing.
        """

        if not isinstance(data, dict):
            raise ValueError("FormNode must be a dict")
        node_id = str(data.get("id") or "").strip()
        node_type = str(data.get("type") or "").strip()
        if not node_id or not node_type:
            raise ValueError("FormNode requires 'id' and 'type'")
        props = data.get("props") if isinstance(data.get("props"), dict) else {}
        props = _normalize_form_node_visibility(props)
        # Normalize container layout values for backward compatibility.
        # Older/experimental versions may store values like "Absolute" or with extra spaces.
        if str(data.get("type") or "").strip() == "Container" and isinstance(props, dict):
            raw_layout = props.get("layout")
            layout = str(raw_layout or "vertical").strip().lower()
            if layout in ("abs", "absolute", "free", "canvas"):
                layout = "absolute"
            elif layout in ("v", "vert", "vertical"):
                layout = "vertical"
            elif layout in ("h", "hor", "horiz", "horizontal"):
                layout = "horizontal"
            elif layout in ("grid", "table", "matrix"):
                layout = "grid"
            else:
                layout = "vertical"
            props = dict(props)
            props["layout"] = layout
        children_raw = data.get("children") if isinstance(data.get("children"), list) else []
        node = FormNode(
            id=node_id,
            type=node_type,  # type: ignore[assignment]
            name=str(data.get("name") or ""),
            title=str(data.get("title") or ""),
            binding=str(data.get("binding") or ""),
            props=dict(props),
            children=[],
        )
        for ch in children_raw:
            if isinstance(ch, dict):
                node.children.append(FormNode.from_dict(ch))
        return node


def _looks_like_legacy_tabs_container(node: FormNode) -> bool:
    """Detect older imported page groups that were stored as plain containers."""

    if str(node.type or "").strip() != "Container":
        return False
    if not node.children:
        return False

    title = str(node.title or "").strip().lower()
    name = str(node.name or "").strip().lower()
    has_pages_marker = (
        "сторін" in title
        or "страниц" in title
        or "pages" in title
        or "stranyts" in name
        or "stranic" in name
        or name in {"tabs", "pages"}
    )
    if not has_pages_marker:
        return False

    for child in node.children:
        if not isinstance(child, FormNode):
            return False
        if str(child.type or "").strip() != "Container":
            return False
        if not str(child.title or child.name or "").strip():
            return False
    return True


def _looks_like_legacy_command_bar(node: FormNode) -> bool:
    """Detect older imported command bars stored as plain horizontal containers."""

    if str(node.type or "").strip() != "Container":
        return False
    props = node.props if isinstance(node.props, dict) else {}
    if str(props.get("layout") or "").strip().lower() != "horizontal":
        return False
    if not node.children:
        return False
    if not all(isinstance(child, FormNode) and str(child.type or "").strip() == "Button" for child in node.children):
        return False

    title = str(node.title or "").strip().lower()
    name = str(node.name or "").strip().lower()
    markers = ("команд", "command", "toolbar", "panel", "бар")
    return any(marker in title for marker in markers) or any(marker in name for marker in markers)


def _command_button_defs(
    children: List[FormNode],
    *,
    existing: Any = None,
) -> list[dict[str, Any]]:
    """Serialize editable Button children to the flat runtime command format."""

    buttons: list[dict[str, Any]] = []
    for child in children:
        if not isinstance(child, FormNode) or str(child.type or "").strip() != "Button":
            continue
        child_props = child.props if isinstance(child.props, dict) else {}
        button = {
            "name": str(child.name or "").strip(),
            "designer_name": str(child_props.get("designer_name") or child.name or "").strip(),
            "title": str(child.title or child.name or "").strip(),
            "command": str(child_props.get("command") or child.name or "").strip(),
            "role": str(child_props.get("role") or child_props.get("variant") or "").strip(),
            "icon": str(child_props.get("icon") or "").strip(),
            "separator_after": bool(child_props.get("separator_after")),
        }
        if not form_node_is_visible(child):
            button["visible"] = False
        buttons.append(button)

    # Preserve legacy pure separators by attaching them to the preceding
    # editable button. This keeps their visual position without storing two
    # incompatible button schemas.
    if isinstance(existing, list) and buttons:
        non_separator_index = 0
        for item in existing:
            if not isinstance(item, dict):
                continue
            has_command = bool(str(item.get("title") or item.get("command") or "").strip())
            if has_command:
                non_separator_index += 1
                continue
            if item.get("separator_after"):
                target = max(0, min(non_separator_index - 1, len(buttons) - 1))
                buttons[target]["separator_after"] = True
    return buttons


def _legacy_button_defs(node: FormNode) -> list[dict[str, Any]]:
    props = node.props if isinstance(node.props, dict) else {}
    existing = props.get("buttons")
    if isinstance(existing, list) and existing:
        return [dict(item) for item in existing if isinstance(item, dict)]

    defs: list[dict[str, Any]] = []
    for child in node.children:
        if not isinstance(child, FormNode) or str(child.type or "").strip() != "Button":
            continue
        props = child.props if isinstance(child.props, dict) else {}
        defs.append(
            {
                "name": str(child.name or "").strip(),
                "designer_name": str(props.get("designer_name") or child.name or "").strip(),
                "title": str(child.title or child.name or "").strip(),
                "command": str(props.get("command") or child.name or "").strip(),
                "role": str(props.get("role") or "").strip(),
                "icon": str(props.get("icon") or "").strip(),
                "separator_after": bool(props.get("separator_after")),
            }
        )
    return defs


def _looks_like_legacy_table_panel(node: FormNode) -> bool:
    """Detect a table with a legacy toolbar wrapper stored as a vertical container."""

    if str(node.type or "").strip() != "Container":
        return False
    props = node.props if isinstance(node.props, dict) else {}
    if str(props.get("layout") or "").strip().lower() != "vertical":
        return False
    if len(node.children) != 2:
        return False

    first, second = node.children
    if not isinstance(first, FormNode) or not isinstance(second, FormNode):
        return False
    if str(second.type or "").strip() != "Table":
        return False
    first_type = str(first.type or "").strip()
    if first_type != "CommandBar" and not _looks_like_legacy_command_bar(first):
        return False

    wrapper_names = {
        str(node.name or "").strip().casefold(),
        str(node.title or "").strip().casefold(),
    }
    table_names = {
        str(second.name or "").strip().casefold(),
        str(second.title or "").strip().casefold(),
        str(second.binding or "").strip().casefold(),
    }
    wrapper_names.discard("")
    table_names.discard("")
    return bool(wrapper_names.intersection(table_names))


def _normalize_legacy_command_bar(node: FormNode) -> FormNode:
    props = dict(node.props or {})
    props["buttons"] = _legacy_button_defs(node)
    props.setdefault("show_all_actions", True)
    node.type = "CommandBar"  # type: ignore[assignment]
    node.props = props
    node.children = []
    return node


def _normalize_legacy_table_panel(node: FormNode) -> FormNode:
    toolbar_node, table_node = node.children
    table_props = dict(table_node.props or {})
    button_defs = _legacy_button_defs(toolbar_node) if isinstance(toolbar_node, FormNode) else []

    fill_by_stock = ""
    fill_by_stock_command = ""
    fill_by_stock_designer_name = ""
    extra_commands: list[dict[str, Any]] = []
    for bdef in button_defs:
        title = str(bdef.get("title") or "").strip()
        low = title.lower()
        if not fill_by_stock and any(marker in low for marker in ("запов", "залишк", "підібр", "подбор", "остатк")):
            fill_by_stock = title
            fill_by_stock_command = str(bdef.get("command") or bdef.get("name") or "").strip()
            fill_by_stock_designer_name = str(
                bdef.get("designer_name") or bdef.get("name") or fill_by_stock_command
            ).strip()
            continue
        extra_commands.append(bdef)

    merged_props = dict(table_props)
    merged_props.setdefault("can_add", False)
    merged_props.setdefault("can_delete", False)
    merged_props.setdefault("can_move_up", False)
    merged_props.setdefault("can_move_down", False)
    if fill_by_stock:
        merged_props["fill_by_stock"] = fill_by_stock
        if fill_by_stock_command:
            merged_props["fill_by_stock_command"] = fill_by_stock_command
        if fill_by_stock_designer_name:
            merged_props["fill_by_stock_designer_name"] = fill_by_stock_designer_name
    if isinstance(toolbar_node, FormNode):
        toolbar_props = toolbar_node.props if isinstance(toolbar_node.props, dict) else {}
        command_bar_name = str(
            toolbar_props.get("designer_name") or toolbar_node.name or ""
        ).strip()
        if command_bar_name:
            merged_props["command_bar_designer_name"] = command_bar_name
    if extra_commands:
        merged_props["extra_commands"] = extra_commands

    node.type = "TablePanel"  # type: ignore[assignment]
    node.binding = str(table_node.binding or node.binding or node.name or "").strip()
    node.props = merged_props
    node.children = []
    return node


def _wrap_leading_buttons_as_command_bar(node: FormNode) -> FormNode:
    """Convert legacy leading Button children into a CommandBar node.

    Older/generated forms stored command buttons directly under a vertical
    container, which made the runtime render them as a vertical stack.
    This helper preserves the original structure by extracting the leading
    button prefix into a dedicated CommandBar child.
    """

    if str(node.type or "").strip() != "Container":
        return node
    props = node.props if isinstance(node.props, dict) else {}
    if str(props.get("layout") or "").strip().lower() != "vertical":
        return node
    if not node.children:
        return node

    button_prefix: list[FormNode] = []
    rest: list[FormNode] = []
    seen_non_button = False
    for child in node.children:
        if not seen_non_button and isinstance(child, FormNode) and str(child.type or "").strip() == "Button":
            button_prefix.append(child)
            continue
        seen_non_button = True
        rest.append(child)

    if not button_prefix:
        return node

    # A single standalone button is a valid form control. Multiple buttons or
    # a leading button prefix above a body are a command strip.
    if not rest and len(button_prefix) == 1:
        return node

    command_bar = FormNode(
        id=f"{node.id}_cmdbar",
        type="CommandBar",
        name="command_bar",
        title="",
        props={
            "buttons": [ch.to_dict() for ch in button_prefix],
            "show_all_actions": True,
        },
        children=[FormNode.from_dict(ch.to_dict()) for ch in button_prefix],
    )
    node.children = [command_bar, *rest]
    return node


def _normalize_legacy_form_tree(node: FormNode, *, inside_tabs: bool = False) -> FormNode:
    """Upgrade older imported form trees to the current model contract."""

    if _looks_like_legacy_tabs_container(node):
        node.type = "Tabs"  # type: ignore[assignment]
        props = dict(node.props or {})
        props.pop("layout", None)
        props.setdefault("pages_representation", "TabsOnTop")
        node.props = props

    next_inside_tabs = inside_tabs or str(node.type or "").strip() == "Tabs"
    node.children = [_normalize_legacy_form_tree(ch, inside_tabs=next_inside_tabs) for ch in node.children]

    if _looks_like_legacy_command_bar(node):
        node = _normalize_legacy_command_bar(node)

    if _looks_like_legacy_table_panel(node):
        node = _normalize_legacy_table_panel(node)

    node = _wrap_leading_buttons_as_command_bar(node)

    # Older object-form imports stored tabular section tables inside pages with
    # a generic binding="items". Runtime should bind such tables to the actual
    # tabular section name taken from the node itself.
    if next_inside_tabs and str(node.type or "").strip() == "Table":
        binding = str(node.binding or "").strip().lower()
        fallback_name = str(node.name or "").strip()
        if binding in {"", "items", "list"} and fallback_name and fallback_name.lower() not in {"list"}:
            node.binding = fallback_name

    return node


@dataclass(slots=True)
class FormModel:
    """Root form model."""

    schema_version: SchemaVersion = 1
    id: str = ""
    name: str = ""
    title: str = ""
    root: FormNode = field(
        default_factory=lambda: FormNode(id="root", type="Container", props={"layout": "vertical"})
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""

        return {
            "schema_version": int(self.schema_version),
            "id": self.id,
            "name": self.name,
            "title": self.title,
            "root": self.root.to_dict(),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "FormModel":
        """Deserialize from dict."""

        if not isinstance(data, dict):
            raise ValueError("FormModel must be a dict")
        ver = int(data.get("schema_version") or 0)
        if ver != 1:
            raise ValueError(f"Unsupported form schema_version: {ver}")
        root_raw = data.get("root") if isinstance(data.get("root"), dict) else {}
        root = FormNode.from_dict(root_raw) if root_raw else FormNode(id="root", type="Container", props={"layout": "vertical"})
        root = _normalize_legacy_form_tree(root)
        return FormModel(
            schema_version=1,
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            title=str(data.get("title") or ""),
            root=root,
        )


def default_form_model(*, form_name: str) -> FormModel:
    """Create a default form model for a new form."""

    fm = FormModel(id=form_name, name=form_name, title=form_name)
    # Default: absolute canvas root (graphical designer-friendly).
    fm.root = FormNode(
        id="root",
        type="Container",
        props={
            "layout": "absolute",
            "w": 1000,
            "h": 700,
        },
    )

    # Start empty: controls are generated from owner requisites or added interactively.
    return fm
