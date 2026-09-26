from __future__ import annotations

import json
import uuid
from functools import partial
from typing import Any, Optional

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMenu, QTreeWidgetItem

from src.configurator.domain.form_model import FormNode, form_node_is_visible
from src.ui_qt.i18n import t


FORM_NODE_CLIPBOARD_MIME = "application/x-metaplatform-form-node-tree"


class FormDesignerInteractionMixin:
    def _can_reparent_tree_node(self, source_id: str, parent_id: str) -> bool:
        source = self._node_by_id.get(str(source_id or "").strip())
        parent = self._node_by_id.get(str(parent_id or "").strip())
        if source is None or parent is None or source is self._model.root:
            return False
        if source.id == parent.id:
            return False
        ancestor = parent
        depth = 0
        while ancestor is not None and depth < 64:
            if ancestor.id == source.id:
                return False
            ancestor = self._parent_node(ancestor.id)
            depth += 1
        parent_type = str(parent.type or "").strip()
        source_type = str(source.type or "").strip()
        if parent_type == "Container":
            return True
        if parent_type == "Tabs":
            return source_type == "Container"
        if parent_type == "CommandBar":
            return source_type == "Button"
        return False

    def _populate_toolbox(self) -> None:
        try:
            self.toolbox.clear()
        except Exception:
            return

        controls: list[tuple[str, str]] = [
            ("Label", "form_ctl_label"),
            ("Picture", "form_ctl_picture"),
            ("TextBox", "form_ctl_textbox"),
            ("TextArea", "form_ctl_textarea"),
            ("NumberBox", "form_ctl_numberbox"),
            ("DateBox", "form_ctl_datebox"),
            ("ComboBox", "form_ctl_combobox"),
            ("CheckBox", "form_ctl_checkbox"),
            ("Button", "form_ctl_button"),
            ("Table", "form_ctl_table"),
            ("Container", "form_ctl_container"),
            ("Tabs", "form_ctl_tabs"),
            ("CommandBar", "form_ctl_command_bar"),
            ("TablePanel", "form_ctl_table_panel"),
            ("StatusBar", "form_ctl_status_bar"),
        ]

        for control_type, key in controls:
            caption = t(key) if key else control_type
            it = QListWidgetItem(str(caption))
            it.setData(Qt.ItemDataRole.UserRole, control_type)
            self.toolbox.addItem(it)

    def _node_tree_name(self, node: FormNode) -> str:
        designer_name = str((node.props or {}).get("designer_name") or "").strip()
        if designer_name:
            return designer_name
        if bool(getattr(self, "_is_onec_imported", False)):
            technical_name = str(node.name or "").strip()
            if technical_name:
                return technical_name
        if str(node.type or "").strip() == "CommandBar":
            technical_name = str(node.name or "").strip().casefold().replace("-", "_")
            if not str(node.title or "").strip() and technical_name in {"", "command_bar", "commandbar"}:
                return t("form_ctl_command_bar")
        for candidate in (node.title, node.name, node.binding, node.id):
            text = str(candidate or "").strip()
            if text:
                return text
        return str(node.id or "")

    def _table_columns_for_tree(self, node: FormNode) -> list[dict[str, Any]]:
        columns: list[dict[str, Any]] = []
        for source in (node.props or {}).get("columns") or []:
            if isinstance(source, dict):
                column = dict(source)
            else:
                name = str(source or "").strip()
                if not name:
                    continue
                column = {"name": name, "title": name, "binding": name}
            name = str(column.get("name") or column.get("code") or column.get("binding") or "").strip()
            if not name:
                continue
            column.setdefault("name", name)
            column.setdefault("binding", name)
            columns.append(column)

        if columns:
            return columns

        binding = str(node.binding or node.name or "").strip().casefold()
        if not binding:
            return []
        for requisite in self._available_requisites():
            if not bool(requisite.get("tabular_part")):
                continue
            candidate = str(
                requisite.get("binding") or requisite.get("code") or requisite.get("name") or ""
            ).strip().casefold()
            if candidate != binding:
                continue
            return [dict(column) for column in requisite.get("columns") or [] if isinstance(column, dict)]
        return []

    def _table_commands_for_tree(self, node: FormNode) -> list[str]:
        props = node.props or {}
        commands: list[str] = []

        def append(value: Any) -> None:
            if isinstance(value, dict):
                text = str(
                    value.get("designer_name")
                    or value.get("name")
                    or value.get("command")
                    or value.get("title")
                    or ""
                ).strip()
            else:
                text = str(value or "").strip()
            if text and text.casefold() not in {item.casefold() for item in commands}:
                commands.append(text)

        append(
            props.get("fill_by_stock_designer_name")
            or props.get("fill_by_stock_command")
            or props.get("fill_by_stock")
        )
        for source in props.get("buttons") or []:
            append(source)
        for source in props.get("extra_commands") or []:
            append(source)
        return commands

    @staticmethod
    def _add_virtual_tree_item(parent: QTreeWidgetItem, item_id: str, caption: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([str(caption or "")])
        item.setData(0, Qt.ItemDataRole.UserRole, f"virtual:{item_id}")
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        parent.addChild(item)
        return item

    def _on_toolbox_double_clicked(self, item: QListWidgetItem) -> None:
        if not self._is_edit_enabled() or item is None:
            return
        control_type = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not control_type:
            return
        self._add_control(control_type)

    def _rebuild_tree(self, *, keep_selected_id: str | None = None) -> None:
        selected_item: Optional[QTreeWidgetItem] = None
        self._ui_guard = True
        try:
            self.tree.clear()
            self._node_by_id = {}
            self._parent_by_id = {}
            self._tree_item_by_id = {}

            def add_node(parent_item: Optional[QTreeWidgetItem], parent_id: str, node: FormNode) -> QTreeWidgetItem:
                self._node_by_id[node.id] = node
                self._parent_by_id[node.id] = parent_id
                caption = t("form_tab_design") if node.id == self._model.root.id else self._node_tree_name(node)
                if node.id != self._model.root.id and not form_node_is_visible(node):
                    caption = f"{caption} [{t('form_hidden_in_client')}]"
                item = QTreeWidgetItem([caption])
                item.setData(0, Qt.ItemDataRole.UserRole, node.id)
                if node.id != self._model.root.id and not form_node_is_visible(node):
                    item.setToolTip(0, t("form_hidden_in_client_help"))
                self._tree_item_by_id[node.id] = item
                if parent_item is None:
                    self.tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                for child in node.children:
                    add_node(item, node.id, child)

                if str(node.type or "").strip() in {"Table", "TablePanel"}:
                    has_command_bar = any(
                        str(child.type or "").strip() == "CommandBar" for child in node.children
                    )
                    if not has_command_bar:
                        command_bar_caption = str(
                            (node.props or {}).get("command_bar_designer_name") or ""
                        ).strip() or t("form_ctl_command_bar")
                        command_bar = self._add_virtual_tree_item(
                            item,
                            f"{node.id}:command_bar",
                            command_bar_caption,
                        )
                        for index, command in enumerate(self._table_commands_for_tree(node)):
                            self._add_virtual_tree_item(
                                command_bar,
                                f"{node.id}:command:{index}",
                                command,
                            )

                    persisted_bindings = {
                        str(child.binding or child.name or "").strip().casefold()
                        for child in node.children
                        if str(child.binding or child.name or "").strip()
                    }
                    for index, column in enumerate(self._table_columns_for_tree(node)):
                        binding = str(
                            column.get("binding") or column.get("code") or column.get("name") or ""
                        ).strip()
                        local_binding = binding.rsplit(".", 1)[-1].casefold()
                        if binding.casefold() in persisted_bindings or local_binding in persisted_bindings:
                            continue
                        technical_title = str(
                            column.get("designer_name")
                            or (
                                column.get("name")
                                if bool(getattr(self, "_is_onec_imported", False))
                                else ""
                            )
                            or ""
                        ).strip()
                        title = technical_title or self._requisite_title(column) or binding.rsplit(".", 1)[-1]
                        self._add_virtual_tree_item(
                            item,
                            f"{node.id}:column:{index}",
                            title,
                        )
                return item

            root_item = add_node(None, "", self._model.root)
            self.tree.expandAll()

            nid = keep_selected_id or self._model.root.id
            it = self._tree_item_by_id.get(nid, root_item)
            self.tree.setCurrentItem(it)
            selected_item = it
        finally:
            self._ui_guard = False
        if selected_item is not None:
            self._on_tree_selection(selected_item, None)
        refresh_workspace = getattr(self, "_refresh_workspace_panels", None)
        if callable(refresh_workspace):
            refresh_workspace()

    def _current_node(self) -> Optional[FormNode]:
        it = self.tree.currentItem()
        if it is None:
            return None
        node_id = str(it.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        return self._node_by_id.get(node_id)

    def _parent_node(self, node_id: str) -> Optional[FormNode]:
        pid = str(self._parent_by_id.get(str(node_id or ""), "") or "")
        return self._node_by_id.get(pid) if pid else None

    def _node_for_id(self, node_id: str) -> Optional[FormNode]:
        nid = str(node_id or "").strip()
        if not nid:
            return None
        return self._node_by_id.get(nid)

    def _new_id(self, prefix: str) -> str:
        base = prefix.lower()[:3]
        return f"{base}_{uuid.uuid4().hex[:8]}"

    def _clone_node_tree(self, node: FormNode) -> FormNode:
        new_node = FormNode(
            id=self._new_id(str(node.type or "node")),
            type=node.type,
            name=str(node.name or ""),
            title=str(node.title or ""),
            binding=str(node.binding or ""),
            props=dict(node.props or {}),
            children=[],
        )
        for child in node.children:
            new_node.children.append(self._clone_node_tree(child))
        return new_node

    def _clipboard_payload_for_node(self, node: FormNode) -> dict[str, Any]:
        return {
            "schema": 1,
            "kind": "form_node_tree",
            "node": node.to_dict(),
        }

    def _clipboard_node_from_mime(self) -> FormNode | None:
        app = QApplication.instance()
        if app is None:
            return None
        raw = str(getattr(app, "_mp_form_node_clipboard_payload", "") or "")
        if not raw:
            clipboard = app.clipboard()
            mime = clipboard.mimeData()
            if mime is None or not mime.hasFormat(FORM_NODE_CLIPBOARD_MIME):
                return None
            try:
                raw = bytes(mime.data(FORM_NODE_CLIPBOARD_MIME)).decode("utf-8", errors="ignore")
            except Exception:
                return None
        if not raw.strip():
            return None
        try:
            payload = json.loads(raw)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        node_payload = payload.get("node")
        if not isinstance(node_payload, dict):
            return None
        try:
            return FormNode.from_dict(node_payload)
        except Exception:
            return None

    def _set_clipboard_node(self, node: FormNode) -> None:
        app = QApplication.instance()
        if app is None:
            return
        clipboard = app.clipboard()
        try:
            payload = json.dumps(self._clipboard_payload_for_node(node), ensure_ascii=False)
        except Exception:
            return
        setattr(app, "_mp_form_node_clipboard_payload", payload)
        clipboard.setText(str(node.title or node.name or node.id or "").strip())

    @staticmethod
    def _clear_form_node_clipboard() -> None:
        app = QApplication.instance()
        if app is None:
            return
        setattr(app, "_mp_form_node_clipboard_payload", "")

    def _target_parent_for_paste(self) -> FormNode:
        node = self._current_node() or self._model.root
        return self._target_parent_for_node(node.id)

    def _target_parent_for_node(self, node_id: str) -> FormNode:
        node = self._node_for_id(node_id) or self._model.root
        if node.type == "Container":
            return node
        parent = self._parent_node(node.id)
        return parent if parent is not None else self._model.root

    def _suggest_pos_in_absolute(self, parent: FormNode) -> tuple[int, int]:
        max_bottom = 20
        for child in parent.children:
            props = child.props or {}
            try:
                cy = int(props.get("y") or 0)
                chh = int(props.get("h") or 0)
                max_bottom = max(max_bottom, cy + chh + 12)
            except Exception:
                continue
        return 20, max_bottom

    def _add_control(
        self,
        control_type: str,
        *,
        default_props: dict[str, Any] | None = None,
        default_title: str = "",
    ) -> None:
        if not self._is_edit_enabled():
            return
        parent = self._current_node() or self._model.root
        if parent.type == "Tabs" and control_type == "Container":
            pass
        elif parent.type != "Container":
            parent = self._model.root
        pid = parent.id
        parent_layout = str((parent.props or {}).get("layout") or "vertical").strip().lower()
        if parent_layout == "absolute":
            x, y = self._suggest_pos_in_absolute(parent)
            self._add_control_at(
                control_type,
                pid,
                x,
                y,
                default_props=default_props,
                default_title=default_title,
            )
        else:
            self._add_control_at(
                control_type,
                pid,
                0,
                0,
                default_props=default_props,
                default_title=default_title,
            )

    def _add_control_at(
        self,
        control_type: str,
        parent_id: str,
        x: int,
        y: int,
        *,
        default_props: dict[str, Any] | None = None,
        default_title: str = "",
    ) -> None:
        if not self._is_edit_enabled():
            return
        parent = self._node_by_id.get(str(parent_id or "").strip())
        if parent is None or (
            parent.type != "Container"
            and not (parent.type == "Tabs" and control_type == "Container")
        ):
            parent = self._model.root

        nid = self._new_id(control_type)
        node = FormNode(id=nid, type=control_type, name=control_type)

        if control_type == "Container":
            node.props["layout"] = "vertical"
            if parent.type == "Tabs":
                node.name = f"Page{len(parent.children) + 1}"
                node.title = t("form_tabs_page_title").format(n=len(parent.children) + 1)
        if control_type == "Tabs":
            node.props["pages_representation"] = "TabsOnTop"
            node.children = [
                FormNode(
                    id=f"{nid}_page_1",
                    type="Container",
                    name="Page1",
                    title=t("form_tabs_page_title").format(n=1),
                    props={"layout": "vertical"},
                )
            ]
        if control_type == "Table":
            node.props["columns"] = []
        if control_type == "ComboBox":
            node.props.setdefault("items", [])
        if control_type == "CommandBar":
            button_defs = [
                {"title": "Провести і закрити", "command": "post_and_close", "role": "primary", "icon": "save"},
                {"separator_after": True},
                {"title": "Провести", "command": "post"},
                {"title": "Записати", "command": "save", "icon": "save"},
                {"title": "Закрити", "command": "close", "icon": "close"},
            ]
            node.props.setdefault("buttons", button_defs)
            node.props.setdefault("show_all_actions", True)
            node.children = [
                FormNode(
                    id=f"{nid}_btn_{i}",
                    type="Button",
                    name=str(bdef.get("command") or bdef.get("title") or f"Command{i}"),
                    title=str(bdef.get("title") or bdef.get("command") or ""),
                    props={
                        "command": str(bdef.get("command") or ""),
                        "role": str(bdef.get("role") or ""),
                        "icon": str(bdef.get("icon") or ""),
                        "separator_after": bool(bdef.get("separator_after")),
                    },
                )
                for i, bdef in enumerate(button_defs, start=1)
                if isinstance(bdef, dict) and (str(bdef.get("title") or "").strip() or str(bdef.get("command") or "").strip())
            ]
        if control_type == "TablePanel":
            node.props["columns"] = []
            node.props.setdefault("can_add", True)
            node.props.setdefault("can_delete", True)
            node.props.setdefault("can_move_up", False)
            node.props.setdefault("can_move_down", False)
            node.props.setdefault("fill_by_stock", "")
        if control_type == "StatusBar":
            node.props.setdefault(
                "fields",
                [
                    {"label": "Перевитрата:", "binding": "overspend", "decimals": 2, "read_only": True},
                    {"label": "Витрачено:", "binding": "total_spent", "decimals": 2, "read_only": True},
                    {"label": "Отримано:", "binding": "total_received", "decimals": 2, "read_only": True},
                ],
            )

        if default_props:
            node.props.update(default_props)
        if default_title:
            node.title = str(default_title)

        parent_layout = "vertical" if parent.type == "Tabs" else str((parent.props or {}).get("layout") or "vertical").strip().lower()
        if parent_layout == "absolute":
            w, h = self._default_size(control_type)
            node.props.update({"x": int(x), "y": int(y), "w": int(w), "h": int(h)})
        elif parent_layout == "grid":
            cols = int((parent.props or {}).get("grid_columns") or 2)
            idx = len(parent.children)
            row = idx // max(1, cols)
            col = idx % max(1, cols)
            node.props["grid"] = {"row": row, "col": col, "rowspan": 1, "colspan": 1}

        parent.children.append(node)

        self._set_dirty(True)
        self._rebuild_tree(keep_selected_id=nid)
        self._refresh_canvas()
        self._render_preview()
        try:
            QTimer.singleShot(0, partial(self._select_node_by_id, nid))
        except Exception:
            pass

    def _on_requisite_double_clicked(self, item, *_args) -> None:
        if not self._is_edit_enabled() or item is None:
            return
        try:
            req = item.data(0, Qt.ItemDataRole.UserRole)
        except TypeError:
            req = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(req, dict):
            return
        parent = self._current_node() or self._model.root
        if parent.type != "Container":
            parent = self._model.root
        pid = parent.id
        parent_layout = str((parent.props or {}).get("layout") or "vertical").strip().lower()
        if parent_layout == "absolute":
            x, y = self._suggest_pos_in_absolute(parent)
            self._add_requisite_pair_at(req, pid, x, y)
        else:
            self._add_requisite_pair_at(req, pid, 0, 0)

    def _next_grid_row(self, parent: FormNode) -> int:
        max_row = -1
        for child in parent.children:
            grid = (child.props or {}).get("grid")
            if not isinstance(grid, dict):
                continue
            try:
                max_row = max(max_row, int(grid.get("row") or 0))
            except Exception:
                continue
        return max_row + 1

    def _add_requisite_pair_at(self, req: dict[str, Any], parent_id: str, x: int, y: int) -> None:
        if not self._is_edit_enabled():
            return
        parent = self._node_by_id.get(str(parent_id or "").strip())
        if parent is None or parent.type != "Container":
            parent = self._model.root

        code = str(req.get("code") or "").strip()
        caption = self._requisite_title(req)
        control_type = self._control_type_for_requisite(str(req.get("type") or ""))

        lbl_id = self._new_id("Label")
        ctl_id = self._new_id(control_type)

        label = FormNode(id=lbl_id, type="Label", name=f"lbl_{code}" if code else "Label", title=caption)
        control = FormNode(id=ctl_id, type=control_type, name=code if code else control_type, title="", binding=code)

        if control_type == "ComboBox":
            control.props.setdefault("items", [])
        if control_type == "Table":
            control.props["columns"] = [
                {
                    "name": str(column.get("name") or column.get("code") or "").strip(),
                    "title": self._requisite_title(column),
                    "type": str(column.get("type") or column.get("data_type") or "string").strip() or "string",
                    "binding": str(column.get("binding") or column.get("name") or column.get("code") or "").strip(),
                }
                for column in req.get("columns") or []
                if isinstance(column, dict)
                and str(column.get("name") or column.get("code") or "").strip()
            ]

        parent_layout = str((parent.props or {}).get("layout") or "vertical").strip().lower()
        if parent_layout == "absolute":
            lw, lh = self._default_size("Label")
            cw, ch = self._default_size(control_type)
            gap = 10
            label.props.update({"x": int(x), "y": int(y), "w": int(lw), "h": int(lh)})
            control.props.update({"x": int(x + lw + gap), "y": int(y), "w": int(cw), "h": int(ch)})
        elif parent_layout == "grid":
            cols = int((parent.props or {}).get("grid_columns") or 2)
            row = self._next_grid_row(parent)
            label.props["grid"] = {"row": row, "col": 0, "rowspan": 1, "colspan": 1}
            control.props["grid"] = {"row": row, "col": 1, "rowspan": 1, "colspan": max(1, cols - 1)}

        parent.children.append(label)
        parent.children.append(control)

        self._set_dirty(True)
        self._rebuild_tree(keep_selected_id=ctl_id)
        self._refresh_canvas()
        self._render_preview()
        try:
            QTimer.singleShot(0, lambda nid=ctl_id: self._select_node_by_id(nid))
        except Exception:
            pass

    def _delete_node_by_id(self, node_id: str) -> None:
        if not self._is_edit_enabled():
            return
        target_id = str(node_id or "").strip()
        if not target_id or target_id == self._model.root.id:
            return

        node = self._node_by_id.get(target_id)
        if node is None:
            return

        def remove_from(parent: FormNode) -> bool:
            for idx, child in enumerate(list(parent.children)):
                if child.id == node.id:
                    parent.children.pop(idx)
                    self._delete_reselect_id = str(parent.id or self._model.root.id).strip() or self._model.root.id
                    return True
                if remove_from(child):
                    return True
            return False

        self._delete_reselect_id = self._model.root.id
        remove_from(self._model.root)
        keep_selected_id = str(getattr(self, "_delete_reselect_id", self._model.root.id) or self._model.root.id).strip()
        self._set_dirty(True)
        self._rebuild_tree(keep_selected_id=keep_selected_id)
        self._refresh_canvas()
        self._render_preview()

    def _duplicate_node_by_id(self, node_id: str) -> None:
        if not self._is_edit_enabled():
            return
        node = self._node_for_id(node_id)
        if node is None or node.id == self._model.root.id:
            return
        parent = self._parent_node(node.id)
        if parent is None:
            return
        try:
            idx = next((i for i, child in enumerate(parent.children) if child.id == node.id), -1)
            if idx < 0:
                return
            clone = self._clone_node_tree(node)
            parent.children.insert(idx + 1, clone)
        except Exception:
            return
        self._set_dirty(True)
        self._rebuild_tree(keep_selected_id=clone.id)
        self._refresh_canvas()
        self._render_preview()
        try:
            QTimer.singleShot(0, lambda nid=clone.id: self._select_node_by_id(nid))
        except Exception:
            pass

    def _copy_node_by_id(self, node_id: str) -> None:
        if not self._is_edit_enabled():
            return
        node = self._node_for_id(node_id)
        if node is None or node.id == self._model.root.id:
            return
        self._set_clipboard_node(node)

    def _cut_node_by_id(self, node_id: str) -> None:
        if not self._is_edit_enabled():
            return
        node = self._node_for_id(node_id)
        if node is None or node.id == self._model.root.id:
            return
        self._set_clipboard_node(node)
        self._delete_node_by_id(node.id)

    def _paste_to_node(self, node_id: str) -> None:
        if not self._is_edit_enabled():
            return
        source = self._clipboard_node_from_mime()
        if source is None:
            return
        parent = self._target_parent_for_node(node_id)
        if parent is None:
            parent = self._model.root
        clone = self._clone_node_tree(source)
        try:
            parent.children.append(clone)
        except Exception:
            return
        self._set_dirty(True)
        self._rebuild_tree(keep_selected_id=clone.id)
        self._refresh_canvas()
        self._render_preview()
        try:
            QTimer.singleShot(0, lambda nid=clone.id: self._select_node_by_id(nid))
        except Exception:
            pass

    def _delete_selected(self) -> None:
        node = self._current_node()
        if node is None:
            return
        self._delete_node_by_id(node.id)

    def _move_selected(self, step: int) -> None:
        if not self._is_edit_enabled():
            return
        node = self._current_node()
        if node is None or node.id == self._model.root.id:
            return
        parent = self._parent_node(node.id)
        if parent is None:
            return
        try:
            siblings = parent.children
            idx = next((i for i, child in enumerate(siblings) if child.id == node.id), -1)
            if idx < 0:
                return
            new_idx = idx + int(step)
            if new_idx < 0 or new_idx >= len(siblings):
                return
            siblings.insert(new_idx, siblings.pop(idx))
        except Exception:
            return
        self._set_dirty(True)
        self._rebuild_tree(keep_selected_id=node.id)
        self._refresh_canvas()
        self._render_preview()

    def _duplicate_selected(self) -> None:
        node = self._current_node()
        if node is None:
            return
        self._duplicate_node_by_id(node.id)

    def _copy_selected(self) -> None:
        node = self._current_node()
        if node is None:
            return
        self._copy_node_by_id(node.id)

    def _cut_selected(self) -> None:
        node = self._current_node()
        if node is None:
            return
        self._cut_node_by_id(node.id)

    def _paste_selected(self) -> None:
        node = self._current_node() or self._model.root
        if node is None:
            return
        self._paste_to_node(node.id)

    def _sync_tree_order_to_model(self) -> None:
        if not self._is_edit_enabled():
            return

        root_item = self.tree.topLevelItem(0)
        if root_item is None:
            return

        def apply(parent_item: QTreeWidgetItem, parent_node: FormNode) -> None:
            ordered_children: list[FormNode] = []
            for idx in range(parent_item.childCount()):
                child_item = parent_item.child(idx)
                node_id = str(child_item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
                child_node = self._node_by_id.get(node_id)
                if child_node is None:
                    continue
                ordered_children.append(child_node)
                apply(child_item, child_node)
            parent_node.children = ordered_children

        try:
            apply(root_item, self._model.root)
        except Exception:
            return

        current = self._current_node()
        keep_selected_id = current.id if current is not None else self._model.root.id
        self._set_dirty(True)
        self._rebuild_tree(keep_selected_id=keep_selected_id)
        self._refresh_canvas()
        self._render_preview()

    def _on_tree_order_changed(self) -> None:
        self._sync_tree_order_to_model()

    def _show_tree_context_menu(self, pos) -> None:
        if not self._is_edit_enabled():
            return
        node = self._current_node()
        if node is None:
            return

        menu = QMenu(self.tree)
        act_add_page = menu.addAction(t("form_tabs_add_page")) if node.type == "Tabs" else None
        if act_add_page is not None:
            menu.addSeparator()
        act_copy = menu.addAction("Copy")
        act_cut = menu.addAction("Cut")
        act_paste = menu.addAction("Paste")
        act_duplicate = menu.addAction("Duplicate")
        act_delete = menu.addAction("Delete")
        menu.addSeparator()
        act_up = menu.addAction("Move Up")
        act_down = menu.addAction("Move Down")

        can_edit_node = node.id != self._model.root.id
        act_copy.setEnabled(can_edit_node)
        act_cut.setEnabled(can_edit_node)
        act_duplicate.setEnabled(can_edit_node)
        act_delete.setEnabled(can_edit_node)
        act_up.setEnabled(can_edit_node)
        act_down.setEnabled(can_edit_node)
        act_paste.setEnabled(self._clipboard_node_from_mime() is not None)

        exec_fn = getattr(self, "_tree_context_menu_exec", None)
        if callable(exec_fn):
            chosen = exec_fn(menu, self.tree.viewport().mapToGlobal(pos))
        else:
            chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if act_add_page is not None and chosen is act_add_page:
            self._add_control_at("Container", node.id, 0, 0)
            return
        if chosen is act_copy:
            self._copy_node_by_id(node.id)
            return
        if chosen is act_cut:
            self._cut_node_by_id(node.id)
            return
        if chosen is act_paste:
            self._paste_to_node(node.id)
            return
        if chosen is act_duplicate:
            self._duplicate_node_by_id(node.id)
            return
        if chosen is act_delete:
            self._delete_selected()
            return
        if chosen is act_up:
            self._move_selected(-1)
            return
        if chosen is act_down:
            self._move_selected(1)
            return

    def _on_canvas_selection(self, node_id: str) -> None:
        if self._ui_guard:
            return
        nid = str(node_id or "").strip()
        it = self._tree_item_by_id.get(nid)
        if it is None:
            return
        self._ui_guard = True
        try:
            self.tree.setCurrentItem(it)
        finally:
            self._ui_guard = False

    def _on_canvas_selection_set_changed(self, count: int, primary_id: str) -> None:
        try:
            self._canvas_sel_count = int(count)
        except Exception:
            self._canvas_sel_count = 0
        self._canvas_primary_id = str(primary_id or "").strip()
        self._update_design_toolbar_state()

    def _on_snap_grid_toggled(self, enabled: bool) -> None:
        try:
            self.canvas.set_grid_snap_enabled(bool(enabled))
            self.canvas.set_grid_visible(bool(enabled))
        except Exception:
            pass

    def _on_grid_size_changed(self, value: int) -> None:
        try:
            self.canvas.set_grid_size(int(value))
        except Exception:
            pass

    def _update_design_toolbar_state(self) -> None:
        try:
            root_layout = str((self._model.root.props or {}).get("layout") or "vertical").strip().lower()
        except Exception:
            root_layout = "vertical"

        is_absolute = root_layout == "absolute"
        can_edit = self._is_edit_enabled() and is_absolute
        sel_count = int(getattr(self, "_canvas_sel_count", 0) or 0)

        try:
            self._act_snap_grid.setEnabled(is_absolute)
            self._sp_design_grid.setEnabled(is_absolute)
        except Exception:
            pass

        enable_align = bool(can_edit and sel_count >= 2)
        try:
            for action in (self._act_align_left, self._act_align_right, self._act_align_top, self._act_align_bottom):
                action.setEnabled(enable_align)
        except Exception:
            pass

    def _align_selected(self, edge: str) -> None:
        if not self._is_edit_enabled():
            return
        try:
            root_layout = str((self._model.root.props or {}).get("layout") or "vertical").strip().lower()
            if root_layout != "absolute":
                return
        except Exception:
            return

        try:
            changes = self.canvas.align_selected(str(edge or ""))
        except Exception:
            changes = []
        if not changes:
            return

        moved_ids = set()
        for node_id, x, y, w, h in changes:
            nid = str(node_id or "").strip()
            if not nid:
                continue
            node = self._node_by_id.get(nid)
            if node is None:
                continue
            node.props = dict(node.props or {})
            node.props["x"] = int(x)
            node.props["y"] = int(y)
            node.props["w"] = int(w)
            node.props["h"] = int(h)
            moved_ids.add(nid)

        if moved_ids:
            self._set_dirty(True)
            self._render_preview()

    def _on_canvas_add_control(self, control_type: str, parent_id: str, x: int, y: int) -> None:
        self._add_control_at(control_type, parent_id, x, y)

    def _on_canvas_add_requisite(self, req: object, parent_id: str, x: int, y: int) -> None:
        if not isinstance(req, dict):
            return
        self._add_requisite_pair_at(req, parent_id, x, y)

    def _refresh_canvas(self) -> None:
        self._refresh_design_surface()

    def eventFilter(self, obj: object, event: QEvent) -> bool:  # noqa: N802
        try:
            if event.type() == QEvent.Type.KeyPress:
                key = int(event.key()) if hasattr(event, "key") else 0
                if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    if hasattr(obj, "objectName") and str(obj.objectName() or "") == "FormDesignerStructure":
                        self._delete_selected()
                        return True
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
                nid = None
                if hasattr(obj, "property"):
                    nid = obj.property("form_node_id")
                if nid:
                    self._select_node_by_id(str(nid))
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _select_node_by_id(self, node_id: str) -> None:
        nid = str(node_id or "").strip()
        if not nid:
            return
        it = self._tree_item_by_id.get(nid)
        if it is None:
            return
        if self.tree.currentItem() is not it:
            self.tree.setCurrentItem(it)
        try:
            self._focus_properties_for_node(nid)
        except Exception:
            pass
        try:
            self._ensure_design_focus(nid)
        except Exception:
            pass

    def _ensure_design_focus(self, node_id: str) -> None:
        nid = str(node_id or "").strip()
        if not nid:
            return

        root_layout = str((self._model.root.props or {}).get("layout") or "vertical").strip().lower()
        try:
            if root_layout == "absolute":
                try:
                    self.canvas.select_node(nid)
                except Exception:
                    pass
                try:
                    self.canvas.ensure_valid_viewport()
                except Exception:
                    pass
            else:
                widget = self._design_wrap_by_id.get(nid)
                if widget is not None:
                    try:
                        self._design_preview_scroll.ensureWidgetVisible(widget)
                    except Exception:
                        pass
        except Exception:
            pass
