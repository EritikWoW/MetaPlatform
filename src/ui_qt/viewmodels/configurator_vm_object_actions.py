from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.configurator.domain.default_schema import ensure_schema_defaults
from src.configurator.domain.metadata_defaults import ensure_payload_defaults
from src.ui_qt.i18n import t


class ConfiguratorVmObjectActionsMixin:
    def create_constants_form(self) -> None:
        """Create the auto-generated Constants form."""
        try:
            constants = [
                o
                for o in self._service.list_objects()
                if str(getattr(o, "obj_type", "") or "").lower() in ("constant",)
            ]
            if not constants:
                self._dialogs.show_info(t("info_title"), t("constants_form_no_constants"))
                return

            constants_folder_guid = ""
            for row in (self._service.require_db().table("manifest").select() or []):
                rtype = str(row.get("type") or "").strip().lower()
                rkind = str(row.get("kind") or "").strip().lower()
                if rtype == "constants" and rkind in ("group", "folder"):
                    constants_folder_guid = str(row.get("guid") or "")
                    break

            existing_forms = [
                row
                for row in (self._service.require_db().table("manifest").select() or [])
                if str(row.get("parent_guid") or "") == constants_folder_guid
                and str(row.get("type") or "").lower() in ("form", "constants_form")
            ]

            if existing_forms:
                self.openEditorRequested.emit(
                    type(
                        "NodeInfo",
                        (),
                        {
                            "kind": "object",
                            "name": t("constants_form_title"),
                            "guid": str(existing_forms[0].get("guid") or ""),
                            "obj_type": "form",
                        },
                    )()
                )
                return

            form_controls = []
            for const in constants:
                cname = str(getattr(const, "name", "") or "")
                ctitle = str(getattr(const, "title", "") or cname)
                payload = getattr(const, "payload", {}) or {}
                const_data = payload.get("constant") if isinstance(payload.get("constant"), dict) else {}
                dtype = str(const_data.get("data_type") or "string")

                form_controls.append({"type": "label", "text": ctitle or cname, "name": f"lbl_{cname}"})
                ctrl_type = {
                    "string": "input",
                    "number": "number_input",
                    "boolean": "checkbox",
                    "date": "date_input",
                }.get(dtype, "input")
                form_controls.append(
                    {
                        "type": ctrl_type,
                        "name": f"fld_{cname}",
                        "bind": cname,
                        "caption": ctitle or cname,
                    }
                )

            form_model = {
                "title": t("constants_form_title"),
                "form_type": "constants",
                "controls": form_controls,
                "data_source": "constants",
            }

            import uuid as _uuid

            form_guid = str(_uuid.uuid4())
            self._service.require_db().table("manifest").insert(
                {
                    "guid": form_guid,
                    "parent_guid": constants_folder_guid,
                    "kind": "object",
                    "type": "form",
                    "name": "ConstantsForm",
                    "title": t("constants_form_title"),
                    "payload": {"form_model": form_model},
                }
            )
            self._service._reload()
            self._dialogs.show_info(
                t("constants_form_title"),
                t("constants_form_created").format(n=len(constants)),
            )
        except Exception as e:
            self._dialogs.show_warning(t("dlg_error_title"), str(e))

    def insert_external_processing_stub(self, type_code: str) -> None:
        msg = t("stub_external_report") if type_code == "report" else t("stub_external_processor")
        self._dialogs.show_info(t("stub_title"), msg)

    def create_options_for_node(self, meta: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return available create options for a node meta."""
        kind = str(meta.get("kind") or "")
        parent_guid = str(meta.get("guid") or "").strip()
        type_code = str(meta.get("type") or "").strip()
        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}

        opts: List[Dict[str, Any]] = []

        if kind == "folder":
            if bool(payload.get("system") or payload.get("protected") or payload.get("seed") or payload.get("auto")):
                return []

        if kind == "root":
            groups = [o for o in self._service.list_objects() if o.kind == "group"]

            def _order(o: Any) -> int:
                p = o.payload if isinstance(o.payload, dict) else {}
                try:
                    return int(p.get("order") or 0)
                except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError):
                    return 0

            groups.sort(key=_order)
            for g in groups:
                g_type = str(getattr(g, "type", "") or "").strip()
                g_guid = str(getattr(g, "guid", "") or "").strip()
                g_title = str(getattr(g, "title", "") or getattr(g, "name", "") or g_type)
                if g_type and g_guid:
                    opts.append(
                        {
                            "kind": "object",
                            "title": f"{g_title}…",
                            "obj_type": g_type,
                            "parent_guid": g_guid,
                        }
                    )
            return opts

        if kind in ("group", "folder"):
            if type_code and parent_guid:
                if type_code == "common":
                    opts.append(
                        {
                            "submenu": t("menu_common"),
                            "items": [
                                {
                                    "kind": "object",
                                    "title": t("menu_common_module"),
                                    "obj_type": "common",
                                    "subtype": "common_module",
                                    "parent_guid": parent_guid,
                                },
                                {
                                    "kind": "object",
                                    "title": t("menu_common_form"),
                                    "obj_type": "common",
                                    "subtype": "common_form",
                                    "parent_guid": parent_guid,
                                },
                                {
                                    "kind": "object",
                                    "title": t("menu_command"),
                                    "obj_type": "common",
                                    "subtype": "common_command",
                                    "parent_guid": parent_guid,
                                },
                            ],
                        }
                    )

                opts.append(
                    {
                        "kind": "object",
                        "title": t("menu_create"),
                        "obj_type": type_code,
                        "parent_guid": parent_guid,
                    }
                )
                opts.append(
                    {
                        "kind": "folder",
                        "title": t("menu_create_folder"),
                        "obj_type": type_code,
                        "parent_guid": parent_guid,
                    }
                )
            return opts

        return opts

    @staticmethod
    def can_rename(meta: Dict[str, Any]) -> bool:
        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
        return not bool(payload.get("system") or payload.get("protected") or payload.get("seed"))

    def can_delete(self, meta: Dict[str, Any]) -> bool:
        return self.can_rename(meta)

    def create_folder_quick(self, obj_type: str, parent_guid: str) -> Optional[str]:
        obj_type = (obj_type or "").strip()
        parent_guid = (parent_guid or "").strip()
        if not obj_type or not parent_guid:
            return None

        try:
            objs = self._service.list_objects()
            used = set()
            for o in objs:
                if o.kind == "folder" and o.parent_guid == parent_guid:
                    used.add((o.title or "").strip().lower())

            n = 1
            while True:
                title = t("folder_default").format(n=n)
                if title.lower() not in used:
                    break
                n += 1

            name = f"folder{n}"
            mo = self._service.add_object(
                obj_type=obj_type,
                name=name,
                title=title,
                parent_guid=parent_guid,
                payload={"user_created": True, "folder": True},
                kind="folder",
            )
            self.reload()
            self.statusChanged.emit(t("status_created"))
            return mo.guid
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            self._dialogs.show_warning(t("dlg_error_title"), t("err_create_folder_failed").format(error=e))
            return None

    def on_item_renamed(self, guid: str, new_title: str) -> None:
        guid = (guid or "").strip()
        new_title = (new_title or "").strip()
        if not guid or not new_title:
            return
        try:
            meta = self.get_meta_by_guid(guid)
            if isinstance(meta, dict) and str(meta.get("type") or "") in ("form", "common_form"):
                payload = self._payload_for_guid(guid)
                fm_raw = payload.get("form_model")
                if isinstance(fm_raw, dict):
                    fm2 = dict(fm_raw)
                    fm2["title"] = str(new_title)
                    fm2["name"] = str(new_title)
                    p2 = dict(payload)
                    p2["form_model"] = fm2
                    self._service.update_object_fields(guid, title=new_title, payload=p2)
                else:
                    self._service.rename_object(guid, new_title)
            else:
                self._service.rename_object(guid, new_title)
            self.statusChanged.emit(t("status_renamed"))
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            self._dialogs.show_warning(t("dlg_error_title"), t("err_rename_failed").format(error=e))
        finally:
            self.reload()

    def create_common_module(self, name: str, title: str = "") -> str:
        from src.configurator.persistence.db_seed import GUID_FOLDER_COMMON_MODULES

        obj_type = "common_module"
        parent_guid = GUID_FOLDER_COMMON_MODULES
        name = name.strip() or "NewModule"
        title = title.strip() or name

        mo = self._service.add_object(
            obj_type=obj_type,
            name=name,
            title=title,
            parent_guid=parent_guid,
            payload={"user_created": True},
        )
        self.reload()
        self.statusChanged.emit(t("status_created"))
        return mo.guid

    def create_object_quick(self, obj_type: str, parent_guid: str, subtype: str | None = None) -> Optional[str]:
        obj_type = (obj_type or "").strip()
        parent_guid = (parent_guid or "").strip()
        if not obj_type or not parent_guid:
            return None

        try:
            objs = self._service.list_objects()
            title, name = self._service.next_auto_name_with_subtype(obj_type, subtype, objs)
            base_payload = {"user_created": True, **({"subtype": subtype} if subtype else {})}
            payload = ensure_payload_defaults(payload=base_payload, obj_type=obj_type, subtype=subtype)
            payload = ensure_schema_defaults(payload=payload, obj_type=obj_type, subtype=subtype)

            if obj_type in ("form", "common_form"):
                try:
                    from src.configurator.domain.form_model import default_form_model

                    payload = dict(payload)
                    payload.setdefault("form_model", default_form_model(form_name=str(title or name)).to_dict())
                    payload.setdefault("form_module", "")
                except Exception:
                    pass

            mo = self._service.add_object(
                obj_type=obj_type,
                name=name,
                title=title,
                parent_guid=parent_guid,
                payload=payload,
            )
            self.reload()
            self.statusChanged.emit(t("status_created"))
            return mo.guid
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            self._dialogs.show_warning(t("dlg_error_title"), t("err_create_object_failed").format(error=e))
            return None

    def update_object_payload(self, guid: str, payload_patch: Dict[str, Any]) -> None:
        guid = (guid or "").strip()
        if not guid:
            return
        try:
            self.save_object_payload_patch(guid, payload_patch or {}, reload=False)
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            self._dialogs.show_warning(t("dlg_error_title"), t("err_save_failed").format(error=e))
