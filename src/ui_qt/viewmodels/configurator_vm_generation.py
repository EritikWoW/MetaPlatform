from __future__ import annotations

from typing import Any, Dict

from src.configurator.domain.metadata_defaults import ensure_payload_defaults
from src.configurator.domain.default_schema import ensure_schema_defaults
from src.configurator.domain.form_templates import build_list_form_model, build_object_form_model
from src.configurator.persistence.manifest_io import sys_object_folder_guid


class ConfiguratorVmGenerationMixin:

    def generate_for_object(
        self,
        guid: str,
        obj_type: str,
        *,
        generate_schema: bool = True,
        generate_forms: bool = True,
        generate_commands: bool = True,
        overwrite: bool = False,
    ) -> None:
        """Generate MVP templates for an existing object.

        Parameters:
            guid: Owner object GUID.
            obj_type: Owner object type (catalog/document).
            generate_schema: Apply default schema templates (attributes/tabular_parts).
            generate_forms: Create/update typical forms (list/object).
            overwrite: If True, templates overwrite existing values; otherwise only fill missing.
        """

        guid = (guid or "").strip()
        obj_type = (obj_type or "").strip()
        if not guid or not obj_type:
            return

        try:
            objs = self._service.list_objects()
            owner = next((x for x in objs if str(getattr(x, "guid", "")) == guid), None)
            if owner is None:
                self._dialogs.show_warning(t("dlg_error_title"), "Объект не найден")
                return

            payload = owner.payload if isinstance(getattr(owner, "payload", None), dict) else {}
            subtype = str(payload.get("subtype") or "").strip() or None
            new_payload = dict(payload)

            if generate_schema:
                if overwrite:
                    from src.configurator.domain.default_schema import (
                        default_attributes_for_object,
                        default_tabular_parts_for_object,
                    )

                    attr_def = default_attributes_for_object(obj_type=obj_type, subtype=subtype)
                    tp_def = default_tabular_parts_for_object(obj_type=obj_type, subtype=subtype)
                    if attr_def:
                        new_payload["attributes"] = attr_def
                    if tp_def:
                        new_payload["tabular_parts"] = tp_def
                else:
                    new_payload = ensure_schema_defaults(payload=new_payload, obj_type=obj_type, subtype=subtype)

            if new_payload != payload:
                self._service.update_object_payload(guid, new_payload)

            if generate_forms and obj_type in ("catalog", "document"):
                self._generate_typical_forms_for_owner(
                    owner_guid=guid,
                    owner_type=obj_type,
                    owner_title=str(getattr(owner, "title", "") or getattr(owner, "name", "") or ""),
                    owner_payload=new_payload,
                    overwrite=overwrite,
                )

            if generate_commands:
                self._generate_typical_commands_for_owner(
                    owner_guid=guid,
                    owner_type=obj_type,
                    owner_payload=new_payload,
                    overwrite=overwrite,
                )

            self.reload()
            self.statusChanged.emit(t("status_generated"))
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            self._dialogs.show_warning(t("dlg_error_title"), t("err_generate_failed").format(error=e))


    def generate_preview_for_object(
        self,
        guid: str,
        obj_type: str,
        *,
        generate_schema: bool = True,
        generate_forms: bool = True,
        generate_commands: bool = True,
        overwrite: bool = False,
    ) -> str:
        """Return a human-readable preview of what generation would do.

        This method MUST NOT modify storage or manifest.
        """

        guid = (guid or "").strip()
        obj_type = (obj_type or "").strip()
        if not guid or not obj_type:
            return ""

        try:
            objs = self._service.list_objects()
            owner = next((x for x in objs if str(getattr(x, "guid", "")) == guid), None)
            if owner is None:
                return t("dlg_generate_preview_not_found")

            payload = owner.payload if isinstance(getattr(owner, "payload", None), dict) else {}
            subtype = str(payload.get("subtype") or "").strip() or None

            lines: list[str] = []
            title = str(getattr(owner, "title", "") or getattr(owner, "name", "") or guid)
            lines.append(f"{t('dlg_generate_preview_for')} {title}")

            # ---------------- schema ----------------
            if generate_schema:
                if overwrite:
                    from src.configurator.domain.default_schema import (
                        default_attributes_for_object,
                        default_tabular_parts_for_object,
                    )

                    attr_new = default_attributes_for_object(obj_type=obj_type, subtype=subtype) or []
                    tp_new = default_tabular_parts_for_object(obj_type=obj_type, subtype=subtype) or []
                    attr_old = payload.get("attributes") if isinstance(payload.get("attributes"), list) else []
                    tp_old = payload.get("tabular_parts") if isinstance(payload.get("tabular_parts"), list) else []

                    lines.append("")
                    lines.append(t("dlg_generate_preview_schema"))
                    lines.append(f"- {t('dlg_generate_preview_overwrite')}")
                    lines.append(
                        f"- {t('dlg_generate_preview_attributes')}: {len(attr_old)} -> {len(attr_new)}"
                    )
                    lines.append(
                        f"- {t('dlg_generate_preview_tabular_parts')}: {len(tp_old)} -> {len(tp_new)}"
                    )
                else:
                    # Merge: compute what's missing
                    from src.configurator.domain.default_schema import (
                        default_attributes_for_object,
                        default_tabular_parts_for_object,
                    )

                    attr_def = default_attributes_for_object(obj_type=obj_type, subtype=subtype) or []
                    tp_def = default_tabular_parts_for_object(obj_type=obj_type, subtype=subtype) or []
                    attr_old = payload.get("attributes") if isinstance(payload.get("attributes"), list) else []
                    tp_old = payload.get("tabular_parts") if isinstance(payload.get("tabular_parts"), list) else []

                    old_attr_names = {str(x.get("name") or "").strip() for x in attr_old if isinstance(x, dict)}
                    add_attrs = [
                        x
                        for x in attr_def
                        if isinstance(x, dict) and str(x.get("name") or "").strip() and str(x.get("name")).strip() not in old_attr_names
                    ]

                    old_tp_names = {str(x.get("name") or "").strip() for x in tp_old if isinstance(x, dict)}
                    add_tps = [
                        x for x in tp_def if isinstance(x, dict) and str(x.get("name") or "").strip() not in old_tp_names
                    ]

                    lines.append("")
                    lines.append(t("dlg_generate_preview_schema"))
                    lines.append(f"- {t('dlg_generate_preview_merge')}")
                    lines.append(
                        f"- {t('dlg_generate_preview_attributes_add')}: {len(add_attrs)}"
                        + (" (" + ", ".join([str(a.get('name')) for a in add_attrs][:8]) + ")" if add_attrs else "")
                    )
                    lines.append(
                        f"- {t('dlg_generate_preview_tabular_parts_add')}: {len(add_tps)}"
                        + (" (" + ", ".join([str(tp.get('name')) for tp in add_tps][:8]) + ")" if add_tps else "")
                    )

            # ---------------- forms ----------------
            if generate_forms and obj_type in ("catalog", "document"):
                lines.append("")
                lines.append(t("dlg_generate_preview_forms"))

                try:
                    forms_folder_guid = sys_object_folder_guid(parent_guid=guid, section_key="forms")
                    children = [
                        x
                        for x in objs
                        if (x.kind == "object" and str(x.parent_guid) == str(forms_folder_guid) and str(x.type) == "form")
                    ]

                    def find_by_subtype(st: str):
                        for x in children:
                            p = x.payload if isinstance(getattr(x, "payload", None), dict) else {}
                            if str(p.get("subtype") or "") == st:
                                return x
                        return None

                    list_form = find_by_subtype("list_form")
                    obj_form = find_by_subtype("object_form")

                    def status_for(form_obj, subtype_label: str) -> str:
                        if form_obj is None:
                            return f"- {subtype_label}: {t('dlg_generate_preview_will_create')}"
                        p = form_obj.payload if isinstance(getattr(form_obj, "payload", None), dict) else {}
                        has_model = isinstance(p.get("form_model"), dict) and bool(p.get("form_model"))
                        if overwrite:
                            return f"- {subtype_label}: {t('dlg_generate_preview_will_overwrite')}"
                        if not has_model:
                            return f"- {subtype_label}: {t('dlg_generate_preview_will_fill')}"
                        return f"- {subtype_label}: {t('dlg_generate_preview_no_change')}"

                    lines.append(status_for(list_form, t("dlg_generate_preview_list_form")))
                    lines.append(status_for(obj_form, t("dlg_generate_preview_object_form")))
                except Exception:
                    lines.append(f"- {t('dlg_generate_preview_unavailable')}")

            # ---------------- commands ----------------
            if generate_commands:
                lines.append("")
                lines.append(t("dlg_generate_preview_commands"))
                try:
                    from src.configurator.domain.default_commands import default_commands_for_context

                    owner_type_norm = str(obj_type or "").strip().lower()
                    defaults: list[dict] = []
                    seen: set[str] = set()
                    for ctx in ("list_form", "object_form"):
                        for d in default_commands_for_context(obj_type=owner_type_norm, context=ctx):
                            code = str(d.get("code") or "").strip()
                            if not code or code in seen:
                                continue
                            defaults.append(d)
                            seen.add(code)

                    commands_folder_guid = sys_object_folder_guid(parent_guid=guid, section_key="commands")
                    existing = [
                        x
                        for x in objs
                        if (
                            x.kind == "object"
                            and str(x.parent_guid) == str(commands_folder_guid)
                            and str(x.type) in ("command", "common_command")
                        )
                    ]
                    existing_codes = {
                        str((x.payload or {}).get("code") or "").strip()
                        for x in existing
                        if isinstance(getattr(x, "payload", None), dict)
                    }
                    missing = [
                        str(d.get("code") or "").strip()
                        for d in defaults
                        if str(d.get("code") or "").strip() and str(d.get("code") or "").strip() not in existing_codes
                    ]
                    if overwrite:
                        lines.append(f"- {t('dlg_generate_preview_overwrite')}")
                        lines.append(f"- {t('dlg_generate_preview_commands_add')}: {len(defaults)}")
                    else:
                        lines.append(f"- {t('dlg_generate_preview_merge')}")
                        lines.append(
                            f"- {t('dlg_generate_preview_commands_add')}: {len(missing)}"
                            + (" (" + ", ".join(missing[:8]) + ")" if missing else "")
                        )
                except Exception:
                    lines.append(f"- {t('dlg_generate_preview_unavailable')}")

            return "\n".join([x for x in lines if x is not None])
        except Exception:
            return ""


    def _generate_typical_forms_for_owner(
        self,
        *,
        owner_guid: str,
        owner_type: str,
        owner_title: str,
        owner_payload: Dict[str, Any],
        overwrite: bool,
    ) -> None:
        """Create or update list/object forms for a given owner."""

        try:
            forms_folder_guid = sys_object_folder_guid(parent_guid=owner_guid, section_key="forms")
            objs = self._service.list_objects()
            children = [
                x
                for x in objs
                if (x.kind == "object" and str(x.parent_guid) == str(forms_folder_guid) and str(x.type) == "form")
            ]

            def find_by_subtype(st: str) -> Any:
                for x in children:
                    p = x.payload if isinstance(getattr(x, "payload", None), dict) else {}
                    if str(p.get("subtype") or "") == st:
                        return x
                return None

            # List form
            list_form = find_by_subtype("list_form")
            owner_type_norm = str(owner_type or "").strip().lower()
            from src.configurator.domain.default_commands import default_commands_for_context
            list_model = build_list_form_model(
                form_name="ListForm",
                owner_title=str(owner_title or ""),
                attributes=owner_payload.get("attributes"),
                commands=default_commands_for_context(obj_type=owner_type_norm, context="list_form"),
            )
            if list_form is None:
                list_payload = {
                    "user_created": True,
                    "subtype": "list_form",
                    "owner_guid": owner_guid,
                    "form_model": list_model,
                    "form_module": "",
                }
                self._service.add_object(
                    obj_type="form",
                    name="list_form1",
                    title=t("form_list_title"),
                    parent_guid=forms_folder_guid,
                    payload=list_payload,
                )
            else:
                p = list_form.payload if isinstance(getattr(list_form, "payload", None), dict) else {}
                if overwrite or (not isinstance(p.get("form_model"), dict)) or not p.get("form_model"):
                    p2 = dict(p)
                    p2["form_model"] = list_model
                    p2.setdefault("form_module", "")
                    self._service.update_object_payload(str(list_form.guid), p2)

            # Object form
            obj_form = find_by_subtype("object_form")
            obj_model = build_object_form_model(
                form_name="ObjectForm",
                owner_title=str(owner_title or ""),
                attributes=owner_payload.get("attributes"),
                commands=default_commands_for_context(obj_type=owner_type_norm, context="object_form"),
            )
            if obj_form is None:
                obj_payload = {
                    "user_created": True,
                    "subtype": "object_form",
                    "owner_guid": owner_guid,
                    "form_model": obj_model,
                    "form_module": "",
                }
                self._service.add_object(
                    obj_type="form",
                    name="object_form1",
                    title=t("form_object_title"),
                    parent_guid=forms_folder_guid,
                    payload=obj_payload,
                )
            else:
                p = obj_form.payload if isinstance(getattr(obj_form, "payload", None), dict) else {}
                if overwrite or (not isinstance(p.get("form_model"), dict)) or not p.get("form_model"):
                    p2 = dict(p)
                    p2["form_model"] = obj_model
                    p2.setdefault("form_module", "")
                    self._service.update_object_payload(str(obj_form.guid), p2)
        except Exception:
            # Generation must never break the workflow.
            return


    def _generate_typical_commands_for_owner(
        self,
        *,
        owner_guid: str,
        owner_type: str,
        owner_payload: Dict[str, Any],
        overwrite: bool,
    ) -> None:
        """Create or update typical command objects under owner/commands.

        Strategy:
            - Generate a union of list_form + object_form default commands.
            - If overwrite=True: overwrite payload fields of existing commands (by code).
            - If overwrite=False: create missing commands only.
        """

        try:
            from src.configurator.domain.default_commands import default_commands_for_context

            owner_type_norm = str(owner_type or "").strip().lower()
            # Union by code (preserve deterministic order: list then object)
            defaults: list[dict] = []
            seen: set[str] = set()
            for ctx in ("list_form", "object_form"):
                for d in default_commands_for_context(obj_type=owner_type_norm, context=ctx):
                    code = str(d.get("code") or "").strip()
                    if not code or code in seen:
                        continue
                    defaults.append(d)
                    seen.add(code)

            if not defaults:
                return

            commands_folder_guid = sys_object_folder_guid(parent_guid=owner_guid, section_key="commands")
            objs = self._service.list_objects()
            existing = [
                x
                for x in objs
                if (
                    x.kind == "object"
                    and str(x.parent_guid) == str(commands_folder_guid)
                    and str(x.type) in ("command", "common_command")
                )
            ]

            by_code: dict[str, Any] = {}
            for x in existing:
                p = x.payload if isinstance(getattr(x, "payload", None), dict) else {}
                code = str(p.get("code") or "").strip()
                if code and code not in by_code:
                    by_code[code] = x

            for d in defaults:
                code = str(d.get("code") or "").strip()
                if not code:
                    continue
                title = d.get("title")
                title_uk = code
                if isinstance(title, dict):
                    title_uk = str(title.get("uk") or title.get("en") or code)
                elif title:
                    title_uk = str(title)

                # Keep names deterministic
                name = f"cmd_{code.lower()}"

                if code in by_code:
                    if not overwrite:
                        continue
                    obj = by_code[code]
                    p_old = obj.payload if isinstance(getattr(obj, "payload", None), dict) else {}
                    p_new = dict(p_old)
                    p_new.update(d)
                    p_new.setdefault("owner_guid", owner_guid)
                    self._service.update_object_payload(str(obj.guid), p_new)
                else:
                    payload = dict(d)
                    payload.setdefault("owner_guid", owner_guid)
                    self._service.add_object(
                        obj_type="command",
                        name=name,
                        title=title_uk,
                        parent_guid=commands_folder_guid,
                        payload=payload,
                    )
        except Exception:
            return
