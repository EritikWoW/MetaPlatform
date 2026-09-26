from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, Dict, List, Tuple

from src.configurator.application.manifest_editor import ManifestEditorState
from src.ui_qt.i18n import get_lang, t


_SCHEMA_SOURCE_KEYS: Dict[str, Tuple[str, ...]] = {
    "attributes": ("requisites", "attributes"),
    "values": ("enum_values", "values"),
}


class ConfiguratorVmEditorActionsMixin:
    def on_save(self) -> bool:
        """Handle UI save command."""
        try:
            schema_state = getattr(self, "_schema_editor_state", ManifestEditorState())
            schema_context = getattr(self, "_schema_editor_context", {})
            if schema_context and schema_state.current:
                if schema_state.is_dirty:
                    owner_guid, owner_payload = self._apply_schema_editor_state()
                    if not self.save_object_payload(owner_guid, owner_payload, reload=True):
                        return False
                    schema_state.original = deepcopy(schema_state.current)
                    schema_state.issues = []
                self.editorStateChanged.emit(schema_state)
                self.statusChanged.emit(t("status_saved"))
                self._deploy_schema_bg()
                return True

            st = self._editor.state
            if st.is_dirty:
                self._editor.apply()
                self.reload()
            self.editorStateChanged.emit(self._editor.state)
            self.statusChanged.emit(t("status_saved") if hasattr(t, "__call__") else "Saved")
            self._deploy_schema_bg()
            return True
        except RuntimeError as e:
            self.show_warning(t("dlg_error_title"), str(e))
            return False
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.statusChanged.emit("")
            return False

    def _deploy_schema_bg(self) -> None:
        """Idempotent schema deployment after save."""
        try:
            report = dict(self._service.deploy_schema() or {})
            created = int(report.get("created") or 0)
            if created:
                self.statusChanged.emit(t("status_schema_deployed").format(n=created))
        except Exception:
            pass

    def on_refresh(self) -> None:
        self.reload()

    def on_check(self) -> None:
        """Validate the configuration and report issues."""
        issues: List[str] = []

        try:
            objs = self._service.list_objects()
        except Exception as e:
            self._dialogs.show_info(t("check_title"), f"{t('check_load_error')}: {e}")
            return

        import re

        name_re = re.compile(r"^[A-Za-zА-ЯҐЄІЇа-яґєії_][A-Za-zА-ЯҐЄІЇа-яґєії0-9_]*$")
        seen_names: Dict[str, List[str]] = {}
        for o in objs:
            kind = str(getattr(o, "kind", "") or "")
            if kind != "object":
                continue
            name = str(getattr(o, "name", "") or "").strip()
            obj_type = str(getattr(o, "type", "") or "").strip()

            if name and not name_re.match(name):
                issues.append(t("check_invalid_name").format(name=name, type=obj_type))
            key = f"{obj_type}:{name.lower()}"
            seen_names.setdefault(key, []).append(name)

        for key, names in seen_names.items():
            if len(names) > 1:
                obj_type, _ = key.split(":", 1)
                issues.append(
                    t("check_duplicate_name").format(name=names[0], type=obj_type, count=len(names))
                )

        for o in objs:
            if str(getattr(o, "kind", "") or "") != "object":
                continue
            title = str(getattr(o, "title", "") or "").strip()
            name = str(getattr(o, "name", "") or "").strip()
            if not title and name:
                issues.append(t("check_missing_title").format(name=name))

        try:
            report = dict(self._service.deploy_schema() or {})
            for err in list(report.get("errors") or []):
                issues.append(f"{t('check_schema_error')}: {err}")
        except Exception as e:
            issues.append(f"{t('check_schema_error')}: {e}")

        if not issues:
            self._dialogs.show_info(t("check_title"), t("check_ok"))
        else:
            msg = "\n".join(f"• {i}" for i in issues[:30])
            if len(issues) > 30:
                msg += f"\n… {t('check_more').format(n=len(issues)-30)}"
            self._dialogs.show_info(
                t("check_title"),
                f"{t('check_found').format(n=len(issues))}\n\n{msg}",
            )

    def on_search(self, text: str) -> None:
        self._search = (text or "").strip().lower()
        # Search is a projection of the already loaded manifest. Rebuild the
        # tree immediately instead of only storing the query and waiting for a
        # full reload, otherwise the field appears to do nothing.
        snapshot = list(getattr(self, "_objects_snapshot", []) or [])
        if snapshot:
            self._populate_tree(snapshot)

    def on_subsystem_filter(self, guid: str) -> None:
        self._subsystem_filter_guid = (guid or "").strip()

    def on_select(self, info: Any) -> None:
        """Prepare properties and editor state for the selected node."""
        guid = str(getattr(info, "guid", "") or "")
        name = str(getattr(info, "name", "") or "")
        obj_type = str(getattr(info, "obj_type", "") or "")
        kind = str(getattr(info, "kind", "") or "")

        rows: List[Tuple[str, str]] = [
            (t("prop_guid"), guid),
            (t("prop_name"), name),
            (t("prop_type"), obj_type),
        ]
        self.propertiesRowsChanged.emit(rows)

        if guid:
            try:
                if kind == "schema":
                    meta = self.get_meta_by_guid(guid)
                    state = self._load_schema_editor(meta)
                    self.editorStateChanged.emit(state)
                    return

                self._clear_schema_editor()
                o = self._objects_by_guid.get(guid)
                if o is not None:
                    full_payload = {}
                    try:
                        full_payload = self._manifest_payload_for_guid(guid)
                    except Exception:
                        full_payload = {}
                    if isinstance(full_payload, dict) and full_payload:
                        current_payload = o.payload if isinstance(getattr(o, "payload", None), dict) else {}
                        if full_payload != current_payload:
                            try:
                                o = replace(o, payload=dict(full_payload))
                            except Exception:
                                try:
                                    setattr(o, "payload", dict(full_payload))
                                except Exception:
                                    pass
                    st: ManifestEditorState = self._editor.load(o)
                    self.editorStateChanged.emit(st)
                else:
                    self.editorStateChanged.emit(ManifestEditorState())
            except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError):
                return
        else:
            try:
                self._clear_schema_editor()
                self.editorStateChanged.emit(ManifestEditorState())
            except Exception:
                pass

    def on_editor_field_changed(self, field: str, value: Any) -> None:
        try:
            if self._schema_editor_active():
                state = self._schema_editor_state
                current = deepcopy(state.current or {})
                field = str(field or "").strip()
                if field in {"name", "title"}:
                    current[field] = value
                    state.current = current
                    state.issues = []
                    self.editorStateChanged.emit(state)
                return
            self._editor.set_field(str(field or "").strip(), value)
            self._editor.validate()
            self.editorStateChanged.emit(self._editor.state)
        except (RuntimeError, ValueError, TypeError, AttributeError, KeyError):
            return

    def on_editor_payload_changed(self, payload: Any) -> None:
        try:
            if not isinstance(payload, dict):
                return
            if self._schema_editor_active():
                state = self._schema_editor_state
                current = deepcopy(state.current or {})
                current["payload"] = deepcopy(payload)
                state.current = current
                state.issues = []
                self.editorStateChanged.emit(state)
                return
            self._editor.set_field("payload", payload)
            self._editor.validate()
            self.editorStateChanged.emit(self._editor.state)
        except (RuntimeError, ValueError, TypeError, AttributeError, KeyError):
            return

    def on_editor_revert(self) -> None:
        try:
            if self._schema_editor_active():
                state = self._schema_editor_state
                state.current = deepcopy(state.original or {})
                state.issues = []
                self.editorStateChanged.emit(state)
                return
            self._editor.revert()
            self.editorStateChanged.emit(self._editor.state)
        except (RuntimeError, ValueError, TypeError, AttributeError, KeyError):
            return

    def on_open(self, info: Any) -> None:
        kind = str(getattr(info, "kind", "") or "")
        if kind != "object":
            return
        self.openEditorRequested.emit(info)

    def request_open_new(self, info: Any) -> None:
        kind = str(getattr(info, "kind", "") or "")
        if kind != "object":
            return
        self.openEditorNewRequested.emit(info)

    def _schema_editor_active(self) -> bool:
        return bool(
            getattr(self, "_schema_editor_context", {})
            and getattr(self, "_schema_editor_state", ManifestEditorState()).current
        )

    def _clear_schema_editor(self) -> None:
        self._schema_editor_state = ManifestEditorState()
        self._schema_editor_context = {}

    @staticmethod
    def _schema_owner_guid(virtual_guid: str) -> str:
        parts = str(virtual_guid or "").split(":", 3)
        return parts[1].strip() if len(parts) >= 3 and parts[0] == "virtual" else ""

    @staticmethod
    def _schema_item_matches(candidate: Any, snapshot: Dict[str, Any]) -> bool:
        if not isinstance(candidate, dict):
            return False
        expected_imported = snapshot.get("imported") if isinstance(snapshot.get("imported"), dict) else {}
        actual_imported = candidate.get("imported") if isinstance(candidate.get("imported"), dict) else {}
        expected_uuid = str(expected_imported.get("src_uuid") or "").strip()
        actual_uuid = str(actual_imported.get("src_uuid") or "").strip()
        if expected_uuid and actual_uuid:
            return expected_uuid == actual_uuid
        return str(candidate.get("name") or "").strip() == str(snapshot.get("name") or "").strip()

    @staticmethod
    def _localized_schema_title(value: Any, fallback: str = "") -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for lang in (get_lang(), "uk", "en", "ru"):
                text = str(value.get(lang) or "").strip()
                if text:
                    return text
            for item in value.values():
                text = str(item or "").strip()
                if text:
                    return text
        return str(fallback or "")

    def _find_schema_editor_context(self, meta: Any) -> Dict[str, Any]:
        if not isinstance(meta, dict):
            return {}
        virtual_guid = str(meta.get("guid") or "").strip()
        owner_guid = self._schema_owner_guid(virtual_guid)
        tree_payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
        snapshot = tree_payload.get("schema_item") if isinstance(tree_payload.get("schema_item"), dict) else {}
        section = str(tree_payload.get("section") or "").strip()
        schema_kind = str(tree_payload.get("schema_item_kind") or "").strip()
        if not owner_guid or not snapshot or not section:
            return {}

        owner_payload = deepcopy(self._payload_for_guid(owner_guid))
        if schema_kind == "column":
            part_name = str(tree_payload.get("tabular_part") or "").strip()
            for part_index, part in enumerate(owner_payload.get("tabular_parts") or []):
                if not isinstance(part, dict) or str(part.get("name") or "").strip() != part_name:
                    continue
                for item_index, item in enumerate(part.get("columns") or []):
                    if self._schema_item_matches(item, snapshot):
                        return {
                            "owner_guid": owner_guid,
                            "owner_payload": owner_payload,
                            "source_key": "tabular_parts",
                            "part_index": part_index,
                            "item_index": item_index,
                            "schema_kind": schema_kind,
                            "raw_item": deepcopy(item),
                        }
            return {}

        source_keys = ("tabular_parts",) if schema_kind == "tabular_part" else _SCHEMA_SOURCE_KEYS.get(section, (section,))
        for source_key in source_keys:
            for item_index, item in enumerate(owner_payload.get(source_key) or []):
                if self._schema_item_matches(item, snapshot):
                    return {
                        "owner_guid": owner_guid,
                        "owner_payload": owner_payload,
                        "source_key": source_key,
                        "item_index": item_index,
                        "schema_kind": schema_kind,
                        "raw_item": deepcopy(item),
                    }
        return {}

    def _load_schema_editor(self, meta: Any) -> ManifestEditorState:
        context = self._find_schema_editor_context(meta)
        if not context:
            self._clear_schema_editor()
            return self._schema_editor_state

        raw_item = deepcopy(context["raw_item"])
        name = str(raw_item.get("name") or "").strip()
        title = self._localized_schema_title(raw_item.get("title"), name)
        payload = deepcopy(raw_item)
        imported = payload.pop("imported", None)
        payload.pop("name", None)
        payload.pop("title", None)

        string_qualifiers = payload.pop("string_qualifiers", None)
        if isinstance(string_qualifiers, dict) and "length" in string_qualifiers:
            payload["string_length"] = string_qualifiers.get("length")
        number_qualifiers = payload.pop("number_qualifiers", None)
        if isinstance(number_qualifiers, dict):
            if "digits" in number_qualifiers:
                payload["number_digits"] = number_qualifiers.get("digits")
            if "fraction_digits" in number_qualifiers:
                payload["number_fraction_digits"] = number_qualifiers.get("fraction_digits")
        if isinstance(imported, dict) and imported.get("raw_type"):
            payload["source_type"] = imported.get("raw_type")

        schema_kind = str(context.get("schema_kind") or "")
        editor_type = "schema_tabular_part" if schema_kind == "tabular_part" else "schema_requisite"
        current = {
            "guid": str(meta.get("guid") or "") if isinstance(meta, dict) else "",
            "type": editor_type,
            "name": name,
            "title": title,
            "payload": payload,
            "kind": "schema",
            "parent_guid": str(context.get("owner_guid") or ""),
        }
        state = ManifestEditorState(
            guid=str(current["guid"]),
            original=deepcopy(current),
            current=deepcopy(current),
            issues=[],
        )
        self._schema_editor_context = context
        self._schema_editor_state = state
        return state

    @staticmethod
    def _coerce_schema_value(value: Any, previous: Any) -> Any:
        if isinstance(previous, bool):
            return bool(value)
        if isinstance(previous, int) and not isinstance(previous, bool):
            try:
                return int(value)
            except (TypeError, ValueError):
                return previous
        if isinstance(previous, float):
            try:
                return float(value)
            except (TypeError, ValueError):
                return previous
        return value

    def _schema_item_from_state(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        current = deepcopy(self._schema_editor_state.current or {})
        updated = deepcopy(raw_item)
        updated["name"] = str(current.get("name") or "").strip()

        title = str(current.get("title") or "").strip()
        old_title = updated.get("title")
        if isinstance(old_title, dict):
            localized = deepcopy(old_title)
            localized[get_lang()] = title
            updated["title"] = localized
        elif old_title is not None:
            updated["title"] = title
        elif title:
            updated["title"] = {get_lang(): title}

        payload = deepcopy(current.get("payload") if isinstance(current.get("payload"), dict) else {})
        payload.pop("source_type", None)
        string_length = payload.pop("string_length", None)
        number_digits = payload.pop("number_digits", None)
        number_fraction_digits = payload.pop("number_fraction_digits", None)
        for key, value in payload.items():
            updated[key] = self._coerce_schema_value(value, updated.get(key))

        if string_length is not None:
            qualifiers = deepcopy(updated.get("string_qualifiers") or {})
            qualifiers["length"] = self._coerce_schema_value(string_length, qualifiers.get("length", 0))
            updated["string_qualifiers"] = qualifiers
        if number_digits is not None or number_fraction_digits is not None:
            qualifiers = deepcopy(updated.get("number_qualifiers") or {})
            if number_digits is not None:
                qualifiers["digits"] = self._coerce_schema_value(number_digits, qualifiers.get("digits", 0))
            if number_fraction_digits is not None:
                qualifiers["fraction_digits"] = self._coerce_schema_value(
                    number_fraction_digits, qualifiers.get("fraction_digits", 0)
                )
            updated["number_qualifiers"] = qualifiers
        return updated

    def _apply_schema_editor_state(self) -> Tuple[str, Dict[str, Any]]:
        context = self._schema_editor_context
        owner_guid = str(context.get("owner_guid") or "").strip()
        owner_payload = deepcopy(self._payload_for_guid(owner_guid) or context.get("owner_payload") or {})
        source_key = str(context.get("source_key") or "")
        item_index = int(context.get("item_index", -1))
        if not owner_guid or not source_key or item_index < 0:
            raise RuntimeError("Schema item owner is not available")

        source_items = deepcopy(owner_payload.get(source_key) or [])
        if str(context.get("schema_kind") or "") == "column":
            part_index = int(context.get("part_index", -1))
            if part_index < 0 or part_index >= len(source_items):
                raise RuntimeError("Tabular part is not available")
            part = deepcopy(source_items[part_index])
            columns = deepcopy(part.get("columns") or [])
            if item_index >= len(columns):
                raise RuntimeError("Tabular part column is not available")
            columns[item_index] = self._schema_item_from_state(columns[item_index])
            part["columns"] = columns
            source_items[part_index] = part
        else:
            if item_index >= len(source_items):
                raise RuntimeError("Schema item is not available")
            source_items[item_index] = self._schema_item_from_state(source_items[item_index])
        owner_payload[source_key] = source_items
        return owner_guid, owner_payload
