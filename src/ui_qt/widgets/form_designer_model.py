from __future__ import annotations

import json
import logging
import time
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox, QTreeWidgetItem

from src.configurator.domain.default_commands import default_commands_for_context
from src.configurator.domain.default_requisites import default_requisites_for_object
from src.configurator.domain.form_model import FormModel, FormNode, default_form_model
from src.configurator.domain.form_templates import build_list_form_model, build_object_form_model
from src.platform.logging_setup import get_logger
from src.infra.onec.module_transform import sanitize_imported_module_text
from src.ui_qt.i18n import get_lang, t


_log = get_logger("ui.form_designer")


class FormDesignerModelMixin:
    def _current_module_text(self) -> str:
        editor = getattr(self, "_module_editor", None)
        if editor is not None:
            try:
                return str(editor.toPlainText() or "")
            except Exception:
                return str(getattr(self, "_module_text", "") or "")
        return str(getattr(self, "_module_text", "") or "")

    def _infer_form_kind(self, *, form_title: str, payload: dict[str, Any]) -> str:
        subtype = str(payload.get("subtype") or "").strip().lower()
        if subtype in {"list_form", "choice_form"}:
            return "list_form"
        if subtype == "object_form":
            return "object_form"

        raw_name = " ".join(
            part for part in (str(form_title or "").strip(), str(payload.get("name") or "").strip()) if part
        ).lower()
        list_markers = ("list", "choice", "спис", "выбор", "вибір")
        if any(marker in raw_name for marker in list_markers):
            return "list_form"
        return "object_form"

    def _owner_form_fields(self, owner_payload: dict[str, Any], *, obj_type: str) -> list[dict[str, Any]]:
        source = owner_payload.get("requisites")
        if not isinstance(source, list) or not source:
            source = default_requisites_for_object(obj_type=obj_type)

        fields: list[dict[str, Any]] = []
        for item in source:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("code") or "").strip()
            if not name:
                continue
            fields.append(
                {
                    "name": name,
                    "binding": str(item.get("binding") or name).strip(),
                    "title": item.get("title") or name,
                    "type": str(item.get("type") or item.get("data_type") or "string").strip() or "string",
                    "required": bool(item.get("required") or False),
                    "comment": str(item.get("comment") or ""),
                }
            )
        return fields

    def _build_generated_form_model(self, *, form_title: str, payload: dict[str, Any]) -> FormModel | None:
        owner = self._resolve_owner_meta()
        if not owner:
            return None

        owner_payload = owner.get("payload") if isinstance(owner.get("payload"), dict) else {}
        obj_type = str(owner.get("type") or "").strip().lower()
        owner_title = str(owner.get("title") or owner.get("name") or form_title or "Form").strip()
        form_kind = self._infer_form_kind(form_title=form_title, payload=payload)
        fields = self._owner_form_fields(owner_payload, obj_type=obj_type)
        commands = default_commands_for_context(obj_type=obj_type, context=form_kind)

        try:
            if form_kind == "list_form":
                return FormModel.from_dict(
                    build_list_form_model(
                        form_name=str(form_title or "Form"),
                        owner_title=owner_title,
                        attributes=fields,
                        commands=commands,
                    )
                )
            return FormModel.from_dict(
                build_object_form_model(
                    form_name=str(form_title or "Form"),
                    owner_title=owner_title,
                    attributes=fields,
                    commands=commands,
                )
            )
        except Exception:
            return None

    def _load_model(self, *, form_title: str, payload: dict[str, Any]) -> FormModel:
        """Load FormModel from payload."""

        candidates = [
            payload.get("form_model"),
            payload.get("model"),
            payload.get("designer_model"),
            payload.get("form"),
        ]

        for raw in candidates:
            try:
                if isinstance(raw, dict):
                    return FormModel.from_dict(raw)
                if isinstance(raw, str):
                    source = raw.strip()
                    if not source:
                        continue
                    obj = json.loads(source)
                    if isinstance(obj, dict):
                        return FormModel.from_dict(obj)
            except Exception:
                continue

        asset_candidates = [
            str(payload.get("form_model_ref") or "").strip(),
            str(payload.get("model_ref") or "").strip(),
            str(payload.get("designer_model_ref") or "").strip(),
            str(payload.get("form_ref") or "").strip(),
        ]
        vm = getattr(self, "_vm", None)
        if vm is not None:
            get_text_asset = getattr(vm, "get_text_asset", None)
            if callable(get_text_asset):
                for asset_key in asset_candidates:
                    if not asset_key:
                        continue
                    try:
                        text, _mime, _resolved = get_text_asset(asset_key)
                    except Exception:
                        continue
                    source = str(text or "").strip()
                    if not source:
                        continue
                    try:
                        obj = json.loads(source)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        return FormModel.from_dict(obj)

        generated = self._build_generated_form_model(form_title=form_title, payload=payload)
        if generated is not None:
            return generated

        return default_form_model(form_name=str(form_title or "Form"))

    def _load_form_module_text(self, payload: dict[str, Any]) -> str:
        """Load form module text from payload or compatibility asset path."""

        payload = dict(payload or {})
        direct = payload.get("form_module")
        if isinstance(direct, str) and direct:
            return sanitize_imported_module_text(direct)
        legacy = payload.get("module")
        if isinstance(legacy, str) and legacy:
            return sanitize_imported_module_text(legacy)
        if isinstance(legacy, dict):
            for key in ("text", "source", "code", "module_text", "content"):
                raw_text = legacy.get(key)
                if isinstance(raw_text, str) and raw_text:
                    return sanitize_imported_module_text(raw_text)

        asset_key = ""
        module_payload = payload.get("module")
        if isinstance(module_payload, dict):
            asset_key = str(module_payload.get("asset_key") or "").strip()
        if not asset_key:
            for key in ("form_module_ref", "module_asset_key", "module_ref", "form_module_asset_key"):
                asset_key = str(payload.get(key) or "").strip()
                if asset_key:
                    break

        vm = getattr(self, "_vm", None)
        form_guid = str(getattr(self, "_form_guid", "") or "").strip()
        if not asset_key and vm is not None and form_guid:
            resolve_for_owner = getattr(vm, "resolve_module_asset_key_for_owner", None)
            if callable(resolve_for_owner):
                try:
                    asset_key = str(resolve_for_owner(form_guid) or "").strip()
                except Exception:
                    asset_key = ""
                if asset_key:
                    payload["module"] = {"asset_key": asset_key, "mime": "text/plain"}
                    self._payload = dict(getattr(self, "_payload", {}) or {})
                    self._payload["module"] = dict(payload["module"])

        if not asset_key or vm is None:
            return ""

        get_text_asset = getattr(vm, "get_text_asset", None)
        if not callable(get_text_asset):
            return ""
        try:
            text, _mime, resolved_key = get_text_asset(asset_key)
            resolved_key = str(resolved_key or asset_key).strip()
            if resolved_key:
                payload["module"] = {"asset_key": resolved_key, "mime": "text/plain"}
                self._payload = dict(getattr(self, "_payload", {}) or {})
                self._payload["module"] = dict(payload["module"])
            return sanitize_imported_module_text(str(text or ""))
        except Exception:
            return ""

    def _merge_payload_from_storage_latest(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Merge payload with the latest snapshot from configuration storage."""

        if self._storage is None or self._lock_target is None:
            return payload
        try:
            if getattr(self._storage, "connection", None) is not None and self._storage.connection() is None:
                return payload
            snap = self._storage.get_latest(lock_key=self._lock_target.lock_key)
            if not isinstance(snap, dict):
                return payload
            patch = snap.get("payload")
            if not isinstance(patch, dict) or not patch:
                return payload
            out = dict(payload or {})
            out.update(patch)
            return out
        except Exception:
            return payload

    def _payload_from_persistent_sources(self) -> dict[str, Any]:
        """Return the latest persisted payload visible to the designer."""

        payload = dict(getattr(self, "_payload", {}) or {})
        vm = getattr(self, "_vm", None)
        guid = str(getattr(self, "_form_guid", "") or "").strip()
        if vm is not None and guid:
            get_meta_by_guid = getattr(vm, "get_meta_by_guid", None)
            if callable(get_meta_by_guid):
                try:
                    meta = get_meta_by_guid(guid)
                except Exception:
                    meta = None
                meta_payload = meta.get("payload") if isinstance(meta, dict) and isinstance(meta.get("payload"), dict) else None
                if isinstance(meta_payload, dict):
                    payload = dict(meta_payload)
        return self._merge_payload_from_storage_latest(payload)

    def _save(self) -> bool:
        if not self._is_edit_enabled():
            QMessageBox.warning(self, t("dlg_error_title"), t("form_storage_readonly"))
            return False

        started_at = time.perf_counter()
        form_model = self._model.to_dict()
        module_text = self._current_module_text()
        patch = {
            "form_model": form_model,
            "form_module": module_text,
        }

        direct_saved = False
        form_saved = False
        module_saved = not bool(getattr(self, "_module_dirty", False))
        form_ref = str(getattr(self, "_payload", {}).get("form_model_ref") or "").strip()
        vm = getattr(self, "_vm", None)
        guid = str(getattr(self, "_form_guid", "") or "").strip()
        _log.info(
            "form_designer.save.start guid=%s has_form_ref=%s module_dirty=%s dirty=%s",
            guid,
            bool(form_ref),
            bool(getattr(self, "_module_dirty", False)),
            bool(getattr(self, "_dirty", False)),
        )

        save_asset_fn = getattr(vm, "save_externalized_payload_asset", None)
        save_patch_fn = getattr(vm, "save_object_payload_patch", None)
        if guid and form_ref and callable(save_asset_fn):
            asset_payload = dict(getattr(self, "_payload", {}) or {})
            asset_payload["form_model_ref"] = form_ref
            asset_payload["form_model"] = form_model
            if module_saved:
                asset_payload["form_module"] = module_text
            form_saved = bool(
                save_asset_fn(
                    guid,
                    asset_payload,
                    key="form_model",
                    reload=False,
                )
            )
            direct_saved = form_saved
            if form_saved:
                self._payload = dict(asset_payload)
                self._payload.pop("form_model", None)
                _log.info(
                    "form_designer.save_form_asset guid=%s ref=%s took=%.3fs",
                    guid,
                    form_ref,
                    time.perf_counter() - started_at,
                )
            else:
                _log.info(
                    "form_designer.save.abort guid=%s stage=form_asset total=%.3fs",
                    guid,
                    time.perf_counter() - started_at,
                )
                return False
        if direct_saved and not module_saved and callable(save_patch_fn):
            module_saved = bool(
                save_patch_fn(
                    guid,
                    {"form_module": module_text},
                    reload=False,
                )
            )
            if module_saved:
                self._payload["form_module"] = module_text
                _log.info(
                    "form_designer.save_form_module_patch guid=%s took=%.3fs",
                    guid,
                    time.perf_counter() - started_at,
                )
            else:
                _log.info(
                    "form_designer.save_form_module_patch_failed guid=%s took=%.3fs",
                    guid,
                    time.perf_counter() - started_at,
                )
                return False

        if not direct_saved:
            _log.info(
                "form_designer.save_fallback_emit guid=%s keys=%s",
                guid,
                sorted(patch.keys()),
            )
            if guid and callable(save_patch_fn):
                form_saved = bool(save_patch_fn(guid, patch, reload=False))
                module_saved = form_saved
                if form_saved:
                    self._payload.update(patch)
            else:
                self.saveRequested.emit(patch)
                form_saved = True
                module_saved = True

        if not (form_saved and module_saved):
            return False

        if self._storage is not None and self._lock_target is not None:
            try:
                if getattr(self._storage, "connection", None) is None or self._storage.connection() is not None:
                    lk = self._lock_target.lock_key
                    if self._storage.is_lock_held_by_me(lock_key=lk, user_id="SYSTEM"):
                        from src.configurator.persistence.object_locks import parse_lock_key

                        parsed = parse_lock_key(lk)
                        snapshot = {
                            "guid": str(getattr(self, "_form_guid", "") or ""),
                            "title": str(getattr(self, "_form_title", "") or self._model.title or ""),
                            "component": {
                                "component_type": str(parsed.component_type) if parsed is not None else "FormModule",
                                "component_id": str(parsed.component_id) if parsed is not None else "-",
                            },
                            "payload": patch,
                        }
                        if hasattr(self._storage, "commit"):
                            self._storage.commit(lock_key=lk, payload=snapshot, message="Form save", user_id="SYSTEM")
            except Exception:
                pass

        if form_saved and module_saved:
            self._module_text = module_text
            self._saved_module_text = module_text
            self._module_dirty = False
            self._set_dirty(False)
            if direct_saved:
                try:
                    QTimer.singleShot(0, self._refresh_from_sources)
                except Exception:
                    pass
            _log.info(
                "form_designer.save.done guid=%s mode=%s total=%.3fs",
                guid,
                "direct" if direct_saved else "fallback",
                time.perf_counter() - started_at,
            )
            return True
        return False

    def save(self) -> bool:
        """Persist the current designer draft for global IDE save actions."""

        return self._save()

    def is_dirty(self) -> bool:
        return bool(getattr(self, "_dirty", False))

    def confirm_close(self) -> bool:
        if not self.is_dirty():
            return True
        res = QMessageBox.question(
            self,
            t("dlg_unsaved_title"),
            t("dlg_unsaved_text"),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if res == QMessageBox.StandardButton.Save:
            return bool(self._save())
        if res == QMessageBox.StandardButton.Discard:
            self._module_dirty = False
            self._set_dirty(False)
            return True
        return False

    def _on_module_changed(self) -> None:
        if self._ui_guard:
            return
        self._module_dirty = self._current_module_text() != str(getattr(self, "_saved_module_text", "") or "")
        self._set_dirty(True)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self.confirm_close():
            event.ignore()
            return

        try:
            self._clear_form_node_clipboard()
        except Exception:
            pass

        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        try:
            key = event.key()
            mods = event.modifiers()
            if key == Qt.Key.Key_Escape:
                self._dispatch_command("Close")
                event.accept()
                return
            if key == Qt.Key.Key_F5:
                self._dispatch_command("Refresh")
                event.accept()
                return
            if key == Qt.Key.Key_S and (mods & Qt.KeyboardModifier.ControlModifier):
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self._dispatch_command("SaveAndClose")
                else:
                    self._dispatch_command("Save")
                event.accept()
                return
        except Exception:
            pass
        super().keyPressEvent(event)

    def _dispatch_command(self, code: str) -> None:
        raw = str(code or "").strip()
        if not raw:
            return

        norm = raw.lower()
        if norm in ("close", "closeform", "form.close"):
            self.close()
            return
        if norm in ("save", "form.save"):
            self._save()
            return
        if norm in ("saveandclose", "save_close", "form.saveandclose"):
            if self._save():
                self.close()
            return
        if norm in ("refresh", "form.refresh"):
            self._refresh_from_sources()
            return

        try:
            QMessageBox.information(self, t("dlg_error_title"), t("info_not_implemented") + f" ({raw})")
        except Exception:
            pass

    def _refresh_from_sources(self) -> None:
        try:
            selected_id = ""
            try:
                current = self._current_node()
                selected_id = str(getattr(current, "id", "") or "").strip()
            except Exception:
                selected_id = ""

            payload = self._payload_from_persistent_sources()
            self._payload = dict(payload or {})
            imported = self._payload.get("imported") if isinstance(self._payload.get("imported"), dict) else {}
            self._is_onec_imported = str(imported.get("source") or "").strip().lower() == "1c"
            self._form_meta_cache = None
            self._forms_folder_meta_cache = None
            self._owner_meta_cache = None
            self._available_requisites_cache = None
            self._model = self._load_model(form_title=self._form_title, payload=payload)
            self._module_text = self._load_form_module_text(payload)
            self._saved_module_text = self._module_text
            self._module_dirty = False
            module_editor = getattr(self, "_module_editor", None)
            if module_editor is not None:
                self._ui_guard = True
                try:
                    module_editor.setPlainText(self._module_text)
                finally:
                    self._ui_guard = False
            self._reload_requisites_panel()
            self._rebuild_tree(keep_selected_id=selected_id or self._model.root.id)
            self._update_window_frames()
            self._refresh_design_surface()
            self._render_preview()
            self._set_dirty(False)
        except Exception:
            logging.getLogger(__name__).exception("Form refresh failed")

    def reload_from_vm(self) -> None:
        self._refresh_from_sources()

    def _maybe_auto_checkout(self) -> None:
        if self._storage is None or self._lock_target is None:
            return
        try:
            if getattr(self._storage, "connection", None) is not None and self._storage.connection() is None:
                return
            lk = self._lock_target.lock_key
            if self._storage.is_lock_held_by_me(lock_key=lk, user_id="SYSTEM"):
                return
            from src.configurator.persistence.object_locks import parse_lock_key

            parsed = parse_lock_key(lk)
            if parsed is None:
                return
            self._storage.checkout(
                object_type=parsed.object_type,
                object_id=parsed.object_id,
                component_type=parsed.component_type,
                component_id=parsed.component_id,
                comment="Auto checkout (Form Designer)",
                user_id="SYSTEM",
            )
        except Exception:
            return

    def _is_edit_enabled(self) -> bool:
        if self._storage is None or self._lock_target is None:
            return True
        try:
            if self._storage.connection() is None:
                return True
            return bool(self._storage.is_lock_held_by_me(lock_key=self._lock_target.lock_key, user_id="SYSTEM"))
        except Exception:
            return False

    def _apply_edit_guard(self) -> None:
        enabled = self._is_edit_enabled()
        widgets = [
            getattr(self, "_btn_delete", None),
            getattr(self, "_btn_save", None),
            getattr(self, "tree", None),
            getattr(self, "requisites", None),
            getattr(self, "canvas", None),
            getattr(self, "_ed_name", None),
            getattr(self, "_ed_title", None),
            getattr(self, "_ed_binding", None),
            getattr(self, "_cb_open_mode", None),
            getattr(self, "_cb_window_lock_mode", None),
            getattr(self, "_cb_layout", None),
            getattr(self, "_sp_grid_cols", None),
            getattr(self, "_cb_group_anchor", None),
            getattr(self, "_sp_canvas_w", None),
            getattr(self, "_sp_canvas_h", None),
            getattr(self, "_sp_x", None),
            getattr(self, "_sp_y", None),
            getattr(self, "_sp_w", None),
            getattr(self, "_sp_h", None),
            getattr(self, "_sp_row", None),
            getattr(self, "_sp_col", None),
            getattr(self, "_sp_rowspan", None),
            getattr(self, "_sp_colspan", None),
            getattr(self, "_tbl_columns", None),
            getattr(self, "_module_editor", None),
        ]

        for widget in widgets:
            if widget is None:
                continue
            try:
                widget.setEnabled(enabled)
            except Exception:
                pass

        window_lock = getattr(self, "_cb_window_lock_mode", None)
        open_mode = getattr(self, "_cb_open_mode", None)
        if window_lock is not None and open_mode is not None:
            try:
                window_lock.setEnabled(enabled and str(open_mode.currentData() or "auto") == "window")
            except Exception:
                pass

        lbl = getattr(self, "_lbl_mode", None)
        if lbl is not None:
            if enabled:
                lbl.setText(t("form_mode_edit"))
            else:
                who = ""
                try:
                    if self._storage is not None and self._lock_target is not None:
                        info = self._storage.get_lock_info(lock_key=self._lock_target.lock_key)
                        if isinstance(info, dict):
                            who = str(info.get("locked_by") or "")
                except Exception:
                    who = ""
                lbl.setText(t("form_mode_readonly").format(user=who or "?"))

    def _resolve_owner_meta(self) -> dict[str, Any] | None:
        cached_owner = getattr(self, "_owner_meta_cache", None)
        if isinstance(cached_owner, dict):
            return cached_owner

        cached_form = getattr(self, "_form_meta_cache", None)
        if not isinstance(cached_form, dict):
            try:
                cached_form = self._vm.get_meta_by_guid(self._form_guid)
            except Exception:
                cached_form = None
            if isinstance(cached_form, dict):
                self._form_meta_cache = cached_form
        if not isinstance(cached_form, dict):
            return None

        try:
            forms_folder_guid = str(cached_form.get("parent_guid") or "").strip()
        except Exception:
            return None
        if not forms_folder_guid:
            return None

        cached_forms_folder = getattr(self, "_forms_folder_meta_cache", None)
        if not isinstance(cached_forms_folder, dict):
            try:
                cached_forms_folder = self._vm.get_meta_by_guid(forms_folder_guid)
            except Exception:
                cached_forms_folder = None
            if isinstance(cached_forms_folder, dict):
                self._forms_folder_meta_cache = cached_forms_folder
        if not isinstance(cached_forms_folder, dict):
            return None

        try:
            owner_guid = str(cached_forms_folder.get("parent_guid") or "").strip()
        except Exception:
            return None
        if not owner_guid:
            return None

        cached_owner = getattr(self, "_owner_meta_cache", None)
        if isinstance(cached_owner, dict):
            return cached_owner
        try:
            owner_meta = self._vm.get_meta_by_guid(owner_guid)
        except Exception:
            return None
        if isinstance(owner_meta, dict):
            self._owner_meta_cache = owner_meta
            return owner_meta
        return None

    def _available_requisites(self) -> list[dict[str, Any]]:
        cached = getattr(self, "_available_requisites_cache", None)
        if isinstance(cached, list):
            return list(cached)

        owner = self._resolve_owner_meta()
        if not owner:
            return []

        payload = owner.get("payload") if isinstance(owner.get("payload"), dict) else {}
        reqs = payload.get("requisites")
        if isinstance(reqs, list) and reqs:
            out: list[dict[str, Any]] = []
            for source in reqs:
                if not isinstance(source, dict):
                    continue
                code = str(source.get("code") or source.get("name") or "").strip()
                if not code:
                    continue
                item = dict(source)
                item["code"] = code
                item.setdefault("name", code)
                item.setdefault("binding", code)
                out.append(item)
            for source_part in payload.get("tabular_parts") or []:
                if not isinstance(source_part, dict):
                    continue
                code = str(source_part.get("code") or source_part.get("name") or "").strip()
                if not code:
                    continue
                columns: list[dict[str, Any]] = []
                for source_column in source_part.get("columns") or []:
                    if not isinstance(source_column, dict):
                        continue
                    column_code = str(source_column.get("code") or source_column.get("name") or "").strip()
                    if not column_code:
                        continue
                    column = dict(source_column)
                    column["code"] = column_code
                    column.setdefault("name", column_code)
                    column.setdefault("binding", f"{code}.{column_code}")
                    columns.append(column)
                part = dict(source_part)
                part.update({
                    "code": code,
                    "name": str(source_part.get("name") or code),
                    "binding": str(source_part.get("binding") or code),
                    "type": "table",
                    "tabular_part": True,
                    "columns": columns,
                })
                out.append(part)
            self._available_requisites_cache = list(out)
            return out

        obj_type = str(owner.get("type") or "").strip().lower()
        try:
            out = default_requisites_for_object(obj_type=obj_type)
            self._available_requisites_cache = list(out)
            return out
        except Exception:
            return []

    def _requisite_title(self, req: dict[str, Any]) -> str:
        title = req.get("title")
        if isinstance(title, dict):
            lang = get_lang()
            return str(title.get(lang) or title.get("uk") or title.get("en") or req.get("code") or "").strip()
        if isinstance(title, str) and title.strip():
            return title.strip()
        return str(req.get("code") or "").strip()

    def _owner_technical_name(self) -> str:
        owner = self._resolve_owner_meta() or {}
        payload = owner.get("payload") if isinstance(owner.get("payload"), dict) else {}
        metadata_ref = str(payload.get("metadata_ref") or owner.get("metadata_ref") or "").strip()
        if "." in metadata_ref:
            return metadata_ref.rsplit(".", 1)[-1].strip()
        return str(owner.get("name") or owner.get("title") or self._form_title or "Object").strip()

    def _owner_type_caption(self, *, reference: bool = False) -> str:
        owner = self._resolve_owner_meta() or {}
        obj_type = str(owner.get("type") or "").strip().lower()
        lang = get_lang()
        if lang == "uk":
            prefixes = {
                "catalog": ("ДовідникОб'єкт", "ДовідникПосилання"),
                "document": ("ДокументОб'єкт", "ДокументПосилання"),
                "enumeration": ("Перерахування", "ПерерахуванняПосилання"),
                "data_processor": ("ОбробкаОб'єкт", "ОбробкаПосилання"),
                "report": ("ЗвітОб'єкт", "ЗвітПосилання"),
            }
        else:
            prefixes = {
                "catalog": ("CatalogObject", "CatalogRef"),
                "document": ("DocumentObject", "DocumentRef"),
                "enumeration": ("Enumeration", "EnumerationRef"),
                "data_processor": ("DataProcessorObject", "DataProcessorRef"),
                "report": ("ReportObject", "ReportRef"),
            }
        object_prefix, ref_prefix = prefixes.get(obj_type, ("MetadataObject", "MetadataRef"))
        return f"{ref_prefix if reference else object_prefix}.{self._owner_technical_name()}"

    def _display_requisite_type(
        self,
        req: dict[str, Any],
        *,
        tabular_part: str = "",
    ) -> str:
        req_type = str(req.get("type") or req.get("data_type") or "").strip().lower()
        raw_type = str((req.get("imported") or {}).get("raw_type") or "").strip()
        ref_name = str(req.get("ref_name") or "").strip()
        lang = get_lang()

        if bool(req.get("tabular_part")) or req_type in {"table", "tabular_part", "table_part"}:
            prefix = "ДокументТабличнаЧастина" if lang == "uk" else "DocumentTabularPart"
            name = str(req.get("code") or req.get("name") or tabular_part or "Rows").strip()
            return f"({prefix}.{self._owner_technical_name()}.{name})"

        scalar = {
            "uk": {
                "string": "Рядок",
                "number": "Число",
                "integer": "Число",
                "int": "Число",
                "float": "Число",
                "decimal": "Число",
                "bool": "Булеве",
                "boolean": "Булеве",
                "date": "Дата",
                "datetime": "Дата",
                "time": "Дата",
                "uuid": "УнікальнийІдентифікатор",
                "guid": "УнікальнийІдентифікатор",
                "any_ref": "ДовільнеПосилання",
            },
            "en": {
                "string": "String",
                "number": "Number",
                "integer": "Number",
                "int": "Number",
                "float": "Number",
                "decimal": "Number",
                "bool": "Boolean",
                "boolean": "Boolean",
                "date": "Date",
                "datetime": "Date",
                "time": "Date",
                "uuid": "UUID",
                "guid": "UUID",
                "any_ref": "AnyRef",
            },
        }
        if req_type in scalar[lang if lang in scalar else "en"]:
            return scalar[lang if lang in scalar else "en"][req_type]

        raw_family = raw_type.removeprefix("cfg:").split(".", 1)[0]
        raw_name = raw_type.split(".", 1)[1].strip() if "." in raw_type else ref_name
        if not raw_name:
            raw_name = ref_name
        family_names = {
            "uk": {
                "CatalogRef": "ДовідникПосилання",
                "DocumentRef": "ДокументПосилання",
                "EnumRef": "ПерерахуванняПосилання",
                "ChartOfCharacteristicTypesRef": "ПланВидівХарактеристикПосилання",
                "ChartOfAccountsRef": "ПланРахунківПосилання",
                "ChartOfCalculationTypesRef": "ПланВидівРозрахункуПосилання",
                "BusinessProcessRef": "БізнесПроцесПосилання",
                "TaskRef": "ЗавданняПосилання",
                "Characteristic": "Характеристика",
            },
            "en": {
                "CatalogRef": "CatalogRef",
                "DocumentRef": "DocumentRef",
                "EnumRef": "EnumerationRef",
                "ChartOfCharacteristicTypesRef": "ChartOfCharacteristicTypesRef",
                "ChartOfAccountsRef": "ChartOfAccountsRef",
                "ChartOfCalculationTypesRef": "ChartOfCalculationTypesRef",
                "BusinessProcessRef": "BusinessProcessRef",
                "TaskRef": "TaskRef",
                "Characteristic": "Characteristic",
            },
        }
        localized_family = family_names[lang if lang in family_names else "en"].get(raw_family)
        if localized_family and raw_name:
            return f"{localized_family}.{raw_name}"
        if req_type in {"ref", "reference"} and ref_name:
            generic = "Посилання" if lang == "uk" else "Ref"
            return f"{generic}.{ref_name}"
        return str(req.get("type") or req.get("data_type") or "")

    def _form_only_requisites(self, owner_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        owner_bindings: set[str] = set()
        for req in owner_items:
            code = str(req.get("binding") or req.get("code") or req.get("name") or "").strip()
            if code:
                owner_bindings.add(code.casefold())
            for column in req.get("columns") or []:
                if not isinstance(column, dict):
                    continue
                binding = str(column.get("binding") or "").strip()
                if binding:
                    owner_bindings.add(binding.casefold())

        control_types = {
            "TextBox": "string",
            "TextArea": "string",
            "NumberBox": "number",
            "DateBox": "datetime",
            "CheckBox": "bool",
            "ComboBox": "ref",
            "Table": "table",
            "TablePanel": "table",
        }
        result: list[dict[str, Any]] = []
        seen: set[str] = set()

        def visit(node: FormNode) -> None:
            binding = str(node.binding or "").strip()
            key = binding.casefold()
            if binding and key not in owner_bindings and key not in seen and node.type in control_types:
                seen.add(key)
                result.append(
                    {
                        "code": binding,
                        "name": binding,
                        "binding": binding,
                        "title": str(node.title or node.name or binding),
                        "type": control_types[node.type],
                        "form_only": True,
                    }
                )
            for child in node.children:
                visit(child)

        visit(self._model.root)
        return result

    @staticmethod
    def _set_requisite_check_state(item: QTreeWidgetItem, checked: bool) -> None:
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(1, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _reload_requisites_panel(self) -> None:
        try:
            self.requisites.blockSignals(True)
            self.requisites.clear()
        except Exception:
            return
        try:
            owner_items = self._available_requisites()
            stored_always = (self._model.root.props or {}).get("use_always_requisites")
            has_stored_always = isinstance(stored_always, list)
            always_bindings = {
                str(value or "").strip().casefold()
                for value in (stored_always or [])
                if str(value or "").strip()
            }

            root_item = QTreeWidgetItem(
                [t("form_object_root"), "", f"({self._owner_type_caption()})"]
            )
            root_font = root_item.font(0)
            root_font.setBold(True)
            root_item.setFont(0, root_font)
            root_item.setData(0, Qt.ItemDataRole.UserRole, {"kind": "object_root"})
            self.requisites.addTopLevelItem(root_item)

            owner = self._resolve_owner_meta() or {}
            obj_type = str(owner.get("type") or "").strip().lower()
            if obj_type in {"catalog", "document"}:
                reference_req = {
                    "code": "Reference",
                    "name": "Reference",
                    "title": {"uk": "Посилання", "en": "Reference"},
                    "type": "ref",
                    "system": True,
                    "pseudo": True,
                }
                reference_item = QTreeWidgetItem(
                    [self._requisite_title(reference_req), "", self._owner_type_caption(reference=True)]
                )
                reference_item.setData(0, Qt.ItemDataRole.UserRole, reference_req)
                checked = not has_stored_always or "reference" in always_bindings
                self._set_requisite_check_state(reference_item, checked)
                root_item.addChild(reference_item)

            system_items = [req for req in owner_items if bool(req.get("system")) and not req.get("tabular_part")]
            custom_items = [req for req in owner_items if not bool(req.get("system")) and not req.get("tabular_part")]
            table_items = [req for req in owner_items if bool(req.get("tabular_part"))]
            custom_titles = {self._requisite_title(req).casefold() for req in custom_items if self._requisite_title(req)}
            system_items = [req for req in system_items if self._requisite_title(req).casefold() not in custom_titles]

            movement_inserted = False
            for req in [*system_items, *custom_items, *table_items]:
                code = str(req.get("code") or req.get("name") or "").strip()
                if not code:
                    continue
                binding = str(req.get("binding") or code).strip()
                it = QTreeWidgetItem(
                    [self._requisite_title(req) or code, "", self._display_requisite_type(req)]
                )
                it.setData(0, Qt.ItemDataRole.UserRole, req)
                checked = (not has_stored_always and not bool(req.get("form_only"))) or binding.casefold() in always_bindings
                self._set_requisite_check_state(it, checked)
                root_item.addChild(it)

                if bool(req.get("tabular_part")):
                    for column in req.get("columns") or []:
                        if not isinstance(column, dict):
                            continue
                        column_code = str(column.get("code") or column.get("name") or "").strip()
                        if not column_code:
                            continue
                        column_binding = str(column.get("binding") or f"{code}.{column_code}").strip()
                        column_item = QTreeWidgetItem(
                            [
                                self._requisite_title(column) or column_code,
                                "",
                                self._display_requisite_type(column, tabular_part=code),
                            ]
                        )
                        column_item.setData(0, Qt.ItemDataRole.UserRole, column)
                        column_checked = (
                            not has_stored_always or column_binding.casefold() in always_bindings
                        )
                        self._set_requisite_check_state(column_item, column_checked)
                        it.addChild(column_item)

                if obj_type == "document" and not movement_inserted and code.casefold() == "deletionmark":
                    movements = {
                        "code": "Movements",
                        "name": "Movements",
                        "title": {"uk": "Рухи", "en": "Movements"},
                        "type": "collection",
                        "system": True,
                        "pseudo": True,
                    }
                    movement_item = QTreeWidgetItem(
                        [
                            self._requisite_title(movements),
                            "",
                            "(КолекціяРухів)" if get_lang() == "uk" else "(MovementCollection)",
                        ]
                    )
                    movement_item.setData(0, Qt.ItemDataRole.UserRole, movements)
                    self._set_requisite_check_state(
                        movement_item,
                        not has_stored_always or "movements" in always_bindings,
                    )
                    root_item.insertChild(root_item.indexOfChild(it) + 1, movement_item)
                    movement_inserted = True

            for req in self._form_only_requisites(owner_items):
                code = str(req.get("code") or "").strip()
                if not code:
                    continue
                item = QTreeWidgetItem(
                    [self._requisite_title(req) or code, "", self._display_requisite_type(req)]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, req)
                self._set_requisite_check_state(item, code.casefold() in always_bindings)
                self.requisites.addTopLevelItem(item)

            root_item.setExpanded(True)
            self.requisites.scrollToTop()
        finally:
            self.requisites.blockSignals(False)

    def _on_requisite_item_changed(self, _item: QTreeWidgetItem, column: int) -> None:
        if self._ui_guard or int(column) != 1:
            return
        checked: list[str] = []

        def collect(item: QTreeWidgetItem) -> None:
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(payload, dict):
                code = str(payload.get("binding") or payload.get("code") or payload.get("name") or "").strip()
                if code and item.checkState(1) == Qt.CheckState.Checked:
                    checked.append(code)
            for index in range(item.childCount()):
                collect(item.child(index))

        for index in range(self.requisites.topLevelItemCount()):
            collect(self.requisites.topLevelItem(index))
        self._model.root.props["use_always_requisites"] = checked
        self._set_dirty(True)

    def _default_requisite_codes_for_autofill(self, obj_type: str) -> list[str]:
        norm = str(obj_type or "").strip().lower()
        if norm == "catalog":
            return ["Code", "Description"]
        if norm in ("document", "doc"):
            return ["Number", "Date", "Posted", "Comment"]
        if norm in ("information_register", "accumulation_register", "register"):
            return ["Period", "Recorder"]
        reqs = self._available_requisites()
        out: list[str] = []
        for req in reqs:
            code = str(req.get("code") or "").strip()
            if code:
                out.append(code)
            if len(out) >= 3:
                break
        return out

    def _control_type_for_requisite(self, req_type: str) -> str:
        norm = str(req_type or "").strip().lower()
        if norm in ("table", "tabular_part", "table_part"):
            return "Table"
        if norm in ("bool", "boolean") or "bool" in norm:
            return "CheckBox"
        if norm in ("int", "integer", "float", "double", "decimal", "number") or any(
            token in norm for token in ("int", "float", "dec", "num")
        ):
            return "NumberBox"
        if norm in ("date", "datetime", "time") or "date" in norm:
            return "DateBox"
        if norm in ("ref", "reference", "uuid", "guid") or any(token in norm for token in ("ref", "guid", "uuid")):
            return "ComboBox"
        return "TextBox"

    def _default_size(self, control_type: str) -> tuple[int, int]:
        control = str(control_type)
        if control == "Label":
            return (160, 24)
        if control == "Picture":
            return (180, 120)
        if control in ("TextBox", "ComboBox"):
            return (220, 28)
        if control == "TextArea":
            return (320, 120)
        if control == "NumberBox":
            return (160, 28)
        if control == "DateBox":
            return (180, 28)
        if control == "CheckBox":
            return (220, 28)
        if control == "Button":
            return (160, 34)
        if control == "Table":
            return (520, 240)
        if control == "Container":
            return (420, 260)
        if control == "CommandBar":
            return (680, 34)
        if control == "TablePanel":
            return (560, 280)
        if control == "StatusBar":
            return (680, 32)
        return (200, 28)

    def _maybe_autofill_empty_form(self) -> None:
        if not self._is_edit_enabled():
            return

        root = self._model.root
        children = list(root.children or [])
        if children:
            if len(children) == 1 and children[0].type == "Table":
                binding = str(children[0].binding or "").strip()
                cols = (children[0].props or {}).get("columns")
                if not binding and (not isinstance(cols, list) or len(cols) == 0):
                    root.children.clear()
                else:
                    return
            else:
                return

        owner = self._resolve_owner_meta()
        if not owner:
            return
        obj_type = str(owner.get("type") or "").strip().lower()
        reqs = self._available_requisites()
        if not reqs:
            return

        codes = self._default_requisite_codes_for_autofill(obj_type)
        if not codes:
            return

        req_by_code: dict[str, dict[str, Any]] = {}
        for req in reqs:
            code = str(req.get("code") or "").strip()
            if code:
                req_by_code[code] = req

        root.props.setdefault("layout", "absolute")
        root.props.setdefault("w", 1000)
        root.props.setdefault("h", 700)

        x0 = 24
        y = 24
        label_w = 180
        gap = 12

        for code in codes:
            req = req_by_code.get(code)
            if not req:
                continue
            title = self._requisite_title(req)
            control_type = self._control_type_for_requisite(str(req.get("type") or ""))

            lid = self._new_id("Label")
            label = FormNode(id=lid, type="Label", name="Label", title=title)
            lw, lh = self._default_size("Label")
            label.props.update({"x": x0, "y": y, "w": max(label_w, lw), "h": lh})

            cid = self._new_id(control_type)
            ctl = FormNode(id=cid, type=control_type, name=control_type)
            ctl.props["binding"] = code
            cw, ch = self._default_size(control_type)
            ctl_x = x0 + max(label_w, lw) + gap
            ctl.props.update({"x": ctl_x, "y": y - 2, "w": cw, "h": ch})

            root.children.append(label)
            root.children.append(ctl)
            y += max(lh, ch) + 12
            try:
                root.props["h"] = max(int(root.props.get("h") or 0), y + 80)
            except Exception:
                pass

        if root.children:
            self._set_dirty(True)

    def _set_dirty(self, value: bool) -> None:
        if self._dirty == bool(value):
            return
        self._dirty = bool(value)
        self.dirtyChanged.emit(self._dirty)
