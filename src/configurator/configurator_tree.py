from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap, QStandardItem
from PySide6.QtWidgets import QLineEdit, QMenu, QStyle

from src.configurator.persistence.db_seed import GUID_MODULE_APP
from src.configurator.domain.technical_names import technical_object_name
from src.configurator.ui.widgets import NodeInfo
from src.ui_qt.i18n import t


class ConfiguratorTreeMixin:
    def expand_default(self) -> None:
        s = (self.search.text() or "").strip().lower()
        if s:
            self.tree.expandAll()
        else:
            self.tree.blockSignals(True)
            self.tree.collapseAll()
            self.tree.expandToDepth(0)
            self.tree.blockSignals(False)

    def node_info_from_index(self, idx) -> Optional[NodeInfo]:
        if not idx.isValid():
            return None
        item = self.tree_model.itemFromIndex(idx)
        if item is None:
            return None
        kind = str(item.data(self.ROLE_KIND) or "object")
        meta = item.data(self.ROLE_META)
        if kind in ("root", "group", "folder", "object", "schema"):
            if isinstance(meta, dict):
                payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
                obj_type = str(meta.get("type", ""))
                display_name = (
                    technical_object_name(meta.get("name"), payload=payload)
                    if kind == "object"
                    else str(meta.get("title") or item.text())
                )
                return NodeInfo(
                    kind=kind,
                    name=display_name,
                    guid=str(meta.get("guid", "")),
                    obj_type=obj_type,
                )
            return NodeInfo(kind=kind, name=item.text())
        return NodeInfo(kind=kind, name=item.text())

    def _on_tree_select(self, idx) -> None:
        info = self.node_info_from_index(idx)
        if info:
            self.treeSelectChanged.emit(info)

    def _on_tree_open(self, idx) -> None:
        info = self.node_info_from_index(idx)
        if not info:
            return
        if info.kind in ("object", "schema", "folder"):
            self.treeOpenRequested.emit(info)

    def _is_configuration_root(self, kind: str, meta: dict) -> bool:
        try:
            if kind == "root":
                return True
            tpe = str(meta.get("type") or "").lower().strip()
            if tpe in ("configuration", "config", "cfg"):
                if not str(meta.get("parent_guid") or "").strip():
                    return True
            name = str(meta.get("name") or meta.get("title") or "").lower()
            if name in ("конфигурация", "конфігурація", "configuration"):
                if not str(meta.get("parent_guid") or "").strip():
                    return True
        except Exception:
            return False
        return False

    def _find_child_guid_by_title(self, parent_item, titles: tuple[str, ...]) -> str:
        try:
            titles_l = {t1.strip().lower() for t1 in titles}
            for r in range(parent_item.rowCount()):
                ch = parent_item.child(r)
                if ch is None:
                    continue
                if str(ch.text() or "").strip().lower() in titles_l:
                    meta = ch.data(self.ROLE_META) or {}
                    if isinstance(meta, dict):
                        g = str(meta.get("guid") or "").strip()
                        if g:
                            return g
        except Exception:
            pass
        return ""

    def _find_child_item_by_title(self, parent_item, titles: tuple[str, ...]):
        try:
            titles_l = {t1.strip().lower() for t1 in titles}
            for r in range(parent_item.rowCount()):
                ch = parent_item.child(r)
                if ch is None:
                    continue
                if str(ch.text() or "").strip().lower() in titles_l:
                    return ch
        except Exception:
            pass
        return None

    def _populate_configuration_context_menu(self, menu: QMenu, cfg_item, cfg_meta: dict) -> None:
        if self._vm is None:
            return
        cfg_guid = str(cfg_meta.get("guid") or "").strip()
        if not cfg_guid:
            return
        tr = t
        act_app_mod = menu.addAction(tr("ctx_open_app_module"))
        act_app_mod.triggered.connect(lambda _=False: self._open_module_by_guid(GUID_MODULE_APP, "МодульПрограми / AppModule"))
        act_sess = menu.addAction(tr("ctx_open_session_module"))
        act_sess.triggered.connect(lambda _=False: self._open_cfg_module("SessionModule", tr("ctx_open_session_module")))
        act_ext = menu.addAction(tr("ctx_open_external_connection_module"))
        act_ext.triggered.connect(
            lambda _=False: self._open_cfg_module("ExternalConnectionModule", tr("ctx_open_external_connection_module"))
        )
        menu.addSeparator()
        for key in (
            "ctx_open_cfg_cmd_interface",
            "ctx_open_start_page_workspace",
            "ctx_open_main_section_cmd_interface",
            "ctx_open_client_app_interface",
            "ctx_open_autonomous_cfg_composition",
            "SEP",
            "ctx_help",
        ):
            if key == "SEP":
                menu.addSeparator()
                continue
            act = menu.addAction(tr(key))
            act.triggered.connect(lambda _=False: self._vm.show_info(tr("info_title"), tr("info_not_implemented")))
        menu.addSeparator()
        act = menu.addAction(tr("ctx_all_subsystems"))
        act.triggered.connect(lambda _=False: self._vm.open_common_list("subsystems", cfg_guid))
        act = menu.addAction(tr("ctx_all_roles"))
        act.triggered.connect(lambda _=False: self._vm.open_common_list("roles", cfg_guid))
        act = menu.addAction(tr("ctx_all_access_restrictions"))
        act.triggered.connect(lambda _=False: self._vm.open_common_list("access_restrictions", cfg_guid))
        act = menu.addAction(tr("ctx_all_pictures"))
        act.triggered.connect(lambda _=False: self._vm.open_common_list("pictures", cfg_guid))
        pics_menu = menu.addMenu(tr("ctx_pictures_library"))
        act = pics_menu.addAction(tr("pictures_view"))
        act.triggered.connect(lambda _=False: self.open_pictures_gallery())
        act = pics_menu.addAction(tr("pictures_open_editor"))
        act.triggered.connect(lambda _=False: self.open_svg_editor_for_selection())
        act = pics_menu.addAction(tr("pictures_upload"))
        act.triggered.connect(lambda _=False: self.upload_pictures_via_dialog())
        menu.addSeparator()
        add_menu = menu.addMenu(tr("ctx_add"))
        common_item = self._find_child_item_by_title(cfg_item, ("Загальні", "Общие", "Common", "Общее"))
        if common_item is not None:
            create_map = {
                "languages": ("language", None, "ctx_add_language"),
                "subsystems": ("subsystem", None, "ctx_add_subsystem"),
                "common_modules": ("common", "common_module", "ctx_add_common_module"),
                "session_params": ("session_parameter", None, "ctx_add_session_parameter"),
                "roles": ("role", None, "ctx_add_role"),
                "common_attributes": ("common_attribute", None, "ctx_add_common_attribute"),
                "exchange_plans": ("exchange_plan", None, "ctx_add_exchange_plan"),
                "selection_criteria": ("selection_criterion", None, "ctx_add_selection_criterion"),
                "event_subscriptions": ("event_subscription", None, "ctx_add_event_subscription"),
                "scheduled_jobs": ("scheduled_job", None, "ctx_add_scheduled_job"),
                "bots": ("bot", None, "ctx_add_bot"),
                "functional_options": ("functional_option", None, "ctx_add_functional_option"),
                "functional_options_params": ("functional_option_parameter", None, "ctx_add_functional_option_parameter"),
                "defined_types": ("defined_type", None, "ctx_add_defined_type"),
                "settings_storages": ("settings_storage", None, "ctx_add_settings_storage"),
                "common_commands": ("common", "common_command", "ctx_add_common_command"),
                "command_groups": ("common", "command_group", "ctx_add_command_group"),
                "common_forms": ("common", "common_form", "ctx_add_common_form"),
                "common_layouts": ("common_layout", None, "ctx_add_common_layout"),
                "common_pictures": ("common_picture", None, "ctx_add_common_picture"),
                "xdto_packages": ("xdto_package", None, "ctx_add_xdto_package"),
                "web_services": ("web_service", None, "ctx_add_web_service"),
                "http_services": ("http_service", None, "ctx_add_http_service"),
                "ws_links": ("ws_reference", None, "ctx_add_ws_reference"),
                "websocket_clients": ("websocket_client", None, "ctx_add_websocket_client"),
                "integration_services": ("integration_service", None, "ctx_add_integration_service"),
                "style_elements": ("style_element", None, "ctx_add_style_element"),
                "styles": ("style", None, "ctx_add_style"),
            }
            children: list[tuple[int, dict, str]] = []
            for r in range(common_item.rowCount()):
                ch = common_item.child(r)
                if ch is None:
                    continue
                m = ch.data(self.ROLE_META) or {}
                if not isinstance(m, dict):
                    continue
                p = m.get("payload") if isinstance(m.get("payload"), dict) else {}
                try:
                    order = int(p.get("order") or 0)
                except Exception:
                    order = 0
                key = str(m.get("name") or "").strip()
                children.append((order, m, key))
            children.sort(key=lambda x: x[0])
            for _ord, ch_meta, key in children:
                if key not in create_map:
                    continue
                obj_type, subtype, tr_key = create_map[key]
                pg = str(ch_meta.get("guid") or "").strip()
                if not pg:
                    continue
                label = tr(tr_key)
                act = add_menu.addAction(self._plus_green_icon(), label)
                act.triggered.connect(
                    lambda _=False, ot=obj_type, st=subtype, parent=pg: self._create_object_and_rename(ot, parent, st)
                )

    def _on_tree_context_menu(self, pos: QPoint) -> None:
        idx = self.tree.indexAt(pos)
        if not idx.isValid() or self._vm is None:
            return
        item = self.tree_model.itemFromIndex(idx)
        if item is None:
            return
        kind = str(item.data(self.ROLE_KIND) or "object")
        meta = item.data(self.ROLE_META) or {}
        if not isinstance(meta, dict):
            return
        global_pos = self.tree.viewport().mapToGlobal(pos)
        menu = QMenu(self)
        if self._is_configuration_root(kind, meta):
            self._populate_configuration_context_menu(menu, item, meta)
            if menu.actions():
                menu.exec(global_pos)
            return
        if kind == "group" and str(meta.get("type") or "").strip() == "common" and str(meta.get("name") or "").strip() == "common":
            add_menu = menu.addMenu(t("ctx_add"))
            create_map = {
                "languages": ("language", None, "ctx_add_language"),
                "subsystems": ("subsystem", None, "ctx_add_subsystem"),
                "common_modules": ("common", "common_module", "ctx_add_common_module"),
                "session_params": ("session_parameter", None, "ctx_add_session_parameter"),
                "roles": ("role", None, "ctx_add_role"),
                "common_attributes": ("common_attribute", None, "ctx_add_common_attribute"),
                "exchange_plans": ("exchange_plan", None, "ctx_add_exchange_plan"),
                "selection_criteria": ("selection_criterion", None, "ctx_add_selection_criterion"),
                "event_subscriptions": ("event_subscription", None, "ctx_add_event_subscription"),
                "scheduled_jobs": ("scheduled_job", None, "ctx_add_scheduled_job"),
                "bots": ("bot", None, "ctx_add_bot"),
                "functional_options": ("functional_option", None, "ctx_add_functional_option"),
                "functional_options_params": ("functional_option_parameter", None, "ctx_add_functional_option_parameter"),
                "defined_types": ("defined_type", None, "ctx_add_defined_type"),
                "settings_storages": ("settings_storage", None, "ctx_add_settings_storage"),
                "common_commands": ("common", "common_command", "ctx_add_common_command"),
                "command_groups": ("common", "command_group", "ctx_add_command_group"),
                "common_forms": ("common", "common_form", "ctx_add_common_form"),
                "common_layouts": ("common_layout", None, "ctx_add_common_layout"),
                "common_pictures": ("common_picture", None, "ctx_add_common_picture"),
                "xdto_packages": ("xdto_package", None, "ctx_add_xdto_package"),
                "web_services": ("web_service", None, "ctx_add_web_service"),
                "http_services": ("http_service", None, "ctx_add_http_service"),
                "ws_links": ("ws_reference", None, "ctx_add_ws_reference"),
                "websocket_clients": ("websocket_client", None, "ctx_add_websocket_client"),
                "integration_services": ("integration_service", None, "ctx_add_integration_service"),
                "style_elements": ("style_element", None, "ctx_add_style_element"),
                "styles": ("style", None, "ctx_add_style"),
            }
            children: list[tuple[int, dict, str]] = []
            for r in range(item.rowCount()):
                ch = item.child(r)
                if ch is None:
                    continue
                m = ch.data(self.ROLE_META) or {}
                if not isinstance(m, dict):
                    continue
                p = m.get("payload") if isinstance(m.get("payload"), dict) else {}
                try:
                    order = int(p.get("order") or 0)
                except Exception:
                    order = 0
                key = str(m.get("name") or "").strip()
                children.append((order, m, key))
            children.sort(key=lambda x: x[0])
            for _ord, ch_meta, key in children:
                if key not in create_map:
                    continue
                obj_type, subtype, tr_key = create_map[key]
                pg = str(ch_meta.get("guid") or "").strip()
                if not pg:
                    continue
                label = t(tr_key)
                act = add_menu.addAction(self._plus_green_icon(), label)
                act.triggered.connect(
                    lambda _=False, ot=obj_type, st=subtype, parent=pg: self._create_object_and_rename(ot, parent, st)
                )
            if menu.actions():
                menu.exec(global_pos)
            return
        if kind in ("folder", "group") and str(meta.get("type") or "").strip() == "common":
            parent_guid = str(meta.get("parent_guid") or "").strip()
            payload = meta.get("payload") if isinstance(meta, dict) else None
            if isinstance(payload, dict) and parent_guid and str(payload.get("menu") or "") == "add_only":
                try:
                    parent_item = item.parent() if kind != "root" else None
                except Exception:
                    parent_item = None
                is_under_common = False
                pmeta = {}
                if parent_item is not None:
                    pmeta = parent_item.data(self.ROLE_META) or {}
                    if isinstance(pmeta, dict):
                        if str(pmeta.get("type") or "").strip() == "common" and str(pmeta.get("guid") or "").strip() == parent_guid:
                            is_under_common = True
                if is_under_common:
                    key = str(meta.get("name") or "").strip()
                    all_map = {
                        "subsystems": "ctx_all_subsystems",
                        "roles": "ctx_all_roles",
                        "common_pictures": "ctx_all_pictures",
                    }
                    if key in all_map:
                        act_all = menu.addAction(t(all_map[key]))
                        cfg_guid = str(pmeta.get("parent_guid") or "").strip()
                        act_all.triggered.connect(lambda _=False, k=key, cg=cfg_guid: self._vm.open_common_list(k, cg))
                        menu.addSeparator()
                    create_map = {
                        "languages": ("language", None),
                        "subsystems": ("subsystem", None),
                        "common_modules": ("common", "common_module"),
                        "session_params": ("session_parameter", None),
                        "roles": ("role", None),
                        "common_attributes": ("common_attribute", None),
                        "exchange_plans": ("exchange_plan", None),
                        "selection_criteria": ("selection_criterion", None),
                        "event_subscriptions": ("event_subscription", None),
                        "scheduled_jobs": ("scheduled_job", None),
                        "bots": ("bot", None),
                        "functional_options": ("functional_option", None),
                        "functional_options_params": ("functional_option_parameter", None),
                        "defined_types": ("defined_type", None),
                        "settings_storages": ("settings_storage", None),
                        "common_commands": ("common", "common_command"),
                        "command_groups": ("common", "command_group"),
                        "common_forms": ("common", "common_form"),
                        "common_layouts": ("common_layout", None),
                        "common_pictures": ("common_picture", None),
                        "xdto_packages": ("xdto_package", None),
                        "web_services": ("web_service", None),
                        "http_services": ("http_service", None),
                        "ws_links": ("ws_reference", None),
                        "websocket_clients": ("websocket_client", None),
                        "integration_services": ("integration_service", None),
                        "style_elements": ("style_element", None),
                        "styles": ("style", None),
                    }
                    obj_type, subtype = create_map.get(key, ("common", None))
                    act_add = menu.addAction(self._plus_green_icon(), t("ctx_add"))
                    act_add.setShortcut("Ins")
                    act_add.triggered.connect(
                        lambda _=False, ot=obj_type, pg=str(meta.get("guid") or "").strip(), st=subtype: self._create_object_and_rename(ot, pg, st)
                    )
                    if menu.actions():
                        menu.exec(global_pos)
                    return
        if kind == "object":
            info = self.node_info_from_index(idx)
            if info and getattr(info, "guid", ""):
                act_open = menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), t("ctx_open"))
                act_open.triggered.connect(lambda: self._vm.on_open(info))
                act_open_new = menu.addAction(
                    self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder),
                    t("ctx_open_new"),
                )
                act_open_new.triggered.connect(lambda: self._vm.request_open_new(info))
                menu.addSeparator()

        if kind in ("group", "folder"):
            payload = meta.get("payload") if isinstance(meta, dict) else None
            if isinstance(payload, dict) and payload.get("menu") == "add_only":
                type_code = str(meta.get("type") or "").strip()
                if kind == "folder" and payload.get("auto"):
                    section_key = str(meta.get("name") or "").strip().lower()
                    section_create_map = {
                        "forms": "form",
                        "commands": "command",
                        "layouts": "layout",
                    }
                    type_code = section_create_map.get(section_key, "")
                    if section_key == "modules":
                        _this_guid = str(meta.get("guid") or "")
                        try:
                            db = self._vm._service.require_db() if self._vm else None
                            _mf_rows = db.table("manifest").select() if db is not None else []
                            _child_mods = [
                                r
                                for r in (_mf_rows or [])
                                if str(r.get("parent_guid") or "") == _this_guid and str(r.get("type") or "").lower() == "module"
                            ]
                        except Exception:
                            _child_mods = []
                        if _child_mods:
                            for _cm in _child_mods:
                                _cg = str(_cm.get("guid") or "")
                                _payload = _cm.get("payload") if isinstance(_cm.get("payload"), dict) else {}
                                _cn = technical_object_name(_cm.get("name"), payload=_payload)
                                act_m = menu.addAction(t("ctx_open_module") + f": {_cn}")
                                act_m.triggered.connect(lambda _=False, g=_cg, n=_cn: self._open_module_by_guid(g, n))
                        else:
                            menu.addAction(t("ctx_no_modules")).setEnabled(False)
                        menu.exec(global_pos)
                        return

                if type_code and type_code != "common":
                    if type_code == "constants":
                        act_form = menu.addAction(t("ctx_create_constants_form"))
                        act_form.triggered.connect(lambda _=False: self._vm.create_constants_form())
                        menu.addSeparator()
                    elif type_code in ("data_processor", "report"):
                        act_ext = menu.addAction(t("ctx_insert_external_processing"))
                        act_ext.triggered.connect(lambda _=False: self._vm.insert_external_processing_stub(type_code))
                        menu.addSeparator()
                    act_add = menu.addAction(self._plus_green_icon(), t("ctx_add"))
                    act_add.setShortcut("Ins")
                    pg = str(meta.get("guid") or "").strip()
                    act_add.triggered.connect(lambda _=False, ot=type_code, parent=pg: self._create_object_and_rename(ot, parent, None))
                    menu.exec(global_pos)
                    return
        if kind in ("root", "group", "folder"):
            create_opts = self._vm.create_options_for_node(meta)
            if create_opts:
                sub = menu.addMenu(self._plus_green_icon(), t("ctx_create"))
                for opt in create_opts:
                    if isinstance(opt, dict) and opt.get("submenu") and isinstance(opt.get("items"), list):
                        sub2 = sub.addMenu(self._plus_green_icon(), str(opt.get("submenu")))
                        for it in list(opt.get("items") or []):
                            if not isinstance(it, dict):
                                continue
                            label = str(it.get("title") or "Создать…")
                            o_kind = str(it.get("kind") or "object")
                            o_type = str(it.get("obj_type") or "")
                            o_subtype = str(it.get("subtype") or "").strip() or None
                            p_guid = str(it.get("parent_guid") or "")
                            if not o_type or not p_guid:
                                continue
                            act = sub2.addAction(self._plus_green_icon(), label)
                            act.triggered.connect(
                                lambda _=False, ot=o_type, pg=p_guid, st=o_subtype: self._create_object_and_rename(ot, pg, st)
                            )
                        continue
                    label = str(opt.get("title") or "Создать…")
                    o_kind = str(opt.get("kind") or "object")
                    o_type = str(opt.get("obj_type") or "")
                    o_subtype = str(opt.get("subtype") or "").strip() or None
                    p_guid = str(opt.get("parent_guid") or "")
                    if not o_type or not p_guid:
                        continue
                    if o_kind == "folder":
                        act = sub.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon), label)
                        act.triggered.connect(lambda _=False, ot=o_type, pg=p_guid: self._create_folder_and_rename(ot, pg))
                    else:
                        act = sub.addAction(self._plus_green_icon(), label)
                        act.triggered.connect(
                            lambda _=False, ot=o_type, pg=p_guid, st=o_subtype: self._create_object_and_rename(ot, pg, st)
                        )
                menu.addSeparator()
        guid = str(meta.get("guid") or "").strip()
        obj_type_ctx = str(meta.get("type") or meta.get("obj_type") or "").strip().lower()
        if kind == "object" and guid:
            if "module" in obj_type_ctx or obj_type_ctx in ("common_module",):
                act_open = menu.addAction(t("ctx_open_module"))
                payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
                module_name = technical_object_name(meta.get("name"), payload=payload)
                act_open.triggered.connect(lambda _=False, g=guid, n=module_name: self._open_module_by_guid(g, n))
                menu.addSeparator()
            elif obj_type_ctx in ("form", "common_form"):
                act_open = menu.addAction(t("ctx_open_form"))
                info_for_form = self.node_info_from_index(self.tree.currentIndex())
                act_open.triggered.connect(lambda _=False, i=info_for_form: self.open_object_tab(i))
                menu.addSeparator()
            elif obj_type_ctx in ("catalog", "document", "report", "register_accum", "register_info"):
                act_open = menu.addAction(t("ctx_open_object"))
                info_for_obj = self.node_info_from_index(self.tree.currentIndex())
                act_open.triggered.connect(lambda _=False, i=info_for_obj: self.open_object_tab(i))
                menu.addSeparator()

        can_rename = bool(guid) and bool(self._vm.can_rename(meta))
        can_delete = bool(guid) and bool(self._vm.can_delete(meta))
        if can_rename and kind in ("object", "folder"):
            act_rename = menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView), t("ctx_rename"))
            act_rename.setShortcut("F2")
            act_rename.triggered.connect(lambda: self.begin_inline_rename(guid))
        if can_delete and kind in ("object", "folder"):
            act_delete = menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon), t("ctx_delete"))
            act_delete.setShortcut("Del")
            act_delete.triggered.connect(lambda: self._vm.delete_object(meta))
        self._maybe_add_config_storage_submenu(menu, item, meta)
        if menu.actions():
            menu.exec(global_pos)
            return
        info = self.node_info_from_index(idx)
        self.treeContextMenuRequested.emit(kind, item, info, global_pos)

    def _create_object_and_rename(self, obj_type: str, parent_guid: str, subtype: str | None = None) -> None:
        if self._vm is None:
            return
        guid = self._vm.create_object_quick(obj_type, parent_guid, subtype)
        if not guid:
            return
        if (obj_type or "").strip().lower() in ("constants", "constant"):
            meta = self._vm.get_meta_by_guid(guid) if self._vm else None
            title = technical_object_name()
            if isinstance(meta, dict):
                title = technical_object_name(meta.get("name"), payload=meta.get("payload"))
            info = NodeInfo(kind="object", name=title, guid=guid, obj_type=obj_type)
            self.open_object_tab(info, force_new=False)
            return
        self.begin_inline_rename(guid)

    def _create_folder_and_rename(self, obj_type: str, parent_guid: str) -> None:
        if self._vm is None:
            return
        guid = self._vm.create_folder_quick(obj_type, parent_guid)
        if guid:
            self.begin_inline_rename(guid)

    def _current_meta(self) -> Optional[dict]:
        idx = self.tree.currentIndex()
        if not idx.isValid():
            return None
        item = self.tree_model.itemFromIndex(idx)
        if item is None:
            return None
        meta = item.data(self.ROLE_META) or {}
        return meta if isinstance(meta, dict) else None

    def _current_kind(self) -> str:
        idx = self.tree.currentIndex()
        if not idx.isValid():
            return ""
        item = self.tree_model.itemFromIndex(idx)
        if item is None:
            return ""
        return str(item.data(self.ROLE_KIND) or "")

    def _ctx_add_current(self) -> None:
        if self._vm is None:
            return
        meta = self._current_meta()
        kind = self._current_kind()
        if not meta:
            return
        if kind not in ("root", "group", "folder"):
            return
        obj_type = str(meta.get("type") or "").strip()
        parent_guid = str(meta.get("guid") or "").strip()
        if not obj_type or not parent_guid:
            return
        self._create_object_and_rename(obj_type, parent_guid)

    def _ctx_rename_current(self) -> None:
        if self._vm is None:
            return
        meta = self._current_meta()
        kind = self._current_kind()
        if not meta or kind not in ("object", "folder"):
            return
        if not self._vm.can_rename(meta):
            return
        guid = str(meta.get("guid") or "").strip()
        if guid:
            self.begin_inline_rename(guid)

    def _ctx_delete_current(self) -> None:
        if self._vm is None:
            return
        meta = self._current_meta()
        kind = self._current_kind()
        if not meta or kind not in ("object", "folder"):
            return
        if not self._vm.can_delete(meta):
            return
        self._vm.delete_object(meta)

    def _plus_green_icon(self) -> QIcon:
        ic = QIcon.fromTheme("list-add")
        if not ic.isNull():
            return ic
        size = 16
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#22C55E"))
        p.drawRoundedRect(size // 2 - 2, 2, 4, size - 4, 2, 2)
        p.drawRoundedRect(2, size // 2 - 2, size - 4, 4, 2, 2)
        p.end()
        return QIcon(pm)

    def begin_inline_rename(self, guid: str) -> None:
        guid = (guid or "").strip()
        if not guid:
            return
        item = self._find_item_by_guid(guid)
        if item is None:
            return
        meta = item.data(self.ROLE_META) or {}
        self._editing_old_text = str(meta.get("title") or item.text()) if isinstance(meta, dict) else item.text()
        self._editing_guid = guid
        item.setEditable(True)
        idx = item.index()
        self.tree.setCurrentIndex(idx)
        self.tree.scrollTo(idx)
        self.tree.setFocus(Qt.FocusReason.MouseFocusReason)

        def _start():
            self.tree.edit(idx)
            QTimer.singleShot(0, self._tune_inline_editor)
            QTimer.singleShot(0, _start)

    def _tune_inline_editor(self) -> None:
        ed = self.tree.findChild(QLineEdit)
        if not ed:
            return
        ed.setFrame(False)
        ed.setAutoFillBackground(True)
        pal = ed.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor("#5B5BD6"))
        pal.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        ed.setPalette(pal)
        ed.setStyleSheet("border:none; background:#5B5BD6; color:white; padding:0px; margin:0px;")
        ed.textEdited.connect(self._live_update_model_while_editing)

    def _live_update_model_while_editing(self, text: str) -> None:
        idx = self.tree.currentIndex()
        if not idx.isValid():
            return
        self.tree.model().setData(idx, text, Qt.ItemDataRole.EditRole)

    def _on_item_changed(self, item: QStandardItem) -> None:
        if not self._editing_guid:
            return
        meta = item.data(self.ROLE_META)
        if not isinstance(meta, dict):
            self._cleanup_editing_state(item)
            return
        guid = str(meta.get("guid") or "").strip()
        if guid != self._editing_guid:
            return
        new_title = (item.text() or "").strip()
        if not new_title:
            self._revert_rename(item, meta)
            return
        self._apply_rename(item, meta, guid, new_title)

    def _cleanup_editing_state(self, item: QStandardItem) -> None:
        item.setEditable(False)
        self._editing_guid = ""
        self._editing_old_text = ""

    def _revert_rename(self, item: QStandardItem, meta: dict) -> None:
        old_text = self._editing_old_text or str(meta.get("title") or meta.get("name") or "")
        self.tree_model.blockSignals(True)
        try:
            item.setText(old_text)
        finally:
            self.tree_model.blockSignals(False)
        self._cleanup_editing_state(item)

    def _apply_rename(self, item: QStandardItem, meta: dict, guid: str, new_title: str) -> None:
        meta["title"] = new_title
        item.setData(meta, self.ROLE_META)
        self._cleanup_editing_state(item)
        self.itemRenamed.emit(guid, new_title)

    def _on_close_editor(self, editor, hint):
        if not self._editing_guid:
            return
        idx = self.tree.currentIndex()
        if not idx.isValid():
            self._finish_inline_rename()
            return
        item = self.tree_model.itemFromIndex(idx)
        if item is None:
            self._finish_inline_rename()
            return
        meta = item.data(self.ROLE_META)
        if not isinstance(meta, dict):
            self._finish_inline_rename()
            return
        guid = str(meta.get("guid") or "").strip()
        if guid != self._editing_guid:
            self._finish_inline_rename()
            return
        new_title = (item.text() or "").strip()
        if not new_title:
            old_text = self._editing_old_text or str(meta.get("title") or meta.get("name") or "")
            item.setText(old_text)
            self._finish_inline_rename()
            return
        meta["title"] = new_title
        item.setData(meta, self.ROLE_META)
        self._finish_inline_rename()
        self.itemRenamed.emit(guid, new_title)

    def _finish_inline_rename(self):
        self._editing_guid = ""
        self._editing_old_text = ""
